#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds a temp DB)

_harness.bootstrap()

from fastapi import HTTPException  # noqa: E402

import chats_page  # noqa: E402
import relay_cache  # noqa: E402
import server  # noqa: E402
from of_client import OFAPIError  # noqa: E402


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def case_hold_clamped():
    h = chats_page.ThrottleHold(_Clock())
    assert h.hold("a", RuntimeError(), 0.2) == chats_page.HOLD_MIN_S
    assert h.hold("b", RuntimeError(), 3.0) == 3.0
    assert h.hold("c", RuntimeError(), 10.0) == chats_page.HOLD_MAX_S


def case_hold_expires():
    clk = _Clock()
    h = chats_page.ThrottleHold(clk)
    e = RuntimeError("429")
    h.hold("k", e, 1.0)
    assert h.check("k") is e and h.check("other") is None
    clk.t += 1.0
    assert h.check("k") is None and "k" not in h._held


def case_hold_prunes_on_write():
    clk = _Clock()
    h = chats_page.ThrottleHold(clk)
    h.hold("old", RuntimeError(), 1.0)
    clk.t += 2.0
    h.hold("new", RuntimeError(), 1.0)
    assert list(h._held) == ["new"], h._held


class _Resp:
    def __init__(self, status: int, text: str):
        self.status_code, self.text = status, text


_AID = "acct-429-hold"
_KW = dict(limit=25, order="recent", filter=None, list_id=None, query=None, search=None)


def _patched(status: int, text: str):
    reads: list[int] = []
    clk = _Clock()

    def _assemble(_client, *, offset, **_kw):
        reads.append(offset)
        raise OFAPIError(str(status), response=_Resp(status, text))

    orig = (server._resolve_account_id, server._get_client, server._assemble_chats_page,
            server._CHATS_429_HOLD)
    server._resolve_account_id = lambda _req: _AID
    server._get_client = lambda *_a: None
    server._assemble_chats_page = _assemble
    server._CHATS_429_HOLD = chats_page.ThrottleHold(clk)
    relay_cache.invalidate("list_chats", _AID)

    def undo():
        (server._resolve_account_id, server._get_client, server._assemble_chats_page,
         server._CHATS_429_HOLD) = orig
        relay_cache.invalidate("list_chats", _AID)
    return reads, clk, undo


async def _ask(offset: int = 0) -> HTTPException:
    try:
        await server.list_chats(refresh=False, offset=offset, **_KW)
    except HTTPException as e:
        return e
    raise AssertionError("expected the page to fail")


async def case_route_holds_429():
    reads, _clk, undo = _patched(429, "Too many requests. Please allow 2 seconds")
    try:
        first = await _ask()
        assert first.status_code == 502 and first.detail["upstream_status"] == 429, first.detail
        again = await _ask()
        assert reads == [0], f"held re-ask must not read OF: {reads}"
        assert again.status_code == 502 and again.detail == first.detail, again.detail
        await _ask(offset=25)
        assert reads == [0, 25], f"another page is its own key: {reads}"
    finally:
        undo()


async def case_route_reads_after_hold():
    reads, clk, undo = _patched(429, "Please allow 1 seconds")
    try:
        await _ask()
        clk.t += chats_page.HOLD_MIN_S
        await _ask()
        assert reads == [0, 0], reads
    finally:
        undo()


async def case_route_non_429_not_held():
    reads, _clk, undo = _patched(500, "boom")
    try:
        await _ask()
        await _ask()
        assert reads == [0, 0], reads
    finally:
        undo()


async def case_hold_serves_cache_and_gates_swr():
    import asyncio
    import time as _t
    reads, _clk, undo = _patched(429, "Please allow 3 seconds")
    ok = {"on": True}
    real = server._assemble_chats_page

    def _assemble(client, **kw):
        if ok["on"]:
            reads.append(("ok", kw["offset"]))
            return {"list": [], "hasMore": False}
        return real(client, **kw)
    server._assemble_chats_page = _assemble
    try:
        await server.list_chats(refresh=False, offset=0, **_KW)
        ok["on"] = False
        got = await server.list_chats(refresh=True, offset=0, **_KW)
        assert got["list"] == [] and reads[-1] == 0, (got, reads)
        assert server._CHATS_429_HOLD.check(("list_chats", _AID, 25, 0, "recent", None, None, None)), "held"
        n = len(reads)
        got = await server.list_chats(refresh=False, offset=0, **_KW)
        assert got["list"] == [], got
        key = next(k for k in relay_cache._cache if k[0] == "list_chats" and k[1] == _AID)
        relay_cache._cache[key] = (relay_cache._cache[key][0], _t.monotonic() - 1)
        await server.list_chats(refresh=False, offset=0, **_KW)
        await asyncio.sleep(0.2)
        assert len(reads) == n, f"SWR refresh read OF during the hold: {reads[n:]}"
    finally:
        undo()


async def case_held_copy_served_past_swr():
    reads, _clk, undo = _patched(429, "Please allow 1 seconds")
    real = server._assemble_chats_page
    server._assemble_chats_page = lambda client, **kw: {"list": [{"withUser": {"id": 7}}], "hasMore": False}
    try:
        await server.list_chats(refresh=False, offset=0, **_KW)
        key = next(k for k in relay_cache._cache if k[0] == "list_chats" and k[1] == _AID)
        relay_cache._cache[key] = (relay_cache._cache[key][0], -1e9)
        server._assemble_chats_page = real
        got = await server.list_chats(refresh=False, offset=0, **_KW)
        assert [r["withUser"]["id"] for r in got["list"]] == [7] and reads == [0], (got, reads)
        e = await _ask(offset=25)
        assert e.detail["upstream_status"] == 429, e.detail
    finally:
        undo()


async def case_cancelled_waiter_keeps_the_hold():
    import asyncio
    import threading
    import time as _t
    import relay_coalesce
    reads, _clk, undo = _patched(429, "Please allow 3 seconds")
    real, release = server._assemble_chats_page, threading.Event()

    def _slow(client, **kw):
        release.wait(5)
        return real(client, **kw)
    server._assemble_chats_page = _slow
    try:
        waiter = asyncio.create_task(server.list_chats(refresh=False, offset=0, **_KW))
        end = _t.monotonic() + 5
        while not relay_coalesce._inflight and _t.monotonic() < end:
            await asyncio.sleep(0.01)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        release.set()
        while relay_coalesce._inflight and _t.monotonic() < end:
            await asyncio.sleep(0.01)
        assert reads == [0], reads
        again = await _ask()
        assert reads == [0], f"the cancelled waiter's 429 left no hold: re-ask read OF {reads}"
        assert again.detail["upstream_status"] == 429, again.detail
    finally:
        release.set()
        undo()


async def case_expired_history_fallback_does_not_save_thread():
    import asyncio
    import types
    from unittest.mock import AsyncMock, patch

    from automations import scrape_chats

    payload = {"list": [{"id": 8}]}
    key = (42, 9, 10)

    async def cached_page():
        return payload

    def get_messages(*_args, **_kwargs):
        raise OFAPIError("429", response=_Resp(429, "Too many requests"))

    await relay_cache.get_or_fetch("get_messages_tail", _AID, key, ttl_seconds=300, fetcher=cached_page)
    cache_key = next(k for k in relay_cache._cache if k[:2] == ("get_messages_tail", _AID))
    relay_cache._cache[cache_key] = (payload, -1e9)
    client = types.SimpleNamespace(user_id=4242, get_messages=get_messages)
    with (
        patch.object(server, "_current_aid", return_value=_AID),
        patch.object(server, "_get_client", return_value=client),
        patch.object(scrape_chats, "save_thread_page", new_callable=AsyncMock) as save,
    ):
        got = await server.get_messages(42, limit=10, order="desc", before_id=9, refresh=False)
        await asyncio.sleep(0)
    assert got == payload
    save.assert_not_called()


_harness.run()
