"""service/vault_of_folders.py — the vault's OF-folder writes and the folder plan.

Split out of `vault_ai_api` (routes unchanged): duplicate review + hide, the
AI folder plan (preview / apply / mirror to OF / publish one folder), and the
direct OF folder CRUD (create / add / remove / rename / delete / sort), plus
`_reject_foreign_media`, the guard in front of the id-forwarding OF writes.
Pure decisions live in `vault_of_folders_decide`.

Two routers, one per block, because `vault_ai_api` includes each at the spot the
block used to occupy — FastAPI matches routes in registration order. This module
never imports `vault_ai_api` (one-way dependency, no cycle); `vault_ai_api`
re-exports the moved routes, helpers and hide caps as the same objects (not
the `_PAGE*` read-back paging constants, which are this module's own).

The OF client is reached as `ax._make_client(...)` at call time (tests assign
it). Calls to `_reject_foreign_media` are looked up HERE, so patch
`vault_of_folders._reject_foreign_media`, not the re-export.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import delete, func, select, update

import automation_executor as ax  # _make_client seam (same one automations use)
import vault_cache
import vault_dupes
import vault_scripts
from auth import assert_account_owned
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem
from vault_of_folders_decide import chunks, hide_selection, next_folder_ids, parse_folder_ids, too_many

# Same logger name as before the split, so log routing/filters are unchanged.
log = logging.getLogger("of-relay.vault_ai_api")

# GET duplicates, GET folder-plan, POST folders/{id}/publish, POST folder-plan/apply
plan_router = APIRouter()
# POST duplicates/hide, POST of-folders, POST of-folders/{id}/add|remove|rename,
# DELETE of-folders/{id}, POST of-folders/sort
of_router = APIRouter()

# OF list read-back paging (`_read_of_list_members`), owned here.
_PAGE = 100                # OF vault/media caps limit at 100
_MAX_PAGES = 200          # 20k-item backstop so a stuck hasMore can't loop forever
_PAGE_SLEEP_S = 0.15      # pacing: automations bypass the relay's priority lane

# Blast-radius guard: one HTTP request can only ever remove this many. Bigger
# selections are batched by the client (a 2.3k-item vault yields ~700 copies),
# which also gives the operator a progress readout instead of one long stall.
_MAX_HIDE_PER_CALL = 500
# Ids per OF PUT — keeps a single /vault/media/hidden body bounded, and makes a
# failure cost one chunk instead of the whole batch.
_OF_HIDE_CHUNK = 100
# Ids per SQL IN(...) — stays well clear of SQLite's bound-parameter ceiling.
_DB_IN_CHUNK = 200


@plan_router.get("/admin/vault-ai/duplicates")
async def list_duplicates(
    account_id: str = Query(...),
    threshold: int = Query(vault_dupes.DEFAULT_THRESHOLD),
    limit: int = Query(200),
) -> dict[str, Any]:
    """Duplicate sets for the review UI. Each set is {original, dupes[]} where
    `original` is the EARLIEST-uploaded copy (kept) and `dupes` are removal
    candidates. Read-only — nothing is hidden until /duplicates/hide is called.

    Thumbs come from the existing /admin/vault-ai/thumb route, so the client
    renders both sides of every pair before the operator confirms.
    """
    assert_account_owned(account_id)
    res = await vault_dupes.find_duplicates(account_id, threshold)

    def _slim(r: dict, **extra: Any) -> dict[str, Any]:
        return {
            "media_id": r["media_id"], "kind": r["kind"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "duration_seconds": r["duration"], "send_count": r["send_count"],
            **extra,
        }

    clusters = [
        {
            "original": _slim(c["original"]),
            "dupes": [_slim(d, dhash_dist=d["dhash_dist"],
                            ahash_dist=d["ahash_dist"], exact=d["exact"],
                            band=vault_dupes.band_of(
                                max(d["dhash_dist"], d["ahash_dist"])))
                      for d in c["dupes"]],
            "band": c["band"], "worst": c["worst"], "all_exact": c["all_exact"],
            "sent_dupes": sum(1 for d in c["dupes"] if d["send_count"] > 0),
        }
        for c in res["clusters"][:max(1, int(limit))]
    ]
    return {**{k: v for k, v in res.items() if k != "clusters"},
            "account_id": account_id,
            "returned": len(clusters), "clusters": clusters}


@plan_router.get("/admin/vault-ai/folder-plan")
async def get_folder_plan(
    account_id: str = Query(...),
    keep: int = Query(2, ge=0, le=20),
    solo: bool = Query(False),
) -> dict[str, Any]:
    """PREVIEW the folders the pipeline would create. Read-only, free, instant —
    no LLM, no OF traffic, nothing written. This is what the vault button shows
    before the operator confirms.

    `solo` adds a `-solo` cut of each lane, keeping only the items nobody else
    is in."""
    assert_account_owned(account_id)
    return await vault_scripts.plan_ai_folders(account_id, keep=keep, solo=solo)


async def _read_of_list_members(client, of_list_id: int) -> set[int]:
    """Every media id OF currently reports in ONE list.

    Membership is taken from OF rather than from the plan we just sent, because
    `add_media_to_vault_list` only ADDS: a list carries the union of every
    generation of the rules that has ever run. OF is the only thing that knows
    what is actually in there, so the mirror is made to agree with OF, not with
    our intent.
    """
    live: set[int] = set()
    offset = 0
    for _ in range(_MAX_PAGES):
        resp = await asyncio.to_thread(
            client.vault_media, limit=_PAGE, offset=offset,
            type="all", list_id=int(of_list_id),
        )
        rows = (resp or {}).get("list") or []
        if not rows:
            break
        for m in rows:
            if m.get("id") is not None:
                live.add(int(m["id"]))
        if len(rows) < _PAGE:
            break
        offset += _PAGE
        await asyncio.sleep(_PAGE_SLEEP_S)
    return live


async def _apply_list_membership(
    account_id: str, live_by_list: dict[int, set[int]],
) -> int:
    """Rewrite the mirror's per-item `of_folder_ids` for EVERY list we pushed,
    in ONE pass over the vault.

    Without this, mirroring is invisible in the UI. Item→folder membership is
    written ONLY by a full collect (it is parsed from `listStates` on each media
    dict), so a folder we just pushed to OF exists there but no cached item
    claims to be in it — the picker asks "who is in list X", gets nothing, and
    honestly renders "No media in this filter" while the dropdown, which counts
    from OF, says 4. Real on OF, invisible locally.

    This ran PER FOLDER once, and each run re-loaded every VaultItem for the
    account: 12 folders on a 1600-item vault meant ~20k ORM hydrations and 12
    commits inside the request the operator is sitting in front of. The item set
    is identical every time — only the list id differs — so the loads collapse
    into one. Both directions are still written, ids gained AND ids dropped, or
    a folder that shrinks would keep its stale members in the picker forever.
    """
    if not live_by_list:
        return 0
    touched = 0
    async with get_session() as s:
        items = (await s.execute(
            select(VaultItem).where(VaultItem.account_id == account_id)
        )).scalars().all()
        for item in items:
            before = parse_folder_ids(item.of_folder_ids)
            ids = next_folder_ids(before, item.media_id, live_by_list)
            if ids != before:
                item.of_folder_ids = json.dumps(ids)
                touched += 1
        await s.commit()
    return touched


async def _push_folder_to_of(
    client, folder_id: int, name: str, media_ids: list[int],
) -> dict[str, Any]:
    """Create-or-reuse ONE internal folder's OF vault list and add its media.

    The single place that turns a `VaultFolder` into a real OnlyFans list —
    shared by the generated-folder pipeline (`_mirror_ai_folders_to_of`, which
    loops it) and by the operator's per-folder publish button, because they are
    the same three calls and drifting them apart is how one of them quietly
    stops binding `of_list_id`.

    Ordering is load-bearing: the id is bound BEFORE the media add, so a failed
    add leaves a re-run topping up the SAME list rather than minting a second one
    with the same name (the 2026-07-28 symptom of two `AI-` folders sitting with
    a NULL `of_list_id`).

    Raises on failure — the caller decides whether that costs one folder or the
    whole request. Never rolls back the internal folder: a folder that exists
    locally but not on OF is recoverable, losing the grouping is not.
    """
    async with get_session() as s:
        folder = await s.get(VaultFolder, folder_id)
        of_list_id = folder.of_list_id if folder else None

    created = False
    if not of_list_id:
        res = await asyncio.to_thread(client.create_vault_list, name[:120])
        of_list_id = (res or {}).get("id")
        if not of_list_id:
            raise RuntimeError(f"OF returned no list id: {str(res)[:120]}")
        created = True
        async with get_session() as s:
            await s.execute(
                update(VaultFolder)
                .where(VaultFolder.id == folder_id)
                .values(of_list_id=int(of_list_id))
            )
            await s.commit()

    if media_ids:
        await asyncio.to_thread(client.add_media_to_vault_list, int(of_list_id), media_ids)
    return {"of_list_id": int(of_list_id), "created": created}


async def _mirror_ai_folders_to_of(
    account_id: str, created: list[dict[str, Any]], plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Push the just-built internal folders out as REAL OF vault lists.

    This is the only part of the pipeline that writes to her OnlyFans account,
    which is why it is opt-in per request rather than implied by "apply".

    Binds `VaultFolder.of_list_id` on success so a re-run ADDS to the same OF
    list instead of creating a second one with the same name. A folder that
    already carries an `of_list_id` is reused. Failures are reported per folder
    and never roll back the internal folder — a folder that exists locally but
    not on OF is recoverable; losing the grouping is not.

    Runs in two phases, and the ORDER is the point. Phase 1 is every write that
    changes her OnlyFans account; phase 2 only re-READS what we just wrote so
    the local picker agrees with it. They used to be interleaved per folder,
    which made the cheap cosmetic read-back a barrier in front of the next
    folder's create: on a 12-folder plan the request ran for minutes, the proxy
    in front of the relay gave up, and the browser showed a bare "Internal
    Server Error" while the relay had logged nothing at all (a client
    disconnect cancels the handler with `CancelledError`, which is a
    BaseException and so is invisible to the `except Exception` that records
    server errors). The folders that hadn't been reached yet simply never got
    made — the 2026-07-28 symptom of two `AI-` folders sitting with a NULL
    `of_list_id`, and of "sometimes it works": a small plan finished inside the
    timeout, a big one didn't.

    Split, a request cut short still leaves every folder REAL on OF with its
    media in it. Only the read-back is lost, and a re-run (or any collect)
    restores that.
    """
    by_name = {f["name"]: f for f in plan.get("folders") or []}
    client = await asyncio.to_thread(ax._make_client, account_id)
    out: list[dict[str, Any]] = []

    # ── Phase 1: the writes ──────────────────────────────────────────
    for made in created:
        spec = by_name.get(made["name"])
        media_ids = [int(i["media_id"]) for i in (spec or {}).get("items") or []]
        try:
            pushed = await _push_folder_to_of(
                client, made["folder_id"], made["name"], media_ids)
            out.append({**made, "of_list_id": pushed["of_list_id"],
                        "of_added": len(media_ids)})
        except Exception as e:  # noqa: BLE001
            log.warning("OF mirror failed folder=%s name=%s",
                        made["folder_id"], made["name"], exc_info=True)
            out.append({**made, "of_error": str(e)[:200]})

    # ── Phase 2: the read-back, off the request ──────────────────────
    # Detached for the same reason Collect and the flags sweep are: it is one
    # OF page per 100 items across every list, and holding the operator's
    # request open for it is what made a 12-folder plan 500. Her account is
    # already correct when this starts, so nothing here can fail in a way that
    # costs a folder.
    list_ids = [int(r["of_list_id"]) for r in out if r.get("of_list_id")]
    if list_ids:
        asyncio.create_task(_readback_membership(client, account_id, list_ids))
    return out


async def _readback_membership(client, account_id: str, list_ids: list[int]) -> int:
    """Make the mirror agree with OF about who is in the lists we just pushed.

    Runs detached, so it owns its own error handling — an exception escaping a
    bare `create_task` is only ever seen as an "exception was never retrieved"
    warning at GC time.
    """
    live_by_list: dict[int, set[int]] = {}
    for lid in list_ids:
        try:
            live_by_list[lid] = await _read_of_list_members(client, lid)
        except Exception:  # noqa: BLE001
            log.warning("OF membership read-back failed list=%s", lid, exc_info=True)
    try:
        synced = await _apply_list_membership(account_id, live_by_list)
        log.info("mirror membership synced account=%s items=%s lists=%s",
                 account_id, synced, len(live_by_list))
        return synced
    except Exception:  # noqa: BLE001
        log.warning("mirror membership write failed account=%s", account_id,
                    exc_info=True)
        return 0


@plan_router.post("/admin/vault-ai/folders/{folder_id}/publish")
async def publish_folder_to_of(folder_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Push ONE hand-made internal folder out as a REAL OF vault list.

    `_mirror_ai_folders_to_of` does this for folders the `vault_scripts` pipeline
    just generated, and only those: `/folder-plan/apply` RE-DERIVES the plan and,
    by its own docstring, "a folder the operator made by hand is never touched".
    So a hand-curated rung had no way out to OF at all. This is that way out —
    the same `_push_folder_to_of` primitive, called once instead of in a loop.

    ⚠️ **Publish is ADDITIVE, never subtractive.** `add_media_to_vault_list` only
    adds and OF has no remove-one-media call; a rebuild is
    delete(`clear_media=False`) → create → add, which mints a NEW `of_list_id`.
    So an item removed from the internal folder stays on OF until a rebuild.
    Rather than diverge silently, the read-back diffs both sides and reports
    `stale_on_of` — an empty list means the copy is exact.

    Send order: members are pushed in `manual_order` (the operator's rank, NULLs
    last), but OF holds its own in-list order and we do not claim it honours
    ours. Rank is read from `vault_folder_items` at send time, not from OF.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)

    async with get_session() as s:
        folder = await s.get(VaultFolder, folder_id)
        if folder is None or folder.account_id != account_id or folder.deleted_at is not None:
            raise HTTPException(status_code=404, detail={"error": "folder_not_found"})
        name = folder.name
        members = [int(m) for m in (await s.execute(
            select(VaultFolderItem.media_id)
            .where(
                VaultFolderItem.account_id == account_id,
                VaultFolderItem.folder_id == folder_id,
            )
            .order_by(
                VaultFolderItem.manual_order.is_(None),
                VaultFolderItem.manual_order,
                VaultFolderItem.media_id,
            )
        )).scalars().all()]

    if not members:
        # An empty OF list is noise in her vault and tells the operator nothing.
        raise HTTPException(status_code=400, detail={"error": "folder_empty"})

    # These ids came out of the DB, not off the wire — and they are checked
    # anyway, because /folders/{id}/add wrote them there from the wire. A folder
    # poisoned while the unguarded version was live is still sitting on disk
    # with another model's ids in it, carrying this account's `account_id`, and
    # this is the last point before they are posted to her OnlyFans list.
    #
    # Refused whole rather than filtered down: the other guarded routes refuse
    # the batch, silently publishing a subset is a folder whose contents nobody
    # can account for, and the refusal names the offending ids so the operator
    # can drop them with /folders/{id}/remove and publish again.
    await _reject_foreign_media(account_id, members)

    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        pushed = await _push_folder_to_of(client, folder_id, name, members)
    except Exception as e:  # noqa: BLE001
        log.warning("publish failed account=%s folder=%s", account_id, folder_id,
                    exc_info=True)
        raise HTTPException(status_code=502, detail={
            "error": "of_publish_failed", "detail": str(e)[:300]}) from None

    of_list_id = pushed["of_list_id"]

    # Read back INLINE, unlike the 12-folder pipeline whose read-back timed out
    # the proxy: one list is a single OF page, and the operator needs the
    # `stale_on_of` diff in the response to know whether the publish was exact.
    # Cosmetic either way — her account is already correct when this starts.
    synced = 0
    stale_on_of: list[int] = []
    try:
        live = await _read_of_list_members(client, of_list_id)
        stale_on_of = sorted(live - set(members))
        synced = await _apply_list_membership(account_id, {of_list_id: live})
    except Exception:  # noqa: BLE001
        log.warning("publish read-back failed account=%s folder=%s list=%s",
                    account_id, folder_id, of_list_id, exc_info=True)

    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass

    return {
        "account_id": account_id,
        "folder_id": folder_id,
        "name": name,
        "of_list_id": of_list_id,
        "created": pushed["created"],
        "pushed": len(members),
        "synced": synced,
        "stale_on_of": stale_on_of,
    }


@plan_router.post("/admin/vault-ai/folder-plan/apply")
async def apply_folder_plan(payload: dict = Body(...)) -> dict[str, Any]:
    """Create the previewed folders and fill them, in send order.

    Requires `confirm: true` — there is no path that creates folders from a
    single click. The plan is RE-DERIVED here rather than taken from the body,
    so a preview the operator left open for ten minutes cannot write a stale
    grouping; the worst case is that they get the current answer.

    Folders are internal and prefixed `AI-`; re-running refreshes the same ones
    instead of duplicating them, and a folder the operator made by hand is never
    touched.

    `mirror_to_of` additionally creates them as REAL OF vault lists. That is the
    ONLY write to her OnlyFans account in this pipeline, so it is opt-in per
    request and never implied by `confirm` alone. Nothing is ever SENT either
    way.

    `solo` must match what the preview was showing. It is part of what the plan
    IS, and `apply_ai_folders` retires generated folders the current plan no
    longer makes — so applying without it after previewing with it would create
    the lanes and retire every `-solo` folder in the same call.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    keep = int(payload.get("keep") or 2)
    solo = bool(payload.get("solo"))
    plan = await vault_scripts.plan_ai_folders(account_id, keep=keep, solo=solo)
    result = await vault_scripts.apply_ai_folders(account_id, plan)

    if payload.get("mirror_to_of"):
        result["created"] = await _mirror_ai_folders_to_of(
            account_id, result["created"], plan)
        result["of_mirrored"] = sum(1 for c in result["created"] if c.get("of_list_id"))
        result["of_failed"] = sum(1 for c in result["created"] if c.get("of_error"))

    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {"account_id": account_id, **result, "summary": plan["summary"]}


@of_router.post("/admin/vault-ai/duplicates/hide")
async def hide_duplicates(payload: dict = Body(...)) -> dict[str, Any]:
    """Remove confirmed duplicate copies from the REAL OF vault.

    This calls OF's own "Remove selected items from vault" path
    (`PUT /vault/media/hidden`) — the media is hidden, not destroyed, so
    anything already attached to a sent PPV or a live post keeps working. OF
    exposes no unhide, so the UI must confirm before calling this.

    Guards, all enforced server-side because the client's set can be stale:
      · every id is re-clustered NOW and must still be a DUPE — an id that is
        the ORIGINAL of its set is refused, so the keeper can never be hidden;
      · ids not in any duplicate set at the current threshold are refused;
      · copies with send_count > 0 are skipped unless `allow_sent` is set;
      · at most `_MAX_HIDE_PER_CALL` ids per request.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    media_ids = [int(x) for x in (payload.get("media_ids") or [])
                 if str(x).lstrip("-").isdigit()]
    if not media_ids:
        raise HTTPException(status_code=400,
                            detail={"error": "media_ids_required"})
    over = too_many(media_ids, _MAX_HIDE_PER_CALL)
    if over:
        raise HTTPException(status_code=400, detail=over)
    allow_sent = bool(payload.get("allow_sent"))
    threshold = int(payload.get("threshold") or vault_dupes.DEFAULT_THRESHOLD)

    # Re-derive the truth rather than trusting the payload's classification.
    res = await vault_dupes.find_duplicates(account_id, threshold, rehash=False)
    approved, refused = hide_selection(media_ids, res["clusters"], allow_sent)

    # Send OF a bounded body per call rather than one giant mediaIds array, and
    # treat each chunk as independently durable: if a later chunk fails, the
    # ones already hidden ARE hidden on OF, so they must still be recorded
    # locally and reported — silently 502-ing the whole request would leave the
    # mirror claiming media that is actually gone.
    done: list[int] = []
    of_error: str | None = None
    if approved:
        client = await asyncio.to_thread(ax._make_client, account_id)
        for chunk in chunks(approved, _OF_HIDE_CHUNK):
            try:
                await asyncio.to_thread(client.hide_vault_media, chunk)
            except Exception as e:  # noqa: BLE001
                of_error = str(e)[:300]
                log.warning("vault dupes hide chunk failed account=%s at=%s",
                            account_id, len(done), exc_info=True)
                break
            done.extend(chunk)
        if not done:
            raise HTTPException(status_code=502, detail={
                "error": "of_hide_failed", "detail": of_error,
                "attempted": len(approved)})
        # Mirror the removal locally so the grid, the picker, the describe
        # sweep and every automation stop seeing the copies immediately —
        # without waiting for the next collect to notice they're gone.
        now = datetime.utcnow()
        async with get_session() as s:
            for part in chunks(done, _DB_IN_CHUNK):
                await s.execute(
                    update(VaultItem)
                    .where(VaultItem.account_id == account_id,
                           VaultItem.media_id.in_(part))
                    .values(removed_at=now)
                )
            await s.commit()
        try:
            await vault_cache.invalidate(account_id)
        except Exception:  # noqa: BLE001
            pass
        log.info("vault dupes hidden account=%s n=%s", account_id, len(done))
    hidden = len(done)

    out: dict[str, Any] = {
        "account_id": account_id, "hidden": hidden,
        "hidden_ids": done,
        "refused": {k: v for k, v in refused.items() if v},
    }
    if of_error:
        # Partial success: report what OF actually took and what it didn't, so
        # the UI can re-offer the remainder instead of double-counting.
        out["of_error"] = of_error
        out["not_hidden"] = approved[len(done):]
    return out


async def _reject_foreign_media(account_id: str, media_ids: list[int]) -> None:
    """Refuse media ids that are not this account's, BEFORE they reach OnlyFans.

    The routes that take client-supplied `media_ids` used to check only that the
    caller owned the ACCOUNT — never that the media belonged to it. That made an
    ordinary stale browser tab into a real write against the wrong creator: the
    vault manager carried its selection across a model switch, so thirty ids
    picked while looking at one model were posted into the next model's OF
    folder, over that model's session, with the relay forwarding them verbatim.
    The UI bug is fixed (the panel remounts per model), but "the client will
    always be right about which model it is on" is exactly the assumption that
    was already wrong once, and OF's folder-add and hide are not undoable.

    Called from FIVE places across two modules, and the list is the contract —
    grep it before adding a route that forwards ids:

        vault_of_folders  of-folders              create an OF folder with media in it
        vault_of_folders  of-folders/{id}/add     add media to an existing OF folder
        vault_of_folders  of-folders/{id}/remove  take media out of an OF folder
        vault_of_folders  folders/{id}/publish    sends ids stored in `vault_folder_items`
        vault_ai_api      items/{id}/hide         OF's "remove from vault" (no unhide)

    publish forwards ids read back from `vault_folder_items`, under this
    account's id, so every ownership check downstream passes; those rows may
    predate this guard (the old `folders/{id}/add` route wrote them from the
    wire), so publish re-checks them before posting to her real vault list.

    Routes that do NOT need this, deliberately: `hide_duplicates` and the flags
    sweep re-derive their ids from the mirror; `reorder` only ever narrows what
    is already stored; `describe` reads.

    The escape hatch is deliberate: an account with NO mirror at all has never
    been collected, its grid is served straight from OnlyFans, and this function
    knows nothing about its media. Refusing there would break foldering for every
    uncollected account to guard against a case it cannot detect.
    """
    if not media_ids:
        return
    async with get_session() as s:
        known = set((await s.execute(
            select(VaultItem.media_id).where(
                VaultItem.account_id == account_id,
                VaultItem.media_id.in_(media_ids),
            )
        )).scalars().all())
        if not known:
            collected = await s.scalar(
                select(func.count()).select_from(VaultItem)
                .where(VaultItem.account_id == account_id)
            )
            if not collected:
                return
    foreign = [m for m in media_ids if m not in known]
    if foreign:
        log.warning("vault: refused %d media not in account=%s mirror (%s…)",
                    len(foreign), account_id, foreign[:5])
        raise HTTPException(status_code=404, detail={
            "error": "not_in_mirror",
            "detail": ("these media are not in this model's vault — the page was "
                       "probably showing another model when they were selected"),
            "media_ids": foreign[:20],
        })


@of_router.post("/admin/vault-ai/of-folders")
async def create_of_folder(payload: dict = Body(...)) -> dict[str, Any]:
    """Create a REAL OF vault folder (POST /vault/lists) and optionally add the
    selected media. Invalidates the vault cache so the new folder shows at once."""
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail={"error": "name_required"})
    media_ids = [int(x) for x in (payload.get("media_ids") or []) if str(x).lstrip("-").isdigit()]
    # Before the folder is created, not after: a refusal that leaves an empty
    # folder behind on her OnlyFans is still litter the operator has to clear.
    await _reject_foreign_media(account_id, media_ids)
    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        folder = await asyncio.to_thread(client.create_vault_list, name[:120])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "of_create_failed", "detail": str(e)[:300]})
    fid = folder.get("id")
    added = 0
    if media_ids and fid:
        try:
            await asyncio.to_thread(client.add_media_to_vault_list, fid, media_ids)
            added = len(media_ids)
        except Exception:  # noqa: BLE001
            log.warning("of add-media after create failed folder=%s", fid, exc_info=True)
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {"account_id": account_id, "id": fid, "name": folder.get("name"), "added": added}


@of_router.post("/admin/vault-ai/of-folders/{list_id}/add")
async def add_to_of_folder(list_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Add selected media to a REAL OF folder (POST /vault/lists/{id}/media)."""
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    media_ids = [int(x) for x in (payload.get("media_ids") or []) if str(x).lstrip("-").isdigit()]
    if not media_ids:
        raise HTTPException(status_code=400, detail={"error": "media_ids_required"})
    await _reject_foreign_media(account_id, media_ids)
    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        await asyncio.to_thread(client.add_media_to_vault_list, list_id, media_ids)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "of_add_failed", "detail": str(e)[:300]})
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {"account_id": account_id, "list_id": list_id, "added": len(media_ids)}


@of_router.post("/admin/vault-ai/of-folders/{list_id}/remove")
async def remove_from_of_folder(list_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Take selected media out of a REAL OF folder (DELETE /vault/lists/{id}/media).
    The media stay in the vault. A move is /add to the target, then this."""
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    media_ids = [int(x) for x in (payload.get("media_ids") or []) if str(x).lstrip("-").isdigit()]
    if not media_ids:
        raise HTTPException(status_code=400, detail={"error": "media_ids_required"})
    await _reject_foreign_media(account_id, media_ids)
    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        await asyncio.to_thread(client.remove_media_from_vault_list, list_id, media_ids)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "of_remove_failed", "detail": str(e)[:300]})
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {"account_id": account_id, "list_id": list_id, "removed": len(media_ids)}


@of_router.post("/admin/vault-ai/of-folders/{list_id}/rename")
async def rename_of_folder(list_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Rename a REAL OF folder (PATCH /vault/lists/{id})."""
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail={"error": "name_required"})
    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        await asyncio.to_thread(client.rename_vault_list, list_id, name[:120])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "of_rename_failed", "detail": str(e)[:300]})
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {"account_id": account_id, "list_id": list_id, "name": name}


@of_router.delete("/admin/vault-ai/of-folders/{list_id}")
async def delete_of_folder(
    list_id: int, account_id: str = Query(...), clear_media: bool = Query(False),
) -> dict[str, Any]:
    """Delete a REAL OF folder (DELETE /vault/lists/{id}). `clear_media=False`
    keeps the media in the vault (only removes the folder)."""
    assert_account_owned(account_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        await asyncio.to_thread(client.delete_vault_list, list_id, clear_media)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "of_delete_failed", "detail": str(e)[:300]})
    # Drop our local per-folder order rows for this folder too.
    async with get_session() as s:
        await s.execute(delete(VaultFolderItem).where(
            VaultFolderItem.account_id == account_id, VaultFolderItem.folder_id == list_id))
        await s.commit()
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {"account_id": account_id, "list_id": list_id, "deleted": True}


@of_router.post("/admin/vault-ai/of-folders/sort")
async def sort_of_folders(payload: dict = Body(...)) -> dict[str, Any]:
    """Set the OF folder-list ordering (POST /vault/lists/sort). Either
    {sort: name|recent|media|custom|default, order: asc|desc} or a manual
    {custom_order: [list_id,...]} drag order."""
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    custom_order = payload.get("custom_order")
    try:
        if custom_order:
            ids = [int(x) for x in custom_order if str(x).isdigit()]
            await asyncio.to_thread(client.set_vault_lists_custom_order, ids)
        else:
            sort = str(payload.get("sort") or "recent")
            order = str(payload.get("order") or "desc")
            await asyncio.to_thread(client.sort_vault_lists, sort, order)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "of_sort_failed", "detail": str(e)[:300]})
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {"account_id": account_id, "sorted": True}
