from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

import client_pool
import events
import of_pacing
import proxies
import purchase_poll
import purchase_poll_decide as poll_decide
import relay_host
import transaction_ingest
import view_lease
from env_knob import env_float
from fastapi import HTTPException

log = logging.getLogger("of-relay.app_open_warm")

# OF: "Please allow 1 seconds" (of_pacing.PAGE_GAP_S)
GAP_S = env_float("APP_OPEN_WARM_GAP_S", 1.0, 0.0)
REUSE_S = env_float("APP_OPEN_WARM_REUSE_S", 30.0, 0.0)
# Equals accounts_admin_api.ROSTER_COUNT_TTL_S (a test pins them)
FRESH_MAX_S = 300.0
FRESH_S = min(env_float("APP_OPEN_WARM_FRESH_S", FRESH_MAX_S, 0.0), FRESH_MAX_S, poll_decide.SLOW_S)
JOB_DEADLINE_S = 30.0

DIRECT = "direct"
_clock = time.monotonic
_warmed_at: dict[str, float] = {}
_failed_at: dict[str, float] = {}
_pending: set[str] = set()
_tasks: set[asyncio.Task] = set()


class _Job:
    __slots__ = ("feed", "poll", "run", "wanted")

    def __init__(self, feed: bool, poll: Callable[[str], Awaitable[Any]] | None,
                 run: Callable[[str], Awaitable[Any]] | None = None,
                 wanted: Callable[[str], Awaitable[bool]] | None = None) -> None:
        self.feed, self.poll, self.run, self.wanted = feed, poll, run, wanted

    @property
    def warm(self) -> bool:
        return self.poll is None and self.run is None


class _Exit:
    __slots__ = ("label", "jobs", "free_at", "held_until", "task")

    def __init__(self, label: str) -> None:
        self.label = label
        self.jobs: dict[str, _Job] = {}
        self.free_at = 0.0
        self.held_until = 0.0
        self.task: asyncio.Task | None = None


_exits: dict[str, _Exit] = {}


def _server():
    return relay_host.live_server()


async def _eligible(account_ids: Iterable[str]) -> list[str]:
    live = set(await transaction_ingest.live_account_ids())
    return [a for a in dict.fromkeys(account_ids) if a in live]


def _egress(account_id: str) -> tuple[str, str]:
    try:
        c = client_pool.get(account_id)
        key = proxies.egress_identity(getattr(c, "proxy_url", None), proxies.registry())
    except Exception:
        return DIRECT, DIRECT
    return key, of_pacing.exit_label(key)


def _current(account_id: str) -> bool:
    age = purchase_poll.last_poll_age_s(account_id)
    return age is not None and age < poll_decide.FAST_S


def just_polled(account_id: str) -> bool:
    age = purchase_poll.last_poll_age_s(account_id)
    return age is not None and age < poll_decide.SELECT_MIN_AGE_S


def current(account_id: str) -> bool:
    at = _warmed_at.get(account_id)
    return _current(account_id) or account_id in _pending or (at is not None and _clock() - at < REUSE_S)


def _ws_since(account_id: str) -> float | None:
    import of_ws
    return of_ws.connected_since(account_id)


def reuse_decision(*, pending: bool, warmed_age: float | None, failed_age: float | None, ws_kept: bool,
                   reuse_s: float = REUSE_S, fresh_s: float = FRESH_S) -> str:
    if pending:
        return "reused"
    if warmed_age is not None and (warmed_age < reuse_s or (ws_kept and warmed_age < fresh_s)):
        return "reused"
    if failed_age is not None and failed_age < reuse_s:
        return "skip"
    return "start"


def _decide(account_id: str, now: float) -> str:
    # lazy: shared_refresher imports this module
    import shared_refresher
    at, failed = _warmed_at.get(account_id), _failed_at.get(account_id)
    failed_age = None if failed is None else now - failed
    if shared_refresher.ENABLED:
        last = shared_refresher.last_refresh(account_id)
        return reuse_decision(pending=account_id in _pending, warmed_age=None if last is None else now - last,
                              failed_age=failed_age, ws_kept=True, fresh_s=shared_refresher.cycle_for(account_id))
    since = _ws_since(account_id) if at is not None else None
    return reuse_decision(pending=account_id in _pending,
                          warmed_age=None if at is None else now - at,
                          failed_age=failed_age,
                          ws_kept=since is not None and at >= since)


def _publish(account_id: str) -> None:
    try:
        values = _server().app_open_warm_values(account_id)
    except Exception:  # noqa: BLE001 — the event still goes; the tab re-reads what it lacks
        log.debug("app_open_warm_values failed account=%s", account_id, exc_info=True)
        values = {}
    now = datetime.now(timezone.utc)
    events.publish({"creator_warmed": {"account_id": account_id, "at": now.isoformat(timespec="seconds"),
                                       "now": int(now.timestamp() * 1000), **values},
                    "__account_id": account_id})


async def _warm_one(account_id: str, feed: bool) -> bool:
    async def run() -> bool:
        if feed and not _current(account_id):
            await purchase_poll.poll_now(account_id)
            if account_id not in set(await transaction_ingest.live_account_ids()):
                return False
        await _server().app_open_warm_reads(account_id)
        return True
    return await of_pacing.walk(account_id, "app_open_warm", run)


def _walk_done(t: asyncio.Task) -> None:
    _tasks.discard(t)
    if not t.cancelled() and t.exception() is not None:
        log.warning("shared_refresher_job_failed task=%s", t.get_name(), exc_info=t.exception())


async def _run(aid: str, job: _Job, label: str) -> bool:
    if job.run is not None:
        if not await job.wanted(aid):
            return False
        t = asyncio.create_task(job.run(aid), name=f"shared-refresher:{aid}")
        # Never cancelled: past the deadline its result still lands
        _tasks.add(t)
        t.add_done_callback(_walk_done)
        done, _ = await asyncio.wait({t}, timeout=JOB_DEADLINE_S)
        if not done:
            log.warning("shared_refresher_job_timeout account=%s proxy=%s", aid, label)
        return True
    if job.poll is not None:
        if _current(aid) or not view_lease.is_leased(aid):
            return False
        await job.poll(aid)
        return True
    ok = False
    try:
        if await _warm_one(aid, job.feed):
            ok = True
            _publish(aid)
    except asyncio.CancelledError:
        raise
    except HTTPException as exc:
        log.info("app_open_warm_skipped account=%s proxy=%s status=%s", aid, label, exc.status_code)
    except Exception:
        log.warning("app_open_warm_failed account=%s proxy=%s", aid, label, exc_info=True)
    finally:
        _pending.discard(aid)
        (_warmed_at if ok else _failed_at)[aid] = _clock()
        (_failed_at if ok else _warmed_at).pop(aid, None)
    return True


async def _work(key: str, ex: _Exit) -> None:
    try:
        while ex.jobs:
            wait = ex.free_at - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
                continue
            aid = next(iter(ex.jobs))
            job = ex.jobs.pop(aid)
            try:
                read = await _run(aid, job, ex.label)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("app_open_warm_gate_failed account=%s proxy=%s", aid, ex.label, exc_info=True)
                read = True
            if read:
                # max: a hold set meanwhile stands
                ex.free_at = max(ex.free_at, time.monotonic() + GAP_S)
    finally:
        ex.task = None
        for aid, job in ex.jobs.items():
            if job.warm:
                _pending.discard(aid)
        ex.jobs.clear()


def _gate(account_id: str) -> tuple[str, _Exit]:
    key, label = _egress(account_id)
    now = time.monotonic()
    for k in [k for k, e in _exits.items() if e.task is None and not e.jobs and e.free_at <= now]:
        del _exits[k]
    ex = _exits.get(key)
    if ex is None:
        ex = _exits[key] = _Exit(label)
    return key, ex


def _enqueue(account_id: str, job: _Job, *, front: bool = False) -> bool:
    key, ex = _gate(account_id)
    have = ex.jobs.get(account_id)
    took = have is None
    if have is not None:
        if job.warm and not have.warm:
            ex.jobs[account_id] = job
            took = True
        if front:
            ex.jobs = {account_id: ex.jobs.pop(account_id), **ex.jobs}
    elif front:
        ex.jobs = {account_id: job, **ex.jobs}
    else:
        ex.jobs[account_id] = job
    # Fresh context: the worker serves every caller's jobs, must not carry the starter's request/principal/lane lease
    if ex.task is None:
        t = ex.task = asyncio.create_task(_work(key, ex), name=f"app-open-warm:{ex.label}",
                                          context=contextvars.Context())
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return took


def note_read(account_id: str) -> None:
    _, ex = _gate(account_id)
    ex.free_at = max(ex.free_at, time.monotonic() + GAP_S)


# OF may ask any wait, inf included
HOLD_MAX_S = 900.0
HOLD_FLOOR_S = 60.0


def hold(account_id: str, wait_s: float) -> None:
    _, ex = _gate(account_id)
    # 429s follow the proxy IP; inf/nan clamp so a hold is never endless
    wait_s = wait_s if 0.0 <= wait_s <= HOLD_MAX_S else HOLD_MAX_S
    ex.held_until = max(ex.held_until, time.monotonic() + wait_s)
    ex.free_at = max(ex.free_at, ex.held_until)


def hold_on_429(account_id: str, exc: BaseException) -> float | None:
    status, body, header = of_pacing.upstream(exc.__cause__ or exc)
    if status != 429:
        return None
    wait = of_pacing.asked_wait(header, of_pacing.allow_s(body))
    wait = HOLD_FLOOR_S if wait is None else wait
    hold(account_id, wait)
    return wait


def exit_held_s(account_id: str) -> float:
    ex = _exits.get(_egress(account_id)[0])
    return 0.0 if ex is None else max(0.0, ex.held_until - time.monotonic())


async def start(principal: tuple[str, str], account_ids: Iterable[str], leased_first: Iterable[str] = (), *,
                refreshed: Iterable[str] = ()) -> dict[str, str]:
    now = _clock()
    done = set(refreshed)
    out: dict[str, str] = {}
    fresh: list[str] = []
    for aid in await _eligible(account_ids):
        call = _decide(aid, now)
        if call == "reused":
            out[aid] = "reused"
            if aid not in _pending:
                _publish(aid)
        elif call == "skip":
            continue
        else:
            out[aid] = "started"
            fresh.append(aid)
            _pending.add(aid)
    first = set(leased_first)
    ordered = sorted(fresh, key=lambda a: (a not in done, a not in first))
    for aid in [a for a in ordered if a in done][::-1]:
        _enqueue(aid, _Job(False, None), front=True)
    for aid in [a for a in ordered if a not in done]:
        _enqueue(aid, _Job(True, None))
    n_done = len(done & set(fresh))
    log.info("app_open_warm principal=%s:%s started=%d refreshed=%d reused=%d", principal[0],
             principal[1], len(fresh) - n_done, n_done, len(out) - len(fresh))
    return out


def pace(account_ids: Iterable[str], poll: Callable[[str], Awaitable[Any]]) -> None:
    for aid in dict.fromkeys(account_ids):
        _enqueue(aid, _Job(True, poll))


def refresh(account_id: str, run: Callable[[str], Awaitable[Any]], *,
            wanted: Callable[[str], Awaitable[bool]]) -> bool:
    return _enqueue(account_id, _Job(False, None, run, wanted))


def pending(account_id: str) -> bool:
    return account_id in _pending


def summary(result: dict[str, Any]) -> str:
    vals = set(result.values())
    return "started" if "started" in vals else "reused" if vals else "none"
