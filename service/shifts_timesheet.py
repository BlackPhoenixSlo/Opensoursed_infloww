"""service/shifts_timesheet.py — the Timesheet's tally, with no DB.

`GET /admin/shifts/timesheet` (service/shifts_api.py `timesheet`, whose
docstring holds the rules and their ASSUMPTIONs) loads the Agency's live
Shifts, their assignments, its Clock events, their time per Creator
(`shift_time.creator_spans`) and their sales (`sales_attribution.event_sales`),
then calls `timesheet_rows` here and names the rows it returns.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from db.models import ClockEvent, Shift
from shift_time import shift_occurrences

if TYPE_CHECKING:
    from sales_attribution import CreditedSale


def _overlap_s(a: datetime, b: datetime, lo: datetime, hi: datetime) -> float:
    """Seconds of [a, b) inside [lo, hi)."""
    return max(0.0, (min(b, hi) - max(a, lo)).total_seconds())


def timesheet_rows(
    shifts: list[Shift], assigned: dict[int, set[tuple[int, str]]], clock_events: list[ClockEvent],
    on_creator: list[tuple[ClockEvent, str, datetime, datetime]], sales: dict[int, list[CreditedSale]],
    *, lo: datetime, hi: datetime, now: datetime, by_employee: bool,
) -> dict[int | str, dict[str, Any]]:
    """Per key (an Employee id with `by_employee`, else a Creator id), in
    first-seen order, the tally `{scheduled_shifts, shifts_worked,
    scheduled_s, worked_s, recorded_earnings_cents, open_now}` over [lo, hi).

    `assigned` is, by Shift id, its (Employee, Creator) pairs; `on_creator`
    the events' time per Creator (`creator_spans`); `sales`, by event id,
    their credited shares (`event_sales`: `employee_id`, `account_id`,
    `occurred_at`, `amount_cents`). An open event runs to `now`.
    """
    # Recorded earnings: each event's sales inside the range.
    stop = min(hi, now)
    earnings: dict[int | str, int] = {}
    for shares in sales.values():
        for c in shares:
            if lo <= c.occurred_at < stop:
                key = c.employee_id if by_employee else c.account_id
                earnings[key] = earnings.get(key, 0) + c.amount_cents

    rows: dict[int | str, dict[str, Any]] = {}

    def _row(key: int | str) -> dict[str, Any]:
        return rows.setdefault(key, {"scheduled_shifts": 0, "shifts_worked": 0, "scheduled_s": 0.0,
                                     "worked_s": 0.0, "recorded_earnings_cents": 0, "open_now": False})

    for sh in shifts:
        for o_start, o_end in shift_occurrences(sh, lo, hi):
            during = {(ev.employee_id, acc) for ev, acc, s_lo, s_hi in on_creator if s_lo < o_end and s_hi > o_start}
            for key in {emp if by_employee else acc for emp, acc in assigned[sh.id]}:
                tally = _row(key)
                tally["scheduled_shifts"] += 1
                tally["scheduled_s"] += _overlap_s(o_start, o_end, lo, hi)
                if any((emp if by_employee else acc) == key and (emp, acc) in during
                       for emp, acc in assigned[sh.id]):
                    tally["shifts_worked"] += 1

    # Worked time as (key, lo, hi, open) spans: per Employee each whole
    # event, per Creator the event's time on that Creator.
    spans = ([(ev.employee_id, ev.in_utc, ev.out_utc or now, ev.out_utc is None) for ev in clock_events]
             if by_employee else [(acc, s_lo, s_hi, ev.out_utc is None) for ev, acc, s_lo, s_hi in on_creator])
    for key, s_lo, s_hi, is_open in spans:
        worked_s = _overlap_s(s_lo, s_hi, lo, hi)
        if key is None or worked_s <= 0:
            continue
        tally = _row(key)
        tally["worked_s"] += worked_s
        tally["open_now"] = tally["open_now"] or is_open
    for key, cents in earnings.items():
        _row(key)["recorded_earnings_cents"] = int(cents)
    return rows
