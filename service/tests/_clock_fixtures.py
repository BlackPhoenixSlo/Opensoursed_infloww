"""service/tests/_clock_fixtures.py — the clock and Timesheet suites' shared seeders.

Extracted from test_clock_api.py when the Timesheet cases (ticket 14) moved
to test_timesheet_api.py to keep both files under 1,000 lines. Both suites
sit on this bench: an Agency A Shift through POST /admin/shifts, Time
tracking through PUT /admin/settings/time-tracking, and roster Employees and
Clock events seeded straight into the temp DB with past timestamps, so no
clock is mocked.

NOT a test file: no `case_*`, no `_harness.run()`. Importers bootstrap
`_harness` FIRST (the temp-DB footgun), then import this.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

import _agency_fixtures as fx
from db.engine import get_session
from db.models import ClockEvent, Employee, Shift, ShiftAssignment

IDS = fx.seed_two_agencies()

ON = {"enabled": True, "auto_clock_out_minutes": 60, "clock_in_reminder": False}


def utc_now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def create(client, **body) -> dict:
    """POST /admin/shifts as `client`; asserts 200 and returns the body."""
    r = client.post("/admin/shifts", json=body)
    assert r.status_code == 200, f"create: {r.status_code} {r.text}"
    return r.json()


def time_tracking(client, blob: dict) -> None:
    """Save Time tracking backdated to the start (it is versioned, roadmap W6
    6.4), so it applies to every fixture event, as a save did before."""
    r = client.put("/admin/settings/time-tracking", json=blob, params={"effective_from": "1970-01-01T00:00:00Z"})
    assert r.status_code == 200, f"PUT time-tracking: {r.status_code} {r.text}"


def with_anonymous_admin(fn):
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        return fn()
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)


async def _new_employee(name: str, owner: str) -> int:
    async with get_session() as s:
        row = Employee(display_name=name, is_active=True, created_at=datetime.utcnow(), user_id=IDS[owner])
        s.add(row)
        await s.flush()
        return row.id


def employee(name: str, owner: str = "agency_a_owner") -> int:
    """A roster Employee of `owner`'s Agency; returns its id."""
    return asyncio.run(_new_employee(name, owner))


async def _insert_event(employee_id: int, in_utc: datetime, out_utc: datetime | None, shift_id: int | None,
                        owner: str, account_id: str | None) -> int:
    async with get_session() as s:
        ev = ClockEvent(agency_user_id=IDS[owner], employee_id=employee_id, account_id=account_id,
                        shift_id=shift_id, in_utc=in_utc, out_utc=out_utc,
                        close_reason="manual" if out_utc is not None else None)
        s.add(ev)
        await s.flush()
        return ev.id


def event(employee_id: int, in_utc: datetime, out_utc: datetime | None = None, shift_id: int | None = None,
          owner: str = "agency_a_owner", account_id: str | None = None) -> int:
    """A Clock event (open when `out_utc` is None) on `account_id`, by default
    the owner's Agency's fixture Creator; returns its id."""
    return asyncio.run(_insert_event(employee_id, in_utc, out_utc, shift_id, owner,
                                     account_id or IDS["creator_a" if owner == "agency_a_owner" else "creator_b"]))


def agency_wide_event(employee_id: int, in_utc: datetime, out_utc: datetime | None = None,
                      owner: str = "agency_a_owner") -> int:
    """A Clock event on no Creator (the top bar's agency-wide clock, w4-a);
    returns its id."""
    return asyncio.run(_insert_event(employee_id, in_utc, out_utc, None, owner, None))


async def _insert_shift(start_utc: datetime, end_utc: datetime, held: list[tuple[int, str]], owner: str) -> int:
    async with get_session() as s:
        sh = Shift(agency_user_id=IDS[owner], start_utc=start_utc, end_utc=end_utc, tz="UTC",
                   created_by=f"owner:{IDS[owner]}")
        s.add(sh)
        await s.flush()
        s.add_all(ShiftAssignment(shift_id=sh.id, employee_id=emp, account_id=acc) for emp, acc in held)
        return sh.id


def shift(start_utc: datetime, end_utc: datetime, held: list[tuple[int, str]],
          owner: str = "agency_a_owner") -> int:
    """A one-off Shift seeded straight into the DB (any past time, unlike
    POST /admin/shifts), assigning each `(employee_id, account_id)`; returns
    its id."""
    return asyncio.run(_insert_shift(start_utc, end_utc, held, owner))
