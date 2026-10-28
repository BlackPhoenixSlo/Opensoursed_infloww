#!/usr/bin/env python3
"""relay_cache stays bounded, and keeping it bounded stays cheap.

Some keys carry free-form request values (date ranges, markers, search text:
server._account_ttl), so without bounds the dict grew for the life of the
process and a caller could grow it on purpose. Pinned:

  • the periodic sweep (at most every `_SWEEP_INTERVAL_S`, run by a miss)
    drops expired entries and their idle locks, and leaves live entries alone;
    between sweeps a miss does no scan at all;
  • an entry still inside its namespace's stale-while-revalidate window is
    not dead (list_chats serves it stale);
  • crossing the cap sweeps, then evicts the soonest-to-expire down to the
    low-water mark, so the cache never exceeds `_MAX_ENTRIES` and the next 100
    new-key misses run at most ONE more full sweep;
  • a held lock is never dropped;
  • a failed fetch's error (kept for callers queued behind it) goes with its lock.

Run: ./venv/bin/python service/tests/test_relay_cache_bounds.py   (exit 0 = green)
"""
import _harness  # MUST be first (house style; this module needs no DB)

import relay_cache as rc  # noqa: E402


def _reset(cap: int = 5000) -> None:
    rc._cache.clear()
    rc._locks.clear()
    rc._failed.clear()
    rc._ns_grace.clear()
    rc._MAX_ENTRIES = cap
    rc._next_sweep_at = rc.time.monotonic() + 3600   # no interval sweep unless a case asks
    rc._sweeps = 0


async def _put(ns: str, aid: str, extras: tuple, ttl: float, swr: float = 0.0) -> None:
    await rc.get_or_fetch(ns, aid, extras, ttl, lambda: {"k": extras},
                          stale_while_revalidate=swr)


def _expire(ns: str, aid: str) -> None:
    for k, (v, _exp) in list(rc._cache.items()):
        if k[0] == ns and k[1] == aid:
            rc._cache[k] = (v, 0.0)


def _sweep_due() -> None:
    rc._next_sweep_at = 0.0


async def case_the_interval_sweep_drops_expired_entries_and_their_locks_only():
    _reset()
    for day in range(20):
        await _put("payouts", "A", (f"2026-10-{day:02d}",), 60)
    await _put("payouts", "B", ("2026-10-01",), 60)
    await _put("me_stats", "A", ("x",), 60)
    _expire("payouts", "A")
    await _put("payouts", "A", ("between-sweeps",), 60)
    assert rc._sweeps == 0 and len(rc._cache) == 23, "a miss between sweeps scanned"
    _sweep_due()
    await _put("payouts", "A", ("fresh",), 60)
    assert rc._sweeps == 1
    a_keys = sorted(k[2] for k in rc._cache if k[:2] == ("payouts", "A"))
    assert a_keys == [("between-sweeps",), ("fresh",)], a_keys
    assert sorted(k[2] for k in rc._locks if k[:2] == ("payouts", "A")) == a_keys
    assert ("payouts", "B", ("2026-10-01",)) in rc._cache, "a live entry was swept"
    assert ("me_stats", "A", ("x",)) in rc._cache, "a live entry was swept"
    assert rc._next_sweep_at > rc.time.monotonic() + rc._SWEEP_INTERVAL_S - 5


async def case_an_entry_inside_its_stale_window_is_not_dead():
    _reset()
    await _put("list_chats", "A", ("old",), 30, swr=600)
    k = ("list_chats", "A", ("old",))
    v, _ = rc._cache[k]
    rc._cache[k] = (v, rc.time.monotonic() - 10)     # expired 10 s ago: still servable
    _sweep_due()
    await _put("list_chats", "A", ("new",), 30, swr=600)
    assert k in rc._cache, "a stale-servable entry was swept"
    rc._cache[k] = (v, rc.time.monotonic() - 700)    # past the 600 s window: dead
    _sweep_due()
    await _put("list_chats", "A", ("newer",), 30, swr=600)
    assert k not in rc._cache


async def case_crossing_the_cap_evicts_to_low_water_and_the_next_100_misses_sweep_at_most_once():
    cap, low = 1000, 800
    _reset(cap=cap)
    for i in range(50):                       # dead entries, spread over accounts
        await _put("payouts", f"acct{i}", ("d",), 60)
        _expire("payouts", f"acct{i}")
    for i in range(951):                      # live, ttl rising with i: 1001 > cap
        await _put("me_stats", f"live{i}", ("x",), 100 + i)
        assert len(rc._cache) <= cap, len(rc._cache)
    assert rc._sweeps == 1, rc._sweeps
    assert not any(k[0] == "payouts" for k in rc._cache), "dead entries survived the sweep"
    kept = sorted(int(k[1][4:]) for k in rc._cache)
    assert kept == list(range(951 - low, 951)), "not evicted to low water, soonest-to-expire first"
    assert len(rc._locks) == low, len(rc._locks)
    before = rc._sweeps
    for i in range(951, 1051):                # the next 100 new-key misses
        await _put("me_stats", f"live{i}", ("x",), 100 + i)
    assert rc._sweeps - before <= 1, f"{rc._sweeps - before} full sweeps for 100 misses"
    assert len(rc._cache) == low + 100, len(rc._cache)


async def case_a_held_lock_is_never_dropped():
    _reset(cap=5)
    await _put("payouts", "A", ("held",), 60)
    held = rc._locks[("payouts", "A", ("held",))]
    _expire("payouts", "A")
    async with held:
        for i in range(10):
            _sweep_due()
            await _put("payouts", "A", (f"n{i}",), 60)
        assert rc._locks.get(("payouts", "A", ("held",))) is held, "a held lock was dropped"


async def case_a_failed_fetch_is_swept_with_its_lock():
    """Search text keys fail too: the error kept for queued callers must not
    outlive the key's lock, or a dead proxy grows `_failed` for good."""
    _reset()

    def boom():
        raise RuntimeError("dead proxy")

    for q in ("a", "an", "ann"):
        try:
            await rc.get_or_fetch("list_chats", "A", (q,), 30, boom)
        except RuntimeError:
            pass
    assert len(rc._failed) == 3, rc._failed
    _sweep_due()
    await _put("me_stats", "A", ("x",), 60)
    assert not rc._failed, f"failures outlived their locks: {list(rc._failed)}"


_harness.run()
