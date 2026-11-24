"""An untagged outbound row reads as a human send and stands the bot down."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

TTL_S = 60.0
ECHO_WAIT_S = 10.0
ECHO_POLL_S = 0.1
_lock = threading.Lock()


@dataclass
class _Pending:
    started: float
    posting: int = 0
    message_ids: set[int] = field(default_factory=set)


_open: dict[tuple[str, int], _Pending] = {}


def _key(account_id, fan_id) -> tuple[str, int] | None:
    if account_id is None or account_id == "":
        return None
    try:
        return str(account_id), int(fan_id)
    except (TypeError, ValueError):
        return None


def begin(account_id, fan_id) -> _Pending | None:
    key = _key(account_id, fan_id)
    if key is None:
        return None
    with _lock:
        now = time.monotonic()
        state = _open.get(key)
        if state is None or now - state.started > TTL_S:
            state = _open[key] = _Pending(now)
        state.posting += 1
        return state


def post_finished(account_id, fan_id, state: _Pending | None, message_id=None) -> None:
    key = _key(account_id, fan_id)
    if key is None or state is None:
        return
    with _lock:
        if _open.get(key) is not state:
            return
        state.posting -= 1
        if message_id is not None:
            try:
                state.message_ids.add(int(message_id))
            except (TypeError, ValueError):
                pass
        if not state.posting and not state.message_ids:
            del _open[key]


def end(account_id, fan_id, message_id: int) -> None:
    key = _key(account_id, fan_id)
    if key is None:
        return
    try:
        mid = int(message_id)
    except (TypeError, ValueError):
        return
    with _lock:
        state = _open.get(key)
        if state is None:
            return
        state.message_ids.discard(mid)
        if not state.posting and not state.message_ids:
            del _open[key]


def pending(account_id, fan_id) -> bool:
    key = _key(account_id, fan_id)
    if key is None:
        return False
    with _lock:
        state = _open.get(key)
        if state is None:
            return False
        if time.monotonic() - state.started > TTL_S:
            del _open[key]
            return False
        return True
