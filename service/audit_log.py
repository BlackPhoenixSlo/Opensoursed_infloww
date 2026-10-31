"""service/audit_log.py — the audit middleware: a row in `actions` for every
write that succeeded.

`audit_decision` is its pure rule (which request, which `actions.action`);
`audit_middleware` snapshots the body, resolves the acting Employee through
employees.py and writes the row.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import Request

import notifications_api
from auth import get_request_user
from db.engine import get_session
from db.models import Action, Employee

log = logging.getLogger("of-relay.employees")  # employees' name: log continuity


# Defined once here; employees re-exports it and the middleware reads it from
# there (see audit_middleware).
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
    # The served Browserbase login (remote_login_api): its start body carries
    # the OnlyFans PASSWORD, which must never be written to the actions table.
    "/admin/login",
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


def audited(method: str, path: str, skip: tuple[str, ...]) -> bool:
    """Whether a request is a write the audit log records once it succeeds,
    `skip` being the skip prefixes in force."""
    return method in ("POST", "PATCH", "PUT", "DELETE") and not any(path.startswith(p) for p in skip)


def audit_decision(method: str, path: str, status: int, *, should_audit: bool) -> str | None:
    """The `actions.action` a finished request is logged under, or None: only
    an audited write (`should_audit`, from `audited` before the response) that
    answered 2xx."""
    return audit_action(method, path) if should_audit and 200 <= status < 300 else None


async def audit_middleware(request: Request, call_next):
    """FastAPI HTTP middleware. Wraps every request so:
      • if method is mutating (POST / PATCH / PUT / DELETE) and the
        response is 2xx, we log a row to `actions`.
      • employee_id comes from the `X-Employee-Id` header (NULL if absent).
      • payload_json captures a truncated snapshot of the body for replay.

    Failure isolation: every step is try/except + log. A bad audit write
    never affects the actual response the user sees.
    """
    import employees  # lazy: employees re-exports this module
    # Snapshot enough to log BEFORE call_next so a failed downstream still
    # gets recorded (with status_code set in the post-block).
    method = request.method
    path = request.url.path
    # The skip prefixes are read from employees at call time, not this
    # module's binding: slop/lib/relay.py reassigns
    # employees._AUDIT_SKIP_PREFIXES (adding "/__slop/"), and this module's
    # own name would miss that.
    should_audit = audited(method, path, employees._AUDIT_SKIP_PREFIXES)

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

    action = audit_decision(method, path, response.status_code, should_audit=should_audit)
    if action is not None:
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
                        employees._warn_chatter_header_ignored_once()
                        emp_id = None
                    emp_id = await employees.resolve_chatter_employee_id(
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
                emp_id = await employees.get_owner_employee_id(user)
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
                    emp_id = await employees.get_automation_employee_id()
                except LookupError:
                    employees._warn_automation_missing_once()
            await _write_action(
                employee_id=emp_id,
                account_id=account_id,
                action=action,
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
