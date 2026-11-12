"""Public bio asset paths and safe file containment."""
from __future__ import annotations

import os
from pathlib import Path

from bio_pages.hono import decode

PUBLIC = Path(__file__).resolve().parent / "public"
INDEX = PUBLIC / "index.html"


def public_key(rpath: str) -> str | None:
    """Normalise a public request against the cached asset keys, without touching disk."""
    try:
        rel = decode(rpath, "")
        key = os.path.normpath("." + rel)
        return key if key and key != "index.html" and not key.startswith(".") else None
    except ValueError:
        return None

def contained_file(base: Path, *parts: str) -> Path | None:
    """Resolve symlinks and return only a regular file beneath base."""
    try:
        root = os.path.realpath(base)
        path = os.path.realpath(os.path.join(root, *parts))
        return Path(path) if path.startswith(root + os.sep) and os.path.isfile(path) else None
    except (OSError, ValueError):
        return None

