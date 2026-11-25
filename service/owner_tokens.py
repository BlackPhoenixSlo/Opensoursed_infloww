from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Literal

PREFIX = "ifw_"
DAYS = (30, 90, 365)
DEFAULT_DAYS = 90
TOUCH_S = 300


def mint() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hint(token: str) -> str:
    return PREFIX + "…" + token[-4:]


def bearer(header: str | None) -> str | None:
    # A bare `ifw_` still counts, so it is refused rather than falling through to a cookie.
    parts = (header or "").split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip().startswith(PREFIX):
        return None
    return parts[1].strip()


def verdict(
    *, created_at: datetime, expires_at: datetime, revoked_at: datetime | None,
    valid_after: datetime | None, last_used_at: datetime | None, now: datetime,
) -> Literal["refuse", "touch", "ok"]:
    # Log out other sessions (sessions_valid_after) ends tokens too.
    if revoked_at is not None or now >= expires_at or (valid_after is not None and created_at < valid_after):
        return "refuse"
    if last_used_at is None or (now - last_used_at).total_seconds() > TOUCH_S:
        return "touch"
    return "ok"
