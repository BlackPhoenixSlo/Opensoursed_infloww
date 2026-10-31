"""service/session_secret.py — a session HMAC secret: env var, else a file
beside the service, else a new one written there.

Used by session_stamps.py (SESSION_SECRET, service/.session_secret) and
chatters.py (CHATTER_SESSION_SECRET, service/.chatter_secret), each at import.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def load_secret(env_name: str, path: Path) -> bytes:
    """`env_name`'s value (stripped; blank is unset), else `path`'s contents
    (stripped), else a new token written to `path` (mode 0600), all UTF-8."""
    env = os.environ.get(env_name, "").strip()
    if env:
        return env.encode("utf-8")
    try:
        if path.exists():
            return path.read_text().strip().encode("utf-8")
    except OSError:
        pass
    new = secrets.token_urlsafe(48)
    try:
        path.write_text(new)
        os.chmod(path, 0o600)
    except OSError:
        # Read-only FS (some container setups) — fall back to in-process
        # only. Sessions don't survive restart but auth still works.
        pass
    return new.encode("utf-8")
