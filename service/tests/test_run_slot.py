"""A run hands its concurrency slot back while it only waits (run_slot).

The supervisor's `_one` takes its permit through `run_slot.hold(pool)`; the
typing hold (`_common.hold_with_typing`) wraps its sleep in
`run_slot.released()`. The OF write spacing (`of_write_paced`) does not: it
can run under `broadcast_lock`. These cases pin that the permit is really free
during the wait, comes back after and ahead of fresh runs, within the run's budget or
not at all (SlotLost), is never released by a task that does not own it, nor
for a short hold, nor with the knob off, and that the
pool count stays exact when a run is cancelled or raises mid-wait. The
`case_the_pool_*` cases drive SlotPool alone: a permit granted to a waiter
cancelled before it resumes passes on, a timeout leaves no waiter, a reserve
permit goes to the next operator or back.

Run: ./venv/bin/python service/tests/test_run_slot.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import asyncio
import os

import automation_executor as ax
import run_slot
from automations import _common

_harness.bootstrap()

B = 120.0   # the budget hold_with_typing passes (rhythm.INLINE_MAX_S)


async def _free(pool: run_slot.SlotPool) -> bool:
    """Can another (fresh) run take a permit right now?"""
    try:
        await asyncio.wait_for(pool.acquire(), 0.05)
    except TimeoutError:
        return False
    pool.release()
    return True


def _released(seconds: float = 5.0, budget_s: float = B):
    return run_slot.released(seconds, budget_s=budget_s)   # the knob's default floor: 3 s


async def case_released_frees_the_slot_and_takes_it_back():
    pool = run_slot.SlotPool(1)
    seen: list[bool] = []
    async with run_slot.hold(pool):
        seen.append(await _free(pool))          # held: nobody else gets in
        async with _released():
            seen.append(await _free(pool))      # waiting: the slot is free
        seen.append(await _free(pool))          # back to work: held again
    assert seen == [False, True, False], seen
    assert pool.free == 1


async def case_the_freed_slot_serves_another_run():
    pool = run_slot.SlotPool(1)
    order: list[str] = []

    async def typing_run():
        async with run_slot.hold(pool):
            order.append("a:start")
            async with _released():
                await asyncio.sleep(0.05)
            order.append("a:send")

    async def other_run():
        await asyncio.sleep(0.01)
        async with run_slot.hold(pool):
            order.append("b:ran")
    await asyncio.gather(typing_run(), other_run())
    assert order == ["a:start", "b:ran", "a:send"], order
    assert pool.free == 1


async def case_a_reacquirer_beats_a_fresh_run_queued_first():
    """The hog holds the only slot; a fresh run queues for it, THEN the typing
    run finishes its hold and queues to take its slot back. The hog leaves:
    the run mid-reply (fan lease, run lock) must get the slot first."""
    pool = run_slot.SlotPool(2)
    order: list[str] = []
    hog_in, hog_go, typing_go = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def typing_run():
        async with run_slot.hold(pool):
            async with _released():
                await hog_in.wait()
                await asyncio.sleep(0.02)       # the fresh run queues meanwhile
            order.append("typing:back")
            await typing_go.wait()              # holds its slot until the check below
        order.append("typing:done")

    async def hog():
        async with run_slot.hold(pool):
            hog_in.set()
            await hog_go.wait()

    async def fresh():
        await hog_in.wait()
        async with run_slot.hold(pool):
            order.append("fresh:ran")
    async with run_slot.hold(pool):             # a third run: 2 slots, both taken
        tasks = [asyncio.create_task(c()) for c in (typing_run, hog, fresh)]
        await asyncio.sleep(0.05)
        assert pool.queued() == (1, 1), pool.queued()
        hog_go.set()
        await asyncio.gather(*tasks[1:2])
        await asyncio.sleep(0.005)
        assert order == ["typing:back"], order  # fresh still waits behind it
        typing_go.set()
    await asyncio.gather(*tasks)
    assert order[0] == "typing:back" and "fresh:ran" in order, order
    assert pool.free == 2


async def case_take_back_past_the_budget_loses_the_slot():
    """Hold + wait > budget: SlotLost after the sleep, the count stays exact,
    and every later hold of that run raises before it can send."""
    pool = run_slot.SlotPool(1)
    sent: list[int] = []
    hog_go = asyncio.Event()

    async def hog():
        async with run_slot.hold(pool):
            await hog_go.wait()

    async def run():
        async with run_slot.hold(pool):
            for i in range(3):
                try:
                    async with _released(5.0, budget_s=0.05):
                        await asyncio.sleep(0.01)
                except run_slot.SlotLost:
                    sent.append(-1)
                    continue
                sent.append(i)
    r = asyncio.create_task(run())
    await asyncio.sleep(0.005)                  # run() released; the hog takes the slot
    h = asyncio.create_task(hog())
    await r
    assert sent == [-1, -1, -1], sent           # nothing after the timeout
    hog_go.set()
    await h
    assert pool.free == 1, pool.free


async def case_the_take_back_budget_is_per_run_not_per_hold():
    """Each take-back waits ~40 ms, well inside a 100 ms budget, but the run's
    waits add up: the third crosses it and raises, so many holds of one reply
    (or one run's several replies) cannot stretch past the fan lease."""
    pool = run_slot.SlotPool(1)
    sent: list[int] = []

    async def hog():
        async with run_slot.hold(pool):
            await asyncio.sleep(0.04)
    async with run_slot.hold(pool) as slot:
        try:
            for i in range(5):
                async with _released(5.0, budget_s=0.1):
                    h = asyncio.create_task(hog())
                    await asyncio.sleep(0.005)          # the hog has the slot now
                sent.append(i)
        except run_slot.SlotLost:
            pass
        await h
        assert sent == [0, 1], sent
        assert slot.lost and slot.releases == 3, (slot.lost, slot.releases)
        assert 0.09 <= slot.waited_s <= 0.13, slot.waited_s
    assert pool.free == 1, pool.free


async def case_a_short_hold_keeps_the_slot():
    pool = run_slot.SlotPool(1)
    async with run_slot.hold(pool):
        async with _released(2.5):
            assert not await _free(pool)


async def case_the_knob_turns_release_off():
    pool = run_slot.SlotPool(1)
    os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"] = "120"
    try:
        async with run_slot.hold(pool):
            async with run_slot.released(60.0, budget_s=B):
                assert not await _free(pool)
    finally:
        del os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"]
    assert run_slot.release_floor_s() == 3
    async with run_slot.hold(pool):
        async with run_slot.released(60.0, budget_s=B):
            assert await _free(pool)


async def case_outside_a_run_is_a_plain_wait():
    async with _released():
        await asyncio.sleep(0)


async def case_a_child_task_never_releases_the_parents_slot():
    pool = run_slot.SlotPool(1)
    seen: list[bool] = []

    async def child():
        async with _released():                 # inherits the context, not the slot
            seen.append(await _free(pool))
    async with run_slot.hold(pool):
        await asyncio.create_task(child())
    assert seen == [False], seen
    assert pool.free == 1


async def case_a_lent_slot_is_free_only_while_every_child_waits():
    """send_welcome's paced pool (run_paced): the children share the run's
    permit. It is held while one of them works and handed back while all of
    them sit in a hold; the run has it again after the pool."""
    pool = run_slot.SlotPool(1)
    seen: dict[str, bool] = {}
    a_hold, b_hold, a_back = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def child(name: str, hold_in: asyncio.Event, peek: bool):
        async with run_slot.borrowed(budget_s=B):
            if peek:
                seen["one working"] = await _free(pool)
            async with _released():
                hold_in.set()
                if name == "a":
                    await b_hold.wait()
                    seen["all holding"] = await _free(pool)
                if name == "b":
                    await a_back.wait()
                else:
                    await asyncio.sleep(0.01)
            if name == "a":
                seen["a back, b holding"] = await _free(pool)
                a_back.set()
    async with run_slot.hold(pool) as slot:
        async with run_slot.lend(budget_s=B):
            await asyncio.gather(child("a", a_hold, True), child("b", b_hold, False))
        seen["after the pool"] = await _free(pool)
        assert slot.held and not slot.lost
    assert seen == {"one working": False, "all holding": True,
                    "a back, b holding": False, "after the pool": False}, seen
    assert pool.free == 1, pool.free


async def case_lent_children_take_back_ahead_of_fresh_runs_once():
    """Two children leave their holds while a hog has the slot and a fresh run
    queued first: one take-back (not two permits), served before the fresh run."""
    pool = run_slot.SlotPool(1)
    order: list[str] = []
    hog_in, hog_go = asyncio.Event(), asyncio.Event()

    async def hog():
        async with run_slot.hold(pool):
            hog_in.set()
            await hog_go.wait()

    async def fresh():
        await hog_in.wait()
        async with run_slot.hold(pool):
            order.append("fresh")

    holding = asyncio.Semaphore(0)

    async def child(name):
        async with run_slot.borrowed(budget_s=B):
            async with _released():
                holding.release()
                await hog_in.wait()
                await asyncio.sleep(0.02)
            order.append(name)
            await asyncio.sleep(0.01)
    async with run_slot.hold(pool):
        async with run_slot.lend(budget_s=B):
            kids = asyncio.gather(child("a"), child("b"))
            await holding.acquire()
            await holding.acquire()                    # both children are in their holds
            h, f = asyncio.create_task(hog()), asyncio.create_task(fresh())
            await asyncio.sleep(0.05)
            assert pool.queued() == (1, 1), pool.queued()   # ONE take-back for both
            hog_go.set()
            await kids
        assert "fresh" not in order, order
    await asyncio.gather(h, f)
    assert order == ["a", "b", "fresh"], order
    assert pool.free == 1, pool.free


async def case_a_lent_slot_past_the_budget_stops_every_child_and_the_run():
    pool = run_slot.SlotPool(1)
    sent: list[str] = []
    hog_go = asyncio.Event()

    async def hog():
        async with run_slot.hold(pool):
            await hog_go.wait()

    async def child(name):
        async with run_slot.borrowed(budget_s=0.05):
            async with _released(5.0, budget_s=0.05):
                await asyncio.sleep(0.01)
            sent.append(name)
    h = None
    try:
        async with run_slot.hold(pool) as slot:
            async with run_slot.lend(budget_s=0.05):
                kids = [asyncio.create_task(child(n)) for n in "ab"]
                await asyncio.sleep(0.005)
                h = asyncio.create_task(hog())          # takes the freed permit
                res = await asyncio.gather(*kids, return_exceptions=True)
                assert all(isinstance(r, run_slot.SlotLost) for r in res), res
        raise AssertionError("the run took its slot back past the budget")
    except run_slot.SlotLost:
        pass
    assert sent == [] and slot.lost, (sent, slot.lost)
    hog_go.set()
    await h
    assert pool.free == 1, pool.free


async def case_a_child_cancelled_mid_hold_leaves_its_siblings_and_the_count():
    pool = run_slot.SlotPool(2)
    sent: list[str] = []

    async def child(name, s):
        async with run_slot.borrowed(budget_s=B):
            async with _released():
                await asyncio.sleep(s)
            sent.append(name)
    async with run_slot.hold(pool) as slot:
        async with run_slot.lend(budget_s=B):
            a = asyncio.create_task(child("a", 10))
            b = asyncio.create_task(child("b", 0.03))
            await asyncio.sleep(0.01)
            a.cancel()
            await asyncio.gather(a, b, return_exceptions=True)
        assert slot.held and not slot.lost and slot.busy == 0
    assert sent == ["b"], sent
    assert pool.free == 2, pool.free


async def case_the_switch_turns_release_off_and_on_at_once():
    """AUTOMATION_RELEASE_SLOT_ON_HOLD (ADR 0025 fix 5): saved 0 from the
    panel, a hold keeps its slot and a run lends nothing; saved 1, the very
    next hold of the same run hands it back. An env "off" beats a stored 1.
    The row is a switch, live, never pending."""
    import lane_config
    knob = "AUTOMATION_RELEASE_SLOT_ON_HOLD"
    assert "tmp" in lane_config.path() or "/T/" in lane_config.path(), lane_config.path()
    assert run_slot.release_on()                        # default on; registers the switch
    pool = run_slot.SlotPool(1)
    seen: list[bool] = []
    try:
        lane_config.set_many({knob: 0})
        async with run_slot.hold(pool):
            async with run_slot.released(60.0, budget_s=B):
                assert not await _free(pool), "switched off, yet the hold released"
            async with run_slot.lend(budget_s=B):
                async def child():
                    async with run_slot.borrowed(budget_s=B):
                        async with run_slot.released(60.0, budget_s=B):
                            seen.append(await _free(pool))
                await asyncio.create_task(child())
            lane_config.set_many({knob: 1})
            async with run_slot.released(60.0, budget_s=B):
                assert await _free(pool), "switched back on, the same run's next hold releases"
        assert seen == [False], seen
        row = next(r for r in lane_config.describe() if r["name"] == knob)
        assert row["switch"] and row["value"] == row["live"] == 1 and not row["pending"], row
        os.environ[knob] = "off"
        try:
            assert not run_slot.release_on()
            async with run_slot.hold(pool):
                async with run_slot.released(60.0, budget_s=B):
                    assert not await _free(pool)
        finally:
            del os.environ[knob]
    finally:
        lane_config.set_many({knob: None})
    assert run_slot.release_on() and pool.free == 1


async def case_the_kill_switch_turns_lending_off():
    pool = run_slot.SlotPool(1)
    seen: list[bool] = []
    os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"] = "120"
    try:
        async with run_slot.hold(pool):
            async with run_slot.lend(budget_s=B):
                async def child():
                    async with run_slot.borrowed(budget_s=B):
                        async with run_slot.released(60.0, budget_s=B):
                            seen.append(await _free(pool))
                await asyncio.create_task(child())
    finally:
        del os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"]
    assert seen == [False], seen
    assert pool.free == 1


async def case_run_paced_hands_the_slot_back_while_its_bursts_type():
    """The real pool with the real typing hold: while every burst types, a
    fresh run gets the slot; the bursts' sends wait for it to come back."""
    from automations import _run_pool
    pool = run_slot.SlotPool(1)
    seen: list[bool] = []
    saved = _run_pool._sleep
    _run_pool._sleep = lambda s: asyncio.sleep(0)

    async def burst(i):
        await _common.hold_with_typing("acc", i, 1.0)

    async def watch():
        await asyncio.sleep(0.3)
        seen.append(await _free(pool))
    os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"] = "1"
    try:
        async with run_slot.hold(pool) as slot:
            w = asyncio.create_task(watch())
            res = await _run_pool.run_paced([1, 2, 3], burst, concurrency=3, wall_budget_s=60,
                                            started_at=0, clock=lambda: 0, jitter_for=lambda _i: 0)
            await w
            assert res.errors == [] and slot.held and slot.releases >= 1, (res, slot.releases)
            seen.append(await _free(pool))
    finally:
        _run_pool._sleep = saved
        del os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"]
    assert seen == [True, False], seen
    assert pool.free == 1


async def case_an_operator_run_starts_at_once_with_every_slot_taken():
    """ADR 0025 fix 2: automation holds every shared slot and more queue; an
    operator's run starts at once on the reserve. A second operator, with the
    reserve busy, goes ahead of every queued automation run (fresh or taking
    back) for the next shared slot."""
    pool = run_slot.SlotPool(2, reserve=1)
    order: list[str] = []
    go = asyncio.Event()

    async def run(name: str, *, operator: bool = False):
        async with run_slot.hold(pool, operator=operator):
            order.append(name)
            await go.wait()

    hogs = [asyncio.create_task(run(f"hog{i}")) for i in range(2)]
    await asyncio.sleep(0.01)
    fresh = asyncio.create_task(run("fresh"))
    await asyncio.sleep(0.01)
    op1 = asyncio.create_task(run("op1", operator=True))
    await asyncio.sleep(0.01)
    assert order == ["hog0", "hog1", "op1"], ("op1 waited behind automation", order)
    assert (pool.free, pool.reserve_free) == (0, 0), (pool.free, pool.reserve_free)
    op2 = asyncio.create_task(run("op2", operator=True))
    await asyncio.sleep(0.01)
    assert pool.queued_operator() == 1 and pool.queued() == (0, 1), (pool.queued_operator(), pool.queued())
    hogs[0].cancel()                                  # one shared slot frees
    await asyncio.sleep(0.01)
    assert order[-1] == "op2", ("the freed slot went to automation", order)
    go.set()
    await asyncio.gather(*hogs, fresh, op1, op2, return_exceptions=True)
    assert order[-1] == "fresh", order
    assert (pool.free, pool.reserve_free) == (2, 1), (pool.free, pool.reserve_free)


async def case_automation_never_takes_a_reserve_slot():
    pool = run_slot.SlotPool(1, reserve=2)
    async with run_slot.hold(pool):
        assert not await _free(pool), "automation took an operator-only slot"
        assert pool.reserve_free == 2
    assert await _free(pool)


async def case_an_operator_run_takes_its_slot_back_in_its_tier():
    """An operator's run gives its slot back while it types; automation fills
    every shared slot meanwhile. It takes its slot back at once (the reserve),
    and its permit returns to the right side of the pool."""
    pool = run_slot.SlotPool(1, reserve=1)
    hog_in, hog_go = asyncio.Event(), asyncio.Event()

    async def hog():
        async with run_slot.hold(pool):
            hog_in.set()
            await hog_go.wait()

    async with run_slot.hold(pool, operator=True) as slot:
        assert slot.reserve and pool.reserve_free == 0
        h = asyncio.create_task(hog())
        async with _released():
            await hog_in.wait()
        assert slot.held and slot.waited_s < 0.05, slot.waited_s
    assert pool.reserve_free == 1 and pool.free == 0
    hog_go.set()
    await h
    assert (pool.free, pool.reserve_free) == (1, 1)


async def case_an_operator_cancelled_in_the_queue_keeps_both_counts():
    """Cancelled while queued, and cancelled in the same turn a reserve permit
    was handed to it: neither permit is lost or doubled."""
    pool = run_slot.SlotPool(1, reserve=1)
    go = asyncio.Event()

    async def run(operator: bool):
        async with run_slot.hold(pool, operator=operator):
            await go.wait()

    a = asyncio.create_task(run(False))
    b = asyncio.create_task(run(True))                # the reserve
    await asyncio.sleep(0.01)
    c = asyncio.create_task(run(True))                # queued
    await asyncio.sleep(0.01)
    c.cancel()
    await asyncio.gather(c, return_exceptions=True)
    assert pool.queued_operator() == 0
    d = asyncio.create_task(run(True))                # queued again
    await asyncio.sleep(0.01)
    b.cancel()                                        # its reserve permit goes to d…
    await asyncio.sleep(0)
    d.cancel()                                        # …which is cancelled before it runs
    await asyncio.gather(b, d, return_exceptions=True)
    go.set()
    await a
    assert (pool.free, pool.reserve_free) == (1, 1), (pool.free, pool.reserve_free)


async def _parked(pool: run_slot.SlotPool, **kw) -> asyncio.Task:
    """A task parked in `pool.acquire(**kw)` (the pool is full)."""
    t = asyncio.create_task(pool.acquire(**kw))
    await asyncio.sleep(0)
    assert not t.done()
    return t


async def case_the_pool_granted_then_cancelled_before_resuming_passes_it_on():
    """SlotPool alone: a parked waiter is granted, then cancelled before its task
    resumes. Its acquire hands the permit to the next waiter; none is lost."""
    pool = run_slot.SlotPool(1)
    assert await pool.acquire() is False
    a, b = await _parked(pool), await _parked(pool)
    pool.release()                       # a's future resolved, a has not resumed
    a.cancel()
    await asyncio.gather(a, return_exceptions=True)
    assert a.cancelled()
    assert await asyncio.wait_for(b, 1.0) is False      # b got a's permit
    assert pool.queued() == (0, 0) and not pool._wait, (pool.queued(), pool._wait)
    pool.release()
    assert pool.free == 1, pool.free


async def case_the_pool_cancelled_while_parked_then_released_serves_the_next():
    """A parked waiter is cancelled, and a permit is released in the same turn,
    before its handler runs: decide grants the dead waiter, the shell feeds the
    permit straight back, and the next waiter gets it. Counts stay exact."""
    pool = run_slot.SlotPool(1)
    await pool.acquire()
    a, b, c = await _parked(pool), await _parked(pool), await _parked(pool)
    a.cancel()
    pool.release()                       # a is still queued: its grant passes to b
    await asyncio.gather(a, return_exceptions=True)
    assert await asyncio.wait_for(b, 1.0) is False
    assert not c.done() and pool.queued() == (0, 1), pool.queued()
    pool.release()
    assert await asyncio.wait_for(c, 1.0) is False
    pool.release()
    assert (pool.free, pool.queued(), len(pool._wait)) == (1, (0, 0), 0)


async def case_the_pool_timeouts_leave_no_waiter():
    """`wait_for(acquire(), 0)` and a short timeout on a full pool: no waiter is
    left queued, and the permit count is untouched."""
    pool = run_slot.SlotPool(1)
    await pool.acquire()
    for timeout in (0, 0.01):
        try:
            await asyncio.wait_for(pool.acquire(), timeout)
            raise AssertionError("a full pool granted a permit")
        except TimeoutError:
            pass
        assert (pool.free, pool.queued(), len(pool._wait)) == (0, (0, 0), 0), timeout
    pool.release()
    assert pool.free == 1
    assert await asyncio.wait_for(pool.acquire(), 0.01) is False   # straight in
    pool.release()


async def case_the_pool_reserve_goes_to_the_next_operator_or_back():
    """A reserve permit handed back goes to a queued operator (as a reserve one),
    past a dead one granted it first, else back to the reserve."""
    pool = run_slot.SlotPool(1, reserve=1)
    await pool.acquire()                                  # the shared permit
    assert await pool.acquire(operator=True) is True      # the reserve
    fresh = await _parked(pool)
    dead, op = await _parked(pool, operator=True), await _parked(pool, operator=True)
    dead.cancel()
    pool.release(reserve=True)
    await asyncio.gather(dead, return_exceptions=True)
    assert await asyncio.wait_for(op, 1.0) is True        # a reserve permit, not fresh's
    assert not fresh.done() and pool.reserve_free == 0
    pool.release(reserve=True)
    assert pool.reserve_free == 1 and not fresh.done()   # automation never takes it
    pool.release()
    assert await asyncio.wait_for(fresh, 1.0) is False
    pool.release()
    assert (pool.free, pool.reserve_free, len(pool._wait)) == (1, 1, 0)


async def case_a_double_release_is_a_no_op():
    """A RunSlot released twice (and again at the hold's exit) returns ONE permit."""
    pool = run_slot.SlotPool(2, reserve=1)
    for operator in (False, True):
        async with run_slot.hold(pool, operator=operator) as slot:
            slot.release()
            slot.release()
        assert (pool.free, pool.reserve_free) == (2, 1), (operator, pool.free, pool.reserve_free)


def case_auto_runs_follows_the_sweep():
    """ADR 0025 fix 4: the busy sweep's recommendation, 4 up to 20 models and
    one more per 15 after, clamped."""
    got = {n: run_slot.auto_runs(n) for n in (0, 1, 5, 10, 20, 21, 35, 36, 50, 51, 500)}
    assert got == {0: 4, 1: 4, 5: 4, 10: 4, 20: 4, 21: 5, 35: 5, 36: 6, 50: 6, 51: 7, 500: 16}, got


async def case_a_grown_pool_serves_its_waiters_at_once():
    pool = run_slot.SlotPool(1)
    go = asyncio.Event()
    started: list[int] = []

    async def run(i):
        async with run_slot.hold(pool):
            started.append(i)
            await go.wait()
    tasks = [asyncio.create_task(run(i)) for i in range(3)]
    await asyncio.sleep(0.01)
    assert started == [0], started
    pool.resize(3)
    await asyncio.sleep(0.01)
    assert sorted(started) == [0, 1, 2], started
    go.set()
    await asyncio.gather(*tasks)
    assert (pool.n, pool.free) == (3, 3)


async def case_a_shrunk_pool_admits_nobody_until_runs_end():
    pool = run_slot.SlotPool(3)
    go = [asyncio.Event() for _ in range(3)]
    started: list[int] = []

    async def run(i):
        async with run_slot.hold(pool):
            started.append(i)
            await go[i % 3].wait()
    held = [asyncio.create_task(run(i)) for i in range(3)]
    await asyncio.sleep(0.01)
    pool.resize(1)
    late = asyncio.create_task(run(3))           # waits on go[0]
    await asyncio.sleep(0.01)
    go[1].set()
    await asyncio.sleep(0.01)
    assert 3 not in started, ("admitted over the new size", started, pool.free)
    go[2].set()
    await asyncio.sleep(0.01)
    assert 3 not in started, ("admitted with one still running past the new size", started)
    go[0].set()
    await asyncio.gather(*held, late)
    assert 3 in started and (pool.n, pool.free) == (1, 1), (started, pool.free)


async def case_cancelled_mid_wait_keeps_the_count_exact():
    pool = run_slot.SlotPool(2)

    async def run():
        async with run_slot.hold(pool):
            async with _released():
                await asyncio.sleep(10)
    t = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
    assert pool.free == 2, pool.free


async def case_cancelled_while_taking_the_slot_back():
    pool = run_slot.SlotPool(1)
    hog_go = asyncio.Event()

    async def run():
        async with run_slot.hold(pool):
            async with _released():
                await hog_go.wait()             # the hog takes the slot meanwhile

    async def hog():
        async with run_slot.hold(pool):
            hog_go.set()
            await asyncio.sleep(0.05)
    t = asyncio.create_task(run())
    h = asyncio.create_task(hog())
    await asyncio.sleep(0.02)                   # run() is now queued to re-acquire
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
    await h
    assert pool.free == 1, pool.free


async def case_a_raise_mid_wait_does_not_queue_and_ends_slot_work():
    """No take-back just to drop the slot again; a run that swallowed the
    error still cannot send (its next hold raises SlotLost)."""
    pool = run_slot.SlotPool(1)
    async with run_slot.hold(pool) as slot:
        try:
            async with _released():
                raise ValueError("boom")
        except ValueError:
            pass
        assert not slot.held and slot.lost and pool.free == 1
        try:
            async with _released(0.0):
                raise AssertionError("a lost run got past its next hold")
        except run_slot.SlotLost:
            pass
    assert pool.free == 1, pool.free


async def case_typing_hold_releases_the_slot_write_spacing_keeps_it():
    pool = run_slot.SlotPool(1)
    seen: list[bool] = []

    async def watch():
        await asyncio.sleep(0.02)
        seen.append(await _free(pool))

    os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"] = "1"   # the floor is whole seconds
    try:
        async with run_slot.hold(pool):             # the waits run IN the run's task
            w = asyncio.create_task(watch())
            await _common.hold_with_typing("acc", 1, 1.0)
            await w
            aid = "run-slot-test"
            ax._write_gate(aid).next_at = asyncio.get_running_loop().time() + 0.1
            w = asyncio.create_task(watch())
            await ax.of_write_paced(aid, lambda: None, send_purpose="not_fan_dm")
            await w
            seen.append(await _free(pool))
    finally:
        del os.environ["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"]
    assert seen == [True, False, False], seen
    assert pool.free == 1


async def case_an_alias_run_does_not_queue_on_the_run_lock():
    """`of_ai_chat` and `welcome_chatter_for_info` are two in-flight pairs but
    one run lock. Both pass the first `lock.locked()` check (the session checks
    await); the loser must come back `in_flight`, not wait on the lock with a
    slot pinned (automation_executor.run_once)."""
    gate = asyncio.Event()
    calls: list[str] = []

    async def fake(account_id, payload, *, run_id):
        calls.append("ran")
        await gate.wait()
        return {}

    async def slow_check(_aid):
        await asyncio.sleep(0.01)
        return False
    saved = (ax.get_automation, ax.account_health.is_session_dead, ax.account_health.is_deactivated)
    ax.get_automation = lambda k: fake
    ax.account_health.is_session_dead = slow_check
    ax.account_health.is_deactivated = slow_check
    try:
        a = asyncio.create_task(ax.run_once("acc-alias", "of_ai_chat", payload={}))
        b = asyncio.create_task(ax.run_once("acc-alias", "welcome_chatter_for_info", payload={}))
        done, _ = await asyncio.wait({b}, timeout=1.0)
        assert b in done, "the second alias queued on the run lock"
        assert b.result() == {"status": "skipped", "reason": "in_flight"}, b.result()
        gate.set()
        assert (await a)["status"] == "ok"
        assert calls == ["ran"], calls
    finally:
        gate.set()
        ax.get_automation, ax.account_health.is_session_dead, ax.account_health.is_deactivated = saved


if __name__ == "__main__":
    _harness.run()
