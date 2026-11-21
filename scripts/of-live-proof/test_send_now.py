"""Ticket 100: the Send now proof (proofs/phase6.py `QUEUE_SEND_NOW`): the Live guard on its writes, its pure
helpers, FakeOF's message queue (soak/fake_of/queue.py) with the planted faults (fake_layer), the driver's undo
fallback chain (undo_driver `settle_rows`, ticket 131's registration through `/__proof/read-id`), and every proof's
post and queue writes judged fan-visible unless scheduled far enough ahead (moved from test_proof_core: file size).
"""
import time
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

import fake_layer
import undo_driver
from proof_core import NOT_REVERSIBLE_REFUSED, POST_LEAD, Request, Run, decide
import proof_core
from proofs import phase6_writes
from proofs.phase6 import (QUEUE_LEAD, QUEUE_SEND_NOW, audience_problem, find_queued, queue_send_effect, queue_when,
                           read_fan_and_queue, released_message, send_now)
from soak import ids
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World

AT = datetime(2026, 11, 21, 3, 10, tzinfo=timezone.utc)
QUIET = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
FAN = "555"
QID, SID, MID = "900060000000001", "900050000000001", "900010000000019"


def R(method, path, body=None):
    return Request(method=method, host="onlyfans.com", path=path, body=body, at=AT)


def queue_body(**kw):
    return {"text": "oi-proof-x", "userIds": [555], "userLists": [], "price": 0,
            "scheduledDate": (AT + timedelta(minutes=30)).isoformat(), **kw}


ARMED = dict(proof=QUEUE_SEND_NOW, proof_fan=FAN, quiet_hour=QUIET)


# ── the Live guard ──

@pytest.mark.parametrize("why, request_, run, kind", [
    ("queue to the Proof fan alone", R("POST", "/api2/v2/messages/queue", queue_body()), Run(**ARMED), "allow"),
    ("queue with an OF list", R("POST", "/api2/v2/messages/queue", queue_body(userLists=["fans"])), Run(**ARMED),
     "refused"),
    ("queue to a second Fan", R("POST", "/api2/v2/messages/queue", queue_body(userIds=[555, 556])), Run(**ARMED),
     "refused"),
    ("queue with no Proof fan", R("POST", "/api2/v2/messages/queue", queue_body()),
     Run(proof=QUEUE_SEND_NOW, quiet_hour=QUIET), "refused"),
    ("queue scheduled under POST_LEAD ahead", R("POST", "/api2/v2/messages/queue",
                                                queue_body(scheduledDate=(AT + timedelta(minutes=29)).isoformat())),
     Run(**ARMED), "refused"),
    ("publish of an unregistered schedule", R("PUT", f"/api2/v2/schedules/{SID}/publish"),
     Run(**ARMED, spent={("arm", 0): 1}, created=frozenset({QID})), "refused"),
    ("publish of a schedule registered as another kind", R("PUT", f"/api2/v2/schedules/{SID}/publish"),
     Run(**ARMED, spent={("arm", 0): 1}, created=frozenset({QID}), keys={"message": frozenset({SID})}), "refused"),
    ("publish of the registered schedule", R("PUT", f"/api2/v2/schedules/{SID}/publish"),
     Run(**ARMED, spent={("arm", 0): 1}, created=frozenset({QID}), keys={"schedule": frozenset({SID})}), "allow"),
    ("queue unsend of its own item", R("DELETE", f"/api2/v2/messages/queue/{QID}"),
     Run(**ARMED, spent={("arm", 0): 1, ("arm", 1): 1}, created=frozenset({QID})), "reversal"),
    ("queue unsend of an item not created", R("DELETE", f"/api2/v2/messages/queue/{SID}"),
     Run(**ARMED, spent={("arm", 0): 1, ("arm", 1): 1}, created=frozenset({QID})), "refused"),
    ("chat unsend of an unregistered message", R("DELETE", f"/api2/v2/messages/{MID}", {"withUserId": 555}),
     Run(**ARMED, spent={("arm", 0): 1, ("arm", 1): 1}, created=frozenset({QID})), "refused"),
    ("chat unsend of a created, unregistered id", R("DELETE", f"/api2/v2/messages/{QID}", {"withUserId": 555}),
     Run(**ARMED, spent={("arm", 0): 1, ("arm", 1): 1}, created=frozenset({QID})), "refused"),
    ("chat unsend of the registered message", R("DELETE", f"/api2/v2/messages/{MID}", {"withUserId": 555}),
     Run(**ARMED, spent={("arm", 0): 1, ("arm", 1): 1}, created=frozenset({QID}), keys={"message": frozenset({MID})}),
     "reversal"),
], ids=lambda x: x if isinstance(x, str) else "")
def test_guard_on_send_now_writes(why, request_, run, kind):
    v = decide(request_, run)
    assert v.kind == kind, (why, v)


def test_guard_counts_the_publish_fan_visible_and_not_the_scheduled_queue():
    assert decide(R("PUT", f"/api2/v2/schedules/{SID}/publish"),
                  Run(**ARMED, spent={("arm", 0): 1}, created=frozenset({QID}),
                      keys={"schedule": frozenset({SID})})).fan_visible
    assert not decide(R("POST", "/api2/v2/messages/queue", queue_body()), Run(**ARMED)).fan_visible


# ── the proof's pure helpers ──

@pytest.mark.parametrize("audience, bad", [
    ({"userIds": ["555"], "userLists": []}, None),
    ({"userIds": [555]}, None),
    ({"userIds": ["555"], "userLists": ["fans"]}, "lists ['fans']"),
    ({"userIds": ["555", "556"], "userLists": []}, "not the Proof fan 555 alone"),
    ({"userIds": [], "userLists": []}, "not the Proof fan 555 alone"),
])
def test_audience_problem(audience, bad):
    why = audience_problem(audience, FAN)
    assert (why is None) if bad is None else (bad in why)


BEFORE = {"chat": [["1", "<p>history</p>", None]], "queue": []}
QUEUED = {"chat": BEFORE["chat"], "queue": [[SID, QID]]}
SENT = {"chat": [[MID, "oi-proof-run", QID], *BEFORE["chat"]], "queue": []}


def test_effect_find_and_released_message():
    assert not queue_send_effect(BEFORE, BEFORE)
    assert queue_send_effect(BEFORE, QUEUED) and queue_send_effect(BEFORE, SENT)
    assert find_queued(BEFORE, SENT, "oi-proof-run") == QID
    assert find_queued(BEFORE, QUEUED, "oi-proof-run") == QID
    assert find_queued(BEFORE, BEFORE, "oi-proof-run") is None
    assert released_message(SENT, QID, FAN) == {"message": MID}
    assert released_message(QUEUED, QID, FAN) == {"message": None}


def test_read_fan_and_queue_keeps_chat_items_only():
    def get(path, params):
        if path.startswith("/api2/v2/chats/"):
            return {"list": [{"id": 7, "text": "oi-proof-r", "queueId": 3}, {"id": 6, "text": None}]}
        return {"list": [{"id": 9, "type": "chat", "entity": {"id": 3}}, {"id": 8, "type": "post", "entity": {"id": 2}}]}
    assert read_fan_and_queue(get, FAN) == {"chat": [["7", "oi-proof-r", "3"], ["6", "", None]], "queue": [["9", "3"]]}
    assert read_fan_and_queue(get, None)["chat"] == []


# ── FakeOF's queue and the planted faults ──

@pytest.fixture
def fake():
    def make(fault=None):
        of = FakeOF(World(1))
        of.port = 1
        client = TestClient(fake_layer.Recorder(of.build(), fault, of))

        def req(method, path, tagged=False, **kw):
            t, uid = str(int(time.time() * 1000)), str(of.world.creator_id)
            h = {"user-id": uid, "x-hash": of.x_hash, "time": t,
                 "sign": sign_value(of.rules, time_ms=t, path_qs=path, user_id=uid),
                 **({fake_layer.TAG: "1"} if tagged else {})}
            r = client.request(method, path, headers=h, **kw)
            return r.status_code, r.json()
        return of, req
    return make


def _queue(req, fan, **kw):
    when = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    return req("POST", "/api2/v2/messages/queue",
               json={"text": "oi-proof-t", "userIds": [fan], "userLists": [], "scheduledDate": when, "price": 0, **kw})


def _chat(req, fan):
    return req("GET", f"/api2/v2/chats/{fan}/messages?limit=5&order=desc")[1]["list"]


def test_fake_queue_publish_then_unsend(fake):
    of, req = fake()
    fan = ids.fan_id(1)
    status, item = _queue(req, fan)
    assert status == 200 and item["userIds"] == [str(fan)] and "userLists" not in item
    qid = item["id"]
    assert not any("oi-proof-t" in str(m["text"]) for m in _chat(req, fan))   # scheduled: reaches no Fan yet
    assert req("GET", f"/api2/v2/messages/queue/{qid}?format=scheduled")[1]["userIds"] == [str(fan)]
    rows = req("GET", "/api2/v2/schedules?limit=50")[1]["list"]
    assert [(r["id"], r["entity"]["queueId"]) for r in rows] == [(ids.schedule_id(1), qid)]
    assert req("PUT", f"/api2/v2/schedules/{ids.schedule_id(1)}/publish") == (200, {"success": True})
    sent = [m for m in _chat(req, fan) if m["text"] == "oi-proof-t"]
    assert len(sent) == 1 and sent[0]["queueId"] == qid and sent[0]["isFromQueue"]
    assert req("GET", "/api2/v2/schedules?limit=50")[1]["list"] == []
    assert req("DELETE", f"/api2/v2/messages/queue/{qid}") == (200, {"success": True})
    assert not any(m["text"] == "oi-proof-t" for m in _chat(req, fan))


def test_fake_schedules_day_filter_and_chat_unsend(fake):
    of, req = fake()
    fan = ids.fan_id(1)
    _queue(req, fan)
    far = (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()
    assert req("GET", f"/api2/v2/schedules?filter[publishDate]={far}")[1]["list"] == []
    req("PUT", f"/api2/v2/schedules/{ids.schedule_id(1)}/publish")
    mid = next(m["id"] for m in _chat(req, fan) if m["text"] == "oi-proof-t")
    assert req("DELETE", f"/api2/v2/messages/{mid}") == (200, {"success": True})
    assert req("DELETE", f"/api2/v2/messages/{mid}")[0] == 404


@pytest.mark.parametrize("fault, field, planted", [
    ("audience-list", "userLists", ["fans"]),
    ("audience-second", "userIds", [str(ids.fan_id(1)), str(ids.fan_id(2))]),
])
def test_audience_faults_plant_into_the_item_read_only(fake, fault, field, planted):
    of, req = fake(fault)
    fan = ids.fan_id(1)
    status, item = _queue(req, fan)
    assert status == 200 and item["userIds"] == [str(fan)]   # the POST answer is untouched
    assert req("GET", f"/api2/v2/messages/queue/{item['id']}")[1][field] == planted
    # the driver's own tagged read (send_now reads the audience with of_get) sees the fault too
    assert req("GET", f"/api2/v2/messages/queue/{item['id']}?format=scheduled", tagged=True)[1][field] == planted


def test_queue_500_foreign_queues_another_users_item_not_ours(fake):
    """queue-500-foreign (review 1): the queue write answered 500 unapplied while another user's item lands in the
    queue; the one new queued item is the foreign one, whose own read shows its text, never the run's."""
    of, req = fake("queue-500-foreign")
    before = req("GET", "/api2/v2/schedules?limit=50")[1]["list"]
    status, _ = _queue(req, ids.fan_id(1))
    assert status == 500
    rows = req("GET", "/api2/v2/schedules?limit=50")[1]["list"]
    assert len(rows) == len(before) + 1
    qid = rows[-1]["entity"]["queueId"]
    item = req("GET", f"/api2/v2/messages/queue/{qid}?format=scheduled", tagged=True)[1]
    assert item["rawText"] == fake_layer.FOREIGN_QUEUE_TEXT != "oi-proof-t"
    assert item["userIds"] == [str(ids.fan_id(2))]


# ── send_now before the click: the midnight park, the driver's own audience and schedule reads ──

def test_queue_when_parks_across_utc_midnight():
    assert QUEUE_LEAD > proof_core.POST_LEAD   # the guard refuses a queue write under POST_LEAD ahead
    noon = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    assert queue_when(noon) == noon + QUEUE_LEAD
    late = datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc) - QUEUE_LEAD
    assert queue_when(late) == late + QUEUE_LEAD
    assert queue_when(late + timedelta(minutes=2)) is None


class _Stop(Exception):
    pass


def _send_ctx(of_get):
    calls = []

    def call(method, route, data=None):
        calls.append((method, route, data))
        return 200, b'{"id": 3}'

    def park(why):
        calls.append(("park", why))
        raise _Stop(why)

    def reload():
        raise _Stop("reloaded")

    return calls, {"record": {}, "proof_fan": FAN, "call": call, "marker": "oi-proof-r", "of_get": of_get,
                   "park": park, "reload": reload,
                   "read_id": lambda key, of_id, source: calls.append(("read_id", key, of_id, source)) or []}


def test_send_now_parks_unqueued_when_the_lead_crosses_midnight(monkeypatch):
    monkeypatch.setattr(phase6_writes, "queue_when", lambda now: None)
    calls, ctx = _send_ctx(lambda path, q: pytest.fail("no read"))
    with pytest.raises(_Stop, match="crosses UTC midnight"):
        send_now(ctx)
    assert [c[0] for c in calls] == ["park"]   # nothing queued


def test_send_now_reads_the_audience_itself_and_stops_on_a_list():
    reads = []

    def of_get(path, q):
        reads.append((path, q))
        return {"userIds": [555], "userLists": ["fans"]}
    calls, ctx = _send_ctx(of_get)
    out = send_now(ctx)
    assert len(out) == 1 and "lists ['fans']" in out[0] and "Send now not clicked" in out[0]
    assert reads == [("/api2/v2/messages/queue/3", {"format": "scheduled"})]
    assert [c[0] for c in calls] == ["POST"]   # no app-side read, no registration


def _schedules_get(path, q):
    if path == "/api2/v2/schedules":
        assert q["filter[timeZone]"] == "UTC"
        return {"list": [{"id": 8, "entity": {"id": 2}}, {"id": 9, "entity": {"id": 3}}]}
    return {"userIds": [555]}


def test_send_now_stops_unclicked_when_the_relay_refuses_the_schedule():
    calls, ctx = _send_ctx(_schedules_get)
    ctx["read_id"] = lambda key, of_id, source: ["the Relay refused read id schedule=9: 409"]
    assert send_now(ctx) == ["the Relay refused read id schedule=9: 409"]   # no reload, no click


def test_send_now_registers_the_schedule_item_its_own_read_found():
    calls, ctx = _send_ctx(_schedules_get)
    with pytest.raises(_Stop, match="reloaded"):
        send_now(ctx)
    assert calls[1:] == [("read_id", "schedule", "9", "3")] and ctx["record"]["schedule"] == "9"


def test_unsend_refused_only_after_release(fake):
    of, req = fake("unsend-refused")
    fan = ids.fan_id(1)
    first = _queue(req, fan)[1]["id"]
    assert req("DELETE", f"/api2/v2/messages/queue/{first}")[0] == 200   # waiting: canceled as usual
    qid = _queue(req, fan)[1]["id"]
    req("PUT", f"/api2/v2/schedules/{ids.schedule_id(2)}/publish")
    status, body = req("DELETE", f"/api2/v2/messages/queue/{qid}")
    assert status == 400 and "unsend refused" in body["error"]["message"]
    assert any(m["text"] == "oi-proof-t" for m in _chat(req, fan))   # nothing unsent


# ── the driver's undo fallback chain ──

class Wire:
    """A stub Relay: each reversal answers from `statuses` by OnlyFans path prefix, logged as the wire log would;
    `/__proof/read-id` answers `read_id_status`."""

    def __init__(self, statuses, read_id_status=200):
        self.statuses, self.lines, self.calls, self.read_id_status = statuses, [], [], read_id_status

    def __call__(self, method, route, data=None, account=None):
        self.calls.append((method, route, data))
        if route == "/__proof/read-id":
            return self.read_id_status, b"{}"
        path = route.replace("/api/of/v2", "/api2/v2")
        status = next(s for p, s in self.statuses if path.startswith(p))
        self.lines.append({"seq": len(self.lines) + 1, "method": method, "path": path, "status": status,
                           "verdict": "reversal"})
        return (200 if status < 300 else 502), b""

    def wire(self):
        return list(self.lines)


QUEUE_DEL, CHAT_DEL = "/api2/v2/messages/queue/", "/api2/v2/messages/9"


def row(n, method="POST", path="/api2/v2/messages/queue", arm=0, of_id=QID):
    return {"row": n, "arm": arm, "write": {"method": method, "path": path}, "of_id": of_id,
            "opened": AT.isoformat()}


PUBLISH_ROW = dict(method="PUT", path=f"/api2/v2/schedules/{SID}/publish", arm=1)


def undo(w, rows, after=SENT, after_undo=BEFORE):
    res = {"problems": [], "screens": []}
    closed = undo_driver.settle_rows(QUEUE_SEND_NOW, rows, w, w.wire, lambda tag: after_undo, creator="1",
                                     before=BEFORE, after=after, effect=True, keys={}, sent={}, res=res, fan=FAN)
    return closed, res


def _read_ids(w):
    return [c[2] for c in w.calls if c[1] == "/__proof/read-id"]


def test_undo_queue_unsend_takes_it_back():
    w = Wire([(QUEUE_DEL, 200)])
    (c,), res = undo(w, [row(1)])
    assert c["state"] == "undone" and len(c["attempts"]) == 1 and res["problems"] == []
    assert c["reversals"] == c["attempts"] and _read_ids(w) == []


def test_undo_falls_back_to_the_chat_unsend_and_the_publish_row_reuses_it():
    w = Wire([(QUEUE_DEL, 400), (CHAT_DEL, 200)])
    (a, b), res = undo(w, [row(1), row(2, **PUBLISH_ROW)])
    assert [x["state"] for x in (a, b)] == ["undone", "undone"] and res["problems"] == []
    assert [t["status"] for t in a["attempts"]] == [400, 200]
    assert [r["path"] for r in a["reversals"]] == [f"/api2/v2/messages/{MID}"]
    assert _read_ids(w) == [{"row": 1, "key": "message", "of_id": MID, "source": QID}]   # once: B reuses it
    assert ("DELETE", f"/api/of/v2/messages/{MID}", {"withUserId": 555}) in w.calls
    assert b["reversals"] == a["reversals"] and b["keys"] == a["keys"] == {"message": MID}
    assert len([c for c in w.calls if c[0] == "DELETE"]) == 2   # the reuse sent no second unsend


def test_undo_refused_to_the_end_is_not_reversible_with_its_reason():
    w = Wire([(QUEUE_DEL, 400), (CHAT_DEL, 403)])
    (c,), res = undo(w, [row(1)], after_undo=SENT)
    assert c["state"] == NOT_REVERSIBLE_REFUSED
    assert "answered 400" in c["reason"] and "answered 403" in c["reason"]
    assert res["problems"] == [f"row 1: {NOT_REVERSIBLE_REFUSED}: {c['reason']}"]


def test_undo_fallback_read_id_refused_sends_no_chat_unsend():
    w = Wire([(QUEUE_DEL, 400), (CHAT_DEL, 200)], read_id_status=409)
    (c,), res = undo(w, [row(1)], after_undo=SENT)
    assert c["state"] == NOT_REVERSIBLE_REFUSED and "/__proof/read-id" in c["reason"] and "409" in c["reason"]
    assert not any(x[0] == "DELETE" and x[1].startswith("/api/of/v2/messages/9") for x in w.calls)


def test_undo_with_no_released_message_skips_the_fallback():
    w = Wire([(QUEUE_DEL, 400)])
    (c,), res = undo(w, [row(1)], after=QUEUED, after_undo=QUEUED)
    assert c["state"] == NOT_REVERSIBLE_REFUSED and "no message in the after-write read" in c["reason"]
    assert _read_ids(w) == []


def test_undo_with_no_id_sends_nothing_and_fails():
    w = Wire([(QUEUE_DEL, 200)])
    (c,), res = undo(w, [row(1, of_id=None)], after_undo=SENT)
    assert c["state"] == "FAILED" and w.calls == [] and any("no reversal" in p for p in res["problems"])


def test_a_fallback_chain_and_an_undo_sequence_are_exclusive():
    from dataclasses import replace
    with pytest.raises(ValueError, match="exclusive"):
        replace(QUEUE_SEND_NOW, undo_steps=lambda before: [])


# ── every proof's post and queue write is fan-visible unless scheduled at least POST_LEAD ahead ──

def _structural_bodies(api: str, at: datetime) -> dict:
    """Immediate, near- and far-scheduled bodies for a post or queue write."""
    def date(minutes):
        return (at + timedelta(minutes=minutes)).isoformat()
    lead = int(POST_LEAD.total_seconds() // 60)
    if api.startswith("/posts"):
        base = {"text": "oi-proof-x", "price": 0}
        return {"immediate": base, "near": {**base, "isScheduled": 1, "scheduledDate": date(1)},
                "past": {**base, "isScheduled": 1, "scheduledDate": date(-5)},
                "malformed": {**base, "isScheduled": 1, "scheduledDate": "soon"},
                "far": {**base, "isScheduled": 1, "scheduledDate": date(lead + 15)}}
    base = {"text": "oi-proof-x", "userIds": [int(FAN)], "userLists": [], "price": 0}
    return {"immediate": base, "near": {**base, "scheduledDate": date(1)},
            "past": {**base, "scheduledDate": date(-5)}, "malformed": {**base, "scheduledDate": "soon"},
            "far": {**base, "scheduledDate": date(lead + 15)}}


# Every proof whose post or queue write the guard may let through as fan-visible: the effort's two (Q15) at most.
FAN_VISIBLE_PROOFS = {"queue--send-message-right-now", "queue--publish-now"}


def test_every_proofs_post_and_queue_write_is_fan_visible_unless_far_scheduled():
    import re

    from proof_core import _POST, _QUEUE, _api
    from proofs import ALL
    can = set()
    for p in ALL.values():
        for w in p.arm:
            api = _api(w.path)
            if w.method.upper() not in ("POST", "PUT", "PATCH") or not (_POST.match(api) or _QUEUE.match(api)):
                continue
            path = re.sub(r"\{[^/{}]+\}", "77", w.path)
            for name, body in _structural_bodies(api, AT).items():
                body = {**dict(w.body_must or {}), **body}
                for of in ("live", "fake"):
                    v = decide(R(w.method, path, body), Run(proof=p, of=of, proof_fan=FAN, quiet_hour=QUIET,
                                                             created=frozenset({"77"})))
                    if v.kind == "refused":
                        continue
                    if name != "far":
                        assert v.fan_visible, f"{p.id} {w.method} {w.path} {name} ({of}): allowed, not fan-visible"
                    if v.fan_visible:
                        can.add(p.id)
    assert can == FAN_VISIBLE_PROOFS


# ── the guard's queue dates and the upload's convert host (moved from test_proof_core: file size) ──

def _queue_edit():
    return proof_core.Proof(id="p.x", phase=0, page="collections/index", control="x", kind="live",
                            arm=(proof_core.Write("PUT", "/api2/v2/messages/queue/{id}"),),
                            undo=(proof_core.Write("DELETE", "/api2/v2/lists/{id}"),), effect=lambda b, a: True)


def _at(minutes):
    return {"userIds": [555], "userLists": [], "scheduledDate": (AT + timedelta(minutes=minutes)).isoformat()}


@pytest.mark.parametrize("request_, run, kind, cls", [
    (R("POST", "/api2/v2/messages/queue", _at(29)), Run(**ARMED), "refused", "mass_message"),
    (R("POST", "/api2/v2/messages/queue", _at(-5)), Run(**ARMED), "refused", "mass_message"),
    (R("POST", "/api2/v2/messages/queue", {**_at(35), "scheduledDate": "x"}), Run(**ARMED), "refused", "mass_message"),
    (R("PUT", "/api2/v2/messages/queue/88", _at(10)),
     Run(proof=_queue_edit(), proof_fan=FAN, created=frozenset({"88"})), "refused", "mass_message"),
    # the upload convert host, captured live (ticket 53: p2.record-video's /file/upload passed through it), is an
    # onlyfans.com subdomain like any other: unarmed writes refused as such, reads read
    (Request("POST", "convert.onlyfans.com", "/file/upload", None, AT), Run(), "refused", "unarmed"),
    (Request("GET", "convert.onlyfans.com", "/x", None, AT), Run(), "read", "read"),
    # fake mode: relay_live sends it to FakeOF (`_to_fake`, ticket 131), which answers the claim
    (Request("GET", "convert.onlyfans.com", "/x", None, AT), Run(of="fake"), "read", "read"),
], ids=["queue scheduled under POST_LEAD ahead", "queue scheduled in the past", "queue date unreadable",
        "queue edit to under POST_LEAD ahead", "convert host, write unarmed", "convert host, read",
        "convert host, fake mode"])
def test_guard_queue_dates_and_convert_host(request_, run, kind, cls):
    v = decide(request_, run)
    assert (v.kind, v.cls) == (kind, cls), v.reason


@pytest.mark.parametrize("of", ["live", "fake"])
def test_queue_edit_with_no_date_is_fan_visible(of):
    v = decide(R("PUT", "/api2/v2/messages/queue/88", {"userIds": [555], "userLists": []}),
               Run(proof=_queue_edit(), of=of, proof_fan=FAN, created=frozenset({"88"})))
    assert (v.kind, v.cls) == ("refused", "fan_visible"), v.reason
