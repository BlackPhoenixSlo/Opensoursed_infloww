from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import select

import accounts as account_registry
import automation_executor as ax
import of_pacing
import relay_host
import vault_cache
import vault_frames
import vault_mirror
import vault_runs
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
PREEMPT_WAIT_S = 10
THUMB_GAP_S = 0.5

# Match app/hooks/useVaultMedia.ts (LISTS_PAGE 50, PAGE 24): the warm writes under the picker's own cache keys.
LISTS_PAGE = 50
LISTS_MAX_PAGES = 20
PICKER_PAGE = 24
WALK_PAGE = 100  # OF's cap; same as Collect
WALK_MAX_PAGES = 200
# Live links only (a dead one would 403); a cap of 100 left older tiles to cost their first viewer an OF re-sign + CDN fetch behind VAULT_STILL_CONCURRENCY.
THUMB_WARM_MAX = max(0, int(_env("VAULT_COLLECT_THUMB_WARM_MAX", 0)))

P_HOT, P_THUMBS, P_DONE = "auto:hot", "auto:thumbs", "auto:done"
P_ALL = "auto:all:"
P_CAPPED = P_THUMBS + ":capped"  # thumbs after a page-capped walk; survives a pause / error

_walk_lock = asyncio.Lock()  # never two accounts at once
_auto_running: set[str] = set()
_abort: dict[str, asyncio.Event] = {}
_skipped_since: dict[str, float] = {}
_last_call_end = 0.0
_rewarm: set[str] = set()


OfCall = Callable[..., Awaitable[Any]]



def _lane(aid: str):
    return relay_host.priority_lane_background(aid)


def _user_active_at(aid: str) -> float | None:
    return of_pacing.last_user_at(aid)


async def _live_accounts() -> list[str]:
    live = [m["id"] for m in account_registry.list_accounts()
            if m.get("has_session") and m.get("platform", "onlyfans") == "onlyfans"]
    if not live:
        return []
    dead = await dead_session_map()
    off = await deactivated_ids()
    return [a for a in live if a not in dead and a not in off]



class Preempted(Exception):
    pass


def _person_first(aid: str) -> bool:
    # The skip streak survives yields to a person and ends on finish/error/preempt, so a bursty person quiet at every pick but back mid-walk cannot starve the account.
    active, now = _user_active_at(aid), time.monotonic()
    if active is None or now - active >= USER_QUIET_S:
        return False
    return now - _skipped_since.setdefault(aid, now) < MAX_SKIP_S


def _check(aid: str) -> None:
    ev = _abort.get(aid)
    if (ev is not None and ev.is_set()) or aid in vault_runs.manual_running:
        raise Preempted("preempted")
    if _person_first(aid):
        raise Preempted("a person is using the account")


async def _sleep(aid: str, seconds: float) -> None:
    ev = _abort.setdefault(aid, asyncio.Event())
    if seconds > 0:
        try:
            await asyncio.wait_for(ev.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
    _check(aid)


async def preempt(aid: str) -> None:
    _skipped_since.pop(aid, None)
    if aid not in _auto_running:
        return
    _abort.setdefault(aid, asyncio.Event()).set()
    deadline = time.monotonic() + PREEMPT_WAIT_S
    while aid in _auto_running and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    if aid in _auto_running:
        log.warning("vault collect: %s still walking %.0fs after preempt; going ahead",
                    aid, PREEMPT_WAIT_S)


def request_rewarm(aid: str) -> None:
    _rewarm.add(aid)



async def _of_call(aid: str, fn: Callable[..., Any], **kw: Any) -> Any:
    # Pacer and 429 waits sleep inside OFClient.get_json, so the lane slot is held through them; excluding them needs a hook in of_pacing.
    global _last_call_end
    await _sleep(aid, _last_call_end + GAP_S - time.monotonic())

    def _run():
        with _lane(aid):
            return fn(**kw)
    try:
        return await of_pacing.walk(aid, "vault_collect", lambda: asyncio.to_thread(_run))
    finally:
        _last_call_end = time.monotonic()



async def _latest_auto_run(aid: str) -> VaultCacheRun | None:
    async with get_session() as s:
        return (await s.execute(
            select(VaultCacheRun)
            .where(VaultCacheRun.account_id == aid,
                   VaultCacheRun.phase.like(f"{vault_runs.AUTO_PHASE_PREFIX}%"))
            .order_by(VaultCacheRun.started_at.desc(), VaultCacheRun.id.desc())
            .limit(1)
        )).scalar_one_or_none()


async def _walked_recently(aid: str) -> bool:
    async with get_session() as s:
        return await vault_runs.walked_since(s, aid, datetime.utcnow() - timedelta(seconds=FULL_S))



def _due_rank(run: VaultCacheRun | None, now: datetime, rewarm: bool) -> tuple | None:
    if run is not None and run.status == "running":
        return (0, run.started_at or datetime.min)
    if rewarm:
        return (1, datetime.min)
    if run is None or run.status == "abandoned":  # "abandoned": a legacy terminal row
        return (2, datetime.min)
    fin = run.finished_at or run.started_at or datetime.min
    if run.status == "error" and fin <= now - timedelta(seconds=ERROR_BACKOFF_S):
        return (3, fin)
    if run.status == "done" and fin <= now - timedelta(seconds=STALE_S):
        return (3, fin)
    return None


async def _pick() -> tuple[str, VaultCacheRun | None] | None:
    now = datetime.utcnow()
    due: list[tuple[tuple, str, VaultCacheRun | None]] = []
    for aid in await _live_accounts():
        run = await _latest_auto_run(aid)
        rank = _due_rank(run, now, aid in _rewarm)
        if rank is not None:
            due.append((rank, aid, run))
    due.sort(key=lambda t: t[0])
    for _, aid, run in due:
        if aid in vault_runs.manual_running or _person_first(aid):
            continue
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
        await walk(*picked)



async def _media_page(aid: str, client: Any, call: OfCall, *, list_id: int | None, offset: int,
                      run_id: int | None = None) -> list[tuple[dict, dict[str, Any]]]:
    t0 = datetime.utcnow()
    resp = await call(client.vault_media, limit=PICKER_PAGE, offset=offset,
                      type="all", list_id=list_id, sort="desc", field="recent",
                      query=None, before_publish_date=None)
    key = vault_cache.vault_media_cache_key(type="all", list_id=list_id, offset=offset,
                                            limit=PICKER_PAGE, sort="desc", field="recent",
                                            q_norm="")
    await vault_cache.put(aid, key, resp, started_at=t0)
    written, _ = await vault_runs.upsert_page(aid, (resp or {}).get("list") or [], run_id,
                                              folder_id=list_id)
    return written


async def folder_list(aid: str, client: Any, call: OfCall) -> list[dict]:
    folders: list[dict] = []
    offset = 0
    for _ in range(LISTS_MAX_PAGES):
        t0 = datetime.utcnow()
        resp = await call(client.vault_lists, view="main", limit=LISTS_PAGE,
                          offset=offset, query=None)
        await vault_cache.put(aid, vault_cache.vault_lists_cache_key(
            view="main", limit=LISTS_PAGE, offset=offset), resp, started_at=t0)
        rows = (resp or {}).get("list") or []
        folders.extend(r for r in rows if isinstance(r, dict))
        if not (resp or {}).get("hasMore") or not rows:
            break
        offset += LISTS_PAGE
    return folders


async def cache_picker_head(aid: str, list_id: int | None, resp: Any,
                            started_at: datetime) -> None:
    rows = (resp or {}).get("list") or []
    head = {**(resp or {}), "list": rows[:PICKER_PAGE],
            "hasMore": len(rows) > PICKER_PAGE or bool((resp or {}).get("hasMore"))}
    key = vault_cache.vault_media_cache_key(type="all", list_id=list_id, offset=0,
                                            limit=PICKER_PAGE, sort="desc", field="recent",
                                            q_norm="")
    await vault_cache.put(aid, key, head, started_at=started_at)


async def hot_folders(aid: str, client: Any, call: OfCall) -> int:
    folders = await folder_list(aid, client, call)
    n = 0
    for f in folders:
        if f.get("type") == "custom" and f.get("hasMedia") and f.get("id") is not None:
            try:
                written = await _media_page(aid, client, call, list_id=f["id"], offset=0)
            except Preempted:
                raise
            except Exception as e:  # noqa: BLE001 — one bad folder must not cost the full walk
                log.warning("vault collect: folder %s page failed account=%s: %s", f["id"], aid, e)
                continue
            n += len(written)
    return n


async def _hot(aid: str, client: Any) -> int:
    call = functools.partial(_of_call, aid)
    n = await hot_folders(aid, client, call)
    for off in (0, PICKER_PAGE):
        n += len(await _media_page(aid, client, call, list_id=None, offset=off))
    return n


async def _thumbs(aid: str, client: Any) -> None:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.thumb_url)
            .where(VaultItem.account_id == aid, VaultItem.removed_at.is_(None))
            .order_by(VaultItem.created_at.desc())
        )).all()

    def _missing() -> list[tuple[Any, Any, str | None]]:
        return [(mid, path, turl) for mid, kind, turl in rows if vault_mirror.has_still(kind)
                for path in (vault_stills.thumb_path(aid, mid),) if not path.is_file()]
    missing = await asyncio.to_thread(_missing)
    now = time.time()
    todo: list[tuple[Any, str]] = []
    for i in range(0, len(missing), 500):
        if THUMB_WARM_MAX and len(todo) >= THUMB_WARM_MAX:
            break
        chunk = missing[i:i + 500]
        async with get_session() as s:
            raws = dict((await s.execute(
                select(VaultItem.media_id, VaultItem.raw_json)
                .where(VaultItem.account_id == aid, VaultItem.media_id.in_([m for m, _, _ in chunk]))
            )).all())
        for mid, path, turl in chunk:
            if THUMB_WARM_MAX and len(todo) >= THUMB_WARM_MAX:
                break
            url = vault_frames.pick_thumb(load_json(raws.get(mid), {}) or {}) or turl
            if url and not vault_stills.signed_url_expired(url, now):
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

    workers = [asyncio.create_task(_worker()) for _ in range(min(THUMB_CONCURRENCY, len(todo)))]
    try:
        await asyncio.gather(*workers)
    finally:
        # One worker's Preempted stops its siblings too: `walk` drops the abort flag on exit, so a sibling left running would fetch unchecked.
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


async def walk(aid: str, run: VaultCacheRun | None = None) -> None:
    if aid in vault_runs.manual_running:
        return
    _auto_running.add(aid)
    rewarm = aid in _rewarm  # dropped now: a setup that keeps failing must not stay rank 1 every tick
    _rewarm.discard(aid)
    _abort[aid] = asyncio.Event()
    run_id: int | None = None
    try:
        if run is None or run.status not in ("running", "error"):
            async with get_session() as s:
                row = VaultCacheRun(account_id=aid, status="running", phase=P_HOT)
                s.add(row)
                await s.flush()
                await vault_runs.prune_auto_runs(s, aid)
                await s.commit()
                run_id, phase = row.id, P_HOT
                pages, seen, upserted = 0, 0, 0
        else:
            run_id, phase = run.id, run.phase or P_HOT
            pages, seen, upserted = run.pages_done or 0, run.total_seen or 0, run.upserted or 0
            await vault_runs.update_run(run_id, status="running", error=None, finished_at=None)
        client = await asyncio.to_thread(ax._make_client, aid)

        if phase == P_HOT or rewarm:
            upserted += await _hot(aid, client)
            rewarm = False
            if phase == P_HOT:
                phase = f"{P_ALL}0"
            await vault_runs.update_run(run_id, phase=phase, upserted=upserted)

        if phase.startswith(P_ALL) and await _walked_recently(aid):
            # Another walk is fresh (e.g. the manual Collect that preempted us); pages_done 0 keeps this row out of vault_runs._walked (`complete`).
            phase, pages = P_THUMBS, 0
            await vault_runs.update_run(run_id, phase=phase, pages_done=0)

        if phase.startswith(P_ALL):
            offset = int(phase[len(P_ALL):] or 0)
            more = True
            while pages < WALK_MAX_PAGES:
                resp = await _of_call(aid, client.vault_media, limit=WALK_PAGE, offset=offset,
                                      type="all", sort="asc")
                items = (resp or {}).get("list") or []
                n = len((await vault_runs.upsert_page(aid, items))[0])
                seen += len(items)
                upserted += n
                pages += 1
                offset += WALK_PAGE
                more = bool(items) and bool((resp or {}).get("hasMore"))
                phase = f"{P_ALL}{offset}" if more else P_THUMBS
                await vault_runs.update_run(run_id, phase=phase, pages_done=pages, total_seen=seen,
                                            upserted=upserted)
                if not more:
                    break
            if more:  # the backstop, not the end of the vault: not a full walk
                log.warning("vault collect: walk capped at %s pages account=%s", WALK_MAX_PAGES, aid)
            phase = P_CAPPED if more else P_THUMBS
            await vault_runs.update_run(run_id, phase=phase)

        if phase.startswith(P_THUMBS):
            await _thumbs(aid, client)

        capped = vault_runs.capped_error(WALK_MAX_PAGES) if phase == P_CAPPED else None
        await vault_runs.update_run(run_id, status="done", phase=P_DONE, error=capped,
                                    finished_at=datetime.utcnow())
        _skipped_since.pop(aid, None)
        log.info("vault collect done account=%s run=%s pages=%s upserted=%s",
                 aid, run_id, pages, upserted)
    except Preempted as e:
        if rewarm:
            # The saved phase alone cannot remember unfinished hot pages.
            _rewarm.add(aid)
        log.info("vault collect paused account=%s run=%s: %s", aid, run_id, e)
    except Exception as e:  # noqa: BLE001 — a dead session must not kill the periodic
        log.warning("vault collect stopped account=%s run=%s: %s", aid, run_id, e)
        _skipped_since.pop(aid, None)
        if run_id is not None:
            try:
                await vault_runs.update_run(run_id, status="error", error=str(e)[:500],
                                            finished_at=datetime.utcnow())
            except Exception:  # noqa: BLE001
                pass
    finally:
        _auto_running.discard(aid)
        _abort.pop(aid, None)
