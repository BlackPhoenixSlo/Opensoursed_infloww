"""
The App-open warm (ADR-0031, phase-01 1a): when an Employee opens Inflowwww on any page (the first
`POST /admin/view-lease` of a document load carries `opened: true`), every Creator they can access
gets ONE refresh, so the first screen anyone sees is current, even for Creators they never open.
1a reads the purchases feed only and publishes nothing (`creator_warmed` and the other reads are 1b).

  current(account_id) -> bool: no read needed now (polled ok within PURCHASES_POLL_FAST_S, or warmed within
      REUSE_S): the view-lease route's lease-gain Select refresh skips it.
  start(principal, account_ids, leased_first, *, refreshed=()) -> {Creator: "started" | "reused"}
      Schedules the warm and returns at once. `account_ids` are the principal's (the route drops
      watchers); dead-session, deactivated and no-session Creators are skipped (absent from the
      answer; `transaction_ingest.live_account_ids`). `refreshed` (the route's Select refreshes,
      already running) are `started` and warmed now, never read again here: what the user is
      looking at goes first, and the group on their proxy waits one GAP_S before its first read.
      Any other Creator warmed, or still queued, within REUSE_S is `reused`: many Employees
      opening at once cost one warm per Creator. The rest are grouped by their client's proxy
      exit (`proxies.egress_identity`, the ledger pacer's exit key; "direct" without one): each group reads one Creator at a
      time, GAP_S between reads, groups in parallel, Creators in `leased_first` first, then in
      `account_ids` order.
      Per Creator: one purchases poll (`transaction_ingest.poll_now`, single-flight with the loop's
      tick) as a background walk (`of_pacing.walk`, Caller kind `walk:app_open_warm`), skipped
      when its last ok poll is younger than PURCHASES_POLL_FAST_S (a Demand Creator is current).
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
from typing import Any, Iterable

import client_pool
import of_pacing
import proxies
import purchase_poll_decide as poll_decide
import transaction_ingest

log = logging.getLogger("of-relay.app_open_warm")

GAP_S = poll_decide._knob("APP_OPEN_WARM_GAP_S", 1.0, 0.0)
REUSE_S = poll_decide._knob("APP_OPEN_WARM_REUSE_S", 30.0, 0.0)

DIRECT = "direct"                       # proxies.egress_identity's key (and the label) without a proxy
_clock = time.monotonic                 # the reuse memo's clock (tests inject one)
_warmed_at: dict[str, float] = {}       # Creator -> when its warm ended (read, or found current)
_pending: set[str] = set()              # Creators queued or reading in a warm now
_tasks: set[asyncio.Task] = set()       # the running groups (held: a bare task may be collected)


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
    """Its last ok purchases poll is younger than PURCHASES_POLL_FAST_S: no read."""
    age = transaction_ingest.last_ok_poll_age_s(account_id)
    return age is not None and age < poll_decide.FAST_S


def current(account_id: str) -> bool:
    """No read needed now: its last ok purchases poll is younger than PURCHASES_POLL_FAST_S, or a warm read it (or
    holds it queued) within REUSE_S. The view-lease route gives such a Creator no lease-gain Select refresh."""
    at = _warmed_at.get(account_id)
    return _current(account_id) or account_id in _pending or (at is not None and _clock() - at < REUSE_S)


async def _warm_one(account_id: str) -> None:
    """One Creator's 1a read set: the purchases poll, as a background walk."""
    await of_pacing.walk(account_id, "app_open_warm", lambda: transaction_ingest.poll_now(account_id))


async def _run_group(label: str, account_ids: list[str], read_before: bool) -> None:
    """`read_before`: a Select refresh is reading on this proxy now, so the first read waits GAP_S too."""
    try:
        for aid in account_ids:
            try:
                if _current(aid):
                    continue
                if read_before:
                    await asyncio.sleep(GAP_S)
                read_before = True
                await _warm_one(aid)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("app_open_warm_failed account=%s proxy=%s", aid, label, exc_info=True)
            finally:
                _pending.discard(aid)
                _warmed_at[aid] = _clock()
    finally:
        for aid in account_ids:
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
            _warmed_at[aid] = now
            busy.add(_egress(aid)[0])
        elif aid in _pending or (at is not None and now - at < REUSE_S):
            out[aid] = "reused"
        else:
            out[aid] = "started"
            fresh.append(aid)
            _pending.add(aid)
    first = set(leased_first)
    groups: dict[str, tuple[str, list[str]]] = {}
    for aid in sorted(fresh, key=lambda a: a not in first):   # stable: leased first, then the caller's order
        key, label = _egress(aid)
        groups.setdefault(key, (label, []))[1].append(aid)
    for key, (label, aids) in groups.items():
        t = asyncio.create_task(_run_group(label, aids, key in busy), name=f"app-open-warm:{label}")
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    log.info("app_open_warm principal=%s:%s started=%d refreshed=%d reused=%d proxies=%d", principal[0],
             principal[1], len(fresh), len(done & out.keys()), len(out) - len(fresh) - len(done & out.keys()),
             len(groups))
    return out


def summary(result: dict[str, Any]) -> str:
    """The route's `warm` answer for one opened renewal: "started" if any Creator started, else "reused" if any
    was reused, else "none"."""
    vals = set(result.values())
    return "started" if "started" in vals else "reused" if vals else "none"
