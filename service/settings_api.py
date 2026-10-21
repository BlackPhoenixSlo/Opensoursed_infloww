"""service/settings_api.py — Settings blobs, one per agency and Blob tab.

  GET /admin/settings/applied → what applies to the caller's session
  GET /admin/settings/{tab}  → {tab, config}   ({} when nothing is stored)
  PUT /admin/settings/{tab}  → replace the blob with the JSON object body,
                               stamped `version: 1`; returns {tab, config}
  On the versioned tabs (`sales`, `time-tracking`) GET and PUT also answer
  `history`, and PUT takes `?effective_from=<ISO time>` (default now).

ADR-0007: one table (`user_settings`), whole-blob replace. Each tab's schema
lives in `settings_schema.parse_blob` (docs/spec/phase-04-apply-stored-settings.md):
a PUT with a wrong value is refused naming the first failing field, a partial
blob is accepted and unknown keys are kept. GET answers the stored blob as
stored. Every consumer reads a stored blob through `applied_blob`, which drops
each invalid stored field so its default applies: today `time-tracking`
(clock_api) and `sales.multi_employee_shift` (shifts_api).

Versioned tabs (roadmap W6 6.4): a Sales or Time tracking change must not
rewrite past payroll, so those two tabs are not a `user_settings` blob but
append-only `settings_versions` rows. A save adds a version effective from
`effective_from` (now by default, never later than now, as Infloww's "The
effective time start later than the current time"); a read for time `ts` takes
the latest version with `effective_from <= ts` (`applied_versions`, then
`blob_at`), and GET and `applied_blob` answer the one in effect now. A backdated save
therefore recredits the sales and shifts from its effective time up to the
next version. The blobs stored before moved in as versions effective from
SETTINGS_EPOCH (db.engine.move_versioned_settings), so nothing past moved.

A signed-in User is required, as in `tenant_keys_api`: the user id comes from
the session and never from the request, so an owner can only ever touch their
own rows. A Chatter session resolves to no User here and gets a 401.

The Applied settings read is the one route here a chatter may call: any
signed-in session (owner, chatter or Master) gets the values that apply to it,
from Phase 1's Agency context, and never the stored blobs themselves.

Check order: 401 (no User) → 404 (not a Blob tab) → 413 (body over 64 KB) →
400 (not JSON, not an object, or `{"detail": "<tab>.<dotted.path>: <reason>"}`
for the first field the tab's schema refuses).
"""

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
from permissions import (
    _role, data_scope, denied_actions, denied_cards, enforced, granted_pages, narrowest_scope, opt_in_granted,
)
from settings_schema import CHATTING_PAGES, FLAGS, TABS, parse_blob

router = APIRouter(prefix="/admin/settings", tags=["settings"])

# The Settings tabs whose Panel saves a blob, and `flags` (no Panel):
# exactly the tabs the schema module knows, so a tab without a schema is 404,
# never a KeyError. Any other tab is 404.
BLOB_TABS: frozenset[str] = frozenset(TABS)

MAX_BODY_BYTES = 64 * 1024


_SIGN_IN = "sign in as an account owner to manage settings"


def _require_tab(tab: str) -> None:
    if tab not in BLOB_TABS:
        raise HTTPException(status_code=404, detail=f"unknown settings tab {tab!r}")


def _loads(raw: str | None) -> dict[str, Any]:
    """A stored blob's text as an object, or {} when nothing usable is
    stored (empty, not JSON, or not an object)."""
    try:
        loaded = json.loads(raw) if raw else {}
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


async def _read_blob(s, user_id: str, tab: str) -> dict[str, Any]:
    """The stored blob for (user, tab), or {} when nothing usable is stored;
    for a versioned tab, the version in effect now."""
    if tab in VERSIONED_SETTINGS_TABS:
        return blob_at(await _versions(s, user_id, tab), datetime.utcnow())
    row = await s.get(UserSetting, (user_id, tab))
    return _loads(row.config_json if row is not None else None)


async def _version_rows(s, user_id: str, tab: str) -> list[SettingsVersion]:
    """A versioned tab's rows in effect order: by `effective_from`, then by
    id, so of two saved for the same instant the later one wins."""
    return list((await s.execute(
        select(SettingsVersion).where(SettingsVersion.user_id == user_id, SettingsVersion.tab == tab)
        .order_by(SettingsVersion.effective_from, SettingsVersion.id)
    )).scalars().all())


async def _versions(s, user_id: str, tab: str) -> list[tuple[datetime, dict[str, Any]]]:
    """`(effective_from, stored blob)` per distinct effective time, in order."""
    out: list[tuple[datetime, dict[str, Any]]] = []
    for row in await _version_rows(s, user_id, tab):
        if out and out[-1][0] == row.effective_from:
            out.pop()
        out.append((row.effective_from, _loads(row.config_json)))
    return out


def blob_at(versions: list[tuple[datetime, dict[str, Any]]], ts: datetime) -> dict[str, Any]:
    """The blob of the latest version with `effective_from <= ts`; {} (every
    default) before the first one."""
    found: dict[str, Any] = {}
    for at, blob in versions:
        if at > ts:
            break
        found = blob
    return found


async def applied_versions(s, agency_user_id: str, tab: str) -> list[tuple[datetime, dict[str, Any]]]:
    """A versioned tab's versions as consumers apply them (`applied_blob`'s
    rule), in effect order; `blob_at` picks the one for a time. Readers of
    many sales or shifts take this once instead of `applied_blob` per time."""
    return [(at, parse_blob(tab, blob)[0]) for at, blob in await _versions(s, agency_user_id, tab)]


def _wire(dt: datetime) -> str:
    return dt.isoformat() + "Z"


async def _history(s, user_id: str, tab: str) -> list[dict[str, Any]]:
    """The versioned tab's Settings history, latest effective first:
    `{effective_from, saved_at, in_effect}`. `effective_from` is null for a
    version in effect since before versioning (SETTINGS_EPOCH)."""
    rows = await _version_rows(s, user_id, tab)
    now = datetime.utcnow()
    current = next((r.id for r in reversed(rows) if r.effective_from <= now), None)
    return [{
        "effective_from": None if r.effective_from == SETTINGS_EPOCH else _wire(r.effective_from),
        "saved_at": _wire(r.created_at),
        "in_effect": r.id == current,
    } for r in reversed(rows)]


def _parse_effective(value: str | None) -> datetime:
    """`?effective_from` → naive UTC, now when left out; 400 unless an
    ISO-8601 time with a zone, not later than now."""
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


# Role presets (example roles beside the built-ins Owner, Admin, Team Leader, Chatter and Creator;
# settings_schema.BUILT_IN_ROLE_IDS): seeded once per Agency as ordinary roles the owner edits, renames or
# deletes like any other. The built-ins are not stored here. The seeding is recorded in its own `user_settings`
# row (tab `role-presets`, not a Blob tab), so a preset the owner deleted or renamed is never put back and the
# `roles` blob reads and saves as before. Chatter was a preset until w5-a made it a built-in with the same
# pages; an Agency seeded before keeps its stored copy, which the built-in then reads as its permissions.
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
    """`config` with each preset added whose id or name the Agency does not already use."""
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
    """Seed the role presets into the Agency's `roles` blob, once ever."""
    async with get_session() as s:
        if await s.get(UserSetting, (agency_user_id, _PRESETS_MARKER)) is not None:
            return
        config = await _read_blob(s, agency_user_id, "roles")
        await _write_blob(s, agency_user_id, "roles", _with_presets(config))
        await _write_blob(s, agency_user_id, _PRESETS_MARKER, {"seeded": True})


_ENFORCE_DEFAULT_MIGRATION = "20261019_roles_enforce_default"
_BOOKMARKS_PAGE_MIGRATION = "20261020_bookmarks_page"
_COLLECTIONS, _BOOKMARKS = "/of-manager/collections", "/of-manager/collections/bookmarks/all"


# Every Employee login holds a role: one joining an Agency (Add employee, an invite, a link, its first
# request) or left without one by a roles save gets the built-in Chatter. With enforcement on by default,
# a login with no role would be refused every page.
DEFAULT_LOGIN_ROLE = "chatter"


async def _login_employee_ids(s, agency_user_id: str) -> list[int]:
    """The Agency's Employee logins (`employees.is_login`: not the owner's own row, not a name-only row)."""
    rows = (await s.execute(select(Employee).where(
        Employee.user_id == agency_user_id, Employee.chatter_id.is_not(None)))).scalars().all()
    return [e.id for e in rows if is_login(e)]


def _with_roles_for(blob: dict[str, Any], employee_ids: list[int], role_id: str) -> tuple[dict[str, Any], int]:
    """`blob` (an applied roles blob) with `role_id` given to each of `employee_ids` holding no role
    (`permissions._role`: unassigned, or a role the blob does not hold); and how many it gave."""
    unroled = [e for e in employee_ids if _role(blob, e) is None]
    if not unroled:
        return blob, 0
    assignments = {**(blob.get("assignments") or {}), **{str(e): role_id for e in unroled}}
    return {**blob, "assignments": assignments}, len(unroled)


async def give_role_to_unroled(agency_user_id: str, employee_ids: list[int]) -> int:
    """Give the built-in Chatter to each of `employee_ids` holding no role in the Agency; the count."""
    async with get_session() as s:
        blob, n = _with_roles_for(await applied_blob(s, agency_user_id, "roles"), employee_ids, DEFAULT_LOGIN_ROLE)
        if n:
            await _write_blob(s, agency_user_id, "roles", blob)
            events.on_commit(s, "permissions_changed", agency=agency_user_id)
    return n


async def migrate_role_enforcement_once() -> int:
    """ONE-TIME (2026-10-19): Role enforcement is now on unless an Agency
    stored `enforce: false` (`permissions.enforced`); it used to be off until
    turned on. For every Agency that never chose (no valid `enforce` stored),
    each Employee login holding no role, or a role its blob does not hold, gets
    the built-in Admin (every page, all data), which is what it reached before.
    A login holding a role is NOT widened: that role's stored pages and Data
    scope now apply, where with enforcement off it reached every page, so such a
    login can lose pages until the owner widens its role in Role Settings.
    Owners are never checked. Agencies and logins are read from the Employee
    rows (`employees.is_login`): a login linked but with no Employee row yet is
    not given Admin; its row, made on its first request or when the owner opens
    the roster, gets the built-in Chatter. Guarded by a `data_migrations` marker (fresh
    box too, so it never runs later). Returns the logins given Admin."""
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
                await _write_blob(s, agency, "roles", blob)
            assigned += n
    async with get_session() as s:
        await s.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"), marker)
    return assigned


async def migrate_bookmarks_page_once() -> int:
    """ONE-TIME (2026-10-20): Bookmarks left Collections for a page of its own
    (permissions.PAGE_MAP), so every stored role (custom, a seeded preset, a
    saved built-in copy) that grants Collections also gets Bookmarks, which it
    reached before. A role already holding the Bookmarks key keeps its value.
    Edits the stored JSON in place (the rest untouched). Guarded by a
    `data_migrations` marker. Returns the roles widened."""
    marker = {"n": _BOOKMARKS_PAGE_MIGRATION}
    async with get_session() as s:
        await s.execute(text(_DATA_MIGRATIONS_DDL))
        if (await s.execute(text("SELECT 1 FROM data_migrations WHERE name = :n"), marker)).first():
            return 0
        agencies = (await s.execute(select(UserSetting.user_id).where(UserSetting.tab == "roles"))).scalars().all()
    widened = 0
    for agency in sorted(agencies):
        async with get_session() as s:
            blob = await _read_blob(s, agency, "roles")
            roles = blob.get("roles")
            n = 0
            for role in roles if isinstance(roles, list) else []:
                perms = role.get("permissions") if isinstance(role, dict) else None
                if isinstance(perms, dict) and perms.get(_COLLECTIONS) is True and _BOOKMARKS not in perms:
                    perms[_BOOKMARKS] = True
                    n += 1
            if n:
                await _write_blob(s, agency, "roles", blob)
            widened += n
    async with get_session() as s:
        await s.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"), marker)
    return widened


async def _write_blob(s, user_id: str, tab: str, blob: dict[str, Any]) -> None:
    now = datetime.utcnow()
    payload = json.dumps(blob)
    await s.execute(
        sqlite_insert(UserSetting)
        .values(user_id=user_id, tab=tab, config_json=payload, updated_at=now)
        .on_conflict_do_update(
            index_elements=["user_id", "tab"],
            set_={"config_json": payload, "updated_at": now})
    )


async def applied_blob(s, agency_user_id: str, tab: str) -> dict[str, Any]:
    """The Agency's stored blob for `tab` as consumers apply it: each invalid
    stored field dropped (absent, so its consumer's default applies), the rest
    and unknown keys intact, `version: 1`. Never raises on stored data. For a
    versioned tab, the version in effect now.

    ASSUMPTION: it takes the caller's session `s`, like `_read_blob`, where the
    spec wrote `applied_blob(agency_user_id, tab)`. Rung 3: consumers read it
    inside their own transaction. Overturned if a caller with no session needs it.
    """
    blob, _ = parse_blob(tab, await _read_blob(s, agency_user_id, tab))
    return blob


async def translation_allowed(s, contexts: list[AgencyContext]) -> bool:
    """Whether AI translation applies across these Agency contexts: only if
    every one allows it (spec story 59), a never-stored blob or key counting
    as on. The Applied settings read and the `/admin/translate` gate both
    answer with it."""
    for ctx in contexts:
        messaging = await applied_blob(s, ctx.agency_user_id, "messaging")
        if not messaging.get("ai_translation", True):
            return False
    return True


async def _applied_in(s, ctx: AgencyContext) -> dict[str, Any]:
    """One Agency's Applied settings for one session: a never-stored or
    invalid field reads as its default (no zone, Monday, translation on)."""
    prefs = await applied_blob(s, ctx.agency_user_id, "preferences")
    roles = await applied_blob(s, ctx.agency_user_id, "roles")
    flags = await applied_blob(s, ctx.agency_user_id, "flags")
    pages = granted_pages(ctx, roles)
    return {
        "preferences": {
            "tz": prefs.get("tz"),
            "report_tz": prefs.get("report_tz"),
            "week_start": prefs.get("week_start", "monday"),
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
        "flags": {name: flags.get(name) is True for name in FLAGS},
    }


def _merged(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """A chatter's Applied settings across all its Agencies, with no single
    Creator in scope (spec story 13): no time-zone override, translation only
    if every Agency allows it, a page if any Agency grants it.

    ASSUMPTION: the week start reads as Monday, `enforced` is true if any
    Agency enforces, the Data scope is "self" if any Agency narrows it, and a
    feature flag is on only if every Agency turns it on.
    Rung 4: never wider than one of the Agencies allows. Overturned if the
    owner wants the week start or Data scope taken from one chosen Agency.
    """
    pages: set[str] | None = set()
    for part in parts:
        granted = part["permissions"]["pages"]
        pages = None if pages is None or granted is None else pages | set(granted)
    return {
        "preferences": {"tz": None, "report_tz": None, "week_start": "monday"},
        "messaging": {"ai_translation": all(p["messaging"]["ai_translation"] for p in parts)},
        "permissions": {
            "enforced": any(p["permissions"]["enforced"] for p in parts),
            "pages": None if pages is None else sorted(pages),
            "scope": narrowest_scope(p["permissions"]["scope"] for p in parts),
            # A My Automations page if any Agency grants it, as the Relay allows it.
            "opt_in": sorted({h for p in parts for h in p["permissions"]["opt_in"]}),
            # An action any Agency denies, as the Relay refuses a request naming no Creator.
            "denied_actions": sorted({k for p in parts for k in p["permissions"]["denied_actions"]}),
            # A Dashboard card any Agency hides, as the Relay refuses its routes then.
            "denied_cards": sorted({k for p in parts for k in p["permissions"]["denied_cards"]}),
        },
        "flags": {name: all(p["flags"][name] for p in parts) for name in FLAGS},
    }


# Declared before /{tab}, so "applied" is never read as a tab name.
@router.get("/applied")
async def get_applied(request: Request) -> dict[str, Any]:
    """`{preferences: {tz, report_tz, week_start}, messaging: {ai_translation},
    permissions: {enforced, pages, scope, opt_in, denied_actions, denied_cards}, flags:
    {<name>: bool}}` for the caller's session; `null` zones mean the browser's,
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
    """GET's and PUT's answer: the blob in effect now, and on a versioned tab
    its `history`."""
    out: dict[str, Any] = {"tab": tab, "config": await _read_blob(s, user_id, tab)}
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
            # No login is left without a role: one whose assignment this save drops gets Chatter.
            blob, _ = _with_roles_for(blob, await _login_employee_ids(s, user.id), DEFAULT_LOGIN_ROLE)
            events.on_commit(s, "permissions_changed", agency=user.id)
        if tab == "security" and blob.get("require_2fa") is True and (
            await applied_blob(s, user.id, tab)
        ).get("require_2fa") is not True:
            # 2FA just became required: employees without it sign in again and set it up.
            await revoke_unenrolled_employees(s, user.id)
        await _write_blob(s, user.id, tab, blob)
    return {"tab": tab, "config": blob}
