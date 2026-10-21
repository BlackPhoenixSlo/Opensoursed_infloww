"""service/clock_api.py — Clock events: clock in and out, the chatter's own
view, the owner's clocked-in list, Owner edits, and the lazy Auto clock-out.

Shares the `/admin/shifts` prefix with service/shifts_api.py (the Shift
schedule), whose helpers it imports; the check order and wire-time rules in
that module's docstring apply here too.

ASSUMPTION: the spec names one router module `shifts_api` with everything
"on the same router" (docs/spec/phase-02-shifts-time-tracking.md:3, :72);
the Clock endpoints live here on a second APIRouter. Rung 5: keeps
shifts_api under 1000 lines, still one /admin/shifts prefix and one sweep,
and matches the test_shifts_api/test_clock_api split. Overturned if the
spec's Owns list is read as one module.

  GET  /admin/shifts/me  (chatter) → the chatter's Creators with their own
       Agency's time-tracking flags, its own occurrences (now to now+8 days),
       its own open Clock events, across every linked Agency, and the
       clock-in `reminder` (an occurrence, or null).
  GET  /admin/shifts/clocked-in  (owner, Master) → {time_tracking_enabled,
       clocked_in[{clock_event_id, employee, account, in_utc, shift_id,
       shift}]}: the Agency's open Clock events.
  POST /admin/shifts/clock-in  {account_id?, shift_id?}  (whoever may clock)
       → the open Clock event. Without a Creator it is the agency-wide clock
       (`account_id` NULL), as Infloww's parameterless `/sign/in_manual`.
  POST /admin/shifts/clock-out  {clock_event_id}  (the event's own Employee)
       → the event, closed with close_reason=manual.
  GET  /admin/shifts/clock-status, POST /admin/shifts/clock-heartbeat
       (any session) → `ClockStatus` (`_status`), the top bar's Clock
       button; the heartbeat first marks the caller's open event as seen now.
  GET  /admin/shifts/clock-events?employee_id&from&to  (owner, Master) → one
       Employee's Clock events intersecting the range, newest first.
  PATCH /admin/shifts/clock-events/{id}  {in_utc?, out_utc?}  (owner, Master)
       → the event after an Owner edit; closing an open one sets
       close_reason=owner_edit.
  DELETE /admin/shifts/clock-events/{id}  (owner, Master) → {deleted}: an
       Owner delete (roadmap W6 6.6).
  GET  /admin/shifts/records?from&to&employee_id?  (owner, Master) → Shift
       records: the Agency's Clock events intersecting the range, one row per
       worked shift with its sales (`event_sales`; roadmap W6 6.6).

Clocking in needs, checked in this order by `_clock_gate`, the Agency's
`time-tracking` blob to hold `enabled` as literal `true` (409 otherwise), the
caller's role in its `role_ids` (`_may_clock`; 403 otherwise) and an active
Employee (403); each refusal's detail is `{error, message}` (`_refuse`).
Clocking out of one's own open event needs none of them (`clock_out`). A
chatter clocks as its Mirror Employee, an owner or the Master in its own
Agency as the owner's own Employee row (`_my_employees`; docs/spec/phase-02,
"Amended by w4-a").

Auto clock-out has no scheduler: every request to either `/admin/shifts`
router first sweeps the caller's Agencies' open Clock events and closes,
with close_reason=auto and actor `system`, each one whose inactivity
deadline has passed, at the deadline itself (`_auto_clock_out`). server.py
attaches `_sweep_callers_agencies` to both routers. The sweep runs whether or
not time tracking is on.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from auth import get_request_user
from db.engine import get_session
from db.models import Account, Action, ClockEvent, Employee, Shift, ShiftAssignment
from employees import (
    BACKGROUND_WRITES, agency_context, audit_action, find_owner_employee_id, get_owner_employee_id,
)
from sales_attribution import event_sales
from settings_api import applied_blob
from shift_time import minutes_up, shift_occurrences
from shifts_api import (
    _agency_account_ids, _agency_employee_ids, _json_object, _own_row, _owner_context, _parse_range, _parse_utc,
    _wire,
)

router = APIRouter(prefix="/admin/shifts", tags=["shifts"])


# ── Clock in and out (ticket 11, amended by w4-a) ────────────────────
#
# A clock-in acts in one Agency as one Employee: a chatter as its own Mirror
# Employee there (`agency_context`), so a chatter linked to two Agencies files
# each Agency's time apart and may hold one open Clock event in each; an owner
# or the Master as the owner's own Employee row in its own Agency
# (`get_owner_employee_id`). Each clock-in and clock-out appends its own
# `actions` row (`clock.in|out`, actor `employee:<id>`) in the write's
# transaction.

_OWNER_ACTS = "owner sessions act as the agency"
_ALREADY_IN = "already clocked in"

# Why a caller may not clock (ClockStatus's `reason`), as the status and
# message a clock write refuses with. ASSUMPTION: the inactive message is
# "this employee is inactive"; the spec fixes only the status. Rung 5.
# Overturned if the dialog needs other wording.
_REFUSALS: dict[str, tuple[int, str]] = {
    "time_tracking_off": (409, "time tracking is off"),
    "role_not_enabled": (403, "clock in is not enabled for your role"),
    "inactive": (403, "this employee is inactive"),
}


def _refuse(reason: str) -> HTTPException:
    """The refusal for a `_REFUSALS` reason. Its detail is `{error, message}`,
    the typed shape of the api-key errors (llm_client.key_error_payload), so
    the app tells the reasons apart without reading the message."""
    status, message = _REFUSALS[reason]
    return HTTPException(status_code=status, detail={"error": reason, "message": message})


# The Time tracking Panel's default auto clock-out, used when no valid value
# is stored (settings_schema: a whole number from 1 to 999). Infloww's
# `autoCheckOutMinute` defaults to 10 (ClockSetting, bundle @10663332).
DEFAULT_AUTO_CLOCK_OUT_MINUTES = 10


class TimeTracking(NamedTuple):
    enabled: bool
    clock_in_reminder: bool
    auto_clock_out_minutes: int
    # "Enable clock in and clock out for"; None while never saved.
    role_ids: frozenset[str] | None


async def _time_tracking(s, agency_user_id: str) -> TimeTracking:
    """The Agency's `time-tracking` version in effect now through the Applied
    read helper (`settings_api.applied_blob`), which drops any stored field
    its schema refuses (`time_tracking_of`)."""
    return time_tracking_of(await applied_blob(s, agency_user_id, "time-tracking"))


def time_tracking_of(blob: dict[str, Any]) -> TimeTracking:
    """An applied `time-tracking` blob's policy: `enabled` and
    `clock_in_reminder` default to the Time tracking Panel's off,
    `auto_clock_out_minutes` to 10 and `role_ids` to absent."""
    minutes = blob.get("auto_clock_out_minutes", DEFAULT_AUTO_CLOCK_OUT_MINUTES)
    role_ids = frozenset(blob["role_ids"]) if "role_ids" in blob else None
    return TimeTracking(blob.get("enabled") is True, blob.get("clock_in_reminder") is True, minutes, role_ids)


async def _may_clock(s, tt: TimeTracking, agency_user_id: str, employee_id: int | None, owner: bool) -> bool:
    """Whether this Employee's role is in "Enable clock in and clock out for".

    With `role_ids` never saved nobody may clock, as Infloww's ClockSetting
    shows every role unticked until the list is saved (live, w5-a). The
    owner's own row counts as role `owner`, and any other Employee as its
    assigned role in the `roles` blob (permissions.`_role`'s `assignments`);
    an Employee with no role may not clock.
    """
    if tt.role_ids is None:
        return False
    if owner:
        return "owner" in tt.role_ids
    roles = await applied_blob(s, agency_user_id, "roles")
    role_id = (roles.get("assignments") or {}).get(str(employee_id))
    return isinstance(role_id, str) and role_id in tt.role_ids


async def _clock_gate(s, tt: TimeTracking, agency_user_id: str, emp: Employee | None, owner: bool) -> str | None:
    """Why this Employee may not clock in this Agency, or None: time tracking
    off, then its role not enabled (`_may_clock`), then an inactive Employee.
    The one gate of clock-in, ClockStatus and the clock-in reminder; `emp` is
    None while the caller has no row there yet."""
    if not tt.enabled:
        return "time_tracking_off"
    if not await _may_clock(s, tt, agency_user_id, emp.id if emp is not None else None, owner):
        return "role_not_enabled"
    if emp is not None and not emp.is_active:
        return "inactive"
    return None


def _signed_in():
    """(user, chatter) of the request, the owner cookie winning as in
    `agency_context`; 401 with neither, even with ALLOW_ANONYMOUS_ADMIN."""
    from chatters import get_request_chatter
    user = get_request_user()
    chatter = get_request_chatter() if user is None else None
    if user is None and chatter is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return user, chatter


def _chatter_only():
    """The Chatter session of `GET /me`: 401 with no session (even with
    ALLOW_ANONYMOUS_ADMIN), 403 for an Owner or Master session.

    ASSUMPTION: `GET /me` stays chatter-only now that owners may clock; the
    top bar reads `GET /clock-status`, which answers every session. Rung 4,
    least exposure: answering owners later is additive. Overturned if an
    owner surface needs `me` itself.
    """
    user, chatter = _signed_in()
    if user is not None:
        raise HTTPException(status_code=403, detail=_OWNER_ACTS)
    return chatter


async def _my_employees(s, user, chatter) -> dict[str, Employee]:
    """The caller's own Employee in each Agency it clocks in, by Agency id,
    read without creating any: an Owner or Master session's own row in its
    own Agency (`find_owner_employee_id`), a Chatter session's Mirror Employee
    in each linked Agency. The one answer to whose clock a session holds, for
    clock-in, clock-out, ClockStatus and the reminder."""
    if user is not None:
        own = await find_owner_employee_id(s, user)
        emp = await s.get(Employee, own) if own is not None else None
        return {user.id: emp} if emp is not None else {}
    return {e.user_id: e for e in (await s.execute(select(Employee).where(
        Employee.chatter_id == chatter.id, Employee.user_id.in_(chatter.owner_user_ids),
    ).order_by(Employee.id.desc()))).scalars()}


def _clock_json(ev: ClockEvent) -> dict[str, Any]:
    return {
        "clock_event_id": ev.id,
        "employee_id": ev.employee_id,
        "account_id": ev.account_id,
        "shift_id": ev.shift_id,
        "in_utc": _wire(ev.in_utc),
        "out_utc": _wire(ev.out_utc) if ev.out_utc else None,
        "close_reason": ev.close_reason,
    }


_AS_WRITTEN = object()


def _clock_audit(s, action: str, ev: ClockEvent, before: dict[str, Any] | None,
                 actor: str | None = None, after: Any = _AS_WRITTEN) -> None:
    """One `actions` row for a clock write, in the write's transaction (the
    same rule as the Shift rows' `_audit`). With no `actor` the Employee wrote
    it and is recorded as both actor and `employee_id`; an owner or the sweep
    passes its actor and leaves `employee_id` NULL (the spec's Audit rules).
    `after` is the event as written unless given (None for a delete)."""
    s.add(Action(
        employee_id=ev.employee_id if actor is None else None,
        account_id=ev.account_id,
        action=action,
        target_type="clock_event",
        target_id=str(ev.id),
        payload_json=json.dumps({"actor": actor or f"employee:{ev.employee_id}", "before": before,
                                 "after": _clock_json(ev) if after is _AS_WRITTEN else after}),
        at=datetime.utcnow(),
    ))


def _occurrence_at(sh: Shift, t: datetime) -> tuple[datetime, datetime] | None:
    """The Shift's occurrence that contains instant `t`, or None. A cancelled
    Shift has none: it no longer holds anyone's time (the same rule as the
    `status == "scheduled"` filters of clock-in and the my-shifts read)."""
    if sh.status != "scheduled":
        return None
    held = shift_occurrences(sh, t, t + timedelta(microseconds=1))
    return held[0] if held else None


async def _assigned_shift_now(
    s, agency_user_id: str, employee_id: int, account_id: str | None, now: datetime,
) -> list[int]:
    """The ids of the live Shifts whose occurrence contains `now` and that
    assign this Employee to this Creator (to any Creator when `account_id` is
    None, the agency-wide clock): earliest occurrence start first, then
    lowest id."""
    q = select(Shift).join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id).where(
        Shift.agency_user_id == agency_user_id, Shift.status == "scheduled",
        Shift.start_utc <= now, ShiftAssignment.employee_id == employee_id,
    )
    if account_id is not None:
        q = q.where(ShiftAssignment.account_id == account_id)
    shifts = {sh.id: sh for sh in (await s.execute(q)).scalars().all()}
    found = [(occ[0], sid) for sid, sh in shifts.items() if (occ := _occurrence_at(sh, now)) is not None]
    return [sid for _, sid in sorted(found)]


async def _sweep_callers_agencies() -> None:
    """Run `_auto_clock_out` over the signed-in caller's Agencies: an
    Owner or Master session's own Agency, a Chatter session's every linked
    Agency. Nothing for a signed-out request.

    ASSUMPTION: "at the start of every /admin/shifts request" is a dependency
    of both `/admin/shifts` routers (server.py's include_router), so it runs
    before each handler's own 401/403/404/422 checks for any signed-in caller
    (owner, Master or chatter) and never for a signed-out one. Rung 5: one
    hook instead of a call in every handler; a refused request may still close
    an overdue event, which only writes what the next request would.
    Overturned if a refused request must write nothing.
    """
    user = get_request_user()
    if user is not None:
        agencies = {user.id}
    else:
        from chatters import get_request_chatter
        chatter = get_request_chatter()
        agencies = set(chatter.owner_user_ids) if chatter is not None else set()
    if agencies:
        await _auto_clock_out(agencies, datetime.utcnow())


async def _auto_clock_out(agency_user_ids: set[str], now: datetime) -> None:
    """Close every open Clock event of these Agencies whose deadline is at
    or before `now`, with `out_utc` = the deadline and close_reason=auto, and
    one `clock.auto_out` audit row (actor `system`) each.

    One rule for every event, Shift or not: the deadline is the last activity
    plus the Agency's `auto_clock_out_minutes`, where last activity is the
    latest of the clock-in, the event's last heartbeat (`last_seen_utc`) and
    the Employee's latest `actions.at` (but the app's
    `employees.BACKGROUND_WRITES`). Infloww clocks out on inactivity only
    (`useMouseMoveDetection`, bundle @10588799), so a chatter still working
    past the Shift's end stays clocked in.

    ASSUMPTION: `out_utc` is the deadline, so up to N idle minutes count as
    worked, Infloww's client clocking out when it notices the idle. Rung 5,
    the convention already in place. Overturned if the owner wants `out_utc`
    = the last activity.

    ASSUMPTION: each event is closed by a conditional UPDATE (`out_utc IS
    NULL`), and the audit row is written only when it changed the row, so two
    overlapping sweeps, or a sweep racing a clock-out, never close one event
    twice or write two rows. Rung 4: a no-op when nothing raced. Overturned
    if a clock-out that races the sweep must win over the deadline.
    """
    async with get_session() as s:
        events = (await s.execute(
            select(ClockEvent).where(ClockEvent.agency_user_id.in_(agency_user_ids),
                                     ClockEvent.out_utc.is_(None))
        )).scalars().all()
        if not events:
            return
        minutes = {a: timedelta(minutes=(await _time_tracking(s, a)).auto_clock_out_minutes)
                   for a in {ev.agency_user_id for ev in events}}
        people = {ev.employee_id for ev in events if ev.employee_id is not None}
        latest = dict((await s.execute(
            select(Action.employee_id, func.max(Action.at))
            .where(Action.employee_id.in_(people),
                   *(Action.action.not_like(f"{audit_action(m, p)}%") for m, p in BACKGROUND_WRITES))
            .group_by(Action.employee_id)
        )).all()) if people else {}

        for ev in events:
            last = max(ev.in_utc, ev.last_seen_utc or ev.in_utc, latest.get(ev.employee_id) or ev.in_utc)
            deadline = last + minutes[ev.agency_user_id]
            if now < deadline:
                continue
            before = _clock_json(ev)
            closed = await s.execute(
                update(ClockEvent)
                .where(ClockEvent.id == ev.id, ClockEvent.out_utc.is_(None))
                .values(out_utc=deadline, close_reason="auto")
                .execution_options(synchronize_session=False)
            )
            if closed.rowcount != 1:
                continue
            await s.refresh(ev)
            _clock_audit(s, "clock.auto_out", ev, before, actor="system")


@router.post("/clock-in")
async def clock_in(request: Request) -> dict[str, Any]:
    """`{account_id?, shift_id?}` → the open Clock event.

    With no `account_id` the event is the agency-wide clock (`account_id`
    NULL) in the caller's only Agency; a chatter linked to several Agencies
    gets `agency_context`'s 400 "name a creator to choose the agency" and
    names one, as old clients still do (that event keeps its Creator). A
    Creator an owner names must be its Agency's (422).

    Who clocks: a chatter as its Mirror Employee, an owner or the Master as
    the owner's own Employee row (created here on first use); `_clock_gate`'s
    refusals come first (409 time tracking off, 403 role not enabled, 403
    inactive).

    Without `shift_id` the event links the assigned occurrence that contains
    now, if any (on the named Creator, or on any Creator for the agency-wide
    clock; earliest start, then lowest id); an explicit `shift_id` must be
    one of those, or 422. A clock-in while one is open is 409, and the
    partial unique index turns a concurrent second insert that slips past the
    pre-check into the same 409, never a 500.
    """
    user, chatter = _signed_in()
    body = await _json_object(request)
    account_id = body.get("account_id")
    if account_id is not None and (not isinstance(account_id, str) or not account_id):
        raise HTTPException(status_code=422, detail="account_id must be a Creator id or left out")
    ctx = await agency_context(account_id=account_id)  # a chatter's Mirror Employee, created on first use
    shift_id = body.get("shift_id")
    if shift_id is not None and (not isinstance(shift_id, int) or isinstance(shift_id, bool)):
        raise HTTPException(status_code=422, detail="shift_id must be an integer or null")
    if ctx.is_owner:
        await get_owner_employee_id(user)
    async with get_session() as s:
        emp = (await _my_employees(s, user, chatter)).get(ctx.agency_user_id)
        if emp is None:
            raise HTTPException(status_code=503, detail="employee unavailable")
        reason = await _clock_gate(s, await _time_tracking(s, ctx.agency_user_id), ctx.agency_user_id, emp,
                                   ctx.is_owner)
        if reason is not None:
            raise _refuse(reason)
        # The Master clears `agency_context`'s account check for every Creator.
        if ctx.is_owner and account_id is not None and \
                account_id not in await _agency_account_ids(s, ctx.agency_user_id):
            raise HTTPException(status_code=422, detail="account_id: not a Creator of this agency")
        now = datetime.utcnow()
        matching = await _assigned_shift_now(s, ctx.agency_user_id, emp.id, account_id, now)
        if shift_id is not None and shift_id not in matching:
            raise HTTPException(status_code=422,
                                detail=f"shift {shift_id} is not your Shift on this Creator right now")
        already = (await s.execute(select(ClockEvent.id).where(
            ClockEvent.employee_id == emp.id, ClockEvent.out_utc.is_(None)))).first()
        if already is not None:
            raise HTTPException(status_code=409, detail=_ALREADY_IN)
        ev = ClockEvent(
            agency_user_id=ctx.agency_user_id, employee_id=emp.id, account_id=account_id,
            shift_id=shift_id if shift_id is not None else (matching[0] if matching else None),
            in_utc=now,
        )
        s.add(ev)
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail=_ALREADY_IN) from None
        _clock_audit(s, "clock.in", ev, None)
        return _clock_json(ev)


@router.post("/clock-out")
async def clock_out(request: Request) -> dict[str, Any]:
    """`{clock_event_id}` → the event, closed with `close_reason=manual`.

    Only the caller's own open event (a chatter's Mirror Employee's, an
    owner's own row's): another Employee's (in this Agency or another) or a
    missing one is 404, a closed one is 409.

    ASSUMPTION: the Agency comes from the event, whose Employee must be one of
    the caller's Mirror Employees in a linked Agency (or the owner's own row
    in its Agency), instead of from `agency_context`. The body names no
    Creator, so `agency_context()` would answer 400 to a chatter linked to two
    Agencies, and re-checking the event's Creator would strand an event whose
    Creator access was revoked after the clock-in. Rung 5. Overturned if
    clock-out must name the Creator.

    ASSUMPTION: clock-out checks none of `_clock_gate`'s reasons: a caller
    whose role was unticked, whose Agency turned time tracking off, or whose
    own row went inactive while clocked in still closes its own event (the
    top bar keeps showing Clock out while `open` is set). Rung 4: closing
    writes no new time, and a refusal would leave the event to the sweep.
    Overturned if the owner wants such events left to the sweep.
    """
    user, chatter = _signed_in()
    body = await _json_object(request)
    event_id = body.get("clock_event_id")
    if not isinstance(event_id, int) or isinstance(event_id, bool):
        raise HTTPException(status_code=422, detail="clock_event_id must be an integer")
    async with get_session() as s:
        ev = await s.get(ClockEvent, event_id)
        emp = (await _my_employees(s, user, chatter)).get(ev.agency_user_id) if ev is not None else None
        if emp is None or emp.id != ev.employee_id:
            raise HTTPException(status_code=404, detail="clock event not found")
        if ev.out_utc is not None:
            raise HTTPException(status_code=409, detail="this clock event is already closed")
        before = _clock_json(ev)
        ev.out_utc = max(datetime.utcnow(), ev.in_utc + timedelta(microseconds=1))
        ev.close_reason = "manual"
        await s.flush()
        _clock_audit(s, "clock.out", ev, before)
        return _clock_json(ev)


# How far ahead the my-shifts read lists occurrences: today plus seven days.
MY_SHIFTS_AHEAD = timedelta(days=8)


@router.get("/me")
async def my_shifts() -> dict[str, Any]:
    """The chatter's own view across every Agency it is linked to:
    `{accounts[{account_id, display_name, time_tracking_enabled,
    clock_in_reminder}], occurrences[{shift_id, occurrence_start,
    occurrence_end, tz, account_id}] (now to now+8 days), open_clocks[]}`.

    Each accessible Creator resolves to its Agency by `agency_context`'s rule
    (`_chatter_agency_for_creator`) and carries that Agency's own
    time-tracking flags. Only the caller's own Mirror Employee rows come back,
    and an occurrence names no other Employee.

    ASSUMPTION: the read finds the chatter's Mirror Employees and never creates
    one; an Agency it has none in yet has no rows. Rung 4: a read that writes
    nothing. Overturned if a later card needs the Employee id before the
    first clock-in.

    `reminder` is the occurrence a chatter is reminded to clock in for, or
    null. It needs all four: the Agency's `clock_in_reminder` on (literal
    `true`), `_clock_gate` letting that Mirror Employee clock (time tracking
    on, its role enabled, active), an assigned occurrence that contains now,
    and no open Clock event of that Mirror Employee. Of several,
    the earliest start, then the lowest Shift id, then the lowest account id.

    ASSUMPTION: across Agencies the reminder is one occurrence, not one per
    Agency; the toast keys each occurrence apart, so the next poll after a
    clock-in surfaces the next one. Rung 5, the spec's "reminder: occurrence or
    null". Overturned if a chatter linked to two Agencies must be reminded of
    both in the same minute.
    """
    from employees import _chatter_agency_for_creator
    chatter = _chatter_only()
    now = datetime.utcnow()
    by_agency: dict[str, list[str]] = {}
    for acc in sorted(chatter.account_ids):
        agency = await _chatter_agency_for_creator(chatter.id, chatter.owner_user_ids, acc)
        by_agency.setdefault(agency, []).append(acc)

    accounts: list[dict[str, Any]] = []
    open_clocks: list[dict[str, Any]] = []
    mine: list[tuple[datetime, datetime, Shift, str, bool]] = []  # (start, end, Shift, account, due)
    async with get_session() as s:
        nicknames = dict((await s.execute(
            select(Account.id, Account.nickname).where(Account.id.in_(list(chatter.account_ids)))
        )).all())
        mirrors = await _my_employees(s, None, chatter)
        for agency, accs in by_agency.items():
            tt = await _time_tracking(s, agency)
            accounts += [{"account_id": a, "display_name": nicknames.get(a) or a,
                          "time_tracking_enabled": tt.enabled, "clock_in_reminder": tt.clock_in_reminder}
                         for a in accs]
            emp = mirrors.get(agency)
            if emp is None:
                continue
            emp_id = emp.id
            rows = (await s.execute(
                select(Shift, ShiftAssignment.account_id)
                .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
                .where(Shift.agency_user_id == agency, Shift.status == "scheduled",
                       Shift.start_utc < now + MY_SHIFTS_AHEAD,
                       ShiftAssignment.employee_id == emp_id, ShiftAssignment.account_id.in_(accs))
            )).all()
            opened = [_clock_json(ev) for ev in (await s.execute(
                select(ClockEvent).where(ClockEvent.agency_user_id == agency, ClockEvent.employee_id == emp_id,
                                         ClockEvent.out_utc.is_(None))
            )).scalars()]
            open_clocks += opened
            remind = tt.clock_in_reminder and not opened and await _clock_gate(s, tt, agency, emp, False) is None
            mine += [(o_start, o_end, sh, acc, remind and o_start <= now)
                     for sh, acc in rows for o_start, o_end in shift_occurrences(sh, now, now + MY_SHIFTS_AHEAD)]
    mine.sort(key=lambda m: (m[0], m[2].id, m[3]))
    occurrences = [_my_occurrence(sh, acc, o_start, o_end) for o_start, o_end, sh, acc, _ in mine]
    accounts.sort(key=lambda a: (a["display_name"].lower(), a["account_id"]))
    reminder = next((occ for occ, m in zip(occurrences, mine) if m[4]), None)
    return {"accounts": accounts, "occurrences": occurrences, "open_clocks": open_clocks, "reminder": reminder}


def _my_occurrence(sh: Shift, account_id: str, o_start: datetime, o_end: datetime) -> dict[str, Any]:
    return {"shift_id": sh.id, "occurrence_start": _wire(o_start), "occurrence_end": _wire(o_end),
            "tz": sh.tz, "account_id": account_id}


@router.get("/clocked-in")
async def clocked_in() -> dict[str, Any]:
    """The Agency's open Clock events, oldest clock-in first, for the
    Dashboard's "Current clocked-in employees" card: `{time_tracking_enabled,
    clocked_in[{clock_event_id, employee{id, display_name}, account{id,
    display_name}, in_utc, shift_id, shift}]}`. Owner and Master sessions only
    (403 for a chatter, `_owner_context`); each reads its own Agency.

    `shift` is the linked Shift's occurrence that holds the clock-in,
    `{shift_id, occurrence_start, occurrence_end, accounts[{id,
    display_name}]}` (`_occurrence_at`), where `accounts` are the Creators
    this Employee holds in that Shift (what the card names for an agency-wide
    event, whose `account` is null), or null when the event has no Shift, the
    Shift is cancelled, or the Shift's current rule no longer holds it;
    `shift_id` keeps the stored link either way.

    ASSUMPTION: the list comes wrapped with the Agency's time-tracking flag,
    so the card says "Time tracking is off" from this one read; the spec's row
    shape is kept and `shift` is added beside `shift_id` so the card can name
    the Shift by its times. Rung 3 for the envelope (`GET /admin/employees`
    wraps its list as `{employees: [...]}`, service/employees.py) and rung 5
    for `time_tracking_enabled` and `shift`. Overturned if the card must read
    the flag from the Settings blob.

    ASSUMPTION: an open event whose Employee or Creator row is gone (SET NULL)
    is still listed, with `employee`/`account` null. Rung 4: the owner sees
    every open event. Overturned if such events must be hidden.
    """
    ctx = await _owner_context()
    async with get_session() as s:
        tt = await _time_tracking(s, ctx.agency_user_id)
        events = (await s.execute(
            select(ClockEvent).where(ClockEvent.agency_user_id == ctx.agency_user_id,
                                     ClockEvent.out_utc.is_(None))
            .order_by(ClockEvent.in_utc, ClockEvent.id)
        )).scalars().all()
        emp_ids = {ev.employee_id for ev in events if ev.employee_id is not None}
        acc_ids = {ev.account_id for ev in events if ev.account_id is not None}
        shift_ids = {ev.shift_id for ev in events if ev.shift_id is not None}
        names = dict((await s.execute(select(Employee.id, Employee.display_name)
                                      .where(Employee.id.in_(emp_ids)))).all()) if emp_ids else {}
        shifts = {sh.id: sh for sh in (await s.execute(
            select(Shift).where(Shift.id.in_(shift_ids)))).scalars()} if shift_ids else {}
        held_by: dict[tuple[int, int], list[str]] = {}
        if shift_ids:
            for sid, emp, acc in (await s.execute(
                select(ShiftAssignment.shift_id, ShiftAssignment.employee_id, ShiftAssignment.account_id)
                .where(ShiftAssignment.shift_id.in_(shift_ids)).order_by(ShiftAssignment.account_id)
            )).all():
                held_by.setdefault((sid, emp), []).append(acc)
        acc_ids |= {acc for accs in held_by.values() for acc in accs}
        nicknames = dict((await s.execute(select(Account.id, Account.nickname)
                                          .where(Account.id.in_(acc_ids)))).all()) if acc_ids else {}

    def _shift(ev: ClockEvent) -> dict[str, Any] | None:
        sh = shifts.get(ev.shift_id)
        held = _occurrence_at(sh, ev.in_utc) if sh else None
        return ({"shift_id": sh.id, "occurrence_start": _wire(held[0]), "occurrence_end": _wire(held[1]),
                 "accounts": [{"id": a, "display_name": nicknames.get(a) or a}
                              for a in held_by.get((sh.id, ev.employee_id), [])]}
                if held else None)

    return {
        "time_tracking_enabled": tt.enabled,
        "clocked_in": [{
            "clock_event_id": ev.id,
            "employee": ({"id": ev.employee_id, "display_name": names.get(ev.employee_id) or str(ev.employee_id)}
                         if ev.employee_id is not None else None),
            "account": ({"id": ev.account_id, "display_name": nicknames.get(ev.account_id) or ev.account_id}
                        if ev.account_id is not None else None),
            "in_utc": _wire(ev.in_utc),
            "shift_id": ev.shift_id,
            "shift": _shift(ev),
        } for ev in events],
    }


# ── The top bar's Clock button (w4-a) ───────────────────────────────
#
# Infloww's `HeaderSignButton` reads `GET /sign/query_signStatus` and, while
# clocked in, renews through `GET /sign/in_renew` (bundle @10626350). Ours is
# one status read and one heartbeat that returns the same status, so a renew
# that arrives after the inactivity deadline finds the event already closed by
# the router's sweep and reads `last_closed.close_reason == "auto"`.

LAST_CLOSED_WITHIN = timedelta(hours=24)


async def _status() -> dict[str, Any]:
    """`ClockStatus {can_clock, reason, open, last_closed,
    auto_clock_out_minutes, server_now}` for the signed-in caller.

    `reason` says why `can_clock` is false (`_clock_gate`), or, with
    `can_clock` true, `pick_creator` for a chatter linked to several Agencies,
    which must name a Creator (`ClockDialog`). `open` is the caller's open
    Clock event (in any of its Agencies), `last_closed` its latest event
    closed in the last 24 hours `{clock_event_id, out_utc, close_reason}`.

    ASSUMPTION: for a chatter linked to several Agencies `can_clock` is true
    when any of them lets it clock, and `auto_clock_out_minutes` is that of
    the open event's Agency, else the smallest of its Agencies', so the
    heartbeat is never slower than the strictest policy. Rung 5. Overturned
    if such a chatter must see each Agency's status apart.

    ASSUMPTION: a read never creates the owner's or a chatter's Employee row;
    with none yet, the role is checked as an Employee with no role assigned
    and nothing is open. Rung 4: a read that writes nothing.
    """
    user, chatter = _signed_in()
    if user is None and not chatter.owner_user_ids:
        raise HTTPException(status_code=403, detail="chatter is not linked to an agency")
    agencies = sorted({user.id} if user is not None else chatter.owner_user_ids)
    now = datetime.utcnow()
    async with get_session() as s:
        rows = await _my_employees(s, user, chatter)
        mine = (ClockEvent.employee_id.in_([e.id for e in rows.values()]), ClockEvent.agency_user_id.in_(agencies))
        opened = (await s.execute(select(ClockEvent).where(*mine, ClockEvent.out_utc.is_(None))
                                  .order_by(ClockEvent.in_utc.desc(), ClockEvent.id.desc()))).scalars().first()
        closed = (await s.execute(select(ClockEvent).where(
            *mine, ClockEvent.out_utc.is_not(None), ClockEvent.out_utc >= now - LAST_CLOSED_WITHIN,
        ).order_by(ClockEvent.out_utc.desc(), ClockEvent.id.desc()))).scalars().first()
        policies = {agency: await _time_tracking(s, agency) for agency in agencies}
        reasons = {agency: await _clock_gate(s, policies[agency], agency, rows.get(agency), user is not None)
                   for agency in agencies}

    if len(agencies) == 1:
        reason = reasons[agencies[0]]
        can_clock = reason is None
    else:
        can_clock = any(r is None for r in reasons.values())
        reason = "pick_creator" if can_clock else next(iter(reasons.values()))
    minutes = (policies[opened.agency_user_id].auto_clock_out_minutes if opened is not None
               else min(p.auto_clock_out_minutes for p in policies.values()))
    return {
        "can_clock": can_clock,
        "reason": reason,
        "open": _clock_json(opened) if opened is not None else None,
        "last_closed": ({"clock_event_id": closed.id, "out_utc": _wire(closed.out_utc),
                         "close_reason": closed.close_reason} if closed is not None else None),
        "auto_clock_out_minutes": minutes,
        "server_now": _wire(now),
    }


@router.get("/clock-status")
async def clock_status() -> dict[str, Any]:
    """The caller's `ClockStatus` (`_status`). Any signed-in session."""
    return await _status()


@router.post("/clock-heartbeat")
async def clock_heartbeat() -> dict[str, Any]:
    """Marks the caller's open Clock event seen now, then its `ClockStatus`.
    The app sends it only after real input since the last beat, so an idle
    open tab does not keep anyone clocked in. Not in an Agency whose time
    tracking is off, so the sweep still closes an event left open there.
    Left out of the audit middleware's generic rows
    (employees._AUDIT_SKIP_PREFIXES)."""
    user, chatter = _signed_in()
    async with get_session() as s:
        rows = {agency: emp for agency, emp in (await _my_employees(s, user, chatter)).items()
                if (await _time_tracking(s, agency)).enabled}
        if rows:
            await s.execute(update(ClockEvent).where(
                ClockEvent.employee_id.in_([e.id for e in rows.values()]),
                ClockEvent.agency_user_id.in_(list(rows)), ClockEvent.out_utc.is_(None),
            ).values(last_seen_utc=datetime.utcnow()).execution_options(synchronize_session=False))
    return await _status()


# ── Clock records (w4-a) ────────────────────────────────────────────

@router.get("/clock-events")
async def list_clock_events(
    employee_id: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
) -> dict[str, Any]:
    """One Employee's Clock events that intersect [from, to), newest clock-in
    first, for Employee reports' "Clocked hours" modal: `{clock_events[
    {clock_event_id, employee_id, account_id, shift_id, in_utc, out_utc,
    close_reason, minutes, edited}]}`. Owner and Master sessions only (403
    for a chatter); another Agency's or a missing Employee is 404. The range
    follows the Timesheet's (at most 42 days, 422 otherwise). `minutes` is
    rounded up and null while open.

    ASSUMPTION: `edited` (an addition to the prompt's shape) is true when the
    event was closed by an Owner edit or has a `clock.owner_edit` audit row,
    so the modal can mark it "(edited)"; those rows follow the 90-day
    `actions` retention, after which only an owner-closed event still reads
    edited. Rung 5. Overturned if the mark must outlive the audit rows, which
    needs a column.
    """
    async with get_session() as s:
        events = await _events_in_range(s, employee_id, from_, to, required=True)
        return {"clock_events": await _records(s, events)}


async def _events_in_range(s, employee_id: str | None, from_: str | None, to: str | None, *,
                           required: bool) -> list[ClockEvent]:
    """The caller's Agency's Clock events intersecting [from, to), newest
    clock-in first; one Employee's when `employee_id` is given or
    `required` (another Agency's or a missing one 404, not an integer 422)."""
    ctx = await _owner_context()
    start, end = _parse_range(from_, to)
    q = select(ClockEvent).where(
        ClockEvent.agency_user_id == ctx.agency_user_id,
        ClockEvent.in_utc < end, or_(ClockEvent.out_utc.is_(None), ClockEvent.out_utc > start),
    ).order_by(ClockEvent.in_utc.desc(), ClockEvent.id.desc())
    if employee_id is not None or required:
        try:
            emp_id = int(employee_id or "")
        except ValueError:
            raise HTTPException(status_code=422, detail="employee_id must be an integer") from None
        if not await _agency_employee_ids(s, ctx.agency_user_id, [emp_id]):
            raise HTTPException(status_code=404, detail="employee not found")
        q = q.where(ClockEvent.employee_id == emp_id)
    return list((await s.execute(q)).scalars().all())


async def _records(s, events: list[ClockEvent]) -> list[dict[str, Any]]:
    """Each event as a clock record: `minutes` rounded up (null while open)
    and `edited`."""
    edited = set((await s.execute(select(Action.target_id).where(
        Action.action == "clock.owner_edit", Action.target_type == "clock_event",
        Action.target_id.in_([str(ev.id) for ev in events]),
    ))).scalars().all()) if events else set()
    return [{
        **_clock_json(ev),
        "minutes": minutes_up((ev.out_utc - ev.in_utc).total_seconds()) if ev.out_utc is not None else None,
        "edited": ev.close_reason == "owner_edit" or str(ev.id) in edited,
    } for ev in events]


@router.get("/records")
async def shift_records(
    employee_id: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
) -> dict[str, Any]:
    """Shift records (roadmap W6 6.6; Infloww's `/shift/v2/used/query`): the
    Agency's Clock events intersecting [from, to), of one Employee when
    `employee_id` is given, newest clock-in first, each a worked shift:
    `{records[{...clock record, sales_cents, sales}]}`, where `sales_cents`
    and `sales` (how many sales) are the event's sales (`event_sales`). The
    same session and range rules as `/clock-events`.

    ASSUMPTION: Shift records list Clock events, not scheduled occurrences:
    Infloww's records are worked shifts (Sales, Messages sent, ...), and an
    unworked occurrence has no record. Its chatting statistics are not here:
    nothing in the Relay records keystrokes, and the others are Employee
    reports' (roadmap 5.2). Rung 5. Overturned if the owner wants a row per
    scheduled occurrence, worked or not."""
    async with get_session() as s:
        events = await _events_in_range(s, employee_id, from_, to, required=False)
        sales = await event_sales(s, events, datetime.utcnow())
        return {"records": [{
            **rec,
            "sales_cents": sum(c.amount_cents for c in sales[rec["clock_event_id"]]),
            "sales": len({c.tx_id for c in sales[rec["clock_event_id"]]}),
        } for rec in await _records(s, events)]}


@router.patch("/clock-events/{clock_event_id}")
async def owner_edit_clock_event(clock_event_id: str, request: Request) -> dict[str, Any]:
    """An Owner edit, `{in_utc?, out_utc?}` → the event.

    A field left out keeps its stored time. The new interval needs
    `in < out <= now` (for an event left open, `in < now`), else 422; it may
    not overlap another Clock event of the same Employee (409), where touching
    ends do not overlap and an open event runs on to now. Closing an open
    event sets close_reason=owner_edit. Another Agency's event, a missing one
    or an id that is not an integer is 404. One `clock.owner_edit` audit row,
    actor `owner:<id>`, with before and after.

    ASSUMPTION: editing an already closed event keeps its close_reason
    (`manual` or `auto`); only closing an open one marks it `owner_edit`, and
    the audit row records every edit. Rung 5, the spec's "Closing an open
    event sets close_reason=owner_edit" read literally. Overturned if any
    edited event must read `owner_edit`.

    ASSUMPTION: an open event may have only its clock-in corrected and stay
    open; a body with neither field, a null field or reopening a closed event
    (`out_utc: null`) is 422. Rung 4: a refusal writes nothing and loosening it
    later is additive. Overturned if the owner needs to reopen an event.

    ASSUMPTION: Clock events are half-open intervals `[in, out)`, so one that
    ends exactly when another starts does not overlap it, and an open event
    counts as running on to now: its new `in_utc` must be before now and it
    clashes with any event that ends after its clock-in. Rung 5: the spec says
    only "must not overlap another Clock event of the same Employee" and
    "in < out <= now". Overturned if touching events must count as
    overlapping, or an open event must be measured to some end other than now.

    ASSUMPTION: the future and inverted intervals are 422, and only the
    overlap is 409, following the spec's check order (422 an invalid body,
    409 a state conflict). Rung 5. Overturned if the app expects 409 for all
    three.
    """
    ctx = await _owner_context()
    async with get_session() as s:
        ev = await _own_row(s, ctx, ClockEvent, clock_event_id, "clock event")
        body = await _json_object(request)
        if "in_utc" not in body and "out_utc" not in body:
            raise HTTPException(status_code=422, detail="in_utc or out_utc is required")
        new_in = _parse_utc(body["in_utc"], "in_utc") if "in_utc" in body else ev.in_utc
        new_out = _parse_utc(body["out_utc"], "out_utc") if "out_utc" in body else ev.out_utc
        now = datetime.utcnow()
        if new_out is not None and new_out > now:
            raise HTTPException(status_code=422, detail="the clock-out cannot be in the future")
        if new_in >= (new_out if new_out is not None else now):
            raise HTTPException(status_code=422, detail="in_utc must be before out_utc")
        if ev.employee_id is not None:
            q = select(ClockEvent.id).where(
                ClockEvent.employee_id == ev.employee_id, ClockEvent.id != ev.id,
                or_(ClockEvent.out_utc.is_(None), ClockEvent.out_utc > new_in),
            )
            if new_out is not None:
                q = q.where(ClockEvent.in_utc < new_out)
            clashes = sorted((await s.execute(q)).scalars().all())
            if clashes:
                raise HTTPException(
                    status_code=409,
                    detail=f"overlaps this Employee's other Clock event(s) {', '.join(map(str, clashes))}")
        before = _clock_json(ev)
        if ev.out_utc is None and new_out is not None:
            ev.close_reason = "owner_edit"
        ev.in_utc = new_in
        ev.out_utc = new_out
        await s.flush()
        _clock_audit(s, "clock.owner_edit", ev, before, actor=f"owner:{ctx.agency_user_id}")
        return _clock_json(ev)


@router.delete("/clock-events/{clock_event_id}")
async def owner_delete_clock_event(clock_event_id: str) -> dict[str, Any]:
    """An Owner delete (roadmap W6 6.6; Infloww's "Delete shift record?"):
    the event's row is gone, so its time leaves the Timesheet, Employee
    reports' Clocked hours and the Shift schedule credit. Another Agency's
    event, a missing one or an id that is not an integer is 404. One
    `clock.owner_delete` audit row, actor `owner:<id>`, holds the event as it
    was (`before`; `after` null).

    ASSUMPTION: an open event may be deleted too (a mistaken clock-in), which
    clocks its Employee out with no record left. Rung 5: the owner may delete
    any record, as in Infloww. Overturned if an open event must be closed
    before it can be deleted."""
    ctx = await _owner_context()
    async with get_session() as s:
        ev = await _own_row(s, ctx, ClockEvent, clock_event_id, "clock event")
        _clock_audit(s, "clock.owner_delete", ev, _clock_json(ev), actor=f"owner:{ctx.agency_user_id}", after=None)
        await s.delete(ev)
        return {"deleted": ev.id}
