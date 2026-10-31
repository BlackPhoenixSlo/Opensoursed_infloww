"""
service/automations/send_welcome_decide.py — who send_welcome greets this tick, as data.

The pure half of `send_welcome._candidates`: every read (the subscribe feed,
`welcome_sent`, the NOT-NEW scan, the contact guard, the hard-skip list, the
include-only audience, OF's own welcome setting) happens there and arrives here
as one `Reads`; this module only partitions the subscribers it was handed. No
I/O, no clock (`now` is passed in), no payload parsing (the caller parses the
Effective date and the delay band once).

Precedence, first match wins (the order `_candidates` has always filtered in):

    welcomed      a `welcome_sent` row exists: exactly one welcome per fan, ever
    before_start  subscribed before the Effective date (`starts_at`)
    delayed       not yet past his random `delay_range` delay -> a later tick
    established   the NOT-NEW gate: a renewal / re-sub with real history
    guard         another automation touched him inside the contact-guard window
    restricted    muted peer-creator / hand-restricted "no automations"
    audience      outside the include-only audience (enforce mode)

`test_fan` (the UI's "send test") is an explicit force: only `welcomed` and
`audience` apply to it, as before.

A fan who passes is `Welcome`; `by_of` is `Reads.of_welcome_on is True`
(OnlyFans' own subscribe welcome really on, under `after_of_welcome`), and
`send_welcome._welcome_one` routes on it: such a fan is claimed and only the
follow-ups are queued, no burst of ours. He still counts as a new subscriber,
takes a `max_welcomes` slot and a fan lease, as before.

`send_welcome` calls `partition` through this module's attribute so a slop fault
can replace it from outside service code.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import smart_message_extras as extras

Reason = Literal["welcomed", "before_start", "delayed", "established", "guard",
                 "restricted", "audience"]


@dataclass(frozen=True, slots=True)
class Reads:
    """What `_candidates` read so far. A read not taken yet stays empty: it
    excludes nobody. `audience` None = no audience filter (mode off); an empty
    set skips everyone (enforce, nobody in it)."""
    welcomed: Collection[int] = frozenset()
    established: Collection[int] = frozenset()
    guard: Collection[int] = frozenset()
    restricted: Collection[int] = frozenset()
    audience: Collection[int] | None = None
    of_welcome_on: bool | None = None   # OF's own welcome; None = not asked / unreadable


@dataclass(frozen=True, slots=True)
class Welcome:
    sub: dict
    by_of: bool = False   # OF's own welcome greets him: claim + follow-ups only


@dataclass(frozen=True, slots=True)
class Skip:
    sub: dict
    reason: Reason


Decision = Welcome | Skip


def partition(subs: Iterable[dict], reads: Reads, *, account_id: str, now: datetime,
              test_fan: bool = False, starts_at: datetime | None = None,
              delay: list[int] | None = None) -> list[Decision]:
    """One decision per sub, in feed order. `starts_at` is the parsed Effective
    date, `delay` the parsed `delay_range` band (None = off)."""
    out: list[Decision] = []
    for s in subs:
        fid = s["id"]
        at = s.get("at")
        reason: Reason | None = None
        if fid in reads.welcomed:
            reason = "welcomed"
        elif not test_fan:
            if at is not None and starts_at is not None and at < starts_at:
                reason = "before_start"
            elif at is not None and at + timedelta(
                    seconds=extras.delay_seconds(delay, account_id, fid)) > now:
                reason = "delayed"
            elif fid in reads.established:
                reason = "established"
            elif fid in reads.guard:
                reason = "guard"
            elif fid in reads.restricted:
                reason = "restricted"
        if reason is None and reads.audience is not None and int(fid) not in reads.audience:
            reason = "audience"
        out.append(Skip(s, reason) if reason else Welcome(s, reads.of_welcome_on is True))
    return out


def welcomes(decisions: Iterable[Decision]) -> list[Welcome]:
    """The decisions that passed, in order."""
    return [d for d in decisions if isinstance(d, Welcome)]


def skip_counts(decisions: Iterable[Decision]) -> Counter[Reason]:
    """How many were skipped, per reason (a reason nobody hit reads 0)."""
    return Counter(d.reason for d in decisions if isinstance(d, Skip))
