from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import events
from account_security import revoke_unenrolled_employees
from auth import require_user
from db.engine import _DATA_MIGRATIONS_DDL, get_session
from db.models import SETTINGS_EPOCH, VERSIONED_SETTINGS_TABS, Employee, SettingsVersion, UserSetting
from employees import AgencyContext, agency_contexts, is_login
from isotime import iso_z
import leak_tracker
from permissions import (
    _role, data_scope, denied_actions, denied_cards, enforced, granted_pages, narrowest_scope, opt_in_granted,
)
from settings_schema import (
    CHATTING_PAGES, FLAGS, TABS, version_rows, versions, applied_blob, blob_at, parse_blob, read_blob,
)

router = APIRouter(prefix="/admin/settings", tags=["settings"])

BLOB_TABS: frozenset[str] = frozenset(TABS)

MAX_BODY_BYTES = 64 * 1024


_SIGN_IN = "sign in as an account owner to manage settings"


def _require_tab(tab: str) -> None:
    if tab not in BLOB_TABS:
        raise HTTPException(status_code=404, detail=f"unknown settings tab {tab!r}")


async def applied_versions(s, agency_user_id: str, tab: str) -> list[tuple[datetime, dict[str, Any]]]:
    return [(at, parse_blob(tab, blob)[0]) for at, blob in await versions(s, agency_user_id, tab)]


async def _history(s, user_id: str, tab: str) -> list[dict[str, Any]]:
    rows = await version_rows(s, user_id, tab)
    now = datetime.utcnow()
    current = next((r.id for r in reversed(rows) if r.effective_from <= now), None)
    return [{
        "effective_from": None if r.effective_from == SETTINGS_EPOCH else iso_z(r.effective_from),
        "saved_at": iso_z(r.created_at),
        "in_effect": r.id == current,
    } for r in reversed(rows)]


def _parse_effective(value: str | None) -> datetime:
    now = datetime.utcnow()
    if value is None:
        return now
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="effective_from: not an ISO-8601 time") from None
    if at.tzinfo is None:
        raise HTTPException(status_code=400, detail="effective_from: the time needs a zone (end it with Z)")
    at = at.astimezone(timezone.utc).replace(tzinfo=None)
    if at > now:
        raise HTTPException(status_code=400, detail="effective_from: the effective time is later than now")
    return max(at, SETTINGS_EPOCH)


ROLE_PRESETS: tuple[dict[str, Any], ...] = (
    {"id": "manager", "name": "Manager", "scope": "all",
     "description": "Runs the team: employees, creators and shifts, and chats too.",
     "pages": ("/", *CHATTING_PAGES, "/growth/smart-messages", "/of-manager/home", "/of-manager/vault",
               "/creators", "/creators/proxy", "/employees", "/employees/shifts",
               "/analytics/creator-reports", "/analytics/employee-reports",
               "/analytics/message-dashboard", "/analytics/sales-records")},
    {"id": "va", "name": "VA", "scope": "self",
     "description": "Content: vault, posts and the queue. No chatting, no money.",
     "pages": ("/of-manager/home", "/of-manager/new-post", "/of-manager/vault", "/of-manager/queue",
               "/of-manager/collections", "/of-manager/collections/bookmarks/all", "/of-manager/profile",
               "/growth/vault-pro", "/growth/auto-post", "/growth/auto-story")},
)
_PRESETS_MARKER = "role-presets"


def _with_presets(config: dict[str, Any]) -> dict[str, Any]:
    roles = config.get("roles") if isinstance(config.get("roles"), list) else []
    ids = {r.get("id") for r in roles if isinstance(r, dict)}
    names = {str(r.get("name", "")).strip().lower() for r in roles if isinstance(r, dict)}
    added = [
        {"id": p["id"], "name": p["name"], "description": p["description"], "scope": p["scope"],
         "permissions": {href: True for href in p["pages"]}}
        for p in ROLE_PRESETS if p["id"] not in ids and p["name"].lower() not in names
    ]
    return {"version": 1, **config, "roles": [*roles, *added]}


async def ensure_role_presets(agency_user_id: str) -> None:
    async with get_session() as s:
        if await s.get(UserSetting, (agency_user_id, _PRESETS_MARKER)) is not None:
            return
        config = await read_blob(s, agency_user_id, "roles")
        await write_blob(s, agency_user_id, "roles", _with_presets(config))
        await write_blob(s, agency_user_id, _PRESETS_MARKER, {"seeded": True})


_ENFORCE_DEFAULT_MIGRATION = "20261019_roles_enforce_default"
_BOOKMARKS_PAGE_MIGRATION = "20261020_bookmarks_page"
_COLLECTIONS, _BOOKMARKS = "/of-manager/collections", "/of-manager/collections/bookmarks/all"


DEFAULT_LOGIN_ROLE = "chatter"


async def _login_employee_ids(s, agency_user_id: str) -> list[int]:
    rows = (await s.execute(select(Employee).where(
        Employee.user_id == agency_user_id, Employee.chatter_id.is_not(None)))).scalars().all()
    return [e.id for e in rows if is_login(e)]


def _with_roles_for(blob: dict[str, Any], employee_ids: list[int], role_id: str) -> tuple[dict[str, Any], int]:
    unroled = [e for e in employee_ids if _role(blob, e) is None]
    if not unroled:
        return blob, 0
    assignments = {**(blob.get("assignments") or {}), **{str(e): role_id for e in unroled}}
    return {**blob, "assignments": assignments}, len(unroled)


async def give_role_to_unroled(agency_user_id: str, employee_ids: list[int]) -> int:
    async with get_session() as s:
        blob, n = _with_roles_for(await applied_blob(s, agency_user_id, "roles"), employee_ids, DEFAULT_LOGIN_ROLE)
        if n:
            await write_blob(s, agency_user_id, "roles", blob)
            events.on_commit(s, "permissions_changed", agency=agency_user_id)
    return n


async def migrate_role_enforcement_once() -> int:
    marker = {"n": _ENFORCE_DEFAULT_MIGRATION}
    async with get_session() as s:
        await s.execute(text(_DATA_MIGRATIONS_DDL))
        if (await s.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"), marker)).first():
            return 0
        rows = (await s.execute(select(Employee).where(Employee.chatter_id.is_not(None)))).scalars().all()
    logins: dict[str, list[int]] = {}
    for e in rows:
        if is_login(e):
            logins.setdefault(e.user_id, []).append(e.id)
    assigned = 0
    for agency in sorted(logins):
        async with get_session() as s:
            blob = await applied_blob(s, agency, "roles")
            if "enforce" in blob:
                continue
            blob, n = _with_roles_for(blob, logins[agency], "admin")
            if n:
                await write_blob(s, agency, "roles", blob)
            assigned += n
    async with get_session() as s:
        await s.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"), marker)
    return assigned


async def migrate_bookmarks_page_once() -> int:
    marker = {"n": _BOOKMARKS_PAGE_MIGRATION}
    async with get_session() as s:
        await s.execute(text(_DATA_MIGRATIONS_DDL))
        if (await s.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"), marker)).first():
            return 0
        agencies = (await s.execute(select(UserSetting.user_id).where(UserSetting.tab == "roles"))).scalars().all()
    widened = 0
    for agency in sorted(agencies):
        async with get_session() as s:
            blob = await read_blob(s, agency, "roles")
            roles = blob.get("roles")
            n = 0
            for role in roles if isinstance(roles, list) else []:
                perms = role.get("permissions") if isinstance(role, dict) else None
                if isinstance(perms, dict) and perms.get(_COLLECTIONS) is True and _BOOKMARKS not in perms:
                    perms[_BOOKMARKS] = True
                    n += 1
            if n:
                await write_blob(s, agency, "roles", blob)
            widened += n
    async with get_session() as s:
        await s.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"), marker)
    return widened


async def write_blob(s, user_id: str, tab: str, blob: dict[str, Any]) -> None:
    now = datetime.utcnow()
    payload = json.dumps(blob)
    await s.execute(
        sqlite_insert(UserSetting)
        .values(user_id=user_id, tab=tab, config_json=payload, updated_at=now)
        .on_conflict_do_update(
            index_elements=["user_id", "tab"],
            set_={"config_json": payload, "updated_at": now})
    )


async def translation_allowed(s, contexts: list[AgencyContext]) -> bool:
    for ctx in contexts:
        messaging = await applied_blob(s, ctx.agency_user_id, "messaging")
        if not messaging.get("ai_translation", True):
            return False
    return True


async def _applied_in(s, ctx: AgencyContext) -> dict[str, Any]:
    prefs = await applied_blob(s, ctx.agency_user_id, "preferences")
    roles = await applied_blob(s, ctx.agency_user_id, "roles")
    flags = await applied_blob(s, ctx.agency_user_id, "flags")
    reports = await applied_blob(s, ctx.agency_user_id, "reports")
    pages = granted_pages(ctx, roles)
    return {
        "preferences": {
            "tz": prefs.get("tz"),
            "report_tz": prefs.get("report_tz"),
            "week_start": prefs.get("week_start", "monday"),
            "hide_trial_popup": prefs.get("hide_trial_popup") is True,
        },
        "messaging": {"ai_translation": await translation_allowed(s, [ctx])},
        "permissions": {
            "enforced": enforced(roles),
            "pages": None if pages is None else sorted(pages),
            "scope": data_scope(ctx, roles),
            "opt_in": sorted(opt_in_granted(ctx, roles)),
            "denied_actions": sorted(denied_actions(ctx, roles)),
            "denied_cards": sorted(denied_cards(ctx, roles)),
        },
        "flags": {name: flags.get(name) is True for name in FLAGS}
        | {leak_tracker.FLAG: leak_tracker.page_on(ctx, flags, roles)},
        "reports": {"creator_cols": reports.get("creator_cols")},
    }


def _merged(parts: list[dict[str, Any]]) -> dict[str, Any]:
    pages: set[str] | None = set()
    for part in parts:
        granted = part["permissions"]["pages"]
        pages = None if pages is None or granted is None else pages | set(granted)
    return {
        "preferences": {"tz": None, "report_tz": None, "week_start": "monday",
                        "hide_trial_popup": all(p["preferences"]["hide_trial_popup"] for p in parts)},
        "messaging": {"ai_translation": all(p["messaging"]["ai_translation"] for p in parts)},
        "permissions": {
            "enforced": any(p["permissions"]["enforced"] for p in parts),
            "pages": None if pages is None else sorted(pages),
            "scope": narrowest_scope(p["permissions"]["scope"] for p in parts),
            "opt_in": sorted({h for p in parts for h in p["permissions"]["opt_in"]}),
            "denied_actions": sorted({k for p in parts for k in p["permissions"]["denied_actions"]}),
            "denied_cards": sorted({k for p in parts for k in p["permissions"]["denied_cards"]}),
        },
        "flags": {name: all(p["flags"][name] for p in parts) for name in FLAGS} | {leak_tracker.FLAG: False},
        "reports": parts[0]["reports"],
    }


@router.get("/applied")
async def get_applied(request: Request) -> dict[str, Any]:
    """`{preferences: {tz, report_tz, week_start, hide_trial_popup}, messaging: {ai_translation},
    permissions: {enforced, pages, scope, opt_in, denied_actions, denied_cards}, flags:
    {<name>: bool}, reports: {creator_cols}}` for the caller's session; `null` zones mean the browser's,
    `pages: null` every page, `opt_in` the My Automations pages it may use
    (`permissions.opt_in_granted`; every one for an owner session, none for a
    chatter without a stored role ticking them on an enforcing Agency), and
    `denied_actions` the `<page>#<action>` Function permissions its role denies
    (`permissions.denied_actions`), `denied_cards` the Dashboard cards it
    hides (`permissions.denied_cards`). `flags` holds every `settings_schema.FLAGS`
    name, false unless the Agency stored it true. 401 signed out.

    An owner session (the Master included) is its own Agency and is never
    checked against a role, so it reads every page and "all" data; `enforced`
    still reports its Agency's switch. A chatter's Agency is the one Phase 1's
    Agency context picks: its only Agency, or the one holding the Creator in
    `X-Account-Id` (403 when that Creator is not the chatter's). A chatter
    linked to several Agencies that names no Creator gets `_merged`.

    ASSUMPTION: an owner session's `enforced` reports its Agency's switch
    (its own `pages` stay null), so the owner's screens can tell the state.
    Rung 5: one meaning of `enforced` for every session. Overturned if the
    owner's read should say false because owners are never checked.
    """
    contexts = await agency_contexts(account_id=request.headers.get("x-account-id") or None)
    async with get_session() as s:
        parts = [await _applied_in(s, ctx) for ctx in contexts]
    return parts[0] if len(parts) == 1 else _merged(parts)


@router.get("/{tab}")
async def get_settings(tab: str) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    _require_tab(tab)
    async with get_session() as s:
        return await _answer(s, user.id, tab)


async def _answer(s, user_id: str, tab: str) -> dict[str, Any]:
    out: dict[str, Any] = {"tab": tab, "config": await read_blob(s, user_id, tab)}
    if tab in VERSIONED_SETTINGS_TABS:
        out["history"] = await _history(s, user_id, tab)
    return out


@router.put("/{tab}")
async def put_settings(tab: str, request: Request, effective_from: str | None = None) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    _require_tab(tab)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="settings blob over 64 KB")
    try:
        body = json.loads(raw)
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="expected a JSON object")
    blob, errors = parse_blob(tab, body)
    if errors:
        path, reason = errors[0]
        raise HTTPException(status_code=400, detail=f"{path}: {reason}")
    async with get_session() as s:
        if tab in VERSIONED_SETTINGS_TABS:
            s.add(SettingsVersion(user_id=user.id, tab=tab, effective_from=_parse_effective(effective_from),
                                  config_json=json.dumps(blob), created_at=datetime.utcnow()))
            await s.flush()
            return await _answer(s, user.id, tab)
        if tab == "roles":
            blob, _ = _with_roles_for(blob, await _login_employee_ids(s, user.id), DEFAULT_LOGIN_ROLE)
            events.on_commit(s, "permissions_changed", agency=user.id)
        if tab == "security" and blob.get("require_2fa") is True and (
            await applied_blob(s, user.id, tab)
        ).get("require_2fa") is not True:
            await revoke_unenrolled_employees(s, user.id)
        await write_blob(s, user.id, tab, blob)
    return {"tab": tab, "config": blob}
