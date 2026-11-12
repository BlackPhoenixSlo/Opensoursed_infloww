"""The Relay's rewrite-every-30-s telemetry JSON files (priority lane stats in server.py, the OF call
counter): where one lives, read it, rewrite it. Stdlib only, a leaf (of_call_counter is one too).

Lighter than `atomic_json.write_atomic` on purpose: no fsync, no mkdir, a fixed `<name>.tmp`
(one writer per file; callers serialise), so a host crash costs at most one flush interval of counts.
Validation and what a bad file means stay with each caller.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def beside_db(env_var: str, filename: str) -> Path | None:
    """`env_var` if set (empty: None, memory only), else `filename` in the SQLite DB's directory
    (the deployment's one real volume), else None."""
    raw = os.environ.get(env_var)
    if raw is not None:
        raw = raw.strip()
        return Path(raw) if raw else None
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite") and ":///" in url:
        db = url.split(":///", 1)[1].split("?", 1)[0]
        if db and Path(db).parent.is_dir():
            return Path(db).parent / filename
    return None


def read(p: Path) -> Any:
    """The file parsed. Raises (FileNotFoundError when absent)."""
    return json.loads(p.read_text(encoding="utf-8"))


def write(p: Path, data: Any, separators: tuple[str, str] | None = None) -> None:
    """`data` as JSON to `<p>.tmp` beside it, then os.replace over `p`. Raises."""
    tmp = p.parent / (p.name + ".tmp")
    tmp.write_text(json.dumps(data, separators=separators), encoding="utf-8")
    os.replace(tmp, p)
