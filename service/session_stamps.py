"""service/session_stamps.py — the owner session secret and the sessions' clock.

Shared by auth.py (owner cookies), chatters.py (chatter cookies) and
account_security.py (2FA sign-in tickets and enrol tokens), none of which
imports another for these. A cookie or ticket carries its issue time in
milliseconds (`now_ms`); `session_revoked` compares it with its principal's
`sessions_valid_after` (account_security.revoke_sessions), so a revoke ends
every cookie and ticket issued before it; `session_verdict` adds the idle
expiry and the last-seen bump both session middlewares apply.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import signed_cookie
from session_secret import load_secret
from signed_cookie import issued_ms  # noqa: F401  re-exported (account_security tests)

# Persisted to service/.session_secret on first boot if SESSION_SECRET is
# unset, so dev sessions survive restarts without env-var ceremony. In
# prod, set SESSION_SECRET explicitly (env var beats the file).
_SECRET_FILE = Path(__file__).resolve().parent / ".session_secret"
SESSION_SECRET = load_secret("SESSION_SECRET", _SECRET_FILE)


def sign(payload: str, scope: str = "") -> str:
    """HMAC-SHA256 of `payload` under the owner session secret. A non-empty
    `scope` keeps one kind of token from verifying as another: 2FA tickets use
    "account-security"; owner cookies sign through signed_cookie under the same
    secret, i.e. the no-scope bytes."""
    data = f"{scope}|{payload}" if scope else payload
    return signed_cookie.sign(SESSION_SECRET, data)


def now_ms() -> int:
    """The session clock, in milliseconds: `datetime.utcnow()` read through
    `.timestamp()`, as `sessions_valid_after` is in `session_revoked`."""
    return int(datetime.utcnow().timestamp() * 1000)


def session_revoked(issued: int, valid_after: datetime | None) -> bool:
    """Whether a cookie (or sign-in ticket) issued at `issued` (ms) predates
    its principal's `sessions_valid_after`. The request that revokes hands its
    caller a fresh cookie a moment later, which is newer, so it stays signed in."""
    return valid_after is not None and issued < int(valid_after.timestamp() * 1000)


def session_verdict(
    issued: int, valid_after: datetime | None, last_seen: datetime, now: datetime,
    *, max_idle_s: float, touch_s: float,
) -> Literal["ok", "expired", "touch"]:
    """A signed-in cookie's fate on one request: "expired" when its principal
    was idle more than `max_idle_s` or it was revoked (`session_revoked`), so
    the cookie is cleared; "touch" when `last_seen` is more than `touch_s` old,
    so the caller bumps it; else "ok"."""
    age = (now - last_seen).total_seconds()
    if age > max_idle_s or session_revoked(issued, valid_after):
        return "expired"
    return "touch" if age > touch_s else "ok"
