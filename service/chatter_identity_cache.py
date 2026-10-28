"""The chatter identity cache: chatter id -> the identity the session
middleware last read (chatters.py `_session_identity`), so a signed-in
chatter's requests stop re-reading it.

Why: the middleware runs on every /admin/* and /chatter/* request a chatter
makes (2-5 a second each), and building the identity takes four reads
(chatters, chatter_users, user_accounts IN, chatter_account_access) before the
handler starts. A fresh entry skips all of them.

Process-local: one relay process serves a deploy, so one dict is the whole
cache. A second process would not see this one's invalidations; the TTL bounds
how long it could serve old grants (`CHATTERLY_CHATTER_IDENTITY_TTL_S`, default
30 s, 0 = off: every request reads the DB, as before the cache).

Invalidation: `events.publish_state` calls `invalidate()` for
`assignment_changed` and `sessions_revoked`, which every write that changes what
an identity sees already emits after its commit: grants and restrictions
(Chatter Access, Employee setup, shift coverage), links and unlinks, owner
deletes, password / 2FA resets, "log out other sessions" and deactivation (an
unlinked login is revoked). Writes are rare owner actions, so it clears the
whole dict. The cosmetic fields (display_name, color) may lag by up to the TTL.

Threads: `invalidate()` may run off the loop thread (publish_state is
thread-agnostic). `dict.clear()` and the int bump are atomic enough under the
GIL; a load records `generation()` before it reads, and `store()` writes the
entry first and then pops it if the generation moved. `invalidate()` bumps
before it clears, so an invalidation landing at any point after the load
started is seen by that re-check or clears the written entry itself: a read
racing a write never pins the pre-write identity for a TTL.

No service imports: chatters.py and events.py both import this module.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chatters import ChatterIdentity

TTL_S = float(os.environ.get("CHATTERLY_CHATTER_IDENTITY_TTL_S", "30"))


class CachedIdentity:
    """One active chatter as last read: its `chatters.ChatterIdentity`, plus
    the `sessions_valid_after` and `last_seen_at` the revocation and
    inactivity checks need between reads."""

    __slots__ = ("identity", "sessions_valid_after", "last_seen_at", "loaded_at")

    def __init__(self, identity: "ChatterIdentity", sessions_valid_after: datetime | None, last_seen_at: datetime):
        self.identity = identity
        self.sessions_valid_after = sessions_valid_after
        self.last_seen_at = last_seen_at
        self.loaded_at = time.monotonic()


_entries: dict[str, CachedIdentity] = {}
_gen = 0  # bumped by every invalidate()


def get(chatter_id: str) -> CachedIdentity | None:
    """The entry when the cache is on and it is younger than the TTL."""
    if TTL_S <= 0:
        return None
    entry = _entries.get(chatter_id)
    if entry is None or time.monotonic() - entry.loaded_at >= TTL_S:
        return None
    return entry


def generation() -> int:
    """Read before a load; pass to `store()`."""
    return _gen


def store(chatter_id: str, entry: CachedIdentity, gen: int) -> None:
    """Keep `entry` unless the cache is off or an invalidation ran since
    `gen` was read. Write first, then re-check: an off-thread `invalidate()`
    between a compare and the write would otherwise land a stale entry."""
    if TTL_S <= 0:
        return
    _entries[chatter_id] = entry
    if gen != _gen:
        _entries.pop(chatter_id, None)


def drop(chatter_id: str) -> None:
    """Forget one entry (its last_seen_at went out of date); not an
    invalidation."""
    _entries.pop(chatter_id, None)


def invalidate() -> None:
    """Grants or sessions changed: forget every entry, and refuse to store any
    load that started before now."""
    global _gen
    _gen += 1
    _entries.clear()
