import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from proof_core import PACE, Proof, Write

QID, SID, MID, POST, MEDIA = "900060000000001", "900050000000001", "900010000000019", "900070000000001", "900020000000101"
FAN = "555"
LOOPBACK = ("127.0.0.1", 50000)
SEND_NOW, UPLOAD = "queue--send-message-right-now", "new-post--upload"


@pytest.fixture
def relay(tmp_path, monkeypatch):
    monkeypatch.setenv("OFM_PROOF_EVIDENCE", str(tmp_path))
    monkeypatch.setenv("OF_API_ORIGIN", "http://127.0.0.1:9")
    sys.modules.pop("relay_live", None)
    import relay_live
    yield relay_live
    sys.modules.pop("relay_live", None)


def _app(relay, answers, reads=None, client=LOOPBACK):
    def of_get(request, path, params):
        if reads is not None:
            reads.append((path, params))
        got = answers.get(path)
        if callable(got):
            got = got()
        if isinstance(got, Exception):
            raise got
        return got
    app = FastAPI()
    relay.proof_routes(app, of_get)
    return TestClient(app, client=client)


def _arm(c, relay, proof, source=None, arm=0):
    assert c.post("/__proof/arm", json={"proof": proof, "of": "fake", "proof_fan": FAN}).status_code == 200
    if source is not None:
        relay._run = replace(relay._run, created=frozenset({source}), created_by={arm: frozenset({source})})
        relay.append_jsonl(relay.UNDO, {"row": 1, "proof": proof, "state": "pending", "arm": arm, "of_id": source,
                                        "write": {"method": "POST", "path": "/x"}})


def _lines(relay):
    return [json.loads(x) for x in (relay.EVIDENCE / "wire.jsonl").read_text().splitlines() if '"read-id"' in x]


def _reg(c, key, of_id, source, **more):
    return c.post("/__proof/read-id", json={"key": key, "of_id": of_id, "source": source, **more})


SCHEDULES = {"/api2/v2/schedules": {"list": [{"id": int(SID), "type": "chat", "entity": {"id": int(QID)}}]}}


def test_read_id_registers_once_the_relay_read_shows_it(relay):
    reads = []
    c = _app(relay, SCHEDULES, reads)
    _arm(c, relay, SEND_NOW, QID)
    r = _reg(c, "schedule", SID, QID)
    assert r.status_code == 200, r.text
    assert relay._run.keys["schedule"] == frozenset({SID}) and SID not in relay._run.created
    assert reads[0][0] == "/api2/v2/schedules" and reads[0][1]["filter[timeZone]"] == "UTC"
    (line,) = _lines(relay)
    assert (line["verdict"], line["method"], line["path"], line["status"], line["origin"], line["phase"]) == \
        ("read-id", "READ-ID", "/__proof/read-id", 200, "proof-read-id", "done")
    assert line["body"] == {"key": "schedule", "of_id": SID, "source": QID} and line["proof"] == SEND_NOW


@pytest.mark.parametrize("key, of_id, answers", [
    ("schedule", SID, {"/api2/v2/schedules": {"list": [{"id": int(SID), "entity": {"id": 1}}]}}),
    ("schedule", SID, {"/api2/v2/schedules": {"list": []}}),
    ("message", MID, {f"/api2/v2/chats/{FAN}/messages": {"list": [{"id": int(MID), "queueId": 1}]}}),
    ("schedule", SID, {"/api2/v2/schedules": RuntimeError("403 refused")}),
], ids=["entity mismatch", "not listed", "queueId mismatch", "read refused"])
def test_read_id_refuses_what_the_sources_own_read_does_not_show(relay, key, of_id, answers):
    c = _app(relay, answers)
    _arm(c, relay, SEND_NOW, QID)
    r = _reg(c, key, of_id, QID)
    assert r.status_code == 409 and relay._run.keys == {}
    assert [x["status"] for x in _lines(relay)] == [409]


def test_read_id_refuses_a_media_id_not_on_the_posts_own_read(relay):
    c = _app(relay, {f"/api2/v2/posts/{POST}": {"id": int(POST), "media": [{"id": 1}]}})
    _arm(c, relay, UPLOAD, POST, arm=3)
    assert _reg(c, "media", MEDIA, POST).status_code == 409 and relay._run.keys == {}


def test_read_id_refuses_a_source_not_created_before_any_read(relay):
    reads = []
    c = _app(relay, SCHEDULES, reads)
    _arm(c, relay, SEND_NOW)
    relay.append_jsonl(relay.UNDO, {"row": 1, "proof": SEND_NOW, "state": "pending", "arm": 0, "of_id": QID})
    r = _reg(c, "schedule", SID, QID)
    assert r.status_code == 409 and "not created" in r.json()["detail"] and relay._run.keys == {} and reads == []


def test_read_id_refuses_a_source_no_pending_row_of_the_armed_proof_names(relay):
    c = _app(relay, SCHEDULES)
    _arm(c, relay, SEND_NOW)
    relay._run = replace(relay._run, created=frozenset({QID}), created_by={0: frozenset({QID})})
    assert _reg(c, "schedule", SID, QID).status_code == 409 and relay._run.keys == {}


def test_read_id_refuses_a_second_registration_of_the_same_source_and_kind(relay):
    other = {"/api2/v2/schedules": {"list": [*SCHEDULES["/api2/v2/schedules"]["list"],
                                              {"id": 900050000000009, "entity": {"id": int(QID)}}]}}
    c = _app(relay, other)
    _arm(c, relay, SEND_NOW, QID)
    assert _reg(c, "schedule", SID, QID).status_code == 200
    r = _reg(c, "schedule", "900050000000009", QID)
    assert r.status_code == 409 and "already" in r.json()["detail"]
    assert relay._run.keys["schedule"] == frozenset({SID})
    assert _reg(c, "schedule", SID, QID).status_code == 409
    _arm(c, relay, SEND_NOW, QID)
    assert _reg(c, "schedule", SID, QID).status_code == 200


def test_read_id_refuses_an_unknown_or_undeclared_kind(relay):
    c = _app(relay, {f"/api2/v2/posts/{QID}": {"media": [{"id": int(SID)}]}, **SCHEDULES})
    _arm(c, relay, SEND_NOW, QID)
    r = _reg(c, "post-media", SID, QID)
    assert r.status_code == 409 and "not a kind" in r.json()["detail"]
    assert _reg(c, "media", SID, QID).status_code == 409
    _arm(c, relay, "vault--customize-order-save", QID)
    assert _reg(c, "schedule", SID, QID).status_code == 409
    assert relay._run.keys == {} and [x["status"] for x in _lines(relay)] == [409, 409, 409]


def test_read_id_refuses_a_declared_kind_the_relay_cannot_verify(relay):
    reads = []
    c = _app(relay, SCHEDULES, reads)
    _arm(c, relay, SEND_NOW, QID)
    odd = Proof(id="x.odd", phase=6, page="queue/index", control="x", kind="live", arm=(Write("POST", "/api2/v2/lists"),),
                effect=lambda b, a: True, undo=(Write("DELETE", "/api2/v2/lists/{id}", relay="/r/{id}"),),
                binds=frozenset({"list"}))
    relay._run = replace(relay._run, proof=odd)
    relay.append_jsonl(relay.UNDO, {"row": 1, "proof": "x.odd", "state": "pending", "arm": 0, "of_id": QID})
    r = _reg(c, "list", SID, QID)
    assert r.status_code == 409 and "no read" in r.json()["detail"] and reads == [] and relay._run.keys == {}


def test_read_id_refuses_when_the_armed_proof_changed_during_the_read(relay):
    box = {}

    def rearm():
        box["c"].post("/__proof/arm", json={"proof": None})
        return SCHEDULES["/api2/v2/schedules"]
    c = box["c"] = _app(relay, {"/api2/v2/schedules": rearm})
    _arm(c, relay, SEND_NOW, QID)
    r = _reg(c, "schedule", SID, QID)
    assert r.status_code == 409 and "changed" in r.json()["detail"] and relay._run.keys == {}


def test_read_id_refuses_a_non_loopback_caller(relay):
    c = _app(relay, SCHEDULES, client=("203.0.113.5", 50000))
    relay._run = replace(relay._run, proof=relay.ALL[SEND_NOW], created=frozenset({QID}), created_by={0: frozenset({QID})})
    r = _reg(c, "schedule", SID, QID)
    assert r.status_code == 403 and relay._run.keys == {}
    (line,) = _lines(relay)
    assert (line["status"], line["reason"], line["body"]["of_id"], line["proof"]) == \
        (403, "proof hooks are loopback-only", SID, SEND_NOW)
    assert c.post("/__proof/arm", json={"proof": None}).status_code == 403


def test_read_id_message_and_media_reads(relay):
    c = _app(relay, {f"/api2/v2/chats/{FAN}/messages": {"list": [{"id": int(MID), "queueId": int(QID)}]},
                     f"/api2/v2/posts/{POST}": {"id": int(POST), "media": [{"id": int(MEDIA)}]}})
    _arm(c, relay, SEND_NOW, QID)
    assert _reg(c, "message", MID, QID).status_code == 200 and relay._run.keys["message"] == frozenset({MID})
    _arm(c, relay, UPLOAD, POST, arm=3)
    assert _reg(c, "media", MEDIA, POST, row=1).status_code == 200 and relay._run.keys["media"] == frozenset({MEDIA})


@pytest.mark.parametrize("kind, oid, source, body, want", [
    ("schedule", "9", "3", {"list": [{"id": 9, "entity": {"id": 3}}]}, True),
    ("schedule", "9", "3", {"list": [{"id": 9, "entity": {"id": 4}}]}, False),
    ("schedule", "9", "3", {"list": [{"id": 8, "entity": {"id": 3}}]}, False),
    ("message", "7", "3", {"list": [{"id": 7, "queueId": 3}]}, True),
    ("message", "7", "3", {"list": [{"id": 7}]}, False),
    ("media", "5", "2", {"media": [{"id": 5}, {"id": 6}]}, True),
    ("media", "5", "2", {"media": [{"id": 6}]}, False),
    ("media", "5", "2", None, False),
    ("other", "5", "2", {"list": [{"id": 5, "queueId": 2}]}, False),
])
def test_read_id_matches(relay, kind, oid, source, body, want):
    assert relay.read_id_matches(kind, oid, source, body) is want



def test_arm_refuses_a_quiet_hour_outside_fake_mode(relay, monkeypatch):
    c = _app(relay, {})
    qh = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc).isoformat()
    assert c.post("/__proof/arm", json={"proof": None, "quiet_hour": qh}).status_code == 200
    assert relay._run.quiet_hour == datetime.fromisoformat(qh)
    monkeypatch.setattr(relay, "_FAKE", "")
    for body in ({"proof": None, "quiet_hour": qh}, {"proof": None, "of": "fake", "quiet_hour": qh}):
        assert c.post("/__proof/arm", json=body).status_code == 400
    assert c.post("/__proof/arm", json={"proof": None, "of": "live"}).status_code == 200



def test_pacing_loops_until_the_full_pace_when_sleep_wakes_early(relay, monkeypatch):
    clock = [datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)]
    slept = []

    def sleep(s):
        slept.append(s)
        clock[0] += timedelta(seconds=max(s - 0.0002, 0.0001))

    monkeypatch.setattr(relay, "_now", lambda: clock[0])
    monkeypatch.setattr(relay.time, "sleep", sleep)
    relay._run = replace(relay._run, proof=relay.ALL["tracer.create-list"])
    relay._last_write = clock[0]
    entry, v, _ = relay._intent("relay", "POST", "https://onlyfans.com/api2/v2/lists", {"name": "oi-proof-x"})
    assert v.kind == "allow", v
    assert len(slept) >= 2
    assert datetime.fromisoformat(entry["time"]) - datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc) >= PACE



def _post_row(relay, text="oi-proof-r upload", path="/api2/v2/posts"):
    relay._wire[77] = {"seq": 77, "body": {"text": text, "mediaFiles": [1]}}
    relay.append_jsonl(relay.UNDO, {"row": 4, "proof": UPLOAD, "state": "pending", "arm": 3, "of_id": None,
                                    "wire_seq": 77, "write": {"method": "POST", "path": path}})


@pytest.mark.parametrize("read, path, want", [
    ({"id": 1, "text": "<p>oi-proof-r upload</p>", "rawText": "oi-proof-r upload"}, "/api2/v2/posts", 200),
    ({"id": 1, "rawText": "an operator's post"}, "/api2/v2/posts", 409),
    ({"id": 1, "rawText": "oi-proof-r upload!"}, "/api2/v2/posts", 409),
    (RuntimeError("404"), "/api2/v2/posts", 409),
    (None, "/api2/v2/vault/lists/sort", 409),
], ids=["sent text", "another post", "near miss", "read failed", "no read-back"])
def test_found_takes_a_post_id_only_when_the_relay_read_shows_the_sent_text(relay, read, path, want):
    reads = []
    c = _app(relay, {f"/api2/v2/posts/{POST}": read}, reads)
    _arm(c, relay, UPLOAD)
    _post_row(relay, path=path)
    r = c.post("/__proof/found", json={"row": 4, "of_id": POST})
    assert r.status_code == want, r.text
    assert (POST in relay._run.created) is (want == 200)
    assert [p for p, _ in reads] == ([] if path != "/api2/v2/posts" else [f"/api2/v2/posts/{POST}"])


_QUEUE_READ = (f"/api2/v2/messages/queue/{QID}", {"format": "scheduled"})
_FOLDER_READ = (f"/api2/v2/vault/lists/{QID}", {})
_TRIALS_READ = ("/api2/v2/trials", {"offset": 0, "limit": 100})
_MINE = {"id": int(QID), "trialLinkName": "oi-proof-r", "subscribeDays": 1}
_OTHER = {"id": 6201, "trialLinkName": "Alpha trial", "subscribeDays": 1}


@pytest.mark.parametrize("path, sent, answers, want, read", [
    ("/api2/v2/messages/queue", {"text": "oi-proof-r"},
     {_QUEUE_READ[0]: {"id": int(QID), "text": "oi-proof-r", "rawText": "oi-proof-r"}}, 200, [_QUEUE_READ]),
    ("/api2/v2/messages/queue", {"text": "oi-proof-r"},
     {_QUEUE_READ[0]: {"id": int(QID), "text": "an operator's message", "rawText": "an operator's message"}}, 409,
     [_QUEUE_READ]),
    ("/api2/v2/messages/queue", {"text": "oi-proof-r"}, {_QUEUE_READ[0]: RuntimeError("404")}, 409, [_QUEUE_READ]),
    ("/api2/v2/messages/queue", {"userIds": [1]}, {}, 409, []),
    ("/api2/v2/lists", {"name": "oi-proof-r"}, {f"/api2/v2/lists/{QID}": {"id": int(QID), "name": "oi-proof-r"}}, 200,
     [(f"/api2/v2/lists/{QID}", {})]),
    ("/api2/v2/lists", {"name": "oi-proof-r"}, {f"/api2/v2/lists/{QID}": {"id": int(QID), "name": "Whales"}}, 409,
     [(f"/api2/v2/lists/{QID}", {})]),
    ("/api2/v2/vault/lists", {"name": "oi-proof-r"},
     {_FOLDER_READ[0]: {"id": int(QID), "type": "custom", "name": "oi-proof-r"}}, 200, [_FOLDER_READ]),
    ("/api2/v2/vault/lists", {"name": "oi-proof-r"},
     {_FOLDER_READ[0]: {"id": int(QID), "type": "custom", "name": "Soak folder 1"}}, 409, [_FOLDER_READ]),
    ("/api2/v2/vault/lists", {"name": "oi-proof-r"}, {_FOLDER_READ[0]: RuntimeError("404")}, 409, [_FOLDER_READ]),
    ("/api2/v2/trials", {"trialLinkName": "oi-proof-r"}, {_TRIALS_READ[0]: [_MINE, _OTHER]}, 200, [_TRIALS_READ]),
    ("/api2/v2/trials", {"trialLinkName": "oi-proof-r"},
     {_TRIALS_READ[0]: {"list": [_OTHER, _MINE], "hasMore": False}}, 200, [_TRIALS_READ]),
    ("/api2/v2/trials", {"trialLinkName": "oi-proof-r"},
     {_TRIALS_READ[0]: [{**_MINE, "trialLinkName": "an operator's link"}]}, 409, [_TRIALS_READ]),
    ("/api2/v2/trials", {"trialLinkName": "oi-proof-r"}, {_TRIALS_READ[0]: [_OTHER]}, 409, [_TRIALS_READ]),
    ("/api2/v2/trials", {"trialLinkName": "oi-proof-r"}, {_TRIALS_READ[0]: [_MINE, dict(_MINE)]}, 409,
     [_TRIALS_READ]),
    ("/api2/v2/trials", {"trialLinkName": "oi-proof-r"}, {_TRIALS_READ[0]: RuntimeError("500")}, 409, [_TRIALS_READ]),
    ("/api2/v2/trials", {"subscribeDays": 1}, {}, 409, []),
    ("/api2/v2/trials", {"trialLinkName": ""}, {_TRIALS_READ[0]: [{**_MINE, "trialLinkName": ""}]}, 409, []),
    ("/api2/v2/vault/lists", {"name": ""}, {_FOLDER_READ[0]: {"id": int(QID), "type": "custom", "name": ""}}, 409, []),
    ("/api2/v2/vault/lists/sort", {"sort": "name", "order": "asc"}, {}, 409, []),
], ids=["queue sent text", "queue foreign item", "queue read failed", "queue body no text", "list sent name",
        "list foreign", "folder sent name", "folder name mismatch", "folder read failed", "trial own row",
        "trial own row, paged answer", "trial name mismatch", "trial foreign id (not listed)", "trial id twice",
        "trial read failed", "trial body no name", "trial empty name sent", "folder empty name sent",
        "no read-back: refused"])
def test_found_reads_back_by_create_path_and_refuses_the_rest(relay, path, sent, answers, want, read):
    reads = []
    c = _app(relay, answers, reads)
    _arm(c, relay, SEND_NOW)
    relay._wire[77] = {"seq": 77, "body": sent}
    relay.append_jsonl(relay.UNDO, {"row": 4, "proof": SEND_NOW, "state": "pending", "arm": 0, "of_id": None,
                                    "wire_seq": 77, "write": {"method": "POST", "path": path}})
    r = c.post("/__proof/found", json={"row": 4, "of_id": QID})
    assert r.status_code == want, r.text
    assert (QID in relay._run.created) is (want == 200)
    found = [x for x in relay.read_undo_log(relay.UNDO) if x.get("found_by")]
    assert [x["of_id"] for x in found] == ([QID] if want == 200 else [])
    assert reads == read


_SOCIAL, _LINKS = "/api2/v2/users/social/buttons", "/api2/v2/users/links"
_BLOCKED_READ = ("/api2/v2/streams/users/blocked", {"limit": 50})
_BTN = {"id": int(QID), "socialMedia": "instagram", "label": "oi-proof-r", "link": "", "username": "instagram"}
_BTN_OTHER = {"id": 6901, "socialMedia": "x", "label": "My X", "link": "", "username": "someone"}
_YT = "https://www.youtube.com/watch?v=oi-proof-r"
_LINK, _LINK_OTHER = {"id": int(QID), "sort": 0, "url": _YT}, {"id": 6902, "sort": 1, "url": "https://example.org/"}
_BLOCK, _BLOCK_OTHER = {"id": int(QID), "username": "fan_r"}, {"id": 6903, "username": "fan_q"}


@pytest.mark.parametrize("path, sent, answers, want, read", [
    ("PUT " + _SOCIAL, {"label": "oi-proof-r", "username": "instagram"}, {_SOCIAL: [_BTN_OTHER, _BTN]}, 200,
     [(_SOCIAL, {})]),
    ("PUT " + _SOCIAL, {"label": "oi-proof-r"}, {_SOCIAL: [{**_BTN, "label": "My IG"}]}, 409, [(_SOCIAL, {})]),
    ("PUT " + _SOCIAL, {"label": "oi-proof-r"}, {_SOCIAL: [_BTN_OTHER]}, 409, [(_SOCIAL, {})]),
    ("PUT " + _SOCIAL, {"label": "oi-proof-r"}, {_SOCIAL: [_BTN, dict(_BTN)]}, 409, [(_SOCIAL, {})]),
    ("PUT " + _SOCIAL, {"label": ""}, {_SOCIAL: [{**_BTN, "label": ""}]}, 409, []),
    ("PUT " + _LINKS, {"link": _YT}, {_LINKS: [_LINK_OTHER, _LINK]}, 200, [(_LINKS, {})]),
    ("PUT " + _LINKS, {"link": _YT}, {_LINKS: [{**_LINK, "url": "https://example.org/x"}]}, 409, [(_LINKS, {})]),
    ("PUT " + _LINKS, {"link": _YT}, {_LINKS: [_LINK_OTHER]}, 409, [(_LINKS, {})]),
    ("PUT " + _LINKS, {"link": _YT}, {_LINKS: [_LINK, dict(_LINK)]}, 409, [(_LINKS, {})]),
    ("POST /api2/v2/streams/users/u" + QID + "/block", None,
     {_BLOCKED_READ[0]: {"list": [_BLOCK, _BLOCK_OTHER], "hasMore": False}}, 200, [_BLOCKED_READ]),
    ("POST /api2/v2/streams/users/fan_r/block", None, {_BLOCKED_READ[0]: {"list": [_BLOCK], "hasMore": False}}, 200,
     [_BLOCKED_READ]),
    ("POST /api2/v2/streams/users/u6903/block", None,
     {_BLOCKED_READ[0]: {"list": [_BLOCK, _BLOCK_OTHER], "hasMore": False}}, 409, [_BLOCKED_READ]),
    ("POST /api2/v2/streams/users/u" + QID + "/block", None,
     {_BLOCKED_READ[0]: {"list": [_BLOCK_OTHER], "hasMore": False}}, 409, [_BLOCKED_READ]),
    ("POST /api2/v2/streams/users/u" + QID + "/block", None,
     {_BLOCKED_READ[0]: {"list": [_BLOCK, dict(_BLOCK)], "hasMore": False}}, 409, [_BLOCKED_READ]),
    ("PUT /api2/v2/users/social/buttons/sort", {"ids": [1]}, {}, 409, []),
], ids=["button own row", "button label mismatch", "button foreign id (not listed)", "button id twice",
        "button empty label sent", "link own row", "link url mismatch", "link foreign id (not listed)", "link id twice",
        "block own default handle", "block own username", "block another user's handle", "block id not listed",
        "block id twice", "no read-back: refused"])
def test_found_reads_back_phase3_list_creates(relay, path, sent, answers, want, read):
    method, path = path.split(" ", 1)
    reads = []
    c = _app(relay, answers, reads)
    _arm(c, relay, SEND_NOW)
    relay._wire[77] = {"seq": 77, "body": sent}
    relay.append_jsonl(relay.UNDO, {"row": 4, "proof": SEND_NOW, "state": "pending", "arm": 0, "of_id": None,
                                    "wire_seq": 77, "write": {"method": method, "path": path}})
    r = c.post("/__proof/found", json={"row": 4, "of_id": QID})
    assert r.status_code == want, r.text
    assert (QID in relay._run.created) is (want == 200)
    assert reads == read


def test_arm_takes_the_runs_marker_for_the_payload_guards(relay):
    c = _app(relay, {})
    assert c.post("/__proof/arm", json={"proof": UPLOAD, "of": "fake", "marker": "oi-proof-r"}).status_code == 200
    assert relay._run.marker == "oi-proof-r"
    assert c.post("/__proof/arm", json={"proof": UPLOAD, "of": "fake"}).status_code == 200
    assert relay._run.marker is None


_PPV = "p2.bubble-unsend-ppv"
_THREAD_READ = (f"/api2/v2/chats/{FAN}/messages", {"limit": 10, "order": "desc"})
_OWN_PPV = {"id": int(MID), "text": "oi-proof-r ppv", "price": 3}


@pytest.mark.parametrize("answer, want", [
    ({"list": [{"id": 1, "text": "hi"}, _OWN_PPV], "hasMore": False}, 200),
    ({"list": [{**_OWN_PPV, "text": "an operator's PPV"}]}, 409),
    ({"list": [{**_OWN_PPV, "id": 7}]}, 409),
    ({"list": [_OWN_PPV, dict(_OWN_PPV)]}, 409),
    (RuntimeError("500"), 409),
], ids=["own message", "text mismatch", "id not listed", "id twice", "read failed"])
def test_found_reads_a_lost_ppv_send_back_on_the_proof_fans_thread(relay, answer, want):
    reads = []
    c = _app(relay, {_THREAD_READ[0]: answer}, reads)
    _arm(c, relay, _PPV)
    relay._wire[77] = {"seq": 77, "body": {"text": "oi-proof-r ppv", "price": 3, "mediaFiles": [1]}}
    relay.append_jsonl(relay.UNDO, {"row": 4, "proof": _PPV, "state": "pending", "arm": 0, "of_id": None,
                                    "wire_seq": 77, "write": {"method": "POST", "path": _THREAD_READ[0]}})
    r = c.post("/__proof/found", json={"row": 4, "of_id": MID})
    assert r.status_code == want, r.text
    assert (MID in relay._run.created) is (want == 200)
    assert reads == [_THREAD_READ]


@pytest.mark.parametrize("queue_row, want", [
    ({"proof": SEND_NOW, "of_id": QID}, 200),
    ({"proof": SEND_NOW, "of_id": "900060000000009"}, 409),
    ({"proof": UPLOAD, "of_id": QID}, 409),
    (None, 409),
], ids=["own queue write", "another item", "another proof", "no queue write"])
def test_found_publish_takes_only_the_queue_id_its_own_queue_write_made(relay, queue_row, want):
    reads = []
    c = _app(relay, {}, reads)
    _arm(c, relay, SEND_NOW)
    if queue_row:
        relay.append_jsonl(relay.UNDO, {"row": 1, "state": "pending", "arm": 0, "write_status": 200,
                                        "write": {"method": "POST", "path": "/api2/v2/messages/queue"}, **queue_row})
    relay.append_jsonl(relay.UNDO, {"row": 2, "proof": SEND_NOW, "state": "pending", "arm": 1, "of_id": None,
                                    "wire_seq": 78, "write": {"method": "PUT",
                                                              "path": f"/api2/v2/schedules/{SID}/publish"}})
    r = c.post("/__proof/found", json={"row": 2, "of_id": QID})
    assert r.status_code == want, r.text
    assert reads == []
