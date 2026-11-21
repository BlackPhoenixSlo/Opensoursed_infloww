"""queue--publish-now (ticket 99): the guard's publish gate and fan-visible attempts (Proof.fan_visible_max), the
Relay counting each attempt, a found publish taking the post its own create made, FakeOF's Publish now and profile
read, the three planted faults, the proof's pure helpers and the fake check's phased window. No browser, no OnlyFans.
"""
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

import fake_layer
import proof_core
import undo_driver
from proof_core import Request, Run, decide
from proofs import phase6_writes
from proofs.phase6 import (PN_FILE, PN_NOW, PN_VISIBLE, QUEUE_PUBLISH_NOW, QUEUE_SEND_NOW, draft_text,
                           find_publish_now, publish_media, publish_now_effect, read_publish_now)
from proofs.phase2 import S3_HOST
from soak import ids
from soak.fake_of import posts as fake_posts
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World

PN, SEND = QUEUE_PUBLISH_NOW.id, QUEUE_SEND_NOW.id
AT = datetime(2026, 11, 21, 3, 10, tzinfo=timezone.utc)
QUIET = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
POST, OTHER_POST = str(ids.post_id(2)), str(ids.post_id(1))
SID, OTHER_SID = str(ids.post_schedule_id(2)), str(ids.post_schedule_id(1))
X = ids.vault_media_id(ids.UPLOADED + 1)
SPENT = {("arm", i): 1 for i in range(4)}


def R(method, path, body=None):
    return Request(method=method, host="onlyfans.com", path=path, body=body, at=AT)


def post_body(ahead=45):
    return {"text": "oi-proof-r publish-now", "mediaFiles": [X], "price": 0, "isScheduled": 1,
            "scheduledDate": (AT + timedelta(minutes=ahead)).isoformat()}


def armed(**kw):
    return Run(**{"proof": QUEUE_PUBLISH_NOW, "of": "fake", "quiet_hour": QUIET, "spent": SPENT,
                  "created": frozenset({POST}), "keys": {"schedule": frozenset({SID})}, **kw})


PUBLISH = R("PUT", f"/api2/v2/schedules/{SID}/publish")


# ── the guard ──

def test_post_d_scheduled_ahead_is_allowed_and_not_fan_visible():
    v = decide(R("POST", "/api2/v2/posts", post_body()), Run(proof=QUEUE_PUBLISH_NOW, of="fake", quiet_hour=QUIET))
    assert (v.kind, v.fan_visible) == ("allow", False)


@pytest.mark.parametrize("of, host, kind", [
    ("fake", "onlyfans.com", "allow"),   # FakeOF's origin, logged as onlyfans.com
    ("fake", S3_HOST, "allow"),          # spec 53h: the PUT arm names S3_HOST (phase2 UPLOAD_ARMS)
])
def test_the_storage_put_takes_ofs_creator_spliced_key(of, host, kind):
    """Spec 53: OnlyFans' putUrl carries the Creator's id spliced into the key; the arm names its S3 host."""
    assert S3_HOST in QUEUE_PUBLISH_NOW.hosts
    req = Request("PUT", host, f"/upload/{ids.CREATOR_ID}"
                  "/be74f324-6712-4dff-a833-aa3d6a76f2e6/1136746826498/oi-proof-publish.png", None, AT)
    run = Run(proof=QUEUE_PUBLISH_NOW, of=of, quiet_hour=QUIET, spent={("arm", 0): 1},
              hosts=QUEUE_PUBLISH_NOW.hosts)   # the Relay's arm adds the proof's named hosts
    assert decide(req, run).kind == kind


def test_publish_of_ds_registered_schedule_is_allowed_and_fan_visible():
    v = decide(PUBLISH, armed())
    assert (v.kind, v.fan_visible) == ("allow", True)


def test_publish_of_another_queued_posts_schedule_is_refused_by_the_publish_gate():
    """Adviser 1: the planted other-post Publish now is the guard's publish gate's to refuse."""
    v = decide(R("PUT", f"/api2/v2/schedules/{OTHER_SID}/publish"), armed())
    assert (v.kind, v.cls) == ("refused", "mass_message")


@pytest.mark.parametrize("done, kind", [
    ((), "allow"),
    ((PN,), "allow"),                 # the visible re-run: Publish now's second attempt
    ((PN, PN), "refused"),            # fan_visible_max = 2 spent
    ((SEND, PN), "refused"),          # the effort's cap of 2 spent
    ((SEND,), "allow"),               # another proof's one attempt
], ids=["none", "one own", "two own", "cap spent", "other"])
def test_publish_now_may_make_two_fan_visible_attempts_within_the_cap(done, kind):
    v = decide(PUBLISH, armed(fan_visible_done=done))
    assert v.kind == kind, v
    if kind == "refused":
        assert v.cls == "fan_visible"


@pytest.mark.parametrize("done, kind", [
    ((), "allow"),
    ((PN,), "refused"),   # live: Publish now runs with a fan-visible cap of 1, the re-run never sent
], ids=["first", "re-run"])
def test_live_publish_now_gets_one_fan_visible_attempt(done, kind):
    v = decide(PUBLISH, armed(of="live", fan_visible_done=done))
    assert v.kind == kind, v
    if kind == "refused":
        assert v.cls == "fan_visible" and "its one fan-visible attempt" in v.reason


@pytest.mark.parametrize("of, media, kind", [
    ("live", [X], "refused"),   # the guard backstop: live, a fan-visible proof's post carries no media
    ("live", [], "allow"),
    ("fake", [X], "allow"),     # fake mode: the hidden-dedupe drill posts X_D
], ids=["live media", "live text-only", "fake media"])
def test_outside_fake_a_fan_visible_proofs_post_carries_empty_media_files(of, media, kind):
    v = decide(R("POST", "/api2/v2/posts", {**post_body(), "mediaFiles": media}),
               Run(proof=QUEUE_PUBLISH_NOW, of=of, quiet_hour=QUIET))
    assert v.kind == kind, v
    if kind == "refused":
        assert v.cls == "fan_visible" and "empty mediaFiles" in v.reason


def test_send_now_keeps_its_single_attempt():
    run = Run(proof=QUEUE_SEND_NOW, of="fake", proof_fan="555", quiet_hour=QUIET, spent={("arm", 0): 1},
              created=frozenset({"9"}), keys={"schedule": frozenset({SID})}, fan_visible_done=(SEND,))
    v = decide(PUBLISH, run)
    assert (v.kind, v.cls) == ("refused", "fan_visible") and "its one fan-visible attempt" in v.reason


# ── the Relay ──

@pytest.fixture
def relay(tmp_path, monkeypatch):
    """relay_live imported afresh against a temp evidence folder, fake mode (as test_relay_live's)."""
    monkeypatch.setenv("OFM_PROOF_EVIDENCE", str(tmp_path))
    monkeypatch.setenv("OF_API_ORIGIN", "http://127.0.0.1:9")
    sys.modules.pop("relay_live", None)
    import relay_live
    yield relay_live
    sys.modules.pop("relay_live", None)


def test_relay_counts_each_fan_visible_attempt(relay, monkeypatch):
    monkeypatch.setattr(relay, "_now", lambda: AT)
    monkeypatch.setattr(relay, "pace_wait", lambda last, now: 0)
    relay._run = armed()
    url = f"http://127.0.0.1:9/api2/v2/schedules/{SID}/publish"
    verdicts = []
    for _ in range(3):
        _, v, row = relay._intent("of-browser", "PUT", url, None)
        verdicts.append((v.kind, v.cls, bool(row and row["fan_visible"])))
    # the third: the publish arm's max of 2 refuses it first
    assert verdicts == [("allow", "allow", True), ("allow", "allow", True), ("refused", "over_count", False)]
    assert relay._run.fan_visible_done == (PN, PN)
    v = decide(PUBLISH, replace(relay._run, spent=SPENT))   # with the arm unspent, the attempts count refuses it
    assert (v.kind, v.cls) == ("refused", "fan_visible")


def _app(relay):
    from fastapi import FastAPI
    app = FastAPI()
    relay.proof_routes(app, lambda request, path, params: None)
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.mark.parametrize("post_row, want", [
    ({"proof": PN, "of_id": POST}, 200),
    ({"proof": PN, "of_id": OTHER_POST}, 409),                  # the found id is another post
    ({"proof": "new-post--upload", "of_id": POST}, 409),        # another proof's post create
    (None, 409),
], ids=["own post create", "another post", "another proof", "no post create"])
def test_found_publish_takes_only_the_post_its_own_create_made(relay, post_row, want):
    c = _app(relay)
    assert c.post("/__proof/arm", json={"proof": PN, "of": "fake", "proof_fan": "555"}).status_code == 200
    if post_row:
        relay.append_jsonl(relay.UNDO, {"row": 1, "state": "pending", "arm": 3, "write_status": 200,
                                        "write": {"method": "POST", "path": "/api2/v2/posts"}, **post_row})
    relay.append_jsonl(relay.UNDO, {"row": 2, "proof": PN, "state": "pending", "arm": 4, "of_id": None,
                                    "wire_seq": 9, "write": {"method": "PUT",
                                                             "path": f"/api2/v2/schedules/{SID}/publish"}})
    r = c.post("/__proof/found", json={"row": 2, "of_id": POST})
    assert r.status_code == want, r.text


@pytest.mark.parametrize("of_id, ok", [(POST, True), (OTHER_POST, False)], ids=["D's own post", "foreign"])
def test_found_mismatch_takes_a_publish_row_only_with_ds_own_post_id(relay, of_id, ok):
    rows = {1: {"row": 1, "proof": PN, "write": {"method": "POST", "path": "/api2/v2/posts"}, "of_id": POST}}
    row = {"row": 2, "proof": PN, "write": {"method": "PUT", "path": f"/api2/v2/schedules/{SID}/publish"}}
    why = relay._found_mismatch(None, None, row, of_id, rows)
    assert (why is None) == ok, why


# ── FakeOF ──

@pytest.fixture
def fake():
    def make(fault=None, seed=None):
        of = FakeOF(World(1))
        of.host, of.port = "127.0.0.1", 1
        if seed:
            seed(of)
        client = TestClient(fake_layer.Recorder(of.build(), fault, of))

        def req(method, path, **kw):
            t, uid = str(int(time.time() * 1000)), str(of.world.creator_id)
            h = {"user-id": uid, "x-hash": of.x_hash, "time": t,
                 "sign": sign_value(of.rules, time_ms=t, path_qs=path, user_id=uid)}
            r = client.request(method, path, headers=h, **kw)
            return r.status_code, r.json()
        return of, req, client
    return make


def _post(req, media, text="oi-proof-t"):
    when = (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
    return req("POST", "/api2/v2/posts", json={"text": text, "mediaFiles": media, "price": 0, "isScheduled": 1,
                                               "scheduledDate": when})


def _hidden_post(of, req):
    """A post holding the seeded vault item 2, then Removed from vault (a hidden id in a scheduled post)."""
    m = ids.vault_media_id(2)
    assert req("PUT", "/api2/v2/vault/media/hidden", json={"mediaIds": [m]}) == (200, {"success": True})
    return m


def _get(of, req):
    return lambda path, params: req("GET", path + ("?" + "&".join(f"{k}={v}" for k, v in params.items())
                                                   if params else ""))[1]


def test_fake_publish_now_moves_a_post_holding_a_hidden_id_to_the_profile(fake):
    of, req, _ = fake()
    m = _hidden_post(of, req)
    status, post = _post(req, [m])
    assert status == 200 and [x["id"] for x in post["media"]] == [m]   # OnlyFans takes a hidden id (ASSUMPTION)
    sid = req("GET", "/api2/v2/schedules?limit=50")[1]["list"][0]["id"]
    uid = of.world.creator_id
    assert req("GET", f"/api2/v2/users/{uid}/posts?limit=10") == (200, [])
    assert req("PUT", f"/api2/v2/schedules/{sid}/publish") == (200, {"success": True})
    assert req("GET", "/api2/v2/schedules?limit=50")[1]["list"] == []
    status, rows = req("GET", f"/api2/v2/users/{uid}/posts?limit=10")
    assert status == 200 and [(r["id"], r["rawText"], [x["id"] for x in r["media"]]) for r in rows] == \
        [(post["id"], "oi-proof-t", [m])]
    assert req("GET", f"/api2/v2/users/{uid + 1}/posts")[0] == 404
    assert req("PUT", f"/api2/v2/schedules/{sid}/publish")[0] == 404   # published: no schedule item left
    read = read_publish_now(_get(of, req), None)
    assert read["queue"] == [] and read["profile"] == [[post["id"], "oi-proof-t", m]]
    assert req("DELETE", f"/api2/v2/posts/{post['id']}") == (200, {"success": True})
    assert req("GET", f"/api2/v2/users/{uid}/posts")[1] == []


def test_hidden_refused_answers_400_only_for_a_post_holding_a_hidden_medium(fake):
    of, req, client = fake("hidden-refused")
    m = _hidden_post(of, req)
    _post(req, [m])
    _post(req, [ids.vault_media_id(3)])
    rows = {r["entity"]["id"]: r["id"] for r in req("GET", "/api2/v2/schedules?limit=50")[1]["list"]}
    hidden_sid, visible_sid = rows[ids.post_id(1)], rows[ids.post_id(2)]
    status, body = req("PUT", f"/api2/v2/schedules/{hidden_sid}/publish")
    assert status == 400 and "hidden media" in body["error"]["message"]
    assert hidden_sid in [r["id"] for r in req("GET", "/api2/v2/schedules?limit=50")[1]["list"]]   # unpublished
    assert req("PUT", f"/api2/v2/schedules/{visible_sid}/publish") == (200, {"success": True})
    faults = [h.get("fault") for h in client.app.snapshot() if h["path"].endswith("/publish")]
    assert faults == ["hidden-refused", None]


def test_post_lost_hidden_makes_the_post_holding_a_hidden_id_then_drops_the_reply(fake):
    of, req, client = fake("post-lost-hidden")
    assert _post(req, [ids.vault_media_id(3)])[0] == 200   # a visible medium: untouched
    m = _hidden_post(of, req)
    with pytest.raises(Exception):   # noqa: B017  (no reply at all)
        _post(req, [m])
    held = [p.media for p in fake_posts.state(of)["posts"].values()]
    assert held == [[ids.vault_media_id(3)], [m]]   # OnlyFans made it before the reply was lost


@pytest.mark.parametrize("fault, status", [("publish-lost", None), ("publish-500", 500)])
def test_publish_reply_faults_publish_d_then_lose_the_answer(fake, fault, status):
    """The required drill: OnlyFans publishes D, its reply is lost (no reply) or a 5xx; D is on the profile."""
    of, req, client = fake(fault)
    _, post = _post(req, [ids.vault_media_id(3)])
    sid = req("GET", "/api2/v2/schedules?limit=50")[1]["list"][0]["id"]
    if status is None:
        with pytest.raises(Exception):   # noqa: B017  (no reply at all)
            req("PUT", f"/api2/v2/schedules/{sid}/publish")
    else:
        assert req("PUT", f"/api2/v2/schedules/{sid}/publish")[0] == status
    assert req("GET", "/api2/v2/schedules?limit=50")[1]["list"] == []
    rows = req("GET", f"/api2/v2/users/{of.world.creator_id}/posts?limit=10")[1]
    assert [r["id"] for r in rows] == [post["id"]]
    # in-process there is no transport to drop (": connection not dropped"); the fake run proves the real drop
    assert [h.get("fault", "").split(":")[0] for h in client.app.snapshot() if h["path"].endswith("/publish")] == \
        [fault]


def test_publish_other_seeds_the_owners_post_and_rewrites_only_the_publish():
    of = FakeOF(World(1))
    f = fake_layer.FAULTS["publish-other"]
    assert isinstance(f, fake_layer.AppFault) and f.seed is not None
    f.seed(of)
    (owner,) = fake_posts.state(of)["posts"].values()
    assert (owner.id, owner.schedule, owner.text) == (ids.post_id(1), ids.post_schedule_id(1),
                                                     fake_layer.OWNER_POST_TEXT)
    planted, sent = [], []
    hook = f.hook(planted)
    route = SimpleNamespace(continue_=lambda **kw: sent.append(kw))

    def req(method, path):
        return SimpleNamespace(method=method, url=f"http://127.0.0.1:1{path}?x=1")
    assert not hook(route, req("GET", f"/api/of/v2/schedules/{SID}/publish"))
    assert not hook(route, req("PUT", f"/api/of/v2/schedules/{SID}"))
    assert sent == [] and planted == []
    assert hook(route, req("PUT", f"/api/of/v2/schedules/{SID}/publish"))
    assert sent == [{"url": f"http://127.0.0.1:1/api/of/v2/schedules/{OTHER_SID}/publish?x=1"}]
    assert planted == [{"method": "PUT", "path": f"/api/of/v2/schedules/{SID}/publish", "sent": OTHER_SID}]
    with pytest.raises(ValueError, match="unknown FakeOF fault"):
        fake_layer.Recorder(None, "publish-other")


# ── the proof's helpers ──

RUN = "oi-proof-r"
BEFORE = {"queue": [], "vault": [1, 2], "profile": [[7, "owner's", 1]]}
D_QUEUED = {"queue": [[int(SID), int(POST), draft_text(RUN, PN_NOW), X]], "vault": [1, 2],
            "profile": BEFORE["profile"]}
D_PUBLISHED = {"queue": [], "vault": [1, 2], "profile": sorted([[int(POST), draft_text(RUN, PN_NOW), X],
                                                                  *BEFORE["profile"]])}


@pytest.mark.parametrize("after, want", [
    (BEFORE, None),
    (D_QUEUED, int(POST)),
    (D_PUBLISHED, int(POST)),
    ({**D_QUEUED, "queue": [[int(SID), int(POST), "an operator's post", X]]}, None),
    ({**D_QUEUED, "queue": [*D_QUEUED["queue"], [9, 10, draft_text(RUN, PN_VISIBLE), 11]]}, None),   # two
    ({**BEFORE, "queue": [[9, 10, draft_text(RUN, PN_FILE), 11]]}, 10),
], ids=["nothing", "queued", "published", "unmarked", "two", "P"])
def test_finder_takes_the_one_new_marked_post_queued_or_published(after, want):
    assert find_publish_now(BEFORE, after, RUN) == want


def test_effect_and_undo_keys():
    assert not publish_now_effect(BEFORE, BEFORE)
    assert publish_now_effect(BEFORE, D_QUEUED) and publish_now_effect(BEFORE, D_PUBLISHED)
    # X_D is hidden (not listed in the vault after): still D's key; a medium the vault had before never is
    assert publish_media(BEFORE, D_PUBLISHED) == {POST: {"media": X}}
    assert publish_media(BEFORE, {**BEFORE, "queue": [[9, 10, "t", 2]]}) == {}
    assert publish_media(BEFORE, {**BEFORE, "queue": [[9, 10, "t", 11, 12]]}) == {}


@pytest.mark.parametrize("of, spent, blocked", [
    ("fake", [PN], None),
    ("fake", [PN, PN], "already made its 2 fan-visible attempts"),
    ("fake", [SEND, PN], "cap of 2 for the effort is spent"),
    ("fake", [SEND, SEND], "cap of 2 for the effort is spent"),
    ("live", [], None),
    ("live", [PN], "its one fan-visible attempt"),
], ids=["first refused", "own spent", "cap spent", "others spent", "live first", "live re-run"])
def test_fan_visible_refusal_is_the_one_cap_rule(of, spent, blocked):
    why = proof_core.fan_visible_refusal(spent, QUEUE_PUBLISH_NOW, of)
    assert (why is None) if blocked is None else (blocked in why), why


class _Parked(Exception):
    pass


def _pn_ctx(of="fake", spent=()):
    calls = []

    def park(why):
        raise _Parked(why)
    ctx = {"record": {"post_d": {"id": POST, "schedule": SID}, "x": X, "branches": {}}, "of": of, "park": park,
           "settle": lambda: calls.append("settle"), "fan_visible_spent": lambda: tuple(spent), "marker": RUN}
    return ctx, calls


def test_pn_draft_parks_live_before_any_write(monkeypatch):
    """No capture holds a text-only post body: live parks pending capture, nothing written."""
    monkeypatch.setattr(phase6_writes, "_seed_draft", lambda *a: pytest.fail("a write before the live park"))
    ctx, calls = _pn_ctx("live")
    with pytest.raises(_Parked, match="needs capture \\(ticket 12 sitting\\)"):
        phase6_writes.pn_draft(ctx)
    assert calls == [] and ctx["record"]["branches"] == {}


@pytest.mark.parametrize("status", ["error: RemoteProtocolError", None, 500, 502])
def test_pn_publish_lost_or_5xx_fails_unretried_and_leaves_d_to_the_finder(monkeypatch, status):
    """No re-run, no settle here: D is found by the final after-write read (`/__proof/found`) and undone."""
    monkeypatch.setattr(phase6_writes, "_publish_now", lambda ctx, pid, sid, tag: ([], status, None))
    monkeypatch.setattr(phase6_writes, "_seed_draft", lambda *a: pytest.fail("re-run attempted"))
    ctx, calls = _pn_ctx()
    ctx["record"]["publish"] = {"app_status": 502}
    out = phase6_writes.pn_publish(ctx)
    assert len(out) == 1 and "never retried" in out[0] and calls == []
    assert "publish-now" not in ctx["record"]["branches"] and not ctx["record"].get("rerun")


@pytest.mark.parametrize("of, spent, rerun", [
    ("fake", [PN], True),
    ("fake", [SEND, PN], False),   # the effort's cap spent: parks
    ("live", [PN], False),         # live: cap 1, parks, never attempts
])
def test_pn_publish_hidden_refusal_reruns_only_in_fake_within_the_cap(monkeypatch, of, spent, rerun):
    monkeypatch.setattr(phase6_writes, "_publish_now", lambda ctx, pid, sid, tag: ([], 400, {"error": {}}))
    seeded = []
    monkeypatch.setattr(phase6_writes, "_seed_draft", lambda ctx, text: seeded.append(text))
    ctx, calls = _pn_ctx(of, spent)
    assert phase6_writes.pn_publish(ctx) == [] and calls == ["settle"]
    assert ctx["record"]["hidden_publish"]["status"] == 400
    assert bool(seeded) == rerun == bool(ctx["record"].get("rerun"))
    branch = ctx["record"]["branches"].get("publish-now", "")
    assert branch.startswith("parked: ") != rerun
    if of == "live":
        assert "its one fan-visible attempt" in branch


def test_publish_now_is_declared_as_a_two_branch_delete_at_once_proof():
    p = QUEUE_PUBLISH_NOW
    assert p.branches == ("hidden-dedupe", "publish-now") and "delete_at_once" in p.tags
    assert p.fan_visible_max == 2 and p.binds == frozenset({"schedule"})
    assert proof_core.FAN_VISIBLE_CAP == 2
    assert [(w.method, w.path) for w in p.arm][3:] == [("POST", "/api2/v2/posts"),
                                                       ("PUT", "/api2/v2/schedules/{id}/publish")]
    assert p.undo[0].reverses == (3, 4) and p.undo[1].reverses == (0, 1, 2, 3, 4)


# ── the fake check: a proof settled in phases ──

def test_fake_check_counts_only_the_rows_inside_each_rows_window():
    """P's row (phase 1) and D's (phase 2) on one path: P's window does not count D's later write."""
    t0 = AT.timestamp()

    def at(s):
        return datetime.fromtimestamp(t0 + s, timezone.utc).isoformat()

    def hit(s, method, path, body=None):
        return {"t": t0 + s, "method": method, "path": path, "body": body, "status": 200}

    keys = {"media": str(X)}
    p1, d = str(ids.post_id(1)), POST
    rows = [{"row": 1, "arm": 3, "write": {"method": "POST", "path": "/api2/v2/posts"}, "of_id": p1,
             "opened": at(0), "closed": at(5), "keys": keys},
            {"row": 2, "arm": 3, "write": {"method": "POST", "path": "/api2/v2/posts"}, "of_id": d,
             "opened": at(10), "closed": at(20), "keys": keys}]
    plain = [hit(1, "POST", "/api2/v2/posts"), hit(3, "DELETE", f"/api2/v2/posts/{p1}"),
             hit(4, "PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X]}),
             hit(11, "POST", "/api2/v2/posts"), hit(15, "DELETE", f"/api2/v2/posts/{d}"),
             hit(16, "PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X]})]
    assert [undo_driver.row_problem(QUEUE_PUBLISH_NOW, c, rows, plain) for c in rows] == [None, None]


def test_capture_record_is_unchanged_json():
    from pathlib import Path
    rec = json.loads((Path(__file__).resolve().parents[2] / "docs/of-manager/captures/queue--publish-now.json")
                     .read_text())
    assert rec["label"] == QUEUE_PUBLISH_NOW.control and QUEUE_PUBLISH_NOW.page in rec["pages"]
