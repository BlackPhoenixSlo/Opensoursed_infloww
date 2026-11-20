"""
The App-open warm (ADR-0031, phase-01 1b): when an Employee opens Inflowwww on any page (the first
`POST /admin/view-lease` of a document load carries `opened: true`), every Creator they can access
gets ONE refresh, so the first screen anyone sees is current, even for Creators they never open.
As each Creator's reads land it publishes `creator_warmed`; every tab that can access the Creator
(events_decide.ANY_SCOPE_TYPES) writes the roster and notifications counts it carries and re-reads, from the warmed
cache, only the rail and bell entries it read before the warm.

  The one gate: every read this module makes goes through ONE queue per proxy exit (`proxies.egress_identity`
  of the Creator's client, the ledger pacer's exit key; "direct" without one), shared by every caller (`start`
  and `pace`, every renewal and every open): one Creator at a time on an exit, the next GAP_S after the last
  read there ended, exits in parallel. A Creator already queued on its exit is not queued again (a queued lease
  gain becomes the warm when an open asks for it), so a queue never holds more than the exit's Creators.
  note_read(account_id): a read outside the gate (the route's Select refresh of the selection, immediate)
      started on the Creator's exit now: the gate's next read there waits GAP_S.
  current(account_id) -> bool: no read needed now (polled within PURCHASES_POLL_FAST_S, ok or not, or warmed
      within REUSE_S, or queued in a warm): the view-lease route's lease-gain Select refresh skips it.
  just_polled(account_id) -> bool: polled within purchase_poll_decide.SELECT_MIN_AGE_S, ok or not: a selection
      reads no feed.
  pace(account_ids, poll): the view-lease route's other lease gains, `poll`ed through the gate, feed only: never
      one read each at once (a restart or a tab back from hidden re-leases many). At its turn a Creator polled
      within PURCHASES_POLL_FAST_S, or no longer leased (`view_lease.is_leased`), is skipped.
  refresh(account_id, run, *, wanted) -> bool: a Shared refresher job (docs/spec/watched-creator-refresher
      phase-01) through the gate; False when the Creator's entry is already held. A warm takes a queued refresh's
      place; a refresh never displaces a warm. At its turn `wanted(aid)` False drops it unread (no GAP_S); else
      `run(aid)` runs as its own task, the exit waiting at most JOB_DEADLINE_S: past it the exit is freed
      (`shared_refresher_job_timeout`), the walk never cancelled, its result still landing.
  hold(account_id, wait_s): a refresher read's terminal 429: the Creator's whole exit reads nothing, for any caller,
      before now + wait_s (a GAP_S after a read never shortens it).
  pending(account_id) -> bool: queued or reading in a warm now.
  start(principal, account_ids, leased_first, *, refreshed=()) -> {Creator: "started" | "reused"}
      Schedules the warm and returns at once. `account_ids` are the principal's (the route drops
      watchers); dead-session, deactivated and no-session Creators are skipped (absent from the
      answer; `transaction_ingest.live_account_ids`). `reuse_decision` per Creator: one queued or
      reading in a warm now, warmed within REUSE_S, or warmed within FRESH_S while its OF WebSocket has
      stayed connected since that warm landed (`of_ws.connected_since`: its frames keep the warmed
      window current, as roster-counts' `ws_kept`) is `reused` (one whose warm ended publishes
      `creator_warmed` at once: its entries are still served), `refreshed` or not: many Employees, or
      many tabs opening on one selection, cost one warm per Creator. With the Shared refresher on
      (Netting, ADR-0044) `warmed_age` is the age of the Creator's one Last refresh
      (`shared_refresher.last_refresh`, written by whichever of the refresher or a warm landed), `fresh_s`
      its Cycle (`shared_refresher.cycle_for`) and `ws_kept` True (the window invariant replaces the
      socket test): `reused` within its Cycle, socket up or down alike. One whose warm failed within
      REUSE_S is skipped (absent: the tab's own read covers it). The rest are `started` into the gate:
      `refreshed` (the route's Select
      refreshes, already running and `note_read`) at the front of their exit, their feed never read again
      here; then Creators in `leased_first`, then in `account_ids` order.
      Per Creator, one background walk (`of_pacing.walk`, Caller kind `walk:app_open_warm`, its pages
      paced per Creator), in order:
        1. one purchases poll (`purchase_poll.poll_now`, single-flight with the loop's tick),
           skipped when its last ok poll is younger than PURCHASES_POLL_FAST_S (a Demand Creator is
           current); a Creator it flags a Dead session reads nothing more;
        2-4. the server's `app_open_warm_reads` (looked up at call time): the chats window (roster-counts'
           recompute with bypass, rewarming the Fan List's page 0), the rail's tip and purchases lists
           and the notifications count, into the entries the pass-through routes serve; with the Shared
           refresher on, first `/users/me` bypassing the cache, and when it was kept and every read landed,
           the Creator's Last refresh (`shared_refresher.note_refresh`).
      At most 5 reads per Creator per REUSE_S (6 with the Shared refresher on). Then `creator_warmed`
      (house envelope); a Creator whose reads failed publishes nothing and is never `reused` (the tab's own read covers it).
      The warm only reads: no send, fan write or automation run waits on it.

Knobs, read here only: APP_OPEN_WARM_GAP_S (default 1.0, of_pacing.PAGE_GAP_S: OF's "Please allow
1 seconds"), APP_OPEN_WARM_REUSE_S (default 30, the notifications pass-through's cache TTL),
APP_OPEN_WARM_FRESH_S (default and cap FRESH_MAX_S 300, the roster count's TTL, the one entry the warm
re-reads past its cache; also at most PURCHASES_POLL_SLOW_S: a skipped warm skips its feed poll, so the
feed is never older than an Idle Creator's tier; under REUSE_S it adds nothing). The 30 s entries (money
lists, count) are not held past their TTL: a tab re-reads an expired one through the same cache. State is
in Relay memory by design: a restart's first open warms everything.
"""
from __future__ import annotations

import asyncio
import hashlib
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

GAP_S = env_float("APP_OPEN_WARM_GAP_S", 1.0, 0.0)
REUSE_S = env_float("APP_OPEN_WARM_REUSE_S", 30.0, 0.0)
FRESH_MAX_S = 300.0                     # accounts_admin_api.ROSTER_COUNT_TTL_S (a test pins them equal)
FRESH_S = min(env_float("APP_OPEN_WARM_FRESH_S", FRESH_MAX_S, 0.0), FRESH_MAX_S, poll_decide.SLOW_S)
JOB_DEADLINE_S = 30.0                   # a refresh job's hold on its exit (phase-01 shared refresher, Pacing)

DIRECT = "direct"                       # proxies.egress_identity's key (and the label) without a proxy
_clock = time.monotonic                 # the reuse memo's clock (tests inject one)
_warmed_at: dict[str, float] = {}       # Creator -> when its warm's reads landed (or found current)
_failed_at: dict[str, float] = {}       # Creator -> when its warm failed: not tried again within REUSE_S
_pending: set[str] = set()              # Creators queued or reading in a warm now
_tasks: set[asyncio.Task] = set()       # the running exit workers (held: a bare task may be collected)


class _Job:
    """One queued read on an exit: the warm (`poll` and `run` None; `feed`: read its feed too), a lease gain's `poll`
    or a Shared refresher job's `run` (re-checked by `wanted` at its turn)."""
    __slots__ = ("feed", "poll", "run", "wanted")

    def __init__(self, feed: bool, poll: Callable[[str], Awaitable[Any]] | None,
                 run: Callable[[str], Awaitable[Any]] | None = None,
                 wanted: Callable[[str], Awaitable[bool]] | None = None) -> None:
        self.feed, self.poll, self.run, self.wanted = feed, poll, run, wanted

    @property
    def warm(self) -> bool:
        return self.poll is None and self.run is None


class _Exit:
    """One proxy exit's gate: its queue (Creator -> job, in order) and when its next read may start."""
    __slots__ = ("label", "jobs", "free_at", "task")

    def __init__(self, label: str) -> None:
        self.label = label
        self.jobs: dict[str, _Job] = {}
        self.free_at = 0.0                  # time.monotonic(): the last read's end (or a note_read) + GAP_S
        self.task: asyncio.Task | None = None


_exits: dict[str, _Exit] = {}


def _server():
    """The serving relay: steps 2-4's read helper lives there (relay_host.live_server)."""
    return relay_host.live_server()


async def _eligible(account_ids: Iterable[str]) -> list[str]:
    live = set(await transaction_ingest.live_account_ids())
    return [a for a in dict.fromkeys(account_ids) if a in live]


def _egress(account_id: str) -> tuple[str, str]:
    """(key, log label) of the exit the Creator's pooled client leaves from: the key is
    `proxies.egress_identity` of its own endpoint (the verified exit IP, else host:port; what
    OFClient.pace_key paces ledger pages on), "direct" when it has none or none can be built (a
    Fansly Creator). The label is `p-<8 hex of the key>`: never a host, port or credential."""
    try:
        c = client_pool.get(account_id)
        key = proxies.egress_identity(getattr(c, "proxy_url", None), proxies.registry())
    except Exception:
        return DIRECT, DIRECT
    return (key, DIRECT) if key == DIRECT else (key, "p-" + hashlib.sha1(key.encode()).hexdigest()[:8])


def _current(account_id: str) -> bool:
    """Its last purchases poll, ok or not, started under PURCHASES_POLL_FAST_S ago: no feed read."""
    age = purchase_poll.last_poll_age_s(account_id)
    return age is not None and age < poll_decide.FAST_S


def just_polled(account_id: str) -> bool:
    """Its last purchases poll, ok or not, started under purchase_poll_decide.SELECT_MIN_AGE_S ago: a selection
    reads no feed."""
    age = purchase_poll.last_poll_age_s(account_id)
    return age is not None and age < poll_decide.SELECT_MIN_AGE_S


def current(account_id: str) -> bool:
    """No read needed now: its last purchases poll started under PURCHASES_POLL_FAST_S ago, or a warm read it (or
    holds it queued) within REUSE_S. The view-lease route gives such a Creator no lease-gain Select refresh."""
    at = _warmed_at.get(account_id)
    return _current(account_id) or account_id in _pending or (at is not None and _clock() - at < REUSE_S)


def _ws_since(account_id: str) -> float | None:
    """time.monotonic() when the Creator's OF WebSocket connected, None while down (of_ws.connected_since)."""
    import of_ws
    return of_ws.connected_since(account_id)


def reuse_decision(*, pending: bool, warmed_age: float | None, failed_age: float | None, ws_kept: bool,
                   reuse_s: float = REUSE_S, fresh_s: float = FRESH_S) -> str:
    """`start`'s call for one Creator: "reused" (queued or reading in a warm now: concurrent opens coalesce;
    warmed under `reuse_s` ago; or under `fresh_s` ago with `ws_kept`, its WebSocket connected since that warm
    landed), "skip" (its last warm failed under `reuse_s` ago), else "start". Ages in seconds, None: never."""
    if pending:
        return "reused"
    if warmed_age is not None and (warmed_age < reuse_s or (ws_kept and warmed_age < fresh_s)):
        return "reused"
    if failed_age is not None and failed_age < reuse_s:
        return "skip"
    return "start"


def _decide(account_id: str, now: float) -> str:
    import shared_refresher              # here: it imports this module
    at, failed = _warmed_at.get(account_id), _failed_at.get(account_id)
    failed_age = None if failed is None else now - failed
    if shared_refresher.ENABLED:         # Netting (ADR-0044): the shared Last refresh within the Creator's Cycle; the
        last = shared_refresher.last_refresh(account_id)   # window invariant stands for the socket test (same clock)
        return reuse_decision(pending=account_id in _pending, warmed_age=None if last is None else now - last,
                              failed_age=failed_age, ws_kept=True, fresh_s=shared_refresher.cycle_for(account_id))
    since = _ws_since(account_id) if at is not None else None
    return reuse_decision(pending=account_id in _pending,
                          warmed_age=None if at is None else now - at,
                          failed_age=failed_age,
                          ws_kept=since is not None and at >= since)


def _publish(account_id: str) -> None:
    """`creator_warmed`, with what the warmed entries serve now (server.app_open_warm_values: the roster count and
    the notifications count, when held) and `now` (epoch ms, the tab's clock-skew reference): the tab writes those
    instead of re-reading them."""
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
    """One Creator's read set as one background walk; True when its reads landed. `feed` False: a Select refresh
    reads its feed."""
    async def run() -> bool:
        if feed and not _current(account_id):
            await purchase_poll.poll_now(account_id)
            if account_id not in set(await transaction_ingest.live_account_ids()):
                return False        # its feed read flagged it a Dead session: nothing else can succeed
        await _server().app_open_warm_reads(account_id)
        return True
    return await of_pacing.walk(account_id, "app_open_warm", run)


def _walk_done(t: asyncio.Task) -> None:
    _tasks.discard(t)
    if not t.cancelled() and t.exception() is not None:
        log.warning("shared_refresher_job_failed task=%s", t.get_name(), exc_info=t.exception())


async def _run(aid: str, job: _Job, label: str) -> bool:
    """One queued job; True when it read (the exit then waits GAP_S)."""
    if job.run is not None:                  # a Shared refresher job: still wanted? then its walk, JOB_DEADLINE_S
        if not await job.wanted(aid):
            return False
        t = asyncio.create_task(job.run(aid), name=f"shared-refresher:{aid}")
        _tasks.add(t)                        # held; never cancelled here: past the deadline its result still lands
        t.add_done_callback(_walk_done)
        done, _ = await asyncio.wait({t}, timeout=JOB_DEADLINE_S)
        if not done:
            log.warning("shared_refresher_job_timeout account=%s proxy=%s", aid, label)
        return True
    if job.poll is not None:                 # a lease gain: feed only, still wanted?
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
    except HTTPException as exc:             # a refused read (bad session, no client): expected, one line
        log.info("app_open_warm_skipped account=%s proxy=%s status=%s", aid, label, exc.status_code)
    except Exception:
        log.warning("app_open_warm_failed account=%s proxy=%s", aid, label, exc_info=True)
    finally:
        _pending.discard(aid)
        (_warmed_at if ok else _failed_at)[aid] = _clock()
        (_failed_at if ok else _warmed_at).pop(aid, None)
    return True


async def _work(key: str, ex: _Exit) -> None:
    """The exit's worker: its queue head, one at a time, each GAP_S after the last read there."""
    try:
        while ex.jobs:
            wait = ex.free_at - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
                continue                     # the head (or free_at) may have moved meanwhile
            aid = next(iter(ex.jobs))
            job = ex.jobs.pop(aid)
            try:
                read = await _run(aid, job, ex.label)
            except asyncio.CancelledError:
                raise
            except Exception:                # a lease gain's `poll` never raises; belt and braces
                log.warning("app_open_warm_gate_failed account=%s proxy=%s", aid, ex.label, exc_info=True)
                read = True
            if read:
                ex.free_at = max(ex.free_at, time.monotonic() + GAP_S)   # a `hold` set meanwhile stands
    finally:
        ex.task = None
        for aid, job in ex.jobs.items():     # cancelled: nothing left queued may look pending
            if job.warm:
                _pending.discard(aid)
        ex.jobs.clear()


def _gate(account_id: str) -> tuple[str, _Exit]:
    key, label = _egress(account_id)
    now = time.monotonic()
    for k in [k for k, e in _exits.items() if e.task is None and not e.jobs and e.free_at <= now]:
        del _exits[k]                        # idle and past its gap: nothing to remember
    ex = _exits.get(key)
    if ex is None:
        ex = _exits[key] = _Exit(label)
    return key, ex


def _enqueue(account_id: str, job: _Job, *, front: bool = False) -> bool:
    """Queue `job` on the Creator's exit (one entry per Creator: a queued lease gain or refresh becomes the warm; a
    queued job absorbs any other) and make sure the exit's worker runs. True when `job` took the entry."""
    key, ex = _gate(account_id)
    have = ex.jobs.get(account_id)
    took = have is None
    if have is not None:
        if job.warm and not have.warm:
            ex.jobs[account_id] = job        # the warm reads more: it takes the place
            took = True
        if front:
            ex.jobs = {account_id: ex.jobs.pop(account_id), **ex.jobs}
    elif front:
        ex.jobs = {account_id: job, **ex.jobs}
    else:
        ex.jobs[account_id] = job
    if ex.task is None:
        t = ex.task = asyncio.create_task(_work(key, ex), name=f"app-open-warm:{ex.label}")
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return took


def note_read(account_id: str) -> None:
    """A read outside the gate (the route's immediate Select refresh) starts on the Creator's exit now: the gate's
    next read there waits GAP_S."""
    _, ex = _gate(account_id)
    ex.free_at = max(ex.free_at, time.monotonic() + GAP_S)


HOLD_MAX_S = 900.0   # the longest one 429 holds an exit (OF may ask any number, `inf` included)


def hold(account_id: str, wait_s: float) -> None:
    """A Shared refresher read on the Creator's exit met a terminal 429 (429s follow the proxy IP): no read there,
    by any caller, before `wait_s` from now (OF's asked wait)."""
    _, ex = _gate(account_id)
    wait_s = wait_s if 0.0 <= wait_s <= HOLD_MAX_S else HOLD_MAX_S   # also inf / nan: never an endless hold
    ex.free_at = max(ex.free_at, time.monotonic() + wait_s)


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
                _publish(aid)                 # its entries are still served: this open's tabs read them now
        elif call == "skip":
            continue                          # failed just now: not again (the tab's own read covers it)
        else:
            out[aid] = "started"
            fresh.append(aid)
            _pending.add(aid)
    first = set(leased_first)
    # Stable: the Select-refreshed first (each to the front of its exit), then leased, then the caller's order.
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
    """A lease renewal's gains (the view-lease route's, not `opened`): `poll` (its Select refresh, feed only) per
    Creator through the gate (module docstring: one queue per exit for every caller, GAP_S apart, one entry per
    Creator). At its turn a Creator polled within PURCHASES_POLL_FAST_S, or no longer leased, is skipped. Returns
    at once; no event, no reuse memo. `poll` never raises."""
    for aid in dict.fromkeys(account_ids):
        _enqueue(aid, _Job(True, poll))


def refresh(account_id: str, run: Callable[[str], Awaitable[Any]], *,
            wanted: Callable[[str], Awaitable[bool]]) -> bool:
    """A Shared refresher job through the gate (module docstring). Returns at once: True when queued, False when
    the Creator already holds its exit's entry (a queued warm, lease gain or refresh absorbs it; a warm arriving
    later takes a queued refresh's place, which then never runs)."""
    return _enqueue(account_id, _Job(False, None, run, wanted))


def pending(account_id: str) -> bool:
    """Queued or reading in a warm now."""
    return account_id in _pending


def summary(result: dict[str, Any]) -> str:
    """The route's `warm` answer for one opened renewal: "started" if any Creator started, else "reused" if any
    was reused, else "none"."""
    vals = set(result.values())
    return "started" if "started" in vals else "reused" if vals else "none"
