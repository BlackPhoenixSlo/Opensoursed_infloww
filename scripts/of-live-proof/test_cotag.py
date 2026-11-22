"""new-post--cotag-scheduled, new-post--cotag-immediate (ofm-not-yet ticket 98): the wire tag assertion, the parks
(no partner, live immediate, the fan-visible cap), the guard's verdicts on both posts, FakeOF's taggable-creators read
and tags on posts, the lost-reply fault on the immediate Co-tagged post only, the cotag-extra planted composer, the
finder and the effect. No browser, no OnlyFans.
"""
import dataclasses
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

import fake_layer
import proof_core
from proof_core import Request, Run, decide
from proofs import phase6_cotag
from proofs.phase6 import (NEW_POST_COTAG_IMMEDIATE, NEW_POST_COTAG_SCHEDULED, QUEUE_PUBLISH_NOW, QUEUE_SEND_NOW,
                           draft_text)
from proofs.phase6_cotag import (COTAG_IMMEDIATE, COTAG_SCHEDULED, cotag_cap_refusal, cotag_effect,
                                  cotag_wire_problems, find_cotag, read_cotag)
from soak import ids
from soak.fake_of import posts as fake_posts
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World

P = fake_layer.COTAG_PARTNER
AT = datetime(2026, 11, 21, 3, 10, tzinfo=timezone.utc)
QUIET = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
SCHED, IMM, PN, SEND = (NEW_POST_COTAG_SCHEDULED.id, NEW_POST_COTAG_IMMEDIATE.id, QUEUE_PUBLISH_NOW.id,
                        QUEUE_SEND_NOW.id)
RUN = "oi-proof-r"


S_TEXT, I_TEXT = draft_text(RUN, COTAG_SCHEDULED), draft_text(RUN, COTAG_IMMEDIATE)   # each proof's draft text


def body(tags=(P,), scheduled=None, media=(), text=f"{RUN} x"):
    """The Relay's outbound co-tag body (of_client `_write_tag_block`)."""
    b = {"text": text, "mediaFiles": list(media), "price": 0, "userTags": list(tags), "rfTag": list(tags),
         "rfGuest": [], "rfPartner": []}
    if scheduled is not None:
        b.update(isScheduled=1, scheduledDate=scheduled)
    return b


# ── the wire tag assertion (story 4) ──

@pytest.mark.parametrize("b, bad", [
    (body(), []),
    (body(tags=(str(P),)), []),                                       # ids as strings: the same partner
    (body(tags=(P, fake_layer.COTAG_EXTRA)), ["rfTag", "userTags"]),  # a second creator (cotag-extra)
    (body(tags=()), ["no Co-tag at all"]),                            # untagged
    ({**body(), "userTags": [P, 4004]}, ["userTags"]),                # an auto-tag in one array only
    ({**body(), "rfGuest": [7]}, ["rfGuest"]),
    ({**body(), "rfPartner": [{"id": 8}]}, ["rfPartner"]),
    (body(media=(5001,)), ["media"]),                                 # media: an auto-tag could join
    ({k: v for k, v in body().items() if k not in ("rfGuest", "rfPartner")}, []),   # absent rf arrays: empty
    (body(tags=("0" + str(P),)), ["rfTag", "userTags"]),              # "02001" is not 2001 (the guard's id rule)
    (body(tags=({"id": P},)), ["rfTag", "userTags"]),                 # not an id
])
def test_wire_assertion_takes_the_partner_alone(b, bad):
    out = cotag_wire_problems(b, str(P))
    assert len(out) == len(bad) and all(k in line for k, line in zip(bad, out)), out


def test_wire_assertion_refuses_an_unreadable_body():
    assert cotag_wire_problems("<12 bytes>", P)


@pytest.mark.parametrize("b", [
    body(), body(tags=(str(P),)), body(tags=(P, fake_layer.COTAG_EXTRA)), body(tags=("0" + str(P),)),
    body(tags=(" 2001",)), body(tags=(True,)), body(tags=(2001.0,)), {**body(), "rfTag": "2001"},
    {**body(), "userTags": [P, 4004]}, {**body(), "rfGuest": [7]}, body(tags=()), "text=x&rfTag=2001", None,
])
@pytest.mark.parametrize("partner", [str(P), P, None])
def test_the_guard_and_the_wire_check_share_one_rule(b, partner):
    """The guard refuses exactly what the wire check's tag part flags (one function, one id rule)."""
    rule = proof_core.cotag_problems(b, partner)
    assert (proof_core.cotag_refusal(b, partner) is None) == (rule == [])
    if proof_core.cotag_tagged(b) or not isinstance(b, dict):
        assert [f"outbound: {p}" for p in rule] == [p for p in cotag_wire_problems(b, partner) if "media" not in p]


# ── parks ──

class _Parked(Exception):
    pass


def _ctx(of="fake", partner=str(P), spent=()):
    def park(why):
        raise _Parked(why)
    return {"record": {}, "of": of, "park": park, "cotag_partner": partner, "marker": RUN,
            "fan_visible_spent": lambda: list(spent)}


@pytest.mark.parametrize("step", [phase6_cotag.cotag_scheduled_draft, phase6_cotag.cotag_immediate_draft])
@pytest.mark.parametrize("of", ["fake", "live"])
@pytest.mark.parametrize("partner", [None, "", "none-given"])
def test_no_partner_parks_both_before_any_write(monkeypatch, step, of, partner):
    monkeypatch.setattr(phase6_cotag, "_cotag_draft", lambda *a: pytest.fail("a draft without a partner"))
    with pytest.raises(_Parked, match=r"^Co-tag partner not named \(owner sheet item 4\)$"):
        step(_ctx(of, partner))


def test_live_immediate_parks_on_the_ruling_scheduled_goes_on(monkeypatch):
    drafts = []
    monkeypatch.setattr(phase6_cotag, "_cotag_draft", lambda ctx, suffix, at: drafts.append((suffix, at)) or [])
    with pytest.raises(_Parked, match="fake mode only"):
        phase6_cotag.cotag_immediate_draft(_ctx("live"))
    assert drafts == []
    assert phase6_cotag.cotag_scheduled_draft(_ctx("live")) == []
    (suffix, at), = drafts
    lead = datetime.fromisoformat(at) - datetime.now(timezone.utc)
    assert suffix == COTAG_SCHEDULED and lead > proof_core.POST_LEAD


@pytest.mark.parametrize("spent, parks", [
    ((), False),               # its own run
    ((SEND,), False),          # Send now already spent its slot: the last one is free
    ((PN,), True),             # the full Phase 6 run: the last slot kept for Send now
    ((PN, SEND), True),        # the guard's cap spent
    ((IMM,), True),            # its one attempt made
])
def test_immediate_takes_a_fan_visible_slot_only_when_one_is_left_for_send_now(monkeypatch, spent, parks):
    monkeypatch.setattr(phase6_cotag, "_cotag_draft", lambda *a: [])
    if parks:
        with pytest.raises(_Parked, match="^fan-visible cap: "):
            phase6_cotag.cotag_immediate_draft(_ctx(spent=spent))
    else:
        assert phase6_cotag.cotag_immediate_draft(_ctx(spent=spent)) == []
    assert (cotag_cap_refusal(spent, NEW_POST_COTAG_IMMEDIATE, "fake") is not None) == parks


# ── the guard ──

def R(b):
    return Request(method="POST", host="onlyfans.com", path="/api2/v2/posts", body=b, at=AT)


def test_scheduled_post_c_is_allowed_and_not_fan_visible():
    v = decide(R(body(scheduled=(AT + timedelta(minutes=45)).isoformat(), text=S_TEXT)),
               Run(proof=NEW_POST_COTAG_SCHEDULED, of="fake", quiet_hour=QUIET, marker=RUN, cotag_partner=str(P)))
    assert (v.kind, v.fan_visible) == ("allow", False)


def test_scheduled_post_c_under_post_lead_is_refused():
    v = decide(R(body(scheduled=(AT + timedelta(minutes=10)).isoformat())),
               Run(proof=NEW_POST_COTAG_SCHEDULED, of="fake", quiet_hour=QUIET, marker=RUN, cotag_partner=str(P)))
    assert v.kind == "refused"


LATER = (AT + timedelta(minutes=45)).isoformat()


@pytest.mark.parametrize("b, partner, refused", [
    (body(scheduled=LATER), str(P), None),
    (body(tags=(str(P),), scheduled=LATER), str(P), None),                       # ids as strings: the same partner
    (body(scheduled=LATER), None, "no Co-tag partner named"),                     # partner unset: a tagged post refused
    (body(tags=(P, fake_layer.COTAG_EXTRA), scheduled=LATER), str(P), "rfTag"),   # cotag-extra's body
    ({**body(scheduled=LATER), "userTags": [P, 4004]}, str(P), "userTags"),
    ({**body(scheduled=LATER), "rfTag": []}, str(P), "rfTag"),                    # userTags alone
    ({**body(scheduled=LATER), "userTags": None}, str(P), "userTags"),
    (body(tags=(4004,), scheduled=LATER), str(P), "rfTag"),                       # someone else
    ({**body(scheduled=LATER), "rfGuest": [7]}, str(P), "rfGuest"),
    ({**body(scheduled=LATER), "rfPartner": [{"id": 8}]}, str(P), "rfPartner"),
    ({**body(tags=(), scheduled=LATER), "rfGuest": [7]}, None, "no Co-tag partner named"),   # any tag array counts
])
def test_the_guard_refuses_a_post_cotagged_with_anyone_but_the_partner(b, partner, refused):
    """The class 7 backstop alone: the proof's own payload (class 4, test_the_payload_*) taken off its arm."""
    v = decide(R(b), Run(proof=_BARE_SCHED, of="fake", quiet_hour=QUIET, marker=RUN, cotag_partner=partner))
    if refused is None:
        assert v.kind == "allow", v
    else:
        assert (v.kind, v.cls) == ("refused", "post") and refused in v.reason, v


_BARE_SCHED = dataclasses.replace(NEW_POST_COTAG_SCHEDULED, arm=(proof_core.Write("POST", phase6_cotag.POSTS_PATH),))


@pytest.mark.parametrize("proof", [SCHED, IMM])
@pytest.mark.parametrize("b, why", [
    (body(), None),
    ({**body(), "text": "x"}, "lacks this run's marker"),
    ({**body(), "text": "oi-proof-q x"}, "lacks this run's marker"),               # round 2 #22: another run's
    (body(tags=()), "no Co-tag at all"),                                          # the declared tag left off
    (body(media=(5001,)), "media"),                                               # media: an auto-tag could join
    (body(tags=(P, fake_layer.COTAG_EXTRA)), "rfTag"),
    ("text=x&rfTag=2001", "not a JSON object"),
])
def test_the_payload_holds_both_cotag_posts_to_the_marker_the_partner_and_no_media(proof, b, why):
    """Follow-up #5: each Co-tag post leaves only as declared (Write.payload, class 4), whatever the steps sent."""
    p = _POST_PROOFS()[proof]
    if isinstance(b, dict) and b["text"] == f"{RUN} x":   # the proof's own draft text (W30 W1)
        b = {**b, "text": I_TEXT if proof == IMM else S_TEXT}
    b = b if proof == IMM or not isinstance(b, dict) else {**b, "isScheduled": 1, "scheduledDate": LATER}
    v = decide(R(b), Run(proof=p, of="fake", quiet_hour=QUIET, marker=RUN, cotag_partner=str(P)))
    if why is None:
        assert v.kind == "allow", v
    else:
        assert (v.kind, v.cls) == ("refused", "unarmed") and why in v.reason and "declared payload" in v.reason, v


def _at(minutes):
    return (AT + timedelta(minutes=minutes)).isoformat()


@pytest.mark.parametrize("proof, b, why", [
    (SCHED, body(scheduled=LATER, text=S_TEXT), None),
    (SCHED, body(scheduled=_at(46), text=S_TEXT), None),                     # the draft's lead plus the clock slack
    (SCHED, body(scheduled=_at(31), text=S_TEXT), None),                     # posted 14 min after its draft
    (SCHED, body(scheduled=LATER, text=f"{S_TEXT} changed"), "not the draft's"),   # holds the marker, altered
    (SCHED, body(scheduled=LATER, text=f"<p>{S_TEXT}</p>"), "not the draft's"),
    (SCHED, body(scheduled=LATER, text=I_TEXT), "not the draft's"),          # the other proof's text
    (SCHED, body(scheduled=_at(4 * 24 * 60), text=S_TEXT), "minutes ahead"),  # +4 days: outside the finder's read
    (SCHED, body(scheduled=_at(48), text=S_TEXT), "minutes ahead"),
    (SCHED, body(scheduled="soon", text=S_TEXT), "unreadable"),
    (SCHED, {**body(scheduled=LATER, text=S_TEXT), "isScheduled": 0}, "not scheduled"),
    (SCHED, body(text=S_TEXT), "not scheduled"),
    (IMM, body(text=I_TEXT), None),
    (IMM, body(text=f"{I_TEXT}!"), "not the draft's"),
    (IMM, body(scheduled=_at(4 * 24 * 60), text=I_TEXT), "carries a schedule"),
    (IMM, {**body(text=I_TEXT), "scheduledDate": LATER}, "carries a schedule"),
])
def test_the_payload_binds_each_cotag_post_to_its_exact_draft_text_and_schedule(proof, b, why):
    """W30 W1: a Co-tag post leaves only with its draft's exact text (what find_cotag recovers a lost reply by) and
    its draft's schedule (post C: POST_SCHEDULE_LEAD ahead, inside the finder's today/tomorrow read; immediate: none)."""
    v = decide(R(b), Run(proof=_POST_PROOFS()[proof], of="fake", quiet_hour=QUIET, marker=RUN, cotag_partner=str(P)))
    if why is None:
        assert v.kind == "allow", v
    else:
        assert (v.kind, v.cls) == ("refused", "unarmed") and why in v.reason and "declared payload" in v.reason, v


@pytest.mark.parametrize("of", ["fake", "live"])
@pytest.mark.parametrize("b", [
    {"text": "t", "mediaFiles": [], "price": 0, "isScheduled": 1, "scheduledDate": LATER},     # no tag arrays at all
    {**body(tags=(), scheduled=LATER)},                                                        # the Relay's empty ones
])
@pytest.mark.parametrize("partner", [None, str(P)])
@pytest.mark.parametrize("proof", ["new-post--upload", "queue--publish-now", SCHED, IMM])
def test_untagged_posts_pass_as_before(of, b, partner, proof):
    """An untagged post passes the backstop under every proof, a partner named or not; a Co-tag proof's own payload
    (follow-up #5) refuses it: its post carries the declared tag."""
    v = decide(R(b), Run(proof=_POST_PROOFS()[proof], of=of, quiet_hour=QUIET, marker=RUN, cotag_partner=partner))
    if proof in (SCHED, IMM):
        assert (v.kind, v.cls) == ("refused", "unarmed"), v
    else:
        assert v.kind == "allow", v


def _POST_PROOFS() -> dict:
    from proofs.phase6 import NEW_POST_UPLOAD
    return {p.id: p for p in (NEW_POST_UPLOAD, QUEUE_PUBLISH_NOW, NEW_POST_COTAG_SCHEDULED, NEW_POST_COTAG_IMMEDIATE)}


@pytest.mark.parametrize("of", ["fake", "live"])
@pytest.mark.parametrize("proof, kind", [
    ("new-post--upload", "refused"), ("queue--publish-now", "refused"),   # an auto-tag on their media: never sent
    (SCHED, "allow"), (IMM, "allow"),
])
def test_only_a_cotag_proof_may_tag(of, proof, kind):
    """A tag notification cannot be undone: the partner's tag rides only the two Co-tag proofs' posts (Proof.may_tag);
    any other proof's tagged post is refused, the named partner or not."""
    p = _POST_PROOFS()[proof]
    assert p.may_tag == (kind == "allow")
    b = body(text=I_TEXT) if proof == IMM else body(scheduled=LATER, text=S_TEXT)
    v = decide(R(b), Run(proof=p, of=of, quiet_hour=QUIET, marker=RUN, cotag_partner=str(P)))
    assert v.kind == kind, v
    if kind == "refused":
        assert v.cls == "post" and "may not tag" in v.reason, v


@pytest.mark.parametrize("raw", ["text=x&rfTag=2001&rfTag=2002", b"\x00\x01", None, ["2001"]])
@pytest.mark.parametrize("proof", ["new-post--cotag-scheduled", "queue--publish-now"])
def test_the_guard_refuses_a_post_body_it_cannot_read(raw, proof):
    """Form-encoded, raw or absent: the backstop cannot see its Co-tags, so the post never leaves."""
    p = {"new-post--cotag-scheduled": NEW_POST_COTAG_SCHEDULED, "queue--publish-now": QUEUE_PUBLISH_NOW}[proof]
    v = decide(R(raw), Run(proof=p, of="fake", quiet_hour=QUIET, marker=RUN, cotag_partner=str(P)))
    assert v.kind == "refused", v


@pytest.fixture
def relay(tmp_path, monkeypatch):
    """relay_live imported afresh against a temp evidence folder, fake mode (as test_publish_now's)."""
    import sys
    monkeypatch.setenv("OFM_PROOF_EVIDENCE", str(tmp_path))
    monkeypatch.setenv("OF_API_ORIGIN", "http://127.0.0.1:9")
    sys.modules.pop("relay_live", None)
    import relay_live
    yield relay_live
    sys.modules.pop("relay_live", None)


@pytest.mark.parametrize("sent, want", [(str(P), str(P)), (P, str(P)), (None, None), ("", None)])
def test_relay_arm_carries_the_partner_to_the_guard(relay, monkeypatch, sent, want):
    from fastapi import FastAPI
    app = FastAPI()
    relay.proof_routes(app, lambda request, path, params: None)
    c = TestClient(app, client=("127.0.0.1", 50000))
    assert c.post("/__proof/arm", json={"proof": SCHED, "of": "fake", "cotag_partner": sent}).status_code == 200
    assert relay._run.cotag_partner == want
    monkeypatch.setattr(relay, "_now", lambda: AT)
    monkeypatch.setattr(relay, "pace_wait", lambda last, now: 0)
    _, v, _ = relay._intent("of-browser", "POST", "http://127.0.0.1:9/api2/v2/posts",
                            body(tags=(P, fake_layer.COTAG_EXTRA), scheduled=LATER))
    assert (v.kind, v.cls) == ("refused", "unarmed")   # cotag-extra's body never leaves (the proof's payload)


@pytest.mark.parametrize("of, quiet, done, kind", [
    ("fake", QUIET, (), "allow"),
    ("fake", None, (), "refused"),              # outside a declared quiet hour
    ("fake", QUIET, (PN, SEND), "refused"),     # the effort's cap spent
    ("fake", QUIET, (IMM,), "refused"),         # its one attempt
])
def test_immediate_post_is_fan_visible_and_capped(of, quiet, done, kind):
    v = decide(R(body(text=I_TEXT)), Run(proof=NEW_POST_COTAG_IMMEDIATE, of=of, quiet_hour=quiet, fan_visible_done=done,
                              marker=RUN, cotag_partner=str(P)))
    assert v.kind == kind
    if kind == "allow":
        assert v.fan_visible


@pytest.mark.parametrize("args, want", [
    (["--of", "fake"], "2001"),                                  # fake default: FakeOF's taggable creator
    (["--of", "fake", "--cotag-partner", "none"], None),
    (["--of", "fake", "--cotag-partner", "NONE"], None),
    (["--of", "fake", "--cotag-partner", ""], None),
    (["--of", "fake", "--cotag-partner", "2003"], "2003"),
])
def test_cli_names_the_partner(monkeypatch, args, want):
    import prove
    got = {}
    monkeypatch.setattr(prove, "prove", lambda ids, fault, fan, **k: got.update(k) or 0)
    monkeypatch.setattr(prove.signal, "signal", lambda *a: None)
    monkeypatch.setattr(prove.os, "setpriority", lambda *a: None)
    assert prove.main(args) == 0
    assert got["cotag_partner"] == want


@pytest.mark.parametrize("value", ["abc", "20o1", "-5", "2001,2002"])
def test_cli_refuses_a_non_digit_partner(monkeypatch, value):
    import prove
    monkeypatch.setattr(prove, "prove", lambda *a, **k: pytest.fail("prove ran"))
    monkeypatch.setattr(prove.signal, "signal", lambda *a: None)
    monkeypatch.setattr(prove.os, "setpriority", lambda *a: None)
    assert prove.main(["--of", "fake", "--cotag-partner", value]) == 2


def test_undo_deadlines_scheduled_before_it_fires_immediate_at_once():
    now = AT
    sched = proof_core.undo_deadline(NEW_POST_COTAG_SCHEDULED, "POST", "/api2/v2/posts",
                                     body(scheduled=(now + timedelta(minutes=45)).isoformat()), now)
    imm = proof_core.undo_deadline(NEW_POST_COTAG_IMMEDIATE, "POST", "/api2/v2/posts", body(), now)
    assert sched is not None and now < sched < now + timedelta(minutes=45)
    assert imm is not None and imm - now <= timedelta(seconds=60)


# ── FakeOF ──

@pytest.fixture
def fake():
    def make(fault=None):
        of = FakeOF(World(1))
        of.host, of.port = "127.0.0.1", 1
        client = TestClient(fake_layer.Recorder(of.build(), fault, of))

        def req(method, path, **kw):
            t, uid = str(int(time.time() * 1000)), str(of.world.creator_id)
            h = {"user-id": uid, "x-hash": of.x_hash, "time": t,
                 "sign": sign_value(of.rules, time_ms=t, path_qs=path, user_id=uid)}
            r = client.request(method, path, headers=h, **kw)
            return r.status_code, r.json()
        return of, req, client
    return make


def _get(req):
    return lambda path, params: req("GET", path + ("?" + "&".join(f"{k}={v}" for k, v in params.items())
                                                   if params else ""))[1]


def _create(req, tags=(P,), scheduled=True, text=f"{RUN} {COTAG_SCHEDULED}"):
    b = body(tags=tags, scheduled=(datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat() if scheduled
             else None)
    return req("POST", "/api2/v2/posts", json={**b, "text": text})


def test_fake_taggable_creators_read_searches_and_pages(fake):
    _, req, _ = fake()
    status, got = req("GET", "/api2/v2/posts/tagged-friend-users?limit=50&offset=0")
    assert status == 200 and [i["id"] for i in got["items"]] == [2001, 2002, 2003] and got["hasMore"] is False
    assert [i["id"] for i in req("GET", "/api2/v2/posts/tagged-friend-users?name=creator%203")[1]["items"]] == [2003]
    assert [i["id"] for i in req("GET", "/api2/v2/posts/tagged-friend-users?name=SYNTHCREATOR2")[1]["items"]] == [2002]
    page = req("GET", "/api2/v2/posts/tagged-friend-users?limit=2&offset=0")[1]
    assert [i["id"] for i in page["items"]] == [2001, 2002] and page["hasMore"] is True
    assert P in [i["id"] for i in got["items"]]   # the fake run's partner is taggable


def test_fake_scheduled_cotag_post_reads_its_tag_then_deletes(fake):
    of, req, _ = fake()
    get = _get(req)
    before = read_cotag(get, None)
    status, post = _create(req)
    assert status == 200 and post["rfTag"] == [P]
    after = read_cotag(get, None)
    (sid, pid, text, at, tags), = after["queue"]
    assert (pid, text, tags) == (post["id"], f"{RUN} {COTAG_SCHEDULED}", str(P)) and after["profile"] == []
    assert cotag_effect(before, after)
    assert find_cotag(COTAG_SCHEDULED)(before, after, RUN) == post["id"]
    assert find_cotag(COTAG_IMMEDIATE)(before, after, RUN) is None
    assert req("DELETE", f"/api2/v2/posts/{post['id']}") == (200, {"success": True})
    assert read_cotag(get, None) == before


def test_fake_immediate_cotag_post_is_published_with_its_tag(fake):
    of, req, _ = fake()
    get = _get(req)
    before = read_cotag(get, None)
    status, post = _create(req, scheduled=False, text=f"{RUN} {COTAG_IMMEDIATE}")
    assert status == 200
    after = read_cotag(get, None)
    assert after["queue"] == [] and after["profile"] == [[post["id"], f"{RUN} {COTAG_IMMEDIATE}", str(P)]]
    assert find_cotag(COTAG_IMMEDIATE)(before, after, RUN) == post["id"]
    assert req("DELETE", f"/api2/v2/posts/{post['id']}")[0] == 200
    assert read_cotag(get, None) == before


def test_the_settle_poll_reads_only_its_own_scheduled_post(fake):
    """Follow-up #19: the post's settle poll reads the schedule list and that one post, not each scheduled post."""
    _, req, _ = fake()
    posts = [_create(req, text=f"{RUN} {COTAG_SCHEDULED} {n}")[1] for n in range(5)]
    paths = []
    get = _get(req)
    ctx = {"of_get": lambda path, params: paths.append(path) or get(path, params), "page": None}
    want = posts[2]
    row = phase6_cotag._cotag_shown(ctx, str(want["id"]), "queue", f"{RUN} {COTAG_SCHEDULED} 2")
    assert row is not None and (row[1], row[4]) == (want["id"], str(P)), row
    assert paths == ["/api2/v2/schedules", f"/api2/v2/posts/{want['id']}"], paths
    assert len(read_cotag(get, None)["queue"]) == 5   # the full read still reads them all


def test_fake_untagged_post_reads_no_tag(fake):
    _, req, _ = fake()
    status, post = req("POST", "/api2/v2/posts", json={"text": "plain", "mediaFiles": [], "price": 0})
    assert status == 200 and "rfTag" not in post


def test_lost_reply_drops_only_the_immediate_cotagged_post(fake):
    of, req, client = fake("lost-reply")
    assert _create(req)[0] == 200                                          # scheduled and tagged: answered
    assert req("POST", "/api2/v2/posts", json={"text": "plain", "mediaFiles": [], "price": 0})[0] == 200   # untagged
    with pytest.raises(Exception):   # noqa: B017  (no reply at all)
        _create(req, scheduled=False, text=f"{RUN} {COTAG_IMMEDIATE}")
    made = [p.text for p in fake_posts.state(of)["posts"].values()]
    assert made == [f"{RUN} {COTAG_SCHEDULED}", "plain", f"{RUN} {COTAG_IMMEDIATE}"]   # made before the drop
    faults = [h.get("fault", "").split(":")[0] or None for h in client.app.snapshot() if h["path"] == "/api2/v2/posts"]
    assert faults == [None, None, "lost-reply"]


def test_lost_reply_still_faults_list_creates():
    hit = {"method": "POST", "path": "/api2/v2/lists", "tagged": False, "query": "", "body": {"name": "x"}}
    assert fake_layer.Recorder(lambda *a: None, "lost-reply")._fires(hit)


class _Route:
    def __init__(self):
        self.sent = None

    def continue_(self, post_data=None, **kw):
        self.sent = json.loads(post_data)


def _request(method, path, data):
    return SimpleNamespace(method=method, url=f"http://127.0.0.1:3000{path}", post_data=json.dumps(data))


@pytest.mark.parametrize("data, fires", [
    ({"text": "t", "media_files": [], "tagged_users": [P]}, True),
    ({"text": "t", "media_files": [], "tagged_users": []}, False),                  # no Co-tag: untouched
    ({"text": "t", "tagged_users": [P, fake_layer.COTAG_EXTRA]}, False),           # already there
])
def test_cotag_extra_plants_a_second_creator_on_the_apps_post(data, fires):
    planted, route = [], _Route()
    hook = fake_layer.FAULTS["cotag-extra"].hook(planted)
    assert hook(route, _request("POST", "/api/of/v2/posts", data)) is fires
    if fires:
        assert route.sent["tagged_users"] == [P, fake_layer.COTAG_EXTRA] and len(planted) == 1
    assert hook(_Route(), _request("POST", "/api/of/v2/upload", data)) is False
    assert hook(_Route(), _request("PUT", "/api/of/v2/posts", data)) is False


def test_cotag_extra_is_an_app_fault_the_recorder_does_not_take():
    assert isinstance(fake_layer.FAULTS["cotag-extra"], fake_layer.AppFault)
    with pytest.raises(ValueError):
        fake_layer.Recorder(lambda *a: None, "cotag-extra")


# ── the declarations and the records ──

@pytest.mark.parametrize("proof, tags", [(NEW_POST_COTAG_SCHEDULED, {"post"}),
                                         (NEW_POST_COTAG_IMMEDIATE, {"post", "delete_at_once"})])
def test_proofs_are_declared_text_posts_deleted_by_id(proof, tags):
    assert set(proof.tags) == tags and proof.page == "new-post/state-tag-people"
    assert [(w.method, w.path, w.max) for w in proof.arm] == [("POST", "/api2/v2/posts", 1)]
    assert [(w.method, w.path, w.relay) for w in proof.undo] == [("DELETE", "/api2/v2/posts/{id}",
                                                                  "/api/of/v2/posts/{id}")]


def test_draft_texts_are_marker_only():
    assert draft_text(RUN, COTAG_SCHEDULED) == f"{RUN} cotag-scheduled"
    assert draft_text(RUN, COTAG_IMMEDIATE) == f"{RUN} cotag-immediate"


@pytest.mark.parametrize("proof", [NEW_POST_COTAG_SCHEDULED, NEW_POST_COTAG_IMMEDIATE])
def test_capture_records_stay_parked_on_the_owner_sheet(proof):
    rec = json.loads((Path(__file__).resolve().parents[2] / f"docs/of-manager/captures/{proof.id}.json").read_text())
    assert rec["label"] == proof.control and proof.page in rec["pages"]
    assert rec["proof"]["verdict"] == "parked" and "owner sheet item 4 (Co-tag partner)" in rec["proof"]["reason"]


def test_a_read_first_park_is_judged_on_its_own_window(monkeypatch, tmp_path):
    """The full Phase 6 run: other proofs' POST /posts (the same arm) before and after the cap park are not its own."""
    import prove
    monkeypatch.setattr(prove, "census", lambda *a: [])
    monkeypatch.setattr(prove, "pace_problems", lambda *a: [])
    monkeypatch.setattr(prove, "_wire_folded", lambda e: {})

    def hit(method, path, t):
        return {"t": t, "method": method, "path": path, "query": "", "body": None, "tagged": False, "status": 200}
    others = [hit("POST", "/api2/v2/posts", 1), hit("DELETE", "/api2/v2/posts/9", 2), hit("POST", "/api2/v2/posts", 9)]
    parked = {"proof": IMM, "read_first": True, "t": [5, 6]}
    assert prove.harness_checks(tmp_path, others, [parked]) == []
    assert prove.harness_checks(tmp_path, others + [hit("POST", "/api2/v2/posts", 5.5)], [parked]) == [
        f"{IMM}: parked, yet FakeOF received POST /api2/v2/posts"]
    assert len(prove.harness_checks(tmp_path, others, [{k: v for k, v in parked.items() if k != "t"}])) == 3
