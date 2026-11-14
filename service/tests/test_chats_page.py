#!/usr/bin/env python3
"""
chats_page.assemble_chats_page — a 429 mid-page. No DB, no OF: a fake client.

  case_mid_page_429_retried_once:  OF's 429 after rows, "allow 1 seconds": one wait (OF's asked
                                   wait) and the SAME offset re-read; the page completes, not partial.
  case_second_429_partial:         the retry 429s too: partial page, the 429 kept, no third read.
  case_one_retry_per_page:         a later 429 in the same page is not retried again.
  case_long_wait_not_retried:      OF asks more than IN_PAGE_RETRY_MAX_S: partial at once, no sleep.
  case_first_read_429_raises:      a 429 before any row raises as before (never retried here).

Run: ./venv/bin/python service/tests/test_chats_page.py   (exit 0 = pass)
"""
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
    """40 chats, 10 per read; `fail` maps a call index (0-based) to the error it raises."""
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
    c, p = _page({1: _429()})  # the second read 429s
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
