#!/usr/bin/env python3
"""S4S requests over the Relay (docs/spec/phase-03-share-for-share.md, ticket 17).

The seam is the Relay over HTTP with real owner and chatter session cookies
from the shared two-Agency fixture, on the throwaway `_harness` database:
send from one of the caller's own opted-in Creators to an S4S profile id,
the Received and Sent boxes, Accept / Skip / Decline by the receiver,
Cancel by the sender, lazy expiry, and Accept booking one S4S slot per side
with one queued `s4s_post` job each. Queued jobs are read straight from
`scheduled_jobs`; the executor never runs here, so nothing is posted.

Creators: A (Agency A), B (Agency B) from the fixture, plus C (Agency A),
the third Creator for limit cases, and a few single-purpose Creators for
the refusals. Every case runs on its own UTC day (`day(n)`), so one case's
slots never fill another case's Daily limit.

Run: ./venv/bin/python service/tests/test_s4s_requests.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _s4s_fixtures import (  # noqa: E402
    IDS, audit_rows, count, db, list_in_discovery, of_profile, profile, seed_creators, with_env,
)
from db.engine import get_session  # noqa: E402
from db.models import S4SRequest, S4SSlot, ScheduledJob, UserAccount  # noqa: E402

A = IDS["creator_a"]
B = IDS["creator_b"]
C = "1000009"
NO_PRIMARY_A, NO_PRIMARY_B, OUT_A, OUT_B, HIDDEN_B, GONE_B = (
    "1000011", "1000012", "1000013", "1000014", "1000015", "1000016")
# The proposal case's own Creators, so no other case's slot fills their days.
PROP_A, PROP_B, PROP_X = "1000021", "1000022", "1000023"
seed_creators({C: "agency_a_owner", NO_PRIMARY_A: "agency_a_owner", OUT_A: "agency_a_owner",
               NO_PRIMARY_B: "agency_b_owner", OUT_B: "agency_b_owner", HIDDEN_B: "agency_b_owner",
               GONE_B: "agency_b_owner", PROP_A: "agency_a_owner", PROP_B: "agency_b_owner",
               PROP_X: "agency_a_owner"})

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")

CAPTION = {
    A: list_in_discovery(OWNER_A, A, "Fixture Alpha", "fixture_alpha"),
    B: list_in_discovery(OWNER_B, B, "Fixture Beta", "fixture_beta",
                         avatar_url="https://thumbs.onlyfans.com/public/files/thumbs/c144/beta/avatar.jpg"),
    C: list_in_discovery(OWNER_A, C, "Fixture Gamma", "fixture_gamma"),
}
for _owner, _aid, _name in ((OWNER_A, NO_PRIMARY_A, "Fixture Plain A"), (OWNER_B, NO_PRIMARY_B, "Fixture Plain B")):
    of_profile(_aid, _name, _name.lower().replace(" ", "_"))
    _r = _owner.put(f"/admin/s4s/profiles/{_aid}", json={"opted_in": True})
    assert _r.status_code == 200, _r.text
list_in_discovery(OWNER_A, OUT_A, "Fixture Out A", "fixture_out_a")
list_in_discovery(OWNER_B, OUT_B, "Fixture Out B", "fixture_out_b")
for _owner, _aid in ((OWNER_A, OUT_A), (OWNER_B, OUT_B)):
    assert _owner.put(f"/admin/s4s/profiles/{_aid}", json={"opted_in": False}).status_code == 200
list_in_discovery(OWNER_B, HIDDEN_B, "Fixture Hidden", "fixture_hidden", discovery_visible=False)
list_in_discovery(OWNER_B, GONE_B, "Fixture Gone", "fixture_gone")
list_in_discovery(OWNER_A, PROP_A, "Fixture Prop A", "fixture_prop_a")
list_in_discovery(OWNER_B, PROP_B, "Fixture Prop B", "fixture_prop_b")
list_in_discovery(OWNER_A, PROP_X, "Fixture Prop X", "fixture_prop_x")


def pid(client, aid: str) -> int:
    return profile(client, aid)["profile_id"]


PID = {A: pid(OWNER_A, A), B: pid(OWNER_B, B), C: pid(OWNER_A, C),
       PROP_A: pid(OWNER_A, PROP_A), PROP_B: pid(OWNER_B, PROP_B), PROP_X: pid(OWNER_A, PROP_X)}


def day(n: int, hour: int = 10, minute: int = 0) -> datetime:
    """`n` UTC days after today, at hour:minute UTC."""
    today = datetime.utcnow().date()
    return datetime(today.year, today.month, today.day) + timedelta(days=n, hours=hour, minutes=minute)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def send(client, from_id: str, to_pid: int, slot_at: datetime):
    return client.post("/admin/s4s/requests", json={"from_account_id": from_id, "to_profile_id": to_pid,
                                                    "slot_at": z(slot_at)})


def sent(client, from_id: str, to_aid: str, slot_at: datetime) -> dict:
    r = send(client, from_id, PID[to_aid], slot_at)
    assert r.status_code == 201, f"send {from_id}→{to_aid}: {r.status_code} {r.text}"
    return r.json()


def box(client, which: str) -> dict[int, dict]:
    r = client.get(f"/admin/s4s/requests?box={which}")
    assert r.status_code == 200, f"GET {which}: {r.status_code} {r.text}"
    return {item["id"]: item for item in r.json()}


def act(client, request_id: int, verb: str):
    return client.post(f"/admin/s4s/requests/{request_id}/{verb}")


def projection(aid: str, client) -> dict:
    p = profile(client, aid)
    return {"profile_id": p["profile_id"], "display_name": p["display_name"], "username": p["username"],
            "avatar_url": p["avatar_url"], "primary_caption": CAPTION[aid], "daily_limit": p["daily_limit"],
            "opted_in": p["opted_in"]}


async def _rows(model, **where) -> list:
    async with get_session() as s:
        q = select(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return list((await s.execute(q.order_by(model.id))).scalars().all())


def rows(model, **where) -> list:
    return asyncio.run(_rows(model, **where))


def one_new_audit(action: str, before: int, account_id: str, owner: str, request_id: int) -> dict:
    got = audit_rows(action)
    assert len(got) == before + 1, f"{action}: {len(got) - before} new rows"
    row = got[-1]
    assert row.account_id == account_id and row.employee_id is None, (row.account_id, row.employee_id)
    payload = json.loads(row.payload_json)
    assert payload["agency_user_id"] == IDS[owner] and payload["request_id"] == request_id, payload
    return payload


def _every_route(client) -> list:
    body = {"from_account_id": A, "to_profile_id": 1, "slot_at": z(day(30))}
    return [
        ("GET received", client.get("/admin/s4s/requests?box=received")),
        ("GET sent", client.get("/admin/s4s/requests?box=sent")),
        ("POST requests", client.post("/admin/s4s/requests", json=body)),
        ("GET proposal", client.get(f"/admin/s4s/requests/proposal?from_account_id={A}&to_profile_id=1")),
        *[(f"POST {v}", client.post(f"/admin/s4s/requests/1/{v}")) for v in ("accept", "skip", "decline", "cancel")],
    ]


# ── Sessions ─────────────────────────────────────────────────────────

def case_signed_out_is_401_and_a_chatter_is_403_on_every_request_route():
    anon = _harness.make_client()
    for label, r in _every_route(anon):
        assert r.status_code == 401, f"{label} signed out: {r.status_code} {r.text}"
    for label, r in with_env("ALLOW_ANONYMOUS_ADMIN", "1", lambda: _every_route(anon)):
        assert r.status_code == 401, f"{label} with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    for name in ("chatter_a", "chatter_ab"):
        for label, r in _every_route(fx.login_chatter(name)):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code} {r.text}"
    assert count(S4SRequest) == 0, "a refused call wrote a request"


# ── Send, boxes, snapshots ───────────────────────────────────────────

def case_sending_answers_201_with_both_snapshots_and_the_boxes_never_read_the_partner_live():
    audits = len(audit_rows("s4s.request_send"))
    a_proj, b_proj = projection(A, OWNER_A), projection(B, OWNER_B)
    slot_at = day(2)
    r = send(OWNER_A, A, PID[B], slot_at)
    assert r.status_code == 201, f"send: {r.status_code} {r.text}"
    got = r.json()
    assert set(got) == {"id", "box", "status", "slot_at", "from", "to", "from_media", "to_media", "created_at", "answered_at"}, got
    assert (got["box"], got["status"], got["slot_at"], got["answered_at"]) == ("sent", "pending", z(slot_at), None)
    assert got["from"] == a_proj and got["to"] == b_proj, got
    (row,) = rows(S4SRequest, id=got["id"])
    assert (row.from_account_id, row.to_account_id) == (A, B)
    assert (row.from_caption, row.to_caption) == (CAPTION[A], CAPTION[B])
    payload = one_new_audit("s4s.request_send", audits, A, "agency_a_owner", got["id"])
    assert set(payload) == {"agency_user_id", "request_id"}, payload

    # Creator B is renamed on OnlyFans and Agency B rewrites its Primary caption; the request keeps what was sent.
    of_profile(B, "Fixture Beta Renamed", "fixture_beta")
    assert profile(OWNER_B, B)["display_name"] == "Fixture Beta Renamed"
    (primary,) = [p for p in profile(OWNER_B, B)["posts"] if p["is_primary"]]
    assert OWNER_B.patch(f"/admin/s4s/profiles/{B}/posts/{primary['id']}",
                         json={"caption": "Rewritten promo"}).status_code == 200
    received, outbox = box(OWNER_B, "received"), box(OWNER_A, "sent")
    for item, which in ((received[got["id"]], "received"), (outbox[got["id"]], "sent")):
        assert item == {**got, "box": which}, (which, item)
    for client in (OWNER_A, OWNER_B):
        for which in ("received", "sent"):
            text = client.get(f"/admin/s4s/requests?box={which}").text
            for aid in (A, B, C):
                assert aid not in text, f"account id {aid} in the {which} box: {text}"
    assert OWNER_B.patch(f"/admin/s4s/profiles/{B}/posts/{primary['id']}",
                         json={"caption": CAPTION[B]}).status_code == 200
    of_profile(B, "Fixture Beta", "fixture_beta", "https://thumbs.onlyfans.com/public/files/thumbs/c144/beta/avatar.jpg")
    assert profile(OWNER_B, B)["display_name"] == "Fixture Beta"


def case_decline_answers_once_and_every_later_answer_or_cancel_is_409():
    (rid,) = box(OWNER_B, "received")
    audits = len(audit_rows("s4s.request_decline"))
    r = act(OWNER_B, rid, "decline")
    assert r.status_code == 200, f"decline: {r.status_code} {r.text}"
    assert r.json()["status"] == "declined" and r.json()["answered_at"], r.json()
    one_new_audit("s4s.request_decline", audits, B, "agency_b_owner", rid)
    for client, verb in ((OWNER_B, "accept"), (OWNER_B, "skip"), (OWNER_B, "decline"), (OWNER_A, "cancel")):
        r = act(client, rid, verb)
        assert r.status_code == 409, f"{verb} after decline: {r.status_code} {r.text}"
    assert box(OWNER_A, "sent")[rid]["status"] == "declined"
    assert count(S4SSlot) == 0


def case_refusals_are_409_or_400_and_write_nothing():
    before, audits = count(S4SRequest), len(audit_rows("s4s.request_send"))
    gone = pid(OWNER_B, GONE_B)
    refused = [
        ("past time", 409, send(OWNER_A, A, PID[B], datetime.utcnow() - timedelta(minutes=5))),
        ("no Primary post on the sender", 409, send(OWNER_A, NO_PRIMARY_A, PID[B], day(3))),
        ("no Primary post on the receiver", 409, send(OWNER_A, A, pid(OWNER_B, NO_PRIMARY_B), day(3))),
        ("the sender opted out", 409, send(OWNER_A, OUT_A, PID[B], day(3))),
        ("the receiver opted out", 409, send(OWNER_A, A, pid(OWNER_B, OUT_B), day(3))),
        ("to the sender's own Creator", 400, send(OWNER_A, A, PID[A], day(3))),
        ("from another Agency's Creator", 403, send(OWNER_A, B, PID[C], day(3))),
        ("no such profile", 404, send(OWNER_A, A, 999999, day(3))),
        ("a profile hidden from Discovery", 404, send(OWNER_A, A, pid(OWNER_B, HIDDEN_B), day(3))),
    ]
    db(delete(UserAccount).where(UserAccount.account_id == GONE_B))
    refused.append(("a profile whose Creator left every Agency", 404, send(OWNER_A, A, gone, day(3))))
    for label, want, r in refused:
        assert r.status_code == want, f"{label}: {r.status_code} {r.text}"
    bad = [
        [], "text", {}, {"from_account_id": A, "to_profile_id": PID[B]},
        {"from_account_id": A, "to_profile_id": PID[B], "slot_at": "2030-01-01T10:00:00"},
        {"from_account_id": A, "to_profile_id": PID[B], "slot_at": "soon"},
        {"from_account_id": A, "to_profile_id": str(PID[B]), "slot_at": z(day(3))},
        {"from_account_id": A, "to_profile_id": True, "slot_at": z(day(3))},
        {"from_account_id": 1000001, "to_profile_id": PID[B], "slot_at": z(day(3))},
        {"from_account_id": A, "to_profile_id": PID[B], "slot_at": z(day(3)), "note": "x"},
    ]
    for body in bad:
        r = OWNER_A.post("/admin/s4s/requests", json=body)
        assert r.status_code == 400, f"{body!r:.80}: {r.status_code} {r.text}"
    r = OWNER_A.post("/admin/s4s/requests", content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code == 400, f"broken JSON: {r.status_code} {r.text}"
    assert count(S4SRequest) == before and len(audit_rows("s4s.request_send")) == audits, "a refusal wrote"


def case_one_open_request_per_pair_and_direction():
    first = sent(OWNER_A, A, B, day(3))
    r = send(OWNER_A, A, PID[B], day(4))
    assert r.status_code == 409, f"second open A→B: {r.status_code} {r.text}"
    back = sent(OWNER_B, B, A, day(3, 12))  # the other direction is its own pair
    assert {first["id"], back["id"]} <= set(box(OWNER_A, "sent")) | set(box(OWNER_A, "received"))


def case_skip_hides_from_the_receiver_only_and_the_sender_can_still_cancel():
    (rid,) = [i for i, item in box(OWNER_A, "sent").items() if item["status"] == "pending"
              and item["to"]["profile_id"] == PID[B]]
    audits = len(audit_rows("s4s.request_skip"))
    r = act(OWNER_B, rid, "skip")
    assert r.status_code == 200, f"skip: {r.status_code} {r.text}"
    one_new_audit("s4s.request_skip", audits, B, "agency_b_owner", rid)
    assert rid not in box(OWNER_B, "received"), "a skipped request still shows to the receiver"
    mine = box(OWNER_A, "sent")[rid]
    assert (mine["status"], mine["answered_at"]) == ("pending", None), mine
    (row,) = rows(S4SRequest, id=rid)
    assert row.status == "skipped"
    for verb in ("accept", "decline", "skip"):
        assert act(OWNER_B, rid, verb).status_code == 409, f"{verb} after skip"

    audits = len(audit_rows("s4s.request_cancel"))
    r = act(OWNER_A, rid, "cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled", f"cancel: {r.status_code} {r.text}"
    one_new_audit("s4s.request_cancel", audits, A, "agency_a_owner", rid)
    assert box(OWNER_A, "sent")[rid]["status"] == "cancelled"
    assert act(OWNER_A, rid, "cancel").status_code == 409, "a second cancel"


def case_accept_after_cancel_is_409():
    (rid,) = [i for i, item in box(OWNER_B, "sent").items() if item["status"] == "pending"]
    assert act(OWNER_B, rid, "cancel").status_code == 200
    r = act(OWNER_A, rid, "accept")
    assert r.status_code == 409, f"accept after cancel: {r.status_code} {r.text}"
    assert rid not in {s.request_id for s in rows(S4SSlot)}


def case_a_non_party_or_the_wrong_party_gets_404():
    inside_a = sent(OWNER_A, A, C, day(5))  # both Creators in Agency A
    across = sent(OWNER_A, C, B, day(5, 14))
    for verb in ("accept", "skip", "decline", "cancel"):
        r = act(OWNER_B, inside_a["id"], verb)
        assert r.status_code == 404, f"Agency B {verb}s Agency A's own request: {r.status_code} {r.text}"
    for which in ("received", "sent"):
        assert inside_a["id"] not in box(OWNER_B, which), f"Agency B reads it in {which}"
    for verb in ("accept", "skip", "decline"):
        r = act(OWNER_A, across["id"], verb)
        assert r.status_code == 404, f"the sender {verb}s its own request: {r.status_code} {r.text}"
    r = act(OWNER_B, across["id"], "cancel")
    assert r.status_code == 404, f"the receiver cancels: {r.status_code} {r.text}"
    for missing in ("999999", "abc"):
        assert act(OWNER_A, missing, "accept").status_code == 404, missing
    for rid in (inside_a["id"], across["id"]):
        assert act(OWNER_A, rid, "cancel").status_code == 200
    r = OWNER_A.get("/admin/s4s/requests?box=everything")
    assert r.status_code == 400, f"unknown box: {r.status_code} {r.text}"


# ── Accept books two slots ───────────────────────────────────────────

def case_accept_books_one_slot_per_side_and_queues_one_s4s_post_job_each_at_the_slot_time():
    slot_at = day(6)
    req = sent(OWNER_A, A, B, slot_at)
    jobs_before = count(ScheduledJob, kind="s4s_post")
    audits = len(audit_rows("s4s.request_accept"))
    r = act(OWNER_B, req["id"], "accept")
    assert r.status_code == 200, f"accept: {r.status_code} {r.text}"
    assert r.json()["status"] == "accepted" and r.json()["answered_at"], r.json()
    assert box(OWNER_A, "sent")[req["id"]]["status"] == "accepted"

    slots = rows(S4SSlot, request_id=req["id"])
    by_poster = {s.poster_account_id: s for s in slots}
    assert len(slots) == 2 and set(by_poster) == {A, B}, [(s.poster_account_id, s.partner_account_id) for s in slots]
    assert by_poster[B].partner_account_id == A and by_poster[A].partner_account_id == B
    assert by_poster[B].text == f"{CAPTION[A]}\n@fixture_alpha", by_poster[B].text
    assert by_poster[A].text == f"{CAPTION[B]}\n@fixture_beta", by_poster[A].text
    for s in slots:
        assert (s.slot_at, s.status, s.post_id) == (slot_at, "scheduled", None), (s.slot_at, s.status)

    jobs = rows(ScheduledJob, kind="s4s_post")
    assert len(jobs) == jobs_before + 2, len(jobs)
    for s in slots:
        (job,) = [j for j in jobs if json.loads(j.payload_json) == {"slot_id": s.id}]
        assert job.id == s.job_id, (job.id, s.job_id)
        assert (job.account_id, job.run_at, job.status) == (s.poster_account_id, slot_at, "pending"), job.run_at
    payload = one_new_audit("s4s.request_accept", audits, B, "agency_b_owner", req["id"])
    assert sorted(payload["slot_ids"]) == sorted(s.id for s in slots), payload

    for client, verb in ((OWNER_B, "accept"), (OWNER_B, "decline"), (OWNER_B, "skip"), (OWNER_A, "cancel")):
        assert act(client, req["id"], verb).status_code == 409, f"{verb} after accept"
    assert len(rows(S4SSlot, request_id=req["id"])) == 2


def case_a_full_daily_limit_on_either_side_is_409_counted_per_utc_day():
    # A and B each hold one slot on day 6 (the accept above); both Daily limits are 1.
    for label, r in (
        ("the receiver A is full", send(OWNER_A, C, PID[A], day(6, 15))),
        ("the sender A is full", send(OWNER_A, A, PID[C], day(6, 15))),
        ("the receiver B is full", send(OWNER_A, C, PID[B], day(6, 23, 59))),
    ):
        assert r.status_code == 409, f"{label}: {r.status_code} {r.text}"
    # The day is the UTC day: the minutes either side of day 6 are free.
    edge = [sent(OWNER_A, C, A, day(5, 23, 59)), sent(OWNER_A, A, C, day(7, 0, 0))]
    for item in edge:
        assert act(OWNER_A, item["id"], "cancel").status_code == 200
    # A canceled slot does not count (the slot cancel route is ticket 18, so the row is set here).
    (a_slot,) = [s for s in rows(S4SSlot, poster_account_id=A) if s.slot_at == day(6)]
    db(update(S4SSlot).where(S4SSlot.id == a_slot.id).values(status="canceled"))
    freed = sent(OWNER_A, C, A, day(6, 16))
    assert act(OWNER_A, freed["id"], "cancel").status_code == 200
    db(update(S4SSlot).where(S4SSlot.id == a_slot.id).values(status="scheduled"))
    # A higher limit makes room on the same day.
    assert OWNER_A.put(f"/admin/s4s/profiles/{A}", json={"daily_limit": 2}).status_code == 200
    more = sent(OWNER_A, C, A, day(6, 15))
    assert act(OWNER_A, more["id"], "cancel").status_code == 200
    assert OWNER_A.put(f"/admin/s4s/profiles/{A}", json={"daily_limit": 1}).status_code == 200


def case_a_failed_recheck_rolls_the_whole_accept_back_with_409():
    from_c = sent(OWNER_A, C, B, day(8, 9))
    from_a = sent(OWNER_A, A, B, day(8, 18))
    assert act(OWNER_B, from_a["id"], "accept").status_code == 200  # B's one slot on day 8
    slots, jobs = count(S4SSlot), count(ScheduledJob, kind="s4s_post")
    audits = len(audit_rows("s4s.request_accept"))
    r = act(OWNER_B, from_c["id"], "accept")
    assert r.status_code == 409, f"accept over B's Daily limit: {r.status_code} {r.text}"
    assert box(OWNER_B, "received")[from_c["id"]]["status"] == "pending", "the guarded update was not rolled back"
    assert (count(S4SSlot), count(ScheduledJob, kind="s4s_post")) == (slots, jobs)
    assert len(audit_rows("s4s.request_accept")) == audits
    assert act(OWNER_B, from_c["id"], "decline").status_code == 200


def case_accept_after_either_side_opts_out_is_409_and_writes_nothing():
    # The opt-out cascade (ticket 18, test_s4s_schedule.py) cancels the request, so it is no longer pending.
    for n, (owner, creator) in enumerate(((OWNER_A, A), (OWNER_B, B))):
        req = sent(OWNER_A, A, B, day(11 + n))
        assert owner.put(f"/admin/s4s/profiles/{creator}", json={"opted_in": False}).status_code == 200
        slots, jobs = count(S4SSlot), count(ScheduledJob, kind="s4s_post")
        audits = len(audit_rows("s4s.request_accept"))
        r = act(OWNER_B, req["id"], "accept")
        assert r.status_code == 409, f"accept after {creator} opted out: {r.status_code} {r.text}"
        assert box(OWNER_B, "received")[req["id"]]["status"] == "cancelled", "the opt-out left it open"
        assert (count(S4SSlot), count(ScheduledJob, kind="s4s_post")) == (slots, jobs)
        assert len(audit_rows("s4s.request_accept")) == audits
        assert owner.put(f"/admin/s4s/profiles/{creator}", json={"opted_in": True}).status_code == 200
        assert act(OWNER_B, req["id"], "accept").status_code == 409, "opting back in reopened it"


# ── Lazy expiry ──────────────────────────────────────────────────────

def case_a_request_past_its_time_reads_as_expired_and_cannot_be_accepted():
    pending = sent(OWNER_B, B, C, day(9))
    skipped = sent(OWNER_A, A, B, day(9, 12))
    assert act(OWNER_B, skipped["id"], "skip").status_code == 200
    past = datetime.utcnow().replace(microsecond=0) - timedelta(minutes=1)
    db(update(S4SRequest).where(S4SRequest.id.in_([pending["id"], skipped["id"]])).values(slot_at=past))
    audits = len(audit_rows("s4s.request_expire"))

    # Any S4S read applies it, not only a Requests read.
    assert OWNER_A.get("/admin/s4s/profiles").status_code == 200
    assert {r.id: r.status for r in rows(S4SRequest) if r.id in (pending["id"], skipped["id"])} == {
        pending["id"]: "expired", skipped["id"]: "expired"}
    got = audit_rows("s4s.request_expire")
    assert len(got) == audits + 2, len(got) - audits
    by_request = {json.loads(row.payload_json)["request_id"]: row for row in got[audits:]}
    assert by_request[pending["id"]].account_id == B and by_request[skipped["id"]].account_id == A

    assert box(OWNER_A, "received")[pending["id"]]["status"] == "expired"
    assert box(OWNER_B, "sent")[pending["id"]]["status"] == "expired"
    assert box(OWNER_A, "sent")[skipped["id"]]["status"] == "expired"
    r = act(OWNER_A, pending["id"], "accept")
    assert r.status_code == 409, f"accept an expired request: {r.status_code} {r.text}"
    assert act(OWNER_B, pending["id"], "cancel").status_code == 409, "cancel an expired request"
    assert len(audit_rows("s4s.request_expire")) == audits + 2, "a second read expired it again"
    assert not rows(S4SSlot, request_id=pending["id"])


def case_the_master_acts_as_an_owner_of_its_own_creators_only():
    master = fx.login_owner("agency_master")
    for which in ("received", "sent"):
        assert box(master, which) == {}, f"the Master holds no Creator, yet its {which} box is not empty"
    req = sent(OWNER_A, A, B, day(10))
    for verb in ("accept", "cancel"):
        r = act(master, req["id"], verb)
        assert r.status_code == 404, f"the Master {verb}s a request it is not a party to: {r.status_code} {r.text}"
    assert act(OWNER_A, req["id"], "cancel").status_code == 200


# ── Proposed time ────────────────────────────────────────────────────

def proposal(client, from_id: str, to_aid: str):
    return client.get(f"/admin/s4s/requests/proposal?from_account_id={from_id}&to_profile_id={PID[to_aid]}")


def proposed(client, from_id: str, to_aid: str) -> datetime | None:
    r = proposal(client, from_id, to_aid)
    assert r.status_code == 200, f"proposal {from_id}→{to_aid}: {r.status_code} {r.text}"
    assert set(r.json()) == {"slot_at"}, r.json()
    at = r.json()["slot_at"]
    return None if at is None else datetime.fromisoformat(at.removesuffix("Z"))


def book(owner, from_id: str, to_aid: str, receiver, slot_at: datetime) -> None:
    req = sent(owner, from_id, to_aid, slot_at)
    assert act(receiver, req["id"], "accept").status_code == 200


def case_the_proposal_is_0600_utc_on_the_first_day_from_tomorrow_with_room_under_both_daily_limits():
    # Never today, though both are free today: tomorrow at 06:00 UTC.
    assert (got := proposed(OWNER_A, PROP_A, PROP_B)) == day(1, 6), got
    # The sender full on day 1, the receiver full on day 2, both full on day 3: each day is skipped.
    book(OWNER_A, PROP_A, PROP_X, OWNER_A, day(1, 12))
    assert (got := proposed(OWNER_A, PROP_A, PROP_B)) == day(2, 6), got
    book(OWNER_B, PROP_B, PROP_X, OWNER_A, day(2, 12))
    assert (got := proposed(OWNER_A, PROP_A, PROP_B)) == day(3, 6), got
    book(OWNER_A, PROP_A, PROP_B, OWNER_B, day(3, 23))
    assert (got := proposed(OWNER_A, PROP_A, PROP_B)) == day(4, 6), got
    # Either side asking reads the same day.
    assert (got := proposed(OWNER_B, PROP_B, PROP_A)) == day(4, 6), got
    # A higher limit is room: PROP_A's day-1 slot no longer fills it, and PROP_B is free that day.
    assert OWNER_A.put(f"/admin/s4s/profiles/{PROP_A}", json={"daily_limit": 2}).status_code == 200
    assert (got := proposed(OWNER_A, PROP_A, PROP_B)) == day(1, 6), got
    assert OWNER_A.put(f"/admin/s4s/profiles/{PROP_A}", json={"daily_limit": 1}).status_code == 200
    # The proposal is one Send accepts.
    at = proposed(OWNER_A, PROP_A, PROP_B)
    assert at == day(4, 6), at
    assert act(OWNER_A, sent(OWNER_A, PROP_A, PROP_B, at)["id"], "cancel").status_code == 200


def case_the_proposal_refuses_like_send_and_is_null_for_an_opted_out_sender():
    assert proposal(OWNER_B, PROP_A, PROP_B).status_code == 403, "another Agency's Creator as the sender"
    for label, r in (
        ("a hidden partner", OWNER_A.get(f"/admin/s4s/requests/proposal?from_account_id={PROP_A}"
                                         f"&to_profile_id={pid(OWNER_B, HIDDEN_B)}")),
        ("no such profile", OWNER_A.get(f"/admin/s4s/requests/proposal?from_account_id={PROP_A}&to_profile_id=999999")),
    ):
        assert r.status_code == 404, f"{label}: {r.status_code} {r.text}"
    for q in (f"from_account_id={PROP_A}&to_profile_id=x", f"to_profile_id={PID[PROP_B]}"):
        r = OWNER_A.get(f"/admin/s4s/requests/proposal?{q}")
        assert r.status_code == 400, f"{q}: {r.status_code} {r.text}"
    assert proposal(OWNER_A, PROP_A, PROP_A).status_code == 400, "a proposal to itself"
    assert proposed(OWNER_A, OUT_A, PROP_B) is None, "an opted-out sender got a time"


_harness.run()
