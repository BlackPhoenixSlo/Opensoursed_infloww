#!/usr/bin/env python3
"""Stand-alone tests for `service/relay_coalesce.py` (Stage B-2).

The project doesn't ship pytest. Run via:

    ./venv/bin/python service/tests/test_relay_coalesce.py

Exit 0 = all pass. Any failure raises and exits non-zero. Five cases
mapped to plan/call_reduction_2026_05_24/02_relay_request_coalescer.md
section "Verification":

  1. 5 concurrent identical calls → fetcher invoked once
  2. 5 concurrent calls with different keys → fetcher invoked 5 times
  3. Fetcher exception propagates to all waiters
  4. Cancelling one waiter doesn't crash the others (or stop the work)
  5. Keys with the same set of IDs in different orders coalesce
     (handled by the caller sorting; we assert that the SAME key tuple
     reused identically coalesces — sorting is a caller responsibility,
     proven by reusing `tuple(sorted(ids))` from two angles)

Plus a quick safety case:
  6. Deepcopy isolation — one waiter mutating its returned dict does
     not affect a sibling waiter's copy.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
sys.path.insert(0, str(SERVICE_ROOT))

import relay_coalesce  # noqa: E402


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


async def case_1_dedup_identical() -> None:
    relay_coalesce.reset_for_tests()
    calls = 0
    gate = asyncio.Event()

    async def fetcher():
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"ok": True, "n": calls}

    key = ("list_chats", "acct1", 10, 0, "recent", None, None, None)

    waiters = [asyncio.create_task(relay_coalesce.coalesce(key, fetcher)) for _ in range(5)]
    # Let waiters all enter the coalescer before we release the fetcher.
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*waiters)

    _check(calls == 1, f"case 1: fetcher called {calls}x, expected 1")
    _check(all(r == {"ok": True, "n": 1} for r in results), "case 1: bad results")
    # Each waiter must hold its OWN copy.
    _check(results[0] is not results[1], "case 1: results share identity (deepcopy failed)")
    snap = relay_coalesce.stats()
    _check(snap["coalesced_hits"].get("list_chats") == 4, f"case 1: hits {snap}")
    _check(snap["first_calls"].get("list_chats") == 1, f"case 1: first {snap}")
    print("  case 1 OK — 5 identical → 1 upstream call, 4 hits")


async def case_2_distinct_keys() -> None:
    relay_coalesce.reset_for_tests()
    calls = 0

    # Per-key fetcher so each one returns a distinguishable value AND
    # the global `calls` counter still proves the fetcher fired 5 times.
    def make_fetcher(tag: int):
        async def fetcher():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return tag
        return fetcher

    keys = [("get_messages", "acct1", i, None, 10, "desc") for i in range(5)]
    results = await asyncio.gather(*[
        relay_coalesce.coalesce(k, make_fetcher(i)) for i, k in enumerate(keys)
    ])
    _check(calls == 5, f"case 2: fetcher called {calls}x, expected 5")
    _check(sorted(results) == [0, 1, 2, 3, 4], f"case 2: results {results}")
    snap = relay_coalesce.stats()
    _check(snap["coalesced_hits"].get("get_messages", 0) == 0, f"case 2: hits {snap}")
    _check(snap["first_calls"].get("get_messages") == 5, f"case 2: first {snap}")
    print("  case 2 OK — 5 distinct keys → 5 upstream calls, 0 hits")


async def case_3_exception_propagates() -> None:
    relay_coalesce.reset_for_tests()
    calls = 0
    gate = asyncio.Event()

    class BoomError(RuntimeError):
        pass

    async def fetcher():
        nonlocal calls
        calls += 1
        await gate.wait()
        raise BoomError("upstream blew up")

    key = ("init", "acct1")
    waiters = [asyncio.create_task(relay_coalesce.coalesce(key, fetcher)) for _ in range(4)]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*waiters, return_exceptions=True)

    _check(calls == 1, f"case 3: fetcher called {calls}x, expected 1")
    for r in results:
        _check(isinstance(r, BoomError), f"case 3: expected BoomError, got {r!r}")
    print("  case 3 OK — exception propagated to all 4 waiters from 1 fetcher")


async def case_4_cancel_one_others_proceed() -> None:
    relay_coalesce.reset_for_tests()
    calls = 0
    gate = asyncio.Event()

    async def fetcher():
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"value": 42}

    key = ("my_settings", "acct1")
    # First waiter is the one that creates the fetcher task. We'll cancel it.
    leader = asyncio.create_task(relay_coalesce.coalesce(key, fetcher))
    await asyncio.sleep(0.01)
    followers = [asyncio.create_task(relay_coalesce.coalesce(key, fetcher)) for _ in range(3)]
    await asyncio.sleep(0.05)

    leader.cancel()
    # Give the cancellation a moment to land.
    await asyncio.sleep(0.01)
    gate.set()

    leader_result = await asyncio.gather(leader, return_exceptions=True)
    follower_results = await asyncio.gather(*followers)

    _check(calls == 1, f"case 4: fetcher called {calls}x, expected 1")
    _check(isinstance(leader_result[0], asyncio.CancelledError),
           f"case 4: leader expected CancelledError, got {leader_result!r}")
    _check(all(r == {"value": 42} for r in follower_results),
           f"case 4: followers {follower_results}")
    print("  case 4 OK — leader cancellation didn't kill followers (still got result)")


async def case_5_sorted_ids_collide() -> None:
    relay_coalesce.reset_for_tests()
    calls = 0
    gate = asyncio.Event()

    async def fetcher():
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"117183": {"id": 117183}, "9": {"id": 9}, "42": {"id": 42}}

    # Caller is responsible for sorting — server.py does tuple(sorted(ids)).
    # Two callers with [9, 42, 117183] and [42, 117183, 9] both sort to
    # the same tuple, so they share an in-flight fetch.
    ids_a = [9, 42, 117183]
    ids_b = [117183, 9, 42]
    key_a = ("list_users", "acct1", "m", tuple(sorted(ids_a)))
    key_b = ("list_users", "acct1", "m", tuple(sorted(ids_b)))
    _check(key_a == key_b, "case 5: sorted-ids keys should be identical")

    waiters = [
        asyncio.create_task(relay_coalesce.coalesce(key_a, fetcher)),
        asyncio.create_task(relay_coalesce.coalesce(key_b, fetcher)),
    ]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*waiters)
    _check(calls == 1, f"case 5: fetcher called {calls}x, expected 1")
    _check(results[0] == results[1], "case 5: results diverge")
    print("  case 5 OK — same set of ids in different orders coalesce")


async def case_6_deepcopy_isolation() -> None:
    relay_coalesce.reset_for_tests()
    gate = asyncio.Event()

    async def fetcher():
        await gate.wait()
        return {"list": [1, 2, 3], "nested": {"k": "v"}}

    key = ("labels", "acct1")
    waiters = [asyncio.create_task(relay_coalesce.coalesce(key, fetcher)) for _ in range(3)]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*waiters)

    # Mutate the first waiter's copy. The other waiters must be unaffected.
    results[0]["list"].append(999)
    results[0]["nested"]["k"] = "MUTATED"

    _check(results[1]["list"] == [1, 2, 3],
           f"case 6: deepcopy leak in list — {results[1]}")
    _check(results[2]["nested"]["k"] == "v",
           f"case 6: deepcopy leak in nested dict — {results[2]}")
    print("  case 6 OK — waiters hold independent deep copies")


async def main() -> None:
    print("test_relay_coalesce.py — Stage B-2 coalescer")
    await case_1_dedup_identical()
    await case_2_distinct_keys()
    await case_3_exception_propagates()
    await case_4_cancel_one_others_proceed()
    await case_5_sorted_ids_collide()
    await case_6_deepcopy_isolation()
    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
