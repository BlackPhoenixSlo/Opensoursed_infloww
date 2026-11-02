"""The Shift schedule's and the Clock's break-it-once faults (scenarios/2026-11-01-shifts-clock-crowd.py):
lib/faults.py merges `register(Fault)` into FAULTS. The check names live here and the scenario imports
them, so a target can never name a check that does not exist. Each patches, inside the relay, the
product attribute whose bug class it claims; the load never reads which one is on.
"""
from __future__ import annotations

RACE = ("shifts: N concurrent POST /admin/shifts on one Creator and slot: exactly one 2xx, the rest 409, "
        "and one Shift row holds the slot")
ONE_OPEN = ("clock: after the clock-in storm every chatter holds exactly one open clock event "
            "(one 2xx clock-in each, the rest 409)")
ORACLE_EMP = ("timesheet group=employee over the DST window == the zoneinfo oracle (scheduled and worked minutes, "
              "scheduled and worked shifts, open_now)")
ORACLE_ACC = ("timesheet group=account over the DST window == the zoneinfo oracle (scheduled and worked minutes, "
              "scheduled and worked shifts, open_now)")
LIST_ORACLE = ("week list: GET /admin/shifts over the DST window == the oracle's occurrences (id, start, end), "
               "the Berlin fall-back night's 5 h long")
OWNER_WRITES = ("owner writes: every PATCH (all, this, following) and cancel (this, following) answers 2xx and "
                "the week list shows it")
AUDIT = ("one actions row (shift.create|edit|cancel, clock.in|out) per 2xx write, none for a refused one, "
         "no auto clock-out")
UI_SHIFTS = "UI: /employees/shifts settles naming an Employee GET /admin/shifts lists for this week"
UI_REPORTS = ("UI: /analytics/employee-reports' Clocked hours card settles naming an Employee the 30-day "
              "GET /admin/shifts/timesheet?group=employee lists")


def _overlap_check_skipped() -> None:
    """shifts_api._check_overlaps answers "no clash" whatever is stored, as a write path that forgot the
    check (or ran it outside the write's transaction against a stale read): every create on a held slot
    lands. create_shift and edit_shift look it up per call."""
    import shifts_api

    async def none(*_a, **_k):
        return None

    shifts_api._check_overlaps = none


def _timesheet_drops_open_shift() -> None:
    """shifts_api.timesheet_rows (the Timesheet's tally, looked up per call) is handed only the closed
    Clock events: an Employee still clocked in counts no worked time and no open_now, per Employee and
    per Creator."""
    import shifts_api
    real = shifts_api.timesheet_rows

    def closed_only(shifts, assigned, clock_events, on_creator, sales, **kw):
        return real(shifts, assigned, [ev for ev in clock_events if ev.out_utc is not None],
                    [x for x in on_creator if x[0].out_utc is not None], sales, **kw)

    shifts_api.timesheet_rows = closed_only


def _clock_in_twice_opens_two() -> None:
    """The schema without its partial unique index `uq_clock_events_open_employee` (a box whose DB
    predates it, the case employees.py's Mirror-row docstring records for its own index): clock-in's
    read-then-insert pre-check is the only guard, so concurrent clock-ins of one chatter open two
    events. Taken off `db.models.ClockEvent.__table__` before init_db's create_all (the fault applies
    before the relay's startup)."""
    from db.models import ClockEvent
    table = ClockEvent.__table__
    for ix in [ix for ix in table.indexes if ix.name == "uq_clock_events_open_employee"]:
        table.indexes.discard(ix)


def register(Fault) -> dict:
    return {
        # slop/run shifts-clock-crowd --break (the scenario's FAULT)
        "shift-overlap-check-skipped": Fault(_overlap_check_skipped, (RACE,)),
        # slop/run shifts-clock-crowd --break --fault=timesheet-drops-open-shift --baseline=slop/evidence/<run>
        "timesheet-drops-open-shift": Fault(_timesheet_drops_open_shift, (ORACLE_EMP, ORACLE_ACC)),
        # slop/run shifts-clock-crowd --break --fault=clock-in-twice-opens-two --baseline=slop/evidence/<run>
        "clock-in-twice-opens-two": Fault(_clock_in_twice_opens_two, (ONE_OPEN,)),
    }
