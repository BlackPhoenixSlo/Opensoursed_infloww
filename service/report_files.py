"""service/report_files.py — built report files held in memory for a download link
(`POST /admin/reports/files` → `GET /admin/reports/files/{id}`; docs/plans/ultra-mode/issues/05-mcp-server.md,
"Desktop save").

A file lives TTL_S (15 min) under an unguessable id and only its creating user gets it back:
anyone else, an unknown id and an expired one all read as None (the route's 404). Bounded:
at most MAX_FILES files and MAX_BYTES bytes in the process, MAX_PER_USER per user; adding past
a bound drops expired files first, then the caller's own oldest, never another user's: when only
theirs remain, `put` raises Full (the route's 429). One process (single relay worker), so a
restart forgets every link — fine for a 15-minute download.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable

TTL_S = 15 * 60
MAX_FILES = 50
MAX_PER_USER = 10
MAX_BYTES = 100 * 1024 * 1024


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
    """No room without evicting another user's file."""


_files: dict[str, File] = {}  # insertion order = age
_clock: Callable[[], float] = time.monotonic


def _drop_expired(now: float) -> None:
    for fid in [f.id for f in _files.values() if f.expires <= now]:
        _files.pop(fid, None)


def put(user_id: str, filename: str, media_type: str, body: bytes) -> File:
    """Hold `body` for `user_id`; its File (id, expires). TooLarge when one file alone exceeds
    MAX_BYTES; Full when the bounds hold only other users' files."""
    if len(body) > MAX_BYTES:
        raise TooLarge(f"report file over {MAX_BYTES // (1024 * 1024)} MB")
    now = _clock()
    _drop_expired(now)
    mine = [f.id for f in _files.values() if f.user_id == user_id]  # oldest first
    while (len(mine) >= MAX_PER_USER or len(_files) >= MAX_FILES
           or sum(len(f.body) for f in _files.values()) + len(body) > MAX_BYTES):
        if not mine:
            raise Full("report file storage is full; try again in a few minutes")
        _files.pop(mine.pop(0))
    f = File(secrets.token_urlsafe(24), user_id, filename, media_type, body, now + TTL_S)
    _files[f.id] = f
    return f


def get(file_id: str, user_id: str) -> File | None:
    """The file, if it is `user_id`'s and not expired; else None (no hint which)."""
    f = _files.get(file_id)
    if f is None:
        return None
    if f.expires <= _clock():
        _files.pop(file_id, None)
        return None
    return f if secrets.compare_digest(f.user_id, user_id) else None
