from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path


def is_stale(beat, now: float, max_age: float) -> bool:
    return beat is None or now - beat > max_age


def ports_path(root: Path, port: int) -> Path:
    return root / "ports" / f"{port}.json"


def session_dir(root: Path, session: str) -> Path:
    return root / "sessions" / session


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=None))
    os.replace(tmp, path)


def read_ports(root: Path, port: int):
    return read_json(ports_path(root, port))


def read_beat(path: Path):
    b = read_json(path)
    return (b.get("ts"), b) if isinstance(b, dict) else (None, {})


def known_identities(root: Path) -> list:
    out = []
    for f in (root / "sessions").glob("*/identities.json"):
        data = read_json(f)
        if isinstance(data, list):
            out.extend(i for i in data if isinstance(i, dict))
    return out


def gate_alive(sdir: Path) -> bool:
    try:
        fd = os.open(sdir / "gate.lock", os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def log_event(sdir: Path, session: str, name: str, **kw) -> None:
    with (sdir / "gate.jsonl").open("a") as f:
        f.write(json.dumps({"ts": round(time.time(), 3), "session": session, "event": name, **kw}) + "\n")
