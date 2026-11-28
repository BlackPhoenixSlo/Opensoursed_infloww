#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select, text, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts  # noqa: E402
from _s4s_fixtures import (  # noqa: E402
    IDS, audit_rows, db, list_in_discovery, profile, seed_creators, with_env,
)
from db.engine import get_session  # noqa: E402
from db.models import Post, S4SRequest, S4SSlot, ScheduledJob, User, UserAccount  # noqa: E402

A = IDS["creator_a"]
B = IDS["creator_b"]
C = "1000009"
UNLINKED_B = "1000021"
ORPHAN_C = "1000022"
FANSLY_B = "1000023"
seed_creators({C: "agency_a_owner", UNLINKED_B: "agency_b_owner", ORPHAN_C: "agency_c_owner",
               FANSLY_B: "agency_b_owner"},
              users=("agency_c_owner",))

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
OWNER_C = fx.login_owner("agency_c_owner")

list_in_discovery(OWNER_A, A, "Fixture Alpha", "fixture_alpha")
list_in_discovery(OWNER_B, B, "Fixture Beta", "fixture_beta")
list_in_discovery(OWNER_A, C, "Fixture Gamma", "fixture_gamma")
list_in_discovery(OWNER_B, UNLINKED_B, "Fixture Leaving", "fixture_leaving")
list_in_discovery(OWNER_C, ORPHAN_C, "Fixture Orphan", "fixture_orphan")
list_in_discovery(OWNER_B, FANSLY_B, "Fixture Fansly", "fixture_fansly")
accounts.save_meta(FANSLY_B, {**(accounts.load_meta(FANSLY_B) or {}), "platform": "fansly"})

PID = {aid: profile(owner, aid)["profile_id"] for owner, aid in (
    (OWNER_A, A), (OWNER_B, B), (OWNER_A, C), (OWNER_B, UNLINKED_B), (OWNER_C, ORPHAN_C), (OWNER_B, FANSLY_B))}

KEYS = {"id", "slot_at", "status", "display_status", "reason", "partner", "own", "remove_at", "partner_issue"}
PROJECTION_KEYS = {"profile_id", "display_name", "username", "avatar_url", "primary_caption", "daily_limit",
                   "opted_in"}


def day(n: int, hour: int = 10) -> datetime:
    today = datetime.utcnow().date()
    return datetime(today.year, today.month, today.day) + timedelta(days=n, hours=hour)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def month(dt: datetime) -> str:
    first = datetime(dt.year, dt.month, 1)
    return f"from={z(first)}&to={z((first + timedelta(days=32)).replace(day=1))}"


def sent(client, from_id: str, to_aid: str, slot_at: datetime) -> dict:
    r = client.post("/admin/s4s/requests", json={"from_account_id": from_id, "to_profile_id": PID[to_aid],
                                                 "slot_at": z(slot_at)})
    assert r.status_code == 201, f"send {from_id}→{to_aid}: {r.status_code} {r.text}"
    return r.json()


def act(client, request_id: int, verb: str):
    return client.post(f"/admin/s4s/requests/{request_id}/{verb}")


def booked(sender, from_id: str, receiver, to_id: str, slot_at: datetime) -> dict[str, S4SSlot]:
    req = sent(sender, from_id, to_id, slot_at)
    r = act(receiver, req["id"], "accept")
    assert r.status_code == 200, f"accept: {r.status_code} {r.text}"
    return {s.poster_account_id: s for s in rows(S4SSlot, request_id=req["id"])}


async def _rows(model, **where) -> list:
    async with get_session() as s:
        q = select(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return list((await s.execute(q.order_by(model.id))).scalars().all())


def rows(model, **where) -> list:
    return asyncio.run(_rows(model, **where))


def raw_slot(slot_id: int) -> tuple:
    async def go():
        async with get_session() as s:
            return tuple((await s.execute(text("SELECT * FROM s4s_schedule WHERE id = :i"), {"i": slot_id})).one())
    return asyncio.run(go())


def schedule(client, when: datetime) -> dict[int, dict]:
    r = client.get(f"/admin/s4s/schedule?{month(when)}")
    assert r.status_code == 200, f"GET schedule: {r.status_code} {r.text}"
    return {item["id"]: item for item in r.json()}


def cancel(client, slot_id) -> object:
    return client.post(f"/admin/s4s/slots/{slot_id}/cancel")


def reads(client, slot: S4SSlot) -> tuple:
    item = schedule(client, slot.slot_at)[slot.id]
    return item["status"], item["display_status"], item["reason"]


def box(client, which: str) -> dict[int, dict]:
    r = client.get(f"/admin/s4s/requests?box={which}")
    assert r.status_code == 200, f"GET {which}: {r.status_code} {r.text}"
    return {item["id"]: item for item in r.json()}


def _every_route(client) -> list:
    return [
        ("GET schedule", client.get(f"/admin/s4s/schedule?{month(day(1))}")),
        ("POST slot cancel", cancel(client, 1)),
    ]



def case_signed_out_is_401_and_a_chatter_is_403_on_every_schedule_route():
    anon = _harness.make_client()
    for label, r in _every_route(anon):
        assert r.status_code == 401, f"{label} signed out: {r.status_code} {r.text}"
    for label, r in with_env("ALLOW_ANONYMOUS_ADMIN", "1", lambda: _every_route(anon)):
        assert r.status_code == 401, f"{label} with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    for name in ("chatter_a", "chatter_ab"):
        for label, r in _every_route(fx.login_chatter(name)):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code} {r.text}"



def case_the_month_lists_only_the_callers_own_slots_with_the_partner_snapshot_and_no_foreign_account_id():
    slots = booked(OWNER_A, A, OWNER_B, B, day(40))
    mine, theirs = slots[A], slots[B]
    got = schedule(OWNER_A, mine.slot_at)
    assert mine.id in got and theirs.id not in got, f"Agency A reads {sorted(got)}"
    item = got[mine.id]
    assert set(item) == KEYS, item
    assert (item["slot_at"], item["status"], item["display_status"], item["reason"], item["remove_at"]) == (
        z(mine.slot_at), "scheduled", "Will be posted shortly", None, None), item
    assert set(item["partner"]) == PROJECTION_KEYS and set(item["own"]) == PROJECTION_KEYS, item
    assert (item["partner"]["display_name"], item["partner"]["username"]) == ("Fixture Beta", "fixture_beta")
    assert item["partner"]["profile_id"] == PID[B] and item["own"]["profile_id"] == PID[A], item
    for client, foreign in ((OWNER_A, B), (OWNER_B, A)):
        body = client.get(f"/admin/s4s/schedule?{month(mine.slot_at)}").text
        assert foreign not in body, f"another Agency's account id {foreign} in the schedule: {body}"

    got_b = schedule(OWNER_B, theirs.slot_at)
    assert theirs.id in got_b and mine.id not in got_b, f"Agency B reads {sorted(got_b)}"
    assert got_b[theirs.id]["partner"]["display_name"] == "Fixture Alpha"
    assert schedule(fx.login_owner("agency_master"), mine.slot_at) == {}, "the Master holds no Creator"

    june = "from=2030-06-01T00:00:00-05:00&to=2030-07-01T00:00:00-05:00"
    for at, listed in ((datetime(2030, 6, 1, 4, 59, 59), False), (datetime(2030, 6, 1, 5), True),
                       (datetime(2030, 7, 1, 4, 59, 59), True), (datetime(2030, 7, 1, 5), False)):
        db(update(S4SSlot).where(S4SSlot.id == mine.id).values(slot_at=at))
        r = OWNER_A.get(f"/admin/s4s/schedule?{june}")
        assert r.status_code == 200, f"GET schedule: {r.status_code} {r.text}"
        assert (mine.id in {item["id"] for item in r.json()}) is listed, f"slot at {at}Z listed should be {listed}"
    db(update(S4SSlot).where(S4SSlot.id == mine.id).values(slot_at=mine.slot_at))

    for bad in ("", "from=2030-06-01T00:00:00Z", "to=2030-07-01T00:00:00Z",
                "from=2030-06-01&to=2030-07-01", "from=2030-06-01T00:00:00&to=2030-07-01T00:00:00",
                "from=soon&to=later", "from=2030-07-01T00:00:00Z&to=2030-06-01T00:00:00Z",
                "from=2030-06-01T00:00:00Z&to=2030-08-01T00:00:00Z", "month=2030-06"):
        r = OWNER_A.get(f"/admin/s4s/schedule?{bad}")
        assert r.status_code == 422, f"{bad!r}: {r.status_code} {r.text}"


def case_each_slot_state_reads_as_its_display_status():
    slots = booked(OWNER_A, A, OWNER_B, B, day(41))
    mine = slots[A]

    async def posted_post(status: str) -> int:
        async with get_session() as s:
            p = Post(account_id=A, status=status, text="x")
            s.add(p)
            await s.flush()
            return p.id

    post_id = asyncio.run(posted_post("posted"))
    remove_at = mine.slot_at + timedelta(hours=24)
    states = [
        ({"status": "posting"}, ("posting", "In progress", None)),
        ({"status": "posted", "post_id": post_id, "posted_at": mine.slot_at, "remove_at": remove_at},
         ("posted", "In progress", None)),
        ({"status": "canceled", "reason": "live posting off", "post_id": None, "posted_at": None, "remove_at": None},
         ("canceled", "Canceled", "live posting off")),
        ({"status": "failed", "reason": "of_error 500"}, ("failed", "Failed", "of_error 500")),
    ]
    for values, want in states:
        db(update(S4SSlot).where(S4SSlot.id == mine.id).values(**values))
        assert reads(OWNER_A, mine) == want, (values, reads(OWNER_A, mine))

    db(update(S4SSlot).where(S4SSlot.id == mine.id).values(
        status="posted", reason=None, post_id=post_id, posted_at=mine.slot_at, remove_at=remove_at))
    item = schedule(OWNER_A, mine.slot_at)[mine.id]
    assert item["remove_at"] == z(remove_at), item
    db(update(Post).where(Post.id == post_id).values(status="deleted"))
    assert reads(OWNER_A, mine) == ("posted", "Completed", None)

    db(update(S4SSlot).where(S4SSlot.id == mine.id).values(
        status="scheduled", post_id=None, posted_at=None, remove_at=None))
    assert reads(OWNER_A, mine) == ("scheduled", "Will be posted shortly", None)
    db(update(ScheduledJob).where(ScheduledJob.id == mine.job_id).values(status="error"))
    assert reads(OWNER_A, mine) == ("scheduled", "Failed", "job_error")
    db(update(ScheduledJob).where(ScheduledJob.id == mine.job_id).values(status="pending"))



def case_cancelling_an_own_scheduled_slot_leaves_the_partners_slot_row_unchanged():
    slots = booked(OWNER_A, A, OWNER_B, B, day(42))
    mine, theirs = slots[A], slots[B]
    partner_row = raw_slot(theirs.id)
    audits = len(audit_rows("s4s.slot_cancel"))

    for client, slot_id, label in (
        (OWNER_A, theirs.id, "Agency A cancels Agency B's slot, whose partner it is"),
        (OWNER_B, mine.id, "Agency B cancels Agency A's slot"),
        (fx.login_owner("agency_master"), mine.id, "the Master cancels a slot it is no party to"),
        (OWNER_A, 999999, "no such slot"),
        (OWNER_A, "abc", "not an id"),
    ):
        r = cancel(client, slot_id)
        assert r.status_code == 404, f"{label}: {r.status_code} {r.text}"
    assert len(audit_rows("s4s.slot_cancel")) == audits, "a refused cancel wrote audit"

    r = cancel(OWNER_A, mine.id)
    assert r.status_code == 200, f"cancel: {r.status_code} {r.text}"
    assert set(r.json()) == KEYS, r.json()
    assert (r.json()["status"], r.json()["display_status"], r.json()["reason"]) == (
        "canceled", "Canceled", "owner_canceled"), r.json()
    (row,) = rows(S4SSlot, id=mine.id)
    assert (row.status, row.reason) == ("canceled", "owner_canceled")
    assert raw_slot(theirs.id) == partner_row, "the partner's slot row changed"
    got = audit_rows("s4s.slot_cancel")
    assert len(got) == audits + 1, len(got) - audits
    assert (got[-1].account_id, got[-1].employee_id, got[-1].target_type, got[-1].target_id) == (
        A, None, "s4s_slot", str(mine.id))
    payload = json.loads(got[-1].payload_json)
    assert payload == {"agency_user_id": IDS["agency_a_owner"], "slot_id": mine.id,
                       "request_id": mine.request_id, "reason": "owner_canceled"}, payload
    assert reads(OWNER_B, theirs) == ("scheduled", "Will be posted shortly", None)

    r = cancel(OWNER_A, mine.id)
    assert r.status_code == 409, f"a second cancel: {r.status_code} {r.text}"
    for state in ("posting", "posted", "failed"):
        db(update(S4SSlot).where(S4SSlot.id == mine.id).values(status=state, reason=None))
        r = cancel(OWNER_A, mine.id)
        assert r.status_code == 409, f"cancel a {state} slot: {r.status_code} {r.text}"
    assert len(audit_rows("s4s.slot_cancel")) == audits + 1
    assert raw_slot(theirs.id) == partner_row



def case_opting_out_cancels_own_open_requests_and_future_slots_and_writes_nothing_of_the_partner():
    future = booked(OWNER_B, B, OWNER_A, A, day(43))
    posted = booked(OWNER_A, A, OWNER_B, B, day(44))
    db(update(S4SSlot).where(S4SSlot.id == posted[A].id).values(status="posted"))
    sent_pending = sent(OWNER_A, A, B, day(45))
    received_skipped = sent(OWNER_B, B, A, day(46))
    assert act(OWNER_A, received_skipped["id"], "skip").status_code == 200
    inside = sent(OWNER_A, C, B, day(47))
    partner_rows = {s.id: raw_slot(s.id) for s in (future[B], posted[B])}
    own_scheduled = {s.id for s in rows(S4SSlot, poster_account_id=A, status="scheduled")}
    assert future[A].id in own_scheduled and posted[A].id not in own_scheduled
    request_audits, slot_audits = len(audit_rows("s4s.request_cancel")), len(audit_rows("s4s.slot_cancel"))

    assert OWNER_A.put(f"/admin/s4s/profiles/{A}", json={"daily_limit": 1}).status_code == 200
    assert len(audit_rows("s4s.request_cancel")) == request_audits

    r = OWNER_A.put(f"/admin/s4s/profiles/{A}", json={"opted_in": False})
    assert r.status_code == 200, f"opt out: {r.status_code} {r.text}"
    by_id = {q.id: q for q in rows(S4SRequest)}
    for rid in (sent_pending["id"], received_skipped["id"]):
        assert (by_id[rid].status, by_id[rid].cancel_reason) == ("cancelled", "opted_out"), (
            rid, by_id[rid].status, by_id[rid].cancel_reason)
    assert by_id[inside["id"]].status == "pending", "another Creator's request was cancelled"
    assert by_id[future[A].request_id].status == "accepted", "an answered request was rewritten"
    (own_future,) = rows(S4SSlot, id=future[A].id)
    assert (own_future.status, own_future.reason) == ("canceled", "opted_out")
    (own_posted,) = rows(S4SSlot, id=posted[A].id)
    assert (own_posted.status, own_posted.reason) == ("posted", None), "a posted slot was touched"
    for slot_id, before in partner_rows.items():
        assert raw_slot(slot_id) == before, f"the partner's slot {slot_id} changed in the database"

    assert reads(OWNER_B, future[B]) == ("scheduled", "Canceled", "partner_opted_out")
    assert reads(OWNER_A, future[A]) == ("canceled", "Canceled", "opted_out")
    assert box(OWNER_B, "received")[sent_pending["id"]]["status"] == "cancelled"
    assert box(OWNER_B, "sent")[received_skipped["id"]]["status"] == "cancelled"

    req_rows = audit_rows("s4s.request_cancel")[request_audits:]
    assert sorted(json.loads(a.payload_json)["request_id"] for a in req_rows) == sorted(
        [sent_pending["id"], received_skipped["id"]]), [a.payload_json for a in req_rows]
    for a in req_rows:
        payload = json.loads(a.payload_json)
        assert a.account_id == A and payload["agency_user_id"] == IDS["agency_a_owner"], payload
        assert payload["reason"] == "opted_out", payload
    assert {s.id for s in rows(S4SSlot, poster_account_id=A, status="scheduled")} == set(), "a future slot survived"
    slot_rows = audit_rows("s4s.slot_cancel")[slot_audits:]
    assert {json.loads(a.payload_json)["slot_id"] for a in slot_rows} == own_scheduled, [a.payload_json for a in slot_rows]
    for a in slot_rows:
        assert a.account_id == A and json.loads(a.payload_json)["reason"] == "opted_out", a.payload_json

    assert OWNER_A.put(f"/admin/s4s/profiles/{A}", json={"opted_in": False}).status_code == 200
    assert len(audit_rows("s4s.request_cancel")) == request_audits + 2
    assert OWNER_A.put(f"/admin/s4s/profiles/{A}", json={"opted_in": True}).status_code == 200
    assert reads(OWNER_B, future[B]) == ("scheduled", "Will be posted shortly", None)
    assert act(OWNER_A, inside["id"], "cancel").status_code == 200



def case_a_legacy_fansly_media_slot_whose_run_refused_reads_failed_and_the_row_is_not_written():
    slots = booked(OWNER_A, A, OWNER_B, FANSLY_B, day(60))
    legacy, of_side = slots[FANSLY_B], slots[A]
    media = json.dumps([{"id": 7001, "media_type": "photo"}])
    db(update(S4SRequest).where(S4SRequest.id == legacy.request_id).values(from_media_json=media, to_media_json=media))
    assert reads(OWNER_B, legacy) == ("scheduled", "Will be posted shortly", None), "a pending job reads failed"

    db(update(ScheduledJob).where(ScheduledJob.id.in_([legacy.job_id, of_side.job_id])).values(status="done"))
    before = raw_slot(legacy.id)
    assert reads(OWNER_B, legacy) == ("scheduled", "Failed", "platform_lacks:create_post:media")
    assert raw_slot(legacy.id) == before, "reading wrote the slot"
    assert reads(OWNER_A, of_side) == ("scheduled", "Will be posted shortly", None), "the OnlyFans poster reads failed"

    for values, want in (({"status": "posting"}, ("posting", "In progress", None)),
                         ({"status": "canceled", "reason": "owner_canceled"}, ("canceled", "Canceled", "owner_canceled"))):
        db(update(S4SSlot).where(S4SSlot.id == legacy.id).values(**values))
        assert reads(OWNER_B, legacy) == want, (values, reads(OWNER_B, legacy))
    db(update(S4SSlot).where(S4SSlot.id == legacy.id).values(status="scheduled", reason=None))
    assert raw_slot(legacy.id) == before

    db(update(S4SRequest).where(S4SRequest.id == legacy.request_id).values(from_media_json=None))
    assert reads(OWNER_B, legacy) == ("scheduled", "Will be posted shortly", None), "a text-only slot reads failed"



def _departs(partner_owner, partner: str, unlink, n: int, agency_left: bool) -> None:
    slots = booked(OWNER_A, A, partner_owner, partner, day(n))
    waiting = sent(partner_owner, partner, A, day(n + 1))
    outgoing = sent(OWNER_A, A, partner, day(n + 2))
    mine = slots[A]
    assert reads(OWNER_A, mine) == ("scheduled", "Will be posted shortly", None)
    assert box(OWNER_A, "received")[waiting["id"]]["status"] == "pending"
    assert box(OWNER_A, "sent")[outgoing["id"]]["status"] == "pending"
    mine_before = raw_slot(mine.id)

    unlink()

    assert reads(OWNER_A, mine) == ("scheduled", "Canceled", "partner_opted_out")
    assert raw_slot(mine.id) == mine_before, "reading wrote the slot"
    assert box(OWNER_A, "received")[waiting["id"]]["status"] == "cancelled"
    assert box(OWNER_A, "sent")[outgoing["id"]]["status"] == "cancelled"
    assert [r.status for r in rows(S4SRequest, id=outgoing["id"])] == ["pending"], "reading wrote the request"
    r = act(OWNER_A, waiting["id"], "accept")
    assert r.status_code == 409, f"accept a departed Creator's request: {r.status_code} {r.text}"
    assert not rows(S4SSlot, request_id=waiting["id"])
    if agency_left:
        assert slots[partner].id not in schedule(partner_owner, mine.slot_at), "its old Agency still reads the slot"


def case_a_creator_that_left_every_agency_stops_reading_as_live():
    _departs(OWNER_B, UNLINKED_B, lambda: db(delete(UserAccount).where(UserAccount.account_id == UNLINKED_B)), 50, True)


def case_a_creator_whose_agency_was_deleted_stops_reading_as_live():
    _departs(OWNER_C, ORPHAN_C, lambda: db(delete(User).where(User.username == "agency_c_owner")), 52, False)


_harness.run()
