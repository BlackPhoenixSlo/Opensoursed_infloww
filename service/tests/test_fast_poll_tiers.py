#!/usr/bin/env python3
"""The purchases loop's tiers (ADR-0031, phase-01 1a): a Demand Creator (a View lease or an
enabled Seller) is polled every tick, an Idle one every PURCHASES_POLL_SLOW_S, whoever is signed in.

  • case_tiers_ignore_presence: real DB rows. An online admin and an online chatter widen
    nothing; the Seller kinds (reply_mass_funnel, purchase_followup) and a leased Creator are
    fast; a Creator with no rule, the old kinds (ppv_send, ...) and a disabled Seller are not.
    Fansly Creators get the same tiers (a Fansly Seller polled through the Fansly lane, a
    Fansly Idle one not). Each Creator was last polled 20 s ago: one cycle polls exactly the fast ones.
  • case_idle_still_polled: an Idle Creator last polled a slow interval ago is polled; one never
    polled gets its spread phase (purchase_poll_decide.first_idle_state) and is polled only if
    that phase is now.
  • case_demand_first: a cycle where Idle and Demand Creators are all due starts every Demand
    Creator before any Idle one.
  • case_poll_now_single_flight: poll_now during the loop's poll of the same Creator joins it
    (one feed read), and a second poll_now joins too; a Creator with no live session is skipped.
  • case_dead_session_skipped: a Dead-session Seller (account_health.dead_session_map, read each
    cycle) gets no poll and no poll_now; its flag cleared, the next cycle polls it (no poll-state reset).
  • case_429_holds_the_creator: a rate_limited outcome holds that Creator out of the next cycles for
    its Retry-After and nobody else; poll_now inside the hold makes no call; the first ok resets it.
  • case_dead_outcome_flags_unauthorized_does_not: a `dead` outcome flags the Creator through
    account_health.mark_session_dead with the classifier's reason; `unauthorized` backs off and
    flags nothing; neither records a supervisor failure.
  • case_poll_now_stamps_last_ok_not_the_schedule: a Select refresh's ok stamps last-ok, keeps the
    loop's schedule (`last_s`); a Demand Creator's 429 on it holds from OF's answer, and a Select
    refresh makes no call until the cap (the _single_flight gate, no look-ahead).
  • case_cap_poll_starts_at_the_hold_end: a Demand Creator whose capped hold ends inside the cycle
    (the gate refuses it at the cycle's start) is polled at the hold's end, not a cycle later; one
    pending timer per Creator, cancelled when a poll of it starts first.
  • case_catch_up_after_a_gap: a loop cycle's poll (the real run_fast_tick, a fake feed) reads
    PURCHASES_CATCHUP_MAX_PAGES pages after a gap (no ok poll yet, or an old one), one page right
    after an ok poll.

Run:  ./venv/bin/python service/tests/test_fast_poll_tiers.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import dataclasses  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
from datetime import datetime  # noqa: E402

import purchase_poll_decide as decide  # noqa: E402
import purchase_poll as pp  # noqa: E402
import transaction_ingest as ti  # noqa: E402
import view_lease  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRule, Chatter, ChatterUser, User, UserAccount  # noqa: E402

AUTO, FUNNEL, FU, QUIET, OLD, OFF, LEASED, IDLE, F_SELL, F_IDLE = (f"88{i:02d}" for i in range(10))
ACCOUNTS = [AUTO, FUNNEL, FU, QUIET, OLD, OFF, LEASED, IDLE, F_SELL, F_IDLE]
FANSLY = {F_SELL, F_IDLE}
RULES = [(AUTO, "purchase_followup", True), (FUNNEL, "reply_mass_funnel", True), (FU, "purchase_followup", True),
         (OLD, "ppv_send", True), (OLD, "reengage_buyers", True),
         (OLD, "welcome_chatter_for_info", True), (OFF, "purchase_followup", False),
         (F_SELL, "purchase_followup", True)]
FANSLY_TICKS: list[str] = []
REAL_FAST_TICK = pp.run_fast_tick
ORDER: list[str] = []          # every poll's start, both lanes, in order


async def _seed() -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        for a in ACCOUNTS:
            s.add(Account(id=a, nickname=a))
        s.add(User(id="tier-admin", username="tier-admin", password="x", is_admin=True, last_seen_at=now))
        s.add(User(id="tier-owner", username="tier-owner", password="x", last_seen_at=now))
        s.add(Chatter(id="tier-chatter", username="tier-chatter", password="x", is_active=True, last_seen_at=now))
        await s.flush()
        for a in ACCOUNTS:
            s.add(UserAccount(user_id="tier-owner", account_id=a))
        s.add(ChatterUser(chatter_id="tier-chatter", user_id="tier-owner"))
        for a, kind, on in RULES:
            s.add(AutomationRule(account_id=a, name=kind, kind=kind, trigger_json="{}", steps_json="[]",
                                 is_enabled=on))


DEAD: dict[str, object] = {}   # what account_health.dead_session_map answers inside _patched


@contextlib.asynccontextmanager
async def _patched(fake_tick, live=ACCOUNTS, stagger=0.0, concurrency=5):
    async def _none(*_a, **_k):
        return None

    async def _off():
        return set()

    async def _dead():
        return dict(DEAD)

    async def _false(_aid):
        return False

    real_tick = pp.run_fast_tick

    async def _tick(aid):
        # A Fansly Creator takes the product's own platform seam (run_fast_tick -> fansly_revenue).
        return await (real_tick(aid) if aid in FANSLY else fake_tick(aid))

    async def _fansly_tick(aid):
        FANSLY_TICKS.append(aid)
        ORDER.append(aid)
        return types.SimpleNamespace(rows_inserted=0, error=None)

    saved = {(m, k): getattr(m, k) for m, k in ((pp, "run_fast_tick"), (pp, "boot_grace"), (ti, "_is_paused"),
                                                (pp, "_FAST_POLL_STAGGER_S"), (pp, "_FAST_POLL_CONCURRENCY"))}
    saved_list, saved_off = ti.account_registry.list_accounts, ti.account_health.deactivated_ids
    saved_dead = ti.account_health.dead_session_map
    ti.account_health.dead_session_map = _dead
    saved_fansly = ti.fansly_backend.is_fansly, ti.fansly_revenue.run_one_tick
    pp.run_fast_tick, pp.boot_grace, ti._is_paused = _tick, _none, _false
    ti.fansly_backend.is_fansly = lambda a: a in FANSLY
    ti.fansly_revenue.run_one_tick = _fansly_tick
    pp._FAST_POLL_STAGGER_S, pp._FAST_POLL_CONCURRENCY = stagger, concurrency
    ti.account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in live]
    ti.account_health.deactivated_ids = _off
    try:
        yield
    finally:
        for (m, k), v in saved.items():
            setattr(m, k, v)
        ti.account_registry.list_accounts, ti.account_health.deactivated_ids = saved_list, saved_off
        ti.account_health.dead_session_map = saved_dead
        ti.fansly_backend.is_fansly, ti.fansly_revenue.run_one_tick = saved_fansly


async def _one_cycle(outcomes=None, poll=None, **kw) -> list[str]:
    """One loop cycle; `outcomes` (Creator -> Outcome) is what each fake poll answers (default ok). With
    `poll` (a fake purchase_notifications.poll_purchases) an OnlyFans Creator's poll is the real run_fast_tick."""
    FANSLY_TICKS.clear()
    ORDER.clear()

    async def _tick(aid):
        ORDER.append(aid)
        if poll is not None:
            return await REAL_FAST_TICK(aid)
        return {"outcome": (outcomes or {}).get(aid, decide.Outcome("ok"))}

    saved = ti._client_for, ti.purchase_notifications.poll_purchases
    if poll is not None:
        ti._client_for, ti.purchase_notifications.poll_purchases = (lambda _aid: object()), poll
    try:
        async with _patched(_tick, **kw):
            task = asyncio.create_task(pp.start_fast_poll())
            await asyncio.sleep(0.5)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        ti._client_for, ti.purchase_notifications.poll_purchases = saved
    return list(ORDER)


async def case_tiers_ignore_presence():
    await _seed()
    view_lease._holders.clear()
    view_lease.renew(("user", "tier-owner", "t1"), [LEASED], LEASED)
    sellers = await ti._seller_account_ids()
    assert sellers == {AUTO, FUNNEL, FU, F_SELL}, sorted(sellers)
    pp._poll_state.clear()
    ago = time.monotonic() - 20
    pp._poll_state.update({a: decide.PollState(ago) for a in ACCOUNTS})
    polled = await _one_cycle()
    assert sorted(polled) == sorted([AUTO, FUNNEL, FU, LEASED, F_SELL]), sorted(polled)
    assert FANSLY_TICKS == [F_SELL], f"through the Fansly lane: {FANSLY_TICKS}"
    view_lease._holders.clear()


async def case_idle_still_polled():
    view_lease._holders.clear()
    pp._poll_state.clear()
    pp._poll_state[QUIET] = decide.PollState(time.monotonic() - decide.SLOW_S)
    pp._poll_state[OLD] = decide.PollState(time.monotonic() - 20)
    polled = await _one_cycle()
    assert QUIET in polled, sorted(polled)
    assert OLD not in polled, "Idle polled 20 s ago: not due"
    for aid in (IDLE, OFF, F_IDLE):            # never polled: its phase decides
        assert aid in pp._poll_state, aid
        phase_now = decide.due(decide.first_idle_state(aid, 0.0, None), "slow", 0.0)
        assert (aid in polled) is phase_now, (aid, phase_now, sorted(polled))


async def case_demand_first():
    view_lease._holders.clear()
    long_ago = time.monotonic() - 2 * decide.SLOW_S
    pp._poll_state.clear()
    pp._poll_state.update({a: decide.PollState(long_ago) for a in ACCOUNTS})   # every Creator due
    polled = await _one_cycle(stagger=0.01, concurrency=1)
    fast = {AUTO, FUNNEL, FU, F_SELL}
    assert sorted(polled) == sorted(ACCOUNTS), sorted(polled)
    first_idle = min(i for i, a in enumerate(polled) if a not in fast)
    assert all(a in fast for a in polled[:first_idle]) and not fast & set(polled[first_idle:]), polled


async def case_poll_now_single_flight():
    reads: list[str] = []
    gate = asyncio.Event()

    async def _tick(aid):
        reads.append(aid)
        await gate.wait()
        return {"aid": aid}

    real_single_flight = pp._single_flight
    joins: list[asyncio.Task | None] = []
    joined = asyncio.Event()

    def _counting_single_flight(account_id, tier):
        t = real_single_flight(account_id, tier)
        joins.append(t)
        if len(joins) == 2:
            joined.set()
        return t

    async with _patched(_tick, live=[AUTO, IDLE]):
        pp._poll_inflight.clear()
        loop_poll = pp._single_flight(AUTO, "fast")          # the loop's tick, in flight
        pp._single_flight = _counting_single_flight
        try:
            a = asyncio.create_task(pp.poll_now(AUTO))
            b = asyncio.create_task(pp.poll_now(AUTO))
            # Both callers reached the gate (poll_now awaits DB reads first, so no fixed sleep is enough).
            await asyncio.wait_for(joined.wait(), 10)
            assert joins == [loop_poll, loop_poll], "both joined the loop's poll"
            assert reads == [AUTO], reads
            gate.set()
            assert await a == {"aid": AUTO} and await b == {"aid": AUTO}
            assert await loop_poll == {"aid": AUTO}
        finally:
            pp._single_flight = real_single_flight
        assert reads == [AUTO], f"one feed read, got {reads}"
        assert AUTO not in pp._poll_inflight
        assert await pp.poll_now(LEASED) is None, "no live session: skipped"
        assert await pp.poll_now(IDLE) == {"aid": IDLE} and reads == [AUTO, IDLE]


def _all_polled_long_ago() -> None:
    view_lease._holders.clear()
    pp._poll_state.clear()
    ago = time.monotonic() - 2 * decide.SLOW_S
    pp._poll_state.update({a: decide.PollState(ago) for a in ACCOUNTS})


async def case_dead_session_skipped():
    _all_polled_long_ago()
    DEAD.clear()
    DEAD[AUTO] = object()
    try:
        polled = await _one_cycle()
        assert AUTO not in polled and FUNNEL in polled, sorted(polled)
        assert AUTO not in await ti.live_account_ids(), "the ledger supervisor, chargebacks, post sweep: same set"
        reads: list[str] = []

        async def _tick(aid):
            reads.append(aid)
            return {}
        async with _patched(_tick):
            assert await pp.poll_now(AUTO) is None and reads == [], "a Select refresh honours the dead set"
    finally:
        DEAD.clear()
    polled = await _one_cycle()
    assert AUTO in polled, "flag cleared: polled on the next cycle, no poll-state reset needed"


async def case_429_holds_the_creator():
    _all_polled_long_ago()
    polled = await _one_cycle({AUTO: decide.Outcome("rate_limited", retry_after_s=90.0)})
    assert AUTO in polled
    st = pp._poll_state[AUTO]
    assert st.step == 1 and st.hold_s == 90.0, st
    _all_polled_long_ago()                                  # every interval up: only the hold decides
    pp._poll_state[AUTO] = dataclasses.replace(pp._poll_state[AUTO], step=st.step, held_at=st.held_at,
                                               hold_s=st.hold_s)
    polled = await _one_cycle()
    assert AUTO not in polled and FUNNEL in polled, sorted(polled)
    reads: list[str] = []

    async def _tick(aid):
        reads.append(aid)
        return {}
    async with _patched(_tick):
        assert await pp.poll_now(AUTO) is None and reads == [], "poll_now inside a backoff: no call"
    # the hold over (90 s ago), the next cycle polls it, and an ok resets the ladder
    pp._poll_state[AUTO] = dataclasses.replace(pp._poll_state[AUTO], held_at=st.held_at - 90)
    polled = await _one_cycle()
    assert AUTO in polled and pp._poll_state[AUTO].step == 0 and pp._poll_state[AUTO].held_at is None


async def case_dead_outcome_flags_unauthorized_does_not():
    _all_polled_long_ago()
    marked: list[tuple] = []
    failures: list[str] = []

    async def _mark(aid, reason):
        marked.append((aid, reason))
        return True

    async def _fail(aid, *_a, **_k):
        failures.append(aid)

    saved = ti.account_health.mark_session_dead, ti._record_failure
    ti.account_health.mark_session_dead, ti._record_failure = _mark, _fail
    try:
        await _one_cycle({AUTO: decide.Outcome("dead", reason="wrong_user"), FUNNEL: decide.Outcome("unauthorized")})
    finally:
        ti.account_health.mark_session_dead, ti._record_failure = saved
    assert marked == [(AUTO, "wrong_user")], marked
    assert failures == [], f"feed outcomes never count toward the supervisor's pause: {failures}"
    assert pp._poll_state[AUTO].held_at is None, "dead holds no poll state"
    assert pp._poll_state[FUNNEL].step == 1 and pp._poll_state[FUNNEL].hold_s == decide.BACKOFF_BASE_S


async def case_poll_now_stamps_last_ok_not_the_schedule():
    _all_polled_long_ago()
    before = pp._poll_state[AUTO]
    answer = [decide.Outcome("ok")]
    reads: list[str] = []

    async def _tick(aid):
        reads.append(aid)
        return {"outcome": answer[0]}
    async with _patched(_tick):
        t0 = time.monotonic()
        await pp.poll_now(AUTO)
        st = pp._poll_state[AUTO]
        assert st.last_s == before.last_s, "the loop's schedule is not moved"
        assert st.last_ok_s is not None and st.last_ok_s >= t0, st
        # A Demand Creator's 429 on a Select refresh: the hold runs from OF's answer, last-ok stays the ok
        # poll's, and a Select refresh makes no call before the cap (OF asked longer).
        answer[0] = decide.Outcome("rate_limited", retry_after_s=600.0)
        await pp.poll_now(AUTO)
        t1 = time.monotonic()
        st2 = pp._poll_state[AUTO]
        assert st2.held_at <= t1 and st2.held_at >= st.last_ok_s and st2.last_ok_s == st.last_ok_s, st2
        answer[0] = decide.Outcome("ok")
        cap = decide.BACKOFF_DEMAND_MAX_S
        pp._poll_state[AUTO] = dataclasses.replace(st2, held_at=time.monotonic() - cap + decide.FAST_S / 2)
        n = len(reads)
        assert await pp.poll_now(AUTO) is None and len(reads) == n, "inside the cap, the next tick past it: no call"
        pp._poll_state[AUTO] = dataclasses.replace(st2, held_at=time.monotonic() - cap)
        assert await pp.poll_now(AUTO) is not None and len(reads) == n + 1, "the cap reached: polled"


async def case_cap_poll_starts_at_the_hold_end():
    _all_polled_long_ago()
    cap = decide.BACKOFF_DEMAND_MAX_S
    starts: list[tuple[str, float]] = []

    async def _tick(aid):
        starts.append((aid, time.monotonic()))
        return {"outcome": decide.Outcome("ok")}
    end = time.monotonic() + 0.2                           # the capped hold ends 0.2 s into the cycle
    pp._poll_state[AUTO] = dataclasses.replace(pp._poll_state[AUTO], step=6, held_at=end - cap, hold_s=600.0)
    async with _patched(_tick):
        task = asyncio.create_task(pp.start_fast_poll())
        await asyncio.sleep(0.6)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    at = [t for a, t in starts if a == AUTO]
    assert len(at) == 1 and end <= at[0] < end + 0.2, (at, end)
    assert FUNNEL in [a for a, _ in starts] and AUTO not in pp._poll_timers
    assert pp._poll_state[AUTO].step == 0, "the ok at the hold's end resets the ladder"
    # One pending timer per Creator; a poll starting first cancels it.
    pp._poll_state[AUTO] = dataclasses.replace(pp._poll_state[AUTO], step=1, held_at=time.monotonic() - cap + 5.0,
                                               hold_s=600.0)
    async with _patched(_tick):
        pp._poll_at_hold_end(AUTO, "fast")
        first = pp._poll_timers[AUTO]
        pp._poll_at_hold_end(AUTO, "fast")
        assert pp._poll_timers[AUTO] is first and len(pp._poll_timers) == 1
        pp._poll_state[AUTO] = dataclasses.replace(pp._poll_state[AUTO], held_at=time.monotonic() - cap)
        await pp._single_flight(AUTO, "fast")
        assert first.cancelled() and AUTO not in pp._poll_timers


async def case_hold_end_timer_rechecks_eligibility():
    """A hold-end timer armed for a Demand Creator polls nothing when, by its end, the Creator is paused, flagged a
    Dead session, or no longer Demand (its lease lapsed: the uncapped Idle hold rules): the same gate as poll_now,
    with the tier read at the hold's end (fetch-diet rwl2 F4)."""
    _all_polled_long_ago()
    cap = decide.BACKOFF_DEMAND_MAX_S
    starts: list[str] = []

    async def _tick(aid):
        starts.append(aid)
        return {"outcome": decide.Outcome("ok")}

    def _held(aid):
        pp._poll_state[aid] = dataclasses.replace(pp._poll_state[aid], step=6,
                                                  held_at=time.monotonic() + 0.1 - cap, hold_s=600.0)
    view_lease._holders.clear()
    view_lease.renew(("user", "tier-owner", "t1"), [LEASED], None)
    paused = {FU}
    async with _patched(_tick):
        async def _paused(aid):
            return aid in paused
        ti._is_paused = _paused
        for aid in (AUTO, FU, LEASED, FUNNEL):
            _held(aid)
            pp._poll_at_hold_end(aid, "fast")
        DEAD[AUTO] = object()                 # flagged dead before its hold ends
        view_lease._holders.clear()           # LEASED's lease lapses: Idle, its 600 s hold uncapped
        try:
            await asyncio.sleep(0.4)
        finally:
            DEAD.clear()
    assert starts == [FUNNEL], f"only the still-eligible Demand Creator is polled at its hold's end: {starts}"
    assert not pp._poll_timers, pp._poll_timers


async def case_held_past_next_tick_starts_at_the_hold_end():
    """A Demand hold ending just past the loop's look-ahead (due: held) starts at its end, not a tick
    late: the next tick is FAST_S + the cycle's work away."""
    _all_polled_long_ago()
    cap = decide.BACKOFF_DEMAND_MAX_S
    starts: list[float] = []

    async def _tick(aid):
        if aid == AUTO:
            starts.append(time.monotonic())
        return {"outcome": decide.Outcome("ok")}
    fast, decide.FAST_S = decide.FAST_S, 0.2
    try:
        end = time.monotonic() + 0.3                        # past now + FAST_S, before 2 * FAST_S
        pp._poll_state[AUTO] = dataclasses.replace(pp._poll_state[AUTO], step=6, held_at=end - cap, hold_s=600.0)
        async with _patched(_tick):
            task = asyncio.create_task(pp.start_fast_poll())
            await asyncio.sleep(0.6)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        decide.FAST_S = fast
    assert len(starts) == 1 and end <= starts[0] < end + 0.1, (starts, end)


async def case_catch_up_after_a_gap():
    read: list[int] = []

    async def _poll(account_id, client, *, limit, pages=1):
        read.append(pages)
        return {"seen": 0, "flipped": 0, "posts": 0, "stamped": 0, "outcome": decide.Outcome("ok")}
    view_lease._holders.clear()
    pp._poll_state.clear()
    await _one_cycle(poll=_poll, live=[AUTO])                            # no state: a restart
    now = time.monotonic()
    pp._poll_state[AUTO] = decide.PollState(now - decide.SLOW_S, now - 1)             # ok a second ago
    await _one_cycle(poll=_poll, live=[AUTO])
    pp._poll_state[AUTO] = decide.PollState(now - decide.SLOW_S, now - decide.SLOW_S)  # an Idle gap
    await _one_cycle(poll=_poll, live=[AUTO])
    assert read == [decide.CATCHUP_MAX_PAGES, 1, decide.CATCHUP_MAX_PAGES], read


_harness.run()
