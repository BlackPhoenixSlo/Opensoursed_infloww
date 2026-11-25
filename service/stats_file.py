from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def beside_db(env_var: str, filename: str) -> Path | None:
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
    return json.loads(p.read_text(encoding="utf-8"))


def write(p: Path, data: Any, separators: tuple[str, str] | None = None) -> None:
    tmp = p.parent / (p.name + ".tmp")
    tmp.write_text(json.dumps(data, separators=separators), encoding="utf-8")
    os.replace(tmp, p)
