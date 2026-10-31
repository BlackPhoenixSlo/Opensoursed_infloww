#!/usr/bin/env python3
"""`server._periodic` — the one loop every background sweeper runs on.

WHY THIS FILE EXISTS. Six sweepers (img cache, storyboard locks, perflog,
raw_json, audit retention, payload size cap) were six hand-copied
transcriptions of the same eight lines. Copies drift, and this set drifted in a
way that cost real money: every one of them slept BEFORE its first pass, so the
two with a DAILY interval only ever swept on a process that stayed up longer
than a day. This relay is redeployed, autohealed and restarted far more often
than that, so the honest description of the old behaviour is not "prunes late",
it is "never prunes". Measured on the live DB 2026-08-25, every window blown:
scheduled_jobs (7d window) held rows back to 45d, automation_runs (14d) back to
20d, and 3,668 messages still carried raw_json past a 60-day window.

None of that was catchable by a test, because the schedule was welded to the
work inside six anonymous `while True` bodies. It is one function now, so the
schedule is a thing that can be asserted — which is the actual reason to
extract it, ahead of the 91 lines it deleted.

The cases drive `_periodic` with a fake clock: `asyncio.sleep` is patched to
record what it was asked to wait for and return immediately, so the suite makes
no real-time assertions and cannot go flaky on a loaded machine.

Run: ./venv/bin/python service/tests/test_periodic_loop.py   (exit 0 = green)
"""
import _harness  # MUST be first — sets sys.path / binds a throwaway temp DB

import asyncio  # noqa: E402

import server  # noqa: E402
import diag_api  # noqa: E402
import img_api  # noqa: E402


class _StopLoop(BaseException):
    """Raised by the fake clock to end an otherwise-infinite loop.

    Inherits BaseException, and that is load-bearing in BOTH directions.

    It must not be `Exception`, because `_periodic`'s whole job is to swallow
    those and keep going — the first draft of this file subclassed Exception
    and the suite hung forever on case 1, which is the helper working exactly
    as designed. It must not be `CancelledError` either: that is the other
    control path `_periodic` handles, so a test using it could not tell a
    correct loop from one that quit for reasons of its own.

    BaseException passes straight through both handlers, so the only thing that
    stops the loop is the clock deciding it has seen enough ticks.
    """


async def _drive(coro_factory, *, ticks: int):
    """Run `_periodic` with a fake clock, stopping after `ticks` sleeps.

    Returns the list of durations it asked to sleep for, in order.
    """
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(d, *a, **kw):
        slept.append(d)
        if len(slept) > ticks:
            raise _StopLoop
        await real_sleep(0)          # yield, so the loop is genuinely async

    asyncio.sleep = fake_sleep       # type: ignore[assignment]
    try:
        try:
            await coro_factory()
        except _StopLoop:
            pass
    finally:
        asyncio.sleep = real_sleep   # type: ignore[assignment]
    return slept


def case_first_pass_waits_a_full_interval_by_default() -> None:
    """The behaviour every hourly sweeper already relied on, kept intact."""
    calls = []

    async def work():
        calls.append(1)

    slept = asyncio.run(_drive(
        lambda: server._periodic("t", 3600, work), ticks=3,
    ))
    assert slept[:3] == [3600, 3600, 3600], f"expected a steady interval, got {slept[:3]}"
    assert len(calls) == 3, f"work ran {len(calls)} times, expected 3"


def case_first_after_s_moves_only_the_first_pass() -> None:
    """The fix. A daily sweeper must not wait a day to run for the first time.

    This is the assertion that would have failed before the change: the first
    sleep was the full interval, so on a process that never lives that long the
    sweep never happened at all.
    """
    async def work():
        return None

    slept = asyncio.run(_drive(
        lambda: server._periodic("t", 86_400, work, first_after_s=300), ticks=3,
    ))
    assert slept[0] == 300, f"first pass should wait the grace, waited {slept[0]}"
    assert slept[1:3] == [86_400, 86_400], (
        f"after the first pass it must settle onto the interval, got {slept[1:3]}"
    )


def case_a_failing_cycle_does_not_kill_the_sweeper() -> None:
    """One bad cycle must never take a sweeper down for the life of the process.

    Every caller relies on this: these tasks are spawned once at startup and
    never restarted, so a loop that exits on its first exception is a sweeper
    that silently stops for the remaining uptime.
    """
    calls = []

    async def work():
        calls.append(1)
        raise RuntimeError("boom")

    slept = asyncio.run(_drive(
        lambda: server._periodic("t", 60, work), ticks=3,
    ))
    assert len(calls) == 3, f"loop stopped after {len(calls)} failures, expected to keep going"
    assert slept[:3] == [60, 60, 60], f"cadence should be unaffected by failures, got {slept[:3]}"


def case_cancellation_returns_cleanly() -> None:
    """`_stop_event_pumps` cancels these at shutdown; that must not log or raise."""
    async def work():
        return None

    async def scenario():
        task = asyncio.create_task(server._periodic("t", 0.01, work))
        await asyncio.sleep(0)
        task.cancel()
        await task                     # must NOT raise CancelledError back out
        return task

    task = asyncio.run(scenario())
    assert task.done() and not task.cancelled(), (
        "_periodic should swallow its cancellation and return, so shutdown is quiet"
    )
    assert task.exception() is None, f"cancellation raised {task.exception()!r}"


def case_the_real_sweepers_ask_for_the_right_first_delay() -> None:
    """`_periodic` being correct is worth nothing if the CALLERS still ask for a
    full day. So this drives the four real loops and asserts the first thing
    each one actually waits for: grace for the two daily sweepers — that is the
    whole bug — and a plain interval for the hourly ones, which run often enough
    that a grace would only drag work into every restart.

    Each sweeper's `work` is stubbed to a no-op. That is deliberate and not
    laziness: this case is about the SCHEDULE, and letting the real sweeps run
    would drag a DB round-trip per loop into an assertion that is already
    decided by then (`slept[0]` is recorded before `work()` is ever awaited).
    An earlier draft did let them run, and bought nothing but a screenful of
    logged tracebacks that had to be explained every time someone read the
    output. The sweeps have their own tests — test_audit_retention.py covers
    `evict_audit_logs_once` directly.
    """
    grace = server._EVICT_BOOT_GRACE_S
    # (module, loop, first delay, sweep): the stub goes on the module whose
    # globals the loop reads at call time.
    expectations = [
        (server, "_raw_json_evictor_loop", grace, "_raw_json_sweep"),
        (server, "_audit_retention_evictor_loop", grace, "_audit_retention_sweep"),
        (img_api, "_img_cache_evictor_loop", img_api._IMG_CACHE_EVICT_INTERVAL_S, "_img_cache_sweep"),
        (diag_api, "_perflog_evictor_loop", diag_api._PERFLOG_EVICT_INTERVAL_S, "_perflog_sweep"),
    ]

    async def _noop() -> None:
        return None

    for mod, name, want_first, sweep_attr in expectations:
        original = getattr(mod, sweep_attr)
        setattr(mod, sweep_attr, _noop)
        try:
            slept = asyncio.run(_drive(getattr(mod, name), ticks=1))
        finally:
            setattr(mod, sweep_attr, original)
        assert slept[0] == want_first, (
            f"{name} waits {slept[0]}s before its first sweep, expected "
            f"{want_first}s. A daily sweeper that opens with its full interval "
            f"never runs at all on a relay that restarts more often than that."
        )
    assert grace < server._AUDIT_EVICT_INTERVAL_S, (
        "the boot grace must be shorter than the interval it front-runs, or it "
        "is not a grace"
    )


_harness.run(
    case_first_pass_waits_a_full_interval_by_default,
    case_first_after_s_moves_only_the_first_pass,
    case_a_failing_cycle_does_not_kill_the_sweeper,
    case_cancellation_returns_cleanly,
    case_the_real_sweepers_ask_for_the_right_first_delay,
)
