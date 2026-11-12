"""The OF call counter's file as slop reads it: one parser and one flush-wait for every scenario that checks it.

service/of_call_counter.py writes `of_call_stats.json` beside the DB, its `rows` each
[Caller kind, "METHOD folded-path", Creator, status class, n]; a scenario reading it sets RELAY_ENV
OF_CALL_STATS_FLUSH_S=1 (prod 30). Used by 2026-11-08-of-call-counter and 2026-11-05-slow-connections.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable


def path(ctx) -> Path:
    """The stack's counter file."""
    return ctx.stack.db.parent / "of_call_stats.json"


def counts(raw: dict, caller: str | None = None) -> Counter:
    """(key, Creator, status class) -> n over the file's rows; `caller` keeps one Caller kind's rows only."""
    out: Counter = Counter()
    for kind, key, aid, status, n in raw["rows"]:
        if caller is None or kind == caller:
            out[(key, aid, status)] += n
    return out


def read(p: Path) -> tuple[dict, Counter]:
    """(raw file, counts over every Caller kind)."""
    raw = json.loads(p.read_text())
    return raw, counts(raw)


async def quiet(fake, quiet_s: float = 2.5, max_s: float = 60.0) -> bool:
    """Until no OF call arrived for `quiet_s` (the counter flushes every 1 s)."""
    t0 = time.monotonic()
    n = -1
    while time.monotonic() - t0 < max_s:
        with fake.lock:
            m = len(fake.calls)
        if m == n:
            return True
        n = m
        await asyncio.sleep(quiet_s)
    return False


def _n_calls(fake) -> int:
    with fake.lock:
        return len(fake.calls)


async def settled(fake, p: Path, wire: Callable[[Any], Any] = _n_calls) -> tuple[dict, Counter, Any]:
    """The file and the wire read with no call in between: (raw file, file counts, `wire(fake)`)."""
    for _ in range(20):
        await quiet(fake)
        w1 = wire(fake)
        await asyncio.sleep(2.5)     # > 2 flushes
        raw, got = read(p)
        if wire(fake) == w1:
            return raw, got, w1
    return raw, got, wire(fake)
