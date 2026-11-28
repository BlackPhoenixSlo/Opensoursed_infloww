#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402

import httpx  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from test_leak_tracker_api import (  # noqa: E402
    CHATTER_A, CREATOR, CREATORS, DOWN, EMP_A, EMP_SCOPED, ERR_401, FANSLY, IDS, KEY_1, LIMITED, ME, MIA_W, OWNER_A,
    PUT_CREATED, SECOND, _connect, _enrol, _golden, _live, _roster, _setup, _track, _tracker, _watches,
)
from test_leak_tracker_leaks import (  # noqa: E402
    CREATOR_LEAKS, CREATOR_ONE, MIA_LEAKS, SCOPED, _drill, _enrol_two,
)

LANES = CREATOR_ONE["response"]["lanes"]
MIA_ONE = CREATOR_ONE["path"]


def _one(lanes) -> dict:
    return {**CREATOR_ONE, "response": {**CREATOR_ONE["response"], "lanes": lanes}}


def _lane_gets(t) -> list[str]:
    return [c.url.path for c in t.calls if c.method == "GET" and c.url.path == MIA_ONE]


def case_lanes_reach_the_drill_in_unchanged_and_a_later_page_asks_for_none():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        first = _drill()
        later = _drill(cursor="c2")
        gets, bearers = _lane_gets(t), {c.headers.get("authorization") for c in t.calls if c.method == "GET"}
    assert first.status_code == 200, first.text
    assert first.json()["lanes"] == LANES, first.json()["lanes"]
    assert first.json()["leaks"] == CREATOR_LEAKS["response"]["leaks"]
    assert later.status_code == 200 and later.json()["lanes"] is None, later.text
    assert gets == [MIA_ONE], gets
    assert bearers == {f"Bearer {KEY_1}"}, bearers


def case_paused_reduced_waiting_and_trimmed_lanes_pass_through():
    lanes = [
        {**LANES[0], "state": "paused", "next_attempt_on": None},
        {**LANES[2], "state": "reduced", "reason": "listing_rotated"},
        {**LANES[3], "state": "waiting", "reason": "cap_tenant_month", "next_attempt_on": "2026-12-01"},
        {**LANES[4], "state": "reduced", "reason": "cap_global",
         "trimmed": [{"field": "alias:1", "value": "mia.vale.x"}, {"field": "instagram", "value": "miavale"}]},
    ]
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        t.routes[MIA_ONE] = _one(lanes)
        body = _drill().json()
    assert body["lanes"] == lanes, body["lanes"]


def case_a_malformed_lane_is_dropped_and_unknown_fields_never_pass():
    good = LANES[4]
    bad = [{**good, "state": "done"}, {**good, "state": []}, {**good, "lane": "bing"}, {**good, "cadence": "hourly"},
           {**good, "last_success_at": 7}, {**good, "reason": ["x"]}, "google_full", None]
    junk = [{"field": "x", "value": "miavale"}, {"field": 1, "value": "a"}, {"field": "x"}, "alias:0"]
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        t.routes[MIA_ONE] = _one([*bad, {**good, "carry_json": "{}", "trimmed": junk, "plan": {"loads": 31}}])
        body = _drill().json()
    assert body["lanes"] == [{**good, "trimmed": [{"field": "x", "value": "miavale"}]}], body["lanes"]
    assert "carry_json" not in json.dumps(body) and "plan" not in json.dumps(body["lanes"])


def case_a_bad_lanes_answer_reads_null_and_the_leak_list_still_works():
    for label, answer in [
        ("no lanes", {**CREATOR_ONE, "response": {k: v for k, v in CREATOR_ONE["response"].items() if k != "lanes"}}),
        ("lanes null", _one(None)),
        ("lanes a dict", _one({})),
        ("404", {**CREATOR_ONE, "status": 404, "response": {"error": "not_found"}}),
        ("422", {**CREATOR_ONE, "status": 422, "response": {"error": "invalid"}}),
        ("500", {**CREATOR_ONE, "status": 500, "response": {"error": "boom"}}),
        ("not json", {**CREATOR_ONE, "raw": b"<html>"}),
    ]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_two(t)
            t.routes[MIA_LEAKS] = CREATOR_LEAKS
            t.routes[MIA_ONE] = answer
            r = _drill()
        assert r.status_code == 200, (label, r.text)
        body = r.json()
        assert body["lanes"] is None and body["leaks"] == CREATOR_LEAKS["response"]["leaks"], (label, body)
        assert body["stale"] is False, label


def case_a_bad_lanes_answer_never_replaces_the_last_good_copy():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        assert _drill().json()["lanes"] == LANES
        t.routes[MIA_ONE] = _one({})
        assert _drill().json()["lanes"] is None
        t.routes[MIA_ONE] = DOWN
        body = _drill().json()
    assert (body["lanes"], body["stale"]) == (LANES, True), body


def case_a_refused_key_on_the_lanes_read_is_key_invalid():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        t.routes[MIA_ONE] = {**CREATOR_ONE, "status": 401, "response": ERR_401["response"]}
        r = _drill()
        t.answer = ME
        key = _setup()["key"]
    assert r.status_code == 409 and r.json()["detail"]["error"] == "key_invalid", r.text
    assert key == "invalid"


def case_with_the_service_down_lanes_read_null_or_the_last_good_copy_marked_stale():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        t.routes[MIA_ONE] = DOWN
        none = _drill().json()
        t.routes[MIA_ONE] = CREATOR_ONE
        fresh = _drill().json()
        t.routes[MIA_ONE] = httpx.ReadTimeout("slow")
        stale = _drill().json()
    assert none["lanes"] is None and none["leaks"] == CREATOR_LEAKS["response"]["leaks"], none
    assert (none["stale"], fresh["stale"]) == (False, False), (none, fresh)
    assert stale["removal"] == {**fresh["removal"], "stale": True}, stale
    assert fresh["lanes"] == stale["lanes"] == LANES
    assert {**stale, "removal": fresh["removal"], "fetched_at": None} == {**fresh, "stale": True, "fetched_at": None}


def case_an_untracked_creator_asks_for_no_lanes():
    _connect()
    with _tracker() as t, _live({}):
        body = _drill().json()
        calls = list(t.calls)
    assert (body["tracked"], body["lanes"]) == (False, None), body
    assert calls == [], [str(c.url) for c in calls]


def case_an_unsynced_watch_asks_for_no_lanes():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = DOWN
        assert _enrol().json() == {"synced": False}
        body = _drill().json()
        assert all(c.method == "PUT" for c in t.calls), [str(c.url) for c in t.calls]
    assert body["lanes"] is None, body


def case_the_drill_in_passes_this_week_through_and_a_bad_or_missing_this_week_reads_null():
    one = CREATOR_ONE["response"]
    week, at = one["this_week"], one["next_refresh_at"]
    assert (week["state"], week["since"], at) == ("partial", "2026-11-21", "2026-11-28T04:00:00Z")
    drop = {k: v for k, v in one.items() if k not in ("this_week", "next_refresh_at")}
    for label, answer, want in [
        ("golden", CREATOR_ONE, (week, at)),
        ("unknown keys dropped", {**CREATOR_ONE, "response": {**one, "this_week": {**week, "lane_day": [1], "watch_id": "w_x"}}},
         (week, at)),
        ("missing", {**CREATOR_ONE, "response": drop}, (None, None)),
        ("a pre-change today", {**CREATOR_ONE, "response": {**drop, "today": {**week, "day": "2026-11-27"}}}, (None, None)),
        ("unknown state", {**CREATOR_ONE, "response": {**one, "this_week": {**week, "state": "done"}}}, (None, at)),
        ("list state", {**CREATOR_ONE, "response": {**one, "this_week": {**week, "state": []}}}, (None, at)),
        ("count a bool", {**CREATOR_ONE, "response": {**one, "this_week": {**week, "gone": False}}}, (None, at)),
        ("next refresh a number", {**CREATOR_ONE, "response": {**one, "next_refresh_at": 7}}, (week, None)),
        ("no lanes", {**CREATOR_ONE, "response": {k: v for k, v in one.items() if k != "lanes"}}, (None, None)),
    ]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_two(t)
            t.routes[MIA_LEAKS] = CREATOR_LEAKS
            t.routes[MIA_ONE] = answer
            body = _drill().json()
            later = _drill(cursor="c2").json()
        assert (body["this_week"], body["next_refresh_at"]) == want, (label, body["this_week"], body["next_refresh_at"])
        assert "today" not in body, label
        assert body["leaks"] == CREATOR_LEAKS["response"]["leaks"], label
        assert (later["this_week"], later["next_refresh_at"]) == (None, None), label
    _connect()
    with _tracker() as t, _live({}):
        body = _drill().json()
    assert (body["this_week"], body["next_refresh_at"]) == (None, None), "an untracked Creator has no week"


def case_the_coverage_goldens_pass_through_with_five_weekly_lanes():
    for name in ("creator_one_coverage", "creator_one_coverage_paused"):
        g = _golden(name)
        _connect()
        with _tracker() as t, _live({}):
            _enrol_two(t)
            t.routes[MIA_LEAKS] = CREATOR_LEAKS
            t.routes[MIA_ONE] = {**g, "path": MIA_ONE}
            body = _drill().json()
        want = g["response"]
        assert body["lanes"] == want["lanes"], (name, body["lanes"])
        assert len(body["lanes"]) == 5 and {x["cadence"] for x in body["lanes"]} == {"weekly"}, name
        assert "google_fresh" not in json.dumps(body), name
        assert (body["this_week"], body["next_refresh_at"]) == (want["this_week"], want["next_refresh_at"]), name


def case_a_pre_change_google_fresh_lane_is_dropped():
    fresh = {**LANES[0], "lane": "google_fresh", "cadence": "daily"}
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        t.routes[MIA_ONE] = _one([*LANES, fresh])
        body = _drill().json()
    assert body["lanes"] == LANES, body["lanes"]


def case_with_any_gate_off_the_drill_in_is_404_and_asks_nothing():
    for label, off in [("deployment", "env"), ("agency flag", "flag"), ("role", "role")]:
        _connect()
        with _tracker() as t, _live({}):
            t.answer = PUT_CREATED
            assert _enrol().status_code == 200
            t.calls.clear()
            if off == "env":
                os.environ["LEAK_TRACKER_ENABLED"] = "0"
            elif off == "flag":
                fx.store_blob(IDS["agency_a_owner"], "flags", {"leak_tracker": False})
            else:
                fx.store_blob(IDS["agency_a_owner"], "roles", {"enforce": True, "roles": [], "assignments": {}})
            client = SCOPED if off == "role" else OWNER_A
            r = client.get(f"/admin/leaks/watches/{CREATOR}")
            calls = list(t.calls)
        assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), (label, r.text)
        assert calls == [], label


QUEUED = _golden("refresh_queued")
RUNNING = _golden("refresh_running")
COOLDOWN = _golden("err_429_refresh_cooldown")
PAUSED = _golden("err_409_watch_paused")
MIA_REFRESH = f"/v1/watches/{MIA_W}/refresh"


def _refresh(account: str = CREATOR, client=OWNER_A):
    return client.post(f"/admin/leaks/watches/{account}/refresh")


def _posts(t) -> list:
    return [c for c in t.calls if c.method == "POST"]


def case_refresh_refusals_before_egress_make_no_upstream_call():
    _connect({"enforce": True, "roles": [], "assignments": {str(EMP_A): "team-leader", str(EMP_SCOPED): "admin"}})
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_REFRESH] = QUEUED
        t.calls.clear()
        cases = [("team leader", CREATOR, CHATTER_A, 403, "Only the owner or an Admin can change Leak tracking"),
                 ("another agency", IDS["creator_b"], OWNER_A, 404, "Not Found"),
                 ("unknown account", "1000999", OWNER_A, 404, "Not Found"),
                 ("outside the session scope", SECOND, SCOPED, 404, "Not Found"),
                 ("untracked", FANSLY, OWNER_A, 404, "Not Found")]
        got = [(label, _refresh(account, client)) for label, account, client, *_ in cases]
        assert _track(False).status_code == 200
        off = _refresh()
        assert _track(True).status_code == 200
        calls = list(t.calls)
    for (label, *_, status, detail), (_, r) in zip(cases, got):
        assert (r.status_code, r.json()["detail"]) == (status, detail), (label, r.text)
    assert (off.status_code, off.json()["detail"]) == (409, "Tracking is off for this Creator"), off.text
    assert calls == [], [str(c.url) for c in calls]


def case_refresh_queued_answers_200_and_drops_the_agencys_read_cache():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes["/v1/creators"] = CREATORS
        assert _roster()["rows"][0]["reachable"] is True
        t.routes[MIA_REFRESH] = QUEUED
        r = _refresh()
        (post,) = _posts(t)
        t.routes["/v1/creators"] = DOWN
        after = _roster()
    assert (r.status_code, r.json()) == (200, {"queued_at": "2026-11-27T12:00:00Z",
                                                "next_refresh_at": "2026-11-28T12:00:00Z"}), r.text
    assert (str(post.url), post.headers["authorization"], post.content) == (
        f"http://127.0.0.1:9{MIA_REFRESH}", f"Bearer {KEY_1}", b""), post
    assert after["stale"] is False and after["rows"][0]["reachable"] is False, "the next read is not served from cache"


def case_refresh_while_a_scan_runs_answers_its_earlier_queued_at():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_REFRESH] = RUNNING
        r = _refresh()
    assert (r.status_code, r.json()) == (200, {"queued_at": "2026-11-27T12:00:00Z",
                                                "next_refresh_at": "2026-11-28T12:01:00Z"}), r.text


def case_refresh_cooldown_is_429_with_retry_after_and_next_refresh_at():
    no_wait = {k: v for k, v in COOLDOWN["response"].items() if k != "retry_after_s"}
    for label, answer, retry in [
        ("golden", COOLDOWN, "57600"),
        ("body wins over the header", {**COOLDOWN, "headers": {"Retry-After": "5"}}, "57600"),
        ("header fallback", {**COOLDOWN, "response": no_wait, "headers": {"Retry-After": "120"}}, "120"),
        ("neither", {**COOLDOWN, "response": no_wait}, None),
    ]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_two(t)
            t.routes[MIA_REFRESH] = answer
            r = _refresh()
        assert (r.status_code, r.json()) == (429, {"detail": "Refreshed recently",
                                                    "next_refresh_at": "2026-11-28T04:00:00Z"}), (label, r.text)
        assert r.headers.get("retry-after") == retry, (label, r.headers)


def case_refresh_rate_limited_is_429_try_again_shortly():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_REFRESH] = {**LIMITED, "method": "POST", "headers": {"Retry-After": "30"}}
        r = _refresh()
    assert (r.status_code, r.json()) == (429, {"detail": "Try again shortly", "next_refresh_at": None}), r.text
    assert r.headers.get("retry-after") == "30"


def case_refresh_watch_paused_reads_tracking_off():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_REFRESH] = PAUSED
        r = _refresh()
    assert (r.status_code, r.json()["detail"]) == (409, "Tracking is off for this Creator"), r.text


def case_refresh_waitlist_reads_a_plain_409_not_502():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_REFRESH] = {**PAUSED, "response": {"error": "waitlist"}}
        r = _refresh()
    assert (r.status_code, r.json()["detail"]) == (409, "The removal service is full right now; try again later"), r.text


def case_refresh_401_marks_the_key_invalid_and_asks_nothing_more():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_REFRESH] = {**QUEUED, "status": 401, "response": ERR_401["response"]}
        r = _refresh()
        again = _refresh()
        posts = len(_posts(t))
        t.answer = ME
        key = _setup()["key"]
    for one in (r, again):
        assert one.status_code == 409 and one.json()["detail"]["error"] == "key_invalid", one.text
    assert (posts, key) == (1, "invalid")


def case_refresh_410_drops_the_row_and_reads_404():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_REFRESH] = {**QUEUED, "status": 410, "response": {"error": "watch_deleted"}}
        r = _refresh()
    assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), r.text
    assert CREATOR not in [w.account_id for w in _watches()]


def case_refresh_down_or_5xx_is_503_and_a_bad_answer_502():
    for label, answer, want in [
        ("connect", DOWN, 503), ("timeout", httpx.ReadTimeout("slow"), 503),
        ("500", {**QUEUED, "status": 500, "response": {"error": "boom"}}, 503),
        ("503", {**QUEUED, "status": 503, "response": {"error": "unavailable"}}, 503),
        ("upstream 404", {**QUEUED, "status": 404, "response": {"error": "not_found"}}, 404),
        ("202 without queued_at", {**QUEUED, "response": {"watch_id": MIA_W}}, 502),
        ("not json", {**QUEUED, "raw": b"<html>"}, 502),
        ("422", {**QUEUED, "status": 422, "response": {"error": "invalid"}}, 502),
    ]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_two(t)
            t.routes[MIA_REFRESH] = answer
            r = _refresh()
        assert r.status_code == want, (label, r.text)
        assert CREATOR in [w.account_id for w in _watches()], label


if __name__ == "__main__":
    _harness.run()
