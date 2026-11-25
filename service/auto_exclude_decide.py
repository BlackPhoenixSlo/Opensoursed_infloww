from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Invariant at OF POST: (guard - ids OF refused) <= mirror <= the list's real members.
REFRESH_EVERY_S = 600.0
# One OF call each, guessed ~200-400 ms: a hold is ~2-4 s, the longest a send waits behind the refresh.
BATCH = 10
# Runaway bound, not a size cap; hitting it is logged loud and changes nothing.
REFRESH_MAX_PAGES = 5_000


@dataclass
class Mirror:
    list_id: int
    members: set[int] = field(default_factory=set)
    guard: frozenset[int] = frozenset()
    refreshed_at: float = 0.0


@dataclass
class RefreshStats:
    crawled: int = 0
    crawl_s: float = 0.0
    adds: int = 0
    add_fail: int = 0
    removes: int = 0
    remove_fail: int = 0
    holds: int = 0
    s: float = 0.0


def next_batch(members: set[int], guard: frozenset[int] | set[int], n: int,
               skip: set[int]) -> tuple[Literal["add", "remove"], list[int]] | None:
    adds = sorted(guard - members - skip)
    if adds:
        return "add", adds[:n]
    removes = sorted(members - guard - skip)
    if removes:
        return "remove", removes[:n]
    return None


def refresh_due(mirror: Mirror, now: float) -> bool:
    return now - mirror.refreshed_at >= REFRESH_EVERY_S
