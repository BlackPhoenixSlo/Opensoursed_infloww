from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


# Raises OSError; callers decide: lane_config fails open to defaults, restart_budget fails closed.
def write_atomic(target: Path, data: Any) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Temp in the target's directory: os.replace is atomic only within one filesystem.
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix="." + target.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            # fsync before the rename so the bytes are on disk when it publishes.
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        # Parent dir fsync after the rename (a host crash can lose the rename itself); best-effort and non-raising, the data already landed and restart_budget would read a raise as "refuse the restart".
        dir_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass
