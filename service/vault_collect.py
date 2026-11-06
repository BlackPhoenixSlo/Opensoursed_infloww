"""service/vault_collect.py — the vault week cache, filled slowly in the background.

One Creator at a time, never while someone is using it, at most one OF API call
per VAULT_COLLECT_GAP_S. Each walk, recorded as one `vault_cache_runs` row:

  auto:hot        (a) the folder list, paged exactly as the picker asks (50/page)
                  (b) page 0 of every dropdown folder (custom + hasMedia; limit 24)
                  (c) All's page 0 and its prefetch page (offset 24)
                  — each written to vault_cache under the picker route's own key
                  AND upserted into the vault_items mirror (no run id).
  auto:all:<off>  (d) the full walk of All (limit 100, sort asc), cursor in the
                  phase so a restart resumes at <off>. Only when the account has no
                  full walk (manual Collect, or an auto:done with pages_done > 0)
                  finished within FULL_S — so `complete` is re-earned weekly and
                  items beyond the hot pages reach the mirror at least weekly.
  auto:thumbs     (e) the newest 100 mirror items' thumbs into vault_stills'
                  permanent store (thumb only; CDN fetches, not GAP-paced).
  auto:done       finished; `finished_at` dates it for staleness.

Deletions stay lazy: nothing here removes mirror rows. A media OF has deleted is
stamped `removed_at` when a still request for it 404s on re-sign
(vault_stills.resolve_fresh), not by the walk.

Picking (one per tick): an unfinished `auto:*` run (resume) → an account with no
auto run → the stalest done run older than STALE_S, or an errored run past its
1 h backoff (after MAX_ATTEMPTS errors in a row the run is abandoned and a fresh
walk, hot set first, starts). Skipped while a manual Collect holds it
(vault_ai_api._running) or a user-priority request hit its lane within
USER_QUIET_S — unless that has kept it waiting MAX_SKIP_S, then it walks anyway.

The collector's own `_auto_running` is never vault_ai_api._running: the Collect
button must not 409 behind it. A manual Collect preempts instead (`preempt`):
the walk stops at its next OF call or sleep, marks its run `error: preempted`
(cursor kept) and lets go within one gap. Dead-session / OTP / deactivated
accounts are not candidates. Not reused: vault_ai_api's Collect (it also warms
full images, posters and storyboards, and sleeps 0.15 s between pages).

Env knobs (read at import):
  VAULT_COLLECT_ENABLED=1             0 = never registered
  VAULT_COLLECT_TICK_S=60             periodic interval
  VAULT_COLLECT_FIRST_AFTER_S=120     first tick after boot
  VAULT_COLLECT_GAP_S=5               seconds between OF API calls (end → next start)
  VAULT_COLLECT_STALE_S=21600         refresh the hot set + thumbs after 6 h
  VAULT_COLLECT_FULL_S=604800         redo the full All walk when the last one is older (7 d)
  VAULT_COLLECT_USER_QUIET_S=120      stay off an account used this recently
  VAULT_COLLECT_MAX_SKIP_S=1800       …unless skipped that long (bounded starvation)
  VAULT_COLLECT_THUMB_CONCURRENCY=2   parallel thumb fetches (0.5 s gap each)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select

import accounts as account_registry
import automation_executor as ax
import relay_host
import vault_ai_api
import vault_cache
import vault_frames
import vault_mirror
import vault_stills
from account_health import dead_session_map, deactivated_ids
from db.engine import get_session
from db.models import VaultCacheRun, VaultItem
from jsonsafe import load_json

log = logging.getLogger("of-relay.vault_collect")


def _env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


TICK_S = _env("VAULT_COLLECT_TICK_S", 60)
ENABLED = (os.environ.get("VAULT_COLLECT_ENABLED", "1").strip().lower()
           not in ("0", "false", "no", "off")) and TICK_S > 0
FIRST_AFTER_S = _env("VAULT_COLLECT_FIRST_AFTER_S", 120)
GAP_S = _env("VAULT_COLLECT_GAP_S", 5)
STALE_S = _env("VAULT_COLLECT_STALE_S", 21600)
FULL_S = _env("VAULT_COLLECT_FULL_S", 604800)
USER_QUIET_S = _env("VAULT_COLLECT_USER_QUIET_S", 120)
MAX_SKIP_S = _env("VAULT_COLLECT_MAX_SKIP_S", 1800)
THUMB_CONCURRENCY = max(1, int(_env("VAULT_COLLECT_THUMB_CONCURRENCY", 2)))
ERROR_BACKOFF_S = 3600
MAX_ATTEMPTS = 3          # consecutive errors on one run before a fresh walk
PREEMPT_WAIT_S = 10
THUMB_GAP_S = 0.5

LISTS_PAGE = 50          # useVaultMedia.ts fetchAllVaultLists
LISTS_MAX_PAGES = 20     # same hard cap as the picker
PICKER_PAGE = 24         # useVaultMedia.ts PAGE
WALK_PAGE = 100          # OF's cap; same as Collect
WALK_MAX_PAGES = 200     # 20k-item backstop, same as Collect
HOT_THUMBS = 100

P_HOT, P_THUMBS, P_DONE = "auto:hot", "auto:thumbs", "auto:done"
P_ALL = "auto:all:"

_walk_lock = asyncio.Lock()           # never two accounts at once
_auto_running: set[str] = set()        # the account being walked (≤1)
_abort: dict[str, asyncio.Event] = {}  # aid → set by `preempt`
_skipped_since: dict[str, float] = {}  # aid → monotonic() of its first skip in a row
_last_call_end = 0.0                   # monotonic() when the last OF call returned


# ── seams (tests patch these) ─────────────────────────────────────────

def _lane(aid: str):
    return relay_host.priority_lane_background(aid)


def _user_active_at(aid: str) -> float | None:
    return relay_host.last_user_activity_at(aid)


async def _live_accounts() -> list[str]:
    """OF accounts with a session, not flagged dead (wrong user / OTP / none)
    and not deactivated — the same filter link_metrics.prewarm_all uses."""
    live = [m["id"] for m in account_registry.list_accounts()
            if m.get("has_session") and m.get("platform", "onlyfans") == "onlyfans"]
    if not live:
        return []
    dead = await dead_session_map()
    off = await deactivated_ids()
    return [a for a in live if a not in dead and a not in off]


# ── preemption (manual Collect wins) ──────────────────────────────────

class Preempted(Exception):
    pass


def _check(aid: str) -> None:
    ev = _abort.get(aid)
    if (ev is not None and ev.is_set()) or aid in vault_ai_api._running:
        raise Preempted("preempted")


async def _sleep(aid: str, seconds: float) -> None:
    """Sleep, but wake (and raise Preempted) the moment `preempt` asks."""
    ev = _abort.setdefault(aid, asyncio.Event())
    if seconds > 0:
        try:
            await asyncio.wait_for(ev.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
    _check(aid)


async def preempt(aid: str) -> None:
    """Ask the walk of `aid` (if any) to stop; wait ≤PREEMPT_WAIT_S for it."""
    if aid not in _auto_running:
        return
    _abort.setdefault(aid, asyncio.Event()).set()
    deadline = time.monotonic() + PREEMPT_WAIT_S
    while aid in _auto_running and time.monotonic() < deadline:
        await asyncio.sleep(0.05)


vault_ai_api.preempt_auto = preempt


# ── pacing + one OF call ──────────────────────────────────────────────

async def _of_call(aid: str, fn: Callable[..., Any], **kw: Any) -> Any:
    """One OF API call: ≥GAP_S after the previous one returned, on a thread,
    holding the account's background lane only around the call itself."""
    global _last_call_end
    await _sleep(aid, _last_call_end + GAP_S - time.monotonic())

    def _run():
        with _lane(aid):
            return fn(**kw)
    try:
        return await asyncio.to_thread(_run)
    finally:
        _last_call_end = time.monotonic()


# ── run rows ──────────────────────────────────────────────────────────

async def _latest_auto_run(aid: str) -> VaultCacheRun | None:
    async with get_session() as s:
        return (await s.execute(
            select(VaultCacheRun)
            .where(VaultCacheRun.account_id == aid,
                   VaultCacheRun.phase.like(f"{vault_ai_api.AUTO_PHASE_PREFIX}%"))
            .order_by(VaultCacheRun.started_at.desc(), VaultCacheRun.id.desc())
            .limit(1)
        )).scalar_one_or_none()


async def _full_walk_fresh(aid: str) -> bool:
    """A whole-vault walk finished within FULL_S (vault_ai_api.full_walk_done)."""
    async with get_session() as s:
        return await vault_ai_api.full_walk_done(
            s, aid, since=datetime.utcnow() - timedelta(seconds=FULL_S))


def _attempts(run: VaultCacheRun) -> int:
    """Consecutive errors on this run, kept as the error's "[n] " prefix."""
    m = re.match(r"\[(\d+)\] ", run.error or "")
    return int(m.group(1)) if m else (1 if run.status == "error" else 0)


# ── picking ───────────────────────────────────────────────────────────

def _due_rank(run: VaultCacheRun | None, now: datetime) -> tuple | None:
    """Sort key for an account that is due, None when it is not."""
    if run is None:
        return (1, datetime.min)
    if run.status == "running":
        return (0, run.started_at or datetime.min)   # interrupted walk: resume first
    fin = run.finished_at or run.started_at or datetime.min
    if run.status == "error" and fin <= now - timedelta(seconds=ERROR_BACKOFF_S):
        return (2, fin)
    if run.status == "done" and fin <= now - timedelta(seconds=STALE_S):
        return (2, fin)
    return None


async def _pick() -> tuple[str, VaultCacheRun | None] | None:
    now = datetime.utcnow()
    due: list[tuple[tuple, str, VaultCacheRun | None]] = []
    for aid in await _live_accounts():
        run = await _latest_auto_run(aid)
        rank = _due_rank(run, now)
        if rank is not None:
            due.append((rank, aid, run))
    due.sort(key=lambda t: t[0])
    mono = time.monotonic()
    for _, aid, run in due:
        if aid in vault_ai_api._running:
            continue
        active = _user_active_at(aid)
        if active is None or mono - active >= USER_QUIET_S:
            _skipped_since.pop(aid, None)  # quiet: the skip streak is over
            return aid, run
        first = _skipped_since.setdefault(aid, mono)
        if mono - first >= MAX_SKIP_S:
            log.info("vault collect: %s busy for %.0fs, walking anyway", aid, mono - first)
            _skipped_since.pop(aid, None)
            return aid, run
    return None


async def tick() -> None:
    """One periodic pass: pick at most one account and walk it."""
    if _walk_lock.locked():
        return
    async with _walk_lock:
        picked = await _pick()
        if picked is None:
            log.debug("vault collect: nothing due")
            return
        aid, run = picked
        await walk(aid, run)


# ── the walk ──────────────────────────────────────────────────────────

async def _media_page(aid: str, client: Any, *, list_id: int | None, offset: int) -> int:
    """One picker page fetched exactly as /api/of/v2/vault/media would, cached
    under that route's key and folded into the mirror. Returns rows upserted."""
    resp = await _of_call(aid, client.vault_media, limit=PICKER_PAGE, offset=offset,
                          type="all", list_id=list_id, sort="desc", field="recent",
                          query=None, before_publish_date=None)
    key = vault_cache.vault_media_cache_key(type="all", list_id=list_id, offset=offset,
                                            limit=PICKER_PAGE, sort="desc", field="recent",
                                            q_norm="")
    await vault_cache.put(aid, key, resp)
    written, _ = await vault_ai_api._upsert_page(aid, (resp or {}).get("list") or [], folder_id=list_id)
    return len(written)


async def _hot(aid: str, client: Any) -> int:
    folders: list[dict] = []
    offset = 0
    for _ in range(LISTS_MAX_PAGES):
        resp = await _of_call(aid, client.vault_lists, view="main", limit=LISTS_PAGE,
                              offset=offset, query=None)
        await vault_cache.put(aid, vault_cache.vault_lists_cache_key(
            view="main", limit=LISTS_PAGE, offset=offset), resp)
        rows = (resp or {}).get("list") or []
        folders.extend(r for r in rows if isinstance(r, dict))
        if not (resp or {}).get("hasMore") or not rows:
            break
        offset += LISTS_PAGE
    n = 0
    for f in folders:  # the picker's dropdown: custom folders that have media
        if f.get("type") == "custom" and f.get("hasMedia") and f.get("id") is not None:
            n += await _media_page(aid, client, list_id=f["id"], offset=0)
    for off in (0, PICKER_PAGE):  # All: first page + the prefetched second
        n += await _media_page(aid, client, list_id=None, offset=off)
    return n


async def _thumbs(aid: str, client: Any) -> None:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.raw_json, VaultItem.thumb_url)
            .where(VaultItem.account_id == aid, VaultItem.removed_at.is_(None))
            .order_by(VaultItem.created_at.desc()).limit(HOT_THUMBS)
        )).all()
    todo: list[tuple[Any, str]] = []
    for mid, kind, raw, turl in rows:
        if not vault_mirror.has_still(kind):
            continue
        path = vault_stills.thumb_path(aid, mid)
        url = vault_frames.pick_thumb(load_json(raw, {}) or {}) or turl
        if url and not path.is_file():
            todo.append((path, url))
    queue: asyncio.Queue = asyncio.Queue()
    for t in todo:
        queue.put_nowait(t)

    def _fetch(url: str) -> bytes | None:
        with _lane(aid):
            return vault_stills.fetch_bytes_sync(client, url)

    async def _worker() -> None:
        while not queue.empty():
            _check(aid)
            path, url = queue.get_nowait()
            data = await asyncio.to_thread(_fetch, url)
            if data:
                vault_stills.write(path, data)
            await _sleep(aid, THUMB_GAP_S)

    await asyncio.gather(*(_worker() for _ in range(min(THUMB_CONCURRENCY, len(todo)))))


async def walk(aid: str, run: VaultCacheRun | None = None) -> None:
    """Walk one account, resuming `run` if it is unfinished. Never raises."""
    if aid in vault_ai_api._running:   # a manual Collect got there first
        return
    _auto_running.add(aid)
    _abort[aid] = asyncio.Event()
    run_id: int | None = None
    attempts = 0
    try:
        if run is not None and run.status == "error" and _attempts(run) >= MAX_ATTEMPTS:
            await vault_ai_api._update_run(run.id, status="abandoned")
            run = None
        if run is None or run.status == "done":
            async with get_session() as s:
                row = VaultCacheRun(account_id=aid, status="running", phase=P_HOT)
                s.add(row)
                await s.commit()
                run_id, phase = row.id, P_HOT
                pages, seen, upserted = 0, 0, 0
        else:
            run_id, phase = run.id, run.phase or P_HOT
            attempts = _attempts(run)
            pages, seen, upserted = run.pages_done or 0, run.total_seen or 0, run.upserted or 0
            # The error stays: its "[n] " prefix is the consecutive-error count.
            await vault_ai_api._update_run(run_id, status="running", finished_at=None)
            if phase.startswith(P_ALL) and await _full_walk_fresh(aid):
                phase = P_THUMBS   # e.g. the manual Collect that preempted us walked it
        client = await asyncio.to_thread(ax._make_client, aid)

        if phase == P_HOT:
            upserted += await _hot(aid, client)
            phase = P_THUMBS if await _full_walk_fresh(aid) else f"{P_ALL}0"
            await vault_ai_api._update_run(run_id, phase=phase, upserted=upserted)

        if phase.startswith(P_ALL):
            offset = int(phase[len(P_ALL):] or 0)
            while pages < WALK_MAX_PAGES:
                resp = await _of_call(aid, client.vault_media, limit=WALK_PAGE, offset=offset,
                                      type="all", sort="asc")
                items = (resp or {}).get("list") or []
                n = len((await vault_ai_api._upsert_page(aid, items))[0])
                seen += len(items)
                upserted += n
                pages += 1
                offset += WALK_PAGE
                more = bool(items) and bool((resp or {}).get("hasMore"))
                phase = f"{P_ALL}{offset}" if more else P_THUMBS
                await vault_ai_api._update_run(run_id, phase=phase, pages_done=pages, total_seen=seen,
                              upserted=upserted)
                if not more:
                    break
            phase = P_THUMBS
            await vault_ai_api._update_run(run_id, phase=phase)

        if phase == P_THUMBS:
            await _thumbs(aid, client)

        await vault_ai_api._update_run(run_id, status="done", phase=P_DONE, error=None,
                                       finished_at=datetime.utcnow())
        log.info("vault collect done account=%s run=%s pages=%s upserted=%s",
                 aid, run_id, pages, upserted)
    except Exception as e:  # noqa: BLE001 — a dead session must not kill the periodic
        log.warning("vault collect stopped account=%s run=%s: %s", aid, run_id, e)
        if run_id is not None:
            try:
                await vault_ai_api._update_run(run_id, status="error", error=f"[{attempts + 1}] {e}"[:500],
                              finished_at=datetime.utcnow())
            except Exception:  # noqa: BLE001
                pass
    finally:
        _auto_running.discard(aid)
        _abort.pop(aid, None)
