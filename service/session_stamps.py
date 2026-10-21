"""service/session_stamps.py — the owner session secret and the sessions' clock.

Shared by auth.py (owner cookies), chatters.py (chatter cookies) and
account_security.py (2FA sign-in tickets and enrol tokens), none of which
imports another for these. A cookie or ticket carries its issue time in
milliseconds (`now_ms`); `session_revoked` compares it with its principal's
`sessions_valid_after` (account_security.revoke_sessions), so a revoke ends
every cookie and ticket issued before it.
"""

from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime
from hashlib import sha256
from pathlib import Path

# Persisted to service/.session_secret on first boot if SESSION_SECRET is
# unset, so dev sessions survive restarts without env-var ceremony. In
# prod, set SESSION_SECRET explicitly (env var beats the file).
_SECRET_FILE = Path(__file__).resolve().parent / ".session_secret"


def _load_session_secret() -> bytes:
    env = os.environ.get("SESSION_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    try:
        if _SECRET_FILE.exists():
            return _SECRET_FILE.read_text().strip().encode("utf-8")
    except OSError:
        pass
    new = secrets.token_urlsafe(48)
    try:
        _SECRET_FILE.write_text(new)
        os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        # Read-only FS (some container setups) — fall back to in-process
        # only. Sessions don't survive restart but auth still works.
        pass
    return new.encode("utf-8")


SESSION_SECRET = _load_session_secret()


def sign(payload: str, scope: str = "") -> str:
    """HMAC-SHA256 of `payload` under the owner session secret. A non-empty
    `scope` keeps one kind of token from verifying as another (an owner cookie
    is signed with no scope, a 2FA ticket with "account-security")."""
    data = f"{scope}|{payload}" if scope else payload
    return hmac.new(SESSION_SECRET, data.encode("utf-8"), sha256).hexdigest()


def now_ms() -> int:
    """The session clock, in milliseconds: `datetime.utcnow()` read through
    `.timestamp()`, as `sessions_valid_after` is in `session_revoked`."""
    return int(datetime.utcnow().timestamp() * 1000)


def issued_ms(raw: str) -> int:
    """A cookie's issue stamp in milliseconds. Cookies minted before session
    revoke (2026-10) carry whole seconds."""
    n = int(raw)
    return n * 1000 if n < 10 ** 11 else n


def session_revoked(issued: int, valid_after: datetime | None) -> bool:
    """Whether a cookie (or sign-in ticket) issued at `issued` (ms) predates
    its principal's `sessions_valid_after`. The request that revokes hands its
    caller a fresh cookie a moment later, which is newer, so it stays signed in."""
    return valid_after is not None and issued < int(valid_after.timestamp() * 1000)
