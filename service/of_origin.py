from __future__ import annotations

import os
from urllib.parse import SplitResult, urlsplit

_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def loopback_url(raw: str) -> SplitResult | None:
    try:
        parts = urlsplit(raw.strip())
        parts.port  # noqa: B018 — raises on a malformed port
    except ValueError:
        return None
    if (parts.scheme not in ("http", "https")
            or parts.username is not None or parts.password is not None or "@" in parts.netloc
            or parts.hostname not in _LOOPBACK):
        return None
    return parts


def parse(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    parts = loopback_url(raw)
    port = parts.port if parts is not None else None
    if parts is None or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise RuntimeError(
            f"OF_API_ORIGIN={raw!r} refused: only a bare loopback origin "
            "(http://127.0.0.1:PORT, http://localhost:PORT, http://[::1]:PORT) "
            "is allowed. Unset it to talk to OnlyFans.")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


# Test-only seam: must stay loopback so a signed request can never reach a third party.
OF_API_ORIGIN = parse(os.environ.get("OF_API_ORIGIN", ""))
OF_WEB_ORIGIN = OF_API_ORIGIN or "https://onlyfans.com"

IMPERSONATE = "chrome"
