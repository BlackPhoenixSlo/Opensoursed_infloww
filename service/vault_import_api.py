"""service/vault_import_api.py — the vault import routes (fan check, batch,
append, Drive listing, status) and the batch upload's body cap, moved out of
server.py (behaviour unchanged).

server.py includes `router` where these routes used to be (route order) and
registers `_cap_vault_batch_body` on its hook chain at the old spot (hook order).
Server globals are read through `relay_host` at call time, never `from server
import`, so a test's `server._get_client = fake` still reaches these routes.
The pure rules (the 411/413 room math, the fan re-check, the per-part details,
the status route's run fields) are `vault_import_decide`'s, called by module
attribute so a fault can patch them; the routes keep the I/O and the card's
own status fields.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

import gdrive
import relay_host
import vault_ai_api
import vault_cache
import vault_import_decide
import vault_ingest
import vault_upload
from auth import assert_account_owned
from of_client import OFAPIError

log = logging.getLogger("of-relay")  # the relay's own logger, as before the move

router = APIRouter()


_VAULT_BATCH_PATH = "/api/of/v2/vault/upload/batch"
# One more file for a run the batch route opened with `keep_open` — the browser
# sends a batch a file at a time so the first is uploading to OnlyFans while
# the rest are still crossing the wire. Capped by the same middleware.
_VAULT_APPEND_PATH = "/api/of/v2/vault/upload/batch/append"
# Ceiling on one import write's wait for the per-account pacer. Generous by
# design — it is a wedge detector, not a policy — but finite: an unbounded wait
# here is an import that never ends, and an import that never ends keeps its
# account marked live, which silences the carrier sweep and its warnings.
_VAULT_WRITE_GATE_TIMEOUT_S = 30 * 60
# Ceiling on the post-import mirror write. The run reports `running` for the
# whole of it (that is the point — see `vault_upload._mirror_landed`), so a
# wedged read here would hold the account's lock open and silence the carrier
# sweep exactly like an unbounded pacer wait would.
#
# It is NOT an order of magnitude above the work, which is what this comment
# used to claim. The honest worst case is `resolve_budget`'s `max_files * 2` —
# 80 landed ids at the default cap, because `_apply_caps` counts only `pending`
# items and a Google Drive memo hit is already `done` before caps run — each one
# a serial OF by-id read. At an OF read timeout in the tens of seconds, 80 of
# those exceed 15 minutes. So the ceiling is a DEADLINE for the whole write and
# the write is chunked underneath it: a slow OF loses the tail rather than the
# whole thing, which matters because a cancelled write is the pre-import grid
# coming back on exactly the largest imports — the symptom the mirror write was
# added to remove.
_VAULT_MIRROR_TIMEOUT_S = 15 * 60
# Ids per hop. Small enough that a chunk's own share of the deadline is a real
# bound, large enough that the loop hop and the commit are amortised.
_VAULT_MIRROR_CHUNK = 10
# Budget for writing an import's per-file details onto the rows that landed. Its
# own, not what the mirror write left over: local DB writes, so seconds, and a
# mirror write that ran out of time must not take the details down with it.
_VAULT_DETAILS_TIMEOUT_S = 60


async def _cap_vault_batch_body(request: Request, call_next):
    """Refuse an oversized batch upload BEFORE anything is written to disk.

    The per-file cap inside the handler is already too late: FastAPI resolves
    the form before the handler body runs, and Starlette spills every part past
    1 MB into TMPDIR. So 60 GB dragged into the browser filled TMPDIR in full
    and only the SECOND copy — into the staging directory — was ever capped. A
    full disk takes SQLite, and with it the whole relay, down.

    The ceiling is what BOTH filesystems involved can hold: Starlette spills the
    parts into TMPDIR and the handler then copies them into
    `vault_upload.STAGE_ROOT` under the spool, so the batch has to fit twice
    when those are the same device and into the tighter of the two when they are
    not. Measuring only TMPDIR — while the staging copy had been moved to the
    spool — passed batches the spool could not hold (aborting 507 only after the
    whole upload had transferred) and, where /tmp is a small tmpfs, rejected
    every batch citing a volume with nothing to do with it.

    A body with no content-length cannot be measured before it is read, and the
    handler's own cap runs too late, so this route requires one.
    """
    if request.method == "POST" and request.url.path in (_VAULT_BATCH_PATH,
                                                         _VAULT_APPEND_PATH):
        refusal = vault_import_decide.batch_body_refusal(
            request.headers.get("content-length"), _measure_stage_room,
            # .checked() so the staging loop's cap matches the run's — an
            # unchecked Limits still carries the raw two-ceiling pair.
            lambda: vault_upload.Limits().checked())
        if refusal is not None:
            status, detail = refusal
            return JSONResponse(status_code=status, content={"detail": detail})
    return await call_next(request)


def _measure_stage_room() -> tuple[int, bool]:
    """The disk side of the body cap: free bytes on TMPDIR and the staging
    root (the tighter), and whether they are one device."""
    tmp_dir = Path(tempfile.gettempdir())
    stage_root = vault_upload.STAGE_ROOT
    try:
        stage_root.mkdir(parents=True, exist_ok=True)
        same_device = os.stat(tmp_dir).st_dev == os.stat(stage_root).st_dev
        free = min(shutil.disk_usage(tmp_dir).free,
                   shutil.disk_usage(stage_root).free)
    except OSError:
        same_device, free = True, shutil.disk_usage(tmp_dir).free
    return free, same_device


_STAGE_CHUNK = 1024 * 1024
_STAGE_FREE_CHECK_EVERY = 64 * _STAGE_CHUNK


async def _vault_stage_file(f: UploadFile, stage_dir: str,
                            limits: "vault_upload.Limits") -> str:
    """Stream one uploaded part into its own sub-directory of `stage_dir`,
    under its per-file cap and the spool's free-space floor. Returns the staged
    path; raises 413 / the guard's RuntimeError, having removed its own partial.

    Its OWN sub-directory, so the staged file keeps the operator's file name
    (the run names its item after it) while two files of the same name — two
    `IMG_0001.jpg` from two phones — can never be the same path. They used to
    be: the later one truncated the earlier while it was still queued, and its
    failure cleanup deleted the earlier one's bytes."""
    vault_upload.guard_space(0, limits, path=Path(stage_dir))
    own = tempfile.mkdtemp(prefix="f-", dir=stage_dir)
    dest = os.path.join(own, os.path.basename(f.filename or "upload") or "upload")
    # The SAME cap rule the Drive path uses: only video ffmpeg can shrink earns
    # the big download ceiling. Applying that ceiling to everything meant a
    # 1.5 GB dragged-in JPEG was streamed to disk in full and then skipped at
    # 200 MB.
    cap = vault_upload.cap_for(f.filename or "", f.content_type, limits)
    written = since_check = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await f.read(_STAGE_CHUNK):
                written += len(chunk)
                since_check += len(chunk)
                if written > cap:
                    raise HTTPException(
                        status_code=413,
                        detail=(f"{f.filename} is over the "
                                f"{cap / 1e6:.0f} MB per-file limit"))
                if since_check >= _STAGE_FREE_CHECK_EVERY:
                    since_check = 0
                    vault_upload.guard_space(0, limits, path=Path(stage_dir))
                out.write(chunk)
    except BaseException:
        shutil.rmtree(own, ignore_errors=True)
        raise
    return dest


def _vault_resolve_fan(client, raw: str) -> dict | None:
    """The fan account the operator typed, as OnlyFans names it:
    `{id, username, name}`, or None when the field was left empty (the carrier
    path). ONE `get_user` — the import card's "check" step and the batch
    route's re-check both come here.

    Only OnlyFans' 404 means "no such account". Anything else (a dead session,
    a 429, a proxy error) is said as itself: calling it "no such account" sent
    operators off to re-type a name that was right."""
    try:
        handle = vault_upload.fan_handle(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not handle:
        return None
    try:
        user = client.get_user(handle)
    except OFAPIError as e:
        code = e.response.status_code if e.response is not None else None
        if code == 404:
            raise HTTPException(status_code=404,
                                detail=f"No OnlyFans account @{handle} — check the username")
        raise HTTPException(status_code=502,
                            detail=f"Could not look up @{handle}: OnlyFans answered {code}")
    except Exception as e:  # noqa: BLE001 — a transport failure, said as one
        raise HTTPException(status_code=502,
                            detail=f"Could not look up @{handle}: {type(e).__name__}: {e}")
    fid = user.get("id") if isinstance(user, dict) else None
    if not fid:
        raise HTTPException(status_code=404,
                            detail=f"No OnlyFans account @{handle} — check the username")
    return {"id": int(fid), "username": str(user.get("username") or handle),
            "name": str(user.get("name") or "")}


@router.get("/api/of/v2/vault/upload/fan")
async def of_vault_upload_fan(username: str):
    """Who a vault import would send to: `{id, username, name}` for the typed
    OnlyFans username (or `@name`, or profile link). Read-only — one profile
    read. The card shows the answer and sends its `id` and `username` back
    with the import, which re-checks them, so a typo can never quietly pick a
    different fan."""
    aid = relay_host.current_aid()
    assert_account_owned(aid)
    client = relay_host.get_client()
    fan = await asyncio.to_thread(_vault_resolve_fan, client, username)
    if fan is None:
        raise HTTPException(status_code=400, detail="no username given")
    return fan


@router.post(_VAULT_BATCH_PATH)
async def of_vault_upload_batch(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    drive_links: str = Form(default=""),
    list_id: str = Form(default=""),
    meta: str = Form(default=""),
    fan_username: str = Form(default=""),
    fan_id: str = Form(default=""),
    keep_open: bool = Form(False),
):
    """Start a batch import into the vault. Returns `{run_id}` immediately.

    Accepts either uploaded files (repeated `files` parts) or `drive_links`
    (newline/comma separated public Google Drive file or folder links), or
    both. `list_id` optionally files everything into a vault folder at the end.

    `meta` is a JSON list of per-file details, one per `files` part in order
    (`{hashtags, tag_creators, notes, price_cents, list_id}`); they are written
    onto each file's mirror row once it lands. `fan_username` + `fan_id` send
    each new file to that fan (Infloww's "Link a fan account") instead of a
    carrier post: both are what `GET …/upload/fan` answered, and the username
    is looked up again here and must still be that id — the operator confirmed
    a person, not a string. `keep_open` leaves the run taking more files from
    `POST …/batch/append` until one of those says `last`.

    The run record is created HERE, synchronously, so the response can name the
    run: the worker starts on a thread and a client that polled before it got
    there used to be told `running: false` and never start polling at all.

    The work itself runs in a worker THREAD, not on the event loop: each file is
    a multi-minute sequence of blocking network calls, and the relay serves every
    other account from this same loop. Poll
    `/api/of/v2/vault/upload/status?run_id=…`.
    """
    import time
    from concurrent.futures import TimeoutError as FuturesTimeout
    # Local import, matching every other automation_executor callsite here —
    # importing it at module scope reintroduces the load cycle its own docstring
    # warns about.
    from automation_executor import of_write_paced
    aid = relay_host.current_aid()
    assert_account_owned(aid)
    # BEFORE `begin`, because it can raise. `_get_client` answers 503 for an
    # account whose OnlyFans session is dead — a first-class state here, with
    # its own columns and its own banner on the vault page — and it used to sit
    # below the staging block, outside the `try` that abandons the run. So the
    # 503 left `_live[aid]` claimed, the lockfile on disk and `run.json` saying
    # `running`, with nothing to release any of it: `begin()` refuses on `_live`
    # unconditionally and there is no stall ceiling on the in-process claim, so
    # every later import for that account answered 409 until the relay was
    # restarted. Restoring the session did not help. Asking for the client while
    # we still hold nothing costs one lookup and cannot strand anything.
    client = relay_host.get_client()
    # Same rule: resolving the linked fan can fail, so it happens while we
    # still hold nothing. And it must be the fan the operator was SHOWN: the
    # card resolved the name first and sends that id back; a mismatch (a
    # different typo, a renamed account) refuses rather than sending.
    fan = await asyncio.to_thread(_vault_resolve_fan, client, fan_username)
    mismatch = vault_import_decide.fan_mismatch(fan, fan_id)
    if mismatch is not None:
        raise HTTPException(status_code=400, detail=mismatch)
    # Who the fan messages are from, for their outbound rows — the same
    # resolution the chat route uses.
    employee_id = None
    if fan is not None:
        from employees import resolve_outbound_employee_id
        employee_id = await resolve_outbound_employee_id(request, aid)
    metas_in = vault_upload.parse_metas(meta)
    # pace_s=0: the write gate below already spaces every write for this
    # account, so the module's own inter-file sleep would only double it. This
    # is the POLICY, stated here — it used to be inferred from whether a gate
    # was passed at all, which silently disabled pacing for any other gate.
    limits = vault_upload.Limits(pace_s=0).checked()
    # The staging dir, made BEFORE the claim. Making it is not staging a byte,
    # and a full, read-only or permission-broken spool volume then fails here,
    # while we hold nothing — between `begin()` and a handler that abandons,
    # NOTHING may raise (the rule stated above `_get_client()`); out there these
    # two calls once left `_live[aid]` claimed, the lockfile on disk and
    # `run.json` saying `running`, a permanent 409 for the account.
    #
    # Under the spool, not TMPDIR: a SIGKILL between staging and the run leaked
    # the whole staged batch, and nothing in a container ever cleans /tmp. Here
    # the boot sweep owns it.
    try:
        vault_upload.STAGE_ROOT.mkdir(parents=True, exist_ok=True)
        stage_dir = tempfile.mkdtemp(prefix="vault-in-",
                                     dir=str(vault_upload.STAGE_ROOT))
    except Exception as e:  # noqa: BLE001 — a spool that cannot be written
        raise HTTPException(status_code=507, detail=str(e))
    # Claim the account BEFORE staging a single byte. `begin` is the only
    # gate: it takes the in-process claim and the cross-process lockfile
    # together, so it also refuses while a CLI import holds the lock. The
    # cheap pre-check that used to live here read the in-process registry
    # only, which meant a 5 GB drag-in was transferred and written to disk
    # in full before the lock refused it -- and, once a wedged run aged past
    # the stall ceiling, it answered 409 to the very re-run the dashboard was
    # telling the operator to start. The staging dir rides on the run's inbox,
    # so an append finds it — and stops finding it — with the run itself.
    try:
        run_id = vault_upload.begin(aid, list_id=int(list_id) if list_id else None,
                                    fan_id=fan["id"] if fan else None,
                                    keep_open=keep_open, stage_dir=stage_dir)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail=str(e))

    links = [s.strip() for s in re.split(r"[\n,]+", drive_links or "") if s.strip()]
    # Spool uploaded bytes to disk here, inside the request, so the client's
    # connection can close; the run itself must not depend on it staying open.
    #
    # Streamed with a running byte count and a free-space check on the STAGING
    # filesystem, which is usually not the spool's: dragging in 60 GB of raw
    # footage used to fill the disk with no cap consulted at all, and a full disk
    # takes SQLite — and with it the whole relay — down, which is the exact
    # outcome this feature's design notes claim to prevent.
    staged: list[str] = []
    try:
        for f in files or []:
            if not f.filename:
                continue
            staged.append(await _vault_stage_file(f, stage_dir, limits))
        metas = vault_import_decide.metas_for_parts(
            [f.filename for f in files or []], metas_in)
        if not staged and not links:
            raise HTTPException(status_code=400, detail="no files and no drive links")
    except HTTPException as e:
        shutil.rmtree(stage_dir, ignore_errors=True)
        vault_upload.abandon(run_id, str(e.detail))
        raise
    except Exception as e:  # noqa: BLE001 — a staging failure is the caller's answer
        shutil.rmtree(stage_dir, ignore_errors=True)
        vault_upload.abandon(run_id, str(e))
        raise HTTPException(status_code=507, detail=str(e))

    loop = asyncio.get_running_loop()

    def _hop(coro, timeout: float):
        """Run one coroutine on the relay's loop from this worker thread, bounded.

        The wait is BOUNDED. `fut.result()` with no timeout meant a wedged
        pacer (or a loop that never got round to us) parked the import thread
        for the life of the process, and an import that never ends keeps its
        account marked live — which silences the sweep and the carrier warnings
        for every one of its older runs.

        Bounding the WAIT is not enough, though. `run_coroutine_threadsafe`
        returns a future whose timeout does not touch the coroutine: a write
        parked in its pacing sleep still goes out when its slot arrives — after
        this call has raised past the `finally` that would have deleted a
        carrier, after the run finished, and after the sweep concluded there
        was nothing scheduled and retired the intent. The post then appears with
        nothing on record tracking it, and publishes on its date. Hence the
        cancel, and hence `vault_upload` treating a timeout as "may still have
        happened" (`carrier_write_pending`, `message_write_pending`).
        """
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            fut.cancel()
            raise

    def _write_gate(thunk):
        """Run one OnlyFans write that reaches NO fan — the carrier create, the
        carrier delete, the final foldering call — through the relay's
        per-account write pacer. The fan send has its own gate below.

        A GATE, not a post factory: none of those writes is described here —
        `of_client` stays the only place that knows what a carrier post is.

        OnlyFans throttles EVERY write per account, so an import that paced only
        its own posts would still crowd an automation's fan message into OF's
        limit. Through the pacer it is spaced like every write, and it goes
        ahead of automation's waiting writes (the operator's tier, ADR 0025):
        those wait one more gap, none is dropped. The
        pacer lives on the event loop; we are on a worker thread, so hop across
        and block this thread (not the loop) until it is our turn. The ceiling
        is far above any real wait: the pacer spaces writes 11 s apart and the
        write itself carries its own network timeouts, so minutes here means
        something is stuck.
        """
        return _hop(of_write_paced(aid, thunk, send_purpose="not_fan_dm", operator=True),
                    _VAULT_WRITE_GATE_TIMEOUT_S)

    def _fan_send_gate(thunk):
        """The linked-fan run's chat message: a real DM to a real fan, so it is
        sent as one. The same pacer as every write, declared as what it is
        (`manual`: the operator picked this fan and confirmed who it is), the
        chat route's resale guard, and the chat route's outbound bookkeeping —
        the `messages` row, the media pin, the chat cache bust — since the
        sender is the only producer of outbound rows."""
        async def _send():
            # Free by construction (`materialize_via_message` sends price 0),
            # so the guard passes today; it runs so that stays the guard's call.
            await relay_host.reject_if_resale(aid, fan["id"], relay_host.send_message_body(text=""))
            result = await of_write_paced(aid, thunk, send_purpose="manual", operator=True)
            await relay_host.record_fan_send(aid, fan["id"], result,
                                             employee_id=employee_id, price=0)
            return result
        return _hop(_send(), _VAULT_WRITE_GATE_TIMEOUT_S)

    def _mirror_gate(media_ids: list[int], details: dict[int, dict]) -> dict | None:
        """Write the ids this run landed into the local mirror, and the
        operator's per-file details onto those rows, BEFORE the run reports
        finished. Returns what became of the details (`{applied, skipped,
        why}`), which the run keeps on its record for the card to show.

        The grid reads the LOCAL mirror the moment the mirror holds any row for
        this account, and an upload only ever reached OnlyFans — so without this
        the file the operator just watched succeed appears in no vault view at
        all until somebody runs a full re-collect.

        It is a `vault_upload` hook rather than something this route does after
        the run because of the ORDER. The card polls the status route and fires
        its cache invalidations on the `running → not running` edge, exactly
        once; a mirror write that lands after that edge is a write nothing
        refetches (the mirror query has a 30 s staleTime, no interval, and
        `refetchOnWindowFocus` is off). Two hundred imported photos then stay
        invisible until the next collect — precisely the failure the mirror
        write was added to fix. `vault_upload` calls this while the run is still
        `running`, so the edge the client watches now comes after the write.

        Same loop-hop as `_write_gate`, for the same reason: `vault_upload.start`
        is on a worker thread and `ingest_ids` needs the relay's loop (and its DB
        session).

        CHUNKED under one deadline — see `_VAULT_MIRROR_TIMEOUT_S`, which can be
        smaller than the work it bounds. One 80-id write that runs out of time
        loses ALL of it (`fut.cancel()` does not stop the coroutine, so the rows
        land later, after the edge nothing refetches — the pre-import grid, back
        on the largest imports). Chunked, the same slow OF loses only the tail,
        and everything before it is in the mirror before the run reports
        finished. The details then go onto whichever rows DID land, on a budget
        of their own: a mirror write that ran out of time is no reason to drop
        the hashtags of the files it did write.

        The server-side listing cache is dropped here too, and unconditionally,
        because it is the SAME ordering rule applied to the other cache — and it
        matters most for the account `ingest_ids` stands aside for. An account
        that was never collected has no mirror, so its only view of the import is
        `/api/of/v2/vault/media`, which is served out of `vault_cache` on a 24 h
        TTL to a client whose `vault-media` staleTime is three days with
        `refetchOnWindowFocus` off. Dropping it in `_drive`'s `finally` — after
        `start` published `done` — leaves a refetch that beats the drop by a
        millisecond showing the pre-import listing for a day. `_drive` keeps its
        invalidate as belt-and-braces for the run that never reached this hook.
        """
        ids = list(media_ids)
        deadline = time.monotonic() + _VAULT_MIRROR_TIMEOUT_S
        try:
            for i in range(0, len(ids), _VAULT_MIRROR_CHUNK):
                left = deadline - time.monotonic()
                if left <= 0:
                    log.warning("vault mirror write ran out of time with %d of "
                                "%d ids unwritten", len(ids) - i, len(ids))
                    break
                try:
                    _hop(vault_ingest.ingest_ids(
                        aid, ids[i:i + _VAULT_MIRROR_CHUNK], client), left)
                except FuturesTimeout:
                    log.warning("vault mirror write timed out with %d of %d ids "
                                "unwritten", len(ids) - i, len(ids))
                    break
            if not details:
                return None
            try:
                return _hop(vault_ai_api.apply_import_meta(aid, details),
                            _VAULT_DETAILS_TIMEOUT_S)
            except FuturesTimeout:
                # Said on the run, not only in the log: the card shows it.
                return {"applied": 0, "skipped": len(details),
                        "why": "saving them timed out — check the files' "
                               "details in the vault"}
        finally:
            # Its own `finally`, and not conditional on the ingest: a chunk that
            # timed out or raised still leaves a stale listing behind, and the
            # media IS on OnlyFans either way.
            try:
                _hop(vault_cache.invalidate(aid), 30)
            except Exception as e:  # noqa: BLE001 — never mask the run's outcome
                log.warning("vault_cache: invalidate-before-finish failed: %s", e)

    def _run():
        try:
            return vault_upload.start(aid, client=client, local_paths=staged,
                                      drive_links=links, gate=_write_gate,
                                      send_gate=_fan_send_gate if fan else None,
                                      run_id=run_id, limits=limits,
                                      on_landed=_mirror_gate, metas=metas,
                                      list_id=int(list_id) if list_id else None)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

    async def _drive():
        try:
            await asyncio.to_thread(_run)
        except Exception:
            log.exception("vault batch upload failed")
            vault_upload.abandon(run_id, "the import worker died before it started")
        finally:
            # Its own `finally`, not a sibling `except Exception`: the relay
            # shutting down mid-run cancels this task, and `CancelledError` is a
            # BaseException — it would have walked straight past an `except
            # Exception` and left the server-side TTL cache serving the
            # PRE-import listing until it aged out on its own.
            try:
                await vault_cache.invalidate(aid)
            except Exception as e:  # noqa: BLE001 — never mask the run's own outcome
                log.warning("vault_cache: invalidate-after-batch failed: %s", e)

    relay_host.spawn_bg(_drive(), "vault-import")
    return {"run_id": run_id, "started": True,
            "files": len(staged), "drive_links": len(links)}


@router.post(_VAULT_APPEND_PATH)
async def of_vault_upload_batch_append(
    run_id: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    meta: str = Form(default=""),
    last: bool = Form(False),
):
    """Hand a run opened with `keep_open` its next file(s). `last` says that
    was everything (it may come with no file). 409 once the run has stopped
    taking files — it finished, failed, or sat idle past `OPEN_IDLE_S`."""
    aid = relay_host.current_aid()
    assert_account_owned(aid)
    state = (vault_upload.read_state(run_id)
             if re.fullmatch(r"[\w.-]+", run_id or "") else None)
    if state is None or str(state.get("account_id")) != str(aid):
        raise HTTPException(status_code=404, detail="no such import for this account")
    limits = vault_upload.Limits(pace_s=0).checked()
    metas_in = vault_upload.parse_metas(meta)
    taken = 0
    for n, f in enumerate(files or []):
        if not f.filename:
            continue
        try:
            # Held open for the transfer: the run does not idle out under a
            # large file, and the staging dir is the run's own.
            with vault_upload.receiving(run_id) as stage_dir:
                dest = await _vault_stage_file(f, stage_dir, limits)
                try:
                    vault_upload.append(run_id, dest,
                                        metas_in[n] if n < len(metas_in) else None)
                except vault_upload.NotTaking:
                    # Stopped listening while this file crossed the wire: it
                    # is ours to drop, and the operator's to re-send.
                    Path(dest).unlink(missing_ok=True)
                    raise
        except vault_upload.NotTaking as e:
            raise HTTPException(status_code=409, detail=str(e))
        except HTTPException:
            raise
        except (RuntimeError, OSError) as e:      # the disk floor, or the disk
            raise HTTPException(status_code=507, detail=str(e))
        taken += 1
    closed = vault_upload.close(run_id) if last else False
    return {"run_id": run_id, "files": taken, "closed": closed}


@router.get("/api/of/v2/vault/upload/drive/list")
async def of_vault_drive_list(link: str):
    """What a public Drive folder (or file) link would import, before importing
    it: each file's name, size, whether it can be imported, and the hashtags
    its folder path gives it. Read-only — it lists, it downloads nothing.
    `max_files` is how many of them one import takes."""
    aid = relay_host.current_aid()
    assert_account_owned(aid)
    limits = vault_upload.Limits(pace_s=0).checked()
    try:
        found = await asyncio.to_thread(
            gdrive.resolve, [link], max_files=vault_upload.resolve_budget(limits))
    except gdrive.GDriveError as e:
        raise HTTPException(status_code=400, detail=gdrive.redact(str(e)))
    out = []
    for f in found:
        ok, why = gdrive.is_uploadable(f)
        out.append({"name": f.name, "size": f.size, "mime_type": f.mime_type,
                    "folders": list(f.folders),
                    "hashtags": (vault_upload.drive_meta(f) or {}).get("hashtags", []),
                    "importable": ok, "reason": why or None})
    return {"files": out, "max_files": limits.max_files}


@router.get("/api/of/v2/vault/upload/status")
async def of_vault_upload_status(run_id: str | None = None):
    """Progress for the current (or named) batch. Safe to poll every ~2s.

    A run whose relay restarted mid-flight reports `interrupted` rather than a
    forever-`running` lie, and `running` describes THIS run, not the account, so
    an old run does not read as live because a new one is.

    Every field here that turns on liveness — the run's status and both carrier
    warnings — is `vault_upload._run_is_live` answering, once. It used to be two
    different answers: this payload could report a CLI import as "interrupted"
    (the dashboard renders that as "the relay restarted mid-run") while
    suppressing its carrier warnings in the same breath BECAUSE the account was
    busy.
    """
    aid = relay_host.current_aid()
    assert_account_owned(aid)
    # Whether the Drive import is on, for the card's Drive section: the key's
    # own reader answers (store first, then environment), so a paste in
    # Settings -> AI keys shows on the next poll with no restart. One deployment-wide
    # boolean on every answer; the key and any hint of it stay here.
    try:
        gdrive.api_key()
        drive_import_configured = True
    except gdrive.GDriveError:
        drive_import_configured = False
    # This server's own upload limits, the ones the batch route enforces, for
    # the card's rules row (in place of Infloww's 4 GB / 100 MB / pixel rules).
    limits = vault_upload.Limits(pace_s=0).checked()
    upload_limits = {"max_file_mb": limits.max_bytes // (1024 * 1024),
                     "max_files": limits.max_files}
    # Whether per-file details (hashtags, notes, price, tagged creators) can be
    # kept for this account at all: they live on its vault mirror rows, and an
    # account never synced here has none — the card labels those columns.
    details_saved_here = await vault_ingest.has_live_mirror(aid)
    # ONE walk of the spool per request: the latest run and the account-wide
    # carrier roll-up used to scan and re-parse every run.json separately, twice
    # over, for every 2.5s poll of every open tab. OFF the event loop, too — it
    # reads every run.json and, while another process holds an import lock, asks
    # the OS about that process, which on a non-Linux host forks `ps`.
    def _roll_up():
        runs = vault_upload.account_runs(aid)
        state = (vault_upload.read_state(run_id) if run_id
                 else vault_upload.latest_of(runs))
        return state, vault_upload.carriers_outstanding(aid, runs)

    try:
        state, carriers = await asyncio.to_thread(_roll_up)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad run id")
    card = {"drive_import_configured": drive_import_configured,
            "upload_limits": upload_limits,
            "details_saved_here": details_saved_here}
    if state is None:
        return {"running": False, "run": None, **card}
    if str(state.get("account_id")) != str(aid):
        raise HTTPException(status_code=403, detail="not your run")
    return {**vault_import_decide.status_body(
        state, vault_upload.ITEM_STATUSES, carriers), **card}

