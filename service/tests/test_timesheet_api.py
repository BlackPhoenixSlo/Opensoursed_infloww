#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import (  # noqa: E402
    IDS, ON, agency_wide_event as _agency_wide_event, create as _create, employee as _employee, event as _event,
    time_tracking as _time_tracking, utc_now as _utc_now, with_anonymous_admin as _with_anonymous_admin, z as _z,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, Chatter, ChatterUser, Message, Transaction, UserAccount  # noqa: E402
from employees import get_or_create_mirror_employee  # noqa: E402


TS_FROM, TS_TO = "2026-03-02T00:00:00Z", "2026-03-09T00:00:00Z"
TS1, TS2 = "1000021", "1000022"
FAN = 5_000_001


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s)


async def _seed_timesheet_creators() -> None:
    async with get_session() as s:
        for acc in (TS1, TS2):
            s.add(Account(id=acc, nickname=f"ts_creator_{acc[-1]}", color="#aaaaaa"))
            (account_registry.ACCOUNTS_DIR / acc).mkdir()
    async with get_session() as s:
        for acc in (TS1, TS2):
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=acc))
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "db", "migrations", "versions", "20261027_0100_converters_window.py")
    spec = importlib.util.spec_from_file_location("mig_attr_view", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    async with get_session() as s:
        # init_db (create_all) builds no views: apply the shipped attribution view.
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(mig._NEW_VIEW_SQL))


asyncio.run(_seed_timesheet_creators())


async def _seed_mirror_chatter(name: str) -> None:
    now = datetime.utcnow()
    cid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(Chatter(id=cid, username=name, password=fx.PASSWORD, display_name=name, color="#bbbbbb",
                      created_at=now, last_seen_at=now))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=IDS["agency_a_owner"], created_at=now))
    await get_or_create_mirror_employee(cid, IDS["agency_a_owner"], display_name=name, color=None)


asyncio.run(_seed_mirror_chatter("ts_chatter"))
_next_message = iter(range(9_000_001, 9_100_000))


async def _insert_sale(employee_id: int, account_id: str, at: datetime, cents: int) -> None:
    mid = next(_next_message)
    async with get_session() as s:
        s.add(Message(account_id=account_id, fan_id=FAN, message_id=mid, direction="out",
                      sent_by_employee_id=employee_id, created_at=at - timedelta(minutes=5)))
        s.add(Transaction(account_id=account_id, fan_id=FAN, kind="ppv_message", message_id=mid,
                          amount_cents=cents, occurred_at=at, status="cleared", currency="USD", source="ledger"))


def _sale(employee_id: int, account_id: str, at: str, cents: int) -> None:
    asyncio.run(_insert_sale(employee_id, account_id, _at(at), cents))


def _timesheet(client, group: str | None = "employee", frm: str = TS_FROM, to: str = TS_TO):
    params = {"from": frm, "to": to}
    if group is not None:
        params["group"] = group
    return client.get("/admin/shifts/timesheet", params=params)


def _ts_rows(client, group: str, **kw) -> dict[str, dict]:
    r = _timesheet(client, group, **kw)
    assert r.status_code == 200, f"timesheet {group}: {r.status_code} {r.text}"
    return {row["key"]: row for row in r.json()["rows"]}


def _figures(row: dict) -> tuple:
    return (row["scheduled_shifts"], row["shifts_worked"], row["scheduled_minutes"],
            row["worked_minutes"], row["recorded_earnings_cents"], row["open_now"])


def _seed_week() -> dict[str, int]:
    owner_a = fx.login_owner("agency_a_owner")
    e1, e2 = _employee("ts_avery"), _employee("ts_blake")
    _create(owner_a, start_utc="2026-03-01T22:00:00Z", end_utc="2026-03-02T04:00:00Z", tz="UTC",
            employee_ids=[e1], account_ids=[TS1])
    _create(owner_a, start_utc="2026-03-04T09:00:00Z", end_utc="2026-03-04T17:00:00Z", tz="UTC",
            repeat_days=[3, 5], repeat_until="2026-03-06", employee_ids=[e1], account_ids=[TS1])
    _create(owner_a, start_utc="2026-03-08T20:00:00Z", end_utc="2026-03-09T02:00:00Z", tz="UTC",
            employee_ids=[e2], account_ids=[TS2])
    s4 = _create(owner_a, start_utc="2026-03-05T09:00:00Z", end_utc="2026-03-05T17:00:00Z", tz="UTC",
                 employee_ids=[e2], account_ids=[TS1])["shift_id"]
    assert owner_a.post(f"/admin/shifts/{s4}/cancel").status_code == 200
    _event(e1, _at("2026-03-01T23:00:00"), _at("2026-03-02T01:00:00"), account_id=TS1)
    _event(e1, _at("2026-03-04T09:30:00"), _at("2026-03-04T12:00:00"), account_id=TS1)
    _event(e1, _at("2026-03-06T10:00:00"), _at("2026-03-06T11:00:00"), account_id=TS2)
    _event(e2, _at("2026-03-08T23:00:00"), _at("2026-03-09T01:00:00"), account_id=TS2)
    for emp, acc, at, cents in (
        (e1, TS1, "2026-03-04T10:00:00", 1000), (e1, TS1, "2026-03-04T13:00:00", 2000),
        (e1, TS1, "2026-03-01T23:30:00", 4000), (e2, TS1, "2026-03-04T11:00:00", 8000),
        (e1, TS2, "2026-03-06T10:30:00", 16000), (e1, TS1, "2026-03-06T10:30:00", 32000),
        (e2, TS2, "2026-03-09T00:30:00", 64000), (e2, TS2, "2026-03-08T23:30:00", 250),
    ):
        _sale(emp, acc, at, cents)

    owner_b = fx.login_owner("agency_b_owner")
    b1 = _employee("ts_b", "agency_b_owner")
    _create(owner_b, start_utc="2026-03-03T09:00:00Z", end_utc="2026-03-03T17:00:00Z", tz="UTC",
            employee_ids=[b1], account_ids=[IDS["creator_b"]])
    _event(b1, _at("2026-03-03T09:00:00"), _at("2026-03-03T10:00:00"), owner="agency_b_owner")
    _sale(b1, IDS["creator_b"], "2026-03-03T09:30:00", 500)
    return {"e1": e1, "e2": e2, "b1": b1}


TS = _seed_week()


def case_the_timesheet_per_employee_clips_at_the_week_edges_and_counts_only_earnings_in_worked_time():
    rows = _ts_rows(fx.login_owner("agency_a_owner"), "employee")
    e1, e2 = rows[str(TS["e1"])], rows[str(TS["e2"])]
    assert e1["display_name"] == "ts_avery" and e2["display_name"] == "ts_blake", (e1, e2)
    assert _figures(e1) == (3, 2, 1200, 270, 17000, False), e1
    assert _figures(e2) == (1, 1, 240, 60, 250, False), e2
    assert all(type(r["recorded_earnings_cents"]) is int for r in (e1, e2)), "Recorded earnings in integer cents"
    assert set(e1) == {"key", "display_name", "scheduled_shifts", "shifts_worked", "scheduled_minutes",
                       "worked_minutes", "recorded_earnings_cents", "open_now", "employee_id",
                       "group_name"}, f"payroll or other extra field: {e1}"


def case_an_employee_row_names_its_employee_id_and_group_and_a_creator_row_neither():
    owner_a = fx.login_owner("agency_a_owner")
    r = owner_a.post("/admin/employee-groups", json={"name": "TS Night team", "parent_id": None})
    assert r.status_code == 200, r.text
    r = owner_a.put("/admin/employee-groups/members", json={"group_id": r.json()["id"], "employee_ids": [TS["e1"]]})
    assert r.status_code == 200, r.text
    rows = _ts_rows(owner_a, "employee")
    e1, e2 = rows[str(TS["e1"])], rows[str(TS["e2"])]
    assert (e1["employee_id"], e1["group_name"]) == (TS["e1"], "TS Night team"), e1
    assert (e2["employee_id"], e2["group_name"]) == (TS["e2"], None), e2
    t1 = _ts_rows(owner_a, "account")[TS1]
    assert (t1["employee_id"], t1["group_name"]) == (None, None), t1


def case_the_timesheet_per_creator_counts_each_occurrence_once_and_its_creators_earnings():
    rows = _ts_rows(fx.login_owner("agency_a_owner"), "account")
    t1, t2 = rows[TS1], rows[TS2]
    assert (t1["display_name"], t2["display_name"]) == ("ts_creator_1", "ts_creator_2"), (t1, t2)
    assert _figures(t1) == (3, 2, 1200, 210, 1000, False), t1
    assert _figures(t2) == (1, 1, 240, 120, 16250, False), t2
    assert all(type(r["recorded_earnings_cents"]) is int for r in (t1, t2)), "Recorded earnings in integer cents"


def case_the_timesheet_reads_one_agency_and_is_owner_and_master_only():
    a_emp = _ts_rows(fx.login_owner("agency_a_owner"), "employee")
    a_acc = _ts_rows(fx.login_owner("agency_a_owner"), "account")
    assert str(TS["b1"]) not in a_emp, f"Agency B's Employee in Agency A's Timesheet: {a_emp}"
    assert IDS["creator_b"] not in a_acc, f"Agency B's Creator in Agency A's Timesheet: {a_acc}"
    b_emp = _ts_rows(fx.login_owner("agency_b_owner"), "employee")
    b_acc = _ts_rows(fx.login_owner("agency_b_owner"), "account")
    assert set(b_emp) == {str(TS["b1"])}, b_emp
    assert _figures(b_emp[str(TS["b1"])]) == (1, 1, 480, 60, 500, False), b_emp
    assert set(b_acc) == {IDS["creator_b"]}, b_acc
    assert _ts_rows(fx.login_owner("agency_master"), "employee") == {}, "the Master reads its own (empty) Agency"

    for name in ("chatter_a", "chatter_ab", "ts_chatter"):
        r = _timesheet(fx.login_chatter(name))
        assert r.status_code == 403, f"{name}: {r.status_code} {r.text}"
    anon = _harness.make_client()
    assert _timesheet(anon).status_code == 401
    r = _with_anonymous_admin(lambda: _timesheet(anon))
    assert r.status_code == 401, f"with ALLOW_ANONYMOUS_ADMIN=1: {r.status_code} {r.text}"


def case_the_timesheet_refuses_a_bad_group_or_range_and_defaults_to_employees():
    owner_a = fx.login_owner("agency_a_owner")
    assert {r["key"] for r in _timesheet(owner_a, None).json()["rows"]} == set(_ts_rows(owner_a, "employee"))
    for kw, label in (({"group": "fan"}, "unknown group"),
                      ({"to": TS_FROM}, "empty range"),
                      ({"to": "2026-04-14T00:00:01Z"}, "over 42 days"),
                      ({"frm": "2026-03-02"}, "no zone")):
        r = _timesheet(owner_a, **{"group": "employee", **kw})
        assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"


def case_an_open_clock_event_counts_up_to_now_and_sets_open_now():
    owner_a = fx.login_owner("agency_a_owner")
    _time_tracking(owner_a, ON)
    now = _utc_now()
    emp = _employee("ts_open")
    _event(emp, now - timedelta(minutes=30), account_id=TS1)
    _sale(emp, TS1, (now - timedelta(minutes=10)).isoformat(), 300)
    rng = {"frm": _z(now - timedelta(days=1)), "to": _z(now + timedelta(days=1))}
    row = _ts_rows(owner_a, "employee", **rng)[str(emp)]
    assert row["open_now"] is True, row
    assert row["worked_minutes"] in (30, 31), f"counted up to now: {row}"
    assert (row["scheduled_shifts"], row["shifts_worked"], row["recorded_earnings_cents"]) == (0, 0, 300), row
    creator = _ts_rows(owner_a, "account", **rng)[TS1]
    assert creator["open_now"] is True, creator
    assert creator["worked_minutes"] in (30, 31), f"the Creator's open event counted up to now: {creator}"
    assert str(emp) not in _ts_rows(owner_a, "employee"), "an open event leaked into a past week"


def case_agency_wide_clock_events_count_only_on_the_creators_their_shifts_hold_and_minutes_round_up():
    owner_a = fx.login_owner("agency_a_owner")
    fx.store_blob(IDS["agency_a_owner"], "sales", {"multi_employee_shift": True})
    e3 = _employee("ts_casey")
    _create(owner_a, start_utc="2026-03-17T09:00:00Z", end_utc="2026-03-17T13:00:00Z", tz="UTC",
            employee_ids=[e3], account_ids=[TS1, TS2])
    _create(owner_a, start_utc="2026-03-18T09:00:00Z", end_utc="2026-03-18T11:00:00Z", tz="UTC",
            employee_ids=[e3], account_ids=[TS1])
    _create(owner_a, start_utc="2026-03-17T09:30:00Z", end_utc="2026-03-17T10:30:00Z", tz="UTC",
            employee_ids=[e3], account_ids=[TS1])
    for start, end in (("2026-03-17T08:00:00", "2026-03-17T10:00:30"), ("2026-03-19T10:00:00", "2026-03-19T11:00:00"),
                       ("2026-03-18T10:30:00", "2026-03-18T12:00:00")):
        _agency_wide_event(e3, _at(start), _at(end))
    for acc, at, cents in ((TS2, "2026-03-17T09:30:00", 1000), (TS1, "2026-03-19T10:30:00", 2000),
                           (TS2, "2026-03-18T10:45:00", 4000), (TS1, "2026-03-18T10:45:00", 8000)):
        _sale(e3, acc, at, cents)
    week = {"frm": "2026-03-16T00:00:00Z", "to": "2026-03-23T00:00:00Z"}

    row = _ts_rows(owner_a, "employee", **week)[str(e3)]
    assert _figures(row) == (3, 3, 420, 271, 9000, False), row
    rows = _ts_rows(owner_a, "account", **week)
    assert _figures(rows[TS1]) == (3, 3, 420, 91, 8000, False), rows[TS1]
    assert _figures(rows[TS2]) == (1, 1, 240, 61, 1000, False), rows[TS2]


_harness.run(
    case_the_timesheet_per_employee_clips_at_the_week_edges_and_counts_only_earnings_in_worked_time,
    case_an_employee_row_names_its_employee_id_and_group_and_a_creator_row_neither,
    case_the_timesheet_per_creator_counts_each_occurrence_once_and_its_creators_earnings,
    case_the_timesheet_reads_one_agency_and_is_owner_and_master_only,
    case_the_timesheet_refuses_a_bad_group_or_range_and_defaults_to_employees,
    case_an_open_clock_event_counts_up_to_now_and_sets_open_now,
    case_agency_wide_clock_events_count_only_on_the_creators_their_shifts_hold_and_minutes_round_up,
)
