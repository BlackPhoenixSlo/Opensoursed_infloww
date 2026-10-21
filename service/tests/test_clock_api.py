#!/usr/bin/env python3
"""Clock in and out, auto clock-out and the Owner edit on the Relay
(docs/spec/phase-02, tickets 11 and 13, as amended by w4-a: the inactivity-
only sweep). The w4-a additions (the agency-wide clock, the role gate,
clock-status, the heartbeat and the clock-records read) are in
test_clock_status_api.py.

The seam is the Relay over HTTP with real session cookies from the shared
two-Agency fixture (`/auth/login`, `/chatter/login`): every assertion is on a
status code, a response body or the rows an endpoint leaves behind.

Clocking happens at the server's "now", so each Shift here is laid around
the real clock (an hour either side), never at a fixed date. Each case has
its own chatters, seeded below, so one open Clock event never leaks into
another case. Time tracking is set per case through the owner's
PUT /admin/settings/time-tracking, the endpoint the Time tracking Panel saves to.

Run: ./venv/bin/python service/tests/test_clock_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from _clock_fixtures import (  # noqa: E402
    ON as _ON, create as _create, employee as _employee, event as _event, time_tracking as _time_tracking,
    utc_now as _utc_now, with_anonymous_admin as _with_anonymous_admin, z as _z,
)
import accounts as account_registry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    SETTINGS_EPOCH, Account, Action, Chatter, ChatterUser, ClockEvent, Employee, SettingsVersion, UserAccount,
)
from employees import get_or_create_mirror_employee  # noqa: E402

IDS = fx.seed_two_agencies()

# ASSUMPTION: this file seeds its own second Creator of Agency A, roster
# Employees and chatters, as test_shifts_api.py and test_agency_context.py
# do. Rung 3. Kept per-file because the three files seed different subsets;
# overturned when two files need the same rows and drift.
CREATOR_A2 = "1000013"


async def _seed() -> dict[str, int]:
    now = datetime.utcnow()
    out: dict[str, int] = {}
    async with get_session() as s:
        s.add(Account(id=CREATOR_A2, nickname="creator_a2", color="#aaaaaa"))
        (account_registry.ACCOUNTS_DIR / CREATOR_A2).mkdir()
        for key, owner in (("emp_a1", "agency_a_owner"), ("emp_b1", "agency_b_owner")):
            row = Employee(display_name=key, is_active=True, created_at=now, user_id=IDS[owner])
            s.add(row)
            await s.flush()
            out[key] = row.id
    async with get_session() as s:
        s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=CREATOR_A2))
        # ASSUMPTION: Agency A allows multiple employees per shift, so the
        # Shifts laid around now on Creator A are not refused by the overlap
        # rule (test_shifts_api.py tests that rule). Rung 5. Overturned if a
        # clock case needs the rule on in Agency A.
        s.add(SettingsVersion(user_id=IDS["agency_a_owner"], tab="sales", effective_from=SETTINGS_EPOCH,
                              config_json=json.dumps({"multi_employee_shift": True})))
    return out


EMP = asyncio.run(_seed())


def _stored_time_tracking(blob: dict) -> None:
    """Agency A's `time-tracking` blob written straight into the store: an odd
    value the PUT now refuses, as if saved before Phase 4 validated it."""
    fx.store_blob(IDS["agency_a_owner"], "time-tracking", blob)


def _sales(client, blob: dict) -> None:
    r = client.put("/admin/settings/sales", json=blob)
    assert r.status_code == 200, f"PUT sales: {r.status_code} {r.text}"


TT_OFF = {"detail": {"error": "time_tracking_off", "message": "time tracking is off"}}
OWNER_ACTS = {"detail": "owner sessions act as the agency"}

# The clock cases' own chatters, each linked to Agency A only.
_CLOCK_CHATTERS = (
    "clock_link", "clock_tie", "clock_free", "clock_off", "clock_odd",
    "clock_dup", "clock_race", "clock_out", "clock_other", "clock_idle",
    "clock_remind", "clock_later", "clock_seen", "clock_loose", "clock_sweep",
)


async def _seed_clock_chatters() -> dict[str, int]:
    now = datetime.utcnow()
    chatter_ids = {}
    async with get_session() as s:
        for name in _CLOCK_CHATTERS:
            chatter_ids[name] = uuid.uuid4().hex
            s.add(Chatter(id=chatter_ids[name], username=name, password=fx.PASSWORD,
                          display_name=name, color="#bbbbbb", created_at=now, last_seen_at=now))
    async with get_session() as s:
        for name in _CLOCK_CHATTERS:
            s.add(ChatterUser(chatter_id=chatter_ids[name], user_id=IDS["agency_a_owner"], created_at=now))
    # Each one's Mirror Employee in Agency A, so a Shift can be assigned to it
    # before it first clocks in.
    return {name: await get_or_create_mirror_employee(chatter_ids[name], IDS["agency_a_owner"],
                                                      display_name=name, color=None)
            for name in _CLOCK_CHATTERS}


MIRROR = asyncio.run(_seed_clock_chatters())


async def _ab_mirrors() -> dict[str, int]:
    return {owner: await get_or_create_mirror_employee(IDS["chatter_ab"], IDS[owner], display_name="chatter_ab",
                                                       color=None)
            for owner in ("agency_a_owner", "agency_b_owner")}


# Since w5-a nobody clocks until "Enable clock in and clock out for" is saved (Infloww's never-saved list is all
# unticked), so these cases' time tracking ticks the built-in Chatter, and every clocking chatter holds it in its
# Agency (test_clock_status_api.py tests the role gate itself).
ON = {**_ON, "role_ids": ["chatter"]}
_AB = asyncio.run(_ab_mirrors())
fx.store_blob(IDS["agency_a_owner"], "roles", {"roles": [], "assignments": {
    str(e): "chatter" for e in [*MIRROR.values(), _AB["agency_a_owner"]]}})
fx.store_blob(IDS["agency_b_owner"], "roles", {"roles": [], "assignments": {str(_AB["agency_b_owner"]): "chatter"}})


def _around_now(before_h: float, after_h: float) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    return {"start_utc": _z(now - timedelta(hours=before_h)), "end_utc": _z(now + timedelta(hours=after_h)),
            "tz": "UTC"}


def _clock_in(client, account_id: str, **extra):
    return client.post("/admin/shifts/clock-in", json={"account_id": account_id, **extra})


def _clock_out(client, clock_event_id):
    return client.post("/admin/shifts/clock-out", json={"clock_event_id": clock_event_id})


async def _clock_rows(employee_id: int) -> list[ClockEvent]:
    async with get_session() as s:
        return list((await s.execute(
            select(ClockEvent).where(ClockEvent.employee_id == employee_id).order_by(ClockEvent.id)
        )).scalars().all())


async def _clock_audit(event_id: int) -> list[dict]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Action).where(Action.target_type == "clock_event", Action.target_id == str(event_id))
            .order_by(Action.id)
        )).scalars().all()
    return [{"action": a.action, "employee_id": a.employee_id, "account_id": a.account_id,
             "payload": json.loads(a.payload_json)} for a in rows]


def _open_count(employee_id: int) -> int:
    return sum(1 for ev in asyncio.run(_clock_rows(employee_id)) if ev.out_utc is None)


def case_clock_endpoints_are_401_signed_out_and_an_owner_is_403_until_its_role_is_enabled():
    # Rewritten for w4-a: owners clock as their own row once Owner is ticked
    # (test_clock_status_api.py); with `role_ids` never saved they are 403.
    anon = _harness.make_client()

    def _calls(client):
        return [
            ("clock-in", _clock_in(client, IDS["creator_a"])),
            ("clock-out", _clock_out(client, 1)),
            ("me", client.get("/admin/shifts/me")),
            ("clock-status", client.get("/admin/shifts/clock-status")),
            ("clock-heartbeat", client.post("/admin/shifts/clock-heartbeat")),
        ]
    for label, r in _calls(anon):
        assert r.status_code == 401, f"{label} signed out: {r.status_code} {r.text}"
    for label, r in _with_anonymous_admin(lambda: _calls(anon)):
        assert r.status_code == 401, f"{label} with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    role_off = {"detail": {"error": "role_not_enabled", "message": "clock in is not enabled for your role"}}
    for name in ("agency_a_owner", "agency_master"):
        owner = fx.login_owner(name)
        _time_tracking(owner, ON)  # time tracking off is refused first (`_clock_gate`)
        for body in ({"account_id": IDS["creator_a"]}, {}, {"nope": 1}):
            r = owner.post("/admin/shifts/clock-in", json=body)
            assert r.status_code == 403 and r.json() == role_off, f"clock-in {body} as {name}: {r.status_code} {r.text}"
        r = owner.get("/admin/shifts/me")
        assert r.status_code == 403 and r.json() == OWNER_ACTS, f"me as {name}: {r.status_code} {r.text}"
        r = _clock_out(owner, 1)  # not its own row's event
        assert r.status_code == 404, f"clock-out as {name}: {r.status_code} {r.text}"
    async def _owner_rows():
        async with get_session() as s:
            return (await s.execute(select(ClockEvent.id).join(Employee, Employee.id == ClockEvent.employee_id)
                                    .where(Employee.chatter_id.like("owner:%")))).all()
    assert asyncio.run(_owner_rows()) == [], "an owner session wrote a Clock event"
    _time_tracking(fx.login_owner("agency_master"), {**ON, "enabled": False})


def case_clock_in_inside_an_assigned_occurrence_links_it_and_clock_out_closes_it_manual():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    emp = MIRROR["clock_link"]
    sid = _create(owner_a, **_around_now(1, 1), employee_ids=[emp], account_ids=[IDS["creator_a"]])["shift_id"]
    chatter = fx.login_chatter("clock_link")

    r = _clock_in(chatter, IDS["creator_a"])
    assert r.status_code == 200, f"clock-in: {r.status_code} {r.text}"
    ev = r.json()
    assert ev["shift_id"] == sid and ev["employee_id"] == emp and ev["account_id"] == IDS["creator_a"], ev
    assert ev["out_utc"] is None and ev["close_reason"] is None and ev["in_utc"].endswith("Z"), ev
    (row,) = asyncio.run(_clock_rows(emp))
    assert (row.id, row.agency_user_id, row.shift_id, row.out_utc) == \
        (ev["clock_event_id"], IDS["agency_a_owner"], sid, None), row

    r = _clock_out(chatter, ev["clock_event_id"])
    assert r.status_code == 200, f"clock-out: {r.status_code} {r.text}"
    out = r.json()
    assert out["clock_event_id"] == ev["clock_event_id"] and out["close_reason"] == "manual", out
    assert out["out_utc"] is not None and out["out_utc"] >= ev["in_utc"], out
    (row,) = asyncio.run(_clock_rows(emp))
    assert row.out_utc is not None and row.close_reason == "manual", row

    # Both writes carry their own audit row, with the employee as actor.
    rows = asyncio.run(_clock_audit(ev["clock_event_id"]))
    assert [a["action"] for a in rows] == ["clock.in", "clock.out"], rows
    for a in rows:
        assert a["payload"]["actor"] == f"employee:{emp}", a
        assert a["employee_id"] == emp and a["account_id"] == IDS["creator_a"], a
    assert rows[0]["payload"]["before"] is None and rows[0]["payload"]["after"]["out_utc"] is None, rows[0]
    assert rows[1]["payload"]["before"]["out_utc"] is None, rows[1]
    assert rows[1]["payload"]["after"]["close_reason"] == "manual", rows[1]


def case_clock_in_takes_the_earliest_starting_occurrence_then_the_lowest_id():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    emp = MIRROR["clock_tie"]
    mine = {"employee_ids": [emp], "account_ids": [IDS["creator_a"]]}
    two_hours_ago = _around_now(2, 1)  # once, so `same` below starts on the very same minute
    lower = _create(owner_a, **two_hours_ago, **mine)["shift_id"]
    earlier = _create(owner_a, **_around_now(3, 1), **mine)["shift_id"]
    chatter = fx.login_chatter("clock_tie")

    r = _clock_in(chatter, IDS["creator_a"])
    assert r.status_code == 200 and r.json()["shift_id"] == earlier, \
        f"earliest start should win over the lower id {lower}: {r.status_code} {r.text}"
    assert _clock_out(chatter, r.json()["clock_event_id"]).status_code == 200

    # Same start: the lower id wins. (Cancelled Shifts are not candidates.)
    assert owner_a.post(f"/admin/shifts/{earlier}/cancel").status_code == 200
    same = _create(owner_a, **two_hours_ago, **mine)["shift_id"]
    assert same > lower
    r = _clock_in(chatter, IDS["creator_a"])
    assert r.status_code == 200 and r.json()["shift_id"] == lower, f"lowest id: {r.status_code} {r.text}"
    assert _clock_out(chatter, r.json()["clock_event_id"]).status_code == 200

    # An explicit shift_id that is one of the matching occurrences is taken as named.
    r = _clock_in(chatter, IDS["creator_a"], shift_id=same)
    assert r.status_code == 200 and r.json()["shift_id"] == same, f"explicit: {r.status_code} {r.text}"
    assert _clock_out(chatter, r.json()["clock_event_id"]).status_code == 200


def case_clock_in_outside_any_shift_has_no_link_and_an_unassigned_shift_id_is_422():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    _time_tracking(owner_a, ON)
    emp = MIRROR["clock_free"]
    # Someone else's Shift now on Creator A, this Employee's own Shift on Creator A
    # tomorrow, a cancelled one now, and Agency B's Shift now: none of them is it.
    others = _create(owner_a, **_around_now(1, 1), employee_ids=[EMP["emp_a1"]],
                     account_ids=[IDS["creator_a"]])["shift_id"]
    later = _create(owner_a, **_around_now(-23, 25), employee_ids=[emp], account_ids=[IDS["creator_a"]])["shift_id"]
    cancelled = _create(owner_a, **_around_now(1, 1), employee_ids=[emp], account_ids=[IDS["creator_a"]])["shift_id"]
    assert owner_a.post(f"/admin/shifts/{cancelled}/cancel").status_code == 200
    on_a2 = _create(owner_a, **_around_now(1, 1), employee_ids=[emp], account_ids=[CREATOR_A2])["shift_id"]
    _sales(owner_b, {"multi_employee_shift": True})
    b_sid = _create(owner_b, **_around_now(1, 1), employee_ids=[EMP["emp_b1"]],
                    account_ids=[IDS["creator_b"]])["shift_id"]
    chatter = fx.login_chatter("clock_free")
    for bad, label in ((others, "another Employee's"), (later, "not running now"), (cancelled, "cancelled"),
                       (on_a2, "another Creator's"), (b_sid, "Agency B's"), (987654, "missing"),
                       ("1", "not an integer")):
        r = _clock_in(chatter, IDS["creator_a"], shift_id=bad)
        assert r.status_code == 422, f"shift_id {label}: {r.status_code} {r.text}"
    assert asyncio.run(_clock_rows(emp)) == [], "a refused clock-in wrote a Clock event"

    r = _clock_in(chatter, IDS["creator_a"])
    assert r.status_code == 200 and r.json()["shift_id"] is None, f"no Shift: {r.status_code} {r.text}"
    (row,) = asyncio.run(_clock_rows(emp))
    assert row.shift_id is None and row.account_id == IDS["creator_a"], row
    # A Creator outside the chatter's Agencies is refused before anything else.
    r = _clock_in(chatter, IDS["creator_b"])
    assert r.status_code == 403, f"Agency B's Creator: {r.status_code} {r.text}"
    assert _clock_out(chatter, row.id).status_code == 200


def case_time_tracking_off_refuses_clock_in_but_closes_an_open_event_and_stops_its_heartbeat():
    owner_a = fx.login_owner("agency_a_owner")
    emp = MIRROR["clock_off"]
    chatter = fx.login_chatter("clock_off")
    for blob, label in (({**ON, "enabled": False}, "off"), ({**ON, "enabled": "true"}, "the string 'true'"),
                        ({"auto_clock_out_minutes": 60}, "enabled missing")):
        _time_tracking(owner_a, ON)
        r = _clock_in(chatter, IDS["creator_a"])
        assert r.status_code == 200, f"clock-in while on, {label}: {r.status_code} {r.text}"
        open_id = r.json()["clock_event_id"]
        seen = next(row.last_seen_utc for row in asyncio.run(_clock_rows(emp)) if row.id == open_id)
        _stored_time_tracking(blob)

        # A heartbeat no longer renews the event, so the sweep can close it.
        assert chatter.post("/admin/shifts/clock-heartbeat").status_code == 200
        row = next(row for row in asyncio.run(_clock_rows(emp)) if row.id == open_id)
        assert row.last_seen_utc == seen, f"heartbeat while {label} renewed the event: {row.last_seen_utc}"
        r = _clock_in(fx.login_chatter("clock_idle"), IDS["creator_a"])
        assert r.status_code == 409 and r.json() == TT_OFF, \
            f"clock-in, {label}: {r.status_code} {r.text}"
        r = chatter.get("/admin/shifts/me")
        assert r.status_code == 200, f"me, {label}: {r.status_code} {r.text}"
        me = r.json()
        assert [a["time_tracking_enabled"] for a in me["accounts"]] == [False] * len(me["accounts"]), me
        assert [c["clock_event_id"] for c in me["open_clocks"]] == [open_id], me
        # The caller still closes its own open event.
        r = _clock_out(chatter, open_id)
        assert r.status_code == 200 and r.json()["close_reason"] == "manual", \
            f"clock-out, {label}: {r.status_code} {r.text}"
    assert asyncio.run(_clock_rows(MIRROR["clock_idle"])) == []
    _time_tracking(owner_a, ON)


def case_odd_stored_time_tracking_values_fall_back_and_do_not_break_clocking():
    owner_a = fx.login_owner("agency_a_owner")
    chatter = fx.login_chatter("clock_odd")
    # The invalid field is dropped; the rest of the stored blob still applies
    # (`enabled`, and `clock_in_reminder` where it is stored as true).
    for blob, label, want in (({"enabled": True, "auto_clock_out_minutes": "soon", "clock_in_reminder": "yes"},
                               "minutes a string", (True, False)),
                              ({"enabled": True, "auto_clock_out_minutes": 0}, "minutes 0", (True, False)),
                              ({"enabled": True, "auto_clock_out_minutes": 0, "clock_in_reminder": True},
                               "minutes 0, reminder on", (True, True)),
                              ({"enabled": True}, "minutes missing", (True, False))):
        _stored_time_tracking({**blob, "role_ids": ON["role_ids"]})
        r = _clock_in(chatter, IDS["creator_a"])
        assert r.status_code == 200, f"clock-in, {label}: {r.status_code} {r.text}"
        me = chatter.get("/admin/shifts/me").json()
        flags = {a["account_id"]: (a["time_tracking_enabled"], a["clock_in_reminder"]) for a in me["accounts"]}
        assert flags[IDS["creator_a"]] == want, f"{label}: {flags}"
        r = _clock_out(chatter, r.json()["clock_event_id"])
        assert r.status_code == 200, f"clock-out, {label}: {r.status_code} {r.text}"
    _time_tracking(owner_a, ON)


def case_a_second_clock_in_is_409_and_two_concurrent_ones_leave_one_open_event():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    chatter = fx.login_chatter("clock_dup")
    r = _clock_in(chatter, IDS["creator_a"])
    assert r.status_code == 200, f"first: {r.status_code} {r.text}"
    for acc in (IDS["creator_a"], CREATOR_A2):
        r = _clock_in(chatter, acc)
        assert r.status_code == 409 and r.json() == {"detail": "already clocked in"}, \
            f"second on {acc}: {r.status_code} {r.text}"
    assert _open_count(MIRROR["clock_dup"]) == 1

    # Two tabs, one click each, at the same instant. The two requests do not
    # always meet inside the database, so the race is run several times; each
    # round must leave exactly one open event, which is then closed.
    for round_no in range(8):
        clients = [fx.login_chatter("clock_race"), fx.login_chatter("clock_race")]
        barrier = threading.Barrier(len(clients))
        results: list = [None] * len(clients)

        def _fire(i: int) -> None:
            barrier.wait()
            try:
                results[i] = _clock_in(clients[i], IDS["creator_a"])
            except Exception as e:  # a 500 raised through the TestClient
                results[i] = e
        threads = [threading.Thread(target=_fire, args=(i,)) for i in range(len(clients))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        statuses = [getattr(r, "status_code", repr(r)) for r in results]
        assert sorted(statuses, key=str) == [200, 409], \
            f"round {round_no}, concurrent clock-ins: {statuses} {[getattr(r, 'text', r) for r in results]}"
        winner, loser = sorted(results, key=lambda r: r.status_code)
        assert loser.json() == {"detail": "already clocked in"}, loser.text
        assert _open_count(MIRROR["clock_race"]) == 1, f"round {round_no}"
        assert _clock_out(clients[0], winner.json()["clock_event_id"]).status_code == 200


def case_invalid_clock_outs_are_refused():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    _time_tracking(owner_a, ON)
    _time_tracking(owner_b, ON)
    chatter = fx.login_chatter("clock_out")
    other = fx.login_chatter("clock_other")

    # Nothing open: a missing id is 404, and a body without an id is 422.
    r = _clock_out(chatter, 987654)
    assert r.status_code == 404, f"none open: {r.status_code} {r.text}"
    for body in ({}, {"clock_event_id": "1"}, {"clock_event_id": True}):
        r = chatter.post("/admin/shifts/clock-out", json=body)
        assert r.status_code == 422, f"body {body}: {r.status_code} {r.text}"

    theirs = _clock_in(other, IDS["creator_a"]).json()["clock_event_id"]
    # Another Employee's open event, in the same Agency or from Agency B: 404, still open.
    for client, label in ((chatter, "same Agency"), (fx.login_chatter("chatter_b"), "Agency B's chatter")):
        r = _clock_out(client, theirs)
        assert r.status_code == 404, f"someone else's, {label}: {r.status_code} {r.text}"
    assert _open_count(MIRROR["clock_other"]) == 1

    mine = _clock_in(chatter, IDS["creator_a"]).json()["clock_event_id"]
    assert _clock_out(chatter, mine).status_code == 200
    r = _clock_out(chatter, mine)
    assert r.status_code == 409, f"already closed: {r.status_code} {r.text}"
    assert [a["action"] for a in asyncio.run(_clock_audit(mine))] == ["clock.in", "clock.out"]
    assert _clock_out(other, theirs).status_code == 200


def case_an_inactive_mirror_employee_cannot_clock():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    chatter = fx.login_chatter("clock_idle")
    r = _clock_in(chatter, IDS["creator_a"])
    assert r.status_code == 200, f"while active: {r.status_code} {r.text}"
    open_id = r.json()["clock_event_id"]
    r = owner_a.delete(f"/admin/employees/{MIRROR['clock_idle']}")
    assert r.status_code == 200, f"deactivate: {r.status_code} {r.text}"
    # Deactivating an Employee with a login unlinks it from the Agency and signs
    # it out (account_security.revoke_if_unlinked): it cannot clock in or out.
    r = _clock_out(chatter, open_id)
    assert r.status_code == 401, f"clock-out inactive: {r.status_code} {r.text}"
    r = _clock_in(chatter, CREATOR_A2)
    assert r.status_code == 401, f"clock-in inactive: {r.status_code} {r.text}"
    assert _open_count(MIRROR["clock_idle"]) == 1
    r = owner_a.patch(f"/admin/employees/{MIRROR['clock_idle']}", json={"is_active": True})
    assert r.status_code == 200, f"reactivate: {r.status_code} {r.text}"
    assert _clock_out(fx.login_chatter("clock_idle"), open_id).status_code == 200


def case_a_chatter_in_both_agencies_files_time_under_the_creators_agency_and_reads_only_its_own_rows():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    _time_tracking(owner_a, {**ON, "clock_in_reminder": True})
    _time_tracking(owner_b, {**ON, "enabled": False})
    ab = fx.login_chatter("chatter_ab")

    # Off in B, on in A, reported per Creator.
    r = ab.get("/admin/shifts/me")
    assert r.status_code == 200, f"me: {r.status_code} {r.text}"
    flags = {a["account_id"]: (a["display_name"], a["time_tracking_enabled"], a["clock_in_reminder"])
             for a in r.json()["accounts"]}
    assert flags == {IDS["creator_a"]: ("creator_a", True, True), CREATOR_A2: ("creator_a2", True, True),
                     IDS["creator_b"]: ("creator_b", False, False)}, flags
    r = _clock_in(ab, IDS["creator_b"])
    assert r.status_code == 409 and r.json() == TT_OFF, f"B off: {r.status_code} {r.text}"

    r = _clock_in(ab, IDS["creator_a"])
    assert r.status_code == 200, f"A: {r.status_code} {r.text}"
    on_a = r.json()
    _time_tracking(owner_b, ON)
    r = _clock_in(ab, IDS["creator_b"])
    assert r.status_code == 200, f"B on: {r.status_code} {r.text}"
    on_b = r.json()

    async def _rows():
        async with get_session() as s:
            evs = {ev.id: ev for ev in (await s.execute(select(ClockEvent).where(
                ClockEvent.id.in_([on_a["clock_event_id"], on_b["clock_event_id"]])))).scalars()}
            emps = {e.id: e.user_id for e in (await s.execute(select(Employee).where(
                Employee.id.in_([on_a["employee_id"], on_b["employee_id"]])))).scalars()}
            return evs, emps
    evs, emps = asyncio.run(_rows())
    assert evs[on_a["clock_event_id"]].agency_user_id == IDS["agency_a_owner"], "A's time not filed under A"
    assert evs[on_b["clock_event_id"]].agency_user_id == IDS["agency_b_owner"], "B's time not filed under B"
    assert emps == {on_a["employee_id"]: IDS["agency_a_owner"], on_b["employee_id"]: IDS["agency_b_owner"]}, \
        "each Agency's time is not on its own Mirror Employee"

    # Its own Shift in A, plus another Employee's Shift and open event on the
    # same Creator: the read holds the first and none of the others.
    own = _create(owner_a, **_around_now(-24, 26), employee_ids=[on_a["employee_id"]],
                  account_ids=[IDS["creator_a"]])["shift_id"]
    _create(owner_a, **_around_now(-24, 26), employee_ids=[MIRROR["clock_other"]], account_ids=[IDS["creator_a"]])
    _create(owner_a, **_around_now(-24 * 9, 24 * 9 + 2), employee_ids=[on_a["employee_id"]],
            account_ids=[IDS["creator_a"]])  # nine days out: past the read's eight
    other = _clock_in(fx.login_chatter("clock_other"), IDS["creator_a"])
    assert other.status_code == 200, other.text
    me = ab.get("/admin/shifts/me").json()
    assert sorted(c["clock_event_id"] for c in me["open_clocks"]) == \
        sorted([on_a["clock_event_id"], on_b["clock_event_id"]]), me["open_clocks"]
    assert {c["account_id"] for c in me["open_clocks"]} == {IDS["creator_a"], IDS["creator_b"]}, me["open_clocks"]
    assert [(o["shift_id"], o["account_id"]) for o in me["occurrences"]] == [(own, IDS["creator_a"])], \
        me["occurrences"]
    assert set(me["occurrences"][0]) >= {"shift_id", "occurrence_start", "occurrence_end", "account_id"}, me
    assert "employees" not in me["occurrences"][0], "another Employee's name reached the chatter"

    # Agency B's owner sees only B's event among its rows; each closes on its own.
    for ev in (on_a, on_b):
        r = _clock_out(ab, ev["clock_event_id"])
        assert r.status_code == 200 and r.json()["close_reason"] == "manual", f"{r.status_code} {r.text}"
    assert _clock_out(fx.login_chatter("clock_other"), other.json()["clock_event_id"]).status_code == 200


def _reminder(client):
    r = client.get("/admin/shifts/me")
    assert r.status_code == 200, f"me: {r.status_code} {r.text}"
    return r.json()["reminder"]


def case_the_reminder_needs_time_tracking_and_the_reminder_on_a_started_shift_and_no_open_event():
    owner_a = fx.login_owner("agency_a_owner")
    emp = MIRROR["clock_remind"]
    mine = {"employee_ids": [emp], "account_ids": [IDS["creator_a"]]}
    two_hours_ago = _around_now(2, 2)
    sid = _create(owner_a, **two_hours_ago, **mine)["shift_id"]
    later = _create(owner_a, **_around_now(1, 1), **mine)["shift_id"]  # also contains now, starts later
    chatter = fx.login_chatter("clock_remind")
    expected = {"shift_id": sid, "occurrence_start": two_hours_ago["start_utc"],
                "occurrence_end": two_hours_ago["end_utc"], "tz": "UTC", "account_id": IDS["creator_a"]}
    assert later != sid

    # Each of the four conditions alone withholds it; only literal `true` counts.
    for blob, label in (({**ON, "clock_in_reminder": False}, "reminder off"),
                        ({**ON, "enabled": False, "clock_in_reminder": True}, "time tracking off"),
                        ({**ON, "clock_in_reminder": "true"}, "reminder the string 'true'"),
                        ({"enabled": True}, "reminder missing")):
        _stored_time_tracking(blob)
        assert _reminder(chatter) is None, f"{label}: a reminder came back"

    _time_tracking(owner_a, {**ON, "clock_in_reminder": True})
    assert _reminder(chatter) == expected, "both on, a started Shift, nothing open: the earliest-started occurrence"

    r = _clock_in(chatter, IDS["creator_a"])
    assert r.status_code == 200, f"clock-in: {r.status_code} {r.text}"
    assert _reminder(chatter) is None, "an open Clock event still got a reminder"
    assert _clock_out(chatter, r.json()["clock_event_id"]).status_code == 200
    assert _reminder(chatter) == expected, "clocked out again inside the Shift: the reminder returns"

    # A cancelled Shift no longer reminds; the next started one takes over.
    assert owner_a.post(f"/admin/shifts/{sid}/cancel").status_code == 200
    assert _reminder(chatter)["shift_id"] == later, "a cancelled Shift still reminded"


def case_no_reminder_for_a_shift_that_has_not_started_or_belongs_to_someone_else():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, {**ON, "clock_in_reminder": True})
    _create(owner_a, **_around_now(-1, 3), employee_ids=[MIRROR["clock_later"]], account_ids=[IDS["creator_a"]])
    _create(owner_a, **_around_now(1, 1), employee_ids=[MIRROR["clock_loose"]], account_ids=[IDS["creator_a"]])
    me = fx.login_chatter("clock_later").get("/admin/shifts/me").json()
    assert len(me["occurrences"]) == 1, me  # its Shift is listed, starting in an hour
    assert me["reminder"] is None, f"a Shift that starts in an hour reminded: {me['reminder']}"


def _clocked_in(client):
    r = client.get("/admin/shifts/clocked-in")
    assert r.status_code == 200, f"clocked-in: {r.status_code} {r.text}"
    return r.json()


def case_clocked_in_lists_the_agencys_open_events_for_owners_and_is_403_for_chatters():
    anon = _harness.make_client()
    assert anon.get("/admin/shifts/clocked-in").status_code == 401
    r = _with_anonymous_admin(lambda: anon.get("/admin/shifts/clocked-in"))
    assert r.status_code == 401, f"with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    for name in ("clock_seen", "chatter_ab"):
        r = fx.login_chatter(name).get("/admin/shifts/clocked-in")
        assert r.status_code == 403, f"{name}: {r.status_code} {r.text}"

    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    _time_tracking(owner_a, ON)
    _time_tracking(owner_b, {**ON, "enabled": False})
    emp = MIRROR["clock_seen"]
    occ = _around_now(1, 1)
    sid = _create(owner_a, **occ, employee_ids=[emp], account_ids=[IDS["creator_a"]])["shift_id"]
    seen = fx.login_chatter("clock_seen")
    ev = _clock_in(seen, IDS["creator_a"]).json()
    loose = _clock_in(fx.login_chatter("clock_idle"), CREATOR_A2).json()  # outside any Shift
    closed = _clock_in(fx.login_chatter("clock_later"), IDS["creator_a"]).json()
    assert _clock_out(fx.login_chatter("clock_later"), closed["clock_event_id"]).status_code == 200

    a = _clocked_in(owner_a)
    assert a["time_tracking_enabled"] is True, a
    rows = {row["clock_event_id"]: row for row in a["clocked_in"]}
    assert rows[ev["clock_event_id"]] == {
        "clock_event_id": ev["clock_event_id"],
        "employee": {"id": emp, "display_name": "clock_seen"},
        "account": {"id": IDS["creator_a"], "display_name": "creator_a"},
        "in_utc": ev["in_utc"], "shift_id": sid,
        "shift": {"shift_id": sid, "occurrence_start": occ["start_utc"], "occurrence_end": occ["end_utc"],
                  "accounts": [{"id": IDS["creator_a"], "display_name": "creator_a"}]},
    }, rows[ev["clock_event_id"]]
    assert rows[loose["clock_event_id"]]["shift_id"] is None and rows[loose["clock_event_id"]]["shift"] is None
    assert rows[loose["clock_event_id"]]["account"] == {"id": CREATOR_A2, "display_name": "creator_a2"}
    assert closed["clock_event_id"] not in rows, "a closed event is listed as clocked in"
    assert [r["in_utc"] for r in a["clocked_in"]] == sorted(r["in_utc"] for r in a["clocked_in"]), a

    # Agency B and the Master see none of Agency A's events; time tracking is per Agency.
    b = _clocked_in(owner_b)
    assert b["time_tracking_enabled"] is False, b
    master = _clocked_in(fx.login_owner("agency_master"))
    for label, body in (("B", b), ("Master", master)):
        leaked = {r["clock_event_id"] for r in body["clocked_in"]} & {ev["clock_event_id"], loose["clock_event_id"]}
        assert not leaked, f"{label} sees Agency A's open events: {leaked}"

    # A cancelled Shift no longer names the occurrence; the link itself stays.
    assert owner_a.post(f"/admin/shifts/{sid}/cancel").status_code == 200
    row = {r["clock_event_id"]: r for r in _clocked_in(owner_a)["clocked_in"]}[ev["clock_event_id"]]
    assert row["shift_id"] == sid and row["shift"] is None, f"a cancelled Shift is still named: {row}"

    assert _clock_out(seen, ev["clock_event_id"]).status_code == 200
    assert _clock_out(fx.login_chatter("clock_idle"), loose["clock_event_id"]).status_code == 200
    assert ev["clock_event_id"] not in {r["clock_event_id"] for r in _clocked_in(owner_a)["clocked_in"]}


# ── Auto clock-out and the Owner edit (ticket 13) ───────────────────────
#
# Abandoned events are seeded straight into `clock_events` (and `actions` for
# the last activity) with past timestamps, so the deadline has already passed
# when a request arrives and no clock is mocked. Each event belongs to its own
# roster Employee of Agency A, seeded here, so one case's events never meet
# another's.

def _naive(z: str) -> datetime:
    return datetime.strptime(z, "%Y-%m-%dT%H:%M:%SZ")



async def _insert_activity(employee_id: int, at: datetime) -> None:
    async with get_session() as s:
        s.add(Action(employee_id=employee_id, account_id=IDS["creator_a"], action="test.activity", at=at))


def _activity(employee_id: int, at: datetime) -> None:
    asyncio.run(_insert_activity(employee_id, at))


async def _event_row(event_id: int) -> ClockEvent:
    async with get_session() as s:
        return await s.get(ClockEvent, event_id)


def _row(event_id: int) -> ClockEvent:
    return asyncio.run(_event_row(event_id))


async def _set_seen(event_id: int, at: datetime) -> None:
    async with get_session() as s:
        (await s.get(ClockEvent, event_id)).last_seen_utc = at


def _seen(event_id: int, at: datetime) -> None:
    """The event's last heartbeat (`last_seen_utc`), as POST /clock-heartbeat leaves it."""
    asyncio.run(_set_seen(event_id, at))


def case_an_abandoned_event_on_a_long_ended_shift_closes_auto_at_its_last_activity_plus_the_minutes():
    # Rewritten for w4-a: the Shift's end no longer decides; Infloww clocks
    # out on inactivity only.
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    _time_tracking(owner_a, {**ON, "auto_clock_out_minutes": 30})
    emp = _employee("sweep_shift")
    occ = _around_now(6, -4)  # ended four hours ago
    sid = _create(owner_a, **occ, employee_ids=[emp], account_ids=[IDS["creator_a"]])["shift_id"]
    ev_id = _event(emp, _naive(occ["start_utc"]) + timedelta(minutes=10), shift_id=sid)
    # Activity three hours after the Shift ended: it, not the occurrence end, decides.
    active = _utc_now() - timedelta(hours=1)
    _activity(emp, active)

    # Agency B's request sweeps only Agency B.
    _clocked_in(owner_b)
    assert _row(ev_id).out_utc is None, "Agency B's request closed Agency A's event"

    listed = _clocked_in(owner_a)
    assert ev_id not in {r["clock_event_id"] for r in listed["clocked_in"]}, "a swept event is still clocked in"
    row = _row(ev_id)
    assert row.close_reason == "auto", row.close_reason
    assert row.out_utc == active + timedelta(minutes=30), \
        f"out_utc {row.out_utc}, want the last activity {active} plus 30 minutes"

    (audit,) = asyncio.run(_clock_audit(ev_id))
    assert audit["action"] == "clock.auto_out" and audit["employee_id"] is None, audit
    assert audit["account_id"] == IDS["creator_a"], audit
    assert audit["payload"]["actor"] == "system", audit
    assert audit["payload"]["before"]["out_utc"] is None and audit["payload"]["before"]["close_reason"] is None, audit
    assert audit["payload"]["after"]["out_utc"] == _z(row.out_utc), audit
    assert audit["payload"]["after"]["close_reason"] == "auto", audit

    # A later request finds nothing more to close and writes no second row.
    _clocked_in(owner_a)
    assert len(asyncio.run(_clock_audit(ev_id))) == 1


def case_an_abandoned_event_with_no_shift_closes_at_last_activity_plus_the_minutes():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, {**ON, "auto_clock_out_minutes": 45})
    now = _utc_now()
    # A chatter's own request sweeps its Agency too.
    emp = MIRROR["clock_sweep"]
    ev_id = _event(emp, now - timedelta(hours=5))
    _activity(emp, now - timedelta(hours=6))  # before the clock-in: the clock-in is later
    _activity(emp, now - timedelta(hours=3))  # the latest audit row
    other = _employee("sweep_quiet")
    quiet_id = _event(other, now - timedelta(hours=5))  # nothing after its clock-in

    r = fx.login_chatter("clock_sweep").get("/admin/shifts/me")
    assert r.status_code == 200, f"me: {r.status_code} {r.text}"
    assert r.json()["open_clocks"] == [], r.json()["open_clocks"]
    row = _row(ev_id)
    assert (row.close_reason, row.out_utc) == ("auto", now - timedelta(hours=3) + timedelta(minutes=45)), \
        f"{row.close_reason} {row.out_utc}: want auto at the last activity plus 45 minutes"
    row = _row(quiet_id)
    assert (row.close_reason, row.out_utc) == ("auto", now - timedelta(hours=5) + timedelta(minutes=45)), \
        f"{row.close_reason} {row.out_utc}: want auto at the clock-in plus 45 minutes"
    assert [a["payload"]["actor"] for a in asyncio.run(_clock_audit(quiet_id))] == ["system"]


def case_an_event_not_yet_past_its_deadline_stays_open_past_its_shift_end_and_the_sweep_runs_with_time_tracking_off():
    # Rewritten for w4-a: the event past its Shift's end stays open because
    # its heartbeat is recent, not because of a grace after the Shift.
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, {**ON, "enabled": False, "auto_clock_out_minutes": 30})
    now = _utc_now()
    fresh = _event(_employee("sweep_fresh"), now - timedelta(minutes=20))  # deadline in ten minutes
    stale = _event(_employee("sweep_stale"), now - timedelta(minutes=40))  # deadline ten minutes ago
    # A Shift that ended fifteen minutes ago, its event clocked in near two
    # hours ago and seen five minutes ago: its deadline is 25 minutes away.
    emp = _employee("sweep_grace")
    occ = _around_now(2, -0.25)
    sid = _create(owner_a, **occ, employee_ids=[emp], account_ids=[IDS["creator_a"]])["shift_id"]
    grace = _event(emp, _naive(occ["start_utc"]) + timedelta(minutes=5), shift_id=sid)
    _seen(grace, now - timedelta(minutes=5))
    # The same, last seen 40 minutes ago: closed at that heartbeat plus 30.
    emp = _employee("sweep_gone")
    sid = _create(owner_a, **occ, employee_ids=[emp], account_ids=[IDS["creator_a"]])["shift_id"]
    gone = _event(emp, _naive(occ["start_utc"]) + timedelta(minutes=5), shift_id=sid)
    _seen(gone, now - timedelta(minutes=40))

    # Fired through the schedule read, so the sweep on the Shift router (not
    # only the Clock one) is what closes the stale event.
    r = owner_a.get("/admin/shifts", params={"from": _z(now - timedelta(days=1)), "to": _z(now + timedelta(days=1))})
    assert r.status_code == 200, f"GET /admin/shifts: {r.status_code} {r.text}"
    assert _row(fresh).out_utc is None and _row(grace).out_utc is None
    row = _row(stale)
    assert (row.close_reason, row.out_utc) == ("auto", now - timedelta(minutes=10)), \
        f"time tracking off: {row.close_reason} {row.out_utc}"
    row = _row(gone)
    assert (row.close_reason, row.out_utc) == ("auto", now - timedelta(minutes=10)), \
        f"last seen 40 minutes ago: {row.close_reason} {row.out_utc}"
    listed = {r["clock_event_id"] for r in _clocked_in(owner_a)["clocked_in"]}
    assert fresh in listed and grace in listed, f"an event inside its deadline was closed: {listed}"
    _time_tracking(owner_a, ON)


def case_a_non_number_or_missing_stored_minutes_makes_the_sweep_use_10():
    # Rewritten for w4-a: the default is Infloww's 10 minutes, not 60.
    owner_a = fx.login_owner("agency_a_owner")
    for i, (blob, label) in enumerate((({**ON, "auto_clock_out_minutes": "soon"}, "a string"),
                                       ({"enabled": True}, "missing"),
                                       ({**ON, "auto_clock_out_minutes": 0}, "zero"))):
        _stored_time_tracking(blob)
        now = _utc_now()
        old = _event(_employee(f"sweep_odd_{i}"), now - timedelta(hours=3))
        young = _event(_employee(f"sweep_odd_young_{i}"), now - timedelta(minutes=5))
        _clocked_in(owner_a)
        row = _row(old)
        assert (row.close_reason, row.out_utc) == ("auto", now - timedelta(hours=3) + timedelta(minutes=10)), \
            f"minutes {label}: {row.close_reason} {row.out_utc}, want the clock-in plus 10 minutes"
        assert _row(young).out_utc is None, f"minutes {label}: closed before 10 minutes"
    _time_tracking(owner_a, ON)


def _owner_edit(client, event_id, **body):
    return client.patch(f"/admin/shifts/clock-events/{event_id}", json=body)


def case_an_owner_edit_corrects_times_and_closing_an_open_event_marks_it_owner_edit():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    now = _utc_now()
    emp = _employee("edit_me")
    closed = _event(emp, now - timedelta(hours=5), now - timedelta(hours=4))
    r = _owner_edit(owner_a, closed, in_utc=_z(now - timedelta(hours=5, minutes=30)),
                    out_utc=_z(now - timedelta(hours=3, minutes=30)))
    assert r.status_code == 200, f"edit both: {r.status_code} {r.text}"
    body = r.json()
    assert (body["clock_event_id"], body["in_utc"], body["out_utc"], body["close_reason"]) == \
        (closed, _z(now - timedelta(hours=5, minutes=30)), _z(now - timedelta(hours=3, minutes=30)),
         "manual"), body
    row = _row(closed)
    assert (row.in_utc, row.out_utc) == (now - timedelta(hours=5, minutes=30), now - timedelta(hours=3, minutes=30))

    # One side alone: the other keeps its stored time.
    r = _owner_edit(owner_a, closed, out_utc=_z(now - timedelta(hours=3)))
    assert r.status_code == 200, f"edit out only: {r.status_code} {r.text}"
    assert (_row(closed).in_utc, _row(closed).out_utc) == (now - timedelta(hours=5, minutes=30),
                                                          now - timedelta(hours=3))

    opened = _event(emp, now - timedelta(minutes=20))  # inside its 60-minute deadline
    r = _owner_edit(owner_a, opened, in_utc=_z(now - timedelta(minutes=25)))
    assert r.status_code == 200 and r.json()["out_utc"] is None, f"open, in only: {r.status_code} {r.text}"
    r = _owner_edit(owner_a, opened, out_utc=_z(now - timedelta(minutes=5)))
    assert r.status_code == 200, f"close an open event: {r.status_code} {r.text}"
    row = _row(opened)
    assert (row.out_utc, row.close_reason) == (now - timedelta(minutes=5), "owner_edit"), row

    rows = asyncio.run(_clock_audit(opened))
    assert [a["action"] for a in rows] == ["clock.owner_edit", "clock.owner_edit"], rows
    last = rows[-1]
    assert last["payload"]["actor"] == f"owner:{IDS['agency_a_owner']}", last
    assert last["employee_id"] is None and last["account_id"] == IDS["creator_a"], last
    assert last["payload"]["before"]["out_utc"] is None and last["payload"]["before"]["close_reason"] is None, last
    assert last["payload"]["after"]["out_utc"] == _z(now - timedelta(minutes=5)), last
    assert last["payload"]["after"]["close_reason"] == "owner_edit", last
    assert [a["action"] for a in asyncio.run(_clock_audit(closed))] == ["clock.owner_edit"] * 2


def case_an_owner_edit_is_refused_in_the_future_inverted_overlapping_or_outside_the_agency():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    now = _utc_now()
    emp = _employee("edit_refused")
    first = _event(emp, now - timedelta(hours=5), now - timedelta(hours=4))
    second = _event(emp, now - timedelta(hours=3), now - timedelta(hours=2))
    # Another Employee's event over the same hours does not count as an overlap.
    _event(_employee("edit_neighbour"), now - timedelta(hours=5), now - timedelta(hours=1))

    for body, label in (({"out_utc": _z(now + timedelta(minutes=5))}, "ends in the future"),
                        ({"in_utc": _z(now - timedelta(hours=1))}, "in after out"),
                        ({"in_utc": _z(now - timedelta(hours=2))}, "in equal to out"),
                        ({}, "nothing to change"),
                        ({"in_utc": "soon"}, "not a time"),
                        ({"in_utc": "2026-01-01T00:00:00"}, "no zone")):
        r = _owner_edit(owner_a, second, **body)
        assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"

    r = _owner_edit(owner_a, second, in_utc=_z(now - timedelta(hours=4, minutes=30)))
    assert r.status_code == 409, f"overlap: {r.status_code} {r.text}"
    row = _row(second)
    assert (row.in_utc, row.out_utc) == (now - timedelta(hours=3), now - timedelta(hours=2)), "a refused edit wrote"
    assert asyncio.run(_clock_audit(second)) == [], "a refused edit wrote an audit row"
    # Touching is not overlapping.
    r = _owner_edit(owner_a, second, in_utc=_z(now - timedelta(hours=4)))
    assert r.status_code == 200, f"touching the other event: {r.status_code} {r.text}"
    # An open event runs on to now: an earlier one may not be stretched over it.
    opened = _event(emp, now - timedelta(minutes=30))
    r = _owner_edit(owner_a, second, out_utc=_z(now - timedelta(minutes=10)))
    assert r.status_code == 409, f"overlap with an open event: {r.status_code} {r.text}"
    assert _row(opened).out_utc is None

    # Another Agency's owner, the Master, a missing id: 404. A chatter: 403. Signed out: 401.
    for client, label in ((fx.login_owner("agency_b_owner"), "Agency B"), (fx.login_owner("agency_master"), "Master")):
        r = _owner_edit(client, first, out_utc=_z(now - timedelta(hours=4, minutes=30)))
        assert r.status_code == 404, f"{label}: {r.status_code} {r.text}"
    for bad in (987654, "x"):
        r = _owner_edit(owner_a, bad, out_utc=_z(now - timedelta(hours=4, minutes=30)))
        assert r.status_code == 404, f"id {bad!r}: {r.status_code} {r.text}"
    r = _owner_edit(fx.login_chatter("clock_seen"), first, out_utc=_z(now - timedelta(hours=4, minutes=30)))
    assert r.status_code == 403, f"chatter: {r.status_code} {r.text}"
    anon = _harness.make_client()
    assert _owner_edit(anon, first, out_utc=_z(now)).status_code == 401
    r = _with_anonymous_admin(lambda: _owner_edit(anon, first, out_utc=_z(now)))
    assert r.status_code == 401, f"with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    row = _row(first)
    assert (row.in_utc, row.out_utc) == (now - timedelta(hours=5), now - timedelta(hours=4)), "a refused edit wrote"

    # Agency B's owner edits its own event.
    b_ev = _event(_employee("edit_b", "agency_b_owner"), now - timedelta(hours=2), now - timedelta(hours=1),
                  owner="agency_b_owner")
    r = _owner_edit(fx.login_owner("agency_b_owner"), b_ev, out_utc=_z(now - timedelta(minutes=50)))
    assert r.status_code == 200, f"B's own: {r.status_code} {r.text}"
    (audit,) = asyncio.run(_clock_audit(b_ev))
    assert audit["payload"]["actor"] == f"owner:{IDS['agency_b_owner']}", audit


_harness.run(
    case_clock_endpoints_are_401_signed_out_and_an_owner_is_403_until_its_role_is_enabled,
    case_clock_in_inside_an_assigned_occurrence_links_it_and_clock_out_closes_it_manual,
    case_clock_in_takes_the_earliest_starting_occurrence_then_the_lowest_id,
    case_clock_in_outside_any_shift_has_no_link_and_an_unassigned_shift_id_is_422,
    case_time_tracking_off_refuses_clock_in_but_closes_an_open_event_and_stops_its_heartbeat,
    case_odd_stored_time_tracking_values_fall_back_and_do_not_break_clocking,
    case_a_second_clock_in_is_409_and_two_concurrent_ones_leave_one_open_event,
    case_invalid_clock_outs_are_refused,
    case_an_inactive_mirror_employee_cannot_clock,
    case_a_chatter_in_both_agencies_files_time_under_the_creators_agency_and_reads_only_its_own_rows,
    case_the_reminder_needs_time_tracking_and_the_reminder_on_a_started_shift_and_no_open_event,
    case_no_reminder_for_a_shift_that_has_not_started_or_belongs_to_someone_else,
    case_clocked_in_lists_the_agencys_open_events_for_owners_and_is_403_for_chatters,
    case_an_abandoned_event_on_a_long_ended_shift_closes_auto_at_its_last_activity_plus_the_minutes,
    case_an_abandoned_event_with_no_shift_closes_at_last_activity_plus_the_minutes,
    case_an_event_not_yet_past_its_deadline_stays_open_past_its_shift_end_and_the_sweep_runs_with_time_tracking_off,
    case_a_non_number_or_missing_stored_minutes_makes_the_sweep_use_10,
    case_an_owner_edit_corrects_times_and_closing_an_open_event_marks_it_owner_edit,
    case_an_owner_edit_is_refused_in_the_future_inverted_overlapping_or_outside_the_agency,
)
