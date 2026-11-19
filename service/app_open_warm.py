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
  start(principal, account_ids, leased_first, *, refreshed=()) -> {Creator: "started" | "reused"}
      Schedules the warm and returns at once. `account_ids` are the principal's (the route drops
      watchers); dead-session, deactivated and no-session Creators are skipped (absent from the
      answer; `transaction_ingest.live_account_ids`). A Creator warmed within REUSE_S, or queued or
      reading in a warm now, is `reused` (one whose warm ended publishes `creator_warmed` at once: its
      entries are still served), `refreshed` or not: many Employees, or many tabs opening on one
      selection, cost one warm per Creator. One whose warm failed within REUSE_S is skipped (absent: the
      tab's own read covers it). The rest are `started` into the gate: `refreshed` (the route's Select
      refreshes, already running and `note_read`) at the front of their exit, their feed never read again
      here; then Creators in `leased_first`, then in `account_ids` order.
      Per Creator, one background walk (`of_pacing.walk`, Caller kind `walk:app_open_warm`, its pages
      paced per Creator), in order:
        1. one purchases poll (`purchase_poll.poll_now`, single-flight with the loop's tick),
           skipped when its last ok poll is younger than PURCHASES_POLL_FAST_S (a Demand Creator is
           current); a Creator it flags a Dead session reads nothing more;
        2-4. the server's `app_open_warm_reads` (looked up at call time): the chats window (roster-counts'
           recompute with bypass, rewarming the Fan List's page 0), the rail's tip and purchases lists
           and the notifications count, into the entries the pass-through routes serve.
      At most 5 reads per Creator per REUSE_S. Then `creator_warmed` (house envelope); a Creator whose
      reads failed publishes nothing and is never `reused` (the tab's own read covers it).
      The warm only reads: no send, fan write or automation run waits on it.

Knobs, read here only: APP_OPEN_WARM_GAP_S (default 1.0, of_pacing.PAGE_GAP_S: OF's "Please allow
1 seconds"), APP_OPEN_WARM_REUSE_S (default 30, the notifications pass-through's cache TTL). State is
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

DIRECT = "direct"                       # proxies.egress_identity's key (and the label) without a proxy
_clock = time.monotonic                 # the reuse memo's clock (tests inject one)
_warmed_at: dict[str, float] = {}       # Creator -> when its warm's reads landed (or found current)
_failed_at: dict[str, float] = {}       # Creator -> when its warm failed: not tried again within REUSE_S
_pending: set[str] = set()              # Creators queued or reading in a warm now
_tasks: set[asyncio.Task] = set()       # the running exit workers (held: a bare task may be collected)


class _Job:
    """One queued read on an exit: the warm (`poll` None; `feed`: read its feed too) or a lease gain's `poll`."""
    __slots__ = ("feed", "poll")

    def __init__(self, feed: bool, poll: Callable[[str], Awaitable[Any]] | None) -> None:
        self.feed, self.poll = feed, poll


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


async def _run(aid: str, job: _Job, label: str) -> bool:
    """One queued job; True when it read (the exit then waits GAP_S)."""
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
                ex.free_at = time.monotonic() + GAP_S
    finally:
        ex.task = None
        for aid, job in ex.jobs.items():     # cancelled: nothing left queued may look pending
            if job.poll is None:
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


def _enqueue(account_id: str, job: _Job, *, front: bool = False) -> None:
    """Queue `job` on the Creator's exit (one entry per Creator: a queued lease gain becomes the warm; a queued
    warm absorbs a lease gain) and make sure the exit's worker runs."""
    key, ex = _gate(account_id)
    have = ex.jobs.get(account_id)
    if have is not None:
        if job.poll is None and have.poll is not None:
            ex.jobs[account_id] = job        # the warm reads more: it takes the place
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


def note_read(account_id: str) -> None:
    """A read outside the gate (the route's immediate Select refresh) starts on the Creator's exit now: the gate's
    next read there waits GAP_S."""
    _, ex = _gate(account_id)
    ex.free_at = max(ex.free_at, time.monotonic() + GAP_S)


async def start(principal: tuple[str, str], account_ids: Iterable[str], leased_first: Iterable[str] = (), *,
                refreshed: Iterable[str] = ()) -> dict[str, str]:
    now = _clock()
    done = set(refreshed)
    out: dict[str, str] = {}
    fresh: list[str] = []
    for aid in await _eligible(account_ids):
        at, failed = _warmed_at.get(aid), _failed_at.get(aid)
        if aid in _pending or (at is not None and now - at < REUSE_S):
            out[aid] = "reused"
            if aid not in _pending:
                _publish(aid)                 # its entries are still served: this open's tabs read them now
        elif failed is not None and now - failed < REUSE_S:
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


def summary(result: dict[str, Any]) -> str:
    """The route's `warm` answer for one opened renewal: "started" if any Creator started, else "reused" if any
    was reused, else "none"."""
    vals = set(result.values())
    return "started" if "started" in vals else "reused" if vals else "none"
