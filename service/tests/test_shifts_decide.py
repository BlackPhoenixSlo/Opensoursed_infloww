#!/usr/bin/env python3
"""
Shift schedule and clock decisions — table tests over the pure cores the
`/admin/shifts` routers call (no DB, no loop):

  case_timesheet_by_employee:  shifts_timesheet.timesheet_rows per Employee: an
                               occurrence and an event crossing the range edge are
                               clipped; a multi-employee Shift counts once per
                               Employee; an open event runs to now and sets
                               open_now; a share before the range or after now is
                               not counted; a key with only a sale gets a row.
  case_timesheet_by_account:   the same per Creator: one count per Creator however
                               many Employees; only `on_creator` time counts, so an
                               agency-wide event with no span adds nothing.
  case_overlap_s:              seconds of [a, b) inside [lo, hi); disjoint → 0.
  case_find_overlaps_edges:    touching ends never clash; an overlap is reported at
                               its occurrence start; results in (start, id) order.
  case_find_overlaps_multi:    own double-staffing once per Creator, first.
  case_find_overlaps_repeat:   weekly series: the first clashing occurrence, a
                               cancelled date skipped; `hits` carries every clash
                               within OVERLAP_HORIZON.
  case_clock_gate_table:       clock_api.clock_gate: every `_REFUSALS` reason in
                               precedence, and the allowed rows.
  case_needs_roles_table:      clock_api.needs_roles: the roles blob is read only
                               with time tracking on, a saved role list, not owner.
  case_due_clock_outs_table:   clock_api.due_clock_outs: due exactly at N minutes,
                               not a microsecond before; heartbeat / audit activity
                               push the deadline; none open → nothing.
  case_time_tracking_of:       clock_api.time_tracking_of: defaults (off, 10
                               minutes, no role list), literal `true` only.

Run: ./venv/bin/python service/tests/test_shifts_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from clock_api import (  # noqa: E402
    DEFAULT_AUTO_CLOCK_OUT_MINUTES, _REFUSALS, TimeTracking, clock_gate, due_clock_outs, needs_roles,
    time_tracking_of,
)
from db.models import ClockEvent, Employee, Shift  # noqa: E402
from shifts_api import find_overlaps  # noqa: E402
from shifts_timesheet import _overlap_s, timesheet_rows  # noqa: E402

H = timedelta(hours=1)
LO, HI = datetime(2026, 11, 2), datetime(2026, 11, 9)   # Monday 2 Nov to Monday 9 Nov
NOW = datetime(2026, 11, 5, 12)


def _shift(sid, start, end, repeat_days=None, cancelled=None) -> Shift:
    return Shift(id=sid, agency_user_id="a", start_utc=start, end_utc=end, tz="UTC", status="scheduled",
                 repeat_days=repeat_days, repeat_until=None, cancelled_dates=cancelled)


def _event(eid, emp, acc, in_utc, out_utc=None, last_seen=None, agency="a") -> ClockEvent:
    return ClockEvent(id=eid, agency_user_id=agency, employee_id=emp, account_id=acc,
                      in_utc=in_utc, out_utc=out_utc, last_seen_utc=last_seen)


def _share(emp, acc, at, cents):
    return SimpleNamespace(employee_id=emp, account_id=acc, occurred_at=at, amount_cents=cents)


# The Timesheet bench: Shift 1 crosses the range's start (Sun 22:00 → Mon 06:00),
# Shift 2 puts Employees 10 and 11 on Creator c1, and 11 on c2 too.
SH1 = _shift(1, datetime(2026, 11, 1, 22), datetime(2026, 11, 2, 6))
SH2 = _shift(2, datetime(2026, 11, 3, 9), datetime(2026, 11, 3, 17))
ASSIGNED = {1: {(10, "c1")}, 2: {(10, "c1"), (11, "c1"), (11, "c2")}}
E1 = _event(1, 10, "c1", datetime(2026, 11, 1, 23), datetime(2026, 11, 2, 5))   # crosses LO
E2 = _event(2, 11, None, datetime(2026, 11, 5, 10))                            # open, agency-wide
E3 = _event(3, 11, "c2", datetime(2026, 11, 3, 16), datetime(2026, 11, 3, 18))
ON_CREATOR = [(E1, "c1", E1.in_utc, E1.out_utc), (E3, "c2", E3.in_utc, E3.out_utc)]
SALES = {
    1: [_share(10, "c1", datetime(2026, 11, 2, 1), 500),
        _share(10, "c1", datetime(2026, 11, 1, 23, 30), 700)],   # before the range
    2: [_share(12, "c3", datetime(2026, 11, 5, 11), 100)],       # a key with no Shift
    3: [_share(11, "c2", datetime(2026, 11, 3, 17), 300),
        _share(11, "c2", datetime(2026, 11, 6), 999)],           # after now
}


def _tally(shifts, worked, sched_s, worked_s, cents, open_now):
    return {"scheduled_shifts": shifts, "shifts_worked": worked, "scheduled_s": float(sched_s),
            "worked_s": float(worked_s), "recorded_earnings_cents": cents, "open_now": open_now}


def case_timesheet_by_employee():
    rows = timesheet_rows([SH1, SH2], ASSIGNED, [E1, E2, E3], ON_CREATOR, SALES, lo=LO, hi=HI, now=NOW,
                          by_employee=True)
    want = {
        10: _tally(2, 1, (6 + 8) * 3600, 5 * 3600, 500, False),        # SH1 clipped to 6h, E1 to 5h
        11: _tally(1, 1, 8 * 3600, (2 + 2) * 3600, 300, True),         # once for two Creators; E2 to now
        12: _tally(0, 0, 0, 0, 100, False),
    }
    assert rows == want, rows
    assert list(rows)[-1] == 12, "an earnings-only key comes last"


def case_timesheet_by_account():
    rows = timesheet_rows([SH1, SH2], ASSIGNED, [E1, E2, E3], ON_CREATOR, SALES, lo=LO, hi=HI, now=NOW,
                          by_employee=False)
    want = {
        "c1": _tally(2, 1, (6 + 8) * 3600, 5 * 3600, 500, False),      # SH2 once for two Employees
        "c2": _tally(1, 1, 8 * 3600, 2 * 3600, 300, False),
        "c3": _tally(0, 0, 0, 0, 100, False),
    }
    assert rows == want, rows
    assert timesheet_rows([], {}, [], [], {}, lo=LO, hi=HI, now=NOW, by_employee=False) == {}


def case_overlap_s():
    t = datetime(2026, 11, 2)
    table = [
        ((t, t + 2 * H, t, t + 4 * H), 7200.0),
        ((t - H, t + H, t, t + 4 * H), 3600.0),
        ((t + 3 * H, t + 6 * H, t, t + 4 * H), 3600.0),
        ((t + 5 * H, t + 6 * H, t, t + 4 * H), 0.0),
        ((t + 4 * H, t + 6 * H, t, t + 4 * H), 0.0),
    ]
    for args, want in table:
        assert _overlap_s(*args) == want, (args, _overlap_s(*args))


def case_find_overlaps_edges():
    mine = _shift(None, datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 17))
    touching_after = _shift(5, datetime(2026, 11, 2, 17), datetime(2026, 11, 2, 20))
    touching_before = _shift(6, datetime(2026, 11, 2, 6), datetime(2026, 11, 2, 9))
    # A series from the week before whose 2 Nov occurrence starts as `mine` ends.
    touching_series = _shift(7, datetime(2026, 10, 26, 17), datetime(2026, 10, 26, 20), repeat_days="[1]")
    clashes, hits = find_overlaps(mine, [1], ["c1"], {5: (touching_after, {"c1"}), 6: (touching_before, {"c1"}),
                                                      7: (touching_series, {"c1"})})
    assert (clashes, hits) == ([], {}), clashes

    late = _shift(8, datetime(2026, 11, 2, 16), datetime(2026, 11, 2, 18))
    early = _shift(9, datetime(2026, 11, 2, 8), datetime(2026, 11, 2, 10))
    clashes, hits = find_overlaps(mine, [1], ["c1", "c2"], {8: (late, {"c1"}), 9: (early, {"c2", "c1"})})
    assert clashes == [
        {"shift_id": 9, "occurrence_start": "2026-11-02T08:00:00Z", "account_id": "c1"},
        {"shift_id": 9, "occurrence_start": "2026-11-02T08:00:00Z", "account_id": "c2"},
        {"shift_id": 8, "occurrence_start": "2026-11-02T16:00:00Z", "account_id": "c1"},
    ], clashes
    assert hits == {8: (late, [late.start_utc]), 9: (early, [early.start_utc])}, hits


def case_find_overlaps_multi():
    mine = _shift(None, datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 17))
    other = _shift(5, datetime(2026, 11, 2, 10), datetime(2026, 11, 2, 11))
    existing = {5: (other, {"c1"})}
    clashes, hits = find_overlaps(mine, [1, 2], ["c1", "c2"], existing)
    assert clashes == [
        {"shift_id": None, "occurrence_start": "2026-11-02T09:00:00Z", "account_id": "c1"},
        {"shift_id": None, "occurrence_start": "2026-11-02T09:00:00Z", "account_id": "c2"},
        {"shift_id": 5, "occurrence_start": "2026-11-02T10:00:00Z", "account_id": "c1"},
    ], clashes
    assert list(hits) == [5]
    assert find_overlaps(mine, [1], ["c1"], {}) == ([], {})


def case_find_overlaps_repeat():
    # Every Monday 09-17 from 2 Nov; the others are Mondays too.
    mine = _shift(None, datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 17), repeat_days="[1]")
    one_off = _shift(5, datetime(2026, 11, 16, 10), datetime(2026, 11, 16, 11))
    tuesday = _shift(6, datetime(2026, 11, 17, 10), datetime(2026, 11, 17, 11))
    weekly = _shift(7, datetime(2026, 11, 9, 12), datetime(2026, 11, 9, 13), repeat_days="[1]",
                    cancelled='["2026-11-09", "2026-11-16"]')
    clashes, hits = find_overlaps(mine, [1], ["c1"], {5: (one_off, {"c1"}), 6: (tuesday, {"c1"}),
                                                      7: (weekly, {"c1"})})
    assert clashes == [
        {"shift_id": 5, "occurrence_start": "2026-11-16T10:00:00Z", "account_id": "c1"},
        {"shift_id": 7, "occurrence_start": "2026-11-23T12:00:00Z", "account_id": "c1"},
    ], clashes
    starts = hits[7][1]
    assert starts[0] == datetime(2026, 11, 23, 12) and all(s.isoweekday() == 1 for s in starts)
    # 53 Mondays from 9 Nov inside OVERLAP_HORIZON, less the 9 and 16 Nov cancelled.
    assert datetime(2026, 11, 16, 12) not in starts and len(starts) == 51, len(starts)


def _emp(eid, active=True) -> Employee:
    return Employee(id=eid, is_active=active)


def case_clock_gate_table():
    on = dict(enabled=True, clock_in_reminder=False, auto_clock_out_minutes=10)
    roles = {"assignments": {"5": "chatter", "6": 7}}
    chat = frozenset({"chatter"})
    table = [
        # (tt, roles, emp, owner) → reason
        (TimeTracking(**{**on, "enabled": False}, role_ids=chat), roles, _emp(5, False), False, "time_tracking_off"),
        (TimeTracking(**on, role_ids=None), roles, _emp(5), False, "role_not_enabled"),
        (TimeTracking(**on, role_ids=None), roles, _emp(1), True, "role_not_enabled"),
        (TimeTracking(**on, role_ids=chat), roles, _emp(1), True, "role_not_enabled"),       # owner not ticked
        (TimeTracking(**on, role_ids=chat), roles, _emp(9), False, "role_not_enabled"),      # no role
        (TimeTracking(**on, role_ids=chat), roles, _emp(6), False, "role_not_enabled"),      # role not a str
        (TimeTracking(**on, role_ids=chat), {}, _emp(5), False, "role_not_enabled"),         # no assignments
        (TimeTracking(**on, role_ids=chat), roles, None, False, "role_not_enabled"),         # no row yet
        (TimeTracking(**on, role_ids=chat), roles, _emp(5, False), False, "inactive"),
        (TimeTracking(**on, role_ids=frozenset({"owner"})), {}, _emp(1, False), True, "inactive"),
        (TimeTracking(**on, role_ids=chat), roles, _emp(5), False, None),
        (TimeTracking(**on, role_ids=frozenset({"owner"})), {}, _emp(1), True, None),
        (TimeTracking(**on, role_ids=frozenset({"owner"})), {}, None, True, None),
    ]
    seen = set()
    for tt, blob, emp, owner, want in table:
        got = clock_gate(tt, blob, emp, owner)
        assert got == want, (tt, emp and emp.id, owner, got)
        seen.add(got)
    assert seen - {None} == set(_REFUSALS), seen


def case_due_clock_outs_table():
    t = datetime(2026, 11, 2, 9)
    ten = {"a": timedelta(minutes=10), "b": timedelta(minutes=30)}
    plain = _event(1, 10, "c1", t)
    seen = _event(2, 11, "c1", t, last_seen=t + timedelta(minutes=5))
    busy = _event(3, 12, None, t)
    orphan = _event(4, None, "c1", t, agency="b")
    latest = {12: t + timedelta(minutes=8)}   # the audit read: Employees with rows only
    events = [plain, seen, busy, orphan]
    table = [
        (t + timedelta(minutes=10) - timedelta(microseconds=1), []),
        (t + timedelta(minutes=10), [(plain, t + timedelta(minutes=10))]),
        (t + timedelta(minutes=15), [(plain, t + timedelta(minutes=10)), (seen, t + timedelta(minutes=15))]),
        (t + timedelta(minutes=30), [(plain, t + timedelta(minutes=10)), (seen, t + timedelta(minutes=15)),
                                     (busy, t + timedelta(minutes=18)), (orphan, t + timedelta(minutes=30))]),
    ]
    for now, want in table:
        got = due_clock_outs(events, now, ten, latest)
        assert got == want, (now, [(ev.id, d) for ev, d in got])
    assert due_clock_outs([], t + timedelta(days=1), ten, latest) == []


def case_needs_roles_table():
    on = dict(enabled=True, clock_in_reminder=False, auto_clock_out_minutes=10)
    table = [
        # (enabled, role_ids, owner) → reads the roles blob
        (True, frozenset({"chatter"}), False, True),
        (True, frozenset(), False, True),
        (False, frozenset({"chatter"}), False, False),
        (True, None, False, False),
        (True, frozenset({"owner"}), True, False),
    ]
    for enabled, role_ids, owner, want in table:
        tt = TimeTracking(**{**on, "enabled": enabled}, role_ids=role_ids)
        assert needs_roles(tt, owner) is want, (enabled, role_ids, owner)


def case_time_tracking_of():
    assert DEFAULT_AUTO_CLOCK_OUT_MINUTES == 10
    assert time_tracking_of({}) == TimeTracking(False, False, 10, None)
    assert time_tracking_of({"enabled": "true", "clock_in_reminder": 1}) == TimeTracking(False, False, 10, None)
    assert time_tracking_of({"enabled": True, "clock_in_reminder": True, "auto_clock_out_minutes": 25,
                             "role_ids": ["chatter", "owner"]}) == \
        TimeTracking(True, True, 25, frozenset({"chatter", "owner"}))


_harness.run()
