"""service/signed_cookie.py — the dotted HMAC cookie both principals carry.

Format: `{field}.{field}…{hmac_sha256_hex}`, the HMAC over the dotted fields
under the caller's secret. Owner cookies (auth.py, `user_id.issued_ms`, and the
impersonate pair `impersonated.founder.issued_epoch`) and chatter cookies
(chatters.py, `chatter_id.issued_ms`) differ only in the secret and the field
count, so the secret is passed in and each caller keeps its own.
"""

from __future__ import annotations

import hmac
from hashlib import sha256


def issued_ms(raw: str) -> int:
    """A cookie's issue stamp in milliseconds. Cookies minted before session
    revoke (2026-10) carry whole seconds."""
    n = int(raw)
    return n * 1000 if n < 10 ** 11 else n


def sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode("utf-8"), sha256).hexdigest()


def make(secret: bytes, *fields: str) -> str:
    payload = ".".join(fields)
    return f"{payload}.{sign(secret, payload)}"


def parse(secret: bytes, value: str, n_fields: int) -> list[str] | None:
    """The cookie's `n_fields` fields if its HMAC verifies, else None."""
    parts = value.split(".")
    if len(parts) != n_fields + 1:
        return None
    *fields, sig = parts
    if not hmac.compare_digest(sig, sign(secret, ".".join(fields))):
        return None
    return fields


def parse_issued(secret: bytes, value: str) -> tuple[str, int] | None:
    """`(principal_id, issued_ms)` of a `principal_id.issued` cookie whose HMAC
    verifies (an issue stamp in whole seconds is read as ms), else None."""
    fields = parse(secret, value, 2)
    if fields is None:
        return None
    principal_id, issued = fields
    try:
        return principal_id, issued_ms(issued)
    except ValueError:
        return None
