"""
The App-open warm (ADR-0031, phase-01 1b): when an Employee opens Inflowwww on any page (the first
`POST /admin/view-lease` of a document load carries `opened: true`), every Creator they can access
gets ONE refresh, so the first screen anyone sees is current, even for Creators they never open.
As each Creator's reads land it publishes `creator_warmed`; every tab that can access the Creator
(events_decide.ANY_SCOPE_TYPES) re-reads its rail, bell and strip entries from the warmed cache.

  current(account_id) -> bool: no read needed now (polled ok within PURCHASES_POLL_FAST_S, or warmed within
      REUSE_S, or queued in a warm): the view-lease route's lease-gain Select refresh skips it.
  just_polled(account_id) -> bool: polled ok within purchase_poll_decide.SELECT_MIN_AGE_S: a selection reads no feed.
  pace(account_ids, poll, busy=()): the view-lease route's other lease gains, `poll`ed per proxy like the warm's
      groups (below), feed only: never one read each at once (a restart or a tab back from hidden re-leases many).
  start(principal, account_ids, leased_first, *, refreshed=()) -> {Creator: "started" | "reused"}
      Schedules the warm and returns at once. `account_ids` are the principal's (the route drops
      watchers); dead-session, deactivated and no-session Creators are skipped (absent from the
      answer; `transaction_ingest.live_account_ids`). `refreshed` (the route's Select refreshes,
      already running) are `started`, their feed never read again here, their other reads first on
      their proxy: what the user is looking at goes first, and the group on their proxy waits one
      GAP_S before its first read. Any other Creator warmed, or still queued, within REUSE_S is
      `reused` (one whose warm ended publishes `creator_warmed` at once: its entries are still
      served): many Employees opening at once cost one warm per Creator. The rest are grouped by their
      client's proxy exit (`proxies.egress_identity`, the ledger pacer's exit key; "direct" without one):
      each group reads one Creator at a time, GAP_S between Creators, groups in parallel, Creators in `leased_first`
      first, then in `account_ids` order.
      Per Creator, one background walk (`of_pacing.walk`, Caller kind `walk:app_open_warm`, its pages
      paced per Creator), in order:
        1. one purchases poll (`purchase_poll.poll_now`, single-flight with the loop's tick),
           skipped when its last ok poll is younger than PURCHASES_POLL_FAST_S (a Demand Creator is
           current); a Creator it flags a Dead session reads nothing more;
        2-4. the server's `app_open_warm_reads` (looked up at call time): the chats window (roster-counts'
           recompute with bypass, rewarming the Fan List's page 0), the rail's tip and purchases lists
           and the notifications count, into the entries the pass-through routes serve.
      At most 5 reads per Creator per REUSE_S. Then `creator_warmed` (house envelope); a Creator whose
      reads failed publishes nothing (the tab's own read covers it).
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
from env_knob import env_float
from fastapi import HTTPException

log = logging.getLogger("of-relay.app_open_warm")

GAP_S = env_float("APP_OPEN_WARM_GAP_S", 1.0, 0.0)
REUSE_S = env_float("APP_OPEN_WARM_REUSE_S", 30.0, 0.0)

DIRECT = "direct"                       # proxies.egress_identity's key (and the label) without a proxy
_clock = time.monotonic                 # the reuse memo's clock (tests inject one)
_warmed_at: dict[str, float] = {}       # Creator -> when its warm ended (read, or found current)
_pending: set[str] = set()              # Creators queued or reading in a warm now
_tasks: set[asyncio.Task] = set()       # the running groups (held: a bare task may be collected)


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
    """Its last ok purchases poll is younger than PURCHASES_POLL_FAST_S: no feed read."""
    age = purchase_poll.last_ok_poll_age_s(account_id)
    return age is not None and age < poll_decide.FAST_S


def just_polled(account_id: str) -> bool:
    """Its last ok purchases poll is younger than purchase_poll_decide.SELECT_MIN_AGE_S: a selection reads no feed."""
    age = purchase_poll.last_ok_poll_age_s(account_id)
    return age is not None and age < poll_decide.SELECT_MIN_AGE_S


def current(account_id: str) -> bool:
    """No read needed now: its last ok purchases poll is younger than PURCHASES_POLL_FAST_S, or a warm read it (or
    holds it queued) within REUSE_S. The view-lease route gives such a Creator no lease-gain Select refresh."""
    at = _warmed_at.get(account_id)
    return _current(account_id) or account_id in _pending or (at is not None and _clock() - at < REUSE_S)


def _publish(account_id: str) -> None:
    events.publish({"creator_warmed": {"account_id": account_id,
                                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
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


async def _run_group(label: str, jobs: list[tuple[str, bool]], read_before: bool) -> None:
    """`jobs`: (Creator, read its feed). `read_before`: a Select refresh is reading on this proxy now, so the first
    read waits GAP_S too."""
    try:
        for aid, feed in jobs:
            try:
                if read_before:
                    await asyncio.sleep(GAP_S)
                read_before = True
                if await _warm_one(aid, feed):
                    _publish(aid)
            except asyncio.CancelledError:
                raise
            except HTTPException as exc:     # a refused read (bad session, no client): expected, one line
                log.info("app_open_warm_skipped account=%s proxy=%s status=%s", aid, label, exc.status_code)
            except Exception:
                log.warning("app_open_warm_failed account=%s proxy=%s", aid, label, exc_info=True)
            finally:
                _pending.discard(aid)
                _warmed_at[aid] = _clock()
    finally:
        for aid, _ in jobs:
            _pending.discard(aid)


async def start(principal: tuple[str, str], account_ids: Iterable[str], leased_first: Iterable[str] = (), *,
                refreshed: Iterable[str] = ()) -> dict[str, str]:
    now = _clock()
    done = set(refreshed)
    out: dict[str, str] = {}
    fresh: list[str] = []
    busy: set[str] = set()                    # egress keys a Select refresh reads on now
    for aid in await _eligible(account_ids):
        at = _warmed_at.get(aid)
        if aid in done:
            out[aid] = "started"
            fresh.append(aid)
            _pending.add(aid)
            busy.add(_egress(aid)[0])
        elif aid in _pending or (at is not None and now - at < REUSE_S):
            out[aid] = "reused"
            if aid not in _pending:
                _publish(aid)                 # its entries are still served: this open's tabs read them now
        else:
            out[aid] = "started"
            fresh.append(aid)
            _pending.add(aid)
    first = set(leased_first)
    groups: dict[str, tuple[str, list[tuple[str, bool]]]] = {}
    # Stable: the Select-refreshed first, then leased, then the caller's order.
    for aid in sorted(fresh, key=lambda a: (a not in done, a not in first)):
        key, label = _egress(aid)
        groups.setdefault(key, (label, []))[1].append((aid, aid not in done))
    for key, (label, jobs) in groups.items():
        t = asyncio.create_task(_run_group(label, jobs, key in busy), name=f"app-open-warm:{label}")
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    n_done = len(done & out.keys())
    log.info("app_open_warm principal=%s:%s started=%d refreshed=%d reused=%d proxies=%d", principal[0],
             principal[1], len(fresh) - n_done, n_done, len(out) - len(fresh), len(groups))
    return out


async def _pace_group(account_ids: list[str], poll: Callable[[str], Awaitable[Any]], read_before: bool) -> None:
    for aid in account_ids:
        if _current(aid):
            continue
        if read_before:
            await asyncio.sleep(GAP_S)
        read_before = True
        await poll(aid)


def pace(account_ids: Iterable[str], poll: Callable[[str], Awaitable[Any]], busy: Iterable[str] = ()) -> None:
    """A lease renewal's gains (the view-lease route's, not `opened`): `poll` (its Select refresh, feed only) per
    Creator, grouped by proxy exit as `start`'s groups, one Creator at a time GAP_S apart, groups in parallel; a group
    on the exit of a `busy` Creator (the selection, reading now) waits GAP_S first. A Creator polled ok within
    PURCHASES_POLL_FAST_S by its turn is skipped. Returns at once; no event, no reuse memo. `poll` never raises."""
    hot = {_egress(a)[0] for a in busy}
    groups: dict[str, tuple[str, list[str]]] = {}
    for aid in dict.fromkeys(account_ids):
        key, label = _egress(aid)
        groups.setdefault(key, (label, []))[1].append(aid)
    for key, (label, aids) in groups.items():
        t = asyncio.create_task(_pace_group(aids, poll, key in hot), name=f"lease-gain:{label}")
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)


def summary(result: dict[str, Any]) -> str:
    """The route's `warm` answer for one opened renewal: "started" if any Creator started, else "reused" if any
    was reused, else "none"."""
    vals = set(result.values())
    return "started" if "started" in vals else "reused" if vals else "none"
