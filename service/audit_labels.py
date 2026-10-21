"""service/audit_labels.py — the audit log's names for people (roadmap W6
6.16): `action_label` maps an `actions.action` ("METHOD path", as
employees.audit_action writes it, or a named row such as `clock.in`) to a
short label; GET /admin/audit returns it as each row's `label`.
"""
from __future__ import annotations

import re


# (method, path, label): `{x}` is one path segment. First match wins, so a
# specific path goes above the general one. A row the middleware did not
# write (`clock.in`, ...) has no method.
_ACTION_LABELS: tuple[tuple[str, str, str], ...] = (
    ("PUT", "/admin/settings/roles", "Changed role settings"),
    ("PUT", "/admin/settings/{tab}", "Saved settings"),
    ("POST", "/admin/employees", "Added an employee"),
    ("POST", "/admin/employees/login", "Added an employee with a login"),
    ("PUT", "/admin/employees/{id}/setup", "Edited an employee"),
    ("PUT", "/admin/employees/{id}/access", "Changed an employee's creators"),
    ("POST", "/admin/employees/{id}/password", "Reset an employee's password"),
    ("POST", "/admin/employees/{id}/2fa/reset", "Reset an employee's 2FA"),
    ("POST", "/admin/employees/{id}/transfer", "Transferred an employee"),
    ("PATCH", "/admin/employees/{id}", "Edited an employee"),
    ("DELETE", "/admin/employees/{id}", "Deactivated an employee"),
    ("POST", "/admin/chatters/link", "Linked an employee login"),
    ("POST", "/admin/chatters/invite", "Invited an employee"),
    ("POST", "/admin/shifts", "Created a shift"),
    ("POST", "/admin/shifts/clock-in", "Clocked in"),
    ("POST", "/admin/shifts/clock-out", "Clocked out"),
    ("PATCH", "/admin/shifts/clock-events/{id}", "Edited a clock record"),
    ("POST", "/admin/shifts/{id}/cancel", "Deleted a shift"),
    ("PATCH", "/admin/shifts/{id}", "Edited a shift"),
    ("POST", "/admin/session/bootstrap", "Linked a creator session"),
    ("PATCH", "/admin/accounts/{id}", "Edited a creator"),
    ("DELETE", "/admin/accounts/{id}", "Removed a creator"),
    ("POST", "/admin/proxies", "Added a proxy"),
    ("DELETE", "/admin/proxies/{label}", "Removed a proxy"),
    ("POST", "/admin/automation-rules", "Created an automation"),
    ("PATCH", "/admin/automation-rules/{id}", "Edited an automation"),
    ("DELETE", "/admin/automation-rules/{id}", "Deleted an automation"),
    ("POST", "/admin/automation-rules/switch", "Switched an automation"),
    ("POST", "/api/of/v2/chats/{id}/messages", "Sent a message"),
    ("POST", "/api/of/v2/chats/messages", "Sent a message"),
    ("DELETE", "/api/of/v2/messages/queue/{id}", "Unsent a mass message"),
    ("POST", "/api/of/v2/messages/queue", "Sent a mass message"),
    ("DELETE", "/api/of/v2/messages/{id}", "Unsent a message"),
    ("POST", "/api/of/v2/posts", "Published a post"),
    ("DELETE", "/api/of/v2/posts/{id}", "Deleted a post"),
    ("POST", "/api/of/v2/scheduled-sends", "Scheduled a message"),
    ("DELETE", "/api/of/v2/scheduled-sends/{id}", "Cancelled a scheduled message"),
    ("PUT", "/api/of/v2/subscriptions/{id}/note", "Edited a fan note"),
    ("PUT", "/api/of/v2/subscriptions/{id}/custom-name", "Renamed a fan"),
    ("", "clock.in", "Clocked in"),
    ("", "clock.out", "Clocked out"),
    ("", "clock.auto_out", "Clocked out for inactivity"),
    ("", "clock.owner_edit", "Edited a clock record"),
    ("", "shift.create", "Created a shift"),
    ("", "shift.edit", "Edited a shift"),
    ("", "shift.cancel", "Deleted a shift"),
    ("", "sales.reassign", "Reassigned a sale"),
    ("", "s4s.request_send", "Sent an S4S request"),
    ("", "s4s.request_cancel", "Cancelled an S4S request"),
    ("", "s4s.request_expire", "An S4S request expired"),
    ("", "s4s.slot_cancel", "Cancelled an S4S slot"),
    ("", "s4s.profile_update", "Edited the S4S profile"),
)


def _pattern(method: str, path: str) -> re.Pattern[str]:
    head = f"{method} " if method else ""
    return re.compile(re.escape(head) + re.sub(r"\\\{[a-z_]+\\\}", "[^/]+", re.escape(path)) + r"$")


_LABEL_PATTERNS = tuple((_pattern(m, p), label) for m, p, label in _ACTION_LABELS)


def action_label(action: str) -> str | None:
    """The audit log's name for an `actions.action` ("METHOD path" or a
    named row such as `clock.in`), or None when the table has none."""
    return next((label for pat, label in _LABEL_PATTERNS if pat.match(action)), None)
