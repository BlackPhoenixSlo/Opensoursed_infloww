#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "service"))

from service.relay_cache import (  # noqa: E402
    get_or_fetch,
    invalidate,
    invalidate_account,
    invalidate_money_feeds,
    stats,
)


async def main() -> None:
    calls = 0

    async def fetcher():
        nonlocal calls
        calls += 1
        return {"x": 1}

    v = await get_or_fetch("ns", "acc1", (), 60, fetcher)
    assert v == {"x": 1} and calls == 1, f"case1: {v} calls={calls}"

    calls = 0

    async def slow_fetcher():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    results = await asyncio.gather(*[
        get_or_fetch("ns2", "acc1", (), 60, slow_fetcher) for _ in range(5)
    ])
    assert calls == 1, f"case2: calls={calls}"
    assert all(r == 1 for r in results), f"case2 results: {results}"

    n = invalidate("ns", "acc1")
    assert n >= 1, f"case3: should have removed at least one entry, got {n}"

    def sync_fetcher():
        return "sync-result"

    v = await get_or_fetch("ns3", "acc1", (), 60, sync_fetcher)
    assert v == "sync-result", f"case4: {v}"

    calls = 0

    async def f5():
        nonlocal calls
        calls += 1
        return calls

    await get_or_fetch("ns5", "acc1", (), 60, f5)
    await get_or_fetch("ns5", "acc1", (), 60, f5, bypass=True)
    assert calls == 2, f"case5: calls={calls}"

    calls = 0

    async def boom():
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    for _ in range(2):
        try:
            await get_or_fetch("ns6", "acc1", (), 60, boom)
        except RuntimeError:
            pass
    assert calls == 2, f"case6: calls={calls}"

    await get_or_fetch("ns7", "accA", (), 60, lambda: "A")
    await get_or_fetch("ns7", "accB", (), 60, lambda: "B")
    invalidate("ns7", "accA")
    again = await get_or_fetch("ns7", "accB", (), 60, lambda: "FRESH")
    assert again == "B", f"case7: invalidate leaked across accounts, got {again}"

    await get_or_fetch("ns8", "acc1", ("a",), 60, lambda: 1)
    await get_or_fetch("ns8", "acc1", ("b",), 60, lambda: 2)
    n = invalidate("ns8", "acc1", match=lambda extras: extras == ("a",))
    assert n == 1, f"case8 match: expected 1 removed, got {n}"
    v = await get_or_fetch("ns8", "acc1", ("b",), 60, lambda: 999)
    assert v == 2, f"case8: ('b',) should still be cached, got {v}"

    s = stats()
    assert "namespaces" in s and "total_entries" in s, f"case9 shape: {s}"
    assert s["namespaces"].get("ns", {}).get("hits", 0) >= 0, f"case9 hits: {s}"

    await get_or_fetch("list_chats", "accDrop", (), 60, lambda: "chats")
    await get_or_fetch("my_settings", "accDrop", (), 60, lambda: "settings")
    await get_or_fetch("init", "accDrop", ("x",), 60, lambda: "init")
    await get_or_fetch("list_chats", "accKeep", (), 60, lambda: "keep")
    n = invalidate_account("accDrop")
    assert n == 3, f"case10: expected 3 entries dropped across namespaces, got {n}"
    assert await get_or_fetch("list_chats", "accDrop", (), 60, lambda: "FRESH") == "FRESH", "case10: list_chats not dropped"
    assert await get_or_fetch("my_settings", "accDrop", (), 60, lambda: "FRESH") == "FRESH", "case10: my_settings not dropped"
    assert await get_or_fetch("list_chats", "accKeep", (), 60, lambda: "LEAK") == "keep", "case10: leaked across accounts"
    assert invalidate_account("accNeverSeen") == 0, "case10: phantom account should remove 0"

    for ns in ("notifications", "notifications_count"):
        await get_or_fetch(ns, "accMoney", (), 60, lambda: "stale")
    await get_or_fetch("list_chats", "accMoney", (), 60, lambda: "chats")
    await get_or_fetch("notifications", "accOther", (), 60, lambda: "other")

    n = invalidate_money_feeds("accMoney")
    assert n == 2, f"case11: expected the money pair dropped, got {n}"
    for ns in ("notifications", "notifications_count"):
        got = await get_or_fetch(ns, "accMoney", (), 60, lambda: "FRESH")
        assert got == "FRESH", f"case11: {ns} survived the money bust ({got})"
    assert await get_or_fetch("list_chats", "accMoney", (), 60, lambda: "LEAK") == "chats", \
        "case11: busted a namespace that has nothing to do with money"
    assert await get_or_fetch("notifications", "accOther", (), 60, lambda: "LEAK") == "other", \
        "case11: leaked across accounts"

    calls = 0

    async def slow_boom():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        raise RuntimeError(f"boom {calls}")

    got = await asyncio.gather(*[
        get_or_fetch("ns12", "acc1", (), 60, slow_boom) for _ in range(5)
    ], return_exceptions=True)
    assert calls == 1, f"case12: queued callers went upstream again, calls={calls}"
    assert [str(e) for e in got] == ["boom 1"] * 5, f"case12: {got}"
    assert len({id(e) for e in got}) == 5 and all(type(e) is RuntimeError for e in got), \
        "case12: each waiter raises its own copy of the failure (no shared traceback)"
    from fastapi import HTTPException
    from service import relay_cache as _rc0
    h = _rc0._fresh(HTTPException(status_code=502, detail={"upstream_status": "proxy_unreachable"}))
    assert (type(h), h.status_code, h.detail) == (HTTPException, 502, {"upstream_status": "proxy_unreachable"}), h
    try:
        await get_or_fetch("ns12", "acc1", (), 60, slow_boom)
    except RuntimeError as e:
        assert str(e) == "boom 2", f"case12: a later caller got the old failure: {e}"
    assert calls == 2, f"case12: a later caller did not fetch, calls={calls}"
    assert await get_or_fetch("ns12", "acc1", (), 60, lambda: "ok") == "ok", "case12: no recovery"
    from service import relay_cache as _rc
    assert ("ns12", "acc1", ()) not in _rc._failed, "case12: a success left the failure behind"

    print("[relay_cache] all cases passed")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
