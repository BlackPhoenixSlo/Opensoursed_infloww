"""
Employee CRUD + audit middleware.

The "employee picker" is auth-lite: no passwords, no sessions. The user
clicks who they are on first page load; the browser stores the chosen id
in localStorage and sends it as `X-Employee-Id` on every subsequent call.
The relay treats that header as the actor for audit purposes and refuses
to mutate state without it (in phase D — phase A only logs).

This module owns:
  • `GET    /admin/employees`           — list active + inactive
  • `POST   /admin/employees`           — create
  • `PATCH  /admin/employees/{id}`      — rename / recolor / disable
  • `DELETE /admin/employees/{id}`      — soft-delete (sets is_active=false)
  • `GET    /admin/audit`               — paginated audit log
  • `audit_middleware`                  — FastAPI middleware that writes
    a row to `actions` for every mutating request that succeeded.

Why a separate file and not inline in server.py: server.py is already
~2200 lines. Each new concern that fits cleanly into its own module
saves us a refactor pain later. Imported once from server.py at startup.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, select

import events
from account_security import clear_two_factor_values, link_login, revoke_if_unlinked, revoke_sessions
from db.engine import get_session
from db.models import (
    Action, Chatter, ChatterAccountAccess, ChatterUser, Employee, EmployeeAccountAccess, EmployeeGroup,
    UserAccount,
)
from auth import assert_account_owned, get_request_user
import audit_labels
import notifications_api
from settings_schema import BUILT_IN_ROLE_IDS

log = logging.getLogger("of-relay.employees")

router = APIRouter()

# Per-friend chatter quota. Counts ACTIVE rows only — soft-deleted
# employees stay around so audit history reads cleanly (see DELETE handler
# below), and recycling slots after firing someone is normal. 0 / unset
# disables the cap. Founder bypasses by raising this in the env or by
# leaving it unset on their own deploy.
MAX_EMPLOYEES_PER_USER = int(os.environ.get("MAX_EMPLOYEES_PER_USER", "20") or "0")


def _employee_limit(active_count: int, message: str) -> HTTPException:
    """The cap refusal, typed so Manage employees shows its limit dialog (roadmap 6.13)."""
    return HTTPException(status_code=409, detail={
        "code": "employee_limit",
        "message": message,
        "limit": MAX_EMPLOYEES_PER_USER,
        "active": active_count,
    })

# Default colors cycled when an employee is created without one specified.
# Picked to be distinguishable on the dark UI + colorblind-safe enough.
_DEFAULT_COLORS = [
    "#8b5cf6",  # violet
    "#22d3ee",  # cyan
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#10b981",  # emerald
    "#ec4899",  # pink
    "#84cc16",  # lime
    "#06b6d4",  # sky
]


# ── Ownership helper ──────────────────────────────────────────────────

async def _load_owned_employee(s, employee_id: int) -> Employee:
    """Return the Employee row only if owned by the signed-in friend.
    Raises 404 if missing or not owned. Unauthed callers see every row
    (back-compat). Centralised so per-employee endpoints stay one-liners.
    """
    e = await s.get(Employee, employee_id)
    if e is None:
        raise HTTPException(status_code=404, detail=f"no employee with id {employee_id}")
    user = get_request_user()
    if user is not None and e.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"no employee with id {employee_id}")
    return e


# ── CRUD endpoints ────────────────────────────────────────────────────

class _EmployeeCreateBody(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)
    color: str | None = Field(None, description="Hex color; defaults to a cycled palette entry")
    is_active: bool = True


class _EmployeeUpdateBody(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=64)
    color: str | None = None
    is_active: bool | None = None


@router.get("/admin/employees")
async def list_employees(include_disabled: bool = Query(True)) -> dict[str, Any]:
    """Every employee row owned by the signed-in friend. The browser picker
    reads this on first load.

    Default returns all rows so the Settings → Employees table can show
    both active and disabled (with a strikethrough). Pass
    `?include_disabled=false` for the inline picker dropdown.

    `chatter_id` is exposed so the owner's "Who's chatting?" picker can
    hide auto-created per-(chatter, owner) mirror rows (the picker is
    "which member of my team is at the keyboard," not "impersonate a
    chatter"). Callers like the orphan-tip assign dropdown still want
    them visible so they can attribute revenue to a chatter.

    An unauthenticated request is refused 401 by
    `server._account_isolation_middleware` before it gets here; only with
    ALLOW_ANONYMOUS_ADMIN=1 does it reach this handler, and then it sees every
    owner's roster but never the system Automation sentinel.

    `account_ids` is each Employee's Creator access: None for all Creators
    (the wildcard row), else the granted Creator ids (docs/spec/phase-05,
    Interfaces), and `group_id` its Employee group (null for none; item 4,
    set by Batch edit group). A chatter-only session is refused 403 by the chatter admin
    gate (`chatters._CHATTER_BLOCKED_ADMIN_PREFIXES`): Manage employees is
    owner-only at the Relay, not only in the menu (phase-05 story 13).

    ASSUMPTION: the refusal covers every chatter, also on
    `?include_disabled=false` (the Messages filter's Employee dropdown, which
    for a chatter then lists no Employees), because the list served a chatter
    every Agency's roster. Rung 2: ticket 30's "a chatter gets 403". Overturned
    if chatters need a roster, which would then be scoped to their Agencies.

    ASSUMPTION: the gate sits in chatters.py and permissions.py, outside the
    spec's Owns list, because a handler-only check left the middleware's
    carve-out admitting the chatter it then refused. Rung 3 (house precedent:
    every other owner-only /admin surface is a blocked prefix). Overturned if
    Owns is binding, in which case the handler calls `chatters.assert_owner()`.
    """
    user = get_request_user()
    if user is not None:
        await _ensure_login_mirrors(user.id)
        await get_owner_employee_id(user)
        from settings_api import ensure_role_presets  # lazy: settings_api imports this module
        await ensure_role_presets(user.id)
    async with get_session() as s:
        stmt = select(Employee).order_by(Employee.created_at)
        if not include_disabled:
            stmt = stmt.where(Employee.is_active == True)  # noqa: E712
        if user is not None and not user.is_admin:
            stmt = stmt.where(Employee.user_id == user.id)
        else:
            # Admin (master) OR unauthed (reachable only with
            # ALLOW_ANONYMOUS_ADMIN=1): every owner's roster, minus the
            # system Automation sentinel (user_id IS NULL).
            stmt = stmt.where(Employee.user_id.isnot(None))
        rows = (await s.execute(stmt)).scalars().all()
        access: dict[int, list[str | None]] = {}
        if rows:
            for employee_id, account_id in (await s.execute(
                select(EmployeeAccountAccess.employee_id, EmployeeAccountAccess.account_id)
                .where(EmployeeAccountAccess.employee_id.in_([e.id for e in rows]))
                .order_by(EmployeeAccountAccess.account_id)
            )).all():
                access.setdefault(employee_id, []).append(account_id)
        logins = await _login_facts(s, [e for e in rows if is_login(e)])
        out = []
        for e in rows:
            # kind: "owner" — the Agency owner's own row (what an Owner session
            # is credited as); "login" — an Employee with their own login;
            # "name" — a legacy name-only row from the retired "Who's chatting?"
            # picker, kept so history still resolves a name.
            kind = "login" if is_login(e) else "owner" if e.chatter_id else "name"
            row = {
                "id": e.id,
                "display_name": e.display_name,
                "color": e.color,
                "is_active": e.is_active,
                "chatter_id": e.chatter_id if kind == "login" else None,
                "kind": kind,
                "user_id": e.user_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "account_ids": _creator_access(access.get(e.id, [])),
                "group_id": e.group_id,
            }
            if kind == "login":
                facts = logins.get((e.chatter_id, e.user_id), LoginFacts())
                # An Employee with a login: Activated means linked to this Agency, and the
                # Creator access is the enforced one (empty allowlist = every Creator).
                # `last_login_at` is the login's latest sign-in or request (the session
                # middleware's ~5-minute `last_seen_at`), `two_factor` whether 2FA is on.
                row["username"] = facts.username
                row["last_login_at"] = (facts.last_seen.isoformat() + "Z") if facts.last_seen else None
                row["two_factor"] = facts.two_factor
                row["is_active"] = bool(e.is_active and facts.linked)
                row["account_ids"] = list(facts.allowed) or None
                if not include_disabled and not row["is_active"]:
                    continue
            out.append(row)
        return {"employees": out}


async def _ensure_login_mirrors(owner_user_id: str) -> None:
    """Give every login linked to this Agency its Employee row now, not on its
    first action, so an invited or linked Employee is listed (Manage employees,
    Role Settings, the Shift schedule) before they have done anything."""
    async with get_session() as s:
        missing = (await s.execute(
            select(Chatter.id, Chatter.username, Chatter.display_name, Chatter.color)
            .join(ChatterUser, ChatterUser.chatter_id == Chatter.id)
            .where(ChatterUser.user_id == owner_user_id)
            .where(~select(Employee.id).where(
                Employee.chatter_id == Chatter.id, Employee.user_id == owner_user_id,
            ).exists())
        )).all()
    for cid, username, display_name, color in missing:
        await get_or_create_mirror_employee(
            cid, owner_user_id, display_name=display_name or username, color=color,
        )


class LoginFacts(NamedTuple):
    """What the Employees list shows of an Employee's login at one Agency; the
    defaults are a login that is gone."""
    username: str | None = None
    linked: bool = False  # linked to that Agency
    allowed: tuple[str, ...] = ()  # the enforced Creator allowlist (empty = every Creator)
    last_seen: datetime | None = None
    two_factor: bool = False


async def _login_facts(s, mirrors: list) -> dict[tuple[str, str], LoginFacts]:
    """(chatter_id, owner) -> that login's LoginFacts."""
    if not mirrors:
        return {}
    chatter_ids = list({e.chatter_id for e in mirrors})
    by_login = {cid: (username, last_seen, bool(secret)) for cid, username, last_seen, secret in (await s.execute(
        select(Chatter.id, Chatter.username, Chatter.last_seen_at, Chatter.totp_secret)
        .where(Chatter.id.in_(chatter_ids))
    )).all()}
    links = set((await s.execute(
        select(ChatterUser.chatter_id, ChatterUser.user_id).where(ChatterUser.chatter_id.in_(chatter_ids))
    )).all())
    allowed: dict[tuple[str, str], list[str]] = {}
    for cid, uid, aid in (await s.execute(
        select(ChatterAccountAccess.chatter_id, ChatterAccountAccess.user_id, ChatterAccountAccess.account_id)
        .where(ChatterAccountAccess.chatter_id.in_(chatter_ids))
        .order_by(ChatterAccountAccess.account_id)
    )).all():
        allowed.setdefault((cid, uid), []).append(aid)
    out: dict[tuple[str, str], LoginFacts] = {}
    for e in mirrors:
        key = (e.chatter_id, e.user_id)
        username, last_seen, two_factor = by_login.get(e.chatter_id, (None, None, False))
        out[key] = LoginFacts(username, key in links, tuple(allowed.get(key, ())), last_seen, two_factor)
    return out


def _creator_access(ids: list[str | None]) -> list[str] | None:
    """An Employee's Creator access as the list reports it: None when the
    wildcard row grants every Creator, else the granted Creator ids ([] for
    none), as `/admin/employees/{id}/access` stores them."""
    return None if None in ids else [i for i in ids if i is not None]


@router.post("/admin/employees")
async def create_employee(body: _EmployeeCreateBody = Body(...)) -> dict[str, Any]:
    """Create one, owned by the signed-in friend. No de-dupe on
    display_name — Tim and Tim coexist if you want them to. The picker
    disambiguates by id."""
    user = get_request_user()
    async with get_session() as s:
        # Quota gate — applies only to authed friends. Unauthed callers
        # (legacy curl flows / Automation tooling) are exempt because they
        # can't be one bad actor in a multi-tenant deploy.
        if user is not None and MAX_EMPLOYEES_PER_USER > 0:
            active_count = (await s.execute(
                select(func.count(Employee.id)).where(
                    Employee.user_id == user.id,
                    Employee.is_active == True,  # noqa: E712
                )
            )).scalar_one()
            if active_count >= MAX_EMPLOYEES_PER_USER:
                raise _employee_limit(active_count, (
                    f"employee cap reached ({active_count}/{MAX_EMPLOYEES_PER_USER}). "
                    f"Disable an existing chatter or ask the founder to raise "
                    f"MAX_EMPLOYEES_PER_USER on the relay."
                ))
        # Cycle colors when caller didn't pick one. We use the count of
        # the SIGNED-IN USER's existing employees (or all if unauthed),
        # so each user's palette is independent.
        if not body.color:
            base_q = select(Employee)
            if user is not None:
                base_q = base_q.where(Employee.user_id == user.id)
            count = (await s.execute(base_q)).scalars().all()
            body_color = _DEFAULT_COLORS[len(count) % len(_DEFAULT_COLORS)]
        else:
            body_color = _normalize_color(body.color)

        e = Employee(
            display_name=body.display_name.strip(),
            color=body_color,
            is_active=body.is_active,
            user_id=user.id if user is not None else None,
        )
        s.add(e)
        await s.flush()
        return {
            "id": e.id,
            "display_name": e.display_name,
            "color": e.color,
            "is_active": e.is_active,
        }


@router.patch("/admin/employees/{employee_id}")
async def update_employee(
    employee_id: int, body: _EmployeeUpdateBody = Body(...)
) -> dict[str, Any]:
    """Rename, recolor, or toggle active. Empty body = no-op."""
    async with get_session() as s:
        e = await _load_owned_employee(s, employee_id)
        # Re-enabling a disabled chatter is functionally the same as
        # creating one — enforce the same quota so a user can't dodge it
        # by toggling is_active.
        if (
            body.is_active is True
            and e.is_active is False
            and e.user_id
            and MAX_EMPLOYEES_PER_USER > 0
        ):
            active_count = (await s.execute(
                select(func.count(Employee.id)).where(
                    Employee.user_id == e.user_id,
                    Employee.is_active == True,  # noqa: E712
                )
            )).scalar_one()
            if active_count >= MAX_EMPLOYEES_PER_USER:
                raise _employee_limit(active_count, (
                    f"cannot re-enable: employee cap reached "
                    f"({active_count}/{MAX_EMPLOYEES_PER_USER})."
                ))
        if body.display_name is not None:
            e.display_name = body.display_name.strip()
        if body.color is not None:
            e.color = _normalize_color(body.color)
        if body.is_active is not None:
            e.is_active = body.is_active
            if not body.is_active:
                _refuse_owner_row(e, "deactivated")
                await _unlink_login(s, e)
            if body.is_active and is_login(e) and e.user_id:
                await _relink_login(s, e)
        return {
            "id": e.id,
            "display_name": e.display_name,
            "color": e.color,
            "is_active": e.is_active,
        }


@router.get("/admin/employees/{employee_id}/access")
async def list_employee_access(employee_id: int) -> dict[str, Any]:
    """Which accounts this employee can touch. `account_ids` may contain
    `None` — that's the wildcard "every account" row from §1 of 04. The UI
    surfaces it as an "all accounts" toggle and treats it as exclusive of
    any explicit ids."""
    async with get_session() as s:
        await _load_owned_employee(s, employee_id)
        rows = (await s.execute(
            select(EmployeeAccountAccess.account_id)
            .where(EmployeeAccountAccess.employee_id == employee_id)
        )).all()
        ids = [r[0] for r in rows]
        return {
            "employee_id": employee_id,
            "account_ids": ids,
            "wildcard": None in ids,
        }


class _EmployeeAccessBody(BaseModel):
    account_ids: list[str | None] = Field(
        default_factory=list,
        description="Account ids to grant. Include `null` for the wildcard.",
    )
    wildcard: bool | None = Field(
        None,
        description="If true, replaces the list with a single NULL (all-accounts) row.",
    )


@router.put("/admin/employees/{employee_id}/access")
async def set_employee_access(
    employee_id: int, body: _EmployeeAccessBody = Body(...)
) -> dict[str, Any]:
    """Replace the full access set in one shot. Idempotent. We delete +
    re-insert rather than diff because the table is tiny (one row per
    granted account) and atomic replacement makes the intent obvious in
    the audit log."""
    async with get_session() as s:
        e = await _load_owned_employee(s, employee_id)
        _refuse_owner_row(e, "limited to some Creators")
        if is_login(e):
            return await _set_login_access(s, e, body)

        if body.wildcard:
            target: list[str | None] = [None]
        else:
            # De-dupe while preserving the wildcard sentinel.
            seen: set[str | None] = set()
            target = []
            for a in body.account_ids:
                key = a if a else None
                if key in seen:
                    continue
                seen.add(key)
                target.append(key)

        await s.execute(
            delete(EmployeeAccountAccess).where(
                EmployeeAccountAccess.employee_id == employee_id
            )
        )
        for aid in target:
            s.add(EmployeeAccountAccess(employee_id=employee_id, account_id=aid))
        await s.flush()
        return {
            "employee_id": employee_id,
            "account_ids": target,
            "wildcard": None in target,
        }


@router.delete("/admin/employees/{employee_id}")
async def delete_employee(employee_id: int) -> dict[str, Any]:
    """SOFT delete — sets `is_active=false`. We never hard-delete because
    `actions.employee_id` keeps pointing at this row and we want the audit
    history readable. To truly remove, edit the SQL by hand."""
    async with get_session() as s:
        e = await _load_owned_employee(s, employee_id)
        _refuse_owner_row(e, "deleted")
        e.is_active = False
        await _unlink_login(s, e)
        return {"ok": True, "id": employee_id, "is_active": False}


async def _unlink_login(s, e: Employee) -> None:
    """An Employee with a login is deactivated by unlinking it from this
    Agency: the session can no longer act here (same as the old Unlink).
    `_relink_login` undoes it."""
    if not (is_login(e) and e.user_id):
        return
    await s.execute(delete(ChatterUser).where(
        ChatterUser.chatter_id == e.chatter_id, ChatterUser.user_id == e.user_id,
    ))
    events.on_commit(s, "assignment_changed", agency=e.user_id)
    # No Agency left: every session of that login signs out now, and its
    # next sign-in is told it is deactivated (account_security.ACCOUNT_DEACTIVATED).
    await revoke_if_unlinked(s, e.chatter_id)


def _refuse_owner_row(e: Employee, what: str) -> None:
    """The Owner row is the Agency owner themself, not an Employee to manage."""
    if e.chatter_id and not is_login(e):
        raise HTTPException(status_code=400, detail=f"the owner can't be {what}")


async def _relink_login(s, e: Employee) -> None:
    """Re-activating an Employee with a login links it to this Agency again."""
    chatter = await s.get(Chatter, e.chatter_id)
    if chatter is None:
        raise HTTPException(status_code=409, detail="this employee's login no longer exists")
    await link_login(s, chatter, e.user_id)


async def _set_login_access(s, e: Employee, body: "_EmployeeAccessBody") -> dict[str, Any]:
    """Creator access for an Employee with a login is the enforced allowlist
    (`chatter_account_access`, per Agency), where no rows means every Creator.
    So the wildcard clears it, and an empty set is refused rather than stored:
    it would read back as every Creator. Removing all access is Deactivate."""
    wildcard = bool(body.wildcard) or any(not a for a in body.account_ids)
    ids = sorted({a for a in body.account_ids if a})
    if not wildcard and not ids:
        raise HTTPException(
            status_code=400,
            detail="an employee needs at least one Creator; deactivate them to remove all access",
        )
    if not wildcard:
        owned = set((await s.execute(
            select(UserAccount.account_id).where(UserAccount.user_id == e.user_id)
        )).scalars().all())
        foreign = [a for a in ids if a not in owned]
        if foreign:
            raise HTTPException(status_code=403, detail=f"account {foreign[0]!r} is not one of yours")
    await s.execute(delete(ChatterAccountAccess).where(
        ChatterAccountAccess.chatter_id == e.chatter_id, ChatterAccountAccess.user_id == e.user_id,
    ))
    if not wildcard:
        for aid in ids:
            s.add(ChatterAccountAccess(
                chatter_id=e.chatter_id, user_id=e.user_id, account_id=aid, created_at=datetime.utcnow(),
            ))
    await s.flush()
    events.on_commit(s, "assignment_changed", agency=e.user_id)
    return {"employee_id": e.id, "account_ids": [None] if wildcard else ids, "wildcard": wildcard}


# ── Employee setup: role, Creators, group (Add / Edit employee) ──────
#
# One shape for every way an Employee arrives or is edited: the owner creating
# the login outright, an invite (stored on the invite, applied when it is
# accepted), linking an existing login by username, and the Edit modal.
# Present keys are applied; absent ones are left alone.
#   display_name  the name this Agency shows
#   role_id       a role in the Agency's `roles` blob, or a built-in but Owner (settings_schema); null/"" = the
#                 built-in Chatter (a login always holds a role; settings_api.DEFAULT_LOGIN_ROLE)
#   account_ids   the Creators they may work; null or [] = every Creator
#   group_id      their Employee group; null = none

SETUP_KEYS = ("display_name", "role_id", "account_ids", "group_id")


class EmployeeSetup(BaseModel):
    display_name: str | None = Field(None, max_length=64)
    role_id: str | None = Field(None, max_length=64)
    account_ids: list[str] | None = None
    group_id: int | None = None

    def given(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in SETUP_KEYS if k in self.model_fields_set}


async def _held_role_ids(owner_id: str) -> set[str]:
    from settings_api import _read_blob, ensure_role_presets  # lazy: settings_api imports this module
    await ensure_role_presets(owner_id)
    async with get_session() as s:
        blob = await _read_blob(s, owner_id, "roles")
    roles = blob.get("roles") if isinstance(blob.get("roles"), list) else []
    return {r["id"] for r in roles if isinstance(r, dict) and isinstance(r.get("id"), str)} | (BUILT_IN_ROLE_IDS - {"owner"})


async def validate_employee_setup(owner_id: str, setup: dict[str, Any]) -> dict[str, Any]:
    """`setup` checked against the Agency (400/403/404 on a role, Creator or
    group it does not hold) and normalised; safe to store and apply later."""
    out = dict(setup)
    if "display_name" in out:
        out["display_name"] = (out["display_name"] or "").strip()[:64] or None
    if out.get("role_id"):
        if out["role_id"] not in await _held_role_ids(owner_id):
            raise HTTPException(status_code=400, detail=f"no role {out['role_id']!r} in your Role Settings")
    elif "role_id" in out:
        out["role_id"] = None
    async with get_session() as s:
        if out.get("account_ids"):
            ids = sorted(set(out["account_ids"]))
            owned = set((await s.execute(
                select(UserAccount.account_id).where(UserAccount.user_id == owner_id)
            )).scalars().all())
            foreign = [a for a in ids if a not in owned]
            if foreign:
                raise HTTPException(status_code=403, detail=f"account {foreign[0]!r} is not one of yours")
            out["account_ids"] = ids
        elif "account_ids" in out:
            out["account_ids"] = None
        if out.get("group_id") is not None:
            g = await s.get(EmployeeGroup, out["group_id"])
            if g is None or g.agency_user_id != owner_id:
                raise HTTPException(status_code=404, detail="no such employee group")
    return out


async def apply_employee_setup(owner_id: str, employee_id: int, setup: dict[str, Any]) -> None:
    """Apply a validated setup to one of the Agency's Employees."""
    async with get_session() as s:
        e = await s.get(Employee, employee_id)
        if e is None or e.user_id != owner_id:
            raise HTTPException(status_code=404, detail="employee not found")
        if setup.get("display_name"):
            e.display_name = setup["display_name"]
        if "group_id" in setup:
            e.group_id = setup["group_id"]
        if "account_ids" in setup and is_login(e):
            await s.execute(delete(ChatterAccountAccess).where(
                ChatterAccountAccess.chatter_id == e.chatter_id, ChatterAccountAccess.user_id == owner_id,
            ))
            for aid in setup["account_ids"] or []:
                s.add(ChatterAccountAccess(
                    chatter_id=e.chatter_id, user_id=owner_id, account_id=aid, created_at=datetime.utcnow(),
                ))
            events.on_commit(s, "assignment_changed", agency=owner_id)
    if "role_id" in setup:
        from settings_api import _read_blob, _write_blob
        async with get_session() as s:
            blob = await _read_blob(s, owner_id, "roles")
            assignments = dict(blob.get("assignments") or {})
            # No role is not an option: none given is the default role (settings_api.DEFAULT_LOGIN_ROLE).
            assignments[str(employee_id)] = setup["role_id"] or "chatter"
            await _write_blob(s, owner_id, "roles", {"version": 1, **blob, "assignments": assignments})
            events.on_commit(s, "permissions_changed", agency=owner_id)


async def setup_login_employee(owner_id: str, chatter_id: str, setup: dict[str, Any]) -> int | None:
    """The login's Employee row in this Agency, made now, with `setup` applied."""
    async with get_session() as s:
        c = await s.get(Chatter, chatter_id)
    if c is None:
        return None
    emp_id = await get_or_create_mirror_employee(
        chatter_id, owner_id, display_name=setup.get("display_name") or c.display_name or c.username,
        color=c.color,
    )
    if emp_id is not None and setup:
        await apply_employee_setup(owner_id, emp_id, setup)
    if emp_id is not None:
        # An existing row (a login linked again) may hold no role: it gets the default one.
        from settings_api import give_role_to_unroled
        await give_role_to_unroled(owner_id, [emp_id])
    return emp_id


def _owner_or_403():
    user = get_request_user()
    if user is None:
        raise HTTPException(status_code=403, detail="sign in as the agency owner")
    return user


class _CreateLoginBody(EmployeeSetup):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


@router.post("/admin/employees/login")
async def create_employee_login(body: _CreateLoginBody = Body(...)) -> dict[str, Any]:
    """Add employee, the Infloww way: the owner makes the login (username +
    password) and hands it over; it is linked to this Agency at once with its
    role, Creators and group. Owner-only (chatters are refused at the gate)."""
    from auth import _normalize_username, _validate_password, _validate_username
    user = _owner_or_403()
    username = _normalize_username(body.username)
    _validate_username(username)
    _validate_password(body.password)
    setup = await validate_employee_setup(user.id, body.given())
    now = datetime.utcnow()
    import uuid
    cid = uuid.uuid4().hex
    from sqlalchemy.exc import IntegrityError
    async with get_session() as s:
        s.add(Chatter(
            id=cid, username=username, password=body.password,  # plaintext, as every login here
            display_name=setup.get("display_name"), created_at=now, last_seen_at=now,
        ))
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="username already taken")
        s.add(ChatterUser(chatter_id=cid, user_id=user.id, created_at=now))
    emp_id = await setup_login_employee(user.id, cid, setup)
    return {"ok": True, "employee_id": emp_id, "chatter_id": cid, "username": username}


@router.put("/admin/employees/{employee_id}/setup")
async def put_employee_setup(employee_id: int, body: EmployeeSetup = Body(...)) -> dict[str, Any]:
    """Edit employee: name, role, Creators and group in one save."""
    user = _owner_or_403()
    async with get_session() as s:
        e = await _load_owned_employee(s, employee_id)
        _refuse_owner_row(e, "edited here")
        owner_id = e.user_id
    setup = await validate_employee_setup(owner_id, body.given())
    await apply_employee_setup(owner_id, employee_id, setup)
    return {"ok": True, "employee_id": employee_id, **setup}


class _PasswordBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


async def _sole_agency_login(s, employee_id: int, what: str) -> Chatter:
    """The login of this owner's Employee, refused when it also works for another
    Agency: its credentials are not this owner's to reset, or a login they linked
    without asking would hand them another Agency's employee (or weaken that
    Agency's 2FA)."""
    e = await _load_owned_employee(s, employee_id)
    if not is_login(e):
        raise HTTPException(status_code=400, detail="this employee has no login")
    links = set((await s.execute(
        select(ChatterUser.user_id).where(ChatterUser.chatter_id == e.chatter_id)
    )).scalars().all())
    if e.user_id not in links:
        raise HTTPException(status_code=409, detail=f"activate this employee before resetting their {what}")
    if links - {e.user_id}:
        raise HTTPException(
            status_code=409,
            detail=f"this login also works for another agency, so only they can reset its {what}",
        )
    c = await s.get(Chatter, e.chatter_id)
    if c is None:
        raise HTTPException(status_code=409, detail="this employee's login no longer exists")
    return c


@router.post("/admin/employees/{employee_id}/password")
async def reset_employee_password(employee_id: int, body: _PasswordBody = Body(...)) -> dict[str, Any]:
    """Reset password: the owner sets a new password on an Employee's login.
    Owner-only (a chatter session is refused at the gate). Refused when the
    login also works for another Agency (`_sole_agency_login`). Every session
    of the login signs out."""
    from auth import _validate_password
    _owner_or_403()
    _validate_password(body.password)
    async with get_session() as s:
        c = await _sole_agency_login(s, employee_id, "password")
        c.password = body.password
        await revoke_sessions(s, "chatter", c.id)
    return {"ok": True, "employee_id": employee_id}


@router.post("/admin/employees/{employee_id}/2fa/reset")
async def reset_employee_two_factor(employee_id: int) -> dict[str, Any]:
    """Reset 2FA (Security (organization)): 2FA off on an Employee's login, who
    is signed out everywhere and sets it up again at the next sign-in when the
    Agency requires it (Infloww's employee_relogin_two_factor). Owner-only,
    refused like Reset password for a login another Agency shares."""
    _owner_or_403()
    async with get_session() as s:
        c = await _sole_agency_login(s, employee_id, "two-factor authentication")
        for key, value in clear_two_factor_values().items():
            setattr(c, key, value)
        await revoke_sessions(s, "chatter", c.id)
    return {"ok": True, "employee_id": employee_id}


# ── Audit log read endpoint ─────────────────────────────────────────

@router.get("/admin/audit")
async def list_audit(
    employee_id: int | None = Query(None),
    account_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
) -> dict[str, Any]:
    """Paginated `actions` rows, filterable by employee + account and by
    time: `from` (inclusive) and `to` (exclusive), each an ISO datetime (a
    zone offset or Z is converted to UTC) or a date (a `to` date includes
    that whole UTC day); 422 when unreadable. Each row carries `label`, the
    action's name for people (audit_labels.action_label), or null.

    Scoped to the signed-in friend: only actions whose `account_id` is in
    their `user_accounts` set OR whose `employee_id` is one they own.
    Filter parameters (`employee_id`, `account_id`) are intersected with
    that scope — they can never widen it. A master (is_admin) and unauthed
    callers see everything (master oversight / back-compat for internal curl
    flows); the optional `employee_id`/`account_id` filters still apply.
    """
    user = get_request_user()
    async with get_session() as s:
        stmt = select(Action).order_by(desc(Action.at)).limit(limit).offset(offset)
        if from_ is not None:
            stmt = stmt.where(Action.at >= _audit_bound(from_, "from"))
        if to is not None:
            stmt = stmt.where(Action.at < _audit_bound(to, "to"))
        if user is not None and not user.is_admin:
            owned_emp_ids = (await s.execute(
                select(Employee.id).where(Employee.user_id == user.id)
            )).scalars().all()
            owned_emp_set = set(owned_emp_ids)
            conditions = []
            if user.account_ids:
                conditions.append(Action.account_id.in_(list(user.account_ids)))
            if owned_emp_set:
                conditions.append(Action.employee_id.in_(list(owned_emp_set)))
            if not conditions:
                return {"actions": [], "limit": limit, "offset": offset}
            from sqlalchemy import or_
            stmt = stmt.where(or_(*conditions))
            if employee_id is not None:
                if employee_id not in owned_emp_set:
                    return {"actions": [], "limit": limit, "offset": offset}
                stmt = stmt.where(Action.employee_id == employee_id)
            if account_id is not None:
                if account_id not in user.account_ids:
                    return {"actions": [], "limit": limit, "offset": offset}
                stmt = stmt.where(Action.account_id == account_id)
        else:
            if employee_id is not None:
                stmt = stmt.where(Action.employee_id == employee_id)
            if account_id is not None:
                stmt = stmt.where(Action.account_id == account_id)
        rows = (await s.execute(stmt)).scalars().all()
        return {
            "actions": [
                {
                    "id": a.id,
                    "employee_id": a.employee_id,
                    "account_id": a.account_id,
                    "action": a.action,
                    "label": audit_labels.action_label(a.action),
                    "target_type": a.target_type,
                    "target_id": a.target_id,
                    "payload": _safe_loads(a.payload_json),
                    "at": a.at.isoformat() if a.at else None,
                }
                for a in rows
            ],
            "limit": limit,
            "offset": offset,
        }


def _audit_bound(value: str, name: str) -> datetime:
    """`/admin/audit`'s `from` / `to` as naive UTC; a date-only `to` is the
    next day's midnight, so the day it names is included."""
    try:
        if len(value) == 10:
            day = datetime.fromisoformat(value)
            return day + timedelta(days=1) if name == "to" else day
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name}: expected an ISO date or datetime") from None
    return at.astimezone(timezone.utc).replace(tzinfo=None) if at.tzinfo else at


# ── System "Automation" employee lookup ─────────────────────────────

# Process-local cache of the Automation employee's id. Populated lazily on
# the first call; reused for the lifetime of the process. Skipped under
# pytest because fixtures swap DBs between tests and a cached id from
# the wrong DB would silently misattribute action rows.
_automation_emp_id_cache: int | None = None

# Guard so the middleware logs the "migration 0011 not run" WARNING at most
# once per process — without this, a misconfigured deploy would spam the log
# on every header-less /api/of/* request.
_automation_missing_warned: bool = False

# Guard so the middleware logs the "X-Employee-Id ignored under chatter
# session" WARNING at most once per process — a misconfigured client could
# otherwise spam it on every chatter request.
_chatter_header_ignored_warned: bool = False


def _warn_chatter_header_ignored_once() -> None:
    global _chatter_header_ignored_warned
    if _chatter_header_ignored_warned:
        return
    _chatter_header_ignored_warned = True
    log.warning(
        "X-Employee-Id from chatter client ignored — audit pipeline "
        "auto-resolves (chatter_id, account_owner) → Employee.id."
    )


async def resolve_outbound_employee_id(
    request: Request,
    account_id: str | None,
) -> int | None:
    """Pick the Employee.id that should be stamped on an outbound message.

    Used by the chat-send, mass-send, and queue-create handlers — anywhere
    a write needs `sent_by_employee_id` and the audit-middleware path
    isn't the writer (those handlers explicitly persist a `messages` row
    via service/attribution.py).

    Resolution order:
      1. Owner session — the owner's own Owner row (`get_owner_employee_id`);
         an `X-Employee-Id` naming one of their rows still wins.
      2. Chatter session — header is empty (chatters don't pick); look
         up or lazy-create the per-(chatter, account_owner) mirror
         Employee. Header from a chatter client is dropped (logged once)
         to keep audit attribution single-sourced.
      3. None — caller falls through to its Automation fallback.
    """
    emp_id_raw = request.headers.get("x-employee-id")
    user = get_request_user()
    # Owner session: the owner is the one acting, so the write is theirs
    # (their Owner row) — no "who's chatting" pick. A header naming one of
    # their own rows is still honoured (scripts, older clients); a header
    # naming someone else's row is a spoof and falls back to the owner.
    if user is not None:
        if emp_id_raw and emp_id_raw.isdigit():
            emp_id = int(emp_id_raw)
            async with get_session() as s:
                owned = await s.get(Employee, emp_id)
            # An admin/master sees the full registry, so a cross-owner pick is
            # legitimate (mirrors the is_admin scoping bypass in list_employees).
            if owned is not None and (owned.user_id == user.id or user.is_admin):
                return emp_id
        return await get_owner_employee_id(user)
    # Chatter session: ignore the header (defensive), resolve mirror.
    if user is None:
        from chatters import get_request_chatter as _grc
        chatter = _grc()
        if chatter is not None:
            if emp_id_raw:
                _warn_chatter_header_ignored_once()
            return await resolve_chatter_employee_id(
                chatter_id=chatter.id,
                owner_user_ids=chatter.owner_user_ids,
                account_id=account_id,
                display_name=chatter.display_name or chatter.username,
                color=chatter.color,
            )
    # Unauthed (internal curl / cron) — caller's Automation fallback wins.
    if emp_id_raw and emp_id_raw.isdigit():
        return int(emp_id_raw)
    return None


async def resolve_chatter_employee_id(
    chatter_id: str,
    owner_user_ids: set[str] | frozenset[str],
    account_id: str | None,
    *,
    display_name: str | None,
    color: str | None,
) -> int | None:
    """Pick the Agency that owns `account_id` among the chatter's linked
    owners, then hand off to `get_or_create_mirror_employee`. Returns the
    Employee.id, or None if we can't pin the account to one of the chatter's
    linked owners.

    If more than one linked owner holds the account (cross-grant edge case),
    the alphabetically first owner_id wins, for stable attribution.
    """
    if not account_id:
        log.debug("chatter→emp: no account_id (chatter=%s)", chatter_id)
        return None
    if not owner_user_ids:
        log.warning(
            "chatter→emp: chatter has zero linked owners (chatter=%s) — "
            "register a link via /admin/chatters/link",
            chatter_id,
        )
        return None
    try:
        async with get_session() as s:
            # Which of the chatter's owners actually holds this account?
            holders = await _sorted_holder_owner_ids(s, account_id, owner_user_ids)
            if not holders:
                log.warning(
                    "chatter→emp: no owner in chatter's linked set holds "
                    "account=%s (chatter=%s, owners=%s) — chatter.account_ids "
                    "is inconsistent with user_accounts table",
                    account_id, chatter_id, sorted(owner_user_ids),
                )
                return None
            owner_id = holders[0]
    except Exception:
        log.exception(
            "chatter→emp: resolution failed (chatter=%s account=%s)",
            chatter_id, account_id,
        )
        return None
    return await get_or_create_mirror_employee(
        chatter_id, owner_id, display_name=display_name, color=color,
    )


async def _sorted_holder_owner_ids(
    s, account_id: str, owner_user_ids: set[str] | frozenset[str],
) -> list[str]:
    """The chatter's linked owners that hold `account_id` in
    `user_accounts`, alphabetically sorted (the stable tie-break)."""
    rows = (await s.execute(
        select(UserAccount.user_id).where(
            UserAccount.account_id == account_id,
            UserAccount.user_id.in_(list(owner_user_ids)),
        )
    )).scalars().all()
    return sorted(rows)


OWNER_KEY_PREFIX = "owner:"


def is_login(e: Employee) -> bool:
    """True for an Employee with their own login (a per-(chatter, Agency)
    mirror row) — not the Owner row, not a legacy name-only row."""
    return bool(e.chatter_id) and not e.chatter_id.startswith(OWNER_KEY_PREFIX)


async def get_owner_employee_id(user) -> int | None:
    """The Agency owner's own Employee row, created on first use. Whatever an
    Owner session sends, flags or unsends is credited to it, so the owner
    never has to say "who's chatting" and their sends stay counted (as the
    owner, by username) instead of landing on Automation. Keyed like a mirror
    row (`chatter_id = "owner:<user id>"`) so the same partial unique index
    keeps it to one row per Agency."""
    return await get_or_create_mirror_employee(
        f"{OWNER_KEY_PREFIX}{user.id}", user.id,
        display_name=getattr(user, "username", None) or "Owner", color=None,
    )


async def find_owner_employee_id(s, user) -> int | None:
    """The owner's own Employee row (`get_owner_employee_id`) if it exists
    yet, read in the caller's session without creating it."""
    return (await s.execute(select(Employee.id).where(
        Employee.chatter_id == f"{OWNER_KEY_PREFIX}{user.id}", Employee.user_id == user.id,
    ).order_by(Employee.id).limit(1))).scalar_one_or_none()


async def get_or_create_mirror_employee(
    chatter_id: str,
    owner_user_id: str,
    *,
    display_name: str | None,
    color: str | None,
) -> int | None:
    """Find — or lazily create — the Mirror Employee for this chatter in
    this Agency (`owner_user_id`). Returns the Employee.id, or None when the
    database step fails (logged).

    Uses the classic SELECT → INSERT → catch IntegrityError → SELECT
    upsert pattern (NOT dialect-specific ON CONFLICT). Previously used
    sqlite_insert + on_conflict_do_nothing against the partial unique
    index `uq_employees_chatter_owner`, which only works if that index
    actually exists on the live DB — and on prod boxes that came up via
    `init_db()` / `create_all()` rather than `alembic upgrade head`, the
    partial index isn't always present. Symptom: silent insert failure,
    SELECT-after-insert returns None, attribution lands as NULL, bubble
    shows no "Sent by …" label. This rewrite tolerates the missing
    index AND surfaces every decision point in the relay log.

    Race-safe regardless of index presence: if a sibling request raced
    us to the insert, we get IntegrityError (when the index IS present)
    or a duplicate row (when it isn't — friends-scale, acceptable). On
    IntegrityError we rollback + re-SELECT to capture the sibling's id.
    """
    try:
        async with get_session() as s:
            # Fast path: row already exists.
            existing = (await s.execute(
                select(Employee.id).where(
                    Employee.chatter_id == chatter_id,
                    Employee.user_id == owner_user_id,
                )
            )).scalar_one_or_none()
            if existing is not None:
                return existing

            # Plain INSERT (no dialect-specific ON CONFLICT). Catches
            # IntegrityError from the partial unique index OR from a
            # racing sibling that beat us to the same (chatter, owner)
            # pair — either way the post-rollback SELECT picks up the
            # canonical id.
            from sqlalchemy.exc import IntegrityError
            new_row = Employee(
                display_name=(display_name or "Chatter")[:64],
                color=color,
                is_active=True,
                created_at=datetime.utcnow(),
                user_id=owner_user_id,
                chatter_id=chatter_id,
            )
            s.add(new_row)
            try:
                await s.flush()
                log.info(
                    "chatter→emp: created mirror Employee id=%s "
                    "(chatter=%s owner=%s display=%r)",
                    new_row.id, chatter_id, owner_user_id,
                    new_row.display_name,
                )
                created = new_row.id
            except IntegrityError:
                # Sibling raced us — roll back the failed insert and
                # SELECT to capture the canonical id from the winner.
                await s.rollback()
                existing = (await s.execute(
                    select(Employee.id).where(
                        Employee.chatter_id == chatter_id,
                        Employee.user_id == owner_user_id,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    log.error(
                        "chatter→emp: IntegrityError on insert but no "
                        "matching row found post-rollback (chatter=%s "
                        "owner=%s) — schema may be missing the partial "
                        "unique index uq_employees_chatter_owner",
                        chatter_id, owner_user_id,
                    )
                return existing
        # Committed: a new login joins the Agency holding the default role, never none.
        if not chatter_id.startswith(OWNER_KEY_PREFIX):
            from settings_api import give_role_to_unroled  # lazy: settings_api imports this module
            try:
                await give_role_to_unroled(owner_user_id, [created])
            except Exception:
                log.exception("chatter→emp: Employee id=%s has NO ROLE (default role write failed): "
                              "refused every page until one is assigned", created)
        return created
    except Exception:
        log.exception(
            "chatter→emp: get-or-create failed (chatter=%s owner=%s)",
            chatter_id, owner_user_id,
        )
        return None


@dataclass(frozen=True)
class AgencyContext:
    """Which Agency, which Employee, Owner or Master — for one request,
    from the session alone (docs/spec/phase-01)."""
    agency_user_id: str        # users.id of the Agency
    employee_id: int | None    # Mirror Employee for a Chatter session; None for an Owner session
    is_owner: bool             # True for an Owner session (Master included)
    is_master: bool            # users.is_admin


async def agency_context(*, account_id: str | None = None) -> AgencyContext:
    """The Agency context of the current request, from the session cookies'
    ContextVars and the database only — never from client-supplied input.

    Await it inside a handler. A caller with a Creator in its path, query or
    body passes that id as `account_id`. Refusals, in order: 401 `sign in
    required` with no session (ALLOW_ANONYMOUS_ADMIN does not change this);
    403 `not your account` when `account_id` is not the principal's; 403
    `chatter is not linked to an agency`; 400 `name a creator to choose the
    agency` for a chatter linked to several Agencies who names no Creator.
    503 when the chatter's Mirror Employee cannot be resolved.

    An Owner session (it wins over a chatter cookie in the same browser, as
    in `_actor_account_ids`) is the Agency itself: no Employee, and a named
    Creator never moves it into another Agency — the Master included.
    Impersonation needs no case: the session middleware has already
    overlaid the impersonated owner onto `get_request_user()`.

    A Chatter session acts in one of its linked Agencies, as its own Mirror
    Employee there (created on first use): the only Agency when it has one,
    else the one `_chatter_agency_for_creator` picks for the named Creator.
    """
    user = get_request_user()
    from chatters import get_request_chatter as _grc
    chatter = _grc() if user is None else None
    if user is None and chatter is None:
        raise HTTPException(status_code=401, detail="sign in required")
    assert_account_owned(account_id)
    if user is not None:
        return AgencyContext(
            agency_user_id=user.id,
            employee_id=None,
            is_owner=True,
            is_master=bool(user.is_admin),
        )
    if not chatter.owner_user_ids:
        raise HTTPException(status_code=403, detail="chatter is not linked to an agency")
    if account_id:
        agency_user_id = await _chatter_agency_for_creator(
            chatter.id, chatter.owner_user_ids, account_id,
        )
    elif len(chatter.owner_user_ids) == 1:
        (agency_user_id,) = chatter.owner_user_ids
    else:
        raise HTTPException(status_code=400, detail="name a creator to choose the agency")
    return await _chatter_context(chatter, agency_user_id)


async def _chatter_context(chatter, agency_user_id: str) -> AgencyContext:
    """A Chatter session's context in one linked Agency, as its Mirror
    Employee there (created on first use); 503 when it cannot be resolved."""
    employee_id = await get_or_create_mirror_employee(
        chatter.id, agency_user_id,
        display_name=chatter.display_name or chatter.username,
        color=chatter.color,
    )
    if employee_id is None:
        # ASSUMPTION: the 503 detail is `mirror employee unavailable`; the spec
        # fixes only the status. Overturned if a later Phase's UI needs
        # different wording.
        raise HTTPException(status_code=503, detail="mirror employee unavailable")
    return AgencyContext(
        agency_user_id=agency_user_id,
        employee_id=employee_id,
        is_owner=False,
        is_master=False,
    )


async def owner_context(account_id: str | None, detail: str) -> AgencyContext:
    """`agency_context` for an owner-only endpoint.

    ASSUMPTION: a Chatter session is refused 403 (`detail`) before
    `agency_context` runs, so a chatter linked to two Agencies gets 403 (not
    its 400 "name a creator") and no Mirror Employee is created by an
    endpoint it may not use. Rung 5, the spec's check order (401, then 403).
    Overturned if Phase 4's Permission roles open owner endpoints to some
    chatters.
    """
    if get_request_user() is None:
        from chatters import get_request_chatter as _grc
        if _grc() is not None:
            raise HTTPException(status_code=403, detail=detail)
    return await agency_context(account_id=account_id)


async def agency_contexts(*, account_id: str | None = None) -> list[AgencyContext]:
    """Every Agency context the current request acts in: `agency_context`'s
    one, except for a chatter linked to several Agencies that names no
    Creator, which gets one per linked Agency (in Agency id order) instead of
    the 400 — for reads that combine them (docs/spec/phase-04, the Applied
    settings read and Role enforcement). Same refusals and 503 otherwise.
    """
    if not account_id and get_request_user() is None:
        from chatters import get_request_chatter as _grc
        chatter = _grc()
        if chatter is not None and len(chatter.owner_user_ids) > 1:
            return [await _chatter_context(chatter, agency_user_id)
                    for agency_user_id in sorted(chatter.owner_user_ids)]
    return [await agency_context(account_id=account_id)]


async def json_object(request: Request, status_code: int) -> dict[str, Any]:
    """The request body as a JSON object, else `status_code` "expected a
    JSON object"."""
    try:
        body = json.loads(await request.body())
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=status_code, detail="expected a JSON object")
    return body


async def _chatter_agency_for_creator(
    chatter_id: str,
    owner_user_ids: set[str] | frozenset[str],
    account_id: str,
) -> str:
    """The Agency a chatter acts in for a Creator it named (and that already
    passed `assert_account_owned`): the alphabetically first linked owner
    that holds the Creator in `user_accounts` and whose Chatter Access
    allowlist for this chatter does not exclude it.

    Unlike `resolve_chatter_employee_id`'s unfiltered tie-break, the
    allowlist applies first, so a cross-granted Creator allowed only under
    the later Agency resolves there (docs/spec/phase-01, Resolution rules).
    """
    from chatters import _account_restrictions_for, _filter_owner_accounts
    async with get_session() as s:
        holders = await _sorted_holder_owner_ids(s, account_id, owner_user_ids)
        restrictions = await _account_restrictions_for(s, chatter_id)
    allowed = [
        uid for uid in holders
        if _filter_owner_accounts([(uid, account_id)], restrictions)
    ]
    if not allowed:
        # ASSUMPTION: no allowed holder despite `assert_account_owned`
        # passing (links or allowlist changed between the session load and
        # this read) is refused as `not your account`, not a 5xx. Overturned
        # if the owner wants such races surfaced as server errors.
        raise HTTPException(status_code=403, detail="not your account")
    return allowed[0]


def _warn_automation_missing_once() -> None:
    global _automation_missing_warned
    if _automation_missing_warned:
        return
    _automation_missing_warned = True
    log.warning("Automation fallback unavailable — migration 0011 not run.")


async def get_automation_employee_id() -> int:
    """Returns the id of the system Automation employee row.

    No caching when running under pytest (detected via
    'PYTEST_CURRENT_TEST' in os.environ) — fixtures may swap DBs.
    Otherwise cached after first lookup.

    Raises LookupError if the row doesn't exist (migration 0011 hasn't
    run). Callers should catch this and degrade gracefully (e.g.
    write NULL instead of crashing the request).
    """
    global _automation_emp_id_cache
    in_test = "PYTEST_CURRENT_TEST" in os.environ
    if _automation_emp_id_cache is not None and not in_test:
        return _automation_emp_id_cache
    async with get_session() as s:
        row = (await s.execute(
            select(Employee.id).where(
                Employee.display_name == "Automation",
                Employee.is_active == False,  # noqa: E712 — SQL equality, not Python is-comparison
            )
        )).scalar_one_or_none()
    if row is None:
        raise LookupError(
            "Automation employee not found. Migration 0011 must run before "
            "this helper. Caller should handle this gracefully."
        )
    if not in_test:
        _automation_emp_id_cache = row
    return row


# ── Audit middleware ────────────────────────────────────────────────

# Endpoints we DON'T audit even when they're "POST/PATCH/DELETE." Adding
# a row for every health probe / SSE retry would drown the real signal.
_AUDIT_SKIP_PREFIXES = (
    "/health",
    "/events",
    "/ws/",
    "/admin/audit",     # don't audit reads of the audit log itself
    "/admin/rev/",       # drift probe — read-only
    "/docs",
    "/openapi.json",
    "/app/",             # static UI
    "/admin/shifts/clock-heartbeat",  # the clocked-in tab's renew, every 30-60 s of activity
    "/admin/agency-notifications",    # marking a notification read
)
# Note: do NOT include "/" here — every absolute path starts with "/", so
# `startswith("/")` would silently skip every endpoint. The root path is
# handled by the static-UI mount which only serves GET anyway.

# The app's own background writes, as (method, path prefix): audited like any
# write, under the session's Employee, but no sign of anyone at work. Perf-log
# flushes (every 10 s while requests run, app/lib/perfLog.ts) and error
# reports (app/lib/errorReporter.ts). The Auto clock-out sweep leaves them out
# of an Employee's activity (clock_api._auto_clock_out).
BACKGROUND_WRITES = (("POST", "/admin/perflog/"), ("POST", "/admin/errors"))


def audit_action(method: str, path: str) -> str:
    """The generic audit row's `actions.action`: "METHOD path"."""
    return f"{method} {path}"


async def audit_middleware(request: Request, call_next):
    """FastAPI HTTP middleware. Wraps every request so:
      • if method is mutating (POST / PATCH / PUT / DELETE) and the
        response is 2xx, we log a row to `actions`.
      • employee_id comes from the `X-Employee-Id` header (NULL if absent).
      • payload_json captures a truncated snapshot of the body for replay.

    Failure isolation: every step is try/except + log. A bad audit write
    never affects the actual response the user sees.
    """
    # Snapshot enough to log BEFORE call_next so a failed downstream still
    # gets recorded (with status_code set in the post-block).
    method = request.method
    path = request.url.path
    should_audit = (
        method in ("POST", "PATCH", "PUT", "DELETE")
        and not any(path.startswith(p) for p in _AUDIT_SKIP_PREFIXES)
    )

    # Reading the body consumes it; we have to re-inject for the handler.
    body_bytes = b""
    binary_payload_snapshot: str | None = None
    if should_audit:
        # Skip buffering binary uploads — a 30MB image would otherwise sit in
        # RSS for the lifetime of the request just so we can snapshot it.
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("multipart/", "application/octet-stream")):
            binary_payload_snapshot = (
                f"<binary upload, {request.headers.get('content-length', '?')} bytes>"
            )
        else:
            try:
                body_bytes = await request.body()
            except Exception:
                body_bytes = b""

            # Reinject so downstream handlers (Pydantic body parsers) can still
            # read it. FastAPI's request._body cache makes this stick.
            async def _receive() -> dict:
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            request._receive = _receive  # type: ignore[attr-defined]

    notice_step = await notifications_api.audit_snapshot(method, path) if should_audit else None
    response = await call_next(request)

    if should_audit and 200 <= response.status_code < 300:
        try:
            emp_id_raw = request.headers.get("x-employee-id")
            emp_id: int | None = None
            if emp_id_raw and emp_id_raw.isdigit():
                emp_id = int(emp_id_raw)
            account_id = (
                request.headers.get("x-account-id")
                or request.query_params.get("account_id")
            )
            user = get_request_user()
            # Chatter principal: the X-Employee-Id header is meaningless
            # (the chatter doesn't pick from /admin/employees and we want
            # one canonical per-owner mirror Employee anyway). Drop it
            # outright, then auto-resolve (chatter, account.owner_id) →
            # Employee, materialising the row on first hit. The User
            # cookie takes precedence — if a founder happens to be both
            # owner-signed-in AND chatter-signed-in (testing on the same
            # browser), the request still attributes to their User-owned
            # Employee via the existing spoof guard below.
            if user is None:
                # Lazy import: chatters imports employees indirectly via
                # the audit middleware path, so deferring keeps boot
                # order one-way (chatters → auth → employees).
                from chatters import get_request_chatter as _grc
                chatter = _grc()
                if chatter is not None:
                    if emp_id is not None:
                        _warn_chatter_header_ignored_once()
                        emp_id = None
                    emp_id = await resolve_chatter_employee_id(
                        chatter_id=chatter.id,
                        owner_user_ids=chatter.owner_user_ids,
                        account_id=account_id,
                        display_name=chatter.display_name or chatter.username,
                        color=chatter.color,
                    )
            # Cross-user spoof guard: if a signed-in friend passes an
            # X-Employee-Id, the chatter MUST belong to them. Otherwise
            # drop the attribution to NULL (or Automation downstream for
            # /api/of/* paths). Stops friend A from writing actions under
            # friend B's chatter.
            if emp_id is not None and user is not None:
                async with get_session() as _vs:
                    owned = await _vs.get(Employee, emp_id)
                # Admins/master may act as ANY existing employee (full-registry
                # scope); a non-admin friend may only use their own employees.
                if owned is None or (owned.user_id != user.id and not user.is_admin):
                    log.warning(
                        "x-employee-id=%s rejected: not owned by user=%s (path=%s)",
                        emp_id, user.id, path,
                    )
                    emp_id = None
            # Owner session with no (valid) pick: the owner did it.
            if emp_id is None and user is not None:
                emp_id = await get_owner_employee_id(user)
            # Header-less fallback for OF proxy paths only. When no human
            # pressed send (mass-message, scheduled jobs, automation that
            # happens to round-trip through HTTP), we attribute to the
            # system Automation employee so the row doesn't disappear from
            # per-employee stats.
            #
            # NOTE: in-process automation runners (subprocess.run /
            # direct function calls in service/automations/runners.py) do
            # NOT pass through this middleware. They must write their own
            # audit + attribution explicitly. This fallback only catches
            # the rare HTTP-routed automation case.
            #
            # /admin/* paths are intentionally NOT covered — a missing
            # X-Employee-Id there indicates a misconfigured client and
            # should stay NULL so it surfaces in the audit log.
            if emp_id is None and path.startswith("/api/of/"):
                try:
                    emp_id = await get_automation_employee_id()
                except LookupError:
                    _warn_automation_missing_once()
            await _write_action(
                employee_id=emp_id,
                account_id=account_id,
                action=audit_action(method, path),
                payload_json=binary_payload_snapshot if binary_payload_snapshot is not None else _safe_snapshot(body_bytes),
                target_type=None,
                target_id=_extract_target_id(path),
            )
            if notice_step is not None:
                await notice_step(body_bytes, emp_id, account_id)
        except Exception:
            log.exception("audit write failed (path=%s)", path)

    return response


async def _write_action(
    *, employee_id: int | None, account_id: str | None,
    action: str, payload_json: str | None,
    target_type: str | None, target_id: str | None,
) -> None:
    async with get_session() as s:
        s.add(Action(
            employee_id=employee_id,
            account_id=account_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_json=payload_json,
            at=datetime.utcnow(),
        ))


def _safe_snapshot(body_bytes: bytes) -> str | None:
    """Best-effort string snapshot of the request body for the audit log.
    JSON: pretty-print up to 4 KB. Binary: skip. Empty: NULL."""
    if not body_bytes:
        return None
    try:
        text = body_bytes.decode("utf-8", errors="replace")[:4096]
        # If it looks like JSON, normalize so the audit-log view is readable.
        try:
            parsed = json.loads(text)
            # Redact obvious secrets so audit isn't a vector for leaks; `code`
            # and `ticket` are the 2FA sign-in's (account_security_api).
            if isinstance(parsed, dict):
                for k in list(parsed.keys()):
                    if any(s in k.lower() for s in ("password", "token", "secret", "api_key")) \
                            or k.lower() in ("code", "ticket"):
                        parsed[k] = "***"
            return json.dumps(parsed)[:4096]
        except Exception:
            return text
    except Exception:
        return None


def _extract_target_id(path: str) -> str | None:
    """Heuristic: the last path segment is the target id if it's not a
    static verb. Catches `/admin/accounts/ACCOUNT_ID`, `/admin/proxies/hu-1`.
    Returns None for fixed-shape paths like `/admin/session/bootstrap`."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    last = parts[-1]
    # Don't treat known-action segments as ids.
    if last in {"active", "bootstrap", "assign", "test", "reload-session",
                "status", "events", "audit", "employees", "accounts",
                "proxies", "sessions"}:
        return None
    return last


def _safe_loads(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def _normalize_color(c: str) -> str:
    """Accept '#ABC', '#AABBCC', or 'abc' / 'aabbcc'; return '#aabbcc'."""
    c = c.strip().lower().lstrip("#")
    if re.fullmatch(r"[0-9a-f]{3}", c):
        c = "".join(ch * 2 for ch in c)
    if not re.fullmatch(r"[0-9a-f]{6}", c):
        raise HTTPException(status_code=400, detail=f"invalid color {c!r}, expected #RRGGBB")
    return "#" + c


# ── Optional: response header that tells the UI who the relay thinks
# the current employee is. Useful for sanity-checking the picker.

