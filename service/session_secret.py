from __future__ import annotations

import os
import secrets
from pathlib import Path


def load_secret(env_name: str, path: Path) -> bytes:
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
        pass
    return new.encode("utf-8")
