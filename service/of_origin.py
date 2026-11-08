"""`OF_API_ORIGIN`: the test-only seam that points every OF call at a local
fake (ADR 0024), and what OF's web host and Chrome profile follow from it
(`OF_WEB_ORIGIN`, `IMPERSONATE`). Its own module so session_bootstrap and
proxy_probe can read them without importing of_client (and curl_cffi).

Unset → "" and the real OnlyFans hosts. Set → a bare loopback origin, or the
import refuses, so the env can never send a signed request to a third party.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def parse(raw: str) -> str:
    """`raw` as `scheme://host:port`, rebuilt from its parts; "" when blank.
    Raises RuntimeError for anything but a bare loopback origin."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        parts, port = None, None
    if (parts is None or parts.scheme not in ("http", "https")
            or parts.username is not None or parts.password is not None or "@" in parts.netloc
            or parts.hostname not in _LOOPBACK
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise RuntimeError(
            f"OF_API_ORIGIN={raw!r} refused: only a bare loopback origin "
            "(http://127.0.0.1:PORT, http://localhost:PORT, http://[::1]:PORT) "
            "is allowed. Unset it to talk to OnlyFans.")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


OF_API_ORIGIN = parse(os.environ.get("OF_API_ORIGIN", ""))
OF_WEB_ORIGIN = OF_API_ORIGIN or "https://onlyfans.com"   # the host every /api2/ call goes to

# curl_cffi impersonation profile. "chrome" picks the latest stable Chrome JA3.
# Pin to a specific version (e.g. "chrome131") if OF starts blocking newer ones.
IMPERSONATE = "chrome"
