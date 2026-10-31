#!/usr/bin/env python3
"""
of_paging — table tests over the guarded OF pager. No DB, no OF: each row is a
fake `fetch(offset)` -> (rows, truncated, fetch offsets).

  case_page_all_checked_table: offset ignored + hasMore forever stops on a page
                               adding nothing; bare list pages until empty;
                               hasMore false stops; offset advances by len(rows);
                               non-dict items skipped; id-less rows kept.
  case_backstop:               200 pages of fresh ids -> truncated=True + warning.
  case_ids_from_pages:         ids as ints; id-less / non-int ids dropped; flag kept.
  case_same_objects:           audiences' old private names ARE of_paging's objects.
  case_patch_reaches_callers:  patching of_paging.page_all_checked reaches page_all,
                               ids_from_pages and audiences.resolve_recipients_blocking.

Run: ./venv/bin/python service/tests/test_of_paging.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import logging  # noqa: E402

import audiences  # noqa: E402
import of_paging  # noqa: E402


def _rec(pages):
    """fetch over a {offset: page} dict (missing offset -> empty bare list),
    recording every offset asked for."""
    seen: list[int] = []

    def fetch(off):
        seen.append(off)
        return pages.get(off, [])
    return fetch, seen


def _ids(rows):
    return [r.get("id") for r in rows]


def case_page_all_checked_table():
    same = {"list": [{"id": 1}, {"id": 2}], "hasMore": True}
    rows = [
        # (name, pages, want ids, want truncated, want offsets)
        ("offset ignored + hasMore forever -> stop on page adding nothing",
         {0: same, 2: same, 4: same}, [1, 2], False, [0, 2]),
        ("bare list pages until empty",
         {0: [{"id": 1}, {"id": 2}], 2: [{"id": 3}]}, [1, 2, 3], False, [0, 2, 3]),
        ("hasMore false stops",
         {0: {"list": [{"id": 1}], "hasMore": False}, 1: {"list": [{"id": 9}]}},
         [1], False, [0]),
        ("offset advances by len(rows), not limit",
         {0: {"list": [{"id": 1}, {"id": 2}, {"id": 3}], "hasMore": True},
          3: {"list": [{"id": 4}], "hasMore": False}}, [1, 2, 3, 4], False, [0, 3]),
        ("non-dict items skipped (still count toward offset)",
         {0: [{"id": 1}, "x", None, 7], 4: [{"id": 2}]}, [1, 2], False, [0, 4, 5]),
        ("id-less rows kept (never deduped)",
         {0: [{"name": "a"}, {"name": "a"}], 2: []}, [None, None], False, [0, 2]),
        ("empty first page", {}, [], False, [0]),
        ("None page", {0: None}, [], False, [0]),
    ]
    bad = []
    for name, pages, want_ids, want_trunc, want_offs in rows:
        fetch, seen = _rec(pages)
        got, trunc = of_paging.page_all_checked(fetch)
        if (_ids(got), trunc, seen) != (want_ids, want_trunc, want_offs):
            bad.append(f"{name}: {(_ids(got), trunc, seen)!r} != "
                       f"{(want_ids, want_trunc, want_offs)!r}")
    assert not bad, "\n".join(bad)


def case_backstop():
    calls = []

    def endless(off):
        calls.append(off)
        return {"list": [{"id": 10_000 + off}], "hasMore": True}

    logged: list[logging.LogRecord] = []

    class H(logging.Handler):
        def emit(self, record):
            logged.append(record)
    h = H(level=logging.WARNING)
    of_paging.log.addHandler(h)
    try:
        rows, trunc = of_paging.page_all_checked(endless)
    finally:
        of_paging.log.removeHandler(h)
    assert trunc is True, trunc
    assert len(calls) == 200 and len(rows) == 200, (len(calls), len(rows))
    assert any("backstop" in r.getMessage() for r in logged), [r.getMessage() for r in logged]
    assert of_paging.page_all(endless) == rows


def case_ids_from_pages():
    fetch, _ = _rec({0: [{"id": "5"}, {"id": 6}, {"name": "x"}, {"id": "abc"}, {"id": 6}]})
    assert of_paging.ids_from_pages(fetch) == ({5, 6}, False)


def case_same_objects():
    assert audiences._page_all_checked is of_paging.page_all_checked
    assert audiences._page_all is of_paging.page_all
    assert audiences._ids_from_pages is of_paging.ids_from_pages
    assert audiences._LIST_PAGE == of_paging.LIST_PAGE == 100
    assert audiences._ROSTER_PAGE == of_paging.ROSTER_PAGE == 50


def case_patch_reaches_callers():
    """A fault that patches `of_paging.page_all_checked` must reach every caller
    that goes through the module attribute."""
    real = of_paging.page_all_checked
    of_paging.page_all_checked = lambda fetch: ([{"id": 1}], True)
    try:
        assert of_paging.page_all(lambda off: []) == [{"id": 1}]
        assert of_paging.ids_from_pages(lambda off: []) == ({1}, True)

        class C:
            def subscribers(self, **kw):
                return []
        assert audiences.resolve_recipients_blocking(C(), user_lists=["fans"]) is None
    finally:
        of_paging.page_all_checked = real

    class C2:
        def subscribers(self, **kw):
            return [{"id": 3}] if kw.get("offset") == 0 else []
    assert audiences.resolve_recipients_blocking(C2(), user_lists=["fans"]) == [3]


_harness.run()
