from __future__ import annotations

import hmac
from hashlib import sha256


def issued_ms(raw: str) -> int:
    n = int(raw)
    # Cookies minted before session revoke carry whole seconds.
    return n * 1000 if n < 10 ** 11 else n


def sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode("utf-8"), sha256).hexdigest()


def make(secret: bytes, *fields: str) -> str:
    payload = ".".join(fields)
    return f"{payload}.{sign(secret, payload)}"


def parse(secret: bytes, value: str, n_fields: int) -> list[str] | None:
    parts = value.split(".")
    if len(parts) != n_fields + 1:
        return None
    *fields, sig = parts
    if not hmac.compare_digest(sig, sign(secret, ".".join(fields))):
        return None
    return fields


def parse_issued(secret: bytes, value: str) -> tuple[str, int] | None:
    fields = parse(secret, value, 2)
    if fields is None:
        return None
    principal_id, issued = fields
    try:
        return principal_id, issued_ms(issued)
    except ValueError:
        return None
