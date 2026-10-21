#!/usr/bin/env python3
"""Recurring-shift scope (roadmap W6 6.3, 07 M15): an edit or a delete of one
occurrence of a weekly series reaches "this shift", "this and following" or
"all shifts", never the whole series by accident.

The seam is the Relay over HTTP with real owner sessions from the shared
two-Agency fixture: Shifts go through POST /admin/shifts, edits through PATCH
/admin/shifts/{id} and deletes through POST /admin/shifts/{id}/cancel, each
with `scope` and `occurrence_start`; every assertion reads the week list, the
Timesheet, the Shift answer or its audit rows. Each case owns its Creator and
Employee, so Agency A's overlap rule (Multiple employees per shift off) never
trips across cases.

Run: ./venv/bin/python service/tests/test_shift_scope.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import IDS, create as _create, employee as _employee, event as _event  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, Shift, UserAccount  # noqa: E402

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")

# Five Mondays in March 2026 (UTC has no DST): 09:00-17:00Z, repeating until 30 March.
MONDAYS = ["2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23", "2026-03-30"]
MARCH = {"from": "2026-03-01T00:00:00Z", "to": "2026-04-06T00:00:00Z"}
_next_creator = iter(range(1_000_301, 1_000_400))


def _creator(owner: str = "agency_a_owner") -> str:
    """A Creator of `owner`'s Agency used by one case only."""
    aid = str(next(_next_creator))

    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"scope_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS[owner], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


def _series(emp: int, aid: str, client=OWNER_A) -> dict:
    """The weekly Monday series on `aid` held by `emp`."""
    return _create(client, start_utc=f"{MONDAYS[0]}T09:00:00Z", end_utc=f"{MONDAYS[0]}T17:00:00Z", tz="UTC",
                   repeat_days=[1], repeat_until=MONDAYS[-1], employee_ids=[emp], account_ids=[aid])


def _week(aid: str, client=OWNER_A) -> list[tuple[int, str, str]]:
    """`(shift_id, occurrence_start, occurrence_end)` on `aid` through March."""
    r = client.get("/admin/shifts", params={**MARCH, "account_id": aid})
    assert r.status_code == 200, f"week: {r.status_code} {r.text}"
    return [(o["shift_id"], o["occurrence_start"], o["occurrence_end"]) for o in r.json()["occurrences"]]


def _starts(aid: str) -> list[str]:
    return [start for _, start, _ in _week(aid)]


def _cancel(shift_id: int, scope: str | None, day: str | None = None, client=OWNER_A):
    body = None if scope is None else {"scope": scope, "occurrence_start": f"{day}T09:00:00Z" if day else None}
    return client.post(f"/admin/shifts/{shift_id}/cancel", json=body)


def _edit_body(emp: int, aid: str, day: str, start: str = "09:00", end: str = "17:00", **extra) -> dict:
    return {"start_utc": f"{day}T{start}:00Z", "end_utc": f"{day}T{end}:00Z", "tz": "UTC",
            "repeat_days": [1], "repeat_until": MONDAYS[-1], "employee_ids": [emp], "account_ids": [aid], **extra}


def _row(shift_id: int) -> Shift:
    async def _get():
        async with get_session() as s:
            return await s.get(Shift, shift_id)
    return asyncio.run(_get())


def _audit(shift_id: int) -> list[tuple[str, dict]]:
    async def _get():
        async with get_session() as s:
            rows = (await s.execute(select(Action.action, Action.payload_json).where(
                Action.target_type == "shift", Action.target_id == str(shift_id)).order_by(Action.id))).all()
        return [(a, json.loads(p)) for a, p in rows]
    return asyncio.run(_get())


def _at(day: str, hhmm: str) -> str:
    return f"{day}T{hhmm}:00Z"


# ── Delete ──────────────────────────────────────────────────────────


def case_this_shift_delete_keeps_every_other_occurrence():
    aid, emp = _creator(), _employee("scope_this_delete")
    sid = _series(emp, aid)["shift_id"]
    r = _cancel(sid, "this", MONDAYS[2])
    assert r.status_code == 200, f"cancel this: {r.status_code} {r.text}"
    body = r.json()
    assert (body["status"], body["cancelled_dates"]) == ("scheduled", [MONDAYS[2]]), body
    assert _starts(aid) == [_at(d, "09:00") for d in MONDAYS if d != MONDAYS[2]], _starts(aid)
    # The same occurrence again is no longer one of the series'.
    r = _cancel(sid, "this", MONDAYS[2])
    assert r.status_code == 422, f"cancel it twice: {r.status_code} {r.text}"
    # One audit row records the cut, before and after.
    action, payload = _audit(sid)[-1]
    assert action == "shift.cancel", action
    assert (payload["before"]["cancelled_dates"], payload["after"]["cancelled_dates"]) == ([], [MONDAYS[2]])


def case_this_shift_and_following_delete_ends_the_series_the_day_before():
    aid, emp = _creator(), _employee("scope_following_delete")
    sid = _series(emp, aid)["shift_id"]
    _cancel(sid, "this", MONDAYS[3])  # an exception after the cut is dropped with it
    r = _cancel(sid, "following", MONDAYS[2])
    assert r.status_code == 200, f"cancel following: {r.status_code} {r.text}"
    body = r.json()
    assert (body["status"], body["repeat_until"], body["cancelled_dates"]) == ("scheduled", "2026-03-15", []), body
    assert _starts(aid) == [_at(d, "09:00") for d in MONDAYS[:2]], _starts(aid)


def case_all_shifts_and_following_from_the_first_date_cancel_the_whole_series():
    aid, emp = _creator(), _employee("scope_all_delete")
    first = _series(emp, aid)["shift_id"]
    r = _cancel(first, "following", MONDAYS[0])
    assert (r.status_code, r.json()["status"]) == (200, "cancelled"), r.text
    second = _series(emp, aid)["shift_id"]
    assert _cancel(second, "all").json()["status"] == "cancelled"
    third = _series(emp, aid)["shift_id"]
    assert _cancel(third, None).json()["status"] == "cancelled", "no body is still the whole series"
    assert _starts(aid) == []


def case_following_from_the_first_occurrence_left_after_the_first_date_was_cut_is_the_whole_series():
    # The 2nd's occurrence was deleted alone, so the 9th is the first one left:
    # "following" from it cancels the series rather than leave an empty one.
    aid, emp = _creator(), _employee("scope_first_left")
    sid = _series(emp, aid)["shift_id"]
    _cancel(sid, "this", MONDAYS[0])
    r = _cancel(sid, "following", MONDAYS[1])
    assert (r.status_code, r.json()["status"]) == (200, "cancelled"), r.text
    assert _starts(aid) == []
    # The edit does the same: in place, keeping the id.
    sid = _series(emp, aid)["shift_id"]
    _cancel(sid, "this", MONDAYS[0])
    r = OWNER_A.patch(f"/admin/shifts/{sid}", json=_edit_body(
        emp, aid, MONDAYS[1], "08:00", "16:00", scope="following", occurrence_start=_at(MONDAYS[1], "09:00")))
    assert (r.status_code, r.json()["shift_id"]) == (200, sid), r.text
    assert _starts(aid) == [_at(d, "08:00") for d in MONDAYS[1:]], _starts(aid)


def case_a_one_off_shifts_this_shift_delete_cancels_it():
    aid, emp = _creator(), _employee("scope_one_off")
    sid = _create(OWNER_A, start_utc=_at(MONDAYS[1], "09:00"), end_utc=_at(MONDAYS[1], "17:00"), tz="UTC",
                  employee_ids=[emp], account_ids=[aid])["shift_id"]
    r = _cancel(sid, "this", MONDAYS[1])
    assert (r.status_code, r.json()["status"]) == (200, "cancelled"), r.text


def case_a_scope_from_an_instant_that_is_no_occurrence_is_422():
    aid, emp = _creator(), _employee("scope_bad")
    sid = _series(emp, aid)["shift_id"]
    for body in ({"scope": "this", "occurrence_start": "2026-03-03T09:00:00Z"},  # a Tuesday
                 {"scope": "this", "occurrence_start": "2026-03-09T10:00:00Z"},  # not its start
                 {"scope": "following"},
                 {"scope": "some"}):
        r = OWNER_A.post(f"/admin/shifts/{sid}/cancel", json=body)
        assert r.status_code == 422, f"{body}: {r.status_code} {r.text}"
        r = OWNER_A.patch(f"/admin/shifts/{sid}", json=_edit_body(emp, aid, MONDAYS[1], **body))
        assert r.status_code == 422, f"edit {body}: {r.status_code} {r.text}"
    assert len(_starts(aid)) == 5, "a refused scope wrote nothing"


# ── Edit ────────────────────────────────────────────────────────────


def case_this_and_following_edit_splits_the_series():
    aid, emp = _creator(), _employee("scope_split")
    sid = _series(emp, aid)["shift_id"]
    _cancel(sid, "this", MONDAYS[1])  # before the split: stays on the old series
    _cancel(sid, "this", MONDAYS[3])  # after it: carried over to the new one
    r = OWNER_A.patch(f"/admin/shifts/{sid}", json=_edit_body(
        emp, aid, MONDAYS[2], "10:00", "18:00", scope="following", occurrence_start=_at(MONDAYS[2], "09:00")))
    assert r.status_code == 200, f"edit following: {r.status_code} {r.text}"
    new = r.json()
    assert new["shift_id"] != sid
    assert (new["start_utc"], new["repeat_days"], new["repeat_until"], new["cancelled_dates"]) == \
        (_at(MONDAYS[2], "10:00"), [1], MONDAYS[-1], [MONDAYS[3]]), new
    old = _row(sid)
    assert (old.status, str(old.repeat_until), json.loads(old.cancelled_dates)) == \
        ("scheduled", "2026-03-15", [MONDAYS[1]])
    assert _week(aid) == [
        (sid, _at(MONDAYS[0], "09:00"), _at(MONDAYS[0], "17:00")),
        (new["shift_id"], _at(MONDAYS[2], "10:00"), _at(MONDAYS[2], "18:00")),
        (new["shift_id"], _at(MONDAYS[4], "10:00"), _at(MONDAYS[4], "18:00")),
    ], _week(aid)
    assert [a for a, _ in _audit(sid)][-1] == "shift.edit"
    assert [a for a, _ in _audit(new["shift_id"])] == ["shift.create"]


def case_only_this_shift_edit_is_an_exception_plus_a_one_off():
    aid, emp = _creator(), _employee("scope_only_this")
    sid = _series(emp, aid)["shift_id"]
    r = OWNER_A.patch(f"/admin/shifts/{sid}", json=_edit_body(
        emp, aid, MONDAYS[1], "12:00", "20:00", scope="this", occurrence_start=_at(MONDAYS[1], "09:00")))
    assert r.status_code == 200, f"edit this: {r.status_code} {r.text}"
    one_off = r.json()
    assert (one_off["repeat_days"], one_off["repeat_until"]) == (None, None), "the one-off never repeats"
    assert json.loads(_row(sid).cancelled_dates) == [MONDAYS[1]]
    week = _week(aid)
    assert [(s == sid, start) for s, start, _ in week] == [
        (True, _at(MONDAYS[0], "09:00")), (False, _at(MONDAYS[1], "12:00")), (True, _at(MONDAYS[2], "09:00")),
        (True, _at(MONDAYS[3], "09:00")), (True, _at(MONDAYS[4], "09:00"))], week


def case_following_from_the_first_occurrence_edits_the_whole_series_in_place():
    aid, emp = _creator(), _employee("scope_first")
    sid = _series(emp, aid)["shift_id"]
    _cancel(sid, "this", MONDAYS[3])
    r = OWNER_A.patch(f"/admin/shifts/{sid}", json=_edit_body(
        emp, aid, MONDAYS[0], "08:00", "16:00", scope="following", occurrence_start=_at(MONDAYS[0], "09:00")))
    assert r.status_code == 200, f"edit following from the first: {r.status_code} {r.text}"
    assert (r.json()["shift_id"], r.json()["cancelled_dates"]) == (sid, [MONDAYS[3]]), r.json()
    assert _starts(aid) == [_at(d, "08:00") for d in MONDAYS if d != MONDAYS[3]], _starts(aid)


def case_an_occurrence_edit_does_not_clash_with_the_occurrence_it_replaces():
    # Agency B never allows multiple employees per shift. Moving one occurrence
    # an hour later overlaps only the occurrence it replaces, so it saves; moving
    # it onto the next Monday's occurrence clashes with the series.
    aid, emp = _creator("agency_b_owner"), _employee("scope_clash", "agency_b_owner")
    sid = _series(emp, aid, OWNER_B)["shift_id"]
    occ = _at(MONDAYS[1], "09:00")
    r = OWNER_B.patch(f"/admin/shifts/{sid}", json=_edit_body(
        emp, aid, MONDAYS[1], "10:00", "18:00", scope="this", occurrence_start=occ))
    assert r.status_code == 200, f"move one occurrence: {r.status_code} {r.text}"
    r = OWNER_B.patch(f"/admin/shifts/{sid}", json=_edit_body(
        emp, aid, MONDAYS[3], "12:00", "20:00", scope="this", occurrence_start=_at(MONDAYS[2], "09:00")))
    assert r.status_code == 409, f"onto another occurrence: {r.status_code} {r.text}"
    assert r.json()["clashes"][0]["shift_id"] == sid, r.json()
    assert json.loads(_row(sid).cancelled_dates) == [MONDAYS[1]], "a refused edit cut nothing"


# ── Readers ─────────────────────────────────────────────────────────


def _timesheet(frm: str, to: str) -> dict[str, tuple]:
    r = OWNER_A.get("/admin/shifts/timesheet", params={"from": frm, "to": to, "group": "account"})
    assert r.status_code == 200, f"timesheet: {r.status_code} {r.text}"
    return {row["key"]: (row["scheduled_shifts"], row["shifts_worked"], row["scheduled_minutes"],
                         row["worked_minutes"]) for row in r.json()["rows"]}


def case_the_timesheet_reads_untouched_occurrences_as_before():
    # A worked example: each Monday is 480 scheduled minutes; the employee
    # clocked 09:00-13:00 on the 2nd and the 16th. Removing the 9th changes
    # only the week of the 9th, and only by that occurrence.
    aid, emp = _creator(), _employee("scope_timesheet")
    sid = _series(emp, aid)["shift_id"]
    for day in (MONDAYS[0], MONDAYS[2]):
        _event(emp, datetime.fromisoformat(f"{day}T09:00:00"), datetime.fromisoformat(f"{day}T13:00:00"),
               account_id=aid)
    weeks = [(f"{d}T00:00:00Z", f"2026-03-{int(d[-2:]) + 7:02d}T00:00:00Z") for d in MONDAYS[:4]]
    before = [_timesheet(*w).get(aid) for w in weeks]
    assert before == [(1, 1, 480, 240), (1, 0, 480, 0), (1, 1, 480, 240), (1, 0, 480, 0)], before
    assert _cancel(sid, "this", MONDAYS[1]).status_code == 200
    after = [_timesheet(*w).get(aid) for w in weeks]
    assert after == [before[0], None, before[2], before[3]], after


_harness.run()
