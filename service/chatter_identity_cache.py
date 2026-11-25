from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chatters import ChatterIdentity

TTL_S = float(os.environ.get("CHATTERLY_CHATTER_IDENTITY_TTL_S", "30"))


class CachedIdentity:

    __slots__ = ("identity", "sessions_valid_after", "last_seen_at", "loaded_at")

    def __init__(self, identity: "ChatterIdentity", sessions_valid_after: datetime | None, last_seen_at: datetime):
        self.identity = identity
        self.sessions_valid_after = sessions_valid_after
        self.last_seen_at = last_seen_at
        self.loaded_at = time.monotonic()


# Process-local: one relay serves a deploy; display_name/color may lag up to the TTL
_entries: dict[str, CachedIdentity] = {}
_gen = 0


def get(chatter_id: str) -> CachedIdentity | None:
    if TTL_S <= 0:
        return None
    entry = _entries.get(chatter_id)
    if entry is None or time.monotonic() - entry.loaded_at >= TTL_S:
        return None
    return entry


def generation() -> int:
    return _gen


# Write first, then re-check generation: an off-thread invalidate() between compare and write would land a stale entry
def store(chatter_id: str, entry: CachedIdentity, gen: int) -> None:
    if TTL_S <= 0:
        return
    _entries[chatter_id] = entry
    if gen != _gen:
        _entries.pop(chatter_id, None)


def drop(chatter_id: str) -> None:
    """Forget one entry (its last_seen_at went out of date); not an
    invalidation."""
    _entries.pop(chatter_id, None)


# Bump before clear, so a racing load never pins the pre-write identity for a TTL
def invalidate() -> None:
    global _gen
    _gen += 1
    _entries.clear()
