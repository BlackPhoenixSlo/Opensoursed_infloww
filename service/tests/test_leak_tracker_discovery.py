#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402

import httpx  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from test_leak_tracker_api import (  # noqa: E402
    CREATOR, DOWN, ERR_401, IDS, KEY_1, ME, OWNER_A, PUT_CREATED, _connect, _enrol, _live, _setup, _tracker,
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
    bad = [{**good, "state": "done"}, {**good, "lane": "bing"}, {**good, "cadence": "hourly"},
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
    assert fresh["lanes"] == LANES and {**stale, "fetched_at": None} == {**fresh, "stale": True, "fetched_at": None}, stale


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


def case_the_drill_in_passes_today_through_and_a_bad_or_missing_today_reads_null():
    today = CREATOR_ONE["response"]["today"]
    assert today["state"] == "partial"
    drop = {k: v for k, v in CREATOR_ONE["response"].items() if k != "today"}
    for label, answer, want in [
        ("golden", CREATOR_ONE, today),
        ("unknown keys dropped", {**CREATOR_ONE, "response": {**CREATOR_ONE["response"],
                                                              "today": {**today, "lane_day": [1], "watch_id": "w_x"}}}, today),
        ("missing", {**CREATOR_ONE, "response": drop}, None),
        ("unknown state", {**CREATOR_ONE, "response": {**CREATOR_ONE["response"], "today": {**today, "state": "done"}}}, None),
        ("count a bool", {**CREATOR_ONE, "response": {**CREATOR_ONE["response"], "today": {**today, "gone": False}}}, None),
        ("no lanes", {**CREATOR_ONE, "response": {k: v for k, v in drop.items() if k != "lanes"} | {"today": today}}, None),
    ]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_two(t)
            t.routes[MIA_LEAKS] = CREATOR_LEAKS
            t.routes[MIA_ONE] = answer
            body = _drill().json()
            later = _drill(cursor="c2").json()
        assert body["today"] == want, (label, body["today"])
        assert body["leaks"] == CREATOR_LEAKS["response"]["leaks"], label
        assert later["today"] is None, label
    _connect()
    with _tracker() as t, _live({}):
        assert _drill().json()["today"] is None, "an untracked Creator has no day"


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


if __name__ == "__main__":
    _harness.run()
