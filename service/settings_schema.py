"""service/settings_schema.py — the one place each Blob tab's schema lives.

`parse_blob(tab, raw) -> (blob, errors)` is pure. `blob` is `raw` with every
invalid field dropped and `version: 1` stamped; `errors` lists each invalid
field as `("<tab>.<dotted.path>", reason)`, in schema order. The Settings PUT
refuses the first error with 400; `settings_api.applied_blob` serves `blob` to
every consumer, so a field stored before this schema existed reads as absent
and its consumer's default applies (docs/spec/phase-04-apply-stored-settings.md,
story 8).

Every key is optional (a partial blob is whole-blob replace, ADR-0007), and
keys the schema does not know are kept, at the top level and inside nested
objects. The shapes are the spec's Implementation Decisions › Schema.

ASSUMPTION: "drops each invalid stored field to its default" is built as the
field being absent from the applied blob, so the consumer's own default
applies (clock_api's 10 minutes and off, shifts_api's off). Rung 5: no
defaults table is needed until a consumer wants one. Overturned if a later
Phase 4 ticket wants the defaults filled in here.

ASSUMPTION: a role needs a non-empty string `id` (the one key assignments and
uniqueness hang on); a role without one, or repeating an earlier role's id, is
dropped whole from the applied blob, while any other invalid role field drops
only that field. Rung 4: the least stored data lost. Overturned if the owner
wants a role with any bad field dropped whole.

ASSUMPTION: role names are compared trimmed and lower-cased, as the Role
Settings Panel's duplicate check does (RoleSettingsTab.tsx `RoleForm`). Rung 3.
Overturned if names should compare with surrounding spaces kept.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable
from zoneinfo import available_timezones

from tx_rollup import CONVERTERS_WINDOW_MAX_S, CONVERTERS_WINDOW_MIN_S

Error = tuple[str, str]
Check = Callable[[Any], "str | None"]

VERSION = 1
MAX_ROLES = 100
# The pages Messages Pro chatting needs; shared by the built-in Chatter and Team Leader and the role presets
# (settings_api.ROLE_PRESETS).
# Get to know fans: its Model info box is the account's, for whoever chats on it.
CHATTING_PAGES = ("/messages-pro", "/of-manager/messages", "/of-manager/notifications", "/growth/scripts",
                  "/growth/get-to-know-fans")
# The Dashboard's cards a role can hide (Infloww's per-card FUN_PERMISSIONS 6222-6232, 05-analytics M6; roadmap
# W5 5.12), each with the Dashboard routes it reads (permissions.require_permission narrows the Dashboard's grant
# of them) and whether it shows earnings. Stored as `/#card-<id>` in a role's `permissions`.
DASHBOARD_CARDS: dict[str, tuple[str, tuple[str, ...], bool]] = {
    # card id: (label, the routes it reads, whether it shows earnings)
    "earnings": ("Creator earnings overview", ("/admin/stats/revenue",), True),
    "employee-sales": ("Employee sales", ("/admin/stats/per-employee",), True),
    # Its cards also read each Creator's OF fan counts and new-subscriber chart (whose earnings series is money).
    "per-model": ("Per-model KPIs", ("/admin/stats/per-model", "/api/of/v2/subscriptions/count/all",
                                     "/api/of/v2/subscriptions/subscribers/chart"), True),
}
CARD_KEYS: dict[str, str] = {f"/#card-{card}": label for card, (label, _, _) in DASHBOARD_CARDS.items()}
REVENUE_CARD_KEYS: tuple[str, ...] = tuple(f"/#card-{c}" for c, (_, _, money) in DASHBOARD_CARDS.items() if money)
# Infloww's default roles after Owner and Admin, as its Time tracking role list shows them live (w5-a,
# .scratch/infloww-live/05-*.png): Team Leader, Chatter, Creator. Each is built in like Owner and Admin (no
# Delete, its name fixed, assignable), but while the `roles` blob does not store it, it grants these pages and
# this Data scope, less its `denied` keys (permissions._role), where an unstored Owner or Admin grants every page. A stored copy (the
# owner's Set Permissions) wins, as for Owner and Admin. No My Automations page (permissions.OPT_IN_PAGES): an
# unstored built-in grants none of them.
BUILT_IN_ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "team-leader": {"name": "Team Leader", "scope": "subordinates",
                    "pages": ("/", *CHATTING_PAGES, "/growth/smart-messages", "/of-manager/home",
                              "/of-manager/vault", "/creators", "/creators/proxy", "/employees",
                              "/employees/shifts", "/analytics/creator-reports", "/analytics/employee-reports",
                              "/analytics/message-dashboard", "/analytics/sales-records")},
    # `denied`: the keys its defaults store false. The Chatter opens the Dashboard without its revenue cards.
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
    # Infloww's InputInteger max (ClockSetting, bundle @10663332).
    ok = isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 999
    return None if ok else "must be a whole number from 1 to 999"


def _converters_window(v: Any) -> str | None:
    # Infloww's hours (0-999) and minutes (0-59) inputs, never both 0: 1 min to 999 h 59 min, in seconds.
    ok = (isinstance(v, int) and not isinstance(v, bool)
          and CONVERTERS_WINDOW_MIN_S <= v <= CONVERTERS_WINDOW_MAX_S and v % 60 == 0)
    return None if ok else (f"must be whole minutes in seconds, from {CONVERTERS_WINDOW_MIN_S} "
                            f"to {CONVERTERS_WINDOW_MAX_S}")


def _fields(raw: dict[str, Any], checks: dict[str, Any], path: str, errors: list[Error]) -> dict[str, Any]:
    """`raw` with each key in `checks` that fails dropped (and its error
    recorded); a check that is a dict is a nested object checked the same way.
    Keys not in `checks` are kept as they are."""
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


# ── One function per Blob tab ───────────────────────────────────────

def _account(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {"agency_name": _text(128)}, "account", errors)


# The agency notification kinds (notifications_api) the owner may switch off; absent is on.
NOTIFICATION_KINDS = ("role_changed", "employee_deactivated", "message_unsent", "clock_in_missed", "session_dead")


def _preferences(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {
        "tz": _zone, "report_tz": _zone,
        "week_start": _enum("monday", "sunday"), "language": _enum("en", "es"),
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
    """"Enable clock in and clock out for": role ids, the built-ins included.
    An id the roles blob does not hold (yet, or any more) is kept, so a role
    deleted and re-added, or saved here before Role Settings, still applies."""
    limit = MAX_ROLES + len(BUILT_IN_ROLE_IDS)
    ok = isinstance(v, list) and len(v) <= limit and all(isinstance(x, str) and x for x in v)
    return None if ok else f"must be a list of at most {limit} role ids"


MAX_SHIFT_PRESETS = 50


def _hhmm(v: Any) -> bool:
    return (isinstance(v, str) and len(v) == 5 and v[2] == ":" and v[:2].isdigit() and v[3:].isdigit()
            and int(v[:2]) < 24 and int(v[3:]) < 60)


def _shift_presets(v: Any) -> str | None:
    """The Shift schedule's saved periods (Infloww's "common periods",
    roadmap W6 6.12), offered in the Shifts window: `[{start, end}]` wall
    clock "HH:MM" in the Shift's own zone, an `end` before `start` ending the
    next day. Stored in the `shifts` blob, not `time-tracking`, whose saves
    are payroll versions (settings_api): a period is a form shortcut and
    credits nothing."""
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
    # Security (organization)'s "Two-factor authentication" switch: every
    # employee signs in with 2FA (service/account_security.py).
    return _fields(raw, {"require_2fa": _bool}, "security", errors)


def _permissions(v: Any) -> str | None:
    if not isinstance(v, dict):
        return "must be an object"
    return None if all(isinstance(x, bool) for x in v.values()) else "every page must be true or false"


_ROLE_FIELDS: dict[str, Any] = {
    "name": _text(64), "description": _text(256), "permissions": _permissions,
    "scope": _enum("all", "subordinates", "self"),
    # Role Settings' Status switch: a disabled role grants nothing (permissions._granting_role).
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


# Agency feature flags (roadmap 8.11): a page set ships dark behind one and
# stays off until its Agency stores it on (`PUT /admin/settings/flags`; no
# Panel). Only the flags a page reads are listed; the Applied settings read
# answers each one, off when never stored.
FLAGS = ("fansly_manager",)


def _flags(raw: dict[str, Any], errors: list[Error]) -> dict[str, Any]:
    return _fields(raw, {name: _bool for name in FLAGS}, "flags", errors)


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
}


def parse_blob(tab: str, raw: dict[str, Any]) -> tuple[dict[str, Any], list[Error]]:
    """The normalised blob (invalid fields dropped, `version: 1`) and every
    error, `("<tab>.<dotted.path>", reason)`, the version's first. A missing
    `version` is stamped 1; any other value than 1 is an error."""
    errors: list[Error] = []
    if "version" in raw:
        v = raw["version"]
        if not (isinstance(v, int) and not isinstance(v, bool) and v == VERSION):
            errors.append((f"{tab}.version", f"unsupported version; expected {VERSION}"))
    blob = TABS[tab](raw, errors)
    blob["version"] = VERSION
    return blob, errors
