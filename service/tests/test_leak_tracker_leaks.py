#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import json  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import httpx  # noqa: E402

import leak_tracker  # noqa: E402
from test_leak_tracker_api import (  # noqa: E402
    CREATOR, DOWN, EMP_SCOPED, ERR_401, IDS, KEY_1, ME, MIA, MIA_W, OWNER_A, PUT_CREATED, ROWAN_W, SCOPED, SECOND,
    TRACKER, Tracker, _connect, _enrol, _golden, _live, _rewatch, _setup, _tracker,
)

TEAM_LEADER = {"enforce": True, "roles": [], "assignments": {str(EMP_SCOPED): "team-leader"}}

LEAKS = _golden("leaks")
LEAKS_PAGE2 = _golden("leaks_page2")
CREATOR_LEAKS = _golden("creator_leaks")
CREATOR_ONE = _golden("creator_one")
MIA_LEAKS = f"/v1/creators/{MIA_W}/leaks"


@contextmanager
def _page_size(n: int):
    import leak_tracker_api
    real, leak_tracker_api.PAGE = leak_tracker_api.PAGE, n
    try:
        yield
    finally:
        leak_tracker_api.PAGE = real


def _at(golden: dict) -> dict:
    return {**golden, "path": golden["path"].split("?")[0]}


def _enrol_two(t: Tracker) -> None:
    t.answer = PUT_CREATED
    assert _enrol().status_code == 200
    assert _enrol({**MIA, "username": "rowanash"}, account=SECOND).status_code == 200
    _rewatch(CREATOR, MIA_W)
    _rewatch(SECOND, ROWAN_W)
    t.routes[CREATOR_ONE["path"]] = CREATOR_ONE
    t.routes["/v1/me"] = ME


def _as_account(golden: dict, account: str) -> list[dict]:
    return [{**{k: v for k, v in leak.items() if k != "watch_id"}, "account_id": account}
            for leak in golden["response"]["leaks"]]


def _all(client=OWNER_A, cursor: str | None = None) -> dict:
    r = client.get("/admin/leaks/all", params={"cursor": cursor} if cursor else None)
    assert r.status_code == 200, r.text
    return r.json()


def _gets(t: Tracker) -> list[str]:
    return [str(c.url) for c in t.calls if c.method == "GET"]


def case_all_lists_the_session_watches_newest_first_mapped_to_their_creators():
    _connect()
    with _tracker() as t, _live({}), _page_size(2):
        _enrol_two(t)
        t.routes["/v1/leaks"] = _at(LEAKS)
        first = _all()
        t.routes["/v1/leaks"] = _at(LEAKS_PAGE2)
        second = _all(cursor=first["next_cursor"])
        assert _gets(t) == [TRACKER + LEAKS["path"], TRACKER + LEAKS_PAGE2["path"]], _gets(t)
        assert set(t.bearers()) == {f"Bearer {KEY_1}"}
    assert first["leaks"] == _as_account(LEAKS, CREATOR), first
    assert (first["next_cursor"], first["stale"]) == (LEAKS["response"]["next_cursor"], False), first
    assert second["leaks"] == _as_account(LEAKS_PAGE2, CREATOR) and second["next_cursor"] is None, second
    assert [x["first_seen_at"] for x in first["leaks"] + second["leaks"]] == sorted(
        (x["first_seen_at"] for x in first["leaks"] + second["leaks"]), reverse=True)


def case_all_asks_only_for_the_session_watches_and_none_for_an_empty_set():
    _connect(TEAM_LEADER)
    with _tracker() as t, _live({}):
        t.answer = PUT_CREATED
        assert _enrol({**MIA, "username": "rowanash"}, account=SECOND).status_code == 200
        _rewatch(SECOND, ROWAN_W)
        puts = len(t.calls)
        empty = _all(SCOPED)
        assert len(t.calls) == puts, "no visible watch: no call"
        assert _enrol().status_code == 200
        _rewatch(CREATOR, MIA_W)
        foreign = {**LEAKS["response"]["leaks"][1], "watch_id": ROWAN_W, "leak_id": "lk_0009"}
        t.routes["/v1/leaks"] = {**_at(LEAKS), "response": {
            "leaks": [LEAKS["response"]["leaks"][0], foreign, {**foreign, "watch_id": "w_unknown_0009"}],
            "next_cursor": None}}
        scoped = _all(SCOPED)
        (url,) = _gets(t)
    assert empty == {"leaks": [], "next_cursor": None, "stale": False, "fetched_at": None}, empty
    assert httpx.URL(url).params.get_list("watch_id") == [MIA_W], url
    assert [x["leak_id"] for x in scoped["leaks"]] == ["lk_0004"], scoped
    assert ROWAN_W not in json.dumps(scoped) and SECOND not in json.dumps(scoped)


def case_all_queries_only_watches_with_a_successful_push():
    _connect()
    with _tracker() as t, _live({}):
        t.answer = DOWN
        assert _enrol({**MIA, "username": "rowanash"}, account=SECOND).json() == {"synced": False}
        assert _all()["leaks"] is None
        assert not _gets(t)
        t.answer = PUT_CREATED
        assert _enrol().json() == {"synced": True}
        _rewatch(CREATOR, MIA_W)
        t.routes["/v1/leaks"] = _at(LEAKS)
        assert _all()["leaks"] == _as_account(LEAKS, CREATOR)
        (url,) = _gets(t)
        assert httpx.URL(url).params.get_list("watch_id") == [MIA_W]


def case_all_serves_the_last_good_copy_when_the_service_is_down():
    _connect(TEAM_LEADER)
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes["/v1/leaks"] = DOWN
        none = _all()
        t.routes["/v1/leaks"] = _at(LEAKS)
        fresh = _all()
        t.routes["/v1/leaks"] = {**_at(LEAKS), "status": 503, "response": {"error": "unavailable"}}
        stale = _all()
        t.routes["/v1/leaks"] = {**_at(LEAKS), "status": 429, "response": {"error": "busy"}}
        assert _all() == stale
        t.routes["/v1/leaks"] = DOWN
        scoped = _all(SCOPED)
    assert none == {"leaks": None, "next_cursor": None, "stale": False, "fetched_at": None}, none
    assert stale == {**fresh, "stale": True}, stale
    assert scoped == none, "a Team Leader never gets the owner's copy"


def case_a_later_page_is_never_kept_and_reads_503_when_the_service_is_down():
    _connect()
    with _tracker() as t, _live({}), _page_size(2):
        _enrol_two(t)
        cursor = LEAKS["response"]["next_cursor"]
        t.routes["/v1/leaks"] = _at(LEAKS_PAGE2)
        assert _all(cursor=cursor)["next_cursor"] is None
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        assert _drill(cursor=cursor).status_code == 200
        kept = [path for agency, path in leak_tracker._copies if agency == IDS["agency_a_owner"]]
        t.routes["/v1/leaks"] = t.routes[MIA_LEAKS] = DOWN
        down = [OWNER_A.get("/admin/leaks/all", params={"cursor": cursor}), _drill(cursor=cursor)]
    assert not any("cursor=" in path for path in kept), kept
    for r in down:
        assert (r.status_code, r.json()) == (503, {"detail": "The removal service is not reachable"}), r.text


def case_a_bad_cursor_on_a_hidden_tracker_reads_404():
    _connect()
    for path in ("/admin/leaks/all", f"/admin/leaks/watches/{CREATOR}"):
        r = OWNER_A.get(path, params={"cursor": "c" * 513})
        assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), (path, r.text)


def case_all_with_a_refused_key_reads_key_invalid_and_a_bad_answer_is_502():
    for label, answer, status in [
        ("401", {**_at(LEAKS), "status": 401, "response": ERR_401["response"]}, 409),
        ("422", {**_at(LEAKS), "status": 422, "response": {"error": "invalid", "field": "watch_id"}}, 502),
        ("all malformed", {**_at(LEAKS), "response": {"leaks": [{}], "next_cursor": None}}, 502),
        ("invalid URL", {**_at(LEAKS), "response": {
            "leaks": [{**LEAKS["response"]["leaks"][0], "url": "https://["}], "next_cursor": None}}, 502),
        ("invalid pill", {**_at(LEAKS), "response": {
            "leaks": [{**LEAKS["response"]["leaks"][0], "pill": []}], "next_cursor": None}}, 502),
        ("no list", {**_at(LEAKS), "response": {"leaks": {}, "next_cursor": None}}, 502),
        ("cursor a number", {**_at(LEAKS), "response": {"leaks": [], "next_cursor": 7}}, 502),
    ]:
        _connect()
        with _tracker() as t, _live({}):
            _enrol_two(t)
            t.routes["/v1/leaks"] = answer
            r = OWNER_A.get("/admin/leaks/all")
            t.answer = ME
            key = _setup()["key"]
        assert r.status_code == status, (label, r.text)
        if status == 409:
            assert r.json()["detail"] == {"error": "key_invalid", "message": "Key no longer valid"}, r.text
            assert key == "invalid", label


def case_a_malformed_or_unsafe_leak_is_dropped_and_unknown_fields_never_pass():
    good = LEAKS["response"]["leaks"][0]
    bad = [{**good, "url": "javascript:alert(1)"}, {**good, "url": None}, {**good, "pill": "removed"},
           {**good, "came_back": "no"}, {**good, "first_seen_at": 7}, {**good, "watch_id": None}, ["lk_0001"]]
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes["/v1/leaks"] = {**_at(LEAKS), "response": {
            "leaks": [*bad, {**good, "thumbnail_url": "https://img.example-leaks.test/a.jpg"}], "next_cursor": None}}
        body = _all()
    assert body["leaks"] == _as_account({"response": {"leaks": [good]}}, CREATOR), body
    assert "thumbnail" not in json.dumps(body)


def _drill(account: str = CREATOR, client=OWNER_A, cursor: str | None = None):
    return client.get(f"/admin/leaks/watches/{account}", params={"cursor": cursor} if cursor else None)


def case_the_drill_in_lists_the_watch_leaks_with_their_events_page_by_page():
    _connect()
    with _tracker() as t, _live({}), _page_size(2):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        first = _drill()
        nxt = _drill(cursor="MjAyNi0xMS0yMFQwOTowNjowMFp8bGtfMDAwMw")
        urls = [httpx.URL(u) for u in _gets(t)]
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["tracked"] is True and body["identity"]["username"] == "miavale", body
    assert body["leaks"] == CREATOR_LEAKS["response"]["leaks"], body["leaks"]
    assert (body["next_cursor"], body["stale"]) == (None, False), body
    assert sorted((u.path, sorted(u.params.items())) for u in urls) == [
        (CREATOR_ONE["path"], []), (MIA_LEAKS, [("cursor", "MjAyNi0xMS0yMFQwOTowNjowMFp8bGtfMDAwMw"), ("limit", "2")]),
        (MIA_LEAKS, [("limit", "2")]), ("/v1/me", [])], urls
    assert nxt.status_code == 200, nxt.text


def case_the_drill_in_of_an_untracked_or_unsynced_creator_makes_no_leak_call():
    _connect()
    with _tracker() as t, _live({}):
        untracked = _drill().json()
        t.answer = DOWN
        assert _enrol().json() == {"synced": False}
        unsynced = _drill().json()
        assert t.calls and all(c.method == "PUT" for c in t.calls), _gets(t)
    for body, expected in ((untracked, []), (unsynced, None)):
        assert (body["leaks"], body["next_cursor"], body["stale"], body["fetched_at"]) == (expected, None, False, None), body


def case_failed_edit_keeps_the_existing_leaks_readable_and_retries_same_day():
    import asyncio

    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        t.answer = DOWN
        assert _enrol({**MIA, "display_name": "Edited"}).json() == {"synced": False}
        drill = _drill().json()
        assert drill["leaks"] and drill["synced"] is False
        t.answer = PUT_CREATED
        asyncio.run(leak_tracker.sync_watches())
        assert _drill().json()["synced"] is True


def case_each_leak_keeps_its_own_events_even_when_an_id_repeats():
    one, two = CREATOR_LEAKS["response"]["leaks"][:2]
    twin = {**two, "leak_id": one["leak_id"]}
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = {**CREATOR_LEAKS, "response": {"leaks": [one, twin], "next_cursor": None}}
        body = _drill().json()
    assert [x["events"] for x in body["leaks"]] == [one["events"], two["events"]], body["leaks"]


def case_the_drill_in_serves_a_stale_copy_and_with_none_still_serves_the_identity():
    _connect()
    with _tracker() as t, _live({}):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = DOWN
        none = _drill().json()
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        fresh = _drill().json()
        t.routes[MIA_LEAKS] = httpx.ReadTimeout("slow")
        stale = _drill().json()
    assert none["tracked"] is True and none["identity"]["username"] == "miavale", none
    assert (none["leaks"], none["stale"]) == (None, False), none
    assert stale == {**fresh, "stale": True}, stale


def case_the_drill_in_with_a_refused_key_reads_key_invalid_and_outside_the_session_is_404():
    _connect(TEAM_LEADER)
    with _tracker() as t, _live({}):
        _enrol_two(t)
        calls = len(t.calls)
        outside = _drill(SECOND, SCOPED, cursor="x")
        assert len(t.calls) == calls, "an out-of-scope drill-in makes no call"
        t.routes[MIA_LEAKS] = {**CREATOR_LEAKS, "status": 401, "response": ERR_401["response"]}
        refused = _drill(client=SCOPED)
        bad = _drill(CREATOR, OWNER_A, cursor="c" * 513)
        key = _setup()["key"]
    assert (outside.status_code, outside.json()) == (404, {"detail": "Not Found"}), outside.text
    assert refused.status_code == 409 and refused.json()["detail"]["error"] == "key_invalid", refused.text
    assert key == "invalid"
    assert bad.status_code == 422, bad.text


if __name__ == "__main__":
    _harness.run()
