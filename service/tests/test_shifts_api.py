#!/usr/bin/env python3
"""The Shift schedule's Relay router and storage (docs/spec/phase-02, tickets 08 to 10).

The seam is the Relay over HTTP with real session cookies from the shared
two-Agency fixture (`/auth/login`, `/chatter/login`): every assertion is on a
status code, a response body or the rows an endpoint leaves behind. Two
storage cases sit beside them: the migration's upgrade and downgrade run
through Alembic `Operations` on a fresh temp SQLite file, and the `init_db()`
catch-up rebuilds the three tables after they are dropped from the harness DB.

Run: ./venv/bin/python service/tests/test_shifts_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from db.engine import get_session, init_db  # noqa: E402
from db.models import (  # noqa: E402
    SETTINGS_EPOCH, Account, Action, ChatterAccountAccess, Employee, SettingsVersion, Shift, ShiftAssignment,
    UserAccount,
)
from employees import get_or_create_mirror_employee  # noqa: E402

IDS = fx.seed_two_agencies()

# ASSUMPTION: roster Employees and the second Creator of Agency A are this
# file's own seed, as in test_agency_context.py. Overturned once a third test
# file needs them (then move them into _agency_fixtures).
CREATOR_A2 = "1000013"


async def _seed() -> dict[str, int]:
    now = datetime.utcnow()
    out: dict[str, int] = {}
    async with get_session() as s:
        s.add(Account(id=CREATOR_A2, nickname="creator_a2", color="#aaaaaa"))
        (account_registry.ACCOUNTS_DIR / CREATOR_A2).mkdir()
        for key, owner in (("emp_a1", "agency_a_owner"), ("emp_a2", "agency_a_owner"),
                           ("emp_b1", "agency_b_owner"), ("emp_b2", "agency_b_owner")):
            row = Employee(display_name=key, is_active=True, created_at=now, user_id=IDS[owner])
            s.add(row)
            await s.flush()
            out[key] = row.id
    async with get_session() as s:
        s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=CREATOR_A2))
        # chatter_a may work only Creator A in Agency A, so Creator A2 is out.
        s.add(ChatterAccountAccess(chatter_id=IDS["chatter_a"], user_id=IDS["agency_a_owner"],
                                   account_id=IDS["creator_a"]))
        # ASSUMPTION: Agency A allows multiple employees per shift, so the
        # schedule cases (tickets 08-09), whose Shifts share Creator A at the
        # same times, are not refused by the overlap rule. The overlap cases
        # run in Agency B, whose `sales` blob starts absent. Rung 5.
        # Overturned if the overlap rule should be exercised in Agency A.
        s.add(SettingsVersion(user_id=IDS["agency_a_owner"], tab="sales", effective_from=SETTINGS_EPOCH,
                              config_json=json.dumps({"multi_employee_shift": True})))
    out["mirror_a"] = await get_or_create_mirror_employee(
        IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color=None)
    return out


EMP = asyncio.run(_seed())

# The week of Monday 2026-10-12, as a browser in UTC sends it.
WEEK = {"from": "2026-10-12T00:00:00.000Z", "to": "2026-10-19T00:00:00.000Z"}


def _week(client, **extra):
    return client.get("/admin/shifts", params={**WEEK, **extra})


def _shift_body(**over) -> dict:
    body = {
        "start_utc": "2026-10-13T09:00:00Z",
        "end_utc": "2026-10-13T17:00:00Z",
        "tz": "Europe/Ljubljana",
        "employee_ids": [EMP["emp_a1"]],
        "account_ids": [IDS["creator_a"]],
    }
    body.update(over)
    return body


def _create(client, **over) -> dict:
    r = client.post("/admin/shifts", json=_shift_body(**over))
    assert r.status_code == 200, f"create: {r.status_code} {r.text}"
    return r.json()


def _ids(resp) -> list[int]:
    return [o["shift_id"] for o in resp.json()["occurrences"]]


async def _shift_count() -> int:
    async with get_session() as s:
        return len((await s.execute(select(Shift.id))).all())


def _with_anonymous_admin(fn):
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        return fn()
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)


# ── Sessions: 401, 403 ───────────────────────────────────────────────

def _every_endpoint(client) -> list:
    # 401 and 403 come before 404, so an id that may not exist is fine here.
    return [
        ("GET /admin/shifts", _week(client)),
        ("POST /admin/shifts", client.post("/admin/shifts", json=_shift_body())),
        ("PATCH /admin/shifts/1", client.patch("/admin/shifts/1", json=_shift_body())),
        ("POST /admin/shifts/1/cancel", client.post("/admin/shifts/1/cancel")),
    ]


def case_signed_out_is_401_on_every_endpoint_with_and_without_anonymous_admin():
    before = asyncio.run(_shift_count())
    anon = _harness.make_client()
    for label, r in _every_endpoint(anon):
        assert r.status_code == 401, f"{label} signed out: {r.status_code} {r.text}"
    for label, r in _with_anonymous_admin(lambda: _every_endpoint(anon)):
        assert r.status_code == 401 and r.json() == {"detail": "sign in required"}, \
            f"{label} with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"
    # A signed-out caller with a broken body still gets 401, never 422.
    r = _with_anonymous_admin(lambda: anon.post("/admin/shifts", json={"nope": 1}))
    assert r.status_code == 401, f"bad body signed out: {r.status_code} {r.text}"
    assert asyncio.run(_shift_count()) == before, "a signed-out call wrote a Shift"


def case_chatter_is_403_on_owner_endpoints():
    before = asyncio.run(_shift_count())
    for name in ("chatter_a", "chatter_ab"):
        chatter = fx.login_chatter(name)
        for label, r in _every_endpoint(chatter):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code} {r.text}"
        r = _week(chatter, account_id=IDS["creator_a"])
        assert r.status_code == 403, f"GET with own Creator as {name}: {r.status_code} {r.text}"
        r = chatter.post("/admin/shifts", json={"nope": 1})
        assert r.status_code == 403, f"bad body as {name}: {r.status_code} {r.text}"
    assert asyncio.run(_shift_count()) == before, "a chatter wrote a Shift"


# ── Create and the week read ─────────────────────────────────────────

def case_created_shift_shows_in_its_week_with_time_employees_and_creators():
    owner_a = fx.login_owner("agency_a_owner")
    made = _create(owner_a, employee_ids=[EMP["emp_a1"], EMP["emp_a2"]],
                   account_ids=[IDS["creator_a"], CREATOR_A2])
    sid = made["shift_id"]
    assert made["start_utc"] == "2026-10-13T09:00:00Z" and made["end_utc"] == "2026-10-13T17:00:00Z", made
    assert made["status"] == "scheduled", made

    r = _week(owner_a)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    item = next(o for o in r.json()["occurrences"] if o["shift_id"] == sid)
    assert item == {
        "shift_id": sid,
        "occurrence_start": "2026-10-13T09:00:00Z",
        "occurrence_end": "2026-10-13T17:00:00Z",
        "start_utc": "2026-10-13T09:00:00Z",
        "end_utc": "2026-10-13T17:00:00Z",
        "tz": "Europe/Ljubljana",
        "repeat_days": None,
        "repeat_until": None,
        "employees": [{"id": EMP["emp_a1"], "display_name": "emp_a1"},
                      {"id": EMP["emp_a2"], "display_name": "emp_a2"}],
        "accounts": [{"id": IDS["creator_a"], "display_name": "creator_a"},
                     {"id": CREATOR_A2, "display_name": "creator_a2"}],
    }, item

    # One assignment row per (Employee, Creator) pair, and the Shift is A's.
    async def _rows():
        async with get_session() as s:
            pairs = (await s.execute(select(ShiftAssignment.employee_id, ShiftAssignment.account_id)
                                     .where(ShiftAssignment.shift_id == sid))).all()
            shift = await s.get(Shift, sid)
            return sorted(tuple(p) for p in pairs), shift.agency_user_id, shift.created_by
    pairs, agency, created_by = asyncio.run(_rows())
    assert pairs == sorted([(EMP["emp_a1"], IDS["creator_a"]), (EMP["emp_a1"], CREATOR_A2),
                            (EMP["emp_a2"], IDS["creator_a"]), (EMP["emp_a2"], CREATOR_A2)]), pairs
    assert agency == IDS["agency_a_owner"], agency
    assert created_by == f"owner:{IDS['agency_a_owner']}", created_by


def case_week_holds_shifts_that_intersect_it_and_nothing_else():
    owner_a = fx.login_owner("agency_a_owner")
    # Sunday 22:00 → Monday 02:00 crosses the week's start: in.
    edge_in = _create(owner_a, start_utc="2026-10-11T22:00:00Z", end_utc="2026-10-12T02:00:00Z")["shift_id"]
    # Ends exactly at the week's start: out ([from, to) is half open).
    edge_out = _create(owner_a, start_utc="2026-10-11T20:00:00Z", end_utc="2026-10-12T00:00:00Z")["shift_id"]
    # Starts exactly at the week's end: out.
    after = _create(owner_a, start_utc="2026-10-19T00:00:00Z", end_utc="2026-10-19T08:00:00Z")["shift_id"]
    ids = _ids(_week(owner_a))
    assert edge_in in ids, ids
    assert edge_out not in ids and after not in ids, ids
    # The next week holds the later one.
    r = owner_a.get("/admin/shifts", params={"from": "2026-10-19T00:00:00Z", "to": "2026-10-26T00:00:00Z"})
    assert after in _ids(r) and edge_in not in _ids(r), r.json()


def case_occurrences_come_back_in_start_order():
    owner_a = fx.login_owner("agency_a_owner")
    late = _create(owner_a, start_utc="2026-10-16T09:00:00Z", end_utc="2026-10-16T10:00:00Z")["shift_id"]
    early = _create(owner_a, start_utc="2026-10-14T09:00:00Z", end_utc="2026-10-14T10:00:00Z")["shift_id"]
    starts = [o["occurrence_start"] for o in _week(owner_a).json()["occurrences"]]
    assert starts == sorted(starts), starts
    ids = _ids(_week(owner_a))
    assert ids.index(early) < ids.index(late), ids


def case_cancelled_shifts_are_absent():
    owner_a = fx.login_owner("agency_a_owner")
    sid = _create(owner_a, start_utc="2026-10-15T09:00:00Z", end_utc="2026-10-15T12:00:00Z")["shift_id"]
    assert sid in _ids(_week(owner_a))

    # No cancel endpoint yet (ticket 09): the row is cancelled in place.
    async def _cancel():
        async with get_session() as s:
            await s.execute(update(Shift).where(Shift.id == sid)
                            .values(status="cancelled", cancelled_at=datetime.utcnow()))
    asyncio.run(_cancel())
    assert sid not in _ids(_week(owner_a)), "a cancelled Shift is still in the week"


def case_filters_by_employee_and_by_creator():
    owner_a = fx.login_owner("agency_a_owner")
    one = _create(owner_a, start_utc="2026-10-17T09:00:00Z", end_utc="2026-10-17T11:00:00Z",
                  employee_ids=[EMP["emp_a1"]], account_ids=[IDS["creator_a"]])["shift_id"]
    two = _create(owner_a, start_utc="2026-10-17T12:00:00Z", end_utc="2026-10-17T14:00:00Z",
                  employee_ids=[EMP["emp_a2"]], account_ids=[CREATOR_A2])["shift_id"]
    by_emp2 = _week(owner_a, employee_id=EMP["emp_a2"])
    assert by_emp2.status_code == 200, by_emp2.text
    assert two in _ids(by_emp2) and one not in _ids(by_emp2), by_emp2.json()
    for o in by_emp2.json()["occurrences"]:
        assert EMP["emp_a2"] in [e["id"] for e in o["employees"]], o
    by_a2 = _week(owner_a, account_id=CREATOR_A2)
    assert by_a2.status_code == 200, by_a2.text
    assert two in _ids(by_a2) and one not in _ids(by_a2), by_a2.json()
    for o in by_a2.json()["occurrences"]:
        assert CREATOR_A2 in [a["id"] for a in o["accounts"]], o
    both = _week(owner_a, employee_id=EMP["emp_a1"], account_id=CREATOR_A2)
    assert one not in _ids(both) and two not in _ids(both), both.json()


def case_range_rules():
    owner_a = fx.login_owner("agency_a_owner")
    ok = owner_a.get("/admin/shifts", params={"from": "2026-10-12T00:00:00Z", "to": "2026-11-23T00:00:00Z"})
    assert ok.status_code == 200, f"42 days: {ok.status_code} {ok.text}"
    for label, params in (
        ("43 days", {"from": "2026-10-12T00:00:00Z", "to": "2026-11-24T00:00:00Z"}),
        ("to before from", {"from": "2026-10-19T00:00:00Z", "to": "2026-10-12T00:00:00Z"}),
        ("empty range", {"from": "2026-10-12T00:00:00Z", "to": "2026-10-12T00:00:00Z"}),
        ("not a time", {"from": "monday", "to": "2026-10-19T00:00:00Z"}),
        ("no zone", {"from": "2026-10-12T00:00:00", "to": "2026-10-19T00:00:00"}),
        ("missing to", {"from": "2026-10-12T00:00:00Z"}),
    ):
        r = owner_a.get("/admin/shifts", params=params)
        assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"


def case_invalid_create_bodies_are_422_and_write_nothing():
    owner_a = fx.login_owner("agency_a_owner")
    before = asyncio.run(_shift_count())
    for label, over in (
        ("end before start", {"end_utc": "2026-10-13T08:00:00Z"}),
        ("end equals start", {"end_utc": "2026-10-13T09:00:00Z"}),
        ("over 24 hours", {"end_utc": "2026-10-14T09:00:01Z"}),
        ("unknown tz", {"tz": "Mars/Olympus"}),
        ("no Employee", {"employee_ids": []}),
        ("no Creator", {"account_ids": []}),
        ("unknown Employee", {"employee_ids": [987654]}),
        ("unknown Creator", {"account_ids": ["9999999"]}),
        ("no zone on a time", {"start_utc": "2026-10-13T09:00:00"}),
        ("weekday 0", {"repeat_days": [0, 3]}),
        ("weekday 8", {"repeat_days": [8]}),
        ("weekday as text", {"repeat_days": ["1"]}),
        ("no weekday", {"repeat_days": []}),
        ("repeat_days not a list", {"repeat_days": 2}),
        ("repeat_until without repeat_days", {"repeat_until": "2026-12-31"}),
        ("repeat_until not a date", {"repeat_days": [2], "repeat_until": "soon"}),
        ("repeat_until before the start's local date",
         {"repeat_days": [2], "repeat_until": "2026-10-12"}),
        ("unknown tz on a repeat", {"repeat_days": [2], "tz": "Mars/Olympus"}),
    ):
        r = owner_a.post("/admin/shifts", json=_shift_body(**over))
        assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"
    r = owner_a.post("/admin/shifts", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 422, f"not JSON: {r.status_code} {r.text}"
    assert asyncio.run(_shift_count()) == before, "a refused create wrote a Shift"
    # Null repeat fields ask for no repeat, so they are accepted.
    _create(owner_a, start_utc="2026-10-17T09:00:00Z", end_utc="2026-10-17T10:00:00Z",
            repeat_days=None, repeat_until=None)
    # Exactly 24 hours is allowed.
    _create(owner_a, start_utc="2026-10-18T00:00:00Z", end_utc="2026-10-19T00:00:00Z")


# ── Agency isolation ─────────────────────────────────────────────────

def case_a_shift_of_agency_a_is_never_seen_by_owner_b():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    sid = _create(owner_a, start_utc="2026-10-14T13:00:00Z", end_utc="2026-10-14T15:00:00Z")["shift_id"]
    assert sid in _ids(_week(owner_a))
    r = _week(owner_b)
    assert r.status_code == 200, r.text
    assert sid not in _ids(r), "owner B sees Agency A's Shift"
    b_sid = _create(owner_b, employee_ids=[EMP["emp_b1"]], account_ids=[IDS["creator_b"]])["shift_id"]
    assert _ids(_week(owner_b)) == [b_sid], _week(owner_b).json()
    assert b_sid not in _ids(_week(owner_a)), "owner A sees Agency B's Shift"
    # The Master's own Agency holds none of them.
    assert _ids(_week(fx.login_owner("agency_master"))) == []


def case_body_references_to_the_other_agency_are_422_in_both_directions():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    before = asyncio.run(_shift_count())
    for client, label, over in (
        (owner_a, "A names B's Employee", {"employee_ids": [EMP["emp_a1"], EMP["emp_b1"]]}),
        (owner_a, "A names B's Creator", {"account_ids": [IDS["creator_a"], IDS["creator_b"]]}),
        (owner_b, "B names A's Employee", {"employee_ids": [EMP["emp_a1"]], "account_ids": [IDS["creator_b"]]}),
        (owner_b, "B names A's Creator", {"employee_ids": [EMP["emp_b1"]], "account_ids": [IDS["creator_a"]]}),
    ):
        r = client.post("/admin/shifts", json=_shift_body(**over))
        assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"
    # A Master cannot put Agency A's Employee or Creator in a Shift either.
    master = fx.login_owner("agency_master")
    r = master.post("/admin/shifts", json=_shift_body())
    assert r.status_code == 422, f"Master names A's refs: {r.status_code} {r.text}"
    assert asyncio.run(_shift_count()) == before, "a cross-agency create wrote a Shift"


def case_filters_naming_the_other_agency_are_refused():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    r = _week(owner_a, employee_id=EMP["emp_b1"])
    assert r.status_code == 422, f"A filters by B's Employee: {r.status_code} {r.text}"
    r = _week(owner_b, employee_id=EMP["emp_a1"])
    assert r.status_code == 422, f"B filters by A's Employee: {r.status_code} {r.text}"
    # A Creator the session does not own is the isolation gate's 403.
    r = _week(owner_a, account_id=IDS["creator_b"])
    assert r.status_code == 403, f"A filters by B's Creator: {r.status_code} {r.text}"
    r = _week(owner_b, account_id=IDS["creator_a"])
    assert r.status_code == 403, f"B filters by A's Creator: {r.status_code} {r.text}"
    # The Master may name any Creator, but not one outside its own Agency.
    r = _week(fx.login_owner("agency_master"), account_id=IDS["creator_a"])
    assert r.status_code == 422, f"Master filters by A's Creator: {r.status_code} {r.text}"


# ── Weekly repeats, read back through the week GET ──────────────────

NY = "America/New_York"


def _occ(client, sid: int, frm: str, to: str) -> list[tuple[str, str]]:
    r = client.get("/admin/shifts", params={"from": frm, "to": to})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return [(o["occurrence_start"], o["occurrence_end"])
            for o in r.json()["occurrences"] if o["shift_id"] == sid]


def case_weekly_repeat_never_reads_back_in_later_weeks():
    owner_a = fx.login_owner("agency_a_owner")
    # Monday 12 Oct 2026, 09:00–11:00 EDT, every Monday and Wednesday, "Never".
    made = _create(owner_a, start_utc="2026-10-12T13:00:00Z", end_utc="2026-10-12T15:00:00Z",
                   tz=NY, repeat_days=[3, 1], repeat_until=None)
    sid = made["shift_id"]
    assert made["repeat_days"] == [1, 3] and made["repeat_until"] is None, made
    assert _occ(owner_a, sid, "2026-10-12T00:00:00Z", "2026-10-19T00:00:00Z") == [
        ("2026-10-12T13:00:00Z", "2026-10-12T15:00:00Z"),
        ("2026-10-14T13:00:00Z", "2026-10-14T15:00:00Z"),
    ]
    assert _occ(owner_a, sid, "2026-10-19T00:00:00Z", "2026-10-26T00:00:00Z") == [
        ("2026-10-19T13:00:00Z", "2026-10-19T15:00:00Z"),
        ("2026-10-21T13:00:00Z", "2026-10-21T15:00:00Z"),
    ]
    # A year on, in EST, still 09:00 local: 14:00Z.
    assert _occ(owner_a, sid, "2027-11-29T00:00:00Z", "2027-12-06T00:00:00Z") == [
        ("2027-11-29T14:00:00Z", "2027-11-29T16:00:00Z"),
        ("2027-12-01T14:00:00Z", "2027-12-01T16:00:00Z"),
    ]
    # Nothing before the first occurrence.
    assert _occ(owner_a, sid, "2026-10-05T00:00:00Z", "2026-10-12T00:00:00Z") == []
    item = next(o for o in _week(owner_a).json()["occurrences"] if o["shift_id"] == sid)
    assert item["repeat_days"] == [1, 3] and item["repeat_until"] is None, item
    assert item["start_utc"] == "2026-10-12T13:00:00Z", item


def case_repeat_until_is_the_last_local_date_inclusive():
    owner_a = fx.login_owner("agency_a_owner")
    # Friday 16 Oct 2026, 21:00–23:00 EDT = Saturday 01:00–03:00Z, every
    # Friday through Friday 30 Oct. The last one starts on Saturday 31 Oct in
    # UTC but on Friday 30 Oct in New York, so it is in.
    made = _create(owner_a, start_utc="2026-10-17T01:00:00Z", end_utc="2026-10-17T03:00:00Z",
                   tz=NY, repeat_days=[5], repeat_until="2026-10-30")
    sid = made["shift_id"]
    assert made["repeat_until"] == "2026-10-30", made
    assert _occ(owner_a, sid, "2026-10-19T00:00:00Z", "2026-10-26T00:00:00Z") == [
        ("2026-10-24T01:00:00Z", "2026-10-24T03:00:00Z"),
    ]
    assert _occ(owner_a, sid, "2026-10-26T00:00:00Z", "2026-11-02T00:00:00Z") == [
        ("2026-10-31T01:00:00Z", "2026-10-31T03:00:00Z"),
    ]
    assert _occ(owner_a, sid, "2026-11-02T00:00:00Z", "2026-11-09T00:00:00Z") == []
    item = next(o for o in owner_a.get("/admin/shifts", params={
        "from": "2026-10-26T00:00:00Z", "to": "2026-11-02T00:00:00Z"}).json()["occurrences"]
        if o["shift_id"] == sid)
    assert item["repeat_until"] == "2026-10-30", item


def case_new_york_repeats_keep_local_time_across_spring_forward_and_fall_back():
    owner_a = fx.login_owner("agency_a_owner")
    # Every Sunday from 25 Oct 2026. New York falls back on Sunday 1 Nov 2026
    # (02:00 EDT → 01:00 EST) and springs forward on Sunday 14 Mar 2027
    # (02:00 EST → 03:00 EDT). Each expected value is worked by hand.
    day = _create(owner_a, start_utc="2026-10-25T13:00:00Z", end_utc="2026-10-25T21:00:00Z",
                  tz=NY, repeat_days=[7])["shift_id"]          # 09:00–17:00 EDT
    gap = _create(owner_a, start_utc="2026-10-25T06:30:00Z", end_utc="2026-10-25T08:30:00Z",
                  tz=NY, repeat_days=[7])["shift_id"]          # 02:30–04:30 EDT
    fold = _create(owner_a, start_utc="2026-10-25T05:30:00Z", end_utc="2026-10-25T07:30:00Z",
                   tz=NY, repeat_days=[7])["shift_id"]         # 01:30–03:30 EDT

    fall = ("2026-10-26T00:00:00Z", "2026-11-02T00:00:00Z")
    # 09:00–17:00 EST.
    assert _occ(owner_a, day, *fall) == [("2026-11-01T14:00:00Z", "2026-11-01T22:00:00Z")]
    # 01:30 happens twice: the first instant, 01:30 EDT (05:30Z), to 03:30 EST
    # (08:30Z), three real hours.
    assert _occ(owner_a, fold, *fall) == [("2026-11-01T05:30:00Z", "2026-11-01T08:30:00Z")]
    # 02:30–04:30 EST, an ordinary night.
    assert _occ(owner_a, gap, *fall) == [("2026-11-01T07:30:00Z", "2026-11-01T09:30:00Z")]

    before_spring = ("2027-03-01T00:00:00Z", "2027-03-08T00:00:00Z")
    assert _occ(owner_a, day, *before_spring) == [("2027-03-07T14:00:00Z", "2027-03-07T22:00:00Z")]
    assert _occ(owner_a, gap, *before_spring) == [("2027-03-07T07:30:00Z", "2027-03-07T09:30:00Z")]

    spring = ("2027-03-08T00:00:00Z", "2027-03-15T00:00:00Z")
    # 09:00–17:00 EDT.
    assert _occ(owner_a, day, *spring) == [("2027-03-14T13:00:00Z", "2027-03-14T21:00:00Z")]
    # 02:30 does not exist: it resolves forward to 03:30 EDT (07:30Z), and the
    # end stays 04:30 EDT (08:30Z), one real hour.
    assert _occ(owner_a, gap, *spring) == [("2027-03-14T07:30:00Z", "2027-03-14T08:30:00Z")]
    # 01:30 EST is ordinary that night.
    assert _occ(owner_a, fold, *spring) == [("2027-03-14T06:30:00Z", "2027-03-14T07:30:00Z")]

    r = owner_a.post("/admin/shifts", json=_shift_body(tz="America/Nowhere", repeat_days=[7]))
    assert r.status_code == 422, f"unknown tz: {r.status_code} {r.text}"


# ── Edit, cancel and their audit rows ───────────────────────────────

async def _audit(sid: int) -> list[dict]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Action).where(Action.target_type == "shift", Action.target_id == str(sid))
            .order_by(Action.id)
        )).scalars().all()
    return [{"action": a.action, "employee_id": a.employee_id, "account_id": a.account_id,
             "payload": json.loads(a.payload_json)} for a in rows]


async def _shift_row(sid: int) -> tuple[str, datetime | None, list[tuple[int, str]]]:
    async with get_session() as s:
        sh = await s.get(Shift, sid)
        pairs = (await s.execute(select(ShiftAssignment.employee_id, ShiftAssignment.account_id)
                                 .where(ShiftAssignment.shift_id == sid))).all()
        return sh.status, sh.cancelled_at, sorted(tuple(p) for p in pairs)


def case_create_edit_and_cancel_round_trips_with_their_audit_rows():
    owner_a = fx.login_owner("agency_a_owner")
    actor = f"owner:{IDS['agency_a_owner']}"
    week = ("2026-11-09T00:00:00Z", "2026-11-16T00:00:00Z")
    made = _create(owner_a, start_utc="2026-11-10T14:00:00Z", end_utc="2026-11-10T18:00:00Z",
                   tz=NY, employee_ids=[EMP["emp_a1"]], account_ids=[CREATOR_A2])
    sid = made["shift_id"]
    assert _occ(owner_a, sid, *week) == [("2026-11-10T14:00:00Z", "2026-11-10T18:00:00Z")]

    # Edit replaces the whole series: times, repeat, Employees and Creators.
    r = owner_a.patch(f"/admin/shifts/{sid}", json=_shift_body(
        start_utc="2026-11-11T15:00:00Z", end_utc="2026-11-11T20:00:00Z", tz=NY,
        repeat_days=[3, 5], repeat_until="2026-11-20",
        employee_ids=[EMP["emp_a2"]], account_ids=[IDS["creator_a"]]))
    assert r.status_code == 200, f"edit: {r.status_code} {r.text}"
    edited = r.json()
    assert edited["shift_id"] == sid and edited["status"] == "scheduled", edited
    assert edited["start_utc"] == "2026-11-11T15:00:00Z" and edited["repeat_days"] == [3, 5], edited
    assert _occ(owner_a, sid, *week) == [
        ("2026-11-11T15:00:00Z", "2026-11-11T20:00:00Z"),
        ("2026-11-13T15:00:00Z", "2026-11-13T20:00:00Z"),
    ]
    assert _occ(owner_a, sid, "2026-11-16T00:00:00Z", "2026-11-23T00:00:00Z") == [
        ("2026-11-18T15:00:00Z", "2026-11-18T20:00:00Z"),
        ("2026-11-20T15:00:00Z", "2026-11-20T20:00:00Z"),
    ]
    assert _occ(owner_a, sid, "2026-11-23T00:00:00Z", "2026-11-30T00:00:00Z") == []
    status, cancelled_at, pairs = asyncio.run(_shift_row(sid))
    assert pairs == [(EMP["emp_a2"], IDS["creator_a"])], pairs

    # Cancel: gone from the week, the row stays as cancelled.
    r = owner_a.post(f"/admin/shifts/{sid}/cancel")
    assert r.status_code == 200, f"cancel: {r.status_code} {r.text}"
    assert r.json()["status"] == "cancelled", r.json()
    assert _occ(owner_a, sid, *week) == []
    status, cancelled_at, pairs = asyncio.run(_shift_row(sid))
    assert status == "cancelled" and cancelled_at is not None, (status, cancelled_at)
    assert pairs == [(EMP["emp_a2"], IDS["creator_a"])], "cancel dropped the assignments"

    # A second cancel and an edit after cancel are state conflicts.
    r = owner_a.post(f"/admin/shifts/{sid}/cancel")
    assert r.status_code == 409, f"second cancel: {r.status_code} {r.text}"
    r = owner_a.patch(f"/admin/shifts/{sid}", json=_shift_body())
    assert r.status_code == 409, f"edit after cancel: {r.status_code} {r.text}"

    rows = asyncio.run(_audit(sid))
    assert [a["action"] for a in rows] == ["shift.create", "shift.edit", "shift.cancel"], rows
    create, edit, cancel = rows
    for a in rows:
        assert a["payload"]["actor"] == actor, a
        assert a["employee_id"] is None, a
    assert create["account_id"] == CREATOR_A2, create
    assert create["payload"]["before"] is None, create
    assert create["payload"]["after"]["start_utc"] == "2026-11-10T14:00:00Z", create
    assert create["payload"]["after"]["status"] == "scheduled", create
    assert edit["account_id"] == IDS["creator_a"], edit
    assert edit["payload"]["before"]["start_utc"] == "2026-11-10T14:00:00Z", edit
    assert edit["payload"]["before"]["repeat_days"] is None, edit
    assert [e["id"] for e in edit["payload"]["before"]["employees"]] == [EMP["emp_a1"]], edit
    assert edit["payload"]["after"]["start_utc"] == "2026-11-11T15:00:00Z", edit
    assert edit["payload"]["after"]["repeat_days"] == [3, 5], edit
    assert edit["payload"]["after"]["repeat_until"] == "2026-11-20", edit
    assert [e["id"] for e in edit["payload"]["after"]["employees"]] == [EMP["emp_a2"]], edit
    assert cancel["payload"]["before"]["status"] == "scheduled", cancel
    assert cancel["payload"]["after"]["status"] == "cancelled", cancel


def case_a_refused_edit_changes_nothing():
    owner_a = fx.login_owner("agency_a_owner")
    sid = _create(owner_a, start_utc="2026-11-12T14:00:00Z", end_utc="2026-11-12T16:00:00Z")["shift_id"]
    r = owner_a.patch(f"/admin/shifts/{sid}", json=_shift_body(end_utc="2026-11-12T13:00:00Z"))
    assert r.status_code == 422, f"bad edit: {r.status_code} {r.text}"
    r = owner_a.patch(f"/admin/shifts/{sid}", json=_shift_body(account_ids=[IDS["creator_b"]]))
    assert r.status_code == 422, f"edit naming B's Creator: {r.status_code} {r.text}"
    assert _occ(owner_a, sid, "2026-11-09T00:00:00Z", "2026-11-16T00:00:00Z") == [
        ("2026-11-12T14:00:00Z", "2026-11-12T16:00:00Z")]
    assert [a["action"] for a in asyncio.run(_audit(sid))] == ["shift.create"]


def case_another_agencys_or_a_missing_shift_is_404_for_edit_and_cancel():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    a_sid = _create(owner_a, start_utc="2026-11-13T14:00:00Z", end_utc="2026-11-13T16:00:00Z")["shift_id"]
    b_sid = _create(owner_b, start_utc="2026-11-13T14:00:00Z", end_utc="2026-11-13T16:00:00Z",
                    employee_ids=[EMP["emp_b1"]], account_ids=[IDS["creator_b"]])["shift_id"]
    master = fx.login_owner("agency_master")
    for client, sid, body, label in (
        (owner_b, a_sid, _shift_body(employee_ids=[EMP["emp_b1"]], account_ids=[IDS["creator_b"]]), "B on A's"),
        (owner_a, b_sid, _shift_body(), "A on B's"),
        (master, a_sid, _shift_body(), "Master on A's"),
        (owner_a, 987654, _shift_body(), "A on a missing id"),
    ):
        r = client.patch(f"/admin/shifts/{sid}", json=body)
        assert r.status_code == 404, f"edit, {label}: {r.status_code} {r.text}"
        # A broken body on a foreign id is still 404 (404 before 422).
        r = client.patch(f"/admin/shifts/{sid}", json={"nope": 1})
        assert r.status_code == 404, f"bad edit, {label}: {r.status_code} {r.text}"
        r = client.post(f"/admin/shifts/{sid}/cancel")
        assert r.status_code == 404, f"cancel, {label}: {r.status_code} {r.text}"
    r = owner_a.patch("/admin/shifts/not-a-number", json=_shift_body())
    assert r.status_code in (404, 422), f"non-integer id: {r.status_code} {r.text}"
    for sid, client in ((a_sid, owner_a), (b_sid, owner_b)):
        status, _, _ = asyncio.run(_shift_row(sid))
        assert status == "scheduled", f"shift {sid} changed by another Agency"
        assert [a["action"] for a in asyncio.run(_audit(sid))] == ["shift.create"]


# ── Assignment access ────────────────────────────────────────────────

def case_an_employee_paired_with_a_creator_its_chatter_cannot_access_is_422():
    owner_a = fx.login_owner("agency_a_owner")
    before = asyncio.run(_shift_count())
    # chatter_a's Mirror Employee is allowlisted to Creator A only.
    r = owner_a.post("/admin/shifts", json=_shift_body(
        employee_ids=[EMP["mirror_a"], EMP["emp_a1"]], account_ids=[IDS["creator_a"], CREATOR_A2]))
    assert r.status_code == 422, f"restricted pair: {r.status_code} {r.text}"
    detail = r.json()["detail"]
    assert "chatter_a" in detail and "creator_a2" in detail, detail
    assert "emp_a1" not in detail, f"the unrestricted Employee is named: {detail}"
    assert asyncio.run(_shift_count()) == before, "a refused pairing wrote a Shift"

    # The same Mirror Employee on a Creator it may access is fine, and an
    # Employee with no chatter login may be put on any Creator of the Agency.
    _create(owner_a, start_utc="2026-11-14T14:00:00Z", end_utc="2026-11-14T16:00:00Z",
            employee_ids=[EMP["mirror_a"]], account_ids=[IDS["creator_a"]])
    sid = _create(owner_a, start_utc="2026-11-14T17:00:00Z", end_utc="2026-11-14T19:00:00Z",
                  employee_ids=[EMP["emp_a1"]], account_ids=[CREATOR_A2])["shift_id"]

    # An edit that adds the restricted pair is refused the same way.
    r = owner_a.patch(f"/admin/shifts/{sid}", json=_shift_body(
        start_utc="2026-11-14T17:00:00Z", end_utc="2026-11-14T19:00:00Z",
        employee_ids=[EMP["emp_a1"], EMP["mirror_a"]], account_ids=[CREATOR_A2]))
    assert r.status_code == 422, f"restricted pair on edit: {r.status_code} {r.text}"
    assert "chatter_a" in r.json()["detail"] and "creator_a2" in r.json()["detail"], r.json()
    _, _, pairs = asyncio.run(_shift_row(sid))
    assert pairs == [(EMP["emp_a1"], CREATOR_A2)], pairs


async def _allowlist(chatter: str) -> list[str]:
    async with get_session() as s:
        return sorted((await s.execute(select(ChatterAccountAccess.account_id).where(
            ChatterAccountAccess.chatter_id == IDS[chatter],
            ChatterAccountAccess.user_id == IDS["agency_a_owner"]))).scalars().all())


def case_grant_access_adds_the_creator_to_a_linked_chatters_allowlist_with_the_shift():
    owner_a = fx.login_owner("agency_a_owner")
    times = {"start_utc": "2026-11-21T14:00:00Z", "end_utc": "2026-11-21T16:00:00Z"}
    body = _shift_body(**times, employee_ids=[EMP["mirror_a"]], account_ids=[CREATOR_A2])
    before = asyncio.run(_shift_count())

    # Without the flag: 422 naming the grantable pair, nothing written.
    r = owner_a.post("/admin/shifts", json=body)
    assert r.status_code == 422, f"no flag: {r.status_code} {r.text}"
    assert r.json()["grantable"] == [{"employee_id": EMP["mirror_a"], "employee_name": "chatter_a",
                                      "account_id": CREATOR_A2, "account_name": "creator_a2"}], r.json()
    assert "chatter_a" in r.json()["detail"], r.json()
    # A truthy non-boolean is not the flag.
    assert owner_a.post("/admin/shifts", json={**body, "grant_access": "yes"}).status_code == 422
    assert asyncio.run(_allowlist("chatter_a")) == [IDS["creator_a"]]

    # A chatter not linked to Agency A is refused even with the flag: a grant would not let it in.
    stranger = asyncio.run(get_or_create_mirror_employee(
        IDS["chatter_b"], IDS["agency_a_owner"], display_name="chatter_b", color=None))
    r = owner_a.post("/admin/shifts", json={**body, "employee_ids": [EMP["mirror_a"], stranger],
                                            "grant_access": True})
    assert r.status_code == 422 and "grantable" not in r.json(), f"unlinked: {r.status_code} {r.text}"
    assert "chatter_b" in r.json()["detail"], r.json()
    assert asyncio.run(_allowlist("chatter_a")) == [IDS["creator_a"]], "a refused grant wrote the allowlist"
    assert asyncio.run(_shift_count()) == before

    # A cancelled Shift is 409 before any grant is offered, flag or not.
    gone = _create(owner_a, **times)["shift_id"]
    assert owner_a.post(f"/admin/shifts/{gone}/cancel").status_code == 200
    for flag in (False, True):
        r = owner_a.patch(f"/admin/shifts/{gone}", json={**body, "grant_access": flag})
        assert r.status_code == 409, f"cancelled edit, grant_access={flag}: {r.status_code} {r.text}"
    assert asyncio.run(_allowlist("chatter_a")) == [IDS["creator_a"]]
    before = asyncio.run(_shift_count())

    # With the flag: the Shift and the grant land together, and the audit row records the grant.
    try:
        sid = _create(owner_a, **times, employee_ids=[EMP["mirror_a"]], account_ids=[CREATOR_A2],
                      grant_access=True)["shift_id"]
        assert asyncio.run(_allowlist("chatter_a")) == sorted([IDS["creator_a"], CREATOR_A2])
        _, _, pairs = asyncio.run(_shift_row(sid))
        assert pairs == [(EMP["mirror_a"], CREATOR_A2)], pairs
        payload = asyncio.run(_audit(sid))[0]["payload"]
        assert payload["granted_access"] == [{"employee_id": EMP["mirror_a"], "account_id": CREATOR_A2}], payload
        # Now allowed, the same pairing needs no flag.
        _create(owner_a, start_utc="2026-11-22T14:00:00Z", end_utc="2026-11-22T16:00:00Z",
                employee_ids=[EMP["mirror_a"]], account_ids=[CREATOR_A2])

        # A grant racing one already written leaves the row as is.
        import shifts_api

        async def grant_again() -> None:
            async with get_session() as s:
                await shifts_api._grant(s, IDS["agency_a_owner"], [
                    {"chatter_id": IDS["chatter_a"], "account_id": CREATOR_A2}])
        asyncio.run(grant_again())
        assert asyncio.run(_allowlist("chatter_a")) == sorted([IDS["creator_a"], CREATOR_A2])
    finally:
        async def revoke() -> None:
            async with get_session() as s:
                await s.execute(sa.delete(ChatterAccountAccess).where(
                    ChatterAccountAccess.chatter_id == IDS["chatter_a"], ChatterAccountAccess.account_id == CREATOR_A2))
        asyncio.run(revoke())


def case_a_scoped_edit_asks_for_the_grant_and_records_it_on_the_new_shift():
    owner_a = fx.login_owner("agency_a_owner")
    # A weekly Monday series in December, its Creator one chatter_a is already allowed.
    sid = _create(owner_a, start_utc="2026-12-07T10:00:00Z", end_utc="2026-12-07T12:00:00Z",
                  repeat_days=[1], repeat_until="2026-12-28", employee_ids=[EMP["mirror_a"]])["shift_id"]
    edit = _shift_body(start_utc="2026-12-14T10:00:00Z", end_utc="2026-12-14T12:00:00Z",
                       employee_ids=[EMP["mirror_a"]], account_ids=[CREATOR_A2],
                       scope="this", occurrence_start="2026-12-14T10:00:00Z")
    before = asyncio.run(_shift_count())
    r = owner_a.patch(f"/admin/shifts/{sid}", json=edit)
    assert r.status_code == 422 and r.json()["grantable"][0]["account_id"] == CREATOR_A2, f"{r.status_code} {r.text}"
    assert asyncio.run(_shift_count()) == before and [a["action"] for a in asyncio.run(_audit(sid))] == ["shift.create"]
    try:
        r = owner_a.patch(f"/admin/shifts/{sid}", json={**edit, "grant_access": True})
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        new = r.json()["shift_id"]
        assert new != sid and asyncio.run(_allowlist("chatter_a")) == sorted([IDS["creator_a"], CREATOR_A2])
        # The grant is on the new one-off's create row, the series' edit row has none.
        assert asyncio.run(_audit(new))[0]["payload"]["granted_access"] == [
            {"employee_id": EMP["mirror_a"], "account_id": CREATOR_A2}]
        assert "granted_access" not in asyncio.run(_audit(sid))[-1]["payload"]
    finally:
        async def revoke() -> None:
            async with get_session() as s:
                await s.execute(sa.delete(ChatterAccountAccess).where(
                    ChatterAccountAccess.chatter_id == IDS["chatter_a"], ChatterAccountAccess.account_id == CREATOR_A2))
        asyncio.run(revoke())


def case_the_grant_is_asked_after_the_horizon_and_before_a_replace_writes_anything():
    owner_a = fx.login_owner("agency_a_owner")
    grantable = {"employee_ids": [EMP["mirror_a"]], "account_ids": [CREATOR_A2]}
    # Past the scheduling horizon: that 422, with nothing to grant offered.
    r = owner_a.post("/admin/shifts", json=_shift_body(start_utc="2029-01-02T10:00:00Z",
                                                       end_utc="2029-01-02T12:00:00Z", **grantable))
    assert r.status_code == 422 and "grantable" not in r.json() and "ahead" in r.json()["detail"], r.text

    # A one-off on the Creator, then a replacing Shift that needs the grant: asked first, nothing replaced.
    # The overlap rule (and so replace) needs Agency A's "Multiple employees per shift" off for this case.
    fx.store_blob(IDS["agency_a_owner"], "sales", {"multi_employee_shift": False})
    try:
        times = {"start_utc": "2026-12-22T10:00:00Z", "end_utc": "2026-12-22T12:00:00Z"}
        other = _create(owner_a, **times, account_ids=[CREATOR_A2])["shift_id"]
        r = owner_a.post("/admin/shifts", json=_shift_body(**times, **grantable, replace=True))
        assert r.status_code == 422 and r.json()["grantable"], f"{r.status_code} {r.text}"
        assert asyncio.run(_shift_row(other))[0] == "scheduled", "a refused grant let the replace land"
        # Granted, the replace lands too.
        r = owner_a.post("/admin/shifts", json=_shift_body(**times, **grantable, replace=True, grant_access=True))
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert asyncio.run(_shift_row(other))[0] == "cancelled", asyncio.run(_shift_row(other))
        allowed = asyncio.run(_allowlist("chatter_a"))
        assert allowed == sorted([IDS["creator_a"], CREATOR_A2]), allowed
    finally:
        fx.store_blob(IDS["agency_a_owner"], "sales", {"multi_employee_shift": True})

        async def revoke() -> None:
            async with get_session() as s:
                await s.execute(sa.delete(ChatterAccountAccess).where(
                    ChatterAccountAccess.chatter_id == IDS["chatter_a"], ChatterAccountAccess.account_id == CREATOR_A2))
        asyncio.run(revoke())


# ── Overlap rule: `sales.multi_employee_shift` (ticket 10) ───────────
#
# Agency B, in 2027, where no other case puts a Shift. Its `sales` blob
# starts absent; the cases below write it through PUT /admin/settings/sales,
# the endpoint the Sales Panel and Shift Settings both save to.

def _b_body(**over) -> dict:
    body = {
        "start_utc": "2027-01-05T09:00:00Z",
        "end_utc": "2027-01-05T17:00:00Z",
        "tz": "UTC",
        "employee_ids": [EMP["emp_b1"]],
        "account_ids": [IDS["creator_b"]],
    }
    body.update(over)
    return body


def _sales(client, blob: dict) -> None:
    r = client.put("/admin/settings/sales", json=blob)
    assert r.status_code == 200, f"PUT sales: {r.status_code} {r.text}"


def _assert_clash(r, clashes: list[dict], label: str) -> None:
    assert r.status_code == 409, f"{label}: {r.status_code} {r.text}"
    body = r.json()
    assert set(body) == {"detail", "clashes"}, f"{label}: {body}"
    assert isinstance(body["detail"], str) and body["detail"], f"{label}: {body}"
    assert body["clashes"] == clashes, f"{label}: {body['clashes']}"


def case_overlap_rule_refuses_double_staffing_while_the_setting_is_off_or_absent():
    owner_b = fx.login_owner("agency_b_owner")
    assert owner_b.get("/admin/settings/sales").json()["config"] == {}, "setup: B's sales blob is stored"
    before = asyncio.run(_shift_count())

    # Absent: two Employees on one Creator in the Shift itself.
    two = _b_body(employee_ids=[EMP["emp_b1"], EMP["emp_b2"]])
    r = owner_b.post("/admin/shifts", json=two)
    _assert_clash(r, [{"shift_id": None, "occurrence_start": "2027-01-05T09:00:00Z",
                       "account_id": IDS["creator_b"]}], "two Employees, setting absent")
    assert "creator_b" in r.json()["detail"], r.json()
    assert asyncio.run(_shift_count()) == before, "a refused Shift was written"

    # One Shift on Creator B, then another that overlaps it by an hour.
    first = _create(owner_b, **_b_body())["shift_id"]
    r = owner_b.post("/admin/shifts", json=_b_body(
        start_utc="2027-01-05T16:00:00Z", end_utc="2027-01-05T20:00:00Z", employee_ids=[EMP["emp_b2"]]))
    _assert_clash(r, [{"shift_id": first, "occurrence_start": "2027-01-05T09:00:00Z",
                       "account_id": IDS["creator_b"]}], "overlapping Shift, setting absent")
    assert str(first) in r.json()["detail"], r.json()
    # Back to back is not an overlap: [start, end) is half open.
    _create(owner_b, **_b_body(start_utc="2027-01-05T17:00:00Z", end_utc="2027-01-05T20:00:00Z",
                               employee_ids=[EMP["emp_b2"]]))

    # Stored off, or stored as anything but literal true (written straight
    # into the store, as the PUT now refuses it): still refused, and both
    # clashes are named (its own two Employees, and the first Shift).
    for value in (False, "true", 1):
        fx.store_blob(IDS["agency_b_owner"], "sales", {"exclude_welcome": True, "multi_employee_shift": value})
        r = owner_b.post("/admin/shifts", json=two)
        _assert_clash(r, [
            {"shift_id": None, "occurrence_start": "2027-01-05T09:00:00Z", "account_id": IDS["creator_b"]},
            {"shift_id": first, "occurrence_start": "2027-01-05T09:00:00Z", "account_id": IDS["creator_b"]},
        ], f"two Employees, stored {value!r}")

    # A weekly series on Wednesdays that first meets a one-off Shift seven
    # weeks later (Wed 24 Feb 2027) is refused, naming that later occurrence.
    later = _create(owner_b, **_b_body(start_utc="2027-02-24T10:00:00Z",
                                       end_utc="2027-02-24T12:00:00Z"))["shift_id"]
    series = _b_body(start_utc="2027-01-06T11:00:00Z", end_utc="2027-01-06T13:00:00Z",
                     employee_ids=[EMP["emp_b2"]], repeat_days=[3])
    r = owner_b.post("/admin/shifts", json=series)
    _assert_clash(r, [{"shift_id": later, "occurrence_start": "2027-02-24T10:00:00Z",
                       "account_id": IDS["creator_b"]}], "series clashing in week 8")
    # The same series ending the week before the clash is saved.
    _create(owner_b, **{**series, "repeat_until": "2027-02-17"})

    # An edit into a clash is refused and changes nothing.
    sid = _create(owner_b, **_b_body(start_utc="2027-03-01T09:00:00Z",
                                     end_utc="2027-03-01T10:00:00Z"))["shift_id"]
    r = owner_b.patch(f"/admin/shifts/{sid}", json=_b_body(
        start_utc="2027-02-24T11:00:00Z", end_utc="2027-02-24T13:00:00Z"))
    _assert_clash(r, [{"shift_id": later, "occurrence_start": "2027-02-24T10:00:00Z",
                       "account_id": IDS["creator_b"]}], "edit into a clash")
    assert _occ(owner_b, sid, "2027-03-01T00:00:00Z", "2027-03-08T00:00:00Z") == [
        ("2027-03-01T09:00:00Z", "2027-03-01T10:00:00Z")]
    assert [a["action"] for a in asyncio.run(_audit(sid))] == ["shift.create"]
    # Editing a Shift in place (its own old times) is not a clash with itself.
    r = owner_b.patch(f"/admin/shifts/{sid}", json=_b_body(
        start_utc="2027-03-01T09:30:00Z", end_utc="2027-03-01T10:30:00Z"))
    assert r.status_code == 200, f"edit over its own old times: {r.status_code} {r.text}"

    # Back to back across two series: Mondays 08:00-09:00 from 4 Jan meet a
    # one-off 06:00-08:00 on Monday 8 Mar end to start, which is no clash.
    _create(owner_b, **_b_body(start_utc="2027-03-08T06:00:00Z", end_utc="2027-03-08T08:00:00Z"))
    _create(owner_b, **_b_body(start_utc="2027-01-04T08:00:00Z", end_utc="2027-01-04T09:00:00Z",
                               employee_ids=[EMP["emp_b2"]], repeat_days=[1], repeat_until="2027-03-29"))

    # Two series that start a week apart and first clash nine weeks later, when
    # New York springs forward (14 Mar 2027): Mondays 10:00-11:00 New York
    # time are 15:00-16:00Z in winter and 14:00-15:00Z from 15 Mar, which
    # then meets Mondays 14:30-15:00 UTC.
    ny = _create(owner_b, **_b_body(start_utc="2027-01-04T15:00:00Z", end_utc="2027-01-04T16:00:00Z",
                                    tz=NY, repeat_days=[1]))["shift_id"]
    r = owner_b.post("/admin/shifts", json=_b_body(
        start_utc="2027-01-11T14:30:00Z", end_utc="2027-01-11T15:00:00Z",
        employee_ids=[EMP["emp_b2"]], repeat_days=[1]))
    _assert_clash(r, [{"shift_id": ny, "occurrence_start": "2027-03-15T14:00:00Z",
                       "account_id": IDS["creator_b"]}], "series clashing after spring forward")

    # A cancelled Shift clashes with nothing: its slot is free again.
    r = owner_b.post(f"/admin/shifts/{later}/cancel")
    assert r.status_code == 200, r.text
    _create(owner_b, **_b_body(start_utc="2027-02-24T10:00:00Z", end_utc="2027-02-24T12:00:00Z",
                               employee_ids=[EMP["emp_b2"]]))


def case_overlap_rule_allows_the_same_requests_while_the_setting_is_on():
    owner_b = fx.login_owner("agency_b_owner")
    # Two Employees on one Creator, with `true` stored beside an invalid
    # sibling field (written straight into the store, as the PUT refuses it):
    # the invalid field is dropped and `multi_employee_shift` still applies.
    fx.store_blob(IDS["agency_b_owner"], "sales", {"exclude_welcome": True, "multi_employee_shift": True,
                                                   "attribution": {"messages": "lottery"}})
    two = _create(owner_b, **_b_body(start_utc="2027-04-06T09:00:00Z", end_utc="2027-04-06T17:00:00Z",
                                     employee_ids=[EMP["emp_b1"], EMP["emp_b2"]]))["shift_id"]
    _sales(owner_b, {"exclude_welcome": True, "multi_employee_shift": True})
    # A Shift overlapping it.
    over = _create(owner_b, **_b_body(start_utc="2027-04-06T16:00:00Z", end_utc="2027-04-06T20:00:00Z",
                                      employee_ids=[EMP["emp_b2"]]))["shift_id"]
    # A weekly series that meets a one-off seven weeks later.
    _create(owner_b, **_b_body(start_utc="2027-05-26T10:00:00Z", end_utc="2027-05-26T12:00:00Z"))
    _create(owner_b, **_b_body(start_utc="2027-04-07T11:00:00Z", end_utc="2027-04-07T13:00:00Z",
                               employee_ids=[EMP["emp_b2"]], repeat_days=[3]))
    # An edit into an overlap.
    r = owner_b.patch(f"/admin/shifts/{over}", json=_b_body(
        start_utc="2027-04-06T10:00:00Z", end_utc="2027-04-06T12:00:00Z", employee_ids=[EMP["emp_b2"]]))
    assert r.status_code == 200, f"edit into overlap, setting on: {r.status_code} {r.text}"

    # Turned off again: the Shifts that already overlap are left alone.
    _sales(owner_b, {"exclude_welcome": True, "multi_employee_shift": False})
    week = ("2027-04-05T00:00:00Z", "2027-04-12T00:00:00Z")
    assert _occ(owner_b, two, *week) == [("2027-04-06T09:00:00Z", "2027-04-06T17:00:00Z")]
    assert _occ(owner_b, over, *week) == [("2027-04-06T10:00:00Z", "2027-04-06T12:00:00Z")]
    for sid in (two, over):
        status, _, _ = asyncio.run(_shift_row(sid))
        assert status == "scheduled", f"shift {sid} was touched when the setting went off"
    # ...and a new clash is refused again.
    r = owner_b.post("/admin/shifts", json=_b_body(start_utc="2027-04-06T12:00:00Z",
                                                   end_utc="2027-04-06T13:00:00Z"))
    assert r.status_code == 409, f"new clash after turning off: {r.status_code} {r.text}"


def case_one_agencys_setting_does_not_apply_to_another():
    # Agency A allows it (seeded); Agency B, now off, still refuses.
    owner_b = fx.login_owner("agency_b_owner")
    r = owner_b.post("/admin/shifts", json=_b_body(start_utc="2027-06-01T09:00:00Z",
                                                   end_utc="2027-06-01T10:00:00Z",
                                                   employee_ids=[EMP["emp_b1"], EMP["emp_b2"]]))
    assert r.status_code == 409, f"B with A's setting on: {r.status_code} {r.text}"
    owner_a = fx.login_owner("agency_a_owner")
    _create(owner_a, start_utc="2027-06-01T09:00:00Z", end_utc="2027-06-01T10:00:00Z",
            employee_ids=[EMP["emp_a1"], EMP["emp_a2"]], account_ids=[CREATOR_A2])


# ── Storage: migration and init_db() catch-up ────────────────────────

_TABLES = ("shifts", "shift_assignments", "clock_events")
_INDEXES = {
    "ix_shifts_agency_start": "shifts",
    "ix_shift_assignments_employee": "shift_assignments",
    "ix_shift_assignments_account": "shift_assignments",
    "uq_clock_events_open_employee": "clock_events",
    "ix_clock_events_agency_in": "clock_events",
    "ix_clock_events_account_in": "clock_events",
}
_MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"


def _schema(conn) -> tuple[set[str], dict[str, str]]:
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    indexes = {r[0]: (r[1] or "") for r in conn.execute(
        "select name, sql from sqlite_master where type='index' and sql is not null")}
    return tables, indexes


def _assert_open_clock_index_is_partial_unique(conn) -> None:
    """Behaviour, not just a name: two open events for one Employee are
    refused, a closed one beside an open one is not."""
    conn.execute("insert into clock_events (agency_user_id, employee_id, in_utc) "
                 "values ('agency', 1, '2026-10-12 09:00:00')")
    conn.execute("insert into clock_events (agency_user_id, employee_id, in_utc, out_utc, close_reason) "
                 "values ('agency', 1, '2026-10-11 09:00:00', '2026-10-11 10:00:00', 'manual')")
    try:
        conn.execute("insert into clock_events (agency_user_id, employee_id, in_utc) "
                     "values ('agency', 1, '2026-10-12 10:00:00')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("a second open Clock event for one Employee was accepted")
    conn.rollback()


def _load_shifts_migration():
    found = [p for p in _MIGRATIONS.glob("*shifts*.py")]
    assert len(found) == 1, f"want one shifts migration, found {found}"
    spec = importlib.util.spec_from_file_location("shifts_migration", found[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def case_migration_upgrade_and_downgrade_on_a_fresh_temp_file():
    mod = _load_shifts_migration()
    assert mod.down_revision == "0066_split_inbox", mod.down_revision
    path = Path(tempfile.gettempdir()) / f"shifts_migration_{uuid.uuid4().hex}.db"
    assert path != Path(_harness.DB_PATH)
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        def _run(step) -> None:
            with engine.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    step()

        _run(mod.upgrade)
        conn = sqlite3.connect(path)
        try:
            tables, indexes = _schema(conn)
            assert set(_TABLES) <= tables, tables
            for name in _INDEXES:
                assert name in indexes, f"{name} missing after upgrade: {sorted(indexes)}"
            assert "WHERE out_utc IS NULL" in indexes["uq_clock_events_open_employee"], \
                indexes["uq_clock_events_open_employee"]
            assert "UNIQUE" in indexes["uq_clock_events_open_employee"].upper(), \
                indexes["uq_clock_events_open_employee"]
            _assert_open_clock_index_is_partial_unique(conn)
        finally:
            conn.close()

        _run(mod.upgrade)  # idempotent, house convention

        _run(mod.downgrade)
        conn = sqlite3.connect(path)
        try:
            tables, indexes = _schema(conn)
        finally:
            conn.close()
        assert not (set(_TABLES) & tables), f"left after downgrade: {set(_TABLES) & tables}"
        assert not (set(_INDEXES) & set(indexes)), f"left after downgrade: {set(_INDEXES) & set(indexes)}"
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def case_init_db_brings_the_dropped_tables_back_with_their_indexes():
    conn = sqlite3.connect(_harness.DB_PATH)
    try:
        for t in reversed(_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
        tables, _ = _schema(conn)
        assert not (set(_TABLES) & tables), "setup: the tables survived the DROP"
    finally:
        conn.close()

    asyncio.run(init_db())

    conn = sqlite3.connect(_harness.DB_PATH)
    try:
        tables, indexes = _schema(conn)
        assert set(_TABLES) <= tables, f"init_db() did not recreate {set(_TABLES) - tables}"
        for name, table in _INDEXES.items():
            assert name in indexes, f"{name} on {table} missing after init_db(): {sorted(indexes)}"
        assert "WHERE out_utc IS NULL" in indexes["uq_clock_events_open_employee"], \
            indexes["uq_clock_events_open_employee"]
        _assert_open_clock_index_is_partial_unique(conn)
    finally:
        conn.close()
    # The router works on the rebuilt tables.
    owner_a = fx.login_owner("agency_a_owner")
    sid = _create(owner_a)["shift_id"]
    assert sid in _ids(_week(owner_a))


_harness.run(
    case_signed_out_is_401_on_every_endpoint_with_and_without_anonymous_admin,
    case_chatter_is_403_on_owner_endpoints,
    case_created_shift_shows_in_its_week_with_time_employees_and_creators,
    case_week_holds_shifts_that_intersect_it_and_nothing_else,
    case_occurrences_come_back_in_start_order,
    case_cancelled_shifts_are_absent,
    case_filters_by_employee_and_by_creator,
    case_range_rules,
    case_invalid_create_bodies_are_422_and_write_nothing,
    case_a_shift_of_agency_a_is_never_seen_by_owner_b,
    case_body_references_to_the_other_agency_are_422_in_both_directions,
    case_filters_naming_the_other_agency_are_refused,
    case_weekly_repeat_never_reads_back_in_later_weeks,
    case_repeat_until_is_the_last_local_date_inclusive,
    case_new_york_repeats_keep_local_time_across_spring_forward_and_fall_back,
    case_create_edit_and_cancel_round_trips_with_their_audit_rows,
    case_a_refused_edit_changes_nothing,
    case_another_agencys_or_a_missing_shift_is_404_for_edit_and_cancel,
    case_an_employee_paired_with_a_creator_its_chatter_cannot_access_is_422,
    case_grant_access_adds_the_creator_to_a_linked_chatters_allowlist_with_the_shift,
    case_a_scoped_edit_asks_for_the_grant_and_records_it_on_the_new_shift,
    case_the_grant_is_asked_after_the_horizon_and_before_a_replace_writes_anything,
    case_overlap_rule_refuses_double_staffing_while_the_setting_is_off_or_absent,
    case_overlap_rule_allows_the_same_requests_while_the_setting_is_on,
    case_one_agencys_setting_does_not_apply_to_another,
    case_migration_upgrade_and_downgrade_on_a_fresh_temp_file,
    case_init_db_brings_the_dropped_tables_back_with_their_indexes,
)
