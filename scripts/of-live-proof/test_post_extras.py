"""ofm-not-yet ticket 35: New post's labels, expiration and target proof (proofs/phase2.py
p2.post-labels-expiry-target), FakeOF's posts surface (soak/fake_of/posts.py) and the planted post-drop-* faults
(fake_layer.py): a 2xx that drops a field fails the read-back.
"""
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient

from fake_layer import DROPS, Recorder
from live_entry import live_refusal
from proofs import ALL, phase2
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World

PROOF = ALL["p2.post-labels-expiry-target"]
MARK = "oi-proof-t35"


def _client(fault=None):
    fake = FakeOF(World(seed=1))
    app = fake.build()
    client = TestClient(Recorder(app, fault) if fault else app)

    def call(method, path_qs, json=None):
        t = str(int(time.time() * 1000))
        uid = str(fake.world.creator_id)
        h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
             "sign": sign_value(fake.rules, time_ms=t, path_qs=path_qs, user_id=uid)}
        return client.request(method, path_qs, headers=h, json=json)
    return call


def _read(call):
    def get(path, q):
        return call("GET", path + (f"?{urlencode(q)}" if q else "")).json()
    return phase2.read_post_extras(get, None)


def _body(label="3101"):
    """OF's body for the post the trigger makes (service/of_sends.py `_post_body`: posted_at, expire_days,
    fund_raising_target with the default presets, label_ids)."""
    at = (datetime.now(timezone.utc) + timedelta(days=31)).replace(microsecond=0).isoformat()   # ≤ next month's 1st
    return {"text": MARK, "mediaFiles": [], "price": 0, "isScheduled": 1, "scheduledDate": at,
            "expireDays": phase2.EXTRAS_DAYS, "fundRaisingTargetAmount": phase2.EXTRAS_TARGET,
            "fundRaisingTipsPresets": [5], "labelIds": [int(label)]}


def test_fake_post_is_read_back_with_its_label_expiry_and_target_and_deleted():
    call = _client()
    before = _read(call)
    assert before == {"labels": [["3101", "Label 3"], ["3102", "Label 4"]], "posts": []}
    r = call("POST", "/api2/v2/posts", _body())
    assert r.status_code == 200
    post = r.json()
    assert post["labelStates"] == [{"id": 3101, "isAdded": True}]
    assert post["fundRaising"] == {"target": 25, "presets": [5]}
    after = _read(call)
    assert after["posts"] == [[str(post["id"]), MARK, ["3101"], 7, 25.0]]
    rows = call("GET", "/api2/v2/schedules?" + urlencode({"filter[publishDate]": "2000-01-01",
                                                           "filter[publishDateEnd]": "2100-01-01",
                                                           "filter[timeZone]": "UTC"})).json()["list"]
    row = rows[0]   # a queue row: its own id is not the post's
    assert row["entity"]["id"] == post["id"] != row["id"]
    # ticket 136: a dated post is not on OF's saved-for-later list, so a reader still on it would see `posts: []`
    assert call("GET", "/api2/v2/schedules/later/post").json()["list"] == []
    assert phase2.post_extras_held(before, after)
    assert phase2.find_marked_post(before["posts"], after["posts"], MARK) == str(post["id"])
    assert call("DELETE", f"/api2/v2/posts/{post['id']}").json() == {"success": True}
    assert _read(call) == before
    assert call("DELETE", f"/api2/v2/posts/{post['id']}").status_code == 404


def test_a_post_with_no_extras_reads_back_none():
    call = _client()
    before = _read(call)
    body = {k: v for k, v in _body().items() if k in ("text", "mediaFiles", "price", "isScheduled", "scheduledDate")}
    call("POST", "/api2/v2/posts", body)
    after = _read(call)
    assert after["posts"][0][2:] == [[], None, None]
    assert not phase2.post_extras_held(before, after)


@pytest.mark.parametrize("fault", sorted(DROPS))
def test_drop_fault_answers_200_and_the_read_back_fails(fault):
    call = _client(fault)
    before = _read(call)
    r = call("POST", "/api2/v2/posts", _body())
    assert r.status_code == 200 and r.json()["id"]
    after = _read(call)
    assert len(after["posts"]) == 1
    assert not phase2.post_extras_held(before, after)   # the dropped field fails the proof
    # every other field still landed: only the planted one is missing
    _, _, ids, days, target = after["posts"][0]
    assert (ids == [], days is None, target is None) == tuple(f == fault for f in
                                                              ("post-drop-label", "post-drop-expiry", "post-drop-target"))


def test_drop_fault_marks_a_body_without_its_field():
    fault = "post-drop-label"
    fake = FakeOF(World(seed=1))
    rec = Recorder(fake.build(), fault)
    client = TestClient(rec)
    t, uid = str(int(time.time() * 1000)), str(fake.world.creator_id)
    h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
         "sign": sign_value(fake.rules, time_ms=t, path_qs="/api2/v2/posts", user_id=uid)}
    client.post("/api2/v2/posts", headers=h, json={"text": MARK})
    assert rec.snapshot()[-1]["fault"].startswith(f"{fault}: the body had no labelIds")


def _after(ids=("3101",), days=7, target=25.0, text=MARK, labels=(("3101", "Label 3"), ("3102", "Label 4"))):
    return {"labels": [list(x) for x in labels], "posts": [["9", text, list(ids), days, target]]}


@pytest.mark.parametrize("after,held", [
    (_after(), True),
    (_after(ids=()), False),                       # labels dropped
    (_after(ids=("3102",)), False),                # not the dialog's first row
    (_after(ids=("3101", "3102")), False),         # one more than was ticked
    (_after(days=None), False),                    # expiry dropped
    (_after(days=3), False),
    (_after(target=None), False),                  # target dropped
    (_after(target=10.0), False),
    (_after(text="someone else's"), False),        # not the run's post
    (_after(labels=()), False),                    # no label to have ticked
])
def test_effect_table(after, held):
    before = {"labels": after["labels"], "posts": []}
    assert phase2.post_extras_held(before, after) is held


def test_effect_needs_exactly_one_new_post():
    before = {"labels": [["3101", "Label 3"]], "posts": []}
    two = {"labels": before["labels"], "posts": [["8", MARK, ["3101"], 7, 25.0], ["9", MARK, ["3101"], 7, 25.0]]}
    assert not phase2.post_extras_held(before, two)
    assert phase2.find_marked_post(before["posts"], two["posts"], MARK) is None
    assert not phase2.post_extras_held(before, before)


def _queue(*posts):
    """OF's `GET /schedules` answer (app/lib/__fixtures__/of/queue-schedules-2026-11.json): queue rows, each post in
    `entity`, no `hasMore`."""
    return {"list": [{"id": 700 + i, "type": "post", "entity": p} for i, p in enumerate(posts)], "syncInProcess": False}


def test_read_tolerates_bare_label_ids_and_unticked_states():
    pages = {"/api2/v2/labels": {"list": [{"id": "archived", "name": "Archive"}, {"id": 4, "name": "x"}]},
             "/api2/v2/schedules": _queue(
                 {"id": 1, "rawText": "a", "labelStates": [4, {"id": 5, "isAdded": False}],
                  "postedAt": "2026-12-01T10:00:00+00:00", "expiredAt": "2026-12-08T10:00:00+00:00",
                  "fundRaising": {"target": "25.00"}},
                 {"id": 2, "text": "b", "fundRaising": None, "expiredAt": None})}
    got = phase2.read_post_extras(lambda path, q: pages[path], None)
    assert got == {"labels": [["4", "x"]], "posts": [["1", "a", ["4"], 7, 25.0], ["2", "b", [], None, None]]}


def test_a_bare_post_row_raises():
    pages = {"/api2/v2/labels": {"list": []},
             "/api2/v2/schedules": {"list": [{"id": 1, "type": "post", "rawText": MARK}], "syncInProcess": False}}
    with pytest.raises(ValueError, match="without `entity`"):
        phase2.read_post_extras(lambda path, q: pages[path], None)


def test_the_proof_starts_live_with_the_reader_and_runs_fake():
    assert live_refusal(PROOF, "live", None) is None   # ticket 11: the live reader is built
    assert live_refusal(PROOF, "fake", None) is None
