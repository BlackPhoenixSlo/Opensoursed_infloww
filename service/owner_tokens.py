"""service/owner_tokens.py — owner access tokens: mint, digest, verdict (pure).

An owner access token signs a non-browser caller (an MCP client) in as one
Agency owner: `Authorization: Bearer ifw_…`. Opaque, not a JWT: the session
middleware looks its sha256 up per request (auth._token_request →
token_auth.resolve), so revoke, expiry and "Log out other sessions"
(`sessions_valid_after`) bite on the next call, as they do for cookies. Only the digest is stored; the plaintext is shown
once, at mint (owner_tokens_api). Ticket: docs/plans/ultra-mode/issues/03-owner-tokens.md.

`ifw_` + `secrets.token_urlsafe(32)` (43 chars, 256 bits) is what the leak gate
matches (`ifw_[A-Za-z0-9_-]{40,}`, .claude/skills/public-sync/leak-check.sh).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Literal

PREFIX = "ifw_"
DAYS = (30, 90, 365)        # the expiries the card offers; expiry is required
DEFAULT_DAYS = 90
TOUCH_S = 300               # last_used_at is bumped at most this often


def mint() -> str:
    """A fresh token, shown to the owner once."""
    return PREFIX + secrets.token_urlsafe(32)


def digest(token: str) -> str:
    """What `owner_tokens.token_sha256` stores and the lookup matches."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hint(token: str) -> str:
    """The list's stand-in for a token: "ifw_…" + its last four."""
    return PREFIX + "…" + token[-4:]


def bearer(header: str | None) -> str | None:
    """The `ifw_` token an `Authorization` header carries, else None. Any other
    scheme or bearer (no `ifw_` prefix) is not ours and is ignored; a bare
    `ifw_` still counts, so it is refused rather than falling through to a cookie."""
    parts = (header or "").split(None, 1)  # any whitespace run (tab, spaces) after the scheme
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip().startswith(PREFIX):
        return None
    return parts[1].strip()


def verdict(
    *, created_at: datetime, expires_at: datetime, revoked_at: datetime | None,
    valid_after: datetime | None, last_used_at: datetime | None, now: datetime,
) -> Literal["refuse", "touch", "ok"]:
    """A found token's fate on one request: "refuse" when revoked, expired
    (`now >= expires_at`) or minted before its owner's `sessions_valid_after`
    (Log out other sessions ends tokens too); "touch" when `last_used_at` is
    unset or older than TOUCH_S, so the caller bumps it; else "ok"."""
    if revoked_at is not None or now >= expires_at or (valid_after is not None and created_at < valid_after):
        return "refuse"
    if last_used_at is None or (now - last_used_at).total_seconds() > TOUCH_S:
        return "touch"
    return "ok"
