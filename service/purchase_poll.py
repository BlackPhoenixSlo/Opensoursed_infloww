"""
The purchases poll's scheduler (ADR-0031, phase-01 1a), moved out of transaction_ingest (the ledger's): the loop
(`start_fast_poll`, server.py spawns it), the Select refresh (`poll_now`), the one hold gate (`_single_flight`) and
each Creator's poll state in Relay memory. The decisions are purchase_poll_decide's, pure.

The ledger pieces it shares are looked up on `transaction_ingest` at call time (tests and slop faults swap them):
`live_account_ids`, `_seller_account_ids`, `_is_paused`, `_record_failure`, `_client_for`, `_tick_locks`,
`_MIN_CYCLE_GAP_S`, `_FAST_BOOT_GRACE_S`. Logs on the ingest logger, `of-relay.ingest_tx`, as before the move.
"""
from __future__ import annotations

import asyncio
import logging
import time

import account_health
from cadence import boot_grace
import fansly_backend
import fansly_revenue
import purchase_notifications
import purchase_poll_decide as poll_decide
from purchase_poll_decide import PollState, Tier
import transaction_ingest as ti
import view_lease

log = logging.getLogger("of-relay.ingest_tx")

# Layered ON TOP of the 15-min supervisor: one tiny request per due account
# reading OF's purchases notification feed, so a PPV unlock flips
# `messages.is_paid` within ~30s on a Demand Creator (View lease or Seller;
# 5 min on an Idle one, purchase_poll_decide) and the automations see the
# payment the tick after the fan pays. The supervisor owns the ledger: the authoritative 7-day
# window, relink sweep, orphan attribution, and backfill.
#
# This tick used to ALSO re-read the newest ledger page every 30s. The ledger
# lands hours late (measured 209/560/628 min), so a 30s read of it bought no
# freshness over the then 5-min supervisor and cost 120 OF calls an hour per selling
# account (about 40% of its OF traffic). A DM tip is recorded instantly off the
# WS pump (event_transcoder); a purchase is seen off the feed below.
_FAST_PAGE_LIMIT = 10
# Accounts polled at once, and the gap between their starts. One account's
# tick is ~0.7 s of OF round-trip, so walking 20 one by one took ~14 s of the
# 30 s period and told the last account about a payment ~14 s late. Five at a
# time, starts STAGGER_S apart so a fleet never hits OF in the same second:
# 20 accounts finish in ~4.5 s. Each account still makes one call per tick,
# inside its own OF lane (purchase_notifications._of_lane), so this adds at
# most five threads to the shared executor.
_FAST_POLL_CONCURRENCY = 5
_FAST_POLL_STAGGER_S = 0.2


async def run_fast_tick(account_id: str) -> dict:
    """One freshness poll for one account: the newest _FAST_PAGE_LIMIT purchase
    notifications (single request). Writes NO money on OF — see above."""
    # PLATFORM SEAM, mirroring run_one_tick's. Without it a Fansly account
    # fell straight through to `transaction_ingest._client_for` -> no OFClient -> "no_session"
    # every 30 seconds forever: a permanently dead path. That is not merely a
    # wasted call — this loop exists so a SELLING automation learns about a
    # payment in seconds rather than minutes (see transaction_ingest._SELLING_KINDS), and
    # on Fansly the purchases feed IS the payment signal. Skipping it left
    # Fansly sellers on the 15-minute supervisor cadence, still saying "waiting
    # on your tip" to a fan who had already paid. The read is cheap here: one
    # un-paginated page, already TTL-cached in the shim.
    if fansly_backend.is_fansly(account_id):
        async with ti._tick_locks[account_id]:
            r = await fansly_revenue.run_one_tick(account_id)
        return {"rows_inserted": r.rows_inserted, "rows_patched": 0,
                "error": r.error}
    client = ti._client_for(account_id)
    if client is None:
        return {"rows_inserted": 0, "rows_patched": 0, "error": "no_session"}
    # OF's purchases notification names the exact message id the moment it is
    # paid — flipping is_paid off it lets every reader of `messages.is_paid` see
    # the buy on its next tick. Writes NO money: the ledger (supervisor) stays the
    # sole revenue writer, so nothing here can double-count. Never raises.
    # After a gap (an Idle interval, a backoff, a restart) it pages back
    # (purchase_poll_decide.catch_up).
    pages = (poll_decide.CATCHUP_MAX_PAGES
             if poll_decide.catch_up(_poll_state.get(account_id), time.monotonic()) else 1)
    r = await purchase_notifications.poll_purchases(
        account_id, client, limit=_FAST_PAGE_LIMIT, pages=pages)
    return {"rows_inserted": 0, "rows_patched": 0, "outcome": r["outcome"]}


# Per-Creator poll state (purchase_poll_decide.PollState), in Relay memory by design: a restart
# polls every live Creator on its first cycle.
_poll_state: dict[str, PollState] = {}
# The purchases poll running now per Creator: the loop's tick and `poll_now` join it, never a second.
_poll_inflight: dict[str, asyncio.Task] = {}
# A loop poll the gate refused inside the last cycle before the Demand cap, set for the hold's end
# (`_poll_at_hold_end`): at most one per Creator, cancelled when any poll of it starts first.
_poll_timers: dict[str, asyncio.TimerHandle] = {}
# Past the hold's end on the loop's clock: never a hair early, which the gate would refuse.
_HOLD_END_PAD_S = 0.01


async def _poll_once(account_id: str, tier: Tier) -> dict:
    """run_fast_tick, then its outcome folded into the Creator's poll state
    (purchase_poll_decide.after: last-ok from this poll's actual start, a hold from OF's answer;
    the loop's and a Select refresh's alike). A `dead` outcome flags the Creator through
    account_health (it then leaves `transaction_ingest.live_account_ids`); no feed outcome is a supervisor failure
    (`transaction_ingest._record_failure` stays for a raise: the Fansly lane's)."""
    started = time.monotonic()
    r = await run_fast_tick(account_id)
    answered = time.monotonic()
    outcome = r.get("outcome")
    if outcome is None:          # Fansly, no session: the ladder is OnlyFans-only
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
    """The Creator's running purchases poll, or a new one (`_poll_once`: run_fast_tick + its
    outcome), or None while its 429 / unauthorized hold is on: the one hold gate for the loop and
    a Select refresh, checked where a poll starts (purchase_poll_decide.held, no look-ahead). The
    task copies the caller's context, so its OF calls carry the starter's Caller kind (the loop's,
    or `select_refresh`)."""
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
                task.exception()  # retrieved: a joiner logs it, never "exception was never retrieved"
        t.add_done_callback(_done)
    return t


def _poll_at_hold_end(account_id: str, tier: Tier) -> None:
    """The loop's poll of a Demand Creator the gate refused in the last cycle before its cap (`due`
    looks a tick ahead): started at its hold's end instead of the next cycle, so the next poll never
    starts past PURCHASES_BACKOFF_DEMAND_MAX_S; also armed by the loop for a held Demand Creator whose
    hold ends before the next tick (FAST_S + the cycle's work away). One pending timer per Creator; a
    hold ending past 2 * FAST_S is a later cycle's. The timer copies the loop's context (its Caller kind)."""
    st = _poll_state.get(account_id)
    if account_id in _poll_timers or st is None or st.held_at is None:
        return
    wait = st.held_at + poll_decide.hold_s(st, tier) - time.monotonic()
    if wait > 2 * poll_decide.FAST_S:
        return

    def _fire() -> None:
        _poll_timers.pop(account_id, None)
        if _single_flight(account_id, tier) is not None:
            _poll_state[account_id] = poll_decide.polled(_poll_state.get(account_id), time.monotonic())

    _poll_timers[account_id] = asyncio.get_running_loop().call_later(max(0.0, wait) + _HOLD_END_PAD_S, _fire)


def last_ok_poll_age_s(account_id: str) -> float | None:
    """Seconds since `account_id`'s last ok purchases poll started (its PollState `last_ok_s`); None
    if none since boot. The App-open warm skips a Creator polled ok within PURCHASES_POLL_FAST_S."""
    st = _poll_state.get(account_id)
    return None if st is None or st.last_ok_s is None else time.monotonic() - st.last_ok_s


async def poll_now(account_id: str) -> dict | None:
    """The Select refresh: one purchases poll for `account_id` right away, single-flight with the
    loop's tick (joins one already running). Skips a Creator with no live session, deactivated,
    flagged a Dead session or paused, and one inside its 429 / unauthorized hold (None: the
    `_single_flight` gate). Never raises. Does not move the loop's schedule (a Demand Creator
    keeps its FAST_S cadence); its outcome stamps last-ok and the hold like the loop's."""
    try:
        if account_id not in await ti.live_account_ids() or await ti._is_paused(account_id):
            return None
        tier = poll_decide.tier(view_lease.is_leased(account_id), account_id in await ti._seller_account_ids())
        t = _single_flight(account_id, tier)
        return None if t is None else await asyncio.shield(t)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("ingest_tx_poll_now_failed account=%s", account_id, exc_info=True)
        return None


async def start_fast_poll() -> None:
    """The purchases loop — see run_fast_tick. Ticks every FAST_S (PURCHASES_POLL_FAST_S, 30 s)
    and polls only the Creators purchase_poll_decide.due says are due: every tick a Demand
    Creator (a View lease, `view_lease`, or an enabled Seller, `transaction_ingest._seller_account_ids`), every
    SLOW_S (PURCHASES_POLL_SLOW_S, 5 min) an Idle one, at its own phase, whoever is signed in.
    A Dead-session Creator is not in the live set; one inside its 429 / unauthorized hold
    (purchase_poll_decide.held, the Backoff ladder) waits it out, and nobody else does; a Demand
    one whose capped hold ends before the next tick is polled at its end (`_poll_at_hold_end`).
    Demand Creators start first in a cycle. An account the supervisor
    backed off after 3 fails stays skipped. Due accounts run _FAST_POLL_CONCURRENCY at a time,
    starts _FAST_POLL_STAGGER_S apart — bounded OF load without the last account waiting out the
    whole fleet. Sleep AT END so the gap is FAST_S regardless of cycle duration."""
    log.info("ingest_tx_fast_poll_started tick=%ds slow=%ds limit=%d",
             poll_decide.FAST_S, poll_decide.SLOW_S, _FAST_PAGE_LIMIT)
    # One tick interval of politeness, once, so the first fleet walk does not
    # land on top of the pumps still connecting. See transaction_ingest._FAST_BOOT_GRACE_S.
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
                    # Spread Idle Creators over SLOW_S, so they never all land in one cycle.
                    state = _poll_state[aid] = poll_decide.first_idle_state(aid, cycle_started, state)
                if poll_decide.due(state, t, cycle_started) and not await ti._is_paused(aid):
                    due_now.append((t != "fast", aid, t))
                elif t == "fast" and poll_decide.held(state, t, cycle_started, 0.0):
                    # The next tick lands FAST_S + this cycle's work away: a hold ending before it
                    # starts at its end, not a tick late.
                    _poll_at_hold_end(aid, t)
            # Demand Creators first: an Idle batch never pushes a Seller's start back.
            due_now.sort(key=lambda x: x[0])
            sem = asyncio.Semaphore(_FAST_POLL_CONCURRENCY)

            async def _fast(i: int, aid: str, t: Tier) -> None:
                await asyncio.sleep(i * _FAST_POLL_STAGGER_S)
                async with sem:
                    try:
                        task = _single_flight(aid, t)
                        if task is None:     # still inside its hold: started at the hold's end
                            _poll_at_hold_end(aid, t)
                            return
                        _poll_state[aid] = poll_decide.polled(_poll_state.get(aid), cycle_started)
                        await task
                    except Exception as e:
                        # RECORD it, don't just whisper. This was `log.debug` and
                        # nothing else, which was harmless while run_fast_tick
                        # swallowed its own fetch errors into an error dict — the
                        # only way here was a bug, not a dead session. The Fansly
                        # lane raises on a feed failure by design (its silence is
                        # unrecoverable lost sales), so an unrecorded catch here
                        # meant a dead Fansly session failed 120 times an hour,
                        # never incremented consecutive_failures, never paused,
                        # and never showed on the admin dashboard.
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
