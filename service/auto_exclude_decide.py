"""service/auto_exclude_decide.py — the pure rules of an Auto_Exclude list past the
20k paging backstop (owner decision O2: refreshed incrementally in the
background, never blocking a send). Stdlib only, no I/O; audiences.py runs them.

The invariant they serve: at OF POST time, (guard − ids OF refused to list) ⊆
mirror ⊆ the list's real members, where mirror = the members the last refresh
crawl saw ∪ the ids whose add OF confirmed one by one since. So a send adds only
the guard ids the mirror lacks; stale members (over-exclude) and an operator's
OF-side removal of a guard id lag until the next background refresh
(`refresh_due`), which crawls the whole list and then applies `next_batch`
against the newest guard, one small batch per short `broadcast_lock` hold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

REFRESH_EVERY_S = 600.0   # a big list's background refresh is due this long after its last attempt
# Adds / removes per broadcast_lock hold. Each is one OF call; at a guessed ~200-400 ms
# per call a hold is ~2-4 s, the longest a send waits behind the refresh.
BATCH = 10
# The refresh crawl's runaway bound, not a size cap: 5,000 pages = 500k members, far
# past any Creator's subscriber count; a crawl that hits it is logged loud and
# changes nothing (audiences `_refresh_auto_exclude`).
REFRESH_MAX_PAGES = 5_000


@dataclass
class Mirror:
    """One account's Auto_Exclude past the backstop, as this process last knew
    it (in memory only: cold after a restart; a small list has none)."""
    list_id: int
    members: set[int] = field(default_factory=set)
    guard: frozenset[int] = frozenset()   # the newest guard a send mirrored
    refreshed_at: float = 0.0             # epoch s of the last crawl / refresh attempt


@dataclass
class RefreshStats:
    """What one background refresh did (logged; the slop relay journals it)."""
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
    """The refresh's next batch against `guard`: up to `n` ids, ascending, adds
    (guard − members: re-adds an id removed on OF's side) before removes
    (members − guard). `skip`: ids this refresh already failed on (a refused add,
    a failed remove). None when nothing is left. Recomputed in every hold, so a
    newer guard or a send's adds count at once."""
    adds = sorted(guard - members - skip)
    if adds:
        return "add", adds[:n]
    removes = sorted(members - guard - skip)
    if removes:
        return "remove", removes[:n]
    return None


def refresh_due(mirror: Mirror, now: float) -> bool:
    """The mirror's background refresh is due: its last attempt is
    REFRESH_EVERY_S old (the module global, read at call time)."""
    return now - mirror.refreshed_at >= REFRESH_EVERY_S
