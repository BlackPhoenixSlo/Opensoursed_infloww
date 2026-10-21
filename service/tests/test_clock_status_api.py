#!/usr/bin/env python3
"""The top bar's clock on the Relay (w4-a, amending docs/spec/phase-02):
clock-in without a Creator, who may clock (`role_ids`), owners clocking as
their own row, GET /clock-status, POST /clock-heartbeat, the clock-records
read GET /clock-events, and the `last_seen_utc` column's migration and
init_db() catch-up.

The seam is the Relay over HTTP with real session cookies from the shared
two-Agency fixture, as in test_clock_api.py (whose sweep and Owner edit
cases this file does not repeat). Clocking happens at the server's "now";
past events are seeded straight into the temp DB through _clock_fixtures.py,
so no clock is mocked. Each case has its own chatters, so one open Clock
event never leaks into another case.

Run: ./venv/bin/python service/tests/test_clock_status_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import select  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import (  # noqa: E402
    IDS, ON as NEVER_SAVED, create as _create, employee as _employee, event as _event, time_tracking as _time_tracking,
    utc_now as _utc_now, z as _z,
)
from db.engine import get_session, init_db  # noqa: E402
from db.models import (  # noqa: E402
    SETTINGS_EPOCH, Account, Action, Chatter, ChatterUser, ClockEvent, Employee, SettingsVersion, UserAccount,
)
from employees import get_or_create_mirror_employee  # noqa: E402

ROLE_OFF = {"detail": {"error": "role_not_enabled", "message": "clock in is not enabled for your role"}}

# ASSUMPTION: this file seeds its own second Creator of Agency A and its own
# chatters, as test_clock_api.py does (same ids: each suite has its own temp
# DB). Rung 3. Overturned when two files need the same rows and drift.
CREATOR_A2 = "1000013"

_CHATTERS = ("st_free", "st_attach", "st_role", "st_norole", "st_status", "st_idle", "st_beat", "st_late",
             "st_background", "st_remind")


async def _seed() -> dict[str, int]:
    now = datetime.utcnow()
    ids = {}
    async with get_session() as s:
        s.add(Account(id=CREATOR_A2, nickname="creator_a2", color="#aaaaaa"))
        (account_registry.ACCOUNTS_DIR / CREATOR_A2).mkdir()
        for name in _CHATTERS:
            ids[name] = uuid.uuid4().hex
            s.add(Chatter(id=ids[name], username=name, password=fx.PASSWORD, display_name=name,
                          color="#bbbbbb", created_at=now, last_seen_at=now))
    async with get_session() as s:
        s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=CREATOR_A2))
        for name in _CHATTERS:
            s.add(ChatterUser(chatter_id=ids[name], user_id=IDS["agency_a_owner"], created_at=now))
        # Two Shifts on one Creator may overlap here (test_shifts_api.py tests the rule).
        s.add(SettingsVersion(user_id=IDS["agency_a_owner"], tab="sales", effective_from=SETTINGS_EPOCH,
                              config_json='{"multi_employee_shift": true}'))
    return {name: await get_or_create_mirror_employee(ids[name], IDS["agency_a_owner"],
                                                      display_name=name, color=None)
            for name in _CHATTERS}


MIRROR = asyncio.run(_seed())


async def _ab_mirrors() -> dict[str, int]:
    return {owner: await get_or_create_mirror_employee(IDS["chatter_ab"], IDS[owner], display_name="chatter_ab",
                                                       color=None)
            for owner in ("agency_a_owner", "agency_b_owner")}


# Since w5-a nobody clocks until "Enable clock in and clock out for" is saved (Infloww's never-saved list is all
# unticked; case_role_ids_decide_who_may_clock... tests it), so the other cases tick the built-in Chatter, which
# every chatter here holds but st_norole.
ON = {**NEVER_SAVED, "role_ids": ["chatter"]}
_AB = asyncio.run(_ab_mirrors())
BASE_A = {str(e): "chatter" for name, e in MIRROR.items() if name != "st_norole"} | {str(_AB["agency_a_owner"]): "chatter"}
fx.store_blob(IDS["agency_a_owner"], "roles", {"roles": [], "assignments": BASE_A})
fx.store_blob(IDS["agency_b_owner"], "roles", {"roles": [], "assignments": {str(_AB["agency_b_owner"]): "chatter"}})


def _around_now(before_h: float, after_h: float) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    return {"start_utc": _z(now - timedelta(hours=before_h)), "end_utc": _z(now + timedelta(hours=after_h)),
            "tz": "UTC"}


def _clock_in(client, **body):
    return client.post("/admin/shifts/clock-in", json=body)


def _clock_out(client, clock_event_id):
    r = client.post("/admin/shifts/clock-out", json={"clock_event_id": clock_event_id})
    assert r.status_code == 200, f"clock-out: {r.status_code} {r.text}"
    return r.json()


def _status(client, heartbeat: bool = False) -> dict:
    r = client.post("/admin/shifts/clock-heartbeat") if heartbeat else client.get("/admin/shifts/clock-status")
    assert r.status_code == 200, f"status: {r.status_code} {r.text}"
    return r.json()


def _roles(client, assignments: dict[int, str]) -> None:
    body = {"roles": [{"id": "role-chat", "name": "Custom chat"}],
            "assignments": BASE_A | {str(emp): role for emp, role in assignments.items()}}
    r = client.put("/admin/settings/roles", json=body)
    assert r.status_code == 200, f"PUT roles: {r.status_code} {r.text}"
    # The PUT gives every login it left unassigned the built-in Chatter; st_norole stands for a login stored
    # with no role before that, so its assignment is taken back out of the stored blob.
    saved = r.json()["config"]
    fx.store_blob(IDS["agency_a_owner"], "roles", {**saved, "assignments": {
        k: v for k, v in saved["assignments"].items() if k != str(MIRROR["st_norole"])}})


async def _event_row(event_id: int) -> ClockEvent:
    async with get_session() as s:
        return await s.get(ClockEvent, event_id)


def _row(event_id: int) -> ClockEvent:
    return asyncio.run(_event_row(event_id))


async def _employee_row(employee_id: int) -> Employee:
    async with get_session() as s:
        return await s.get(Employee, employee_id)


def case_clock_in_without_a_creator_files_the_agency_wide_clock_and_links_a_shift_on_any_creator():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    free = fx.login_chatter("st_free")
    r = _clock_in(free)
    assert r.status_code == 200, f"no Creator: {r.status_code} {r.text}"
    ev = r.json()
    assert ev["account_id"] is None and ev["shift_id"] is None and ev["employee_id"] == MIRROR["st_free"], ev
    assert _row(ev["clock_event_id"]).account_id is None
    _clock_out(free, ev["clock_event_id"])
    # An old client naming the Creator still files it.
    ev = _clock_in(free, account_id=IDS["creator_a"]).json()
    assert ev["account_id"] == IDS["creator_a"], ev
    _clock_out(free, ev["clock_event_id"])
    r = _clock_in(free, account_id="")
    assert r.status_code == 422, f"empty account_id: {r.status_code} {r.text}"

    # The agency-wide clock links the assigned occurrence on any Creator,
    # earliest start first.
    emp = MIRROR["st_attach"]
    late = _create(owner_a, **_around_now(1, 1), employee_ids=[emp], account_ids=[CREATOR_A2])["shift_id"]
    early = _create(owner_a, **_around_now(2, 1), employee_ids=[emp], account_ids=[CREATOR_A2])["shift_id"]
    _create(owner_a, **_around_now(3, 1), employee_ids=[MIRROR["st_free"]], account_ids=[IDS["creator_a"]])
    attach = fx.login_chatter("st_attach")
    ev = _clock_in(attach).json()
    assert (ev["account_id"], ev["shift_id"]) == (None, early), f"want the earlier Shift {early}: {ev}"
    _clock_out(attach, ev["clock_event_id"])
    ev = _clock_in(attach, shift_id=late).json()
    assert ev["shift_id"] == late, ev
    _clock_out(attach, ev["clock_event_id"])

    # A chatter in two Agencies must still name a Creator.
    _time_tracking(fx.login_owner("agency_b_owner"), ON)
    ab = fx.login_chatter("chatter_ab")
    r = _clock_in(ab)
    assert r.status_code == 400 and r.json() == {"detail": "name a creator to choose the agency"}, \
        f"two Agencies: {r.status_code} {r.text}"


def case_role_ids_decide_who_may_clock_and_an_owner_clocks_as_its_own_row():
    owner_a = fx.login_owner("agency_a_owner")
    _roles(owner_a, {MIRROR["st_role"]: "role-chat"})
    role, norole = fx.login_chatter("st_role"), fx.login_chatter("st_norole")

    # Never saved: nobody clocks, as Infloww's list starts all unticked (w5-a).
    _time_tracking(owner_a, NEVER_SAVED)
    for client in (role, norole):
        assert (_status(client)["can_clock"], _status(client)["reason"]) == (False, "role_not_enabled")
        assert _clock_in(client).json() == ROLE_OFF
    assert _clock_in(owner_a).json() == ROLE_OFF
    assert _status(owner_a) | {"server_now": None} == {
        "can_clock": False, "reason": "role_not_enabled", "open": None, "last_closed": None,
        "auto_clock_out_minutes": 60, "server_now": None}

    # A built-in role (Chatter) is assignable and tickable like any other.
    _time_tracking(owner_a, ON)
    _clock_out(free_chatter := fx.login_chatter("st_free"), _clock_in(free_chatter).json()["clock_event_id"])
    assert _clock_in(norole).json() == ROLE_OFF

    # Saved: only the ticked roles; an Employee with no role is refused.
    _time_tracking(owner_a, {**ON, "role_ids": ["role-chat", "gone-role"]})
    _clock_out(role, _clock_in(role).json()["clock_event_id"])
    r = _clock_in(norole)
    assert r.status_code == 403 and r.json() == ROLE_OFF, f"no role: {r.status_code} {r.text}"
    assert (_status(norole)["can_clock"], _status(norole)["reason"]) == (False, "role_not_enabled")
    assert _clock_in(owner_a).json() == ROLE_OFF

    # Owner ticked: the owner clocks as its own row, without a Creator.
    _time_tracking(owner_a, {**ON, "role_ids": ["owner"]})
    r = _clock_in(role)
    assert r.status_code == 403 and r.json() == ROLE_OFF, f"role unticked: {r.status_code} {r.text}"
    r = _clock_in(owner_a)
    assert r.status_code == 200, f"owner ticked: {r.status_code} {r.text}"
    ev = r.json()
    row = asyncio.run(_employee_row(ev["employee_id"]))
    assert (row.chatter_id, row.user_id) == (f"owner:{IDS['agency_a_owner']}", IDS["agency_a_owner"]), \
        f"filed on {row.chatter_id} / {row.user_id}"
    assert ev["account_id"] is None, ev
    assert _status(owner_a)["open"] == ev
    assert _clock_in(owner_a).status_code == 409
    listed = owner_a.get("/admin/shifts/clocked-in").json()["clocked_in"]
    assert ev["clock_event_id"] in {r["clock_event_id"] for r in listed}, listed
    r = _clock_in(owner_a, account_id=IDS["creator_b"])
    assert r.status_code in (403, 422), f"another Agency's Creator: {r.status_code} {r.text}"
    # Another Agency's owner cannot close it.
    r = fx.login_owner("agency_b_owner").post("/admin/shifts/clock-out", json={"clock_event_id": ev["clock_event_id"]})
    assert r.status_code == 404, f"B closes A's owner event: {r.status_code} {r.text}"
    # Unticking Owner while clocked in still lets it clock out.
    _time_tracking(owner_a, {**ON, "role_ids": []})
    assert _clock_out(owner_a, ev["clock_event_id"])["close_reason"] == "manual"
    last = _status(owner_a)["last_closed"]
    assert last["clock_event_id"] == ev["clock_event_id"] and last["close_reason"] == "manual", last

    # The Master clocks as its own row in its own Agency.
    master = fx.login_owner("agency_master")
    _time_tracking(master, {**ON, "role_ids": ["owner"]})
    ev = _clock_in(master).json()
    row = asyncio.run(_employee_row(ev["employee_id"]))
    assert row.chatter_id == f"owner:{IDS['agency_master']}", row.chatter_id
    _clock_out(master, ev["clock_event_id"])
    _time_tracking(owner_a, ON)


def case_clock_status_names_why_it_cannot_clock_and_a_two_agency_chatter_picks_a_creator():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    st = fx.login_chatter("st_status")
    _time_tracking(owner_a, {**ON, "enabled": False, "auto_clock_out_minutes": 25})
    body = _status(st)
    assert (body["can_clock"], body["reason"], body["open"], body["auto_clock_out_minutes"]) == \
        (False, "time_tracking_off", None, 25), body
    server_now = datetime.fromisoformat(body["server_now"].replace("Z", "")).replace(microsecond=0)
    assert abs((server_now - _utc_now()).total_seconds()) < 5, body["server_now"]
    _time_tracking(owner_a, ON)
    assert (_status(st)["can_clock"], _status(st)["reason"]) == (True, None)

    async def _deactivate(active: bool):
        async with get_session() as s:
            (await s.get(Employee, MIRROR["st_status"])).is_active = active
    asyncio.run(_deactivate(False))
    try:
        assert (_status(st)["can_clock"], _status(st)["reason"]) == (False, "inactive")
    finally:
        asyncio.run(_deactivate(True))

    # Two Agencies: pick a Creator while either allows; `open` in any Agency.
    ab = fx.login_chatter("chatter_ab")
    _time_tracking(owner_a, {**ON, "enabled": False})
    _time_tracking(owner_b, {**ON, "enabled": False})
    assert (_status(ab)["can_clock"], _status(ab)["reason"]) == (False, "time_tracking_off")
    _time_tracking(owner_b, {**ON, "auto_clock_out_minutes": 15})
    assert (_status(ab)["can_clock"], _status(ab)["reason"]) == (True, "pick_creator")
    ev = _clock_in(ab, account_id=IDS["creator_b"]).json()
    body = _status(ab)
    assert (body["reason"], body["open"], body["auto_clock_out_minutes"]) == ("pick_creator", ev, 15), body
    _clock_out(ab, ev["clock_event_id"])
    _time_tracking(owner_a, ON)
    _time_tracking(owner_b, ON)


def case_the_heartbeat_marks_the_open_event_seen_and_after_its_deadline_reports_the_auto_close():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, {**ON, "auto_clock_out_minutes": 10})
    idle = fx.login_chatter("st_idle")
    assert _status(idle, heartbeat=True)["open"] is None  # nothing open: a no-op

    beat = fx.login_chatter("st_beat")
    now = _utc_now()
    ev_id = _event(MIRROR["st_beat"], now - timedelta(minutes=5))
    assert _row(ev_id).last_seen_utc is None
    assert _status(beat)["open"]["clock_event_id"] == ev_id
    assert _row(ev_id).last_seen_utc is None, "GET /clock-status marked the event seen"
    body = _status(beat, heartbeat=True)
    assert body["open"]["clock_event_id"] == ev_id, body
    seen = _row(ev_id).last_seen_utc
    assert seen is not None and abs((seen - datetime.utcnow()).total_seconds()) < 5, seen
    _clock_out(beat, ev_id)

    # A heartbeat after the deadline finds the event already swept.
    late = fx.login_chatter("st_late")
    ev_id = _event(MIRROR["st_late"], now - timedelta(minutes=30))
    body = _status(late, heartbeat=True)
    assert body["open"] is None, body
    assert body["last_closed"] == {"clock_event_id": ev_id, "out_utc": _z(now - timedelta(minutes=20)),
                                   "close_reason": "auto"}, body["last_closed"]
    assert _row(ev_id).last_seen_utc is None, "the late heartbeat reopened or marked a closed event"
    _time_tracking(owner_a, ON)


async def _actions_of(employee_id: int) -> list[str]:
    async with get_session() as s:
        return list((await s.execute(select(Action.action).where(Action.employee_id == employee_id))).scalars())


def case_the_apps_background_writes_do_not_keep_an_idle_event_open():
    """A perf-log flush and an error report sent in one Creator's scope (the
    app's `X-Account-Id`) are audited under the chatter's Mirror Employee (the
    audit middleware), yet the sweep closes the idle event at its clock-in
    plus the minutes, not at those writes."""
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, {**ON, "auto_clock_out_minutes": 10})
    chatter = fx.login_chatter("st_background")
    emp = MIRROR["st_background"]
    now = _utc_now()
    ev_id = _event(emp, now - timedelta(minutes=30))
    scope = {"X-Account-Id": IDS["creator_a"]}
    r = chatter.post("/admin/perflog/ingest", json={"tabId": "t1", "events": []}, headers=scope)
    assert r.status_code == 200, f"perflog: {r.status_code} {r.text}"
    r = chatter.post("/admin/errors", json={"message": "boom"}, headers=scope)
    assert r.status_code == 200, f"errors: {r.status_code} {r.text}"
    audited = asyncio.run(_actions_of(emp))
    assert {"POST /admin/perflog/ingest", "POST /admin/errors"} <= set(audited), audited
    body = _status(chatter)
    assert body["open"] is None and body["last_closed"] == {
        "clock_event_id": ev_id, "out_utc": _z(now - timedelta(minutes=20)), "close_reason": "auto"}, body
    _time_tracking(owner_a, ON)


def case_the_clock_in_reminder_follows_the_role_gate():
    owner_a = fx.login_owner("agency_a_owner")
    emp = MIRROR["st_remind"]
    _create(owner_a, **_around_now(1, 1), employee_ids=[emp], account_ids=[IDS["creator_a"]])
    chatter = fx.login_chatter("st_remind")
    _time_tracking(owner_a, {**ON, "clock_in_reminder": True})
    assert chatter.get("/admin/shifts/me").json()["reminder"] is not None
    # Its role (Chatter) is not ticked: no reminder to a clock-in it would be refused.
    _time_tracking(owner_a, {**ON, "clock_in_reminder": True, "role_ids": ["owner"]})
    assert chatter.get("/admin/shifts/me").json()["reminder"] is None
    _time_tracking(owner_a, ON)


def _records(client, employee_id, start: datetime, end: datetime):
    return client.get("/admin/shifts/clock-events",
                      params={"employee_id": employee_id, "from": _z(start), "to": _z(end)})


def case_clock_records_list_one_employees_events_newest_first_for_owners_only():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    _time_tracking(owner_a, {**ON, "auto_clock_out_minutes": 60})
    emp = _employee("records")
    now = _utc_now()
    t0 = now - timedelta(days=2)
    older = _event(emp, t0, t0 + timedelta(minutes=60, seconds=1))  # rounds up to 61
    newer = _event(emp, t0 + timedelta(hours=3), t0 + timedelta(hours=4), account_id=CREATOR_A2)
    _event(emp, t0 - timedelta(days=5), t0 - timedelta(days=5) + timedelta(hours=1))  # before the range
    swept = _event(emp, now - timedelta(hours=5), None)  # no activity: auto at +60
    edited = _event(emp, now - timedelta(hours=26), now - timedelta(hours=25))
    r = owner_a.patch(f"/admin/shifts/clock-events/{edited}", json={"in_utc": _z(now - timedelta(hours=26, minutes=30))})
    assert r.status_code == 200, f"edit: {r.status_code} {r.text}"
    other = _event(_employee("records_other"), t0, t0 + timedelta(hours=1))

    r = _records(owner_a, emp, now - timedelta(days=3), now)
    assert r.status_code == 200, f"list: {r.status_code} {r.text}"
    rows = r.json()["clock_events"]
    assert [x["clock_event_id"] for x in rows] == [swept, edited, newer, older], rows
    assert other not in {x["clock_event_id"] for x in rows}
    by_id = {x["clock_event_id"]: x for x in rows}
    assert by_id[older] == {"clock_event_id": older, "employee_id": emp, "account_id": IDS["creator_a"],
                            "shift_id": None, "in_utc": _z(t0), "out_utc": _z(t0 + timedelta(minutes=60, seconds=1)),
                            "close_reason": "manual", "minutes": 61, "edited": False}, by_id[older]
    assert (by_id[newer]["account_id"], by_id[newer]["minutes"]) == (CREATOR_A2, 60), by_id[newer]
    assert (by_id[swept]["close_reason"], by_id[swept]["minutes"], by_id[swept]["edited"]) == ("auto", 60, False)
    assert (by_id[edited]["minutes"], by_id[edited]["edited"]) == (90, True), by_id[edited]
    # An open event has no minutes; an event straddling `from` is listed.
    open_id = _event(emp, now - timedelta(minutes=2))
    rows = _records(owner_a, emp, now - timedelta(minutes=1), now + timedelta(hours=1)).json()["clock_events"]
    assert [(x["clock_event_id"], x["minutes"], x["out_utc"]) for x in rows] == [(open_id, None, None)], rows

    for label, client, params, status in (
        ("chatter", fx.login_chatter("st_free"), {"employee_id": emp}, 403),
        ("signed out", _harness.make_client(), {"employee_id": emp}, 401),
        ("another Agency's owner", owner_b, {"employee_id": emp}, 404),
        ("a missing employee", owner_a, {"employee_id": 999999}, 404),
        ("a non-number employee", owner_a, {"employee_id": "x"}, 422),
    ):
        r = client.get("/admin/shifts/clock-events",
                       params={**params, "from": _z(now - timedelta(days=1)), "to": _z(now)})
        assert r.status_code == status, f"{label}: {r.status_code} {r.text}"
    r = _records(owner_a, emp, now - timedelta(days=43), now)
    assert r.status_code == 422 and r.json() == {"detail": "the range is at most 42 days"}, f"{r.status_code} {r.text}"
    r = _records(owner_a, emp, now, now - timedelta(days=1))
    assert r.status_code == 422, f"inverted range: {r.status_code} {r.text}"
    _time_tracking(owner_a, ON)


# ── Storage: the `last_seen_utc` column ──────────────────────────────

_MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"


def _load_migration():
    found = list(_MIGRATIONS.glob("*clock_last_seen*.py"))
    assert len(found) == 1, f"want one clock_last_seen migration, found {found}"
    spec = importlib.util.spec_from_file_location("clock_last_seen_migration", found[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _columns(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(clock_events)")}


def _open_index(conn) -> str:
    return conn.execute("SELECT sql FROM sqlite_master WHERE name = 'uq_clock_events_open_employee'").fetchone()[0]


def case_migration_upgrade_and_downgrade_on_a_fresh_temp_file():
    mod = _load_migration()
    assert (mod.revision, mod.down_revision) == ("0075_clock_last_seen", "0074_link_list"), mod.revision
    path = Path(tempfile.gettempdir()) / f"clock_last_seen_{uuid.uuid4().hex}.db"
    assert path != Path(_harness.DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE clock_events (id INTEGER PRIMARY KEY, employee_id INTEGER, out_utc DATETIME)")
    conn.execute("CREATE UNIQUE INDEX uq_clock_events_open_employee ON clock_events (employee_id) "
                 "WHERE out_utc IS NULL")
    conn.commit()
    conn.close()
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        def _run(step) -> None:
            with engine.begin() as c:
                with Operations.context(MigrationContext.configure(c)):
                    step()

        for step, want in ((mod.upgrade, True), (mod.upgrade, True), (mod.downgrade, False), (mod.downgrade, False)):
            _run(step)  # each twice: idempotent, house convention
            conn = sqlite3.connect(path)
            try:
                assert ("last_seen_utc" in _columns(conn)) is want, f"{step.__name__}: {_columns(conn)}"
                assert "WHERE out_utc IS NULL" in _open_index(conn), _open_index(conn)
            finally:
                conn.close()
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def case_init_db_brings_the_dropped_column_back():
    conn = sqlite3.connect(_harness.DB_PATH)
    try:
        conn.execute("ALTER TABLE clock_events DROP COLUMN last_seen_utc")
        conn.commit()
        assert "last_seen_utc" not in _columns(conn), "setup: the column survived the DROP"
    finally:
        conn.close()

    asyncio.run(init_db())

    conn = sqlite3.connect(_harness.DB_PATH)
    try:
        assert "last_seen_utc" in _columns(conn), f"init_db() did not add it back: {_columns(conn)}"
    finally:
        conn.close()
    # The heartbeat works on the rebuilt column.
    _time_tracking(fx.login_owner("agency_a_owner"), ON)
    beat = fx.login_chatter("st_beat")
    ev_id = _event(MIRROR["st_beat"], _utc_now() - timedelta(minutes=1))
    assert _status(beat, heartbeat=True)["open"]["clock_event_id"] == ev_id
    assert _row(ev_id).last_seen_utc is not None


_harness.run(
    case_clock_in_without_a_creator_files_the_agency_wide_clock_and_links_a_shift_on_any_creator,
    case_role_ids_decide_who_may_clock_and_an_owner_clocks_as_its_own_row,
    case_clock_status_names_why_it_cannot_clock_and_a_two_agency_chatter_picks_a_creator,
    case_the_heartbeat_marks_the_open_event_seen_and_after_its_deadline_reports_the_auto_close,
    case_the_apps_background_writes_do_not_keep_an_idle_event_open,
    case_the_clock_in_reminder_follows_the_role_gate,
    case_clock_records_list_one_employees_events_newest_first_for_owners_only,
    case_migration_upgrade_and_downgrade_on_a_fresh_temp_file,
    case_init_db_brings_the_dropped_column_back,
)
