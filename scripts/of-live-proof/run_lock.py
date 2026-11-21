"""The Creator's run lock (story 21): one run per Creator, a lock file in the system temp dir shared by every lane's
harness run. Moved out of prove.py in ticket 09 (prove.py < 1000 lines); `holds_lock` is new there (the preflight's
"the lock is held" check)."""
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
    """The Creator's run lock (story 21): (taken, report or refusal). The check-and-take runs under an flock on a
    guard file, so two runs taking over one stale lock cannot both win."""
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
