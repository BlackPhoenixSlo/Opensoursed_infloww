#!/usr/bin/env python3
from __future__ import annotations

import _harness

import logging  # noqa: E402

import audiences  # noqa: E402
import of_paging  # noqa: E402


def _rec(pages):
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
        ("offset ignored + hasMore forever -> stop on page adding nothing, incomplete",
         {0: same, 2: same, 4: same}, [1, 2], True, [0, 2]),
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


def case_repeat_short_end():
    full = [{"id": i} for i in range(100)]
    rows = [
        ("bare: OF repeats page 1 at offset 100 -> incomplete",
         {0: full, 100: full}, 100, True, [0, 100]),
        ("envelope: repeat with hasMore -> incomplete",
         {0: {"list": full, "hasMore": True}, 100: {"list": full, "hasMore": True}}, 100, True, [0, 100]),
        ("bare: a later page repeats an earlier one -> incomplete",
         {0: full, 100: [{"id": 500}], 101: full}, 101, True, [0, 100, 101]),
        ("non-dict-only page adds nothing -> incomplete",
         {0: full, 100: ["x", 7]}, 100, True, [0, 100]),
        ("short page then empty -> complete",
         {0: full, 100: [{"id": 200}, {"id": 201}]}, 102, False, [0, 100, 102]),
        ("envelope: empty page that says hasMore -> incomplete",
         {0: {"list": full, "hasMore": True}, 100: {"list": [], "hasMore": True}}, 100, True, [0, 100]),
        ("envelope short page with hasMore then empty -> complete",
         {0: {"list": full[:30], "hasMore": True}, 30: {"list": [], "hasMore": False}}, 30, False, [0, 30]),
        ("normal end: hasMore false -> complete",
         {0: {"list": full, "hasMore": True}, 100: {"list": [{"id": 300}], "hasMore": False}},
         101, False, [0, 100]),
        ("normal end: bare empty page -> complete",
         {0: full, 100: []}, 100, False, [0, 100]),
    ]
    bad = []
    for name, pages, want_n, want_inc, want_offs in rows:
        fetch, seen = _rec(pages)
        got, inc = of_paging.page_all_checked(fetch)
        if (len(got), inc, seen) != (want_n, want_inc, want_offs):
            bad.append(f"{name}: {(len(got), inc, seen)!r} != {(want_n, want_inc, want_offs)!r}")
    assert not bad, "\n".join(bad)
    fetch, _ = _rec({0: full, 100: full})
    assert of_paging.ids_from_pages(fetch) == (set(range(100)), True)


def case_list_members_repeat():
    full = [{"id": i} for i in range(1, 101)]

    class C:
        def list_users_in(self, lid, limit, offset):
            return list(full)
    ids, truncated = of_paging.list_member_ids(C(), 7)
    assert ids == set(range(1, 101)) and truncated is True, (len(ids), truncated)

    class Counted(C):
        def __init__(self, n):
            self.n, self.counts = n, 0

        def get_list(self, lid):
            self.counts += 1
            return {"id": lid, "usersCount": self.n}
    for n, want in ((100, False), (250, True), (None, True)):
        c = Counted(n)
        ids, truncated = of_paging.list_member_ids(c, 7)
        assert (len(ids), truncated, c.counts) == (100, want, 1), (n, truncated, c.counts)

    class Boom(C):
        def get_list(self, lid):
            raise RuntimeError("502")
    assert of_paging.list_member_ids(Boom(), 7)[1] is True
    c = Counted(3)
    c.list_users_in = lambda lid, limit, offset: [{"id": i} for i in (1, 2, 3)][offset:]
    assert of_paging.list_member_ids(c, 7) == ({1, 2, 3}, False) and c.counts == 0


def case_list_members_tail_only():
    p1 = [{"id": i} for i in range(1, 101)]
    p2 = [{"id": i} for i in range(101, 151)]

    # OF re-serves a list's last page past its end
    class C:
        def __init__(self, pages):
            self.pages, self.counts = pages, 0

        def list_users_in(self, lid, limit, offset):
            return self.pages.get(offset, [])

        def get_list(self, lid):
            self.counts += 1
            return {"id": lid, "usersCount": 150}
    rows = [
        ("tail repeat + count -> complete", {0: p1, 100: p2, 150: p2}, False),
        ("earlier page repeated + count -> incomplete", {0: p1, 100: p2, 150: p1}, True),
        ("tail repeat, a row's lastSeen moved + count -> complete",
         {0: p1, 100: p2, 150: [{**u, "lastSeen": "now"} for u in p2]}, False),
        ("tail repeat, envelope offset echo differs + count -> complete",
         {0: {"list": p1, "hasMore": True, "offset": 0},
          100: {"list": p2, "hasMore": True, "offset": 100},
          150: {"list": p2, "hasMore": True, "offset": 150}}, False),
        ("empty envelope with hasMore + count -> incomplete",
         {0: {"list": p1, "hasMore": True}, 100: {"list": p2, "hasMore": True},
          150: {"list": [], "hasMore": True}}, True),
    ]
    bad = []
    for name, pages, want in rows:
        ids, inc = of_paging.list_member_ids(C(pages), 7)
        if (len(ids), inc) != (150, want):
            bad.append(f"{name}: {(len(ids), inc)!r} != {(150, want)!r}")
    assert not bad, "\n".join(bad)


def case_find_list_id():
    page1 = [{"id": i, "name": f"n{i}"} for i in range(1, 101)]

    class C:
        def __init__(self, pages):
            self.pages = pages

        def get_lists(self, *, limit, offset):
            return self.pages.get(offset, {"list": [], "hasMore": False})
    repeat = {0: {"list": page1, "hasMore": True}, 100: {"list": page1, "hasMore": True}}
    whole = {0: {"list": page1, "hasMore": True},
             100: {"list": [{"name": "id-less"}, {"id": "500", "name": "late"}], "hasMore": False}}
    rows = [
        ("complete read, found", whole, "late", 500),
        ("complete read, absent -> None", whole, "nope", None),
        ("incomplete read, found on page 1", repeat, "n7", 7),
        ("incomplete read, absent -> raises", repeat, "late", of_paging.ListLookupIncomplete),
        ("exact name only", whole, "n", None),
    ]
    bad = []
    for name, pages, lname, want in rows:
        try:
            got = of_paging.find_list_id(C(pages), lname)
        except of_paging.ListLookupIncomplete as e:
            got = type(e)
        if got != want:
            bad.append(f"{name}: {got!r} != {want!r}")
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
    real = of_paging.page_all_checked
    of_paging.page_all_checked = lambda fetch: ([{"id": 1}], True)
    try:
        assert of_paging.page_all(lambda off: []) == [{"id": 1}]
        assert of_paging.ids_from_pages(lambda off: []) == ({1}, True)

        class C:
            def subscribers(self, **kw):
                return []
        assert audiences.roster_audience_blocking(C(), user_lists=["fans"]) is None
    finally:
        of_paging.page_all_checked = real

    class C2:
        def subscribers(self, **kw):
            return [{"id": 3}] if kw.get("offset") == 0 else []
    assert audiences.roster_audience_blocking(C2(), user_lists=["fans"]) == [3]



from datetime import date, timedelta  # noqa: E402

_TODAY = date(2026, 11, 21)


def _srow(rid, days):
    at = (_TODAY + timedelta(days=days)).isoformat() + "T12:00:00+00:00"
    return {"id": 900 + rid, "type": "post", "publishDateTime": at,
            "createdDateTime": "2026-11-01T00:00:00+00:00",
            "entity": {"id": rid, "text": f"post {rid}"}}


class _Cal:
    def __init__(self, rows, reply=None):
        self.rows, self.reply, self.windows = rows, reply, []

    def schedules(self, *, publish_date=None, publish_date_end=None,
                  time_zone="Europe/Ljubljana", limit=20):
        # OF: range honoured, limit/offset ignored, no hasMore
        self.windows.append((publish_date, publish_date_end))
        if self.reply is not None:
            return self.reply
        return {"list": [r for r in self.rows
                         if publish_date <= r["publishDateTime"][:10] <= publish_date_end],
                "syncInProcess": False}


def case_schedule_chunks_cover():
    ch = of_paging.schedule_chunks(30, today=_TODAY)
    assert ch[0][0] == _TODAY - timedelta(days=of_paging.SCHEDULE_PAD_BEFORE_DAYS), ch
    assert ch[-1][1] == _TODAY + timedelta(days=30 + of_paging.SCHEDULE_PAD_AFTER_DAYS), ch
    assert all(b[0] <= a[1] for a, b in zip(ch, ch[1:])), ch
    assert max((h - lo).days for lo, h in ch) == of_paging.SCHEDULE_CHUNK_DAYS, ch
    rows, why = of_paging.schedules_in_window(_Cal([_srow(1, 29), _srow(2, 30)]), 30,
                                              today=_TODAY)
    assert why is None and sorted(r["entity"]["id"] for r in rows) == [1, 2], (rows, why)


def case_schedules_full_day():
    cal = _Cal([_srow(1, 10), _srow(2, 10), _srow(3, 10), _srow(4, 25)])
    rows, why = of_paging.schedules_in_window(cal, 30, page=3, today=_TODAY)
    assert why and "one day" in why, why
    assert any(_span(w) == 1 for w in cal.windows), cal.windows


def case_schedules_full_chunk_reread():
    cal = _Cal([_srow(1, 8), _srow(2, 8), _srow(3, 11), _srow(4, 11), _srow(5, 20)])
    rows, why = of_paging.schedules_in_window(cal, 30, page=3, today=_TODAY)
    assert why is None, why
    assert sorted(r["entity"]["id"] for r in rows) == [1, 2, 3, 4, 5], rows
    assert any(_span(w) == 1 for w in cal.windows), cal.windows


def case_schedules_bad_replies():
    for label, reply in [("string", "<html>oops</html>"),
                         ("bare list", [_srow(1, 5)]),
                         ("no list", {"error": {"code": 0, "message": "x"}}),
                         ("list not a list", {"list": "nope"})]:
        rows, why = of_paging.schedules_in_window(_Cal([], reply=reply), 30, today=_TODAY)
        assert why, (label, rows)
        assert rows == [], (label, rows)
    for label, extra in [("syncInProcess", {"syncInProcess": True}),
                         ("hasMore", {"hasMore": True})]:
        reply = {"list": [_srow(1, 5)], **extra}
        rows, why = of_paging.schedules_in_window(_Cal([], reply=reply), 30, today=_TODAY)
        assert why and label in why, (label, why)
        assert [r["entity"]["id"] for r in rows] == [1], (label, rows)


def case_schedules_bad_chunk_reads_on():
    class _Syncing(_Cal):
        def schedules(self, **kw):
            reply = super().schedules(**kw)
            if kw["publish_date"] <= (_TODAY + timedelta(days=8)).isoformat() <= kw["publish_date_end"]:
                reply["syncInProcess"] = True
            return reply
    rows, why = of_paging.schedules_in_window(_Syncing([_srow(1, 4), _srow(2, 30)]), 30,
                                              today=_TODAY)
    assert why and "syncInProcess" in why, why
    assert sorted(r["entity"]["id"] for r in rows) == [1, 2], rows


class _MoreOn(_Cal):
    def __init__(self, rows, more):
        super().__init__(rows)
        self.more = more

    def schedules(self, **kw):
        reply = super().schedules(**kw)
        if self.more(kw["publish_date"], kw["publish_date_end"]):
            reply["hasMore"] = True
        return reply


def case_schedules_chunk_hasmore_rereads_by_day():
    cal = _MoreOn([_srow(1, 3), _srow(2, 20)],
                  lambda lo, hi: _span((lo, hi)) > 1)
    rows, why = of_paging.schedules_in_window(cal, 30, today=_TODAY)
    assert why is None, why
    assert any(_span(w) == 1 for w in cal.windows), cal.windows
    assert sorted(r["entity"]["id"] for r in rows) == [1, 2], rows


def case_schedules_day_hasmore_is_gap():
    bad = (_TODAY + timedelta(days=3)).isoformat()
    cal = _MoreOn([_srow(1, 3), _srow(2, 20)], lambda lo, hi: lo <= bad <= hi)
    rows, why = of_paging.schedules_in_window(cal, 30, today=_TODAY)
    assert why and f"{bad}:" in why and "hasMore" in why, why
    assert sorted(r["entity"]["id"] for r in rows) == [1, 2], rows


def _span(w) -> int:
    return (date.fromisoformat(w[1]) - date.fromisoformat(w[0])).days


_harness.run()
