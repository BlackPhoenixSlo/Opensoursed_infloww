from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import lane_config
from atomic_json import write_atomic

log = logging.getLogger("of-relay.restart-budget")

LIMIT = 2
WINDOW_S = 3600

# Capped per bucket (past/future), never on the merged list: truncating the merged list evicts the largest stamps, which are future ones, and once N piled up it dropped every real in-window stamp (41 restarts granted against a limit of 2).
_MAX_STAMPS = LIMIT * 8

# The ledger is a file because the limited event is this process ending: an in-memory counter would reset on exactly what it counts.
_PATH = Path(lane_config.path()).with_name("lane_restarts.json")
_lock = threading.Lock()


def path() -> str:
    return str(_PATH)


def _stamps() -> list[float]:
    # Never raises: a corrupt ledger must not wedge the button permanently shut.
    try:
        raw = json.loads(_PATH.read_text("utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        log.warning("restart ledger unreadable at %s — treating as empty",
                    _PATH, exc_info=True)
        return []
    if not isinstance(raw, list):
        return []
    out: list[float] = []
    for value in raw:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


# Future stamps do not spend the budget but still survive _kept (a pathological clock must not be able to free it).
def _counted(stamps: list[float], now: float) -> list[float]:
    return [t for t in stamps if 0 <= now - t < WINDOW_S]


def _kept(stamps: list[float], now: float) -> list[float]:
    return [t for t in stamps if now - t < WINDOW_S]


def _budget(stamps: list[float], now: float) -> dict[str, Any]:
    counted = _counted(stamps, now)
    used = len(counted)
    retry_after = 0
    if used >= LIMIT and counted:
        retry_after = max(0, int(WINDOW_S - (now - min(counted))) + 1)
    return {
        "used": used,
        "limit": LIMIT,
        "remaining": max(0, LIMIT - used),
        "window_s": WINDOW_S,
        "retry_after_s": retry_after,
    }


def budget() -> dict[str, Any]:
    now = time.time()
    return _budget(_stamps(), now)


def spend() -> dict[str, Any] | None:
    # Check-and-spend is ONE locked step: two panels clicking together must not both read remaining=1 and both restart. The caller MUST spend BEFORE exiting; this ledger is the only thing that outlives the event it counts. `now` is sampled inside the lock, so a thread never prunes a stamp another committed a moment earlier.
    with _lock:
        now = time.time()
        stamps = _stamps()
        if len(_counted(stamps, now)) >= LIMIT:
            return None
        merged = _kept(stamps, now) + [now]
        counted = sorted(t for t in merged if t <= now)
        ahead = sorted(t for t in merged if t > now)
        # Nearest future stamps are kept: they are next to start counting.
        keep = counted[-_MAX_STAMPS:] + ahead[:_MAX_STAMPS]
        try:
            write_atomic(_PATH, keep)
        except OSError:
            # Fail closed, unlike lane_config: an unrecordable restart is invisible to the next boot, and the button drops in-flight sends. Callers must spend before exiting.
            log.warning("restart ledger unwritable at %s — refusing the restart",
                        _PATH, exc_info=True)
            return None
        # Computed inside the lock from what was just written: re-reading after releasing could report a number another thread already moved.
        return _budget(keep, now)
