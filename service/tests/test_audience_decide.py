#!/usr/bin/env python3
"""
audience decide — table tests over the pure halves of the audience resolvers.
No DB, no OF.

  case_final_audience_table:  include order/dups kept; exclude sources merged
                              first-seen; str ids compared as ints; responders
                              all excluded, only the included ones "skipped".
  case_final_audience_truncated: any truncated crawl -> Fail, never a partial set.
  case_recipients_truncation_stops_crawl: resolve_recipients_blocking stops
                              crawling at the first backstop hit and records None;
                              an unknown user_list refuses before any crawl.
  case_exclude_sync_truncated_logs_loud: a truncated Auto_Exclude crawl syncs as
                              before (no raise) and logs an ERROR.
  case_include_decide_table:  off | shadow | enforce (+ kill switch / unhealthy).

Run: ./venv/bin/python service/tests/test_audience_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import logging  # noqa: E402
from datetime import datetime  # noqa: E402

import audiences  # noqa: E402
import of_paging  # noqa: E402
from audience_include import AudiencePolicy, IncludeDecision, include_decide  # noqa: E402
from audiences import Audience, Fail, final_audience  # noqa: E402


def _table(rows, fn) -> None:
    bad = []
    for rid, args, kw, want in rows:
        got = fn(*args, **kw)
        if got != want:
            bad.append(f"{rid}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def A(inc, exc, skipped=(), total=0):
    return (list(inc), list(exc), list(skipped), total)


def _fa(*a, **kw):
    """final_audience, an Audience read as (included, excluded, skipped, total)."""
    out = final_audience(*a, **kw)
    if isinstance(out, Fail):
        return out
    assert isinstance(out, Audience), out
    return (out.included, out.excluded, out.skipped_responders, out.responders_total)


def case_final_audience_table():
    _table([
        ("nothing", ([],), {}, A([], [])),
        ("base kept verbatim (order + dups)", ([3, 1, 3],), {}, A([3, 1, 3], [])),
        ("excludes win", ([1, 2, 3], [[2]]), {}, A([1, 3], [2])),
        ("exclude sources merged first-seen",
         ([1, 2, 3, 4], [[4, 2], [1, 2], [9]]), {}, A([3], [4, 2, 1, 9])),
        ("str ids compared as ints, kept as given",
         (["1", "2"], [[2], ["7"]]), {}, A(["1"], [2, "7"])),
        ("responders: all excluded, sorted, after the sources; only included ones skipped",
         ([5, 6, 7], [[9]]), {"responders": {8, 6, 1}},
         A([5, 7], [9, 1, 6, 8], skipped=[6], total=3)),
        ("responder already excluded is not duplicated",
         ([1, 2], [[2]]), {"responders": {2}}, A([1], [2], skipped=[2], total=1)),
        ("no responders -> zero total", ([1],), {"responders": set()}, A([1], [])),
        ("recipients shape: sorted base minus set excludes",
         (sorted({4, 1, 3}), [{3}, {9}]), {}, A([1, 4], [3, 9])),
    ], _fa)


def case_final_audience_truncated():
    _table([
        ("one truncated crawl", ([1, 2], [[2]]), {"truncated": ["'fans'"]},
         Fail("truncated:'fans'")),
        ("two", ([1],), {"truncated": ["a", "exclude list 9"]},
         Fail("truncated:a,exclude list 9")),
        ("empty labels list -> not truncated", ([1],), {"truncated": []}, A([1], [])),
    ], _fa)


class _Roster:
    """Fake OF client: `fans` pages forever (fresh ids) when `endless`, else one page."""

    def __init__(self, *, endless=None, members=None):
        self.endless = endless or set()
        self.members = members or {}
        self.calls: list[str] = []

    def _page(self, key, offset):
        self.calls.append(f"{key}@{offset}")
        if key in self.endless:
            return {"list": [{"id": 10_000 + offset}], "hasMore": True}
        return self.members.get(key, []) if offset == 0 else []

    def subscribers(self, *, offset=0, **kw):
        return self._page("fans", offset)

    def following(self, *, offset=0, **kw):
        return self._page("following", offset)

    def list_users_in(self, list_id, *, offset=0, **kw):
        return self._page(int(list_id), offset)


def case_recipients_truncation_stops_crawl():
    m = {"fans": [{"id": 1}, {"id": 2}], "following": [{"id": 3}], 77: [{"id": 2}]}
    ok = _Roster(members=m)
    assert audiences.resolve_recipients_blocking(
        ok, user_lists=["fans", "following"], excluded_user_lists=[77]) == [1, 3]

    # include crawl truncated: None, and neither following nor the exclude list crawled
    c = _Roster(endless={"fans"}, members=m)
    assert audiences.resolve_recipients_blocking(
        c, user_lists=["fans", "following"], excluded_user_lists=[77]) is None
    assert not any(x.startswith(("following", "77")) for x in c.calls), c.calls[-3:]

    # exclude crawl truncated: None, later exclude lists not crawled
    c = _Roster(endless={77}, members=m)
    assert audiences.resolve_recipients_blocking(
        c, user_lists=["fans"], excluded_user_lists=[77, 88]) is None
    assert not any(x.startswith("88") for x in c.calls), c.calls[-3:]

    # unknown user_list: None before any crawl
    c = _Roster(members=m)
    assert audiences.resolve_recipients_blocking(c, user_lists=["fans", "vips"]) is None
    assert c.calls == [], c.calls


class _AutoExclude(_Roster):
    """Fake OF client holding an Auto_Exclude list (id 50) for _sync_exclude_list_blocking."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.added: list[int] = []
        self.removed: list[int] = []

    def get_lists(self, **kw):
        return {"list": [{"id": 50, "name": audiences.AUTO_EXCLUDE_LIST_NAME}], "hasMore": False}

    def add_user_to_list(self, lid, uid):
        self.added.append(uid)

    def remove_user_from_list(self, lid, uid):
        self.removed.append(uid)


def case_exclude_sync_truncated_logs_loud():
    """A truncated Auto_Exclude crawl keeps today's behaviour (sync goes on, the
    read members are reconciled) and logs an ERROR — never raises (a raise fails
    the send closed, changing who receives it)."""
    logged: list[logging.LogRecord] = []

    class H(logging.Handler):
        def emit(self, record):
            logged.append(record)
    h = H(level=logging.ERROR)
    audiences.log.addHandler(h)
    try:
        c = _AutoExclude(endless={50})          # ids 10_000 + offset, forever
        assert audiences._sync_exclude_list_blocking(c, {1, 10_000}) == 50
        assert c.added == [1], c.added           # 10_000 already a member
        assert len(c.removed) == of_paging.MAX_PAGES - 1 and 10_000 not in c.removed
        assert any("backstop" in r.getMessage() for r in logged), logged

        logged.clear()
        ok = _AutoExclude(members={50: [{"id": 1}, {"id": 9}]})
        assert audiences._sync_exclude_list_blocking(ok, {1, 2}) == 50
        assert (ok.added, ok.removed, logged) == ([2], [9], []), (ok.added, ok.removed, logged)
    finally:
        audiences.log.removeHandler(h)


def P(mode, *, healthy=True, paused=False, reason=None, members=()):
    return AudiencePolicy(mode=mode, configured_mode=mode, list_id=1, of_list_id=None,
                          member_ids=frozenset(members), synced_at=datetime(2026, 10, 1),
                          healthy=healthy, paused=paused, reason=reason)


def D(kept, stats, dropped=(), halted=None):
    return IncludeDecision(list(kept), stats, list(dropped), halted,
                           stats.get("audience_skipped_with_intent", 0))


def case_include_decide_table():
    cand = [1, 2, 3, 4]
    uni = {1, 3}
    intent = {2}
    _table([
        ("off: unchanged, no stats", (P("off"), cand, uni, intent), {}, D(cand, {})),
        ("shadow: unchanged, would-skips counted",
         (P("shadow"), cand, uni, intent), {},
         D(cand, {"audience_mode": "shadow", "audience_before": 4,
                  "audience_skipped": 2, "audience_skipped_with_intent": 1}, [2, 4])),
        ("shadow, unhealthy: still unchanged",
         (P("shadow", healthy=False, reason="snapshot_stale"), cand, uni, set()), {},
         D(cand, {"audience_mode": "shadow", "audience_before": 4,
                  "audience_skipped": 2, "audience_skipped_with_intent": 0}, [2, 4])),
        ("enforce: universe ∩ candidates, order kept",
         (P("enforce"), [3, 2, 1], uni, intent), {},
         D([3, 1], {"audience_mode": "enforce", "audience_before": 3,
                    "audience_skipped": 1, "audience_skipped_with_intent": 1}, [2])),
        ("enforce, nothing dropped",
         (P("enforce"), [1, 3], uni, set()), {},
         D([1, 3], {"audience_mode": "enforce", "audience_before": 2,
                    "audience_skipped": 0, "audience_skipped_with_intent": 0})),
        ("enforce, kill switch: empty, all held",
         (P("enforce", paused=True), cand, uni, intent), {},
         D([], {"audience_mode": "enforce", "audience_before": 4,
                "audience_halted": "kill_switch", "audience_skipped": 4,
                "audience_skipped_with_intent": 1}, cand, "kill_switch")),
        ("enforce, unhealthy reason",
         (P("enforce", healthy=False, reason="sync_truncated"), cand, uni, set()), {},
         D([], {"audience_mode": "enforce", "audience_before": 4,
                "audience_halted": "sync_truncated", "audience_skipped": 4,
                "audience_skipped_with_intent": 0}, cand, "sync_truncated")),
        ("enforce, unhealthy no reason",
         (P("enforce", healthy=False), [1], uni, set()), {},
         D([], {"audience_mode": "enforce", "audience_before": 1,
                "audience_halted": "unhealthy", "audience_skipped": 1,
                "audience_skipped_with_intent": 0}, [1], "unhealthy")),
        ("enforce, empty candidates",
         (P("enforce"), [], uni, set()), {},
         D([], {"audience_mode": "enforce", "audience_before": 0,
                "audience_skipped": 0, "audience_skipped_with_intent": 0})),
    ], include_decide)
    # stats key ORDER is part of the run output
    d = include_decide(P("enforce", paused=True), [1], set(), set())
    assert list(d.stats) == ["audience_mode", "audience_before", "audience_halted",
                             "audience_skipped", "audience_skipped_with_intent"], d.stats


_harness.run()
