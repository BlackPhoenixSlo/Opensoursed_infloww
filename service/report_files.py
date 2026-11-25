from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable

TTL_S = 15 * 60
MAX_FILES = 50
MAX_PER_USER = 10
MAX_BYTES = 100 * 1024 * 1024
MAX_BYTES_PER_USER = MAX_BYTES // 5
ROUTE = "/admin/reports/files/{file_id}"


@dataclass(frozen=True)
class File:
    id: str
    user_id: str
    filename: str
    media_type: str
    body: bytes
    expires: float


class TooLarge(Exception):
    pass


class Full(Exception):
    pass


_files: dict[str, File] = {}
_clock: Callable[[], float] = time.monotonic


def _drop_expired(now: float) -> None:
    for fid in [f.id for f in _files.values() if f.expires <= now]:
        _files.pop(fid, None)


# Only the creating user gets a file back; past a bound it drops expired files, then the caller's own oldest, never another user's. One relay worker: a restart forgets every link.
def put(user_id: str, filename: str, media_type: str, body: bytes) -> File:
    if len(body) > MAX_BYTES_PER_USER:
        raise TooLarge(f"report file over {MAX_BYTES_PER_USER // (1024 * 1024)} MB")
    now = _clock()
    _drop_expired(now)
    mine = [f for f in _files.values() if f.user_id == user_id]
    files, total = len(_files), sum(len(f.body) for f in _files.values())
    own = sum(len(f.body) for f in mine)
    drop = 0
    while (len(mine) - drop >= MAX_PER_USER or files - drop >= MAX_FILES
           or total + len(body) > MAX_BYTES or own + len(body) > MAX_BYTES_PER_USER):
        if drop == len(mine):
            raise Full("report file storage is full; try again in a few minutes")
        total -= len(mine[drop].body)
        own -= len(mine[drop].body)
        drop += 1
    for old in mine[:drop]:
        _files.pop(old.id)
    f = File(secrets.token_urlsafe(24), user_id, filename, media_type, body, now + TTL_S)
    _files[f.id] = f
    return f


def get(file_id: str, user_id: str) -> File | None:
    f = _files.get(file_id)
    if f is None:
        return None
    if f.expires <= _clock():
        _files.pop(file_id, None)
        return None
    return f if secrets.compare_digest(f.user_id, user_id) else None
