#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (unset env falls back to PROD)

import logging  # noqa: E402
from _of_fixtures import UNLISTABLE_403, of_error  # noqa: E402
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
    assert audiences.roster_audience_blocking(
        ok, user_lists=["fans", "following"], excluded_user_lists=[77]) == [1, 3]

    c = _Roster(endless={"fans"}, members=m)
    assert audiences.roster_audience_blocking(
        c, user_lists=["fans", "following"], excluded_user_lists=[77]) is None
    assert not any(x.startswith(("following", "77")) for x in c.calls), c.calls[-3:]

    c = _Roster(endless={77}, members=m)
    assert audiences.roster_audience_blocking(
        c, user_lists=["fans"], excluded_user_lists=[77, 88]) is None
    assert not any(x.startswith("88") for x in c.calls), c.calls[-3:]

    c = _Roster(members=m)
    assert audiences.roster_audience_blocking(c, user_lists=["fans", "vips"]) is None
    assert c.calls == [], c.calls


class _AutoExclude(_Roster):

    def __init__(self, *, fail_add=(), fail_remove=(), **kw):
        super().__init__(**kw)
        self.added: list[int] = []
        self.removed: list[int] = []
        self.fail_add, self.fail_remove = set(fail_add), set(fail_remove)

    def get_lists(self, **kw):
        return {"list": [{"id": 50, "name": audiences.AUTO_EXCLUDE_LIST_NAME}], "hasMore": False}

    def add_user_to_list(self, lid, uid):
        if uid in self.fail_add:
            raise of_error(403, UNLISTABLE_403)
        self.added.append(uid)

    def remove_user_from_list(self, lid, uid):
        if uid in self.fail_remove:
            raise RuntimeError("403")
        self.removed.append(uid)


# a truncated Auto_Exclude crawl logs, never raises: a raise fails the send closed and changes who receives it
def case_exclude_sync_truncated_logs_loud():
    logged: list[logging.LogRecord] = []

    class H(logging.Handler):
        def emit(self, record):
            logged.append(record)
    h = H(level=logging.ERROR)
    audiences.log.addHandler(h)
    try:
        c = _AutoExclude(endless={50})
        assert audiences._sync_exclude_list_blocking(c, {1, 10_000}) == 50
        assert c.added == [1], c.added
        assert len(c.removed) == of_paging.MAX_PAGES - 1 and 10_000 not in c.removed
        assert any("backstop" in r.getMessage() for r in logged), logged

        logged.clear()
        ok = _AutoExclude(members={50: [{"id": 1}, {"id": 9}]})
        assert audiences._sync_exclude_list_blocking(ok, {1, 2}) == 50
        assert (ok.added, ok.removed, logged) == ([2], [9], []), (ok.added, ok.removed, logged)
    finally:
        audiences.log.removeHandler(h)


def case_exclude_add_failure_table():
    from curl_cffi.requests import exceptions as curl_exc
    rows = [
        ("403 Unable to add", of_error(403, '{"message":"Unable to add user to user list"}'), True),
        ("404 User not found", of_error(404, '{"error":{"message":"User not found"}}'), True),
        ("generic 403", of_error(403, '{"error":{"message":"Access denied"}}'), False),
        ("404 List not found", of_error(404, '{"error":{"message":"List not found"}}'), False),
        ("400 rate limit", of_error(400, '{"message":"Please allow 10 seconds"}'), False),
        ("429", of_error(429, "Too many requests. Please allow 1 seconds"), False),
        ("502", of_error(502, "Bad gateway"), False),
        ("timeout", curl_exc.Timeout("curl: (28) Operation timed out"), False),
        ("bare error naming the text", RuntimeError("Unable to add user to user list"), False),
    ]
    bad = []
    for name, err, goes_on in rows:
        c = _AutoExclude(members={50: [{"id": 1}]})

        def add(lid, uid, c=c, err=err):
            if uid == 2:
                raise err
            c.added.append(uid)
        c.add_user_to_list = add
        try:
            got = audiences._sync_exclude_list_blocking(c, {1, 2, 3}) == 50
        except Exception:
            got = False
        if got != goes_on:
            bad.append(f"{name}: goes on {got} != {goes_on}")
    assert not bad, "\n".join(bad)


def case_auto_exclude_lookup_incomplete_never_creates():
    class _Lists(_AutoExclude):
        def __init__(self, page, more):
            super().__init__()
            self.page, self.more, self.created = page, more, []

        def get_lists(self, **kw):
            return {"list": list(self.page), "hasMore": self.more}

        def create_list(self, name):
            self.created.append(name)
            return {"id": 77}

    stall = _Lists([{"id": 9, "name": "VIP"}], True)
    try:
        audiences._auto_exclude_list_id_blocking(stall)
        raised = False
    except of_paging.ListLookupIncomplete:
        raised = True
    assert raised and stall.created == [], (raised, stall.created)

    done = _Lists([{"id": 9, "name": "VIP"}], False)
    assert audiences._auto_exclude_list_id_blocking(done) == 77
    assert done.created == [audiences.AUTO_EXCLUDE_LIST_NAME], done.created


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
    d = include_decide(P("enforce", paused=True), [1], set(), set())
    assert list(d.stats) == ["audience_mode", "audience_before", "audience_halted",
                             "audience_skipped", "audience_skipped_with_intent"], d.stats


_harness.run()
