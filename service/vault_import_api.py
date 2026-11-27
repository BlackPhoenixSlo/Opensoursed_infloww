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
import read_flip
import relay_host
import vault_ai_api
import vault_cache
import vault_import_decide
import vault_ingest
import vault_upload
from auth import assert_account_owned
from of_client import OFAPIError

log = logging.getLogger("of-relay")

router = APIRouter()


_VAULT_BATCH_PATH = "/api/of/v2/vault/upload/batch"
_VAULT_APPEND_PATH = "/api/of/v2/vault/upload/batch/append"
# A wedge detector, finite: an import that never ends keeps its account live and silences the carrier sweep.
_VAULT_WRITE_GATE_TIMEOUT_S = 30 * 60
# A deadline for the whole mirror write, chunked beneath it: 80 serial OF by-id reads can exceed it, a slow OF then loses the tail not everything.
_VAULT_MIRROR_TIMEOUT_S = 15 * 60
_VAULT_MIRROR_CHUNK = 10
_VAULT_DETAILS_TIMEOUT_S = 60


async def _cap_vault_batch_body(request: Request, call_next):
    if request.method == "POST" and request.url.path in (_VAULT_BATCH_PATH,
                                                         _VAULT_APPEND_PATH):
        refusal = vault_import_decide.batch_body_refusal(
            request.headers.get("content-length"), _measure_stage_room,
            lambda: vault_upload.Limits().checked())
        if refusal is not None:
            status, detail = refusal
            return JSONResponse(status_code=status, content={"detail": detail})
    return await call_next(request)


def _measure_stage_room() -> tuple[int, bool]:
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
    vault_upload.guard_space(0, limits, path=Path(stage_dir))
    own = tempfile.mkdtemp(prefix="f-", dir=stage_dir)
    dest = os.path.join(own, os.path.basename(f.filename or "upload") or "upload")
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
    # Before begin(): a dead-session 503 here would strand the run claim and 409 every later import until restart.
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
    from automation_executor import of_write_paced
    aid = relay_host.current_aid()
    assert_account_owned(aid)
    client = relay_host.get_client()
    fan = await asyncio.to_thread(_vault_resolve_fan, client, fan_username)
    mismatch = vault_import_decide.fan_mismatch(fan, fan_id)
    if mismatch is not None:
        raise HTTPException(status_code=400, detail=mismatch)
    employee_id = None
    if fan is not None:
        from employees import resolve_outbound_employee_id
        employee_id = await resolve_outbound_employee_id(request, aid)
    metas_in = vault_upload.parse_metas(meta)
    # pace_s=0: the write gate already spaces every write for this account.
    limits = vault_upload.Limits(pace_s=0).checked()
    try:
        # Made before the claim, under the spool not TMPDIR: nothing may raise between begin() and the handler that abandons, and the boot sweep owns it.
        vault_upload.STAGE_ROOT.mkdir(parents=True, exist_ok=True)
        stage_dir = tempfile.mkdtemp(prefix="vault-in-",
                                     dir=str(vault_upload.STAGE_ROOT))
    except Exception as e:  # noqa: BLE001 — a spool that cannot be written
        raise HTTPException(status_code=507, detail=str(e))
    try:
        run_id = vault_upload.begin(aid, list_id=int(list_id) if list_id else None,
                                    fan_id=fan["id"] if fan else None,
                                    keep_open=keep_open, stage_dir=stage_dir)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail=str(e))

    links = [s.strip() for s in re.split(r"[\n,]+", drive_links or "") if s.strip()]
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
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            fut.cancel()
            raise

    def _write_gate(thunk):
        return _hop(of_write_paced(aid, thunk, send_purpose="not_fan_dm", operator=True),
                    _VAULT_WRITE_GATE_TIMEOUT_S)

    def _fan_send_gate(thunk, part: int):
        async def _send():
            await relay_host.reject_if_resale(aid, fan["id"], relay_host.send_message_body(text=""))
            def send():
                before_send_at = read_flip.now_ms()
                import send_ops
                if not send_ops.cells():
                    return before_send_at, thunk(), False
                import accounts
                name, target = accounts.get_platform(aid), str(fan["id"])
                result, replay = send_ops.dispatch(
                    name, aid, send_ops.op_id(name, aid, "vault_send", target, run_id, part), "vault_send", target,
                    send_ops.digest({"run_id": run_id, "part": part, "fan": target}), thunk)
                return before_send_at, result, replay

            before_send_at, result, replay = await of_write_paced(aid, send, send_purpose="manual", operator=True)
            if not replay:
                await relay_host.record_fan_send(aid, fan["id"], result, employee_id=employee_id, price=0,
                                                 before_send_at=before_send_at)
            return result
        return _hop(_send(), _VAULT_WRITE_GATE_TIMEOUT_S)

    def _mirror_gate(media_ids: list[int], details: dict[int, dict]) -> dict | None:
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
                return {"applied": 0, "skipped": len(details),
                        "why": "saving them timed out — check the files' "
                               "details in the vault"}
        finally:
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
            with vault_upload.receiving(run_id) as stage_dir:
                dest = await _vault_stage_file(f, stage_dir, limits)
                try:
                    vault_upload.append(run_id, dest,
                                        metas_in[n] if n < len(metas_in) else None)
                except vault_upload.NotTaking:
                    Path(dest).unlink(missing_ok=True)
                    raise
        except vault_upload.NotTaking as e:
            raise HTTPException(status_code=409, detail=str(e))
        except HTTPException:
            raise
        except (RuntimeError, OSError) as e:
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
    try:
        gdrive.api_key()
        drive_import_configured = True
    except gdrive.GDriveError:
        drive_import_configured = False
    limits = vault_upload.Limits(pace_s=0).checked()
    upload_limits = {"max_file_mb": limits.max_bytes // (1024 * 1024),
                     "max_files": limits.max_files}
    details_saved_here = await vault_ingest.has_live_mirror(aid)
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

