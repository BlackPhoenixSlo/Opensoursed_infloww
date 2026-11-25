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
    welcomed: Collection[int] = frozenset()
    established: Collection[int] = frozenset()
    guard: Collection[int] = frozenset()
    restricted: Collection[int] = frozenset()
    audience: Collection[int] | None = None
    of_welcome_on: bool | None = None


@dataclass(frozen=True, slots=True)
class Welcome:
    sub: dict
    by_of: bool = False


@dataclass(frozen=True, slots=True)
class Skip:
    sub: dict
    reason: Reason


Decision = Welcome | Skip


def partition(subs: Iterable[dict], reads: Reads, *, account_id: str, now: datetime,
              test_fan: bool = False, starts_at: datetime | None = None,
              delay: list[int] | None = None) -> list[Decision]:
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
    return [d for d in decisions if isinstance(d, Welcome)]


def skip_counts(decisions: Iterable[Decision]) -> Counter[Reason]:
    return Counter(d.reason for d in decisions if isinstance(d, Skip))
