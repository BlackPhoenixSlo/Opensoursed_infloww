#!/usr/bin/env python3
import _harness

import asyncio  # noqa: E402

import server  # noqa: E402
import db_retention  # noqa: E402
import diag_api  # noqa: E402
import img_api  # noqa: E402


# BaseException: _periodic swallows Exception and handles CancelledError, so only this ends the fake loop
class _StopLoop(BaseException):
    pass


async def _drive(coro_factory, *, ticks: int):
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(d, *a, **kw):
        slept.append(d)
        if len(slept) > ticks:
            raise _StopLoop
        await real_sleep(0)

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
    calls = []

    async def work():
        calls.append(1)

    slept = asyncio.run(_drive(
        lambda: server._periodic("t", 3600, work), ticks=3,
    ))
    assert slept[:3] == [3600, 3600, 3600], f"expected a steady interval, got {slept[:3]}"
    assert len(calls) == 3, f"work ran {len(calls)} times, expected 3"


def case_first_after_s_moves_only_the_first_pass() -> None:
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
    async def work():
        return None

    async def scenario():
        task = asyncio.create_task(server._periodic("t", 0.01, work))
        await asyncio.sleep(0)
        task.cancel()
        await task
        return task

    task = asyncio.run(scenario())
    assert task.done() and not task.cancelled(), (
        "_periodic should swallow its cancellation and return, so shutdown is quiet"
    )
    assert task.exception() is None, f"cancellation raised {task.exception()!r}"


def case_the_real_sweepers_ask_for_the_right_first_delay() -> None:
    grace = db_retention._EVICT_BOOT_GRACE_S
    expectations = [
        (db_retention, "_raw_json_evictor_loop", grace, "_raw_json_sweep"),
        (db_retention, "_audit_retention_evictor_loop", grace, "_audit_retention_sweep"),
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
    assert grace < db_retention._AUDIT_EVICT_INTERVAL_S, (
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
