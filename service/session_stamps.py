from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import signed_cookie
from session_secret import load_secret
from signed_cookie import issued_ms  # noqa: F401  re-exported (account_security tests)

# Persisted on first boot if SESSION_SECRET is unset; in prod set SESSION_SECRET (env beats the file).
_SECRET_FILE = Path(__file__).resolve().parent / ".session_secret"
SESSION_SECRET = load_secret("SESSION_SECRET", _SECRET_FILE)


def sign(payload: str, scope: str = "") -> str:
    data = f"{scope}|{payload}" if scope else payload
    return signed_cookie.sign(SESSION_SECRET, data)


def now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)


def session_revoked(issued: int, valid_after: datetime | None) -> bool:
    return valid_after is not None and issued < int(valid_after.timestamp() * 1000)


def session_verdict(
    issued: int, valid_after: datetime | None, last_seen: datetime, now: datetime,
    *, max_idle_s: float, touch_s: float,
) -> Literal["ok", "expired", "touch"]:
    age = (now - last_seen).total_seconds()
    if age > max_idle_s or session_revoked(issued, valid_after):
        return "expired"
    return "touch" if age > touch_s else "ok"


def impersonation_verdict(
    parsed_cookie: tuple[str, str, int] | None, now: datetime, founder_uid: str, *, ttl: int,
) -> Literal["apply", "clear"]:
    if parsed_cookie is None:
        return "clear"
    _imp_uid, cookie_founder, issued = parsed_cookie
    if int(now.timestamp()) - issued > ttl or cookie_founder != founder_uid:
        return "clear"
    return "apply"


def blocks_write(method: str, path: str, impersonating: bool) -> bool:
    return impersonating and method in ("POST", "PATCH", "PUT", "DELETE") and not (
        path.startswith("/admin/impersonate") or path.startswith("/auth/")
    )
