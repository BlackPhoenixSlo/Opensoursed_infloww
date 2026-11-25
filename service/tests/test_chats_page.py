#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds a temp DB; this file never touches it)

import chats_page  # noqa: E402
from of_client import OFAPIError  # noqa: E402


class _Resp:
    def __init__(self, status: int, text: str):
        self.status_code, self.text = status, text


def _429(text: str = "Too many requests. Please allow 1 seconds") -> OFAPIError:
    return OFAPIError("429", response=_Resp(429, text))


class _Client:
    def __init__(self, fail: dict[int, OFAPIError]):
        self.fail, self.offsets = fail, []
        self.rows = [{"withUser": {"id": 1000 + i}} for i in range(40)]

    def list_chats(self, *, limit, offset, **_kw):
        n = len(self.offsets)
        self.offsets.append(offset)
        if n in self.fail:
            raise self.fail[n]
        page = self.rows[offset:offset + min(limit, 10)]
        return {"list": page, "hasMore": offset + len(page) < len(self.rows)}


_slept: list[float] = []


def _no_sleep():
    _slept.clear()
    chats_page._sleep = _slept.append  # type: ignore[assignment]


def _page(fail, offset=0):
    _no_sleep()
    c = _Client(fail)
    return c, chats_page.assemble_chats_page(c, limit=25, offset=offset, order="recent")


def case_mid_page_429_retried_once():
    c, p = _page({1: _429()})
    assert c.offsets == [0, 10, 10, 20], c.offsets
    assert _slept == [1.0], _slept
    assert len(p.rows) == 25 and not p.partial and p.throttled is None, p


def case_second_429_partial():
    c, p = _page({1: _429(), 2: _429()})
    assert c.offsets == [0, 10, 10], c.offsets
    assert p.partial and p.throttled is not None and len(p.rows) == 10, p


def case_one_retry_per_page():
    c, p = _page({1: _429(), 3: _429()})
    assert c.offsets == [0, 10, 10, 20], c.offsets
    assert _slept == [1.0], _slept
    assert p.partial and len(p.rows) == 20, p


def case_long_wait_not_retried():
    c, p = _page({1: _429("Please allow 5 seconds")})
    assert c.offsets == [0, 10] and _slept == [], (c.offsets, _slept)
    assert p.partial and len(p.rows) == 10, p


def case_first_read_429_raises():
    try:
        _page({0: _429()})
    except OFAPIError:
        assert _slept == [], _slept
    else:
        raise AssertionError("a 429 before any row must raise")


_real_sleep = chats_page._sleep
try:
    _harness.run()
finally:
    chats_page._sleep = _real_sleep
