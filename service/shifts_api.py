"""service/shifts_api.py — the Shift schedule, one Agency at a time.

  GET  /admin/shifts?from&to&employee_id?&account_id?
       → {occurrences: [{shift_id, occurrence_start, occurrence_end,
          start_utc, end_utc, tz, repeat_days, repeat_until,
          employees[{id, display_name}], accounts[{id, display_name}]}]}
       The Agency's non-cancelled Shift occurrences that intersect
       [from, to), at most 42 days, in start order.
  POST /admin/shifts  {start_utc, end_utc, tz, repeat_days?, repeat_until?,
                       employee_ids[≥1], account_ids[≥1], replace?, grant_access?}
       → the created Shift. A Mirror Employee whose chatter is linked to the
         Agency but not allowed a Creator is 422 `{detail, grantable[{
         employee_id, employee_name, account_id, account_name}]}`; resent
         with `grant_access: true`, those Creators are added to the chatter's
         allowlist in the Shift's own transaction (the app asks first). This
         422 comes before the overlap check, so a `replace` never lands on a
         write that is then refused.
  PATCH /admin/shifts/{id}  (the same body, plus scope?, occurrence_start?)
       → the Shift as edited: `scope` "all" (the default) replaces the whole
       series; "this" and "following" edit from the occurrence starting at
       `occurrence_start` (`edit_shift`). The same grantable 422 applies.
  POST /admin/shifts/{id}/cancel  ({scope?, occurrence_start?} or no body)
       → the Shift: "all" (the default) cancels it (its row stays); "this"
       removes one occurrence, "following" ends the series before it.
  GET  /admin/shifts/timesheet?from&to&group=employee|account
       → {rows: [{key, display_name, scheduled_shifts, shifts_worked,
          scheduled_minutes, worked_minutes, recorded_earnings_cents,
          open_now}]}: the Agency's Timesheet for [from, to) (`timesheet`).

The Clock endpoints under the same prefix (clock-in, clock-out, me,
clocked-in, clock-events) live in service/clock_api.py. server.py mounts
both routers with the lazy Auto clock-out sweep as a dependency.

docs/spec/phase-02-shifts-time-tracking.md (Interfaces, Agency scope). Every
handler starts from Phase 1's `agency_context`; check order is 401 (no
session, even with ALLOW_ANONYMOUS_ADMIN) → 403 (a chatter on an owner
endpoint) → 404 → 422 (invalid input, or a reference to another Agency's
Employee or Creator, or an Employee paired with a Creator its chatter login
cannot access) → 409 (a cancelled Shift). Times on the wire are ISO-8601 UTC
strings ending in Z; stored times are naive UTC.

Weekly repeats are expanded at read time in the Shift's own `tz` (the
Occurrence rule, service/shift_time.py, with the other time rules), never
stored. One occurrence is never a row either (roadmap W6 6.3): "This shift"
puts its local date in the series' `cancelled_dates`, and "This and
following" ends the series the day before (`repeat_until`) and, for an
edit, starts a new series from it. Every create, edit and cancel appends its own
`actions` row (`shift.create|edit|cancel`, actor `owner:<id>`, before/after)
beside the audit middleware's generic one.

The overlap rule: unless the Agency's `sales` Settings blob holds
`multi_employee_shift` as literal `true` ("Multiple employees per shift",
saved by the Sales Panel and by Shift Settings), a create or edit that puts
two Employees on one Creator, or that overlaps another live Shift on the same
Creator, is 409 `{detail, clashes[{shift_id, occurrence_start, account_id}]}`.
Checked on writes only. With `replace: true` (Infloww's "replace the shifts",
roadmap W6 6.12) the write goes ahead instead and takes every clashing
occurrence out of the other Shifts (`_replace`); the Shift's own
double-staffing is still 409.

The scheduling horizon: a create or edit may not put a Shift's start more
than SCHEDULE_HORIZON ahead (422), unless the start stays where it was
(`_check_horizon`).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import events
from chatters import _account_restrictions_for, _filter_owner_accounts
from db.engine import get_session
from db.models import (
    Account, Action, ChatterAccountAccess, ChatterUser, ClockEvent, Employee, EmployeeGroup, Shift, ShiftAssignment,
    UserAccount,
)
from employees import AgencyContext, json_object, owner_context
from sales_attribution import event_sales
from settings_api import applied_blob
from shift_time import (
    OCCURRENCE_REACH, cancelled_dates, creator_spans, live_shifts, minutes_up, repeat_days, shift_occurrences,
)


router = APIRouter(prefix="/admin/shifts", tags=["shifts"])

MAX_RANGE = timedelta(days=42)
MAX_SHIFT = timedelta(hours=24)
# Overlaps are looked for this far after the later of two series' starts:
# both rules repeat weekly, and 53 weeks spans a whole DST cycle.
OVERLAP_HORIZON = timedelta(weeks=53)
# How far ahead a Shift may be scheduled (Infloww's shifts_scheduled_months).
# ASSUMPTION: a year (366 days), counted from now to the Shift's start; a weekly
# series is expanded at read time, so its later occurrences, "Never" and
# `repeat_until` are not capped. Rung 5: Infloww's own figure is not in the
# Inventory. Overturned by Infloww's value or an owner's.
SCHEDULE_HORIZON = timedelta(days=366)

_OWNER_ONLY = "only the agency owner manages the Shift schedule"


async def _owner_context(account_id: str | None = None) -> AgencyContext:
    return await owner_context(account_id, _OWNER_ONLY)


def _parse_utc(value: Any, field: str) -> datetime:
    """An ISO-8601 time with a zone (Z or an offset) → naive UTC.

    ASSUMPTION: any explicit offset is accepted and converted, not only a
    literal Z; a time with no zone is 422. Rung 4: stricter later is a
    narrowing the app never trips (it always sends toISOString()).
    Overturned if the owner wants non-Z input refused.
    """
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=422, detail=f"{field}: an ISO-8601 UTC time is required")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field}: not an ISO-8601 time") from None
    if dt.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{field}: the time needs a zone (end it with Z)")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _wire(dt: datetime) -> str:
    return dt.isoformat() + "Z"


async def _agency_account_ids(s, agency_user_id: str) -> set[str]:
    rows = (await s.execute(
        select(UserAccount.account_id).where(UserAccount.user_id == agency_user_id)
    )).scalars().all()
    return set(rows)


async def _agency_employee_ids(s, agency_user_id: str, ids: list[int]) -> set[int]:
    rows = (await s.execute(
        select(Employee.id).where(Employee.id.in_(ids), Employee.user_id == agency_user_id)
    )).scalars().all()
    return set(rows)


async def _shift_people(s, shift_ids: list[int]) -> dict[int, tuple[list[dict], list[dict]]]:
    """Per Shift: its Employees and its Creators, each sorted by id."""
    out: dict[int, tuple[dict[int, dict], dict[str, dict]]] = {sid: ({}, {}) for sid in shift_ids}
    if not shift_ids:
        return {}
    rows = (await s.execute(
        select(ShiftAssignment.shift_id, Employee.id, Employee.display_name,
               Account.id, Account.nickname)
        .join(Employee, Employee.id == ShiftAssignment.employee_id)
        .join(Account, Account.id == ShiftAssignment.account_id)
        .where(ShiftAssignment.shift_id.in_(shift_ids))
    )).all()
    for sid, emp_id, emp_name, acc_id, nickname in rows:
        emps, accs = out[sid]
        emps[emp_id] = {"id": emp_id, "display_name": emp_name}
        accs[acc_id] = {"id": acc_id, "display_name": nickname or acc_id}
    return {
        sid: ([emps[k] for k in sorted(emps)], [accs[k] for k in sorted(accs)])
        for sid, (emps, accs) in out.items()
    }


def _parse_range(from_: str | None, to: str | None) -> tuple[datetime, datetime]:
    """`from` and `to` → naive UTC, 422 unless from < to within 42 days."""
    start = _parse_utc(from_, "from")
    end = _parse_utc(to, "to")
    if end <= start:
        raise HTTPException(status_code=422, detail="to must be after from")
    if end - start > MAX_RANGE:
        raise HTTPException(status_code=422, detail="the range is at most 42 days")
    return start, end


@router.get("")
async def list_occurrences(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    employee_id: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    # Every parameter is parsed in the handler, after the session checks, so
    # a signed-out or chatter call is 401/403 whatever its query says.
    # ASSUMPTION: the list comes wrapped as `{occurrences: [...]}`. Rung 3,
    # the `{employees: [...]}` envelope of GET /admin/employees. Overturned
    # if the shared `ShiftOccurrence` contract wants a bare array.
    # `?account_id` naming a Creator the session does not hold is 403, not the
    # ticket's 404/422: `_account_isolation_middleware` answers "not your
    # account" before this handler runs (service/server.py:390-404), and
    # `agency_context` would again via `assert_account_owned`
    # (service/employees.py:798). Rung 1, observed. One the session holds
    # outside this Agency (the Master) is 422 below.
    ctx = await _owner_context(account_id)
    start, end = _parse_range(from_, to)
    emp_filter: int | None = None
    if employee_id:
        try:
            emp_filter = int(employee_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="employee_id must be an integer") from None

    async with get_session() as s:
        if emp_filter is not None and not await _agency_employee_ids(s, ctx.agency_user_id, [emp_filter]):
            raise HTTPException(status_code=422, detail=f"employee {emp_filter} is not in this agency")
        if account_id and account_id not in await _agency_account_ids(s, ctx.agency_user_id):
            raise HTTPException(status_code=422, detail=f"creator {account_id} is not in this agency")

        q = live_shifts(ctx.agency_user_id, start, end)
        if emp_filter is not None:
            q = q.where(Shift.id.in_(
                select(ShiftAssignment.shift_id).where(ShiftAssignment.employee_id == emp_filter)))
        if account_id:
            q = q.where(Shift.id.in_(
                select(ShiftAssignment.shift_id).where(ShiftAssignment.account_id == account_id)))
        shifts = (await s.execute(q)).scalars().all()
        occurrences = sorted(
            ((occ_start, occ_end, sh)
             for sh in shifts for occ_start, occ_end in shift_occurrences(sh, start, end)),
            key=lambda o: (o[0], o[2].id),
        )
        people = await _shift_people(s, sorted({sh.id for _, _, sh in occurrences}))

    # ASSUMPTION: each occurrence also carries its series' `start_utc` and
    # `end_utc` (the first occurrence), so the edit window opened from any
    # week prefills the series and not the clicked occurrence. Rung 4: an
    # additive field on the spec's `ShiftOccurrence`. Overturned if editing
    # from a later week should move the series' start to that occurrence.
    return {"occurrences": [
        {
            **_shift_json(sh, *people.get(sh.id, ([], []))),
            "occurrence_start": _wire(occ_start),
            "occurrence_end": _wire(occ_end),
        }
        for occ_start, occ_end, sh in occurrences
    ]}


def _id_list(value: Any, field: str, kind: type) -> list:
    if not isinstance(value, list) or not value:
        raise HTTPException(status_code=422, detail=f"{field}: at least one is required")
    if kind is int:
        ok = all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    else:
        ok = all(isinstance(v, str) and v for v in value)
    if not ok:
        raise HTTPException(status_code=422, detail=f"{field}: a list of {kind.__name__} ids")
    return list(dict.fromkeys(value))


def _parse_repeat(body: dict, tz: str, start: datetime) -> tuple[list[int] | None, date | None]:
    """`repeat_days` (ISO weekdays 1..7, at least one, or null) and
    `repeat_until` (a local date in `tz`, inclusive, or null = "Never").

    ASSUMPTION: an empty `repeat_days` list is 422 rather than "no repeat",
    and `repeat_until` without `repeat_days`, or before the start's local
    date, is 422. Rung 4: refusals store nothing and loosening is additive.
    Overturned if the app needs to send [] for "no repeat".
    """
    days = body.get("repeat_days")
    until = body.get("repeat_until")
    if days is None:
        if until is not None:
            raise HTTPException(status_code=422, detail="repeat_until needs repeat_days")
        return None, None
    if (not isinstance(days, list) or not days
            or not all(isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 7 for d in days)):
        raise HTTPException(status_code=422,
                            detail="repeat_days: a list of ISO weekdays 1 (Monday) to 7 (Sunday)")
    if until is None:
        return sorted(set(days)), None
    try:
        if not isinstance(until, str):
            raise ValueError
        until_date = date.fromisoformat(until)
    except ValueError:
        raise HTTPException(status_code=422, detail="repeat_until: a date YYYY-MM-DD or null") from None
    first = start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).date()
    if until_date < first:
        raise HTTPException(status_code=422, detail="repeat_until is before the Shift's first date")
    return sorted(set(days)), until_date


async def _json_object(request: Request) -> dict[str, Any]:
    return await json_object(request, 422)


def _parse_replace(body: dict[str, Any]) -> bool:
    replace = body.get("replace", False)
    if not isinstance(replace, bool):
        raise HTTPException(status_code=422, detail="replace: true or false")
    return replace


def _check_horizon(start: datetime, prior: datetime | None) -> None:
    """422 when a write moves a Shift's start (from `prior`, the start it
    edits, None on a create) past SCHEDULE_HORIZON from now, so an
    occurrence already scheduled beyond it can still be edited in place."""
    if start != prior and start > datetime.utcnow() + SCHEDULE_HORIZON:
        raise HTTPException(status_code=422,
                            detail=f"a Shift can be scheduled at most {SCHEDULE_HORIZON.days} days ahead")


def _shift_fields(body: dict[str, Any]) -> dict[str, Any]:
    """The create and edit body, validated (422s only; references are
    checked against the Agency separately)."""
    start = _parse_utc(body.get("start_utc"), "start_utc")
    end = _parse_utc(body.get("end_utc"), "end_utc")
    if end <= start:
        raise HTTPException(status_code=422, detail="end_utc must be after start_utc")
    if end - start > MAX_SHIFT:
        raise HTTPException(status_code=422, detail="a Shift is at most 24 hours long")
    tz = body.get("tz")
    try:
        if not isinstance(tz, str) or not tz:
            raise ValueError
        ZoneInfo(tz)
    except (ValueError, ZoneInfoNotFoundError):
        raise HTTPException(status_code=422, detail=f"unknown time zone {tz!r}") from None
    days, repeat_until = _parse_repeat(body, tz, start)
    return {
        "start": start, "end": end, "tz": tz,
        "repeat_days": days, "repeat_until": repeat_until,
        "employee_ids": _id_list(body.get("employee_ids"), "employee_ids", int),
        "account_ids": _id_list(body.get("account_ids"), "account_ids", str),
        "cancelled_dates": [],
        "grant_access": body.get("grant_access") is True,
    }


Scope = Literal["all", "this", "following"]


def _parse_scope(body: dict[str, Any]) -> tuple[Scope, datetime | None]:
    """`scope` ("all" when left out) and, for "this" and "following", the
    `occurrence_start` it starts from (the week list's `occurrence_start`)."""
    scope = body.get("scope", "all")
    if scope not in ("all", "this", "following"):
        raise HTTPException(status_code=422, detail="scope: all, this or following")
    if scope == "all":
        return "all", None
    return scope, _parse_utc(body.get("occurrence_start"), "occurrence_start")


def _local_date(dt: datetime, tz: str) -> date:
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).date()


def _occurrence_date(sh: Shift, at: datetime) -> date:
    """The local date, in the Shift's `tz`, of its occurrence that starts at
    `at`; 422 when no occurrence of it does."""
    if not any(o_start == at for o_start, _ in shift_occurrences(sh, at, at + timedelta(microseconds=1))):
        raise HTTPException(status_code=422, detail="occurrence_start is not an occurrence of this Shift")
    return _local_date(at, sh.tz)


def _whole(sh: Shift, scope: Scope, at: datetime) -> bool:
    """Whether a `scope` write from the occurrence starting at `at` covers the
    whole series: "all", any scope on a Shift that does not repeat, and
    "following" from its first occurrence still in the series (none before
    `at`, the stored first date may be cancelled)."""
    return (scope == "all" or not sh.repeat_days
            or (scope == "following" and not shift_occurrences(sh, sh.start_utc, at)))


def _cut(sh: Shift, scope: Scope, day: date) -> None:
    """Take the occurrence on `day` ("this") or every one from it
    ("following") out of the series `sh`, in place."""
    kept = cancelled_dates(sh.cancelled_dates)
    if scope == "this":
        kept.append(day)
    else:
        sh.repeat_until = day - timedelta(days=1)
        kept = [d for d in kept if d < day]
    sh.cancelled_dates = _dates_json(kept)


def _dates_json(days: list[date]) -> str | None:
    return json.dumps(sorted({d.isoformat() for d in days})) if days else None


async def _check_references(
    s, agency_user_id: str, employee_ids: list[int], account_ids: list[str],
) -> list[dict[str, Any]]:
    """422 unless every Employee and Creator is this Agency's and every
    (Employee, Creator) pair can be clocked or granted; returns the pairs that
    need a grant (empty when every pair can already be clocked).

    A Mirror Employee's chatter must be linked to the Agency and allowed the
    Creator by that owner's allowlist — the same rule that feeds the
    chatter's `account_ids` and `assert_account_owned`
    (service/chatters.py:192-229). An Employee with no chatter login may be
    put on any of the Agency's Creators. A linked chatter missing only the
    allowlist entry is grantable (the caller's `grant_access`); a chatter not
    linked to the Agency is refused outright, since a grant would not let it in.

    Only an owner session (or the Master) reaches the Shift writes
    (`owner_context`), and the same sessions alone may edit Creator access
    (`/admin/employees` is owner-only, chatters._CHATTER_BLOCKED_ADMIN_PREFIXES),
    so whoever may send `grant_access` may grant.

    ASSUMPTION: an inactive chatter's Mirror Employee is not refused here;
    only the link and the allowlist are checked, as the spec names them.
    Rung 5. Overturned if assigning a deactivated chatter should be 422 too.
    """
    own_emps = await _agency_employee_ids(s, agency_user_id, employee_ids)
    foreign_emps = [e for e in employee_ids if e not in own_emps]
    if foreign_emps:
        raise HTTPException(status_code=422, detail=f"employees not in this agency: {foreign_emps}")
    own_accounts = await _agency_account_ids(s, agency_user_id)
    foreign_accounts = [a for a in account_ids if a not in own_accounts]
    if foreign_accounts:
        raise HTTPException(status_code=422, detail=f"creators not in this agency: {foreign_accounts}")

    mirrors = (await s.execute(
        select(Employee.id, Employee.display_name, Employee.chatter_id)
        .where(Employee.id.in_(employee_ids), Employee.chatter_id.is_not(None),
               ~Employee.chatter_id.startswith("owner:"))
    )).all()
    if not mirrors:
        return []
    nicknames = dict((await s.execute(
        select(Account.id, Account.nickname).where(Account.id.in_(account_ids))
    )).all())
    refused: list[dict[str, Any]] = []
    for emp_id, emp_name, chatter_id in sorted(mirrors):
        linked = (await s.execute(
            select(ChatterUser.chatter_id).where(
                ChatterUser.chatter_id == chatter_id, ChatterUser.user_id == agency_user_id)
        )).first() is not None
        allowed = _filter_owner_accounts(
            [(agency_user_id, a) for a in account_ids],
            await _account_restrictions_for(s, chatter_id),
        ) if linked else set()
        refused += [{"employee_id": emp_id, "employee_name": emp_name, "chatter_id": chatter_id, "linked": linked,
                     "account_id": acc, "account_name": nicknames.get(acc) or acc}
                    for acc in account_ids if acc not in allowed]
    if any(not r["linked"] for r in refused):
        raise HTTPException(status_code=422, detail=_refusal_text(refused))
    return refused


def _refusal_text(refused: list[dict[str, Any]]) -> str:
    return "; ".join(f"{r['employee_name']} ({r['employee_id']}) cannot access creator "
                     f"{r['account_name']} ({r['account_id']})" for r in refused)


def _access_refusal(grantable: list[dict[str, Any]]) -> JSONResponse:
    """The 422 a `grant_access` resend clears: each pair named; the chatter id stays server-side."""
    return JSONResponse(status_code=422, content={
        "detail": _refusal_text(grantable),
        "grantable": [{k: g[k] for k in ("employee_id", "employee_name", "account_id", "account_name")}
                      for g in grantable],
    })


async def _grant(s, agency_user_id: str, grantable: list[dict[str, Any]]) -> None:
    """Add each pair's Creator to its chatter's allowlist, in the caller's transaction. A row
    already there (a concurrent grant) is left as is."""
    if not grantable:
        return
    now = datetime.utcnow()
    await s.execute(sqlite_insert(ChatterAccountAccess).values([
        {"chatter_id": g["chatter_id"], "user_id": agency_user_id, "account_id": g["account_id"], "created_at": now}
        for g in grantable
    ]).on_conflict_do_nothing())
    events.on_commit(s, "assignment_changed", agency=agency_user_id)


async def _check_overlaps(
    s, ctx: AgencyContext, fields: dict[str, Any], own_id: int | None, replaced: Shift | None = None,
    replace: bool = False,
) -> JSONResponse | None:
    """The 409 refusal, or None when the Agency allows multiple employees per
    shift or the Shift in `fields` double-staffs no Creator. Called before
    anything is written, so the caller just returns it. With `replace`, a
    clash with other Shifts only is not refused: those Shifts' clashing
    occurrences are taken out (`_replace`) and None is returned.

    The 409 body is `{detail, clashes}` at the top level.
    ASSUMPTION: the spec's `{detail, clashes}` is the whole body, not an
    object nested under FastAPI's `detail`, so `detail` stays the string
    every other refusal carries and the app's relay client reads it as is.
    Rung 5. Overturned if clients expect `detail.clashes`.

    Two ways to clash: the Shift itself puts more than one Employee on a
    Creator, or one of its occurrences overlaps a non-cancelled occurrence
    of another of the Agency's Shifts on the same Creator. Series are
    compared from the later start for OVERLAP_HORIZON. `own_id` is the Shift
    being edited, never compared with itself; `replaced`, an unsaved copy of
    the series a "this" or "following" edit cuts, is compared in place of
    its stored row.

    ASSUMPTION: the Shift's own double-staffing is reported once per Creator
    as `{shift_id: null, occurrence_start: <its first start>, account_id}`;
    null stands for "this Shift", also on an edit. Rung 5. Overturned if the
    app needs the edited Shift's own id there.

    ASSUMPTION: each other Shift is reported once per shared Creator, at its
    first occurrence that clashes, not once per clashing week, so a daily
    series does not produce a year of lines. Rung 5. Overturned if the owner
    wants every clashing occurrence listed.
    """
    agency_user_id = ctx.agency_user_id
    if (await applied_blob(s, agency_user_id, "sales")).get("multi_employee_shift") is True:
        return None
    candidate = Shift()
    _apply(candidate, fields)
    accounts = fields["account_ids"]
    clashes: list[dict[str, Any]] = []
    if len(fields["employee_ids"]) > 1:
        clashes += [{"shift_id": None, "occurrence_start": _wire(candidate.start_utc), "account_id": acc}
                    for acc in accounts]

    q = (select(Shift, ShiftAssignment.account_id)
         .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
         .where(Shift.agency_user_id == agency_user_id, Shift.status == "scheduled",
                ShiftAssignment.account_id.in_(accounts))
         .distinct())
    if own_id is not None:
        q = q.where(Shift.id != own_id)
    others: dict[int, tuple[Shift, set[str]]] = {}
    for other, acc in (await s.execute(q)).all():
        if replaced is not None and other.id == replaced.id:
            other = replaced
        others.setdefault(other.id, (other, set()))[1].add(acc)

    found: list[tuple[datetime, int, str]] = []
    hits: dict[int, tuple[Shift, list[datetime]]] = {}
    for other_id, (other, shared) in others.items():
        lo = max(candidate.start_utc, other.start_utc)
        hi = lo + OVERLAP_HORIZON
        mine = shift_occurrences(candidate, lo, hi)
        theirs = shift_occurrences(other, lo, hi)
        clashing = [o_start for o_start, o_end in theirs
                    if any(m_start < o_end and o_start < m_end for m_start, m_end in mine)]
        if clashing:
            found += [(clashing[0], other_id, acc) for acc in shared]
            hits[other_id] = (other, clashing)
    clashes += [{"shift_id": sid, "occurrence_start": _wire(start), "account_id": acc}
                for start, sid, acc in sorted(found)]
    if not clashes:
        return None
    if replace and all(c["shift_id"] is not None for c in clashes):
        await _replace(s, ctx, hits)
        return None

    nicknames = dict((await s.execute(
        select(Account.id, Account.nickname).where(Account.id.in_(accounts))
    )).all())
    named = [
        (f"more than one Employee on {nicknames.get(c['account_id']) or c['account_id']}"
         if c["shift_id"] is None else
         f"Shift {c['shift_id']} on {nicknames.get(c['account_id']) or c['account_id']}"
         f" at {c['occurrence_start']}")
        for c in clashes
    ]
    detail = "Multiple employees per shift is off; this Shift clashes: " + "; ".join(named)
    return JSONResponse(status_code=409, content={"detail": detail, "clashes": clashes})


async def _replace(s, ctx: AgencyContext, hits: dict[int, tuple[Shift, list[datetime]]]) -> None:
    """Take each clashing occurrence (`hits`: by Shift id, the Shift as
    compared and its clashing occurrence starts) out of its stored Shift: a
    weekly series puts their local dates in its `cancelled_dates`, a one-off
    Shift is cancelled. Each Shift changed gets its `shift.edit` or
    `shift.cancel` row.

    ASSUMPTION: an occurrence leaves whole, on every Creator and with every
    Employee it has, though it may clash on one shared Creator only: a Shift
    is one row for all of them. Rung 5. Overturned if replacing should only
    take the shared Creators off it.

    ASSUMPTION: a series loses its clashing occurrences within
    OVERLAP_HORIZON, the span the overlap check compares, so the replacing
    write passes that check; two endless series can clash again after it.
    Rung 5. Overturned if a replace must also end the other series."""
    now = datetime.utcnow()
    for shift_id, (compared, starts) in sorted(hits.items()):
        row = await s.get(Shift, shift_id)
        before = await _shift_out(s, row)
        if row.repeat_days:
            row.cancelled_dates = _dates_json(cancelled_dates(row.cancelled_dates)
                                              + [_local_date(at, compared.tz) for at in starts])
            action = "shift.edit"
        else:
            row.status = "cancelled"
            row.cancelled_at = now
            action = "shift.cancel"
        row.updated_at = now
        await s.flush()
        _audit(s, action, ctx, row, before, await _shift_out(s, row), [])


def _shift_json(sh: Shift, emps: list, accs: list) -> dict[str, Any]:
    """The series fields of a Shift, shared by the week list and `_shift_out`."""
    return {
        "shift_id": sh.id,
        "start_utc": _wire(sh.start_utc),
        "end_utc": _wire(sh.end_utc),
        "tz": sh.tz,
        "repeat_days": repeat_days(sh.repeat_days),
        "repeat_until": sh.repeat_until.isoformat() if sh.repeat_until else None,
        "employees": emps,
        "accounts": accs,
    }


async def _shift_out(s, sh: Shift) -> dict[str, Any]:
    """The Shift as the API returns it, and as its audit rows record it."""
    emps, accs = (await _shift_people(s, [sh.id])).get(sh.id, ([], []))
    return {**_shift_json(sh, emps, accs), "status": sh.status,
            "cancelled_dates": [d.isoformat() for d in cancelled_dates(sh.cancelled_dates)]}


def _audit(s, action: str, ctx: AgencyContext, sh: Shift,
           before: dict[str, Any] | None, after: dict[str, Any],
           granted: list[dict[str, Any]]) -> None:
    """One `actions` row for a Shift write, in the write's own transaction.

    ASSUMPTION: the row is added in the same session as the write (one
    commit for both), not through employees._write_action's separate
    session, so a Shift never changes without its audit row. Rung 3 for the
    row shape (employees.py:1060 `_write_action`); rung 5 for the
    transaction. Overturned if audit rows must survive a rolled-back write.
    """
    s.add(Action(
        employee_id=None,
        account_id=after["accounts"][0]["id"],
        action=action,
        target_type="shift",
        target_id=str(sh.id),
        payload_json=json.dumps({
            "actor": f"owner:{ctx.agency_user_id}", "before": before, "after": after,
            # Creator access the write granted (`grant_access`), so the allowlist change is on the Shift's row.
            **({"granted_access": [{"employee_id": g["employee_id"], "account_id": g["account_id"]}
                                   for g in granted]} if granted else {}),
        }),
        at=datetime.utcnow(),
    ))


def _apply(sh: Shift, fields: dict[str, Any]) -> None:
    sh.start_utc = fields["start"]
    sh.end_utc = fields["end"]
    sh.tz = fields["tz"]
    sh.repeat_days = json.dumps(fields["repeat_days"]) if fields["repeat_days"] else None
    sh.repeat_until = fields["repeat_until"]
    sh.cancelled_dates = _dates_json(fields["cancelled_dates"]) if fields["repeat_days"] else None


def _assign(s, shift_id: int, fields: dict[str, Any]) -> None:
    for emp in fields["employee_ids"]:
        for acc in fields["account_ids"]:
            s.add(ShiftAssignment(shift_id=shift_id, employee_id=emp, account_id=acc))


# The Agency-owned rows `_own_row` looks up by path id.
_Owned = TypeVar("_Owned", Shift, ClockEvent)


async def _own_row(s, ctx: AgencyContext, model: type[_Owned], raw_id: str, what: str) -> _Owned:
    """This Agency's `model` row (a Shift or a Clock event) by its path id,
    or 404 "<what> not found" (another Agency's, missing, or not an id)."""
    try:
        row_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found") from None
    row = await s.get(model, row_id)
    if row is None or row.agency_user_id != ctx.agency_user_id:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row


# response_model=None: FastAPI cannot build a response model from a return
# type that unions in JSONResponse (the overlap 409).
@router.post("", response_model=None)
async def create_shift(request: Request) -> dict[str, Any] | JSONResponse:
    ctx = await _owner_context()
    body = await _json_object(request)
    fields = _shift_fields(body)
    replace = _parse_replace(body)
    _check_horizon(fields["start"], None)
    async with get_session() as s:
        grantable = await _check_references(s, ctx.agency_user_id, fields["employee_ids"], fields["account_ids"])
        if grantable and not fields["grant_access"]:
            return _access_refusal(grantable)
        if refused := await _check_overlaps(s, ctx, fields, None, replace=replace):
            return refused
        await _grant(s, ctx.agency_user_id, grantable)
        return await _add_shift(s, ctx, fields, grantable)


async def _add_shift(s, ctx: AgencyContext, fields: dict[str, Any],
                     granted: list[dict[str, Any]]) -> dict[str, Any]:
    """A new Shift from `fields`, its assignments and its `shift.create` row
    (which records the Creator access the write `granted`)."""
    now = datetime.utcnow()
    shift = Shift(
        agency_user_id=ctx.agency_user_id, status="scheduled",
        created_by=f"owner:{ctx.agency_user_id}", created_at=now, updated_at=now,
    )
    _apply(shift, fields)
    s.add(shift)
    await s.flush()
    _assign(s, shift.id, fields)
    await s.flush()
    after = await _shift_out(s, shift)
    _audit(s, "shift.create", ctx, shift, None, after, granted)
    return after


def _copy(sh: Shift) -> Shift:
    """An unsaved copy of the series `sh`, for `_check_overlaps`' `replaced`."""
    return Shift(id=sh.id, agency_user_id=sh.agency_user_id, start_utc=sh.start_utc, end_utc=sh.end_utc,
                 tz=sh.tz, repeat_days=sh.repeat_days, repeat_until=sh.repeat_until,
                 cancelled_dates=sh.cancelled_dates, status=sh.status)


# The id is a string parsed in the handler: a typed `int` path parameter
# would let FastAPI answer 422 before the 401/403 session checks run.
@router.patch("/{shift_id}", response_model=None)
async def edit_shift(shift_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    """Edit the series: times, tz, repeat, Employees and Creators.

    `scope` "all" (or none) replaces the whole series, its `cancelled_dates`
    kept. With "this" or "following", the body is the occurrence that starts
    at `occurrence_start` as edited (Infloww's "Edit recurring shift": "Only
    this shift" / "This and all future shifts"):
      - "this": that date joins the series' `cancelled_dates`, and the body
        becomes a new one-off Shift (its repeat fields are ignored);
      - "following": the series ends the day before (`repeat_until`), and the
        body becomes a new series, which carries the series' cancelled dates
        from that day on.
    The answer is the new Shift. Either scope on a Shift that does not
    repeat, and "following" from the series' first occurrence left, is "all".

    ASSUMPTION: the body is the full create body (every field required, a
    missing repeat field means no repeat), not a partial patch. Rung 5: one
    validator for create and edit, and the Shifts window always sends the
    whole row. Overturned if a client needs to send only changed fields.

    ASSUMPTION: an edit that touches past occurrences is not refused; the
    app warns first ("Past shifts will also be modified", Infloww's
    past_shifts_modified). Rung 1 (Infloww warns and saves). Overturned if
    past occurrences must be locked.
    """
    ctx = await _owner_context()
    async with get_session() as s:
        shift = await _own_row(s, ctx, Shift, shift_id, "shift")
        body = await _json_object(request)
        fields = _shift_fields(body)
        scope, at = _parse_scope(body)
        replace = _parse_replace(body)
        _check_horizon(fields["start"], at or shift.start_utc)
        grantable = await _check_references(s, ctx.agency_user_id, fields["employee_ids"], fields["account_ids"])
        if shift.status == "cancelled":
            raise HTTPException(status_code=409, detail="a cancelled Shift cannot be edited")
        day = _occurrence_date(shift, at) if at else None
        if grantable and not fields["grant_access"]:
            return _access_refusal(grantable)
        before = await _shift_out(s, shift)

        if at is None or _whole(shift, scope, at):
            fields["cancelled_dates"] = cancelled_dates(shift.cancelled_dates)
            if refused := await _check_overlaps(s, ctx, fields, shift.id, replace=replace):
                return refused
            await _grant(s, ctx.agency_user_id, grantable)
            _apply(shift, fields)
            shift.updated_at = datetime.utcnow()
            await s.execute(delete(ShiftAssignment).where(ShiftAssignment.shift_id == shift.id))
            _assign(s, shift.id, fields)
            await s.flush()
            after = await _shift_out(s, shift)
            _audit(s, "shift.edit", ctx, shift, before, after, grantable)
            return after

        if scope == "this":
            fields["repeat_days"] = fields["repeat_until"] = None
        else:
            fields["cancelled_dates"] = [d for d in cancelled_dates(shift.cancelled_dates) if d >= day]
        cut = _copy(shift)
        _cut(cut, scope, day)
        if refused := await _check_overlaps(s, ctx, fields, None, replaced=cut, replace=replace):
            return refused
        await _grant(s, ctx.agency_user_id, grantable)
        # A replace may already have taken clashing dates out of this series
        # (its own `shift.edit` row), so the cut's row starts from there.
        before = await _shift_out(s, shift)
        _cut(shift, scope, day)
        shift.updated_at = datetime.utcnow()
        await s.flush()
        _audit(s, "shift.edit", ctx, shift, before, await _shift_out(s, shift), [])
        # The grant goes with the new Shift, whose assignments need it.
        return await _add_shift(s, ctx, fields, grantable)


@router.post("/{shift_id}/cancel")
async def cancel_shift(shift_id: str, request: Request) -> dict[str, Any]:
    """Cancel the series, or part of it (Infloww's "Delete recurring shift":
    This shift / This shift and following / All shifts):
      - "all" (or no body): a soft cancel, the Shift leaves every week view;
        its row and its assignments stay for the history;
      - "this": the occurrence starting at `occurrence_start` leaves it (its
        local date joins `cancelled_dates`);
      - "following": the series ends the day before that occurrence.
    Either scope on a Shift that does not repeat, and "following" from the
    series' first occurrence left, is "all". One `shift.cancel` row records it.

    ASSUMPTION: cancelling past occurrences is not refused; the app warns
    first ("All records of past shifts will be permanently deleted", Infloww's
    past_shifts_deleted_permanently): they leave the week list and the
    Timesheet, while their Clock events stay. Rung 1. Overturned if past
    occurrences must be kept.
    """
    ctx = await _owner_context()
    async with get_session() as s:
        shift = await _own_row(s, ctx, Shift, shift_id, "shift")
        scope, at = _parse_scope(await _json_object(request) if await request.body() else {})
        if shift.status == "cancelled":
            raise HTTPException(status_code=409, detail="the Shift is already cancelled")
        day = _occurrence_date(shift, at) if at else None
        before = await _shift_out(s, shift)
        now = datetime.utcnow()
        if at is None or _whole(shift, scope, at):
            shift.status = "cancelled"
            shift.cancelled_at = now
        else:
            _cut(shift, scope, day)
        shift.updated_at = now
        await s.flush()
        after = await _shift_out(s, shift)
        _audit(s, "shift.cancel", ctx, shift, before, after, [])
        return after


# ── The Timesheet (ticket 14) ───────────────────────────────────────


def _overlap_s(a: datetime, b: datetime, lo: datetime, hi: datetime) -> float:
    """Seconds of [a, b) inside [lo, hi)."""
    return max(0.0, (min(b, hi) - max(a, lo)).total_seconds())


@router.get("/timesheet")
async def timesheet(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    group: Literal["employee", "account"] = "employee",
) -> dict[str, Any]:
    """The Timesheet for [from, to): `{rows[{key, display_name,
    scheduled_shifts, shifts_worked, scheduled_minutes, worked_minutes,
    recorded_earnings_cents, open_now, employee_id, group_name}]}`, one row
    per Employee (`group=employee`, the default) or per Creator
    (`group=account`; there `employee_id` and `group_name` are null). Owner
    and Master sessions only (403 for a chatter); each reads its own Agency.

    - `scheduled_shifts` counts the non-cancelled occurrences assigned to the
      key that intersect the range; `scheduled_minutes` is their time clipped
      to it. An occurrence with two Employees on one Creator counts once for
      that Creator, and one with two Creators counts once for each Employee.
    - `shifts_worked` counts those occurrences overlapped by a Clock event of
      an Employee assigned to them, on a Creator assigned to that Employee
      there; an agency-wide event (w4-a) is on a Creator only inside the
      occurrences its Employee holds on it (`creator_spans`).
    - `worked_minutes` is the key's Clock events clipped to the range; an
      open event runs to now and sets `open_now`. Per Employee each event
      counts whole; per Creator an agency-wide event counts only its
      `creator_spans` time: Infloww has no per-Creator clock time either
      ("Clocked hours are not differentiated by platform").
    - `recorded_earnings_cents` sums the sales `sales_attribution.credited_sales`
      credits to an Employee on a Creator, by the Agency's Sales Settings
      rules and toggles as Employee reports credit them (phase-04 spec, story
      51), whose `occurred_at` falls inside that Employee's time on that
      Creator (`creator_spans`), clipped to the range: never payroll. The
      rule is `sales_attribution.event_sales`, which Shift records' sales share.

    ASSUMPTION (for Needs-the-human): Recorded earnings stay worked time
    only, Phase 2's definition, so they equal the Employee's per-employee
    figure only where every credited sale falls inside a Clock event of that
    Employee on that Creator. The two differ for any sale whose credited
    Employee was not clocked in on that Creator at the time of sale: under
    Converters, under Message sender, and for a sale reassigned by hand under
    any rule (a manual reassignment is credited before the rule is checked,
    sales_attribution.credited_sales). Such a sale counts in Employee
    reports and not here, which contradicts the literal phase-04 criterion "Recorded
    earnings equal that Employee's per-employee figure over the same
    interval and settings" (story 51). Rung 3 (Phase 2's Timesheet definition). Overturned if the owner
    wants the literal criterion: drop the worked-interval filter and count
    every credited share in the range.
    test_sales_attribution_rules' off-clock case pins it.

    ASSUMPTION: the rows come wrapped as `{rows: [...]}` and `key` is a string
    (the Employee id as text, or the Creator id). Rung 3 for the envelope
    (`GET /admin/employees` wraps `{employees: [...]}`), rung 5 for the key.
    Overturned if the shared `TimesheetRow` contract wants a bare array or a
    numeric Employee key.

    ASSUMPTION: `group` defaults to `employee` (the Shift history's default)
    and anything but `employee` or `account` is FastAPI's own 422; the range follows the
    week list's rules (from < to, at most 42 days, 422 otherwise). Rung 5.
    Overturned if Phase 5's Employee reports need longer ranges.

    ASSUMPTION: cancelled Shifts count nowhere, as they leave the week list.
    Rung 5. Overturned if the owner wants a cancelled Shift that was worked
    to stay in "Scheduled Shifts".

    ASSUMPTION: a Shift counts as worked when a Clock event overlaps its
    whole occurrence, not only the part inside the range, so an occurrence
    crossing a week edge reads the same in both weeks. Rung 5. Overturned if
    only clock time inside the viewed range may mark it worked.

    ASSUMPTION: `worked_minutes` is the key's total seconds rounded up to
    the whole minute, as Infloww's tooltip says ("Number of hours worked based
    on clocked time, rounded up to the nearest minute"; overturns Phase 2's
    rounding down); `scheduled_minutes` still rounds down. Rung 1 for worked
    time (the bundle's copy), rung 5 for keeping scheduled as it was.
    Overturned if Infloww's figure is found to round otherwise on screen.

    ASSUMPTION: per Creator, an agency-wide event's time inside an occurrence
    counts once for each Creator its Employee holds there, so an Employee
    holding two Creators in one Shift adds its time to both rows. Rung 5,
    the same rule as `shifts_worked` per Creator. Overturned if the owner
    wants that time split between the Creators.

    ASSUMPTION: only keys with an occurrence or clock time in the range get
    a row (no zero rows for an idle roster), and a Clock event whose Employee
    or Creator row is gone (SET NULL) counts only under the key it still has.
    Rung 5. Overturned if the history must list every Employee and Creator.

    ASSUMPTION: `open_now` is set by an open Clock event that is counted in
    the range (the spec's "An open event counts up to now and sets
    open_now"), so a past week shows no one as clocked in. Rung 5.
    Overturned if the indicator must show anyone clocked in now in any week.

    ASSUMPTION: Clock events are half-open [in, out), so a sale at the very
    moment of the clock-out is outside it. Rung 5. Overturned if the owner
    wants the clock-out instant included.

    ASSUMPTION: `occurred_at` compares with the range as SQLite text in
    `credited_sales` and with Clock event times as parsed datetimes here,
    because every writer of `transactions.occurred_at` stores
    a naive UTC datetime through the ORM `DateTime` column, so one text form
    (transaction_ingest.py:237 and :866, event_transcoder.py:93 and :715,
    fansly_revenue.py:166 and :366), and stats.py:1260-1261 filters the same
    view the same way. Rung 1 for the writers, rung 3 for the filter.
    Overturned by a writer that stores `occurred_at` as raw text (a `T` or a
    zone suffix), which must then be normalised with `func.datetime`.
    """
    ctx = await _owner_context()
    start, end = _parse_range(from_, to)
    by_employee = group == "employee"
    now = datetime.utcnow()

    async with get_session() as s:
        shifts = (await s.execute(live_shifts(ctx.agency_user_id, start, end))).scalars().all()
        assigned: dict[int, set[tuple[int, str]]] = {sh.id: set() for sh in shifts}
        if shifts:
            for sid, emp, acc in (await s.execute(
                select(ShiftAssignment.shift_id, ShiftAssignment.employee_id, ShiftAssignment.account_id)
                .where(ShiftAssignment.shift_id.in_(list(assigned)))
            )).all():
                assigned[sid].add((emp, acc))
        events = (await s.execute(select(ClockEvent).where(
            ClockEvent.agency_user_id == ctx.agency_user_id,
            ClockEvent.in_utc < end + OCCURRENCE_REACH,
            or_(ClockEvent.out_utc.is_(None), ClockEvent.out_utc > start - OCCURRENCE_REACH),
        ))).scalars().all()
        # Every event's time per Creator, an agency-wide one only inside the
        # occurrences its Employee holds (`creator_spans`).
        on_creator = await creator_spans(s, events, now)
        # Recorded earnings: each event's sales (sales_attribution.event_sales, the
        # one rule Shift records share) inside the range.
        stop = min(end, now)
        earnings: dict[int | str, int] = {}
        for shares in (await event_sales(s, events, now, on_creator)).values():
            for c in shares:
                if start <= c.occurred_at < stop:
                    key = c.employee_id if by_employee else c.account_id
                    earnings[key] = earnings.get(key, 0) + c.amount_cents

        rows: dict[int | str, dict[str, Any]] = {}

        def _row(key: int | str) -> dict[str, Any]:
            return rows.setdefault(key, {"scheduled_shifts": 0, "shifts_worked": 0, "scheduled_s": 0.0,
                                         "worked_s": 0.0, "recorded_earnings_cents": 0, "open_now": False})

        for sh in shifts:
            for o_start, o_end in shift_occurrences(sh, start, end):
                during = {(ev.employee_id, acc) for ev, acc, lo, hi in on_creator if lo < o_end and hi > o_start}
                for key in {emp if by_employee else acc for emp, acc in assigned[sh.id]}:
                    tally = _row(key)
                    tally["scheduled_shifts"] += 1
                    tally["scheduled_s"] += _overlap_s(o_start, o_end, start, end)
                    if any((emp if by_employee else acc) == key and (emp, acc) in during
                           for emp, acc in assigned[sh.id]):
                        tally["shifts_worked"] += 1

        # Worked time as (key, lo, hi, open) spans: per Employee each whole
        # event, per Creator the event's time on that Creator.
        spans = ([(ev.employee_id, ev.in_utc, ev.out_utc or now, ev.out_utc is None) for ev in events]
                 if by_employee else [(acc, lo, hi, ev.out_utc is None) for ev, acc, lo, hi in on_creator])
        for key, lo, hi, is_open in spans:
            worked_s = _overlap_s(lo, hi, start, end)
            if key is None or worked_s <= 0:
                continue
            tally = _row(key)
            tally["worked_s"] += worked_s
            tally["open_now"] = tally["open_now"] or is_open
        for key, cents in earnings.items():
            _row(key)["recorded_earnings_cents"] = int(cents)

        groups: dict[Any, str | None] = {}
        if by_employee:
            found = (await s.execute(
                select(Employee.id, Employee.display_name, EmployeeGroup.name)
                .outerjoin(EmployeeGroup, EmployeeGroup.id == Employee.group_id)
                .where(Employee.id.in_(list(rows))))).all() if rows else []
            names = {eid: name for eid, name, _ in found}
            groups = {eid: group for eid, _, group in found}
        else:
            names = dict((await s.execute(select(Account.id, Account.nickname)
                                          .where(Account.id.in_(list(rows))))).all()) if rows else {}

    out = [{
        "key": str(key),
        "display_name": names.get(key) or str(key),
        "scheduled_shifts": t["scheduled_shifts"],
        "shifts_worked": t["shifts_worked"],
        "scheduled_minutes": int(t["scheduled_s"] // 60),
        "worked_minutes": minutes_up(t["worked_s"]),
        "recorded_earnings_cents": t["recorded_earnings_cents"],
        "open_now": t["open_now"],
        "employee_id": key if by_employee else None,
        "group_name": groups.get(key),
    } for key, t in rows.items()]
    out.sort(key=lambda r: (r["display_name"].lower(), r["key"]))
    return {"rows": out}
