"""service/notifications_api.py — the Agency owner's notification centre
(roadmap W6 6.7, 6.10).

Infloww's bell opens "System Notifications" (role changes, an employee who
unsent a message, ...); ours is the OnlyFans feed. This is the Agency's own
feed beside it: `agency_notifications` rows, owner-only (a chatter session is
refused at `chatters._CHATTER_BLOCKED_ADMIN_PREFIXES`; YAGNI until employees
get notifications of their own). Under Master impersonation `require_user`
is the impersonated owner, so the Master reads that owner's feed; marking it
read is a mutation and refused like any other while impersonating.

  GET  /admin/agency-notifications?limit&offset → {notifications[], unread}
  POST /admin/agency-notifications/{id}/read    → {unread}
  POST /admin/agency-notifications/read-all     → {unread}

Where the rows come from (settings_schema.NOTIFICATION_KINDS):

  role_changed          PUT /admin/settings/roles, PUT /admin/employees/{id}/setup
  employee_deactivated  DELETE or PATCH {is_active: false} /admin/employees/{id}
  message_unsent        DELETE /api/of/v2/messages/{id} from a chatter session
  clock_in_missed       `tick`, every TICK_S: a Shift running for CLOCK_IN_GRACE
                        whose Employee has not clocked in
  session_dead          account_health.mark_session_dead, once per dead episode

The first three ride `employees.audit_middleware`: `audit_snapshot` reads the
before-state of the few routes above (None for any other request, no read)
and returns the request's after-step, which compares it with the state after
a 2xx, so a save that changed no role, or a PATCH of an already inactive
Employee, files nothing. Each kind is on unless the owner's `preferences`
blob stores `notifications.<kind>: false`. One `notify` call files a
request's (or a sweep's) notices for one Agency in one insert and pushes the
owner's unread count once over SSE (`agency_notifications {unread}`, to the
owner's sessions only: events.owner_audience). `tick` also drops rows older
than RETENTION.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import events
from auth import get_request_user, require_user
from db.engine import get_session
from db.models import (
    Account, AgencyNotification, ClockEvent, Employee, Fan, SettingsVersion, Shift, ShiftAssignment, UserAccount,
)
from settings_schema import BUILT_IN_ROLE_DEFAULTS, NOTIFICATION_KINDS

log = logging.getLogger("of-relay.notifications")

router = APIRouter(prefix="/admin/agency-notifications", tags=["notifications"])

# How long a running Shift waits for its clock-in before it is "missed", and
# how often the sweep looks.
CLOCK_IN_GRACE = timedelta(minutes=15)
TICK_S = 5 * 60
# Rows older than this are dropped by the sweep.
RETENTION = timedelta(days=90)

_SIGN_IN = "sign in as an account owner to read notifications"


# ── Filing notifications ─────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Notice:
    """One notification to file; `dedupe` makes a second filing a no-op."""
    kind: str  # one of NOTIFICATION_KINDS
    text: str
    account_id: str | None = None
    employee_id: int | None = None
    data: dict[str, Any] | None = None
    dedupe: str | None = None


async def _switched_off(s, agency_user_id: str) -> set[str]:
    from settings_api import applied_blob  # lazy: settings_api imports employees, which imports this
    prefs = (await applied_blob(s, agency_user_id, "preferences")).get("notifications") or {}
    return {kind for kind in NOTIFICATION_KINDS if prefs.get(kind) is False}


async def _unread(s, agency_user_id: str) -> int:
    return (await s.execute(select(func.count(AgencyNotification.id)).where(
        AgencyNotification.agency_user_id == agency_user_id, AgencyNotification.read_at.is_(None),
    ))).scalar_one()


def _push(agency_user_id: str, unread: int) -> None:
    events.publish_state("agency_notifications", agency=events.owner_audience(agency_user_id), unread=unread)


async def notify(agency_user_id: str, notices: Sequence[Notice]) -> int:
    """File `notices` for the Agency in one insert, minus the kinds its owner
    switched off and those whose `dedupe` key it already has; then push the
    unread count once. Returns how many were filed."""
    if not notices:
        return 0
    async with get_session() as s:
        off = await _switched_off(s, agency_user_id)
        now = datetime.utcnow()
        rows = [dict(agency_user_id=agency_user_id, kind=n.kind, text=n.text, account_id=n.account_id,
                     employee_id=n.employee_id, data_json=json.dumps(n.data) if n.data else None,
                     dedupe_key=n.dedupe, created_at=now)
                for n in notices if n.kind not in off]
        if not rows:
            return 0
        filed = (await s.execute(sqlite_insert(AgencyNotification).values(rows).on_conflict_do_nothing())).rowcount
        if filed < 1:
            return 0
        unread = await _unread(s, agency_user_id)
    _push(agency_user_id, unread)
    return filed


# ── From the audit middleware ────────────────────────────────────────

# What the middleware awaits after a 2xx: (request body, the audit row's
# employee_id, its account_id), i.e. what was sent, who acted, on which Creator.
AfterStep = Callable[[bytes, int | None, str | None], Awaitable[None]]

_ROLES = re.compile(r"PUT /admin/settings/roles$")
_SETUP = re.compile(r"PUT /admin/employees/(\d+)/setup$")
_EMPLOYEE = re.compile(r"(?:PATCH|DELETE) /admin/employees/(\d+)$")
_UNSEND = re.compile(r"DELETE /api/of/v2/messages/(\d+)$")


async def audit_snapshot(method: str, path: str) -> AfterStep | None:
    """The after-step of a request that may file a notification, holding the
    state it read before the request; None for every other request (read
    nothing). Never raises."""
    action = f"{method} {path}"
    try:
        if _ROLES.match(action):
            user = get_request_user()
            return await _roles_step(user.id) if user is not None else None
        if m := _SETUP.match(action):
            e = await _owned_employee(int(m.group(1)))
            if e is None:
                return None
            # The route seeds the role presets first (employees._held_role_ids, validating the role); no owner's change.
            from settings_api import ensure_role_presets
            await ensure_role_presets(e.user_id)
            return await _roles_step(e.user_id)
        if m := _EMPLOYEE.match(action):
            e = await _owned_employee(int(m.group(1)))
            return _deactivation_step(e.user_id, e.id, e.is_active) if e is not None else None
        if m := _UNSEND.match(action):
            return _unsend_step(int(m.group(1)))
    except Exception:
        log.exception("notification snapshot failed (%s)", action)
    return None


async def _owned_employee(employee_id: int) -> Employee | None:
    """The signed-in owner's own Employee, else None: the routes 404 anyone
    else's, so another Agency's request reads (and seeds) nothing here."""
    user = get_request_user()
    if user is None:
        return None
    async with get_session() as s:
        e = await s.get(Employee, employee_id)
    return e if e is not None and e.user_id == user.id else None


async def _roles(s, agency_user_id: str) -> dict[str, Any]:
    from settings_api import applied_blob
    return await applied_blob(s, agency_user_id, "roles")


async def _roles_step(agency: str) -> AfterStep:
    """A roles blob write (the Roles tab, or one Employee's setup): one
    `role_changed` per changed assignment of the Agency's own Employees (an
    assignment key naming anyone else's is ignored), and one for changed
    role definitions or enforcement."""
    async with get_session() as s:
        before = await _roles(s, agency)

    async def after(_body: bytes, _employee_id: int | None, _account_id: str | None) -> None:
        async with get_session() as s:
            changes = _role_changes(before, await _roles(s, agency))
            ids = [int(k) for k, *_ in changes if k.isdigit()]
            names = dict((await s.execute(select(Employee.id, Employee.display_name).where(
                Employee.id.in_(ids), Employee.user_id == agency))).all()) if ids else {}
        notices = []
        for key, old, new in changes:
            if not key:
                notices.append(Notice("role_changed", f"Role settings changed: {new}"))
            elif key.isdigit() and int(key) in names:
                notices.append(Notice("role_changed", f"{names[int(key)]}'s role changed from {old} to {new}",
                                      employee_id=int(key)))
        await notify(agency, notices)
    return after


def _deactivation_step(agency: str, employee_id: int, was_active: bool) -> AfterStep:
    """An Employee edit or delete: `employee_deactivated` only when it turned
    an active Employee inactive."""
    async def after(_body: bytes, _employee_id: int | None, _account_id: str | None) -> None:
        if not was_active:
            return
        async with get_session() as s:
            e = await s.get(Employee, employee_id)
        if e is not None and not e.is_active:
            await notify(agency, [Notice("employee_deactivated", f"{e.display_name} was deactivated",
                                         employee_id=e.id)])
    return after


def _unsend_step(message_id: int) -> AfterStep:
    """An unsent message: `message_unsent` when a chatter unsent it (the audit
    row names its Mirror Employee, whose Agency is notified); the owner
    unsending their own message is no news to them."""
    async def after(body: bytes, employee_id: int | None, account_id: str | None) -> None:
        if get_request_user() is not None or employee_id is None:
            return
        async with get_session() as s:
            actor = await s.get(Employee, employee_id)
            if actor is None or actor.user_id is None:
                return
            fan_id = _with_user_id(body)
            fan = await s.get(Fan, (account_id, fan_id)) if account_id and fan_id is not None else None
            creator = await s.get(Account, account_id) if account_id else None
        to = _fan_name(fan) or (f"fan {fan_id}" if fan_id is not None else "a fan")
        on = f" on {creator.nickname or creator.id}" if creator is not None else ""
        await notify(actor.user_id, [Notice(
            "message_unsent", f"{actor.display_name} unsent a message to {to}{on}", account_id=account_id,
            employee_id=actor.id, data={"fan_id": fan_id, "message_id": message_id})])
    return after


def _role_names(roles: dict[str, Any]) -> dict[str, str]:
    names = {"owner": "Owner", "admin": "Admin", **{k: d["name"] for k, d in BUILT_IN_ROLE_DEFAULTS.items()}}
    for r in roles.get("roles") or []:
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            names[r["id"]] = r.get("name") or r["id"]
    return names


def _role_changes(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(employee id, old role name, new role name) per changed assignment,
    then ("", "", "<role names>") when role definitions or the enforcement
    switch changed."""
    old_names, new_names = _role_names(before), _role_names(after)
    old_as, new_as = before.get("assignments") or {}, after.get("assignments") or {}
    out = [(k, old_names.get(old_as.get(k), "no role"), new_names.get(new_as.get(k), "no role"))
           for k in sorted(set(old_as) | set(new_as)) if old_as.get(k) != new_as.get(k)]
    old_roles = {r.get("id"): r for r in before.get("roles") or [] if isinstance(r, dict)}
    new_roles = {r.get("id"): r for r in after.get("roles") or [] if isinstance(r, dict)}
    changed = [new_names.get(i) or old_names.get(i) or str(i)
               for i in sorted(set(old_roles) | set(new_roles), key=str) if old_roles.get(i) != new_roles.get(i)]
    if (before.get("enforce") is not False) != (after.get("enforce") is not False):
        changed.append("role permissions " + ("on" if after.get("enforce") is not False else "off"))
    if changed:
        out.append(("", "", ", ".join(changed)))
    return out


def _body_json(body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _with_user_id(body: bytes) -> int | None:
    raw = _body_json(body).get("withUserId")
    return int(raw) if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit()) else None


def _fan_name(fan: Fan | None) -> str | None:
    if fan is None:
        return None
    return fan.custom_nickname or fan.of_display_name or (f"@{fan.of_username}" if fan.of_username else None)


# ── Dead sessions (account_health) ───────────────────────────────────

async def notify_session_dead(account_id: str, reason: str, since: datetime) -> None:
    """One `session_dead` notification per owner of the Creator for the dead
    episode that began at `since` (its `session_dead_at`). Never raises: the
    flag it reports matters more."""
    try:
        async with get_session() as s:
            owners = (await s.execute(select(UserAccount.user_id).where(
                UserAccount.account_id == account_id))).scalars().all()
            acc = await s.get(Account, account_id)
        name = (acc.nickname if acc is not None else None) or account_id
        why = "has no captured session" if reason == "no_session" else "was logged out of OnlyFans"
        notice = Notice("session_dead", f"{name} {why}: relink the creator to resume", account_id=account_id,
                        data={"reason": reason}, dedupe=f"session_dead:{account_id}:{since.isoformat()}")
        for owner in owners:
            await notify(owner, [notice])
    except Exception:
        log.exception("session_dead notification failed (account=%s)", account_id)


# ── The periodic sweep: missed clock-ins, retention ──────────────────

async def tick(now: datetime | None = None) -> int:
    """Drop rows older than RETENTION, then file `clock_in_missed` for every
    Shift occurrence running for at least CLOCK_IN_GRACE whose assigned
    Employee may clock (clock_api._clock_gate: time tracking on, its role
    enabled, active) and has no Clock event touching the occurrence. One per
    Employee per occurrence (dedupe), so the sweep may run as often as it
    likes; a Shift that cannot be read (an unknown zone) is logged and
    skipped. Returns how many were filed."""
    from clock_api import _clock_gate, _occurrence_at, _time_tracking  # lazy: clock_api imports employees
    now = now or datetime.utcnow()
    async with get_session() as s:
        await s.execute(delete(AgencyNotification).where(AgencyNotification.created_at < now - RETENTION))
        agencies = (await s.execute(select(SettingsVersion.user_id).where(
            SettingsVersion.tab == "time-tracking").distinct())).scalars().all()
    filed = 0
    for agency in agencies:
        notices: list[Notice] = []
        async with get_session() as s:
            tt = await _time_tracking(s, agency)
            if not tt.enabled:
                continue
            rows = (await s.execute(
                select(Shift, Employee).join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
                .join(Employee, Employee.id == ShiftAssignment.employee_id)
                .where(Shift.agency_user_id == agency, Shift.status == "scheduled", Shift.start_utc <= now,
                       or_(Shift.repeat_days.isnot(None), Shift.end_utc > now))
            )).unique().all()
            may: dict[int, bool] = {}
            seen: set[tuple[int, int]] = set()
            for sh, emp in rows:
                if (sh.id, emp.id) in seen:
                    continue
                seen.add((sh.id, emp.id))
                try:
                    occ = _occurrence_at(sh, now)
                    local = occ and occ[0].replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(sh.tz))
                except Exception:
                    log.exception("clock-in sweep skipped shift %s (tz=%r)", sh.id, sh.tz)
                    continue
                if occ is None or now - occ[0] < CLOCK_IN_GRACE:
                    continue
                if emp.id not in may:
                    may[emp.id] = await _clock_gate(s, tt, agency, emp, False) is None
                if not may[emp.id]:
                    continue
                clocked = (await s.execute(select(ClockEvent.id).where(
                    ClockEvent.employee_id == emp.id, ClockEvent.in_utc <= now,
                    or_(ClockEvent.out_utc.is_(None), ClockEvent.out_utc > occ[0])).limit(1))).first()
                if clocked is None:
                    start = occ[0]
                    notices.append(Notice(
                        "clock_in_missed",
                        f"{emp.display_name} has not clocked in for the {local:%H:%M} shift ({sh.tz})",
                        employee_id=emp.id, data={"shift_id": sh.id, "occurrence_start": start.isoformat() + "Z"},
                        dedupe=f"clock_in_missed:{sh.id}:{emp.id}:{start.isoformat()}"))
        filed += await notify(agency, notices)
    return filed


# ── Routes ───────────────────────────────────────────────────────────

def _row(n: AgencyNotification) -> dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind,
        "text": n.text,
        "account_id": n.account_id,
        "employee_id": n.employee_id,
        "data": json.loads(n.data_json) if n.data_json else None,
        "created_at": n.created_at.isoformat() + "Z",
        "read": n.read_at is not None,
    }


@router.get("")
async def list_notifications(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The owner's notifications, newest first, and the unread count."""
    user = require_user(detail=_SIGN_IN)
    async with get_session() as s:
        rows = (await s.execute(
            select(AgencyNotification).where(AgencyNotification.agency_user_id == user.id)
            .order_by(AgencyNotification.created_at.desc(), AgencyNotification.id.desc())
            .limit(limit).offset(offset)
        )).scalars().all()
        return {"notifications": [_row(n) for n in rows], "unread": await _unread(s, user.id)}


async def _mark_read(user_id: str, notification_id: int | None) -> dict[str, int]:
    async with get_session() as s:
        q = update(AgencyNotification).where(
            AgencyNotification.agency_user_id == user_id, AgencyNotification.read_at.is_(None))
        if notification_id is not None:
            n = await s.get(AgencyNotification, notification_id)
            if n is None or n.agency_user_id != user_id:
                raise HTTPException(status_code=404, detail="notification not found")
            q = q.where(AgencyNotification.id == notification_id)
        await s.execute(q.values(read_at=datetime.utcnow()).execution_options(synchronize_session=False))
        unread = await _unread(s, user_id)
    _push(user_id, unread)
    return {"unread": unread}


@router.post("/read-all")
async def read_all() -> dict[str, int]:
    return await _mark_read(require_user(detail=_SIGN_IN).id, None)


@router.post("/{notification_id}/read")
async def read_one(notification_id: int) -> dict[str, int]:
    return await _mark_read(require_user(detail=_SIGN_IN).id, notification_id)
