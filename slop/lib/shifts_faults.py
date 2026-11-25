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
CANCEL_DATES = ("shift cancels: N concurrent POST /admin/shifts/{id}/cancel scope=this on distinct dates of one "
                "series each answer 2xx, every date is in the series' cancelled_dates and the week list drops it")
UI_SHIFTS = "UI: /employees/shifts settles naming an Employee GET /admin/shifts lists for this week"
UI_REPORTS = ("UI: /analytics/employee-reports' Clocked hours card settles naming an Employee the 30-day "
              "GET /admin/shifts/timesheet?group=employee lists")


def _overlap_check_skipped() -> None:
    import shifts_api

    async def none(*_a, **_k):
        return None

    shifts_api._check_overlaps = none


def _timesheet_drops_open_shift() -> None:
    import shifts_api
    real = shifts_api.timesheet_rows

    def closed_only(shifts, assigned, clock_events, on_creator, sales, **kw):
        return real(shifts, assigned, [ev for ev in clock_events if ev.out_utc is not None],
                    [x for x in on_creator if x[0].out_utc is not None], sales, **kw)

    shifts_api.timesheet_rows = closed_only


def _clock_in_twice_opens_two() -> None:
    from db.models import ClockEvent
    table = ClockEvent.__table__
    for ix in [ix for ix in table.indexes if ix.name == "uq_clock_events_open_employee"]:
        table.indexes.discard(ix)


def _shift_cancel_unlocked() -> None:
    import shifts_api
    from db.engine import get_session

    shifts_api._cancel_txn = get_session


def register(Fault) -> dict:
    return {
        "shift-overlap-check-skipped": Fault(_overlap_check_skipped, (RACE,)),
        "timesheet-drops-open-shift": Fault(_timesheet_drops_open_shift, (ORACLE_EMP, ORACLE_ACC)),
        "clock-in-twice-opens-two": Fault(_clock_in_twice_opens_two, (ONE_OPEN,)),
        "shift-cancel-unlocked": Fault(_shift_cancel_unlocked, (CANCEL_DATES,)),
    }
