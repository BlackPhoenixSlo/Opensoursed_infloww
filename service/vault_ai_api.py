"""service/vault_ai_api.py — whole-vault local mirror ("Collect all") + instant local read.

The "Collect all" button walks the entire OF vault ONCE and upserts every item
into the `vault_items` mirror, so afterward the grid + search are served LOCALLY
(instant, including never-before-typed queries) instead of round-tripping OF.

  POST /admin/vault-ai/collect?account_id=            → start a sweep, returns {run_id}
  POST /admin/vault-ai/collect/continue?account_id=   → a paused sweep walks on (409 if none)
  POST /admin/vault-ai/collect/stop?account_id=       → a paused sweep stops, warms, ends done
  GET  /admin/vault-ai/collect/status?account_id=     → latest run progress
  GET  /admin/vault-ai/cache/summary?account_id=      → {count, last_run}
  GET  /admin/vault-ai/items?account_id=&...           → read from the mirror (local search)

The sweep walks OF in the describe sweep's priority order (rail folders whole, newest,
oldest; `vault_collect_plan`), pausing every COLLECT_PAUSE_EVERY new items for the
operator, downloading each page's stills as it lands (`_run_collect`); it preserves every AI / operator
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
from sqlalchemy import case, func, literal, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax  # _make_client seam (same one automations use)
import vault_ai_vision  # flags + describe passes; routes included at their old spots below
import vault_ai_vision_decide  # rail_folder_ids: the folder rail's order
import vault_collect  # preempt: the Collect button stops the background walk of its account first
import vault_collect_plan  # which OF page the Collect asks next
# The permanent, signature-free picture stores (thumbs / full previews / DRM poster
# frames), including the whole route body behind the three serve endpoints below.
# This module keeps the SWEEP that fills them.
import vault_frames
import vault_mirror
import vault_of_folders  # duplicates list/hide, folder plan + publish, OF folder CRUD; routes included at their old spots below
import relay_coalesce
import vault_ingest  # has_live_mirror: the grid's own "is the mirror on" question
import vault_jev_flags
import vault_jev_manual  # the operator's Jev picks (`fields.jev`)
import vault_jev_rules  # JEV_KEY: a clip's per-frame answers stay out of `_overlay`
import vault_pack_picker
import vault_runs
import vault_stills
import vault_harvest_terms  # which words the OF-search harvest asks
import vault_tags  # the grid's tag chips: tag_match / facets SQL
import vault_folder_prices  # the agency's per-folder prices (Full AI sell)
import vault_internal_folders  # the Inflowwww folders editor (list + edits of our own folders)
# NOTE: the OF payload-shape readers (`still_url`, `giphy_dm_id`) are NOT imported
# here — `vault_frames` owns "which url in a payload is the picture" now, and this
# module reaches them through it.
from auth import assert_account_owned
from chatters import allowed_folder_ids_for_chatter
from db.engine import get_session
from db.models import (
    VaultCacheRun, VaultFolder, VaultFolderItem, VaultItem, VaultOfQueryLog,
)
from jsonsafe import load_json
from vault_mirror import in_of_folders

log = logging.getLogger("of-relay.vault_ai_api")

# Re-exported for callers that still reach them here (test_llm_zai_glm).
# Patch the originals on `vault_ai_vision` — patching a
# re-export here does not change what the sweep calls.
_describe_running = vault_ai_vision._describe_running  # the same set object
describe_all = vault_ai_vision.describe_all
describe_one = vault_ai_vision.describe_one

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
_SOFT_DENY = {"list": [], "hasMore": False, "source": "mirror"}


async def visible_ids(account_id: str, media_ids) -> set[int]:
    """The ids among `media_ids` the acting principal may see: all of them for an
    owner / unrestricted chatter (no DB read — the gate answers None first), else
    those whose mirror row is in its folders (a media the mirror has no row for is
    out: its folders are unknown). One query for all the ids, the listing's predicate."""
    ids = {int(m) for m in media_ids}
    allowed = await allowed_folder_ids_for_chatter(account_id)
    if allowed is None or not ids:
        return ids
    async with get_session() as s:
        return {m for (m,) in (await s.execute(
            select(VaultItem.media_id).where(
                VaultItem.account_id == account_id, VaultItem.media_id.in_(ids),
                vault_mirror.visible_to(allowed))
        )).all()}


async def assert_media_visible(account_id: str, *media_ids: int) -> None:
    """404 a restricted chatter's request naming media outside its folders — a
    still (even on a disk hit), a grade, a pack verdict, an edit,
    a hide, a reorder, a by-id read — or one the mirror has no row for."""
    ids = {int(m) for m in media_ids}
    if ids - await visible_ids(account_id, ids):
        raise HTTPException(status_code=404, detail="not_found")


async def assert_owner_scope(account_id: str) -> None:
    """Refuse a whole-vault operation for a folder-limited chatter."""
    if await allowed_folder_ids_for_chatter(account_id) is not None:
        raise HTTPException(status_code=403, detail={"error": "folder_not_allowed"})


async def assert_folder_visible(account_id: str, folder_id: int) -> None:
    """Refuse an OF folder outside a folder-limited chatter's scope."""
    allowed = await allowed_folder_ids_for_chatter(account_id)
    if allowed is not None and folder_id not in allowed:
        raise HTTPException(status_code=403, detail={"error": "folder_not_allowed"})


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


def _paced_call():
    """The manual sweep's OF call: on a thread, _PAGE_SLEEP_S after the previous one
    (the same `call(fn, **kw)` shape `vault_collect.hot_folders` takes)."""
    called = False

    async def call(fn: Any, **kw: Any) -> Any:
        nonlocal called
        if called:
            await asyncio.sleep(_PAGE_SLEEP_S)
        called = True
        return await asyncio.to_thread(fn, **kw)
    return call


class _Sweep:
    """One manual Collect's tally + per-batch picture warming. A media seen again on
    a later step (the newest 100 again in a folder, the asc walk reaching items
    already taken) is still upserted (bookkeeping refresh) but neither counted nor
    downloaded twice. Counted on upsert (`seen`); marked downloaded (`warmed`) only
    once its page's warm finished, so a failed warm is retried when the walk meets
    the media again."""

    def __init__(self, client: Any, account_id: str, run_id: int) -> None:
        self.client, self.account_id, self.run_id = client, account_id, run_id
        self.seen: set[int] = set()
        self.warmed: set[int] = set()
        self.pages = 0
        # media_id → (created_at, signed url, duration): storyboards warm at the end, newest first.
        self.videos: dict[int, tuple[datetime, str, float]] = {}

    async def batch(self, written: list) -> None:
        """Count the new media in an upserted page and download their stills now,
        so the first pages are usable before the walk goes on."""
        thumbs: list[tuple[int, str]] = []
        stills: list[tuple[int, str]] = []
        drm_posters: list[tuple[int, list[str]]] = []
        fresh: set[int] = set()
        for m, vals in written:
            mid = vals["media_id"]
            self.seen.add(mid)
            if mid in self.warmed or mid in fresh:
                continue
            fresh.add(mid)
            if vals.get("thumb_url"):
                thumbs.append((mid, vals["thumb_url"]))
            # The full-FRAME preview, not just the 300px square: after OF's signature
            # expires we can no longer fetch it, and a lazily-filled store means
            # whatever nobody happened to open is lost.
            still = vault_frames.describe_image_of(
                m.get("files") if isinstance(m.get("files"), dict) else {})
            if still:
                stills.append((mid, still))
            if m.get("type") == "video":
                vurl = vault_frames.video_url(m)
                if vurl:
                    self.videos[mid] = (vals.get("created_at") or datetime.min, vurl,
                                        float(m.get("duration") or 0))
                else:
                    # DRM: no sliceable mp4 → cache OF poster frames so the hover
                    # preview serves from disk, not a cold fetch.
                    pf = vault_frames.poster_frames(m)
                    if pf:
                        drm_posters.append((mid, pf))
        aid = self.account_id
        # All incremental: an already-cached file is skipped, so a re-collect only
        # pays for what is new.
        await _warm_store(self.client, aid, "thumbs",
                          [(vault_stills.thumb_path(aid, mid), u) for mid, u in thumbs])
        # ~960x1280, the copy the review UI reads.
        await _warm_store(self.client, aid, "images",
                          [(vault_stills.image_path(aid, mid), u) for mid, u in stills])
        # DRM clips can't be ffmpeg-storyboarded: OF's poster frames ARE the hover preview.
        await _warm_store(self.client, aid, "posters",
                          [(vault_stills.poster_path(aid, mid, idx), u)
                           for mid, frames in drm_posters for idx, u in enumerate(frames)])
        self.warmed |= fresh
        _warm_progress.pop(aid, None)   # back to the row's phase between batches

    async def page(self, items: list, folder_id: int | None = None) -> None:
        """One page (All desc / asc, or a folder's): upsert, warm, report progress."""
        written, _ = await vault_runs.upsert_page(self.account_id, items, self.run_id,
                                                  folder_id=folder_id)
        await self.batch(written)
        self.pages += 1
        await self.progress()

    async def progress(self) -> None:
        n = len(self.seen)
        await vault_runs.update_run(self.run_id, pages_done=self.pages, total_seen=n,
                                    upserted=n, phase="media")


COLLECT_PAUSE_EVERY = 2000      # new items between the button's "continue collecting?" asks
COLLECT_PAUSE_TIMEOUT_S = 1800  # an ask nobody answers stops the walk (manual_running is not held forever)


class _Gate:
    """One paused Collect waiting for the operator (`/collect/continue`, `/collect/stop`)."""

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.decision: str | None = None


_paused: dict[str, _Gate] = {}   # account → its paused Collect (in memory, like manual_running)


async def _ask_to_continue(account_id: str, run_id: int, sweep: _Sweep) -> str:
    """Pause the walk ("paused" row with its totals) until the operator answers:
    "continue", "stop", or "timeout" after COLLECT_PAUSE_TIMEOUT_S."""
    gate = _paused[account_id] = _Gate()
    try:
        n = len(sweep.seen)
        await vault_runs.update_run(run_id, status="paused", phase="paused",
                                    pages_done=sweep.pages, total_seen=n, upserted=n)
        try:
            await asyncio.wait_for(gate.event.wait(), COLLECT_PAUSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            return "timeout"
        return gate.decision or "stop"
    finally:
        _paused.pop(account_id, None)


def _stopped_error(n: int, answer: str) -> str:
    """A paused walk that did not go on: done, never a full walk (it carries an error)."""
    if answer == "timeout":
        return (f"stopped at {n} items: no answer to continue collecting "
                f"in {round(COLLECT_PAUSE_TIMEOUT_S / 60)} min")
    return f"stopped by operator at {n} items"


async def _run_collect(account_id: str, run_id: int, *, pause_every: int | None = None) -> None:
    """Background sweep in the describe sweep's priority order (`vault_collect_plan`),
    each page's stills downloaded as soon as it is upserted: the folder list
    (`vault_collect.folder_list`, also refilling the picker's cache the start just
    invalidated), then rounds of {the next 10 rail folders, each paged whole → the
    next 5 newest pages → the next oldest page} until All is walked (the two cursors
    met or one hit the end; only that is a full walk, `vault_runs.full_walk_done`)
    or capped at _MAX_PAGES All pages, and every folder is paged; then the video
    storyboards, newest first.

    Every `pause_every` new items (default COLLECT_PAUSE_EVERY; 0 = never: prepare
    content's harvest) it pauses and asks the operator; stop (or no answer within
    COLLECT_PAUSE_TIMEOUT_S) skips the rest of the walk, still warms the storyboards
    and ends done with `_stopped_error`."""
    every = COLLECT_PAUSE_EVERY if pause_every is None else pause_every
    try:
        # The button wins over the background collector: it stops its walk of
        # this account (cursor kept) before this one starts paging.
        await vault_collect.preempt(account_id)
        client = await asyncio.to_thread(ax._make_client, account_id)
        call = _paced_call()
        sweep = _Sweep(client, account_id, run_id)

        try:
            folders = vault_ai_vision_decide.rail_folder_ids(
                [{"list": await vault_collect.folder_list(account_id, client, call)}])
        except Exception as e:  # noqa: BLE001 — the folders are a head start, not the walk
            log.warning("vault_collect: folder list failed account=%s run=%s: %s",
                        account_id, run_id, e)
            folders = []
        plan = vault_collect_plan.CollectPlan(folders, max_pages=_MAX_PAGES, page=_PAGE)
        since = 0          # len(sweep.seen) at the start / the last continue
        stopped = None
        while (step := plan.next()) is not None:
            if step.kind == "folder":
                try:
                    t0 = datetime.utcnow()
                    resp = await call(client.vault_media, limit=_PAGE, offset=step.offset,
                                      type="all", list_id=step.list_id, sort="desc",
                                      field="recent", query=None, before_publish_date=None)
                    if step.offset == 0:   # the picker's page 0 of this folder, as hot_folders did
                        await vault_collect.cache_picker_head(account_id, step.list_id, resp, t0)
                    items = (resp or {}).get("list") or []
                    if items:
                        await sweep.page(items, folder_id=step.list_id)
                except Exception as e:  # noqa: BLE001 — one bad folder (OF or a warm) must not cost the walk
                    log.warning("vault_collect: folder %s page failed account=%s run=%s: %s",
                                step.list_id, account_id, run_id, e)
                    plan.skip_folder()
                    continue
            else:
                resp = await call(client.vault_media, limit=_PAGE, offset=step.offset,
                                  type="all", sort=step.kind)
                items = (resp or {}).get("list") or []
                if items:
                    await sweep.page(items)
            plan.feed(step, [m.get("id") for m in items if isinstance(m, dict)],
                      bool((resp or {}).get("hasMore")))
            if every > 0 and len(sweep.seen) - since >= every and plan.next() is not None:
                answer = await _ask_to_continue(account_id, run_id, sweep)
                if answer != "continue":
                    stopped = _stopped_error(len(sweep.seen), answer)
                    log.info("vault_collect %s account=%s run=%s", stopped, account_id, run_id)
                    break
                since = len(sweep.seen)
                await vault_runs.update_run(run_id, status="running", phase="media")

        # ── Storyboard-warming phase (incremental) ──────────────────
        # Extract + cache 12 frames for every video whose storyboard isn't
        # already on disk, newest first. Metadata and stills are already in,
        # so search + the grid are usable while this (slower) phase runs.
        # Re-collect only warms NEW videos — warm_one_sync short-circuits cached ones.
        videos = sorted(sweep.videos.values(), key=lambda v: v[0], reverse=True)
        await vault_runs.update_run(run_id, status="running", phase="warming")   # also out of "paused" on a stop
        warmed = 0
        _warm_progress[account_id] = {"phase": "warming", "warmed": 0, "warm_total": len(videos)}
        for _, vurl, vdur in videos:
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

        # Stopped by the operator, or by the page cap with All not walked: done,
        # but not a whole-vault walk (`vault_runs.full_walk_done`).
        error = stopped or (vault_runs.capped_error(_MAX_PAGES) if plan.capped else None)
        total = len(sweep.seen)
        await vault_runs.update_run(run_id, status="done", phase="done", pages_done=sweep.pages,
                                    total_seen=total, upserted=total, error=error,
                                    finished_at=datetime.utcnow())
        log.info("vault_collect done account=%s run=%s items=%s", account_id, run_id, total)
    except Exception as e:  # noqa: BLE001
        log.exception("vault_collect failed account=%s run=%s", account_id, run_id)
        try:
            await vault_runs.update_run(run_id, status="error", error=str(e)[:500],
                                        finished_at=datetime.utcnow())
        except Exception:  # noqa: BLE001
            pass
    finally:
        vault_runs.manual_running.discard(account_id)
        _warm_progress.pop(account_id, None)


@router.post("/admin/vault-ai/collect")
async def start_collect(account_id: str = Query(...)) -> dict[str, Any]:
    """Kick off a full-vault mirror sweep in the background."""
    assert_account_owned(account_id)
    run_id = await claim_collect(account_id)
    asyncio.create_task(_run_collect(account_id, run_id))
    return {"account_id": account_id, "run_id": run_id, "status": "running"}


def _answer_pause(account_id: str, decision: str) -> dict[str, Any]:
    gate = _paused.get(account_id)
    if gate is None or gate.decision is not None:
        raise HTTPException(status_code=409, detail={"error": "collect_not_paused"})
    gate.decision = decision
    gate.event.set()
    return {"account_id": account_id, "status": decision}


@router.post("/admin/vault-ai/collect/continue")
async def continue_collect(account_id: str = Query(...)) -> dict[str, Any]:
    """A paused Collect (every COLLECT_PAUSE_EVERY new items) walks on. 409 when none is paused."""
    assert_account_owned(account_id)
    return _answer_pause(account_id, "continue")


@router.post("/admin/vault-ai/collect/stop")
async def stop_collect(account_id: str = Query(...)) -> dict[str, Any]:
    """A paused Collect stops walking OF, warms what it has and ends done (not a full walk).
    409 when none is paused."""
    assert_account_owned(account_id)
    return _answer_pause(account_id, "stop")


async def claim_collect(account_id: str) -> int:
    """The Collect button's setup, shared with prepare content (full_ai_prepare): claim
    `manual_running` (409 when held), drop the OF listing cache, open the run row.
    The caller runs `_run_collect(account_id, run_id)`, which releases the claim."""
    if account_id in vault_runs.manual_running:
        raise HTTPException(status_code=409, detail={"error": "collect_already_running"})
    vault_runs.manual_running.add(account_id)
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
        return run.id


def _run_status(row: VaultCacheRun, account_id: str) -> str:
    """What this run's status actually IS, not what it last managed to write.

    A collect is a background task and its rows are finalised by the task
    itself, so a relay restart mid-sweep leaves `running` behind with nothing
    left to ever clear it. One prod row said `running / warming` for three days;
    it is also why 1,046 clips were never warmed, and the status endpoint
    reported the sweep as still in progress the whole time.

    `vault_runs.manual_running` is the only place a live sweep is tracked and it is process-local,
    so a row claiming to run for an account nobody is running IS orphaned — the
    process that owned it is gone. Read, never written: the stored row stays the
    honest record of what the task last wrote, and a reconciliation pass that
    could itself be interrupted is machinery this does not need. A live "paused" run
    (waiting on the operator) holds manual_running too, so only an orphaned one reads
    "interrupted"."""
    if row.status in ("running", "paused") and account_id not in vault_runs.manual_running:
        return "interrupted"
    return row.status


@router.get("/admin/vault-ai/collect/status")
async def collect_status(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        row = await vault_runs.latest_manual_run(s, account_id)
    if row is None:
        return {"account_id": account_id, "run": None}
    warm = _warm_progress.get(account_id)
    # A restricted chatter gets the run's state, never its whole-vault totals
    # (they would leak the size of folders it may not see).
    allowed = await allowed_folder_ids_for_chatter(account_id)
    return {
        "account_id": account_id,
        "run": {
            "id": row.id,
            "status": _run_status(row, account_id),
            # The warm loop's own phase (thumbs → images → posters → warming)
            # while it runs: the row is written once before the three stores, so
            # alone it showed "thumbs" while the counter reset per store.
            "phase": (warm or {}).get("phase") or row.phase,
            "total_seen": row.total_seen if allowed is None else None,
            "upserted": row.upserted if allowed is None else None,
            "pages_done": row.pages_done if allowed is None else None,
            "error": row.error if allowed is None else None,   # the cap's text names the vault's size
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "running": account_id in vault_runs.manual_running,
            "warmed": (warm or {}).get("warmed") if allowed is None else None,
            "warm_total": (warm or {}).get("warm_total") if allowed is None else None,
        },
    }


@router.get("/admin/vault-ai/cache/summary")
async def cache_summary(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    # A restricted chatter counts only its allowed folders' items — an "All"
    # count would leak the size of folders it may not see.
    allowed = await allowed_folder_ids_for_chatter(account_id)
    async with get_session() as s:
        count = (await s.execute(
            select(func.count()).select_from(VaultItem)
            .where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None),
                   vault_mirror.visible_to(allowed)))).scalar_one()
        last = await vault_runs.latest_manual_run(s, account_id)
        complete = await vault_runs.full_walk_done(s, account_id)
    return {
        "account_id": account_id,
        "count": int(count or 0),
        # A whole-vault walk has finished at least once (manual Collect or the
        # background collector), so the mirror can stand in for OF's listing.
        "complete": complete,
        "running": account_id in vault_runs.manual_running,
        "last_run": None if last is None else {
            "id": last.id, "status": _run_status(last, account_id),
            # Whole-vault, so owners only (same reason as `count`).
            "total_seen": last.total_seen if allowed is None else None,
            "finished_at": last.finished_at.isoformat() if last.finished_at else None,
        },
    }


_SYNC_MAX_PAGES = 5  # Refresh reads at most 500 media from OF; a bigger change is Collect's job


async def _sync_from_of(account_id: str, of_folder_id: int | None) -> dict[str, Any]:
    client = await asyncio.to_thread(ax._make_client, account_id)
    pages = seen = new = 0
    offset = 0
    while pages < _SYNC_MAX_PAGES:
        resp = await asyncio.to_thread(
            client.vault_media, limit=_PAGE, offset=offset, type="all", sort="desc",
            list_id=of_folder_id,
        )
        pages += 1
        written, known = await vault_runs.upsert_page(account_id, (resp or {}).get("list") or [],
                                                      folder_id=of_folder_id)
        if not written:
            break
        seen += len(written)
        fresh = len(written) - len(known)
        new += fresh
        # Newest first: a page with nothing new means the rest is already mirrored. A folder is read whole
        # (within the cap): a media moved INTO it is old, so only re-reading it updates its membership.
        if not (resp or {}).get("hasMore") or (of_folder_id is None and fresh == 0):
            break
        await asyncio.sleep(_PAGE_SLEEP_S)  # paced like Collect: never back-to-back OF reads
        offset += _PAGE
    return {"pages": pages, "seen": seen, "new": new}


@router.post("/admin/vault-ai/sync")
async def sync_from_of(account_id: str = Query(...), of_folder_id: int | None = Query(None)) -> dict[str, Any]:
    """Vault Pro's Refresh: what OnlyFans holds NOW. Drops the relay's OF listing cache (folders and media, so the
    next /api/of/v2/vault/* read goes to OF), then, when the grid reads the mirror, pages OF's live listing newest
    first (the open folder's, if any) and upserts it, so new media and folder membership show without a full
    Collect. Concurrent presses for one account and folder share one OF walk. A restricted chatter: a folder outside
    its own is 403; on All only the cache drop runs (All's walk and its seen/new counts are whole-vault: null)."""
    assert_account_owned(account_id)
    allowed = await allowed_folder_ids_for_chatter(account_id)
    if allowed is not None and of_folder_id is not None and of_folder_id not in allowed:
        raise HTTPException(status_code=403, detail={"error": "folder_not_allowed"})
    try:
        await vault_cache.invalidate(account_id)
    except Exception:  # noqa: BLE001 — invalidate degrades on its own; never fail the refresh on it
        log.warning("vault_cache invalidate failed for %s", account_id, exc_info=True)
    if allowed is not None and of_folder_id is None:
        return {"account_id": account_id, "mirror": None, "pages": 0, "seen": None, "new": None}
    if not await vault_ingest.has_live_mirror(account_id):
        return {"account_id": account_id, "mirror": False, "pages": 0, "seen": 0, "new": 0}
    try:
        r = await relay_coalesce.coalesce(("vault_sync", account_id, of_folder_id),
                                          lambda: _sync_from_of(account_id, of_folder_id))
    except Exception as e:  # noqa: BLE001 — OF unreachable: the grid still reloads what it has
        log.warning("vault sync failed account=%s folder=%s: %s", account_id, of_folder_id, e)
        raise HTTPException(status_code=502, detail=f"vault sync failed: {e}"[:300]) from None
    return {"account_id": account_id, "mirror": True, **r}


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
    await assert_media_visible(account_id, media_id)
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
    await assert_media_visible(account_id, media_id)
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
    await assert_media_visible(account_id, media_id)
    return await vault_stills.serve(
        account_id, media_id, vault_stills.poster_path(account_id, media_id, i),
        vault_frames.pick_poster(i))


def _ai_fields_view(item: VaultItem) -> dict[str, Any] | None:
    """`ai_fields_json` as the browser gets it (None: not a blob)."""
    ai = load_json(item.ai_fields_json, None)
    if not isinstance(ai, dict):
        return None
    jev = ai.get(vault_jev_rules.JEV_KEY)
    if isinstance(jev, dict) and ("frames" in jev or "undo" in jev):
        # a clip's per-frame Jev answers (~10 KB, read only by the rules) and the picks' undo record: never sent
        ai = {**ai, vault_jev_rules.JEV_KEY: {k: v for k, v in jev.items() if k not in ("frames", "undo")}}
    # `description`/`tags` are already served from their columns (which
    # carry any operator override); don't shadow them with the raw AI value.
    return {k: v for k, v in ai.items() if k not in ("description", "tags")}


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
    ai = _ai_fields_view(item)
    if ai is not None:
        base["_ai"]["fields"] = ai
    base["_ai"]["jev_picks"] = vault_jev_manual.stored(item.operator_overrides_json)
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


def _listing_where(type: str | None, query: str | None, tags: list[str]) -> list:
    """The grid's narrowing filters as SQL conditions (AND): media type, the search box, the tag chips.
    One definition for the listing, `/tag-facets` and `/folders/from-tags`, so a saved folder holds
    exactly what the grid showed."""
    out: list = []
    if type and type != "all":
        out.append(VaultItem.kind == type)
    q = (query or "").strip().lower()
    if q:
        like = f"%{q}%"
        out.append(
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
    out.extend(vault_tags.tags_where(tags))
    return out


def _not_nude():
    """SQL: Jev's current reading (`vault_jev_rules.current_sql`) says nothing is bare (lane5 "free") and no toy.
    No reading, an old one or `review` is not "not nude" (absence ≠ safe; docs/plans/ultra-mode/issues/09)."""
    ai = func.coalesce(VaultItem.ai_fields_json, "")
    ai_ok = case((func.json_valid(ai), ai), else_=literal("{}"))
    j = lambda path: func.json_extract(ai_ok, f"$._jev.{path}")  # noqa: E731
    return (vault_jev_rules.current_sql(VaultItem.ai_fields_json) & (j("lane5") == "free")
            & (func.coalesce(j("tags.toy_any"), "") != "y"))


@router.get("/admin/vault-ai/items")
async def local_items(
    account_id: str = Query(...),
    type: str = Query("all"),
    query: str | None = Query(None),
    sort: str = Query("newest"),
    internal_folder_id: int | None = Query(None),
    of_folder_id: int | None = Query(None),
    tags: list[str] | None = Query(None),
    not_nude: bool = Query(False),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Read the LOCAL mirror. Same {list, hasMore} shape as /api/of/v2/vault/media
    so the frontend swaps data source transparently. Search is a local LIKE-scan
    (instant). `internal_folder_id` filters to an internal folder and orders by
    its per-folder manual_order: 0 first, 1,2,3… from front, then unpinned by
    date, then …-3,-2,-1 (so -1 is dead last). `tags` (repeatable): only items
    carrying every one of them (`vault_tags.tag_match`, the grid's tag chips). `not_nude`: only
    media Jev currently reads as nothing bare, no toy (`_not_nude`)."""
    assert_account_owned(account_id)
    # Chatter folder limits, same rule as /api/of/v2/vault/media: a restricted
    # chatter gets only an allowed OF folder; All, internal folders and other
    # folders soft-deny in the listing's own shape.
    allowed = await allowed_folder_ids_for_chatter(account_id)
    if allowed is not None and (internal_folder_id is not None or of_folder_id is None
                                or of_folder_id not in allowed):
        return dict(_SOFT_DENY, list=[])
    where = _listing_where(type, query, vault_tags.parse_tags(tags)) + ([_not_nude()] if not_nude else [])

    def _apply_common(st):
        return st.where(*where) if where else st

    out: list[dict[str, Any]] = []
    mo = VaultFolderItem.manual_order

    async def _append_ordered_page(s, stmt) -> bool:
        """A folder view's page in manual_order (0 first, 1,2,3… from front, then
        unpinned by date, then …-3,-2,-1) appended to `out`; returns has_more."""
        bucket = case((mo.is_(None), 1), (mo >= 0, 0), else_=2)
        stmt = _apply_common(stmt)
        stmt = stmt.order_by(bucket, mo, VaultItem.created_at.desc(), VaultItem.media_id.desc()).limit(limit + 1).offset(offset)
        # Sort/page only keys and order values. Carrying each full media JSON
        # through the folder sort makes deep pages expensive on large vaults.
        page = stmt.with_only_columns(VaultItem.media_id, mo).subquery()
        page_order = page.c.manual_order
        page_bucket = case((page_order.is_(None), 1), (page_order >= 0, 0), else_=2)
        hydrated = (select(VaultItem, page_order)
                    .join(page, (VaultItem.account_id == account_id)
                          & (VaultItem.media_id == page.c.media_id))
                    .order_by(page_bucket, page_order, VaultItem.created_at.desc(), VaultItem.media_id.desc()))
        pairs = (await s.execute(hydrated)).all()
        for item, m_ord in pairs[:limit]:
            out.append(_overlay(item, m_ord))
        return len(pairs) > limit

    async with get_session() as s:
        if internal_folder_id is not None:
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
            has_more = await _append_ordered_page(s, stmt)
        elif of_folder_id is not None:
            # An OF folder, served from the mirror. Membership = of_folder_ids
            # (parsed from listStates); manual_order via a LEFT join on
            # vault_folder_items keyed by the OF list id.
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
                    in_of_folders([of_folder_id]),
                )
            )
            has_more = await _append_ordered_page(s, stmt)
        else:
            stmt = select(VaultItem).where(
                VaultItem.account_id == account_id, VaultItem.removed_at.is_(None)
            )
            stmt = _apply_common(stmt)
            # media_id breaks created_at ties: a page boundary on equal timestamps must not repeat or skip items.
            old = sort == "oldest"
            stmt = stmt.order_by(
                VaultItem.created_at.asc() if old else VaultItem.created_at.desc(),
                VaultItem.media_id.asc() if old else VaultItem.media_id.desc(),
            ).limit(limit + 1).offset(offset)
            rows = (await s.execute(stmt)).scalars().all()
            has_more = len(rows) > limit
            for item in rows[:limit]:
                out.append(_overlay(item))
    return {"list": out, "hasMore": has_more, "source": "mirror"}


# ── Tag chips (SQL: vault_tags) ─────────────────────────────────────

def _chip_scope(account_id: str, of_folder_id: int | None) -> list:
    """The rows a chip read covers: this Creator's live mirror, narrowed to an OF folder when one is open."""
    out = [VaultItem.account_id == account_id, VaultItem.removed_at.is_(None)]
    if of_folder_id is not None:
        out.append(in_of_folders([of_folder_id]))
    return out


@router.get("/admin/vault-ai/tag-facets")
async def tag_facets(
    account_id: str = Query(...),
    type: str = Query("all"),
    query: str | None = Query(None),
    of_folder_id: int | None = Query(None),
    tags: list[str] | None = Query(None),
) -> dict[str, Any]:
    """The grid's tag chips: the top `vault_tags.FACET_LIMIT` tags with item counts over what the grid
    shows now (type, search, open OF folder, the chips already picked), plus `total`, the items matching
    all of it — the size of a "save as folder". One SELECT, folded in Python; no per-tag query. Same chatter gate as the
    listing: a restricted chatter gets chips only inside an allowed OF folder."""
    assert_account_owned(account_id)
    allowed = await allowed_folder_ids_for_chatter(account_id)
    picked = vault_tags.parse_tags(tags)
    if allowed is not None and (of_folder_id is None or of_folder_id not in allowed):
        return {"tags": [], "total": 0, "selected": picked}
    where = _chip_scope(account_id, of_folder_id) + _listing_where(type, query, picked)
    async with get_session() as s:
        rows = (await s.execute(vault_tags.facet_rows_stmt(where))).all()
    return {"tags": [{"tag": t, "count": n} for t, n in vault_tags.count_facets(rows)],
            "total": len(rows), "selected": picked}


@router.post("/admin/vault-ai/folders/from-tags")
async def folder_from_tags(payload: dict = Body(...)) -> dict[str, Any]:
    """"Save as folder": an INTERNAL folder holding exactly what the grid shows under the picked chips
    (same filters as the listing: tags AND, plus type / search / open OF folder), resolved here from the
    mirror, never from client ids — the grid holds one page, the result may be thousands.

    `created_by="operator"`, so vault_scripts' reaper (created_by="vault_ai_script" AND `AI-`) never
    retires it. No OF write: publishing it is the existing /folders/{id}/publish. The name defaults to
    the tags joined and never lands on an existing live folder name (`vault_tags.unique_name`).
    Owner scope: a folder-limited chatter is refused (403) as for the folder plan. More than
    `vault_tags.FOLDER_MAX_ITEMS` matches: 400 `too_many_items` with the count, nothing written."""
    account_id = str(payload.get("account_id") or "")
    assert_account_owned(account_id)
    await assert_owner_scope(account_id)
    picked = vault_tags.parse_tags(payload.get("tags") or [])
    if not picked:
        raise HTTPException(status_code=400, detail={"error": "tags_required"})
    raw_folder = payload.get("of_folder_id")
    try:
        of_folder_id = int(raw_folder) if raw_folder not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"error": "bad_of_folder_id"}) from None
    name = str(payload.get("name") or "").strip()[:120] or vault_tags.default_folder_name(picked)
    where = _chip_scope(account_id, of_folder_id) + _listing_where(
        str(payload.get("type") or "all"), payload.get("query"), picked)
    async with get_session() as s:
        ids = [int(m) for m in (await s.execute(
            select(VaultItem.media_id).where(*where)
            .order_by(VaultItem.created_at.desc(), VaultItem.media_id.desc())
        )).scalars().all()]
        if not ids:
            raise HTTPException(status_code=400, detail={"error": "no_items"})
        if len(ids) > vault_tags.FOLDER_MAX_ITEMS:
            raise HTTPException(status_code=400, detail={
                "error": "too_many_items", "count": len(ids), "cap": vault_tags.FOLDER_MAX_ITEMS,
                "message": f"{len(ids):,} items match; a saved folder holds at most "
                           f"{vault_tags.FOLDER_MAX_ITEMS:,}. Pick another chip or filter to narrow it."})
        used = set((await s.execute(select(VaultFolder.name).where(
            VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None)))).scalars().all())
        folder = VaultFolder(account_id=account_id, name=vault_tags.unique_name(name, used),
                             created_by=vault_pack_picker.CREATED_BY)
        s.add(folder)
        await s.flush()
        await s.execute(sqlite_insert(VaultFolderItem), [
            {"account_id": account_id, "folder_id": folder.id, "media_id": m} for m in ids])
        await s.commit()
        folder_id, saved_name = folder.id, folder.name
    log.info("vault tag folder account=%s folder=%s tags=%s items=%d", account_id, folder_id, picked, len(ids))
    return {"account_id": account_id, "folder_id": folder_id, "name": saved_name,
            "tags": picked, "items": len(ids)}


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
    allowed = await allowed_folder_ids_for_chatter(account_id)
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
        if allowed is not None and f["id"] not in allowed:
            continue  # a restricted chatter sees its allowed folders only
        f["mediaCount"] = (
            f["photosCount"] + f["videosCount"] + f["gifsCount"] + f["audiosCount"]
        )
        f["builtin"] = (f["name"] or "").strip().lower() in _BUILTIN_FOLDER_NAMES
        out.append(f)
    out.sort(key=lambda x: (x["name"] or "").lower())
    return {"list": out, "source": "mirror"}


# ── Internal folders (our own, zero OF writes) ──────────────────────
# List + the Inflowwww folders editor's writes live in `vault_internal_folders`; included HERE so the
# list route keeps its place in the registration order.
router.include_router(vault_internal_folders.router)


# ── Folder prices (Full AI sell; our DB only, zero OF writes) ───────


@router.get("/admin/vault-ai/folder-prices")
async def list_folder_prices(account_id: str = Query(...)) -> dict[str, Any]:
    """The account's priced folders, `{"list": [{"ref", "price_cents"}]}` sorted by ref (`vf:<id>` /
    `of:<id>`, `vault_folder_prices`). Owner scope: a folder-limited chatter is refused (403)."""
    if not account_id:
        raise HTTPException(status_code=400, detail={"error": "account_id_required"})
    assert_account_owned(account_id)
    await assert_owner_scope(account_id)
    prices = await vault_folder_prices.load(account_id)
    return {"list": [{"ref": r, "price_cents": c} for r, c in sorted(prices.items())]}


@router.post("/admin/vault-ai/folder-prices")
async def set_folder_price(payload: dict = Body(...)) -> dict[str, Any]:
    """Set (`price_cents` in [$10, $200], whole cents) or clear (`price_cents: null`) one folder's price.
    `ref` is `vf:<id>` (a live internal folder of this account, else 404) or `of:<OF list id>`. Owner
    scope as the folder plan (403 for a folder-limited chatter). Writes our DB only, never OF. 400s:
    account_id_required, bad_ref, bad_price (with min / max)."""
    account_id = str(payload.get("account_id") or "")
    if not account_id:
        raise HTTPException(status_code=400, detail={"error": "account_id_required"})
    assert_account_owned(account_id)
    await assert_owner_scope(account_id)
    ref = vault_folder_prices.parse_ref(payload.get("ref"))
    if ref is None:
        raise HTTPException(status_code=400, detail={"error": "bad_ref"})
    raw = payload.get("price_cents")
    cents = None if raw is None else vault_folder_prices.parse_cents(raw)
    if raw is not None and cents is None:
        raise HTTPException(status_code=400, detail={
            "error": "bad_price", "min": vault_folder_prices.MIN_CENTS, "max": vault_folder_prices.MAX_CENTS})
    if ref.startswith("vf:"):
        async with get_session() as s:
            live = (await s.execute(select(VaultFolder.id).where(
                VaultFolder.account_id == account_id, VaultFolder.id == int(ref[3:]),
                VaultFolder.deleted_at.is_(None)))).first()
        if live is None:
            raise HTTPException(status_code=404, detail="not_found")
    await vault_folder_prices.put(account_id, ref, cents)
    return {"account_id": account_id, "ref": ref, "price_cents": cents}


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


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
    # A restricted chatter orders only media it can see, inside one of its folders.
    allowed = await allowed_folder_ids_for_chatter(account_id)
    if allowed is not None and folder_id is not None and _int_or_none(folder_id) not in allowed:
        raise HTTPException(status_code=404, detail="not_found")
    rows: list[tuple[int, int | None]] = []   # parsed once: the gate checks exactly what is written
    for r in order:
        mid = _int_or_none(r.get("media_id")) if isinstance(r, dict) else None
        if mid is None:
            continue
        mo = r.get("manual_order")
        rows.append((mid, int(mo) if mo is not None and str(mo).lstrip("-").isdigit() else None))
    await assert_media_visible(account_id, *(mid for mid, _ in rows))
    n = 0
    async with get_session() as s:
        for mid, mo in rows:
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

def _unknown_category() -> HTTPException:
    """400 for a pack category `vault_pack_picker` does not know."""
    return HTTPException(status_code=400, detail={
        "error": "unknown_category",
        "known": sorted(vault_pack_picker.CATEGORIES)})


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
        raise _unknown_category() from None
    # A restricted chatter's candidates come from its folders only (the listing's rule).
    allowed = await allowed_folder_ids_for_chatter(account_id)
    return {"account_id": account_id,
            **await vault_pack_picker.candidates(account_id, cat, limit=limit, allowed=allowed)}


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
        raise _unknown_category() from None
    except vault_pack_picker.UnknownRung as e:
        raise HTTPException(status_code=400, detail={
            "error": "unknown_rung", "rung": str(e)}) from None
    except vault_pack_picker.InvalidMediaIds as e:
        raise HTTPException(status_code=400, detail={
            "error": "invalid_media_ids", "media_ids": e.media_ids}) from None
    if not verdicts:
        raise HTTPException(status_code=400, detail={"error": "verdicts_required"})
    await assert_media_visible(account_id, *verdicts)  # a chatter files only what it may see

    try:
        folders = await vault_pack_picker.triage(
            account_id, cat, verdicts, allowed=await allowed_folder_ids_for_chatter(account_id))
    except vault_pack_picker.NotFreeSafe as e:
        # Jev says her body may be on show: never the free preview rung. Nothing was written.
        raise HTTPException(status_code=400, detail={
            "error": "not_free_safe", "rung": cat.free_rung, "media_ids": e.media_ids}) from None
    except vault_pack_picker.PhotosOnly as e:
        # A pack is photos only (owner, 2026-11-12): no clip on any rung. Nothing was written.
        raise HTTPException(status_code=400, detail={
            "error": f"{cat.name}_photos_only", "media_ids": e.media_ids}) from None
    return {
        "account_id": account_id,
        "category": cat.name,
        "saved": len(verdicts),
        "rejected": sum(1 for r in verdicts.values() if r is None),
        "folders": folders,
    }


import vault_cache  # noqa: E402


import vault_ai_brief  # noqa: E402  (canonical FLAG_KEYS + flags_known)
import vault_ai_fix  # noqa: E402  (the flags grading loop)

# ── Duplicates list + AI folder plan (preview / apply / publish) ────
# Lives in `vault_of_folders`; routes included HERE so registration order is
# what it was before the split.
router.include_router(vault_of_folders.plan_router)


# ── Flags pass (vision) ─────────────────────────────────────────────
# Lives in `vault_ai_vision`; its routes are included HERE so registration
# order (and so the OpenAPI schema) is what it was before the split.
router.include_router(vault_ai_vision.flags_router)


# Chatter folder limits on the review routes below (flags review, the pack
# picker above): the listing's gate. A restricted chatter is shown and
# counted only media in its folders, and may grade or file only those —
# an outside media 404s as a still does (`assert_media_visible`).
def _media_id(payload: dict) -> int:
    """`payload["media_id"]` as an int, else 400 media_id_required."""
    try:
        return int(payload.get("media_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"error": "media_id_required"})


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
                                           only_iffy=only_iffy,
                                           allowed=await allowed_folder_ids_for_chatter(account_id))


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
    media_id = _media_id(payload)
    await assert_media_visible(account_id, media_id)
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
                                             version=vault_ai_vision._FLAGS_VERSION,
                                             allowed=await allowed_folder_ids_for_chatter(account_id))


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
# 30 pages x 100 = 3,000 hits per term. Was 6 x 40 = 240, and every common term
# (ass, cum, pussy, face, solo) hit exactly 240 on AE 562666533 (2026-11-13).
_OF_SEARCH_PAGE = 100
_OF_SEARCH_MAX_PAGES = 30
# A cache row stamped at the old cap was truncated: re-ask OF instead of trusting it.
_OF_SEARCH_LEGACY_CAP = 240

# The term list (seed taxonomy + the account's own describe/Jev vocabulary)
# lives in `vault_harvest_terms`.


async def _harvest_query(account_id: str, q: str, client: Any = None) -> dict[str, Any]:
    """Harvest OF's own vault search for `q` and fold the term into each matched
    mirror item's of_terms/search_text. TTL-cached via vault_of_query_log."""
    q = (q or "").strip().lower()
    if not q:
        return {"query": q, "count": 0, "source": "empty", "ids": []}
    now = datetime.utcnow()
    async with get_session() as s:
        logrow = await s.get(VaultOfQueryLog, (account_id, q))
    if (logrow and (now - logrow.fetched_at).total_seconds() < _OF_SEARCH_TTL_S
            and logrow.match_count != _OF_SEARCH_LEGACY_CAP):
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
                client.vault_media, limit=_OF_SEARCH_PAGE, offset=offset, type="all", sort="desc", query=q,
            )
        except Exception:  # noqa: BLE001
            break
        items = (resp or {}).get("list") or []
        if not items:
            break
        matched += [int(it["id"]) for it in items if it.get("id") is not None]
        if not (resp or {}).get("hasMore"):
            break
        offset += _OF_SEARCH_PAGE

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
    # A restricted chatter gets only ids in its allowed folders (the picker's
    # mirror search calls this for chatters too). Owners / unrestricted: as is.
    ok = await visible_ids(account_id, r.get("ids") or [])
    ids = [i for i in r.get("ids") or [] if i in ok]
    r = {**r, "ids": ids, "count": len(ids)}
    return {"account_id": account_id, **r}


# ── Harvest the whole "what sells" keyword set (background) ─────────
_kw_running: set[str] = set()
_kw_progress: dict[str, dict[str, Any]] = {}


async def _harvest_terms_for(account_id: str) -> list[str]:
    """Seed + this account's own most frequent describe/Jev words."""
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.ai_fields_json).where(
                VaultItem.account_id == account_id, VaultItem.removed_at.is_(None),
                VaultItem.ai_fields_json.is_not(None))
        )).scalars().all()
    return vault_harvest_terms.harvest_terms(load_json(r, None) for r in rows)


async def _run_harvest_keywords(account_id: str) -> None:
    try:
        client = await asyncio.to_thread(ax._make_client, account_id)
        terms = await _harvest_terms_for(account_id)
        total = len(terms)
        done = 0
        matches = 0
        _kw_progress[account_id] = {"total": total, "done": 0, "matches": 0}
        for kw in terms:
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
    return {"account_id": account_id, "status": "running"}


@router.get("/admin/vault-ai/harvest-keywords/status")
async def harvest_keywords_status(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    progress = _kw_progress.get(account_id)
    if progress is not None and await allowed_folder_ids_for_chatter(account_id) is not None:
        progress = {**progress, "matches": None}   # whole-vault hit count: owners only
    return {
        "account_id": account_id,
        "running": account_id in _kw_running,
        "progress": progress,
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
    # The operator's Jev picks ({key: value | None}, `vault_jev_manual`): laid
    # over the item's `_jev`, its flags + tier re-mapped from it.
    "jev",
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
        "fields": _ai_fields_view(item),
        "jev_picks": vault_jev_manual.stored(item.operator_overrides_json),
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
    await assert_media_visible(account_id, media_id)

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
    edits = dict(edits)
    jev_patch = None
    if "jev" in edits:
        try:
            jev_patch = vault_jev_manual.check(edits.pop("jev"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": "bad_jev_pick", "field": str(e)})
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
    if jev_patch is not None:
        _jev_edit(item, jev_patch, overrides, locked, col_vals,
                  keep_tier=vault_jev_flags.TIER_COLUMN in edits)
    col_vals["operator_overrides_json"] = json.dumps(overrides, ensure_ascii=False)
    col_vals["locked_fields_json"] = json.dumps(sorted(locked))
    return col_vals


def _jev_edit(item: VaultItem, patch: dict[str, Any], overrides: dict[str, Any], locked: set[str],
              col_vals: dict[str, Any], *, keep_tier: bool = False) -> None:
    """`_edit_values` for the Jev picks: stored in `overrides["_jev"]` (a cleared key removed), laid over the
    `_jev` (`vault_jev_manual.overlay`), the flags + `explicitness_tier` re-mapped from it. A body / lane pick
    is the operator's answer for what is bare, so it frees the vis flags they locked before (a lane also the
    tier, unless this same edit sets the tier: `keep_tier`); otherwise the old lock would keep a flag the new
    lane contradicts. Taking back a reading the picks alone made leaves the flags and the tier unknown."""
    picks = vault_jev_manual.merged(vault_jev_manual.stored(overrides), patch)
    if picks:
        overrides[vault_jev_manual.PICKS_KEY] = picks
    else:
        overrides.pop(vault_jev_manual.PICKS_KEY, None)
    unlock = [*vault_ai_brief.VIS_REGIONS] if any(k in patch for k in vault_jev_manual.BODY_PICKS) else []
    if "lane" in patch and not keep_tier:
        unlock.append(vault_jev_flags.TIER_COLUMN)
    for k in unlock:
        locked.discard(k)
        overrides.pop(k, None)
    fields = load_json(col_vals.get("ai_fields_json") or item.ai_fields_json, {}) or {}
    key = vault_jev_rules.JEV_KEY
    old = fields.get(key)
    new = vault_jev_manual.overlay(old, picks, vault_jev_manual.kind_of(old, item.kind))
    if new is None:
        fields.pop(key, None)
    else:
        fields[key] = new
    was = vault_jev_flags.reading(old)
    retracted = (was is not None and vault_jev_flags.reading(new) is None and isinstance(old, dict)
                 and old.get("made") == vault_jev_manual.MANUAL)
    if retracted:
        # the flags came from picks alone, now taken back: unknown again (the sweeps read the item)
        for k in (*was, "_flags_v", "_flags_model"):
            if k not in locked:
                fields.pop(k, None)
    fields = vault_jev_flags.apply(fields, fields.get(key), locked)
    col_vals["ai_fields_json"] = json.dumps(fields, ensure_ascii=False, default=str)
    if vault_jev_flags.TIER_COLUMN not in locked:
        tier = None if retracted else item.explicitness_tier
        col_vals[vault_jev_flags.TIER_COLUMN] = vault_jev_flags.column_tier(fields, tier, locked)


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
