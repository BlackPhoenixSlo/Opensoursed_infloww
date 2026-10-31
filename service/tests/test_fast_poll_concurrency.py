#!/usr/bin/env python3
"""The 30 s purchase poll walks the fleet concurrently, bounded and staggered.

  • Every wanted account is polled once per cycle, at most
    _FAST_POLL_CONCURRENCY at a time, starts _FAST_POLL_STAGGER_S apart — 20
    accounts no longer take 20 x ~0.7 s, and never hit OF in the same instant.
  • One account's failure is still recorded and does not stop the others.
  • The feed read runs inside the serving relay's per-account OF lane
    (server._priority_lane_background), so ACCOUNT_LANE_TOTAL still binds it.

Run:  ./venv/bin/python service/tests/test_fast_poll_concurrency.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

import purchase_notifications as pn  # noqa: E402
import transaction_ingest as ti  # noqa: E402

ACCOUNTS = [f"77{i:02d}" for i in range(20)]
TICK_S = 0.1


async def _one_cycle(fake_tick, failures):
    """Run start_fast_poll for one cycle over ACCOUNTS with `fake_tick`."""
    async def _none(*_a, **_k):
        return None

    async def _off():
        return set()

    async def _wanted():
        return set(ACCOUNTS)

    async def _false(_aid):
        return False

    async def _fail(aid, e):
        failures.append((aid, str(e)))

    saved = {k: getattr(ti, k) for k in (
        "run_fast_tick", "boot_grace", "_is_paused", "_fast_poll_account_ids",
        "_record_failure", "_FAST_POLL_STAGGER_S")}
    saved_list, saved_off = ti.account_registry.list_accounts, ti.account_health.deactivated_ids
    ti.run_fast_tick, ti.boot_grace, ti._is_paused = fake_tick, _none, _false
    ti._fast_poll_account_ids, ti._record_failure = _wanted, _fail
    ti._FAST_POLL_STAGGER_S = 0.01
    ti.account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in ACCOUNTS]
    ti.account_health.deactivated_ids = _off
    try:
        task = asyncio.create_task(ti.start_fast_poll())
        await asyncio.sleep(2.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        for k, v in saved.items():
            setattr(ti, k, v)
        ti.account_registry.list_accounts, ti.account_health.deactivated_ids = saved_list, saved_off


async def case_bounded_concurrent_and_staggered():
    started: list[tuple[str, float]] = []
    in_flight = peak = 0

    async def _tick(aid):
        nonlocal in_flight, peak
        started.append((aid, time.monotonic()))
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(TICK_S)
        in_flight -= 1
        return {}

    failures: list = []
    await _one_cycle(_tick, failures)
    assert sorted(a for a, _ in started) == sorted(ACCOUNTS), "every account once per cycle"
    assert peak == ti._FAST_POLL_CONCURRENCY, f"peak in flight {peak}"
    first_wave = sorted(t for _, t in started)[:ti._FAST_POLL_CONCURRENCY]
    # Span, not pairwise gaps: start i sleeps i*stagger from one base, and a
    # loaded loop only ever wakes LATE, so one late start next to an on-time
    # one shrinks a single gap (6 ms seen at load ~40) while the wave's span
    # cannot fall below (n-1)*stagger. All-at-once would read ~0 here.
    spread = first_wave[-1] - first_wave[0]
    want = 0.8 * (ti._FAST_POLL_CONCURRENCY - 1) * 0.01
    assert spread >= want, f"starts not staggered: first wave spans {spread:.4f}s < {want}s"
    span = max(t for _, t in started) - min(t for _, t in started)
    assert span < len(ACCOUNTS) * TICK_S / 2, f"walk still ~sequential: {span:.2f}s"
    assert not failures


async def case_one_failure_recorded_others_still_polled():
    polled: list[str] = []

    async def _tick(aid):
        polled.append(aid)
        if aid == ACCOUNTS[3]:
            raise RuntimeError("feed down")
        return {}

    failures: list = []
    await _one_cycle(_tick, failures)
    assert sorted(polled) == sorted(ACCOUNTS), polled
    assert failures == [(ACCOUNTS[3], "feed down")], failures


async def case_feed_read_holds_the_account_lane():
    held: list[str] = []
    inside = False
    reads: list[bool] = []

    @contextlib.contextmanager
    def _lane(aid):
        nonlocal inside
        held.append(aid)
        inside = True
        try:
            yield
        finally:
            inside = False

    class _Client:
        def get(self, _path):
            reads.append(inside)  # poll_purchases swallows raises: record, assert below
            return {"list": []}

    fake = types.SimpleNamespace(_priority_lane_background=_lane)
    prev = sys.modules.get("server")
    sys.modules["server"] = fake
    try:
        await pn.poll_purchases("9001", _Client())
    finally:
        if prev is None:
            sys.modules.pop("server", None)
        else:
            sys.modules["server"] = prev
    assert held == ["9001"], held
    assert reads == [True], "the OF read must run inside the lane"


_harness.run()
