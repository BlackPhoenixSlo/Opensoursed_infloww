#!/usr/bin/env python3
"""S4S block and the 50-a-day send limit (W7 row 7.11).

The seam is the Relay over HTTP on the two-Agency bench: Agency A blocks a
Creator from Discovery, the block hides it there and refuses requests either
way and an Accept made after it; a Creator's 51st request of the UTC day is
refused. No automation runs; nothing reaches OnlyFans.

Run: ./venv/bin/python service/tests/test_s4s_blocks.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import insert  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _s4s_fixtures import IDS, db, list_in_discovery, profile, seed_creators  # noqa: E402
from db.models import S4SRequest  # noqa: E402

A = IDS["creator_a"]
B = IDS["creator_b"]
C, D, HIDDEN = "1000061", "1000062", "1000063"  # C Agency A; D and HIDDEN Agency B
seed_creators({C: "agency_a_owner", D: "agency_b_owner", HIDDEN: "agency_b_owner"})
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
OWNER_OF = {A: OWNER_A, C: OWNER_A, B: OWNER_B, D: OWNER_B, HIDDEN: OWNER_B}
for _aid, _name in ((A, "Fixture Alpha"), (B, "Fixture Beta"), (C, "Fixture Gamma"), (D, "Fixture Delta")):
    list_in_discovery(OWNER_OF[_aid], _aid, _name, _name.lower().replace(" ", "_"))
list_in_discovery(OWNER_B, HIDDEN, "Fixture Hidden", "fixture_hidden", discovery_visible=False)
PID = {aid: profile(OWNER_OF[aid], aid)["profile_id"] for aid in OWNER_OF}


def day(n: int, hour: int = 10) -> datetime:
    today = datetime.utcnow().date()
    return datetime(today.year, today.month, today.day) + timedelta(days=n, hours=hour)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def send(from_id: str, to_id: str, n: int):
    return OWNER_OF[from_id].post("/admin/s4s/requests", json={
        "from_account_id": from_id, "to_profile_id": PID[to_id], "slot_at": z(day(n))})


def discover(client) -> set[int]:
    r = client.get("/admin/s4s/discover")
    assert r.status_code == 200, r.text
    return {p["profile_id"] for p in r.json()}


# ── Block ────────────────────────────────────────────────────────────

def case_a_block_hides_the_creator_from_the_agencys_discovery_only():
    assert PID[D] in discover(OWNER_A)
    r = OWNER_A.post("/admin/s4s/blocks", json={"profile_id": PID[D]})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["profile_id"] == PID[D] and got["display_name"] == "Fixture Delta" and got["blocked_at"], got
    assert "account_id" not in got, "a block leaks the Creator's account id"
    # Idempotent: one row.
    assert OWNER_A.post("/admin/s4s/blocks", json={"profile_id": PID[D]}).status_code == 200
    assert [b["profile_id"] for b in OWNER_A.get("/admin/s4s/blocks").json()] == [PID[D]]
    assert PID[D] not in discover(OWNER_A)
    assert PID[D] in discover(OWNER_B), "another Agency's Discovery lost the Creator"
    assert OWNER_B.get("/admin/s4s/blocks").json() == []
    assert OWNER_A.delete(f"/admin/s4s/blocks/{PID[D]}").status_code == 200
    assert PID[D] in discover(OWNER_A)


def case_a_block_refuses_requests_either_way_and_an_accept_after_it():
    # A request sent before the block, then the block, then the Accept.
    r = send(B, C, 1)
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]
    assert OWNER_A.post("/admin/s4s/blocks", json={"profile_id": PID[B]}).status_code == 200
    r = OWNER_A.post(f"/admin/s4s/requests/{request_id}/accept")
    assert r.status_code == 409 and "blocked" in r.json()["detail"], r.text
    # Neither side may send: the blocked one reads "not found", as for any unlisted partner.
    r = send(B, A, 2)
    assert r.status_code == 404 and r.json()["detail"] == "partner not found", r.text
    r = send(A, B, 2)
    assert r.status_code == 404, r.text
    # Unblock: they may again.
    r = OWNER_A.delete(f"/admin/s4s/blocks/{PID[B]}")
    assert r.status_code == 200 and r.json() == {"unblocked": PID[B]}, r.text
    assert OWNER_A.delete(f"/admin/s4s/blocks/{PID[B]}").status_code == 404
    assert send(B, A, 2).status_code == 201
    assert OWNER_A.post(f"/admin/s4s/requests/{request_id}/accept").status_code == 200


def case_only_a_listed_creator_of_another_agency_can_be_blocked():
    for pid, code in ((PID[HIDDEN], 404), (999999, 404), (PID[C], 400)):
        r = OWNER_A.post("/admin/s4s/blocks", json={"profile_id": pid})
        assert r.status_code == code, (pid, r.status_code, r.text)
    for body in ({"profile_id": "1"}, {"profile_id": True}, {}, {"profile_id": PID[B], "x": 1}):
        assert OWNER_A.post("/admin/s4s/blocks", json=body).status_code == 400, body


def case_signed_out_is_401_and_a_chatter_is_403_on_every_block_route():
    def every(client):
        return [("GET blocks", client.get("/admin/s4s/blocks")),
                ("POST blocks", client.post("/admin/s4s/blocks", json={"profile_id": PID[B]})),
                ("DELETE block", client.delete(f"/admin/s4s/blocks/{PID[B]}"))]
    for label, r in every(_harness.make_client()):
        assert r.status_code == 401, f"{label} signed out: {r.status_code}"
    for name in ("chatter_a", "chatter_ab"):
        for label, r in every(fx.login_chatter(name)):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code}"


# ── The daily send limit ─────────────────────────────────────────────

def case_a_creators_51st_request_of_the_utc_day_is_refused():
    now = datetime.utcnow()
    filler = [{"from_account_id": D, "to_account_id": A, "slot_at": day(40 + i), "from_caption": "x",
               "to_caption": "y", "from_projection_json": "{}", "to_projection_json": "{}",
               "status": "declined", "created_at": now} for i in range(49)]
    # Yesterday's do not count.
    filler.append({**filler[0], "slot_at": day(90), "created_at": now - timedelta(days=1, minutes=1)})
    db(insert(S4SRequest).values(filler))
    assert send(D, C, 3).status_code == 201  # the 50th today
    r = send(D, A, 4)
    assert r.status_code == 409 and "50" in r.json()["detail"], r.text
    assert send(B, C, 5).status_code == 201, "another Creator's count was shared"


_harness.run()
