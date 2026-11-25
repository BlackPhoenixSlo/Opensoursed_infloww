from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select

from db.models import ClockEvent, Shift, ShiftAssignment

# An occurrence lasts at most a day (plus a DST hour).
OCCURRENCE_REACH = timedelta(days=2)


def repeat_days(raw: str | None) -> list[int] | None:
    return json.loads(raw) if raw else None


def cancelled_dates(raw: str | None) -> list[date]:
    return sorted(date.fromisoformat(d) for d in json.loads(raw)) if raw else []


def _to_utc(wall: datetime, zone: ZoneInfo) -> datetime:
    return wall.replace(tzinfo=zone, fold=0).astimezone(timezone.utc).replace(tzinfo=None)


def shift_occurrences(sh: Shift, lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    if not sh.repeat_days:
        return [(sh.start_utc, sh.end_utc)] if sh.start_utc < hi and sh.end_utc > lo else []
    zone = ZoneInfo(sh.tz)
    wall_start = sh.start_utc.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
    wall_end = sh.end_utc.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
    length = wall_end - wall_start
    weekdays = set(repeat_days(sh.repeat_days)) | {wall_start.isoweekday()}
    skipped = set(cancelled_dates(sh.cancelled_dates))
    first = wall_start.date()
    day = max(first, lo.replace(tzinfo=timezone.utc).astimezone(zone).date() - timedelta(days=2))
    last = hi.replace(tzinfo=timezone.utc).astimezone(zone).date()
    if sh.repeat_until is not None:
        last = min(last, sh.repeat_until)
    out: list[tuple[datetime, datetime]] = []
    while day <= last:
        if day in skipped:
            occ = None
        elif day == first:
            occ = (sh.start_utc, sh.end_utc)
        elif day.isoweekday() in weekdays:
            wall = datetime.combine(day, wall_start.time())
            occ = (_to_utc(wall, zone), _to_utc(wall + length, zone))
        else:
            occ = None
        if occ is not None and occ[0] < hi and occ[1] > lo:
            out.append(occ)
        day += timedelta(days=1)
    return out


def live_shifts(agency_user_id: str, start: datetime, end: datetime):
    return select(Shift).where(
        Shift.agency_user_id == agency_user_id,
        Shift.status == "scheduled",
        Shift.start_utc < end,
        or_(
            and_(Shift.repeat_days.is_(None), Shift.end_utc > start),
            and_(Shift.repeat_days.is_not(None),
                 or_(Shift.repeat_until.is_(None),
                     Shift.repeat_until >= (start - OCCURRENCE_REACH).date())),
        ),
    )


def _merged(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def minutes_up(seconds: float) -> int:
    return math.ceil(round(seconds, 3) / 60)


async def creator_spans(
    s, events: list[ClockEvent], now: datetime,
) -> list[tuple[ClockEvent, str, datetime, datetime]]:
    out = [(ev, ev.account_id, ev.in_utc, ev.out_utc or now) for ev in events if ev.account_id is not None]
    wide = [ev for ev in events if ev.account_id is None and ev.employee_id is not None]
    held: dict[tuple[str, int], list[tuple[Shift, str]]] = defaultdict(list)
    for agency in {ev.agency_user_id for ev in wide}:
        mine = [ev for ev in wide if ev.agency_user_id == agency]
        rows = (await s.execute(
            live_shifts(agency, min(ev.in_utc for ev in mine), max(ev.out_utc or now for ev in mine))
            .add_columns(ShiftAssignment.employee_id, ShiftAssignment.account_id)
            .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
            .where(ShiftAssignment.employee_id.in_({ev.employee_id for ev in mine}))
        )).all()
        for sh, emp, acc in rows:
            held[(agency, emp)].append((sh, acc))
    for ev in wide:
        stop = ev.out_utc or now
        spans: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        for sh, acc in held[(ev.agency_user_id, ev.employee_id)]:
            spans[acc] += [(max(o_start, ev.in_utc), min(o_end, stop))
                           for o_start, o_end in shift_occurrences(sh, ev.in_utc, stop)]
        out += [(ev, acc, lo, hi) for acc, pieces in spans.items() for lo, hi in _merged(pieces) if lo < hi]
    return out
