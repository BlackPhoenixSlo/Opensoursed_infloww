from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable
from zoneinfo import available_timezones

from sqlalchemy import select

from db.models import VERSIONED_SETTINGS_TABS, SettingsVersion, UserSetting
from tx_rollup import CONVERTERS_WINDOW_MAX_S, CONVERTERS_WINDOW_MIN_S

Error = tuple[str, str]
Check = Callable[[Any], "str | None"]

VERSION = 1
MAX_ROLES = 100
CHATTING_PAGES = ("/messages-pro", "/of-manager/messages", "/of-manager/notifications", "/growth/scripts",
                  "/growth/get-to-know-fans")
DASHBOARD_CARDS: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "earnings": ("Creator earnings overview", ("/admin/stats/revenue",), True),
    "employee-sales": ("Employee sales", ("/admin/stats/per-employee",), True),
    "per-model": ("Per-model KPIs", ("/admin/stats/per-model", "/api/of/v2/subscriptions/count/all",
                                     "/api/of/v2/subscriptions/subscribers/chart"), True),
}
CARD_KEYS: dict[str, str] = {f"/#card-{card}": label for card, (label, _, _) in DASHBOARD_CARDS.items()}
REVENUE_CARD_KEYS: tuple[str, ...] = tuple(f"/#card-{c}" for c, (_, _, money) in DASHBOARD_CARDS.items() if money)
BUILT_IN_ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "team-leader": {"name": "Team Leader", "scope": "subordinates",
                    "pages": ("/", *CHATTING_PAGES, "/growth/smart-messages", "/of-manager/home",
                              "/of-manager/vault", "/creators", "/creators/proxy", "/creators/leaks",
                              "/employees", "/employees/shifts", "/analytics/creator-reports",
                              "/analytics/employee-reports", "/analytics/message-dashboard",
                              "/analytics/sales-records")},
    "chatter": {"name": "Chatter", "scope": "self", "pages": ("/", *CHATTING_PAGES), "denied": REVENUE_CARD_KEYS},
    "creator": {"name": "Creator", "scope": "self",
                "pages": ("/of-manager/home", "/of-manager/new-post", "/of-manager/vault", "/of-manager/queue",
                          "/of-manager/collections", "/of-manager/collections/bookmarks/all",
                          "/of-manager/profile", "/of-manager/release-forms", "/growth/vault-pro")},
}
BUILT_IN_ROLE_IDS = frozenset({"owner", "admin", *BUILT_IN_ROLE_DEFAULTS})


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def _bool(v: Any) -> str | None:
    return None if isinstance(v, bool) else "must be true or false"


def _enum(*options: str) -> Check:
    def check(v: Any) -> str | None:
        return None if isinstance(v, str) and v in options else f"must be one of {', '.join(options)}"
    return check


def _text(max_len: int) -> Check:
    def check(v: Any) -> str | None:
        ok = isinstance(v, str) and len(v) <= max_len
        return None if ok else f"must be text of at most {max_len} characters"
    return check


def _zone(v: Any) -> str | None:
    return None if isinstance(v, str) and v in _zones() else "unknown IANA time zone"


def _minutes(v: Any) -> str | None:
    ok = isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 999
    return None if ok else "must be a whole number from 1 to 999"


def _converters_window(v: Any) -> str | None:
    ok = (isinstance(v, int) and not isinstance(v, bool)
          and CONVERTERS_WINDOW_MIN_S <= v <= CONVERTERS_WINDOW_MAX_S and v % 60 == 0)
    return None if ok else (f"must be whole minutes in seconds, from {CONVERTERS_WINDOW_MIN_S} "
                            f"to {CONVERTERS_WINDOW_MAX_S}")


def _fields(raw: dict[str, Any], checks: dict[str, Any], path: str, errors: list[Error]) -> dict[str, Any]:
    out = dict(raw)
    for key, check in checks.items():
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(check, dict):
            if isinstance(value, dict):
                out[key] = _fields(value, check, f"{path}.{key}", errors)
                continue
            reason = "must be an object"
        else:
            reason = check(value)
            if reason is None:
                continue
        errors.append((f"{path}.{key}", reason))
        del out[key]
    return out



def _account(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {"agency_name": _text(128)}, "account", errors)


NOTIFICATION_KINDS = ("role_changed", "employee_deactivated", "message_unsent", "clock_in_missed", "session_dead",
                      "ultra_done", "promo_keep_running")


def _preferences(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {
        "tz": _zone, "report_tz": _zone,
        "week_start": _enum("monday", "sunday"), "language": _enum("en", "es"),
        "hide_trial_popup": _bool,
        "notifications": {kind: _bool for kind in NOTIFICATION_KINDS},
    }, "preferences", errors)


def _sales(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {
        "exclude_welcome": _bool, "exclude_of_fee": _bool, "multi_employee_shift": _bool,
        "attribution": {
            "messages": _enum("shift", "sender", "converters"),
            "posts_tips": _enum("shift", "converters"),
            "subscriptions_chatter_opt_in": _bool,
            "converters_window_seconds": _converters_window,
        },
    }, "sales", errors)


def _role_ids(v: Any) -> str | None:
    limit = MAX_ROLES + len(BUILT_IN_ROLE_IDS)
    ok = isinstance(v, list) and len(v) <= limit and all(isinstance(x, str) and x for x in v)
    return None if ok else f"must be a list of at most {limit} role ids"


MAX_SHIFT_PRESETS = 50


def _hhmm(v: Any) -> bool:
    return (isinstance(v, str) and len(v) == 5 and v[2] == ":" and v[:2].isdigit() and v[3:].isdigit()
            and int(v[:2]) < 24 and int(v[3:]) < 60)


def _shift_presets(v: Any) -> str | None:
    ok = (isinstance(v, list) and len(v) <= MAX_SHIFT_PRESETS
          and all(isinstance(p, dict) and set(p) == {"start", "end"} and _hhmm(p["start"]) and _hhmm(p["end"])
                  and p["start"] != p["end"] for p in v))
    return None if ok else (f"must be a list of at most {MAX_SHIFT_PRESETS} periods "
                            '{"start": "HH:MM", "end": "HH:MM"}, start and end apart')


def _time_tracking(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {
        "enabled": _bool, "auto_clock_out_minutes": _minutes, "clock_in_reminder": _bool,
        "role_ids": _role_ids,
    }, "time-tracking", errors)


def _shifts(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {"presets": _shift_presets}, "shifts", errors)


def _messaging(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {"ai_translation": _bool, "prompt": _text(2000)}, "messaging", errors)


def _security(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {"require_2fa": _bool}, "security", errors)


def _permissions(v: Any) -> str | None:
    if not isinstance(v, dict):
        return "must be an object"
    return None if all(isinstance(x, bool) for x in v.values()) else "every page must be true or false"


_ROLE_FIELDS: dict[str, Any] = {
    "name": _text(64), "description": _text(256), "permissions": _permissions,
    "scope": _enum("all", "subordinates", "self"),
    "disabled": _bool,
}


def _roles(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    out = _fields(raw, {"enforce": _bool}, "roles", errors)
    ids: set[str] = set()
    if "roles" in raw:
        roles = raw["roles"]
        if not isinstance(roles, list):
            errors.append(("roles.roles", "must be a list"))
            del out["roles"]
        elif len(roles) > MAX_ROLES:
            errors.append(("roles.roles", f"must hold at most {MAX_ROLES} roles"))
            del out["roles"]
        else:
            kept: list[dict[str, Any]] = []
            names: set[str] = set()
            for i, role in enumerate(roles):
                at = f"roles.roles.{i}"
                if not isinstance(role, dict):
                    errors.append((at, "must be an object"))
                    continue
                rid = role.get("id")
                if not (isinstance(rid, str) and rid):
                    errors.append((f"{at}.id", "must be a non-empty string"))
                    continue
                if rid in ids:
                    errors.append((f"{at}.id", "duplicate role id"))
                    continue
                ids.add(rid)
                role = _fields(role, _ROLE_FIELDS, at, errors)
                name = role.get("name")
                if isinstance(name, str):
                    key = name.strip().lower()
                    if key in names:
                        errors.append((f"{at}.name", "duplicate role name"))
                        del role["name"]
                    names.add(key)
                kept.append(role)
            out["roles"] = kept
    if "assignments" in raw:
        assignments = raw["assignments"]
        if not isinstance(assignments, dict):
            errors.append(("roles.assignments", "must be an object"))
            del out["assignments"]
        else:
            held = ids | BUILT_IN_ROLE_IDS
            kept_assignments: dict[str, Any] = {}
            for employee_id, role_id in assignments.items():
                if isinstance(role_id, str) and role_id in held:
                    kept_assignments[employee_id] = role_id
                else:
                    errors.append((f"roles.assignments.{employee_id}", "names no role this blob holds"))
            out["assignments"] = kept_assignments
    return out


FLAGS = ("fansly_manager", "leak_tracker")


def _flags(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {name: _bool for name in FLAGS}, "flags", errors)


MAX_REPORT_COLS = 100


def _col_keys(v: Any) -> str | None:
    ok = (isinstance(v, list) and len(v) <= MAX_REPORT_COLS
          and all(isinstance(x, str) and 0 < len(x) <= 64 for x in v) and len(set(v)) == len(v))
    return None if ok else f"must be a list of at most {MAX_REPORT_COLS} unique column keys"


def _reports(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {"creator_cols": _col_keys}, "reports", errors)


TABS: dict[str, Callable[[dict[str, Any], list[Error]], dict[str, Any]]] = {
    "account": _account,
    "preferences": _preferences,
    "roles": _roles,
    "sales": _sales,
    "time-tracking": _time_tracking,
    "shifts": _shifts,
    "messaging": _messaging,
    "security": _security,
    "flags": _flags,
    "reports": _reports,
}


def parse_blob(tab: str, raw: dict[str, Any]) -> tuple[dict[str, Any], list[Error]]:
    errors: list[Error] = []
    if "version" in raw:
        v = raw["version"]
        if not (isinstance(v, int) and not isinstance(v, bool) and v == VERSION):
            errors.append((f"{tab}.version", f"unsupported version; expected {VERSION}"))
    blob = TABS[tab](raw, errors)
    blob["version"] = VERSION
    return blob, errors


def _loads(raw: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(raw) if raw else {}
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


async def read_blob(s, user_id: str, tab: str) -> dict[str, Any]:
    if tab in VERSIONED_SETTINGS_TABS:
        return blob_at(await versions(s, user_id, tab), datetime.utcnow())
    row = await s.get(UserSetting, (user_id, tab))
    return _loads(row.config_json if row is not None else None)


async def version_rows(s, user_id: str, tab: str) -> list[SettingsVersion]:
    return list((await s.execute(
        select(SettingsVersion).where(SettingsVersion.user_id == user_id, SettingsVersion.tab == tab)
        .order_by(SettingsVersion.effective_from, SettingsVersion.id)
    )).scalars().all())


async def versions(s, user_id: str, tab: str) -> list[tuple[datetime, dict[str, Any]]]:
    out: list[tuple[datetime, dict[str, Any]]] = []
    for row in await version_rows(s, user_id, tab):
        if out and out[-1][0] == row.effective_from:
            out.pop()
        out.append((row.effective_from, _loads(row.config_json)))
    return out


def blob_at(versions: list[tuple[datetime, dict[str, Any]]], ts: datetime) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for at, blob in versions:
        if at > ts:
            break
        found = blob
    return found


async def applied_blob(s, agency_user_id: str, tab: str) -> dict[str, Any]:
    blob, _ = parse_blob(tab, await read_blob(s, agency_user_id, tab))
    return blob
