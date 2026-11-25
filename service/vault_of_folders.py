from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import delete, func, select, update

import automation_executor as ax
import relay_host
import vault_cache
import vault_dupes
import vault_pack_picker
import vault_scripts
import vault_topic_folders
from auth import assert_account_owned
from chatters import allowed_folder_ids_for_chatter
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem
from of_client import OFAPIError
from vault_of_folders_decide import chunks, hide_selection, next_folder_ids, parse_folder_ids, parse_threshold, too_many

log = logging.getLogger("of-relay.vault_ai_api")

plan_router = APIRouter()
of_router = APIRouter()

# OF vault/media caps limit at 100.
_PAGE = 100
# 20k-item backstop so a stuck hasMore can't loop forever.
_MAX_PAGES = 200
# Automations bypass the relay's priority lane, so pace here.
_PAGE_SLEEP_S = 0.15

# Blast-radius guard: the client batches bigger selections.
_MAX_HIDE_PER_CALL = 500
_OF_HIDE_CHUNK = 100
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
    allowed = await allowed_folder_ids_for_chatter(account_id)
    was_running = vault_dupes.backfill_running(account_id)
    res = await vault_dupes.find_duplicates(account_id, threshold, allowed=allowed)
    backfill = vault_dupes.backfill_status(account_id)
    if was_running:
        backfill = {**(backfill or {"total": 0, "done": 0, "failed": 0}), "running": True}
        missing_n = max(0, backfill["total"] - backfill["done"])
    else:
        missing = await vault_dupes.missing_thumb_ids(account_id, allowed)
        vault_dupes.start_thumb_backfill(account_id, missing, allowed)
        backfill = vault_dupes.backfill_status(account_id)
        missing_n = len(missing)

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
            "account_id": account_id, "missing_thumbs": missing_n,
            "backfill": backfill,
            "returned": len(clusters), "clusters": clusters}


@plan_router.get("/admin/vault-ai/folder-plan")
async def get_folder_plan(
    account_id: str = Query(...),
    keep: int = Query(vault_scripts.DEFAULT_KEEP_SCRIPTS, ge=0, le=20),
    solo: bool = Query(False),
    topics: str = Query(""),
    split: bool = Query(True),
) -> dict[str, Any]:
    """PREVIEW the folders the pipeline would create. Read-only, free, instant —
    no LLM, no OF traffic, nothing written. This is what the vault button shows
    before the operator confirms.

    `solo` adds a `-solo` cut of each lane, keeping only the items nobody else
    is in. `changes` (+ each folder's `change`) is what Confirm does to the
    AI- folders already there: create / keep / retire, and how many retired
    ones are bound to an OF list.

    `topics` — comma-separated topic slugs (`vault_topic_folders.SLUGS`) to add as Jev topic folders; an
    unknown slug is a 422. `topic_catalogue` + `jev` always come back, so the checklist shows every topic's
    size and the Jev coverage whatever is ticked. `split` (default on) makes one topic folder per price; off, one
    per topic (`AI-<name>`)."""
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    picked = _topics_or_422(topics)
    return await vault_scripts.plan_ai_folders(account_id, keep=keep, solo=solo, topics=picked, split=split)


def _flag(payload: dict, key: str, default: bool) -> bool:
    raw = payload.get(key)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise HTTPException(status_code=400, detail={"error": f"bad_{key}"})
    return raw


def _topics_or_422(raw: Any) -> list[str]:
    if raw is not None and not isinstance(raw, (str, list)):
        raise HTTPException(status_code=422, detail={"error": "bad_topics"})
    try:
        return vault_topic_folders.parse_topics(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"error": "unknown_topics",
                                                      "unknown": e.args[0]}) from None


async def _read_of_list_members(client, of_list_id: int) -> set[int]:
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
    async with get_session() as s:
        folder = await s.get(VaultFolder, folder_id)
        of_list_id = folder.of_list_id if folder else None

    # Ordering: the list id is bound before the media add, so a failed add re-runs into the same list instead of minting a second one.
    created = False
    if not of_list_id:
        of_list_id = await asyncio.shield(_create_and_bind(client, folder_id, name))
        created = True

    if media_ids:
        try:
            await asyncio.to_thread(client.add_media_to_vault_list, int(of_list_id), media_ids)
        except OFAPIError as e:
            if created or getattr(e.response, "status_code", None) != 404:
                raise
            of_list_id = await asyncio.shield(_create_and_bind(client, folder_id, name))
            created = True
            await asyncio.to_thread(client.add_media_to_vault_list, int(of_list_id), media_ids)
    return {"of_list_id": int(of_list_id), "created": created}


async def _create_and_bind(client, folder_id: int, name: str) -> int:
    res = await asyncio.to_thread(client.create_vault_list, name[:120])
    of_list_id = (res or {}).get("id")
    if not of_list_id:
        raise RuntimeError(f"OF returned no list id: {str(res)[:120]}")
    async with get_session() as s:
        await s.execute(
            update(VaultFolder)
            .where(VaultFolder.id == folder_id)
            .values(of_list_id=int(of_list_id))
        )
        await s.commit()
    return int(of_list_id)


async def _mirror_ai_folders_to_of(
    account_id: str, created: list[dict[str, Any]], plan: dict[str, Any],
) -> list[dict[str, Any]]:
    by_name = {f["name"]: f for f in plan.get("folders") or []}
    client = await asyncio.to_thread(ax._make_client, account_id)
    out: list[dict[str, Any]] = []

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

    stale = await _stale_on_of(account_id, {
        int(r["of_list_id"]): {int(i["media_id"]) for i in (by_name.get(r["name"]) or {}).get("items") or []}
        for r in out if r.get("of_list_id")})
    for r in out:
        if r.get("of_list_id"):
            r["of_stale"] = stale.get(int(r["of_list_id"]), 0)

    list_ids = [int(r["of_list_id"]) for r in out if r.get("of_list_id")]
    if list_ids:
        asyncio.create_task(_readback_membership(client, account_id, list_ids))
    return out


async def _stale_on_of(account_id: str, planned: dict[int, set[int]]) -> dict[int, int]:
    if not planned:
        return {}
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.media_id, VaultItem.of_folder_ids).where(
                VaultItem.account_id == account_id, VaultItem.removed_at.is_(None),
                func.coalesce(VaultItem.of_folder_ids, "").notin_(("", "[]"))))).all()
    out = dict.fromkeys(planned, 0)
    for mid, raw in rows:
        for lid in parse_folder_ids(raw):
            if lid in out and int(mid) not in planned[lid]:
                out[lid] += 1
    return out


async def _readback_membership(client, account_id: str, list_ids: list[int]) -> int:
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

    🚨 A pack's free rung (`vault_pack_picker.free_rung_category`, e.g.
    `feet-tease`) never ships a member Jev says may not ride free
    (`vault_pack_picker.unsafe_on_free`): it is left out and named in
    `skipped_unsafe`. Rows filed there before the triage guard existed are what
    this catches; the operator unfiles them in the picker.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)

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
        skipped_videos = (await vault_pack_picker.non_photos(s, account_id, members)
                          if vault_pack_picker.pack_rung_category(name) else [])
        clips = set(skipped_videos)
        members = [m for m in members if m not in clips]
        skipped_unsafe = (await vault_pack_picker.unsafe_on_free(s, account_id, members)
                          if vault_pack_picker.free_rung_category(name) else [])
    skip = set(skipped_unsafe)
    members = [m for m in members if m not in skip]

    if not members:
        raise HTTPException(status_code=400, detail={
            "error": "folder_empty", "skipped_unsafe": skipped_unsafe, "skipped_videos": skipped_videos})

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
        "skipped_unsafe": skipped_unsafe,
        "skipped_videos": skipped_videos,
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
    the lanes and retire every `-solo` folder in the same call. `topics` likewise (a list of slugs; unknown
    → 422): previewed topic folders not posted back would be retired. `split` likewise (absent → on): the other
    naming's topic folders are retired.

    `expected_retire` (list of folder ids, the preview's `changes.retired`): only those stale folders are retired;
    a stale folder the preview did not show stays live and comes back under `skipped_retire`. Absent → every
    stale folder retires (the old behaviour). Not a list of ints → 400 `bad_expected_retire`.
    `solo` / `split` / `mirror_to_of`: JSON booleans; anything else → 400 `bad_<field>`.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    try:
        keep = parse_threshold(payload.get("keep"), vault_scripts.DEFAULT_KEEP_SCRIPTS, 20)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "bad_keep"}) from None
    raw_expected = payload.get("expected_retire")
    if raw_expected is not None and not (isinstance(raw_expected, list)
                                         and all(type(x) is int for x in raw_expected)):
        raise HTTPException(status_code=400, detail={"error": "bad_expected_retire"})
    return {"account_id": account_id, **await build_ai_folders(
        account_id, keep=keep, solo=_flag(payload, "solo", False), topics=_topics_or_422(payload.get("topics")),
        split=_flag(payload, "split", True), mirror_to_of=_flag(payload, "mirror_to_of", False),
        expected_retire=None if raw_expected is None else set(raw_expected))}


async def build_ai_folders(account_id: str, *, keep: int, solo: bool, topics: list[str], split: bool,
                           mirror_to_of: bool, expected_retire: set[int] | None = None) -> dict[str, Any]:
    plan = await vault_scripts.plan_ai_folders(account_id, keep=keep, solo=solo, topics=topics, split=split)
    result = await vault_scripts.apply_ai_folders(account_id, plan, expected_retire=expected_retire)

    if mirror_to_of:
        result["created"] = await _mirror_ai_folders_to_of(
            account_id, result["created"], plan)
        result["of_mirrored"] = sum(1 for c in result["created"] if c.get("of_list_id"))
        result["of_failed"] = sum(1 for c in result["created"] if c.get("of_error"))
        result["of_stale"] = sum(c.get("of_stale") or 0 for c in result["created"])

    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    return {**result, "summary": plan["summary"]}


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

    The keeper guarantee applies within one scope; chatter then owner hides can chain,
    as can owner hides at two thresholds.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    media_ids = [int(x) for x in (payload.get("media_ids") or [])
                 if str(x).lstrip("-").isdigit()]
    from vault_ai_api import assert_media_visible
    await assert_media_visible(account_id, *media_ids)
    if not media_ids:
        raise HTTPException(status_code=400,
                            detail={"error": "media_ids_required"})
    over = too_many(media_ids, _MAX_HIDE_PER_CALL)
    if over:
        raise HTTPException(status_code=400, detail=over)
    allow_sent = bool(payload.get("allow_sent"))
    try:
        threshold = parse_threshold(payload.get("threshold"), vault_dupes.DEFAULT_THRESHOLD,
                                    vault_dupes.MAX_THRESHOLD)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail={"error": "bad_threshold"}) from None

    allowed = await allowed_folder_ids_for_chatter(account_id)
    res = await vault_dupes.find_duplicates(account_id, threshold, rehash=False,
                                            allowed=allowed)
    approved, refused = hide_selection(media_ids, res["clusters"], allow_sent)

    done: list[int] = []
    of_error: str | None = None
    if approved:
        relay_host.refuse_if_platform_lacks(account_id, "hide_vault_media", "remove from vault")
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
        out["of_error"] = of_error
        out["not_hidden"] = approved[len(done):]
    return out


async def _reject_foreign_media(account_id: str, media_ids: list[int]) -> None:
    if not media_ids:
        return
    from vault_ai_api import assert_media_visible
    await assert_media_visible(account_id, *media_ids)
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
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail={"error": "name_required"})
    media_ids = [int(x) for x in (payload.get("media_ids") or []) if str(x).lstrip("-").isdigit()]
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
    from vault_ai_api import assert_folder_visible
    await assert_folder_visible(account_id, list_id)
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
    from vault_ai_api import assert_folder_visible
    await assert_folder_visible(account_id, list_id)
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
    from vault_ai_api import assert_folder_visible
    await assert_folder_visible(account_id, list_id)
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
    from vault_ai_api import assert_folder_visible
    await assert_folder_visible(account_id, list_id)
    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        await asyncio.to_thread(client.delete_vault_list, list_id, clear_media)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "of_delete_failed", "detail": str(e)[:300]})
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
    from vault_ai_api import assert_owner_scope
    await assert_owner_scope(account_id)
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
