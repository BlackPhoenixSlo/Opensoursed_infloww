from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import Request

import notifications_api
from auth import get_request_user, request_via
from db.engine import get_session
from db.models import Action, Employee

# employees' name: log continuity
log = logging.getLogger("of-relay.employees")


_AUDIT_SKIP_PREFIXES = (
    "/health",
    "/events",
    "/ws/",
    "/admin/audit",
    "/admin/rev/",
    "/docs",
    "/openapi.json",
    "/app/",
    "/admin/shifts/clock-heartbeat",
    "/admin/agency-notifications",
    # Browserbase login start body carries the OnlyFans PASSWORD: never write it to actions.
    "/admin/login",
    "/admin/ultra/plans",
    "/push",
    "/t/",
    "/admin/view-lease",
)
# Exact paths skipped (not prefixes: a new route under one stays audited). The MCP host route
# (mcp_api.PATH): its body may carry tool args with secrets under any name, which `_safe_snapshot`
# (by name) would keep; each tool's own inner request is the audited write. The MCP sign-in (mcp_oauth): its
# form bodies (code, code_verifier, CSRF value) are not JSON, so `_safe_snapshot` would store them
# as plain text; the token's mint is its own audited inner request.
_AUDIT_SKIP_PATHS = frozenset({"/admin/mcp", "/auth/oauth/register", "/auth/oauth/authorize", "/auth/oauth/token"})
# Note: do NOT include "/" here — every absolute path starts with "/", so
# `startswith("/")` would silently skip every endpoint. The root path is
# handled by the static-UI mount which only serves GET anyway.

BACKGROUND_WRITES = (("POST", "/admin/perflog/"), ("POST", "/admin/errors"))

AUDIT_ACCOUNT = "audit_account_id"

AUDIT_KEYS_ONLY = "audit_keys_only"


def credential_write(request: Request) -> None:
    setattr(request.state, AUDIT_KEYS_ONLY, True)


def audit_action(method: str, path: str) -> str:
    return f"{method} {path}"


def audited(method: str, path: str, skip: tuple[str, ...]) -> bool:
    return (method in ("POST", "PATCH", "PUT", "DELETE") and path not in _AUDIT_SKIP_PATHS
            and not any(path.startswith(p) for p in skip))


def audit_decision(method: str, path: str, status: int, *, should_audit: bool) -> str | None:
    return audit_action(method, path) if should_audit and 200 <= status < 300 else None


async def audit_middleware(request: Request, call_next):
    # lazy: employees re-exports this module
    import employees
    method = request.method
    path = request.url.path
    # Read from employees at call time: slop/lib/relay.py reassigns employees._AUDIT_SKIP_PREFIXES.
    should_audit = audited(method, path, employees._AUDIT_SKIP_PREFIXES)

    body_bytes = b""
    binary_payload_snapshot: str | None = None
    if should_audit:
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
            if hasattr(request.state, AUDIT_ACCOUNT):
                account_id = getattr(request.state, AUDIT_ACCOUNT)
            else:
                account_id = (
                    request.headers.get("x-account-id")
                    or request.query_params.get("account_id")
                )
            user = get_request_user()
            if user is None:
                from chatters import get_request_chatter as _grc
                chatter = _grc()
                if chatter is not None:
                    if emp_id is not None:
                        employees._warn_chatter_header_ignored_once()
                        emp_id = None
                    emp_id = employees.remembered_chatter_employee(request, chatter, account_id)
                    if emp_id is None:
                        emp_id = await employees.resolve_chatter_employee_id(
                            chatter_id=chatter.id,
                            owner_user_ids=chatter.owner_user_ids,
                            account_id=account_id,
                            display_name=chatter.display_name or chatter.username,
                            color=chatter.color,
                        )
            # Spoof guard: a signed-in friend's X-Employee-Id must be their own Employee (admins: any).
            if emp_id is not None and user is not None:
                async with get_session() as _vs:
                    owned = await _vs.get(Employee, emp_id)
                if owned is None or (owned.user_id != user.id and not user.is_admin):
                    log.warning(
                        "x-employee-id=%s rejected: not owned by user=%s (path=%s)",
                        emp_id, user.id, path,
                    )
                    emp_id = None
            if emp_id is None and user is not None:
                emp_id = await employees.get_owner_employee_id(user)
            # Header-less OF proxy writes (mass, scheduled) go to Automation; /admin/* stays NULL to surface a misconfigured client.
            if emp_id is None and path.startswith("/api/of/"):
                try:
                    emp_id = await employees.get_automation_employee_id()
                except LookupError:
                    employees._warn_automation_missing_once()
            await _write_action(
                employee_id=emp_id,
                account_id=account_id,
                action=action,
                payload_json=binary_payload_snapshot if binary_payload_snapshot is not None else _safe_snapshot(
                    body_bytes, keys_only=getattr(request.state, AUDIT_KEYS_ONLY, False)),
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
            via=request_via(),
        ))


# `code`/`ticket` are secret only at top level (2FA sign-in); a nested `code` is an OF country code.
_SECRET_KEY_PARTS = ("password", "token", "secret", "api_key", "cookie", "curl")
_SECRET_KEYS = ("code", "ticket")


def _is_secret_key(k: str, top: bool) -> bool:
    k = k.lower()
    return (top and k in _SECRET_KEYS) or k.endswith("_key") or any(s in k for s in _SECRET_KEY_PARTS)


def _redact(v, keys_only: bool, top: bool = True):
    if isinstance(v, dict):
        return {k: "***" if not keys_only and _is_secret_key(str(k), top) else _redact(x, keys_only, False)
                for k, x in v.items()}
    if isinstance(v, list):
        return [_redact(x, keys_only, False) for x in v]
    if keys_only:
        return "cleared" if v in ("", None) else "set"
    return v


def _safe_snapshot(body_bytes: bytes, *, keys_only: bool) -> str | None:
    if not body_bytes:
        return None
    try:
        text = body_bytes.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except Exception:
            return None if keys_only else text[:4096]
        return json.dumps(_redact(parsed, keys_only))[:4096]
    except Exception:
        return None


def _extract_target_id(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    last = parts[-1]
    if last in {"active", "bootstrap", "assign", "test", "reload-session",
                "status", "events", "audit", "employees", "accounts",
                "proxies", "sessions"}:
        return None
    return last
