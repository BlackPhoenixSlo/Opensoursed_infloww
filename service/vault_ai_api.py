"""service/vault_ai_api.py — whole-vault local mirror ("Collect all") + instant local read.

The "Collect all" button walks the entire OF vault ONCE and upserts every item
into the `vault_items` mirror, so afterward the grid + search are served LOCALLY
(instant, including never-before-typed queries) instead of round-tripping OF.

  POST /admin/vault-ai/collect?account_id=            → start a sweep, returns {run_id}
  GET  /admin/vault-ai/collect/status?account_id=     → latest run progress
  GET  /admin/vault-ai/cache/summary?account_id=      → {count, last_run}
  GET  /admin/vault-ai/items?account_id=&...           → read from the mirror (local search)

The sweep pages with sort=asc (stable order) and preserves every AI / operator
field on conflict — only the mirror bookkeeping (raw_json, urls, last_seen_run_id)
is refreshed. Describe (Qwen3-VL) and folder-membership passes layer on top later.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax  # _make_client seam (same one automations use)
import vault_ai_vision  # flags + describe passes; routes included at their old spots below
import vault_ai_vision_decide
# The permanent, signature-free picture stores (thumbs / full previews / DRM poster
# frames), including the whole route body behind the three serve endpoints below.
# This module keeps the SWEEP that fills them.
import vault_frames
import vault_mirror
import vault_of_folders  # duplicates list/hide, folder plan + publish, OF folder CRUD; routes included at their old spots below
import vault_pack_picker
import vault_stills
# NOTE: the OF payload-shape readers (`still_url`, `giphy_dm_id`) are NOT imported
# here — `vault_frames` owns "which url in a payload is the picture" now, and this
# module reaches them through it.
from auth import assert_account_owned
from db.engine import get_session
from db.models import (
    VaultCacheRun, VaultFolderItem, VaultItem, VaultOfQueryLog,
)
from jsonsafe import load_json

log = logging.getLogger("of-relay.vault_ai_api")

# Re-exported for callers that still reach them here (test_llm_zai_glm,
# test_vault_scripts). Patch the originals on `vault_ai_vision` — patching a
# re-export here does not change what the sweep calls.
_describe_running = vault_ai_vision._describe_running  # the same set object
describe_all = vault_ai_vision.describe_all
describe_one = vault_ai_vision.describe_one
_ground_in_named_garment = vault_ai_vision_decide._ground_in_named_garment
_reconcile_with_acts = vault_ai_vision_decide._reconcile_with_acts

# Re-exported from `vault_of_folders` (same objects), read here by
# test_vault_dupes, test_vault_foreign_media_guard, test_vault_scripts,
# test_vault_ai_mirror and `vault_pack_picker`'s docstring. Read-only: assigning
# these here does nothing; patch `vault_of_folders.X` (the moved code, and
# `hide_item` below, look them up there).
_MAX_HIDE_PER_CALL = vault_of_folders._MAX_HIDE_PER_CALL
_OF_HIDE_CHUNK = vault_of_folders._OF_HIDE_CHUNK
_DB_IN_CHUNK = vault_of_folders._DB_IN_CHUNK
list_duplicates = vault_of_folders.list_duplicates
get_folder_plan = vault_of_folders.get_folder_plan
_read_of_list_members = vault_of_folders._read_of_list_members
_apply_list_membership = vault_of_folders._apply_list_membership
_push_folder_to_of = vault_of_folders._push_folder_to_of
_mirror_ai_folders_to_of = vault_of_folders._mirror_ai_folders_to_of
_readback_membership = vault_of_folders._readback_membership
publish_folder_to_of = vault_of_folders.publish_folder_to_of
apply_folder_plan = vault_of_folders.apply_folder_plan
hide_duplicates = vault_of_folders.hide_duplicates
_reject_foreign_media = vault_of_folders._reject_foreign_media
create_of_folder = vault_of_folders.create_of_folder
add_to_of_folder = vault_of_folders.add_to_of_folder
remove_from_of_folder = vault_of_folders.remove_from_of_folder
rename_of_folder = vault_of_folders.rename_of_folder
delete_of_folder = vault_of_folders.delete_of_folder
sort_of_folders = vault_of_folders.sort_of_folders

router = APIRouter()

_PAGE = 100                # OF vault/media caps limit at 100
_MAX_PAGES = 200          # 20k-item backstop so a stuck hasMore can't loop forever
_PAGE_SLEEP_S = 0.15      # pacing: automations bypass the relay's priority lane
# Guard against two concurrent sweeps for the same account clobbering each other.
_running: set[str] = set()
# In-memory storyboard-warming progress per account (surfaced in /collect/status).
_warm_progress: dict[str, dict[str, Any]] = {}

async def _warm_store(client: Any, account_id: str, phase: str,
                      targets: list[tuple[Path, str]]) -> None:
    """Download every missing still in `targets` into its permanent path.

    One loop for all three stores — they differed only in which path a media id
    maps to, which is the caller's business and nothing else's.

    Progress uses `warmed`/`warm_total`, the keys /collect/status already reads —
    previously only the storyboard phase spoke them, so the three still phases ran
    silently behind a progress bar stuck on null."""
    total = len(targets)
    _warm_progress[account_id] = {"phase": phase, "warmed": 0, "warm_total": total}
    for n, (path, url) in enumerate(targets, 1):
        if not path.is_file():
            data = await asyncio.to_thread(vault_stills.fetch_bytes_sync, client, url)
            if data:
                vault_stills.write(path, data)
        if n % 10 == 0 or n == total:
            _warm_progress[account_id] = {"phase": phase, "warmed": n,
                                          "warm_total": total}


async def _run_collect(account_id: str, run_id: int) -> None:
    """Background sweep: page the whole vault, upsert into the mirror."""
    try:
        client = await asyncio.to_thread(ax._make_client, account_id)
        offset = 0
        pages = 0
        total = 0
        upserted = 0
        videos: list[tuple[str, float]] = []   # (signed url, duration) to warm after
        thumbs: list[tuple[int, str]] = []     # (media_id, thumb url) to cache after
        stills: list[tuple[int, str]] = []     # (media_id, full-frame url) to cache after
        drm_posters: list[tuple[int, list[str]]] = []  # DRM (media_id, poster urls)
        while pages < _MAX_PAGES:
            resp = await asyncio.to_thread(
                client.vault_media, limit=_PAGE, offset=offset, type="all", sort="asc",
            )
            items = (resp or {}).get("list") or []
            if not items:
                break
            async with get_session() as s:
                for m in items:
                    vals = vault_mirror.row_values(account_id, m, run_id)
                    if vals is None:
                        continue
                    total += 1
                    if vals.get("thumb_url"):
                        thumbs.append((vals["media_id"], vals["thumb_url"]))
                    # The full-FRAME preview, not just the 300px square. Warmed
                    # here for the same reason as the thumb: after OF's signature
                    # expires we can no longer fetch it, and a lazily-filled
                    # store means whatever nobody happened to open is lost.
                    still = vault_frames.describe_image_of(
                        m.get("files") if isinstance(m.get("files"), dict) else {}
                    )
                    if still:
                        stills.append((vals["media_id"], still))
                    if (m.get("type") == "video"):
                        vurl = vault_frames.video_url(m)
                        if vurl:
                            videos.append((vurl, float(m.get("duration") or 0)))
                        else:
                            # DRM: no sliceable mp4 → cache OF poster frames so
                            # the hover preview serves from disk, not a cold fetch.
                            pf = vault_frames.poster_frames(m)
                            if pf:
                                drm_posters.append((vals["media_id"], pf))
                    # Preserve AI / operator / describe fields on conflict —
                    # only refresh the mirror bookkeeping. The statement is
                    # `vault_mirror`'s, shared with the import ingest: one
                    # on-conflict set, so the two writers cannot disagree about
                    # what seeing a media again is allowed to overwrite.
                    await s.execute(vault_mirror.upsert_stmt(vals))
                    upserted += 1
                await s.commit()
            pages += 1
            offset += _PAGE
            async with get_session() as s:
                run = await s.get(VaultCacheRun, run_id)
                if run:
                    run.pages_done = pages
                    run.total_seen = total
                    run.upserted = upserted
                    run.phase = "media"
                    await s.commit()
            if not (resp or {}).get("hasMore"):
                break
            await asyncio.sleep(_PAGE_SLEEP_S)

        # ── Storyboard-warming phase (incremental) ──────────────────
        # Extract + cache 12 frames for every video whose storyboard isn't
        # already on disk. Metadata is already committed above, so search +
        # the grid are usable while this (slower) phase runs. Re-collect only
        # warms NEW videos — _warm_one_sync short-circuits cached ones.
        async with get_session() as s:
            run = await s.get(VaultCacheRun, run_id)
            if run:
                run.phase = "thumbs"
                await s.commit()
        # Fill the three permanent stores. All incremental — an already-cached file
        # is skipped, so a re-collect only pays for what is new.
        await _warm_store(client, account_id, "thumbs",
                          [(vault_stills.thumb_path(account_id, mid), u)
                           for mid, u in thumbs])
        # The full frames too, not just the squares (~960x1280). This is the copy
        # the review UI reads, and it is equally unrecoverable once the signature
        # it came from has aged out.
        await _warm_store(client, account_id, "images",
                          [(vault_stills.image_path(account_id, mid), u)
                           for mid, u in stills])
        # DRM clips can't be ffmpeg-storyboarded, so OF's own poster frames ARE the
        # hover preview — cached, a DRM hover is instant instead of a cold ~0.7s fetch.
        await _warm_store(client, account_id, "posters",
                          [(vault_stills.poster_path(account_id, mid, idx), u)
                           for mid, frames in drm_posters
                           for idx, u in enumerate(frames)])
        async with get_session() as s:
            run = await s.get(VaultCacheRun, run_id)
            if run:
                run.phase = "warming"
                await s.commit()
        warmed = 0
        _warm_progress[account_id] = {"phase": "warming", "warmed": 0, "warm_total": len(videos)}
        for vurl, vdur in videos:
            try:
                await asyncio.to_thread(vault_frames.warm_one_sync, client, vurl, vdur)
            except Exception:  # noqa: BLE001
                log.warning("warm dispatch failed", exc_info=True)
            warmed += 1
            _warm_progress[account_id] = {
                "phase": "warming", "warmed": warmed, "warm_total": len(videos),
            }
            await asyncio.sleep(0.02)   # light pacing between mp4 downloads
        _warm_progress.pop(account_id, None)

        async with get_session() as s:
            run = await s.get(VaultCacheRun, run_id)
            if run:
                run.status = "done"
                run.phase = "done"
                run.pages_done = pages
                run.total_seen = total
                run.upserted = upserted
                run.finished_at = datetime.utcnow()
                await s.commit()
        log.info("vault_collect done account=%s run=%s items=%s", account_id, run_id, total)
    except Exception as e:  # noqa: BLE001
        log.exception("vault_collect failed account=%s run=%s", account_id, run_id)
        try:
            async with get_session() as s:
                run = await s.get(VaultCacheRun, run_id)
                if run:
                    run.status = "error"
                    run.error = str(e)[:500]
                    run.finished_at = datetime.utcnow()
                    await s.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        _running.discard(account_id)
        _warm_progress.pop(account_id, None)


@router.post("/admin/vault-ai/collect")
async def start_collect(account_id: str = Query(...)) -> dict[str, Any]:
    """Kick off a full-vault mirror sweep in the background."""
    assert_account_owned(account_id)
    if account_id in _running:
        raise HTTPException(status_code=409, detail={"error": "collect_already_running"})
    _running.add(account_id)
    # Drop the OF listing cache first. It holds whole response bodies whose
    # urls are time-signed, so serving one back after the signature aged out
    # hands the picker links that 403 — the same stale-url the sweep is about
    # to replace. Cheap, and it makes Re-collect mean "everything fresh".
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        log.warning("vault_cache invalidate failed for %s", account_id, exc_info=True)
    async with get_session() as s:
        run = VaultCacheRun(account_id=account_id, status="running", phase="media")
        s.add(run)
        await s.commit()
        run_id = run.id
    asyncio.create_task(_run_collect(account_id, run_id))
    return {"account_id": account_id, "run_id": run_id, "status": "running"}


def _run_status(row: VaultCacheRun, account_id: str) -> str:
    """What this run's status actually IS, not what it last managed to write.

    A collect is a background task and its rows are finalised by the task
    itself, so a relay restart mid-sweep leaves `running` behind with nothing
    left to ever clear it. One prod row said `running / warming` for three days;
    it is also why 1,046 clips were never warmed, and the status endpoint
    reported the sweep as still in progress the whole time.

    `_running` is the only place a live sweep is tracked and it is process-local,
    so a row claiming to run for an account nobody is running IS orphaned — the
    process that owned it is gone. Read, never written: the stored row stays the
    honest record of what the task last wrote, and a reconciliation pass that
    could itself be interrupted is machinery this does not need."""
    if row.status == "running" and account_id not in _running:
        return "interrupted"
    return row.status


@router.get("/admin/vault-ai/collect/status")
async def collect_status(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        row = (
            await s.execute(
                select(VaultCacheRun)
                .where(VaultCacheRun.account_id == account_id)
                .order_by(VaultCacheRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return {"account_id": account_id, "run": None}
    warm = _warm_progress.get(account_id)
    return {
        "account_id": account_id,
        "run": {
            "id": row.id,
            "status": _run_status(row, account_id),
            # The warm loop's own phase (thumbs → images → posters → warming)
            # while it runs: the row is written once before the three stores, so
            # alone it showed "thumbs" while the counter reset per store.
            "phase": (warm or {}).get("phase") or row.phase,
            "total_seen": row.total_seen,
            "upserted": row.upserted,
            "pages_done": row.pages_done,
            "error": row.error,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "running": account_id in _running,
            "warmed": (warm or {}).get("warmed"),
            "warm_total": (warm or {}).get("warm_total"),
        },
    }


@router.get("/admin/vault-ai/cache/summary")
async def cache_summary(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        count = (
            await s.execute(
                select(func.count())
                .select_from(VaultItem)
                .where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None))
            )
        ).scalar_one()
        last = (
            await s.execute(
                select(VaultCacheRun)
                .where(VaultCacheRun.account_id == account_id)
                .order_by(VaultCacheRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return {
        "account_id": account_id,
        "count": int(count or 0),
        "running": account_id in _running,
        "last_run": None if last is None else {
            "id": last.id, "status": _run_status(last, account_id),
            "total_seen": last.total_seen,
            "finished_at": last.finished_at.isoformat() if last.finished_at else None,
        },
    }


# ── The three permanent stills ────────────────────────────────────────
#
# One route body (`vault_stills.serve`) three times over: disk, else fetch and
# keep, re-signing the url through OF if the stored one has expired. Each endpoint
# supplies only the store it reads and the rule for picking ITS url out of a media
# dict — and that rule is written once, used for both the stored payload and the
# re-signed one, so the two can't disagree.

@router.get("/admin/vault-ai/thumb")
async def vault_thumb(account_id: str = Query(...), media_id: int = Query(...)):
    """The 300px square — the grid + picker tile."""
    assert_account_owned(account_id)
    return await vault_stills.serve(
        account_id, media_id, vault_stills.thumb_path(account_id, media_id),
        vault_frames.pick_thumb)


@router.get("/admin/vault-ai/image")
async def vault_image(account_id: str = Query(...), media_id: int = Query(...)):
    """The FULL-FRAME image (~960x1280) — the review UI shows THIS, never the
    /thumb crop.

    /thumb is a 300x300 centre-crop of a 3:4 portrait: its top and bottom are
    gone, so a waistband or genitalia at the frame edge is invisible in it. That
    crop is exactly what made the vision model over-report `fully_nude`, and an
    operator judging the square would make the same mistake — they'd be
    correcting a flag against less of the picture than the model that set it saw.
    `_describe_image_of` picks the same variant the model was given, so the
    reviewer sees precisely the frame the reading was made on."""
    assert_account_owned(account_id)
    return await vault_stills.serve(
        account_id, media_id, vault_stills.image_path(account_id, media_id),
        vault_frames.pick_image)


@router.get("/admin/vault-ai/poster")
async def vault_poster(
    account_id: str = Query(...), media_id: int = Query(...), i: int = Query(0, ge=0),
):
    """Frame `i` of a DRM video's hover slideshow. The cache fills as you browse;
    Collect just pre-warms the whole vault.

    Takes no caller-supplied url. It used to accept `u=` so a hover over an
    UN-collected clip could still fill the store, gated by a host check that
    accepted any hostname containing both "cdn" and "onlyfans" — so
    `cdn.onlyfans.attacker.com` passed and the route fetched it with the
    account's own authenticated client. The parameter earned nothing: `serve`
    already resolves an unknown media by id straight from OF, which is both the
    safe source and the one that survives an expired signature."""
    assert_account_owned(account_id)
    return await vault_stills.serve(
        account_id, media_id, vault_stills.poster_path(account_id, media_id, i),
        vault_frames.pick_poster(i))


def _overlay(item: VaultItem, manual_order: int | None = None) -> dict[str, Any]:
    try:
        base = json.loads(item.raw_json) if item.raw_json else {"id": item.media_id, "type": item.kind}
    except Exception:  # noqa: BLE001
        base = {"id": item.media_id, "type": item.kind}
    base["_ai"] = {
        "describe_status": item.describe_status,
        "description": item.description,
        "video_description": item.video_description,
        "tags": load_json(item.tags, []),
        "explicitness_tier": item.explicitness_tier,
        "story_suitable": item.story_suitable,
        "tip_vault_flag": item.tip_vault_flag,
        "suggested_caption": item.suggested_caption,
        "suggested_price_cents": item.suggested_price_cents,
        "manual_order": item.manual_order if manual_order is None else manual_order,
        "review_state": item.review_state,
        "suggested_script": item.suggested_script,
    }
    # The V2 describe taxonomy (acts / clothing_state / beats / primary_folder /
    # …) lives ONLY in ai_fields_json — there are no columns for it. Without
    # this projection the browser receives just `description` + `tags` and the
    # other 21 fields the model produced are invisible, which is exactly what
    # made the vault look like it had lost them. Projected read-only: edits
    # still go through the override+lock path on the real columns.
    ai = load_json(item.ai_fields_json, None)
    if isinstance(ai, dict):
        base["_ai"]["fields"] = {
            k: v for k, v in ai.items()
            # `description`/`tags` are already served from their columns (which
            # carry any operator override); don't shadow them with the raw AI value.
            if k not in ("description", "tags")
        }
    # Stable, signature-free cached-thumb URL (self-heals on miss). Frontend
    # prefers this over the expiring OF url so tiles never break.
    #
    # Only for a kind that HAS a still. Its presence is the browser's whole
    # answer to "is there a picture" — every tile surface renders it and asks
    # nothing else — so stamping it on a voice note is not a harmless extra
    # field, it is an instruction to fetch a picture that cannot exist. See
    # `vault_mirror.has_still` for what that used to cost per paint.
    if vault_mirror.has_still(item.kind):
        base["_thumb"] = f"/admin/vault-ai/thumb?account_id={item.account_id}&media_id={item.media_id}"
    return base


@router.get("/admin/vault-ai/items")
async def local_items(
    account_id: str = Query(...),
    type: str = Query("all"),
    query: str | None = Query(None),
    sort: str = Query("newest"),
    internal_folder_id: int | None = Query(None),
    of_folder_id: int | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Read the LOCAL mirror. Same {list, hasMore} shape as /api/of/v2/vault/media
    so the frontend swaps data source transparently. Search is a local LIKE-scan
    (instant). `internal_folder_id` filters to an internal folder and orders by
    its per-folder manual_order: 0 first, 1,2,3… from front, then unpinned by
    date, then …-3,-2,-1 (so -1 is dead last)."""
    assert_account_owned(account_id)
    q = (query or "").strip().lower()

    def _apply_common(st):
        if type and type != "all":
            st = st.where(VaultItem.kind == type)
        if q:
            like = f"%{q}%"
            st = st.where(
                func.lower(func.coalesce(VaultItem.search_text, "")).like(like)
                | func.lower(func.coalesce(VaultItem.description, "")).like(like)
                | func.lower(func.coalesce(VaultItem.tags, "")).like(like)
                | func.lower(func.coalesce(VaultItem.video_description, "")).like(like)
                # of_terms = OF's own vault-search matches (harvested by /search-of),
                # folded per item as a JSON array e.g. ["ass","boobs"]. OF indexes
                # hidden caption/content text the media dict never exposes, so this
                # is the ONLY way our local search becomes a superset of OF's.
                | func.lower(func.coalesce(VaultItem.of_terms, "")).like(like)
            )
        return st

    out: list[dict[str, Any]] = []
    async with get_session() as s:
        if internal_folder_id is not None:
            mo = VaultFolderItem.manual_order
            bucket = case((mo.is_(None), 1), (mo >= 0, 0), else_=2)
            stmt = (
                select(VaultItem, mo)
                .join(
                    VaultFolderItem,
                    (VaultFolderItem.account_id == VaultItem.account_id)
                    & (VaultFolderItem.media_id == VaultItem.media_id),
                )
                .where(
                    VaultItem.account_id == account_id,
                    VaultItem.removed_at.is_(None),
                    VaultFolderItem.folder_id == internal_folder_id,
                )
            )
            stmt = _apply_common(stmt)
            stmt = stmt.order_by(bucket, mo, VaultItem.created_at.desc()).limit(limit + 1).offset(offset)
            pairs = (await s.execute(stmt)).all()
            has_more = len(pairs) > limit
            for item, m_ord in pairs[:limit]:
                out.append(_overlay(item, m_ord))
        elif of_folder_id is not None:
            # An OF folder, served from the mirror. Membership = of_folder_ids
            # (parsed from listStates); manual_order via a LEFT join on
            # vault_folder_items keyed by the OF list id.
            mo = VaultFolderItem.manual_order
            bucket = case((mo.is_(None), 1), (mo >= 0, 0), else_=2)
            stmt = (
                select(VaultItem, mo)
                .outerjoin(
                    VaultFolderItem,
                    (VaultFolderItem.account_id == VaultItem.account_id)
                    & (VaultFolderItem.media_id == VaultItem.media_id)
                    & (VaultFolderItem.folder_id == of_folder_id),
                )
                .where(
                    VaultItem.account_id == account_id,
                    VaultItem.removed_at.is_(None),
                    func.coalesce(VaultItem.of_folder_ids, "[]").like(f"%{of_folder_id}%"),
                )
            )
            stmt = _apply_common(stmt)
            stmt = stmt.order_by(bucket, mo, VaultItem.created_at.desc()).limit(limit + 1).offset(offset)
            pairs = (await s.execute(stmt)).all()
            has_more = len(pairs) > limit
            for item, m_ord in pairs[:limit]:
                out.append(_overlay(item, m_ord))
        else:
            stmt = select(VaultItem).where(
                VaultItem.account_id == account_id, VaultItem.removed_at.is_(None)
            )
            stmt = _apply_common(stmt)
            stmt = stmt.order_by(
                VaultItem.created_at.asc() if sort == "oldest" else VaultItem.created_at.desc()
            ).limit(limit + 1).offset(offset)
            rows = (await s.execute(stmt)).scalars().all()
            has_more = len(rows) > limit
            for item in rows[:limit]:
                out.append(_overlay(item))
    return {"list": out, "hasMore": has_more, "source": "mirror"}


# ── OF folders, served from the MIRROR (accurate + proxy-proof) ─────
#
# OF's live /vault/lists?view=main is unreliable: its per-folder `hasMedia`
# flag lies (reports False for folders that plainly have media, e.g. "photos
# cherry" / "categort") and it can omit freshly-touched folders entirely
# (e.g. "nowfolder"). The mirror instead derives membership from each media
# item's own listStates[], which match the OF UI exactly. This lists every
# NON-EMPTY OF folder with correct per-kind counts, instantly, zero OF round
# trip. Empty folders have no media referencing them, so the frontend unions
# this with the live list to recover those.
_BUILTIN_FOLDER_NAMES = {
    "posts", "stories", "streams", "messages", "uploads",
    "tips", "archived", "purchased",
}


@router.get("/admin/vault-ai/of-folders")
async def list_of_folders_from_mirror(account_id: str = Query(...)) -> dict[str, Any]:
    """OF folders derived from the mirror's per-item listStates — accurate
    counts (incl. folders the live vault/lists endpoint drops) with no OF call."""
    assert_account_owned(account_id)
    kind_key = {
        "photo": "photosCount", "video": "videosCount",
        "gif": "gifsCount", "audio": "audiosCount",
    }
    folders: dict[Any, dict[str, Any]] = {}
    async with get_session() as s:
        rows = (
            await s.execute(
                select(VaultItem.raw_json, VaultItem.kind).where(
                    VaultItem.account_id == account_id,
                    VaultItem.removed_at.is_(None),
                )
            )
        ).all()
    for raw, kind in rows:
        m = load_json(raw, {}) or {}
        for ls in (m.get("listStates") or []):
            if not ls.get("hasMedia"):
                continue
            fid = ls.get("id")
            if fid is None:
                continue
            f = folders.get(fid)
            if f is None:
                f = folders[fid] = {
                    "id": fid, "name": ls.get("name") or "", "type": "custom",
                    "photosCount": 0, "videosCount": 0, "gifsCount": 0,
                    "audiosCount": 0, "hasMedia": True,
                }
            if not f["name"] and ls.get("name"):
                f["name"] = ls["name"]
            k = kind_key.get(kind)
            if k:
                f[k] += 1
    out: list[dict[str, Any]] = []
    for f in folders.values():
        f["mediaCount"] = (
            f["photosCount"] + f["videosCount"] + f["gifsCount"] + f["audiosCount"]
        )
        f["builtin"] = (f["name"] or "").strip().lower() in _BUILTIN_FOLDER_NAMES
        out.append(f)
    out.sort(key=lambda x: (x["name"] or "").lower())
    return {"list": out, "source": "mirror"}


# ── Internal folders (our own, zero OF writes) ──────────────────────


@router.post("/admin/vault-ai/reorder")
async def reorder(payload: dict = Body(...)) -> dict[str, Any]:
    """Set manual_order for media. If `folder_id` is given, order is per-folder
    (on vault_folder_items); otherwise it's the global order (on vault_items).
    `order` = [{media_id, manual_order}]. manual_order: 0 first, 1,2,3… front,
    -1 last, -2,-3… back, null = normal."""
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    folder_id = payload.get("folder_id")
    order = payload.get("order") or []
    n = 0
    async with get_session() as s:
        for row in order:
            try:
                mid = int(row["media_id"])
            except Exception:  # noqa: BLE001
                continue
            mo = row.get("manual_order")
            mo = int(mo) if mo is not None and str(mo).lstrip("-").isdigit() else None
            if folder_id is not None:
                # Upsert: an OF-folder item has no membership row (membership is
                # from of_folder_ids), so INSERT the order row if it's missing.
                await s.execute(
                    sqlite_insert(VaultFolderItem)
                    .values(account_id=account_id, folder_id=int(folder_id),
                            media_id=mid, manual_order=mo)
                    .on_conflict_do_update(
                        index_elements=["account_id", "folder_id", "media_id"],
                        set_={"manual_order": mo},
                    )
                )
            else:
                await s.execute(
                    update(VaultItem)
                    .where(VaultItem.account_id == account_id, VaultItem.media_id == mid)
                    .values(manual_order=mo)
                )
            n += 1
        await s.commit()
    return {"account_id": account_id, "folder_id": folder_id, "updated": n}


# ── The pack picker (logic: vault_pack_picker) ──────────────────────

@router.get("/admin/vault-ai/pack-candidates")
async def pack_candidates(
    account_id: str = Query(...),
    category: str = Query("feet"),
    limit: int = Query(600),
) -> dict[str, Any]:
    """Every candidate for a category, each carrying the rung it is filed on now.

    The client renders these with `mirrorFullSrc` (/image), never /thumb: the
    thumb is a 300x300 centre-crop of a 3:4 portrait, and feet sit at exactly the
    edge it discards. Judging from the square means judging from less of the
    picture than the vision model saw.
    """
    assert_account_owned(account_id)
    try:
        cat = vault_pack_picker.category(category)
    except vault_pack_picker.UnknownCategory:
        raise HTTPException(status_code=400, detail={
            "error": "unknown_category",
            "known": sorted(vault_pack_picker.CATEGORIES)}) from None
    return {"account_id": account_id,
            **await vault_pack_picker.candidates(account_id, cat, limit=limit)}


@router.post("/admin/vault-ai/pack-triage")
async def pack_triage(payload: dict = Body(...)) -> dict[str, Any]:
    """Save the operator's verdicts. Creates the rung folders on first save.

    Folders are `created_by="operator"` and `of_list_id` stays NULL — publishing
    to her real OnlyFans vault is a separate, explicit call.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    try:
        cat = vault_pack_picker.category(payload.get("category") or "feet")
        verdicts = vault_pack_picker.normalise_verdicts(cat, payload.get("verdicts") or [])
    except vault_pack_picker.UnknownCategory:
        raise HTTPException(status_code=400, detail={
            "error": "unknown_category",
            "known": sorted(vault_pack_picker.CATEGORIES)}) from None
    except vault_pack_picker.UnknownRung as e:
        raise HTTPException(status_code=400, detail={
            "error": "unknown_rung", "rung": str(e)}) from None
    if not verdicts:
        raise HTTPException(status_code=400, detail={"error": "verdicts_required"})

    folders = await vault_pack_picker.triage(account_id, cat, verdicts)
    return {
        "account_id": account_id,
        "category": cat.name,
        "saved": len(verdicts),
        "rejected": sum(1 for r in verdicts.values() if r is None),
        "folders": folders,
    }


import vault_cache  # noqa: E402


import vault_ai_brief  # noqa: E402  (canonical FLAG_KEYS + flags_known)
import vault_ai_fix  # noqa: E402  (operator resolution of describe/flags disputes)

# ── Duplicates list + AI folder plan (preview / apply / publish) ────
# Lives in `vault_of_folders`; routes included HERE so registration order is
# what it was before the split.
router.include_router(vault_of_folders.plan_router)


# ── Flags pass (vision) ─────────────────────────────────────────────
# Lives in `vault_ai_vision`; its routes are included HERE so registration
# order (and so the OpenAPI schema) is what it was before the split.
router.include_router(vault_ai_vision.flags_router)


@router.get("/admin/vault-ai/disputes")
async def list_disputes(account_id: str = "") -> dict[str, Any]:
    """Items where the describe pass and the flags pass contradict each other.

    Read-only. Each row carries BOTH readings and the two field-writes that
    would settle it, because which pass is wrong differs item by item and
    picking automatically is the mistake this whole review exists to avoid.
    """
    assert_account_owned(account_id)
    return await vault_ai_fix.list_disputes(account_id)


@router.post("/admin/vault-ai/disputes/resolve")
async def resolve_dispute(payload: dict = Body(...)) -> dict[str, Any]:
    """Apply ONE operator correction, locked against future re-runs.

    Body: `{account_id, media_id, values:{field: value}}` — normally one of the
    two branches `list_disputes` proposed, optionally hand-edited. Writes to
    `ai_fields_json` (so every existing reader sees it), to
    `operator_overrides_json`, and adds the field to `locked_fields_json`.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    try:
        media_id = int(payload.get("media_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"error": "media_id_required"})
    res = await vault_ai_fix.apply_fix(account_id, media_id,
                                       payload.get("values") or {})
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res)
    return res


@router.get("/admin/vault-ai/flags-review")
async def flags_review_queue(account_id: str = "", limit: int = 120,
                             only_iffy: bool = False) -> dict[str, Any]:
    """Items for the operator to check, most valuable first.

    The flags pass has been wrong in a different direction after every prompt
    change, and each reversal was invisible to every automatic check and
    obvious to a human in seconds. So looking is part of the product.

    Returns EVERYTHING by default, suspects first. `only_iffy` narrows to the
    nominated ones, and is off by default because the nomination was measured
    and is not good enough to hide things behind: on the graded vault it flags 40 items
    to catch 11 of the 24 that are actually wrong — 28% precision, 46% recall.
    Filtering on that would quietly hide thirteen real errors, which is worse
    than a longer list. The reasons are a SORT ORDER and a set of badges; they
    are not a substitute for looking.
    """
    assert_account_owned(account_id)
    return await vault_ai_fix.review_queue(account_id, limit=limit,
                                           version=vault_ai_vision._FLAGS_VERSION,
                                           only_iffy=only_iffy)


@router.post("/admin/vault-ai/flags-review/grade")
async def flags_review_grade(payload: dict = Body(...)) -> dict[str, Any]:
    """Record one verdict: corrections locked, everything else CONFIRMED.

    Body: `{account_id, media_id, corrections?:{region:state}, note?}`.
    Confirming is not a no-op — it is the evidence `flags-accuracy` runs on,
    and without it "the operator agreed" and "nobody looked" are the same
    record.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    try:
        media_id = int(payload.get("media_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"error": "media_id_required"})
    res = await vault_ai_fix.record_grade(
        account_id, media_id,
        corrections=payload.get("corrections") or {},
        version=vault_ai_vision._FLAGS_VERSION, note=str(payload.get("note") or ""))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res)
    return res


@router.get("/admin/vault-ai/flags-accuracy")
async def flags_accuracy(account_id: str = "") -> dict[str, Any]:
    """How often the model agrees with the operator, on THIS vault.

    Counted only over items graded at the CURRENT prompt version. Mixing
    versions measures nothing, and counting ungraded items as correct is how a
    100% gets reported on a vault nobody has checked.
    """
    assert_account_owned(account_id)
    return await vault_ai_fix.flags_accuracy(account_id,
                                             version=vault_ai_vision._FLAGS_VERSION)


# ── Duplicates hide + direct OF folder CRUD (REAL writes to OnlyFans) ─
# Lives in `vault_of_folders`; routes included HERE so registration order is
# what it was before the split.
router.include_router(vault_of_folders.of_router)


# ── Describe (Qwen3-VL vision) ──────────────────────────────────────
# Lives in `vault_ai_vision`; routes included HERE for the same reason as the
# flags block above.
router.include_router(vault_ai_vision.describe_router)


# ── OF-search harvest (make local search ⊇ OF search) ──────────────
# OF's vault search matches server-side on hidden data (post captions, its own
# index) and returns NO tags — just the filtered id list (confirmed from the
# live response: 14 keys, zero text). So we run OF's own search in the
# background, fold the matched terms into each item's search_text/of_terms, and
# cache the query — permanently, so next time it's instant AND local search
# returns everything OF would PLUS our AI tags.
_OF_SEARCH_TTL_S = 7 * 24 * 3600
_OF_SEARCH_MAX_PAGES = 6

# "What sells on OnlyFans" seed set — categories + attributes we harvest OF's own
# search for, so local search covers everything OF would match across the selling
# taxonomy (folded in next to the AI vision tags). Explicit acts/body, clothing,
# settings, style, and common attributes.
_SELLING_KEYWORDS = [
    # explicit / body
    "nude", "naked", "topless", "porn", "masturbation", "fingering", "sex", "blowjob",
    "cum", "pussy", "ass", "booty", "boobs", "tits", "feet", "toy", "dildo", "vibrator",
    "anal", "squirt", "creampie", "riding",
    # clothing / lingerie
    "lingerie", "bra", "panties", "thong", "bikini", "dress", "outfit", "heels",
    "stockings", "cosplay", "uniform",
    # settings / themes
    "shower", "bath", "bed", "pool", "beach", "car", "travel", "gym", "mirror", "outdoor",
    # style / framing
    "pov", "solo", "selfie", "tease", "closeup", "face", "flowers",
    # attributes / colors
    "tattoo", "blonde", "red", "black", "white", "blue", "pink",
]


async def _harvest_query(account_id: str, q: str, client: Any = None) -> dict[str, Any]:
    """Harvest OF's own vault search for `q` and fold the term into each matched
    mirror item's of_terms/search_text. TTL-cached via vault_of_query_log."""
    q = (q or "").strip().lower()
    if not q:
        return {"query": q, "count": 0, "source": "empty", "ids": []}
    now = datetime.utcnow()
    async with get_session() as s:
        logrow = await s.get(VaultOfQueryLog, (account_id, q))
    if logrow and (now - logrow.fetched_at).total_seconds() < _OF_SEARCH_TTL_S:
        async with get_session() as s:
            ids = [
                r[0] for r in (
                    await s.execute(
                        select(VaultItem.media_id).where(
                            VaultItem.account_id == account_id,
                            func.lower(func.coalesce(VaultItem.of_terms, "")).like(f"%{q}%"),
                        )
                    )
                ).all()
            ]
        return {"query": q, "ids": ids, "count": len(ids), "source": "cache"}

    if client is None:
        try:
            client = await asyncio.to_thread(ax._make_client, account_id)
        except Exception:  # noqa: BLE001
            return {"query": q, "ids": [], "count": 0, "source": "no_client"}
    matched: list[int] = []
    offset = 0
    for _ in range(_OF_SEARCH_MAX_PAGES):
        try:
            resp = await asyncio.to_thread(
                client.vault_media, limit=40, offset=offset, type="all", sort="desc", query=q,
            )
        except Exception:  # noqa: BLE001
            break
        items = (resp or {}).get("list") or []
        if not items:
            break
        matched += [int(it["id"]) for it in items if it.get("id") is not None]
        if not (resp or {}).get("hasMore"):
            break
        offset += 40

    async with get_session() as s:
        for mid in matched:
            item = await s.get(VaultItem, (account_id, mid))
            if item is None:
                continue
            terms = set(load_json(item.of_terms, []))
            if q in terms:
                continue
            terms.add(q)
            new_search = ((item.search_text or "") + " " + q).strip().lower()
            await s.execute(
                update(VaultItem)
                .where(VaultItem.account_id == account_id, VaultItem.media_id == mid)
                .values(of_terms=json.dumps(sorted(terms)), search_text=new_search)
            )
        await s.execute(
            sqlite_insert(VaultOfQueryLog)
            .values(account_id=account_id, query=q, match_count=len(matched), fetched_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "query"],
                set_={"match_count": len(matched), "fetched_at": now},
            )
        )
        await s.commit()
    return {"query": q, "ids": matched, "count": len(matched), "source": "of"}


@router.post("/admin/vault-ai/search-of")
async def search_of(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    r = await _harvest_query(account_id, str(payload.get("query") or ""))
    return {"account_id": account_id, **r}


# ── Harvest the whole "what sells" keyword set (background) ─────────
_kw_running: set[str] = set()
_kw_progress: dict[str, dict[str, Any]] = {}


async def _run_harvest_keywords(account_id: str) -> None:
    try:
        client = await asyncio.to_thread(ax._make_client, account_id)
        total = len(_SELLING_KEYWORDS)
        done = 0
        matches = 0
        _kw_progress[account_id] = {"total": total, "done": 0, "matches": 0}
        for kw in _SELLING_KEYWORDS:
            r = await _harvest_query(account_id, kw, client=client)
            matches += int(r.get("count") or 0)
            done += 1
            _kw_progress[account_id] = {"total": total, "done": done, "matches": matches}
            await asyncio.sleep(0.1)
        log.info("harvest_keywords done account=%s matches=%s", account_id, matches)
    except Exception:  # noqa: BLE001
        log.exception("harvest_keywords failed account=%s", account_id)
    finally:
        _kw_running.discard(account_id)


@router.post("/admin/vault-ai/harvest-keywords")
async def harvest_keywords(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    if account_id in _kw_running:
        raise HTTPException(status_code=409, detail={"error": "harvest_already_running"})
    _kw_running.add(account_id)
    asyncio.create_task(_run_harvest_keywords(account_id))
    return {"account_id": account_id, "status": "running", "keywords": len(_SELLING_KEYWORDS)}


@router.get("/admin/vault-ai/harvest-keywords/status")
async def harvest_keywords_status(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    return {
        "account_id": account_id,
        "running": account_id in _kw_running,
        "progress": _kw_progress.get(account_id),
    }


# ── Edit-and-lock a mirror item (S10) ──────────────────────────────
# Operator edits to an item's description / tags / tier / caption / script.
# Per contract §3 write rule, each edited field is written into
# operator_overrides_json AND its name added to locked_fields_json AND projected
# into the legacy compat column of the same name — so a later forced describe
# rerun skips it (see _describe_one's locked-skip). We read the
# result back ONLY through effective_value(), never the raw column.

from vault_ai_effective import effective_value, locked_fields as _locked_fields, normalize_tags  # noqa: E402

# The only fields the editor may override+lock. `tags` is stored as a JSON list;
# every other field is free text.
_EDITABLE_FIELDS = (
    "description", "tags", "explicitness_tier", "suggested_caption", "suggested_script",
    # The exposure flags, editable wherever an item is editable rather than
    # only inside the review modal. They decide the folder, the price and
    # whether something may be mass-sent, so an operator who spots a wrong one
    # while doing something else should be able to fix it there and then. Same
    # override+lock contract as `description`: the edit wins at read time and a
    # forced re-flag skips it.
    *vault_ai_brief.VIS_REGIONS,
    *vault_ai_brief.OVER_KEYS.values(),
    # Operator-set PPV price for this media, in CENTS. The AI never writes this
    # (vision classifies explicitness_tier instead — PLAN correction #3); it is
    # purely an operator choice, and the Composer prices an attachment set at the
    # MAX suggested price across the selection.
    "suggested_price_cents",
)


def _item_edit_view(item: VaultItem, locked: list[str]) -> dict[str, Any]:
    """Wire shape for an edited mirror row — every editable field read through
    effective_value() so the operator sees the override that just won, not a raw
    column. `video_description` is surfaced raw for the FE (S9 overlay reads it)."""
    return {
        "media_id": item.media_id,
        "id": item.media_id,
        "kind": item.kind,
        "description": effective_value(item, "description"),
        "video_description": item.video_description,
        "tags": effective_value(item, "tags", default=[]),
        "explicitness_tier": effective_value(item, "explicitness_tier"),
        "suggested_caption": effective_value(item, "suggested_caption"),
        "suggested_script": effective_value(item, "suggested_script"),
        "suggested_price_cents": effective_value(item, "suggested_price_cents"),
        "describe_status": item.describe_status,
        "locked_fields": locked,
    }


@router.patch("/admin/vault-ai/items/{media_id}")
async def edit_item(media_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Override + lock one or more editable fields on a mirror item.

    Body: `{account_id, fields: {description?, tags?, explicitness_tier?,
    suggested_caption?, suggested_script?}}`. Each supplied field is written to
    `operator_overrides_json`, added to `locked_fields_json`, and projected into
    the same-named legacy column (contract §3 + §6c). Returns the updated row
    (read via effective_value) and the full locked-field list.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    if not account_id:
        raise HTTPException(status_code=400, detail={"error": "account_id_required"})
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise HTTPException(status_code=400, detail={"error": "fields_required"})
    # Only known fields may be edited; ignore anything else the client sends.
    edits = {k: fields[k] for k in _EDITABLE_FIELDS if k in fields}
    if not edits:
        raise HTTPException(status_code=400, detail={"error": "no_editable_fields"})

    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is None:
            raise HTTPException(
                status_code=404, detail={"error": "not_in_mirror", "media_id": media_id}
            )
        col_vals = _edit_values(item, edits)
        await s.execute(
            update(VaultItem)
            .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
            .values(**col_vals)
        )
        await s.commit()
        # Re-read through the ORM so effective_value resolves the fresh columns.
        item = await s.get(VaultItem, (account_id, media_id))
        await s.refresh(item)
        locked_out = sorted(_locked_fields(item))
        view = _item_edit_view(item, locked_out)
    return {"item": view, "locked": locked_out}


def _edit_values(item: VaultItem, edits: dict[str, Any]) -> dict[str, Any]:
    """The column values that override + lock `edits` on `item` — `edit_item`'s
    rule, shared with the import's per-file details so an imported hashtag is
    exactly as sticky as a typed one. Raises 400 on a bad value."""
    overrides = load_json(item.operator_overrides_json, {}) or {}
    locked = set(load_json(item.locked_fields_json, []) or [])
    # compat-column projection per field (same-named legacy column).
    col_vals: dict[str, Any] = {}
    flag_edits: dict[str, Any] = {}
    for field, raw in edits.items():
        if field == "tags":
            ov: Any = normalize_tags(raw)
            col_vals["tags"] = json.dumps(ov)
        elif field == "suggested_price_cents":
            # Cents, non-negative. Blank/None clears it back to "no price".
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                ov = None
            else:
                try:
                    ov = max(0, int(float(raw)))
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "bad_price", "field": field},
                    )
            col_vals[field] = ov
        elif field in vault_ai_brief.VIS_REGIONS:
            # Enum-constrained, and stored in `ai_fields_json` rather than
            # a column of its own — so it is written through the same path
            # the review modal uses instead of being projected here.
            if raw not in vault_ai_brief.VIS_STATES:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "bad_region_state", "field": field,
                            "allowed": list(vault_ai_brief.VIS_STATES)})
            ov = raw
            flag_edits[field] = raw
        elif field in vault_ai_brief.OVER_KEYS.values():
            ov = str(raw).strip()[:60] if raw else None
            flag_edits[field] = ov
        elif raw is None:
            ov = None
            col_vals[field] = None
        else:
            ov = str(raw)
            col_vals[field] = ov
        overrides[field] = ov       # operator override (locked or not — read-time wins)
        locked.add(field)            # lock: a describe rerun skips it
    if flag_edits:
        merged = load_json(item.ai_fields_json, {}) or {}
        for k, v in flag_edits.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        col_vals["ai_fields_json"] = json.dumps(merged, ensure_ascii=False,
                                                default=str)
    col_vals["operator_overrides_json"] = json.dumps(overrides, ensure_ascii=False)
    col_vals["locked_fields_json"] = json.dumps(sorted(locked))
    return col_vals


def _import_edits(item: VaultItem, meta: dict[str, Any]) -> dict[str, Any]:
    """An import's per-file details as `_edit_values` edits.

    `meta` is `vault_upload.parse_meta`'s shape (`{hashtags, tag_creators,
    price_cents, ...}`, already normalised) and is trusted as such. Hashtags
    and tagged creators (as `@handle`) are ADDED to the item's tags rather than
    replacing them — a re-import of media the AI has already described must not
    wipe its tags — and they go FIRST: the stored list is capped at 12, and an
    item that already had 12 tags would otherwise keep all of its own and drop
    every one the operator just typed. `notes` is not an edit (it has no
    override+lock contract); `apply_import_meta` writes it as a plain column."""
    add = [*(meta.get("hashtags") or []),
           *("@" + h for h in (meta.get("tag_creators") or []))]
    edits: dict[str, Any] = {}
    if add:
        # The legacy column is a JSON string; an override or AI value a list.
        have = effective_value(item, "tags", default=[]) or []
        if isinstance(have, str):
            have = load_json(have, []) or []
        edits["tags"] = [*add, *(have if isinstance(have, list) else [])]
    if meta.get("price_cents") is not None:
        edits["suggested_price_cents"] = meta["price_cents"]
    return edits


# Why an import's details found no row to land on: the account's vault was
# never collected into this relay's mirror, so the grid reads OnlyFans directly
# and there is nowhere to keep hashtags, notes or a price.
IMPORT_META_NO_ROW = ("this model's vault is not synced here yet, so there was "
                      "no vault row to save them on")


async def apply_import_meta(account_id: str, metas: dict[int, dict]) -> dict[str, Any]:
    """Write a finished import's per-file details onto its mirror rows.

    Called by the batch route once the landed ids are in the mirror. An id with
    no mirror row (the account was never collected — its grid reads OnlyFans,
    which has no tags) is skipped; one bad value skips that file, never the
    rest. Returns `{applied, skipped, why}` — the run record carries it, so the
    import card can say the details were not saved instead of the import
    reading as complete while they were dropped."""
    applied = 0
    why: list[str] = []
    async with get_session() as s:
        for media_id, meta in (metas or {}).items():
            item = await s.get(VaultItem, (account_id, int(media_id)))
            if item is None or not isinstance(meta, dict):
                why.append(IMPORT_META_NO_ROW)
                continue
            try:
                edits = _import_edits(item, meta)
                col_vals = _edit_values(item, edits) if edits else {}
            except HTTPException as e:
                log.warning("vault import: details for media=%s not applied: %s",
                            media_id, e.detail)
                why.append(f"a value was refused ({e.detail})")
                continue
            if notes := meta.get("notes"):
                col_vals["notes"] = notes
            if not col_vals:
                continue
            await s.execute(
                update(VaultItem)
                .where(VaultItem.account_id == account_id,
                       VaultItem.media_id == int(media_id))
                .values(**col_vals))
            applied += 1
        await s.commit()
    return {"applied": applied, "skipped": len(why),
            "why": "; ".join(dict.fromkeys(why)) or None}


@router.post("/admin/vault-ai/items/{media_id}/hide")
async def hide_item(media_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Remove ONE media from the real OF vault (operator-confirmed).

    Same mechanism the duplicates sweep uses — OF's own "Remove selected items
    from vault" (`PUT /vault/media/hidden`) via `of_client.hide_vault_media`: the
    media is HIDDEN, not destroyed, so anything already attached to a sent PPV or
    a live post keeps working. **OF exposes no unhide**, so the UI must confirm
    before calling this.

    Unlike /duplicates/hide there is no cluster to re-derive — the operator is
    pointing at one specific item — so the guards are ownership of the account
    and membership of the media: hiding cannot be undone, and a details drawer
    left open across a model switch pointed this at another model's media id.
    """
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    if not account_id:
        raise HTTPException(status_code=400, detail={"error": "account_id_required"})
    await vault_of_folders._reject_foreign_media(account_id, [int(media_id)])

    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        await asyncio.to_thread(client.hide_vault_media, [int(media_id)])
    except Exception as e:  # noqa: BLE001
        log.warning("vault item hide failed account=%s media=%s",
                    account_id, media_id, exc_info=True)
        raise HTTPException(status_code=502, detail={
            "error": "of_hide_failed", "detail": str(e)[:300],
            "media_id": int(media_id)})

    # Mirror the removal locally so the grid, the picker, the describe sweep and
    # every automation stop seeing it immediately — rather than waiting for the
    # next collect to notice it's gone.
    now = datetime.utcnow()
    async with get_session() as s:
        await s.execute(
            update(VaultItem)
            .where(VaultItem.account_id == account_id,
                   VaultItem.media_id == int(media_id))
            .values(removed_at=now)
        )
        await s.commit()
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001
        pass
    log.info("vault item hidden account=%s media=%s", account_id, media_id)
    return {"ok": True, "media_id": int(media_id), "hidden": True}
