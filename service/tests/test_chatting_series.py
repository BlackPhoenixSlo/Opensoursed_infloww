#!/usr/bin/env python3
"""Employee reports' charts (roadmap W5 5.10): `GET /admin/stats/chatting-stats?bucket=` — the Overview's "Employee
sales" and comparison lines and the Employee performance tab's Sales and Message statistics, in one answer.

  edges     buckets begin at the report zone's midnight (whatever its offset that day), weeks on the Agency's week
            start, months on the 1st; hours are an hour apart in UTC.
  series    one point per bucket: Sales by the Sales Settings rules (pending too), and the Employees' own sends,
            summed in `series` and per Employee in `by_employee`; the Automation sentinel and Unattributed sales in
            none; fans distinct within a point. A Creator whose Rules change in the window is read sale by sale, and
            the points add up to Chatting statistics' totals.
  windows   a granularity the range's calendar days (its length rounded to whole days, from any zone's midnights)
            do not allow is refused (Infloww's: hour up to 2 days, day under 14 or to 31, week 14 to 365, month over
            62); October in Europe is 31 days.
  scope     a "self" Data scope charts only its own Employee.
  plans     the bucketed sends read still seeks ix_messages_chatter_sends.

Seeded straight into the temp DB; no network.

Run: ./venv/bin/python service/tests/test_chatting_series.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import employees  # noqa: E402
import msg_stats  # noqa: E402
import stats  # noqa: E402
from _clock_fixtures import IDS, employee as _employee  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, Transaction, UserAccount  # noqa: E402

ENGINE = sa.create_engine(os.environ["CHATTERLY_DB_URL"])
OWNER_A = fx.login_owner("agency_a_owner")
CHATTER_A = fx.login_chatter("chatter_a")
URL = "/admin/stats/chatting-stats"


def _creator(aid: str) -> str:
    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"series_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


def _sentinel() -> int:
    async def _seed():
        async with get_session() as s:
            row = Employee(display_name="Automation", is_active=False)
            s.add(row)
            await s.flush()
            return row.id
    return asyncio.run(_seed())


_mid = iter(range(71_000_001, 71_100_000))


def _msg(aid: str, fan: int, sender: int | None, at: datetime, price: int = 0, paid: bool | None = None,
         mass_run_id: int | None = None) -> int:
    mid = next(_mid)
    with ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, sent_by_employee_id, mass_run_id, "
            "created_at, ingested_at) VALUES (:a, :f, :m, 'out', '', 'x', '[]', 0, :p, :paid, 0, 0, 0, :e, :r, :c, :c)"),
            {"a": aid, "f": fan, "m": mid, "p": price, "paid": paid, "e": sender, "r": mass_run_id,
             "c": at.strftime("%Y-%m-%d %H:%M:%S.%f")})
    return mid


def _sale(aid: str, cents: int, at: datetime, fan: int, message_id: int | None = None, kind: str = "ppv_message",
          status: str = "cleared") -> None:
    async def _seed():
        async with get_session() as s:
            s.add(Transaction(account_id=aid, fan_id=fan, kind=kind, message_id=message_id, amount_cents=cents,
                              occurred_at=at, status=status, currency="USD", source="ledger"))
    asyncio.run(_seed())


def _get(client=OWNER_A, status: int = 200, **params) -> dict:
    r = client.get(URL, params=params)
    assert r.status_code == status, f"{r.status_code} {r.text}"
    return r.json()


def _col(points: list, key: str) -> list:
    return [p[key] for p in points]


C1, C2, C3 = _creator("5300001"), _creator("5300002"), _creator("5300003")
E1, E2 = _employee("series_emp_1"), _employee("series_emp_2")
AUTO = _sentinel()
D = datetime(2026, 3, 2)  # a Monday

# Day 1: E1 sends a PPV fan 1 buys (pending) and a text to fan 1 again; E2 one send. Day 2: E1 on two Creators,
# the same fan id; a mass message and the sentinel's send count for no one. Day 3: an orphan tip (Unattributed).
P1 = _msg(C1, 1, E1, D.replace(hour=9), price=1000, paid=True)
_msg(C1, 1, E1, D.replace(hour=10))
P2 = _msg(C1, 2, E2, D.replace(hour=11), price=500)
_sale(C1, 1000, D.replace(hour=12), fan=1, message_id=P1, status="pending")
_sale(C1, 500, D.replace(hour=13), fan=2, message_id=P2)
_msg(C1, 3, E1, D.replace(day=3, hour=8))
_msg(C2, 3, E1, D.replace(day=3, hour=8))
_msg(C1, 4, E1, D.replace(day=3, hour=9), mass_run_id=7)
A = _msg(C1, 5, AUTO, D.replace(day=3, hour=9), price=900)
_sale(C1, 900, D.replace(day=3, hour=10), fan=5, message_id=A)
_sale(C1, 250, D.replace(day=4, hour=10), fan=9, kind="tip")
RANGE = {"from": "2026-03-02", "to": "2026-03-04"}


def case_edges_follow_the_report_zone_week_start_and_months():
    la = ZoneInfo("America/Los_Angeles")
    # 8 March 2026 is the US spring-forward: midnight is 08:00 UTC before it, 07:00 after.
    days = stats._bucket_edges("day", datetime(2026, 3, 7, 8), datetime(2026, 3, 9, 7, 30), la)
    assert days == [datetime(2026, 3, 7, 8), datetime(2026, 3, 8, 8), datetime(2026, 3, 9, 7)], days
    wed = datetime(2026, 3, 4, 15)
    assert stats._bucket_edges("week", wed, wed + timedelta(days=8), None) == [
        datetime(2026, 3, 2), datetime(2026, 3, 9)]
    assert stats._bucket_edges("week", wed, wed + timedelta(days=8), None, "sunday") == [
        datetime(2026, 3, 1), datetime(2026, 3, 8)]
    months = stats._bucket_edges("month", datetime(2026, 1, 20), datetime(2026, 4, 1), None)
    assert months == [datetime(2026, 1, 1), datetime(2026, 2, 1), datetime(2026, 3, 1), datetime(2026, 4, 1)], months
    hours = stats._bucket_edges("hour", datetime(2026, 3, 2, 10, 30), datetime(2026, 3, 2, 12), None)
    assert hours == [datetime(2026, 3, 2, 10), datetime(2026, 3, 2, 11), datetime(2026, 3, 2, 12)], hours


def case_the_overview_sums_every_employee_per_day_and_lists_each_leaving_out_automation_and_unattributed():
    body = _get(bucket="day", **RANGE)
    series, by_emp = body["series"], body["by_employee"]
    assert body["bucket"] == "day" and set(by_emp) == {str(E1), str(E2)}, body
    assert _col(series, "start") == ["2026-03-02T00:00", "2026-03-03T00:00", "2026-03-04T00:00"], body
    assert _col(series, "sales_cents") == [1500, 0, 0], body
    assert _col(series, "direct_messages_sent") == [3, 2, 0], body
    assert _col(series, "direct_ppvs_sent") == [2, 0, 0], body
    assert _col(series, "ppvs_unlocked") == [1, 0, 0], body
    # Fans distinct per Creator and Employee within a day: E1's fan 1 once, E2's fan 2; fan 3 on two Creators.
    assert _col(series, "fans_chatted") == [2, 2, 0], body
    assert _col(by_emp[str(E1)], "sales_cents") == [1000, 0, 0] and _col(by_emp[str(E2)], "sales_cents") == [500, 0, 0]
    assert _col(by_emp[str(E1)], "fans_chatted") == [1, 2, 0], by_emp


def case_one_employees_performance_by_hour():
    body = _get(bucket="hour", **{"from": "2026-03-02", "to": "2026-03-02"})
    assert len(body["series"]) == 24, body
    e1 = body["by_employee"][str(E1)]
    assert len(e1) == 24 and (e1[9]["direct_ppvs_sent"], e1[10]["direct_messages_sent"]) == (1, 1), e1
    assert e1[12]["sales_cents"] == 1000 and sum(_col(e1, "sales_cents")) == 1000, e1


def case_a_granularity_the_ranges_calendar_days_do_not_allow_is_refused():
    assert len(_get(bucket="hour", **{"from": "2026-03-01", "to": "2026-03-02"})["series"]) == 48
    _get(status=400, bucket="hour", **{"from": "2026-03-01", "to": "2026-03-03"})
    _get(status=400, bucket="month", **RANGE)
    _get(status=400, bucket="week", **RANGE)
    _get(status=400, bucket="day", **{"from": "2026-03-01", "to": "2026-04-01"})  # 32 days: week only
    _get(status=422, bucket="year", **RANGE)
    assert len(_get(bucket="week", **{"from": "2026-03-02", "to": "2026-03-15"})["series"]) == 2
    assert [d for d in range(1, 400) if stats._bucket_allowed("month", d)][0] == 63
    assert not stats._bucket_allowed("week", 366) and stats._bucket_allowed("week", 365)


def case_a_browsers_month_from_its_own_midnights_is_its_days_with_no_report_zone_saved():
    # No report zone (UTC): the app sends the browser's midnights. Berlin's October touches 32 UTC days, still 31 days.
    october = {"from": "2026-10-01T00:00:00.000+02:00", "to": "2026-10-31T23:59:59.999+01:00"}
    assert len(_get(bucket="day", **october)["series"]) == 32
    january = {"from": "2026-01-01T00:00:00.000-05:00", "to": "2026-01-31T23:59:59.999-05:00"}
    assert len(_get(bucket="day", **january)["series"]) == 32
    _get(status=400, bucket="day", **{"from": "2026-01-01T00:00:00.000-05:00", "to": "2026-02-01T23:59:59.999-05:00"})
    assert stats._range_days(datetime(2026, 3, 8, 8), datetime(2026, 3, 9, 6, 59, 59, 999000)) == 1  # LA's 23 hours


def _roles(scope: str, emp: int) -> None:
    r = OWNER_A.put("/admin/settings/roles", json={
        "enforce": True, "assignments": {str(emp): "role-series"},
        "roles": [{"id": "role-series", "name": "Fixture role-series", "description": "",
                   "permissions": {"/analytics/employee-reports": True}, "scope": scope}]})
    assert r.status_code == 200, r.text


def case_a_self_scope_charts_only_its_own_employee():
    emp_a = asyncio.run(employees.get_or_create_mirror_employee(
        IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
    ppv = _msg(IDS["creator_a"], 61, emp_a, D.replace(hour=14), price=300)
    _sale(IDS["creator_a"], 300, D.replace(hour=15), fan=61, message_id=ppv)
    _msg(IDS["creator_a"], 62, E2, D.replace(hour=14))
    try:
        _roles("self", emp_a)
        mine = _get(CHATTER_A, bucket="day", **RANGE)
        assert list(mine["by_employee"]) == [str(emp_a)], mine
        assert _col(mine["series"], "sales_cents") == [300, 0, 0], mine
        assert _col(mine["series"], "direct_messages_sent") == [1, 0, 0], mine
    finally:
        OWNER_A.put("/admin/settings/roles", json={"enforce": False})


def case_the_bucketed_sends_read_seeks_the_chatter_sends_index():
    edges = stats._bucket_edges("day", D, D.replace(day=4, hour=23), None)
    sql, params = asyncio.run(msg_stats.send_stats_sql(account_ids=[C1], start=D, end=D.replace(day=4, hour=23),
                                                       edges=edges))

    async def _run():
        async with get_session() as s:
            await s.execute(text("ANALYZE"))
            return (await s.execute(text("EXPLAIN QUERY PLAN " + sql), params)).all()
    plan = " | ".join(str(r[-1]) for r in asyncio.run(_run()))
    assert "USING INDEX ix_messages_chatter_sends (account_id=? AND direction=? AND created_at>? AND created_at<?)" \
        in plan, plan


def _prefs(blob: dict) -> None:
    r = OWNER_A.put("/admin/settings/preferences", json=blob)
    assert r.status_code == 200, r.text


def case_october_in_berlin_is_31_days_and_its_weeks_begin_on_sunday():
    # 25 October 2026 01:00 UTC Berlin falls back to CET: 23:30 UTC that day is 00:30 on Monday the 26th.
    p = _msg(C3, 1, E2, datetime(2026, 10, 25, 23, 0), price=700)
    _sale(C3, 700, datetime(2026, 10, 25, 23, 30), fan=1, message_id=p)
    october = {"from": "2026-10-01", "to": "2026-10-31"}
    try:
        _prefs({"report_tz": "Europe/Berlin", "week_start": "sunday"})
        days = _get(bucket="day", **october)["series"]  # 745 hours, 31 calendar days: by day is allowed
        assert len(days) == 31 and days[25]["start"] == "2026-10-26T00:00", days[25]
        assert days[25]["sales_cents"] == 700 and days[25]["direct_messages_sent"] == 1, days[24:27]
        weeks = _get(bucket="week", **october)["series"]
        assert _col(weeks, "start") == ["2026-09-27T00:00", "2026-10-04T00:00", "2026-10-11T00:00",
                                        "2026-10-18T00:00", "2026-10-25T00:00"], weeks
        assert _col(weeks, "sales_cents") == [0, 0, 0, 0, 700], weeks
    finally:
        _prefs({"report_tz": "UTC", "week_start": "monday"})


def case_the_points_add_up_to_the_tables_totals_when_the_rules_change_in_the_window():
    # Last: the fee setting stays on for Agency A after it. C2's Rules change mid-window, so it is read sale by sale.
    r = OWNER_A.put("/admin/settings/sales", json={"exclude_of_fee": True},
                    params={"effective_from": "2026-03-03T00:00:00Z"})
    assert r.status_code == 200, r.text
    p = _msg(C2, 8, E1, D.replace(day=3, hour=20), price=1000)
    _sale(C2, 1000, D.replace(day=3, hour=21, minute=30), fan=8, message_id=p)
    body = _get(bucket="day", **RANGE)
    assert _col(body["by_employee"][str(E1)], "sales_cents") == [1000, 800, 0], body
    table = {e["employee_id"]: e for e in _get(**RANGE)["employees"]}
    assert set(table) == {int(k) for k in body["by_employee"]}, (table.keys(), body["by_employee"].keys())
    for key in ("sales_cents", "direct_messages_sent", "direct_ppvs_sent", "ppvs_unlocked"):
        for eid, row in table.items():
            assert sum(_col(body["by_employee"][str(eid)], key)) == row[key], (key, eid)
        assert sum(_col(body["series"], key)) == sum(row[key] for row in table.values()), key


_harness.run()
