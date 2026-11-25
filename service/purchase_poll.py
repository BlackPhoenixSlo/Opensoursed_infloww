from __future__ import annotations

import asyncio
import logging
import time

import account_health
from cadence import boot_grace
import platforms
import purchase_notifications
import purchase_poll_decide as poll_decide
from purchase_poll_decide import PollState, Tier
import transaction_ingest as ti
import view_lease

log = logging.getLogger("of-relay.ingest_tx")

# Writes no money: the supervisor ledger stays the sole revenue writer (it lands hours late, measured 209/560/628 min); this feed only flips messages.is_paid within ~30s so nothing double-counts.
_FAST_PAGE_LIMIT = 10
# One account's tick is ~0.7 s of OF round-trip: five at a time, staggered, so a fleet never hits OF in the same second and the last account is not told ~14 s late.
_FAST_POLL_CONCURRENCY = 5
_FAST_POLL_STAGGER_S = 0.2


async def run_fast_tick(account_id: str) -> dict:
    # Platform seam: without it a Fansly account fell through to _client_for, got no_session every 30 s forever, and stayed on the 15-min supervisor cadence.
    backend = platforms.for_account(account_id).backend
    if backend is not None:
        async with ti._tick_locks[account_id]:
            r = await backend.revenue_tick(account_id)
        return {"rows_inserted": r.rows_inserted, "rows_patched": 0,
                "error": r.error}
    client = ti._client_for(account_id)
    if client is None:
        return {"rows_inserted": 0, "rows_patched": 0, "error": "no_session"}
    pages = (poll_decide.CATCHUP_MAX_PAGES
             if poll_decide.catch_up(_poll_state.get(account_id), time.monotonic()) else 1)
    r = await purchase_notifications.poll_purchases(
        account_id, client, limit=_FAST_PAGE_LIMIT, pages=pages)
    return {"rows_inserted": 0, "rows_patched": 0, "outcome": r["outcome"]}


# Per-Creator poll state lives in Relay memory by design: a restart polls every live Creator on its first cycle.
_poll_state: dict[str, PollState] = {}
_poll_inflight: dict[str, asyncio.Task] = {}
_poll_timers: dict[str, asyncio.TimerHandle] = {}
_hold_end_tasks: set[asyncio.Task] = set()  # held: a bare task may be garbage-collected
# Past the hold's end on the loop's clock: never a hair early, which the gate would refuse.
_HOLD_END_PAD_S = 0.01


async def _poll_once(account_id: str, tier: Tier) -> dict:
    started = time.monotonic()
    _poll_state[account_id] = poll_decide.started(_poll_state.get(account_id), started)
    r = await run_fast_tick(account_id)
    answered = time.monotonic()
    outcome = r.get("outcome")
    if outcome is None:
        return r
    st = _poll_state[account_id] = poll_decide.after(_poll_state.get(account_id), outcome, started, answered)
    if outcome.kind == "dead":
        try:
            if await account_health.mark_session_dead(account_id, outcome.reason):
                log.warning("ingest_tx_feed_session_dead account=%s reason=%s — purchases poll stops",
                            account_id, outcome.reason)
        except Exception:
            log.warning("ingest_tx_feed_mark_dead_failed account=%s", account_id, exc_info=True)
    elif outcome.kind in ("rate_limited", "unauthorized"):
        log.info("ingest_tx_feed_backoff account=%s outcome=%s step=%d hold_s=%.0f tier=%s",
                 account_id, outcome.kind, st.step,
                 poll_decide.hold_s(st, tier), tier)
    return r


def _single_flight(account_id: str, tier: Tier) -> asyncio.Task | None:
    t = _poll_inflight.get(account_id)
    if t is None or t.done():
        if poll_decide.held(_poll_state.get(account_id), tier, time.monotonic(), 0.0):
            return None
        timer = _poll_timers.pop(account_id, None)
        if timer is not None:
            timer.cancel()
        t = asyncio.create_task(
            _poll_once(account_id, tier),
            name=f"purchases-poll:{account_id}")
        _poll_inflight[account_id] = t

        def _done(task: asyncio.Task, aid: str = account_id) -> None:
            if _poll_inflight.get(aid) is task:
                del _poll_inflight[aid]
            if not task.cancelled():
                task.exception()
        t.add_done_callback(_done)
    return t


def _poll_at_hold_end(account_id: str, tier: Tier) -> None:
    st = _poll_state.get(account_id)
    if account_id in _poll_timers or st is None or st.held_at is None:
        return
    wait = st.held_at + poll_decide.hold_s(st, tier) - time.monotonic()
    if wait > 2 * poll_decide.FAST_S:
        return

    async def _at_end() -> None:
        try:
            if await _poll_tier(account_id) != "fast":
                return
            if _single_flight(account_id, "fast") is not None:
                _poll_state[account_id] = poll_decide.polled(_poll_state.get(account_id), time.monotonic())
        except Exception:
            log.warning("ingest_tx_hold_end_poll_failed account=%s", account_id, exc_info=True)

    def _fire() -> None:
        _poll_timers.pop(account_id, None)
        t = asyncio.ensure_future(_at_end())
        _hold_end_tasks.add(t)
        t.add_done_callback(_hold_end_tasks.discard)

    _poll_timers[account_id] = asyncio.get_running_loop().call_later(max(0.0, wait) + _HOLD_END_PAD_S, _fire)


def last_poll_age_s(account_id: str) -> float | None:
    st = _poll_state.get(account_id)
    return None if st is None or st.last_started_s is None else time.monotonic() - st.last_started_s


async def _poll_tier(account_id: str) -> Tier | None:
    if account_id not in await ti.live_account_ids() or await ti._is_paused(account_id):
        return None
    return poll_decide.tier(view_lease.is_leased(account_id), account_id in await ti._seller_account_ids())


async def poll_now(account_id: str) -> dict | None:
    try:
        tier = await _poll_tier(account_id)
        if tier is None:
            return None
        t = _single_flight(account_id, tier)
        return None if t is None else await asyncio.shield(t)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("ingest_tx_poll_now_failed account=%s", account_id, exc_info=True)
        return None


async def start_fast_poll() -> None:
    log.info("ingest_tx_fast_poll_started tick=%ds slow=%ds limit=%d",
             poll_decide.FAST_S, poll_decide.SLOW_S, _FAST_PAGE_LIMIT)
    # One tick interval of politeness, once, so the first fleet walk does not land on top of the pumps still connecting.
    await boot_grace(ti._FAST_BOOT_GRACE_S, name="ingest-fast-poll")
    while True:
        try:
            cycle_started = time.monotonic()
            live = await ti.live_account_ids()
            leased = view_lease.leased_ids()
            sellers = await ti._seller_account_ids()
            due_now: list[tuple[bool, str, Tier]] = []
            for aid in live:
                t = poll_decide.tier(aid in leased, aid in sellers)
                state = _poll_state.get(aid)
                if (state is None or state.last_s is None) and t == "slow":
                    state = _poll_state[aid] = poll_decide.first_idle_state(aid, cycle_started, state)
                if t == "fast" and poll_decide.held(state, t, cycle_started, 0.0):
                    _poll_at_hold_end(aid, t)
                elif poll_decide.due(state, t, cycle_started) and not await ti._is_paused(aid):
                    due_now.append((t != "fast", aid, t))
            due_now.sort(key=lambda x: x[0])
            sem = asyncio.Semaphore(_FAST_POLL_CONCURRENCY)

            async def _fast(i: int, aid: str, t: Tier) -> None:
                await asyncio.sleep(i * _FAST_POLL_STAGGER_S)
                async with sem:
                    try:
                        task = _single_flight(aid, t)
                        if task is None:
                            return
                        _poll_state[aid] = poll_decide.polled(_poll_state.get(aid), cycle_started)
                        await task
                    # Record, don't just log: the Fansly lane raises on a feed failure by design, so an unrecorded catch let a dead session fail 120 times an hour, never pause, never show on the dashboard.
                    except Exception as e:
                        log.warning(
                            "ingest_tx_fast_cycle_account_failed account=%s",
                            aid, exc_info=True)
                        await ti._record_failure(aid, e)

            await asyncio.gather(*(_fast(i, a, t) for i, (_, a, t) in enumerate(due_now)))
            elapsed = time.monotonic() - cycle_started
            await asyncio.sleep(max(ti._MIN_CYCLE_GAP_S, poll_decide.FAST_S - elapsed))
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("ingest_tx_fast_poll cycle failed", exc_info=True)
            await asyncio.sleep(poll_decide.FAST_S)
