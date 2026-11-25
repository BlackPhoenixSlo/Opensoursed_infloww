#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401  — MUST be first: binds a throwaway temp DB

import ast
import asyncio
import re
import time
from pathlib import Path

import transaction_ingest as tx  # noqa: E402
from cadence import boot_grace  # noqa: E402

_SERVICE = Path(__file__).resolve().parents[1]
_INGEST_SRC = _SERVICE / "transaction_ingest.py"
_POLL_SRC = _SERVICE / "purchase_poll.py"
_COMPOSE = _SERVICE.parent / "docker-compose.yml"

_GUARDED_LOOPS = {"start_fast_poll": _POLL_SRC, "start_supervisor": _INGEST_SRC}


def _fn(name: str) -> ast.AsyncFunctionDef:
    src = _GUARDED_LOOPS[name]
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is no longer a module-level async def in "
                         f"{src.name} — this guard needs updating")


def _index_of_await_boot_grace(fn: ast.AsyncFunctionDef) -> int:
    for i, stmt in enumerate(fn.body):
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
            continue
        call = stmt.value.value
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "boot_grace":
            return i
    return -1


def _index_of_while(fn: ast.AsyncFunctionDef) -> int:
    for i, stmt in enumerate(fn.body):
        if isinstance(stmt, ast.While):
            return i
    raise AssertionError(f"{fn.name} no longer has a body-level `while` loop")


def case_both_ingest_loops_hold_before_their_first_cycle():
    for name in _GUARDED_LOOPS:
        fn = _fn(name)
        grace_at = _index_of_await_boot_grace(fn)
        assert grace_at >= 0, (
            f"{name} does not await boot_grace() at its body level — its first "
            f"cycle fires at t=0, into the pumps/executor/scrape-seed startup "
            f"herd. That is the 2026-08-21 shape.")
        while_at = _index_of_while(fn)
        assert grace_at < while_at, (
            f"{name} awaits boot_grace() at stmt {grace_at} but its `while` "
            f"starts at {while_at} — the grace must precede the loop, not sit "
            f"inside or after it.")


def case_the_supervisor_grace_runs_after_the_stale_sweep():
    fn = _fn("start_supervisor")
    grace_at = _index_of_await_boot_grace(fn)
    sweep_at = -1
    for i, stmt in enumerate(fn.body):
        if isinstance(stmt, ast.Try) and "_clear_stale_inflight" in ast.dump(stmt):
            sweep_at = i
            break
    assert sweep_at >= 0, "start_supervisor no longer runs _clear_stale_inflight at boot"
    assert sweep_at < grace_at, (
        "the boot stale-inflight sweep must run BEFORE the grace — otherwise "
        "every account stays locked out of /run for the whole hold")


def case_zero_or_negative_delay_does_not_sleep():
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def spy(d, *a, **kw):
        slept.append(d)
        return await real_sleep(0)

    asyncio.sleep = spy
    try:
        asyncio.run(boot_grace(0))
        asyncio.run(boot_grace(-5))
        asyncio.run(boot_grace(0.0, name="named-still-silent"))
    finally:
        asyncio.sleep = real_sleep
    assert slept == [], (
        f"a non-positive grace must yield immediately so it can be disabled by "
        f"config without branching; it slept {slept}")


def case_a_positive_delay_holds_for_exactly_that_long():
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def spy(d, *a, **kw):
        slept.append(d)
        return await real_sleep(0)

    asyncio.sleep = spy
    try:
        asyncio.run(boot_grace(90.0, name="unit"))
    finally:
        asyncio.sleep = real_sleep
    assert slept == [90.0], f"expected a single 90s hold, got {slept}"


def case_cancellation_is_not_delayed_by_the_grace():
    async def body():
        task = asyncio.create_task(boot_grace(3600, name="cancel-me"))
        await asyncio.sleep(0.05)
        started = time.monotonic()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return time.monotonic() - started
        raise AssertionError("boot_grace swallowed CancelledError — a container "
                             "stop would hold for the full grace and hit SIGKILL")

    elapsed = asyncio.run(body())
    assert elapsed < 0.5, (
        f"cancellation took {elapsed:.2f}s — it must be immediate, not held "
        f"for the remainder of the grace")


def case_env_float_degrades_on_garbage():
    import os
    key = "INGEST_BOOT_GRACE_S_TEST_ONLY"
    cases = [
        (None, 90.0, "unset falls back"),
        ("", 90.0, "empty falls back (an operator blanking the value in .env)"),
        ("   ", 90.0, "whitespace falls back"),
        ("not-a-number", 90.0, "garbage falls back instead of raising at import"),
        ("inf", 90.0, "non-finite falls back (an infinite grace never starts the loop)"),
        ("nan", 90.0, "nan falls back"),
        ("0", 0.0, "an explicit zero is honoured — that is the disable switch"),
        ("45.5", 45.5, "a real value is read"),
    ]
    for raw, want, why in cases:
        os.environ.pop(key, None)
        if raw is not None:
            os.environ[key] = raw
        got = tx.env_knob.env_float(key, 90.0)
        assert got == want, f"{why}: env_float({raw!r}) -> {got}, want {want}"
    os.environ.pop(key, None)


def case_defaults_are_sane_and_fit_inside_the_healthcheck_start_period():
    assert tx._FAST_BOOT_GRACE_S > 0, "the fast poll ships with no grace at all"
    assert tx._BOOT_GRACE_S > 0, "the supervisor ships with no grace at all"
    assert tx._FAST_BOOT_GRACE_S <= tx._BOOT_GRACE_S, (
        f"the 30s freshness poll ({tx._FAST_BOOT_GRACE_S}s) is held LONGER than "
        f"the 15-min supervisor ({tx._BOOT_GRACE_S}s) — that inverts their jobs")

    text = _COMPOSE.read_text(encoding="utf-8")
    block = re.search(r"test:\s*\[\"CMD\",\s*\"curl\".*?/livez.*?\n(.*?)\n    labels:",
                      text, re.S)
    assert block, "could not find the relay healthcheck block in docker-compose.yml"
    m = re.search(r"start_period:\s*(\d+)s", block.group(1))
    assert m, "the relay healthcheck has no start_period"
    start_period = int(m.group(1))
    assert tx._BOOT_GRACE_S < start_period, (
        f"the supervisor's boot grace ({tx._BOOT_GRACE_S}s) is >= the relay's "
        f"healthcheck start_period ({start_period}s) — the container leaves its "
        f"grace window before ingest has run a single cycle, so the first walk "
        f"lands under a live healthcheck. Raise start_period or lower the grace.")


def case_the_cadence_floor_is_still_there():
    assert tx._MIN_CYCLE_GAP_S >= 1.0, "the anti-spin floor is gone or zeroed"


_harness.run()
