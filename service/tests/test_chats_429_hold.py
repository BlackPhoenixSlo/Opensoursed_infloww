#!/usr/bin/env python3
"""
OF's 429 on a chats page is held a few seconds per page key (chats_page.ThrottleHold), so the
UI's re-asks answer it from RAM instead of 429-ing OF again.

  case_hold_clamped:            OF's wait clamped to [HOLD_MIN_S, HOLD_MAX_S].
  case_hold_expires:            past its hold a key reads None and is dropped.
  case_hold_prunes_on_write:    expired keys leave the map on the next hold.
  case_route_holds_429:         GET /api/of/v2/chats: a 429 page, re-asked inside the hold,
                                answers the same 429 without reading OF; another page still reads.
  case_route_reads_after_hold:  once the hold ends the page reads OF again.
  case_route_non_429_not_held:  any other upstream error is never held.

Run: ./venv/bin/python service/tests/test_chats_429_hold.py   (exit 0 = pass)
"""
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
    """Route wired to a fake page reader that always raises OF's `status`; returns (reads, clock, undo)."""
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


_harness.run()
