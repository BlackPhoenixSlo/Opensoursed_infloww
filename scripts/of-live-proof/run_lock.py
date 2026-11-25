from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from proof_core import lock_decision


def _lock_path(creator: str) -> Path:
    return Path(tempfile.gettempdir()) / f"ofm-live-proof-{creator}.lock"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def take_lock(creator: str, folder: str) -> tuple[bool, str]:
    path = _lock_path(creator)
    with open(f"{path}.guard", "a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        held = None
        if path.exists():
            try:
                held = json.loads(path.read_text())
            except (ValueError, OSError):
                held = {}
            held = held if isinstance(held, dict) else {}
        pid = held.get("pid") if held else None
        verdict, msg = lock_decision(held, isinstance(pid, int) and _alive(pid))
        if verdict == "refuse":
            return False, f"{msg} [{path}]"
        path.write_text(json.dumps({"pid": os.getpid(), "evidence": f"slop/evidence/{folder}",
                                    "started": datetime.now(timezone.utc).isoformat()}))
        return True, msg


def holds_lock(creator: str) -> bool:
    try:
        return json.loads(_lock_path(creator).read_text()).get("pid") == os.getpid()
    except (OSError, ValueError, AttributeError):
        return False


def release_lock(creator: str) -> None:
    if holds_lock(creator):
        _lock_path(creator).unlink(missing_ok=True)


def _index_path(creator: str) -> Path:
    return _lock_path(creator).with_suffix(".undo-index.json")


def index_logs(creator: str) -> list[Path]:
    path = _index_path(creator)
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise ValueError(f"shared Undo index {path} unreadable: {e}") from e
    got = json.loads(text)
    if not isinstance(got, list) or not all(isinstance(p, str) for p in got):
        raise ValueError(f"shared Undo index {path} is not a list of paths")
    return [Path(p) for p in got]


def index_update(creator: str, add: Path | None = None, drop=()) -> None:
    path = _index_path(creator)
    with open(f"{_lock_path(creator)}.guard", "a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        gone = {str(Path(p).resolve()) for p in drop}
        logs = [str(p) for p in index_logs(creator) if str(p) not in gone]
        if add is not None and str(Path(add).resolve()) not in logs:
            logs.append(str(Path(add).resolve()))
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # atomic: a reader never sees half a write
        tmp.write_text(json.dumps(logs))
        os.replace(tmp, path)
