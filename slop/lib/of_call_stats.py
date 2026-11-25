from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable


def path(ctx) -> Path:
    return ctx.stack.db.parent / "of_call_stats.json"


def counts(raw: dict, caller: str | None = None) -> Counter:
    out: Counter = Counter()
    for kind, key, aid, status, n in raw["rows"]:
        if caller is None or kind == caller:
            out[(key, aid, status)] += n
    return out


def read(p: Path) -> tuple[dict, Counter]:
    raw = json.loads(p.read_text())
    return raw, counts(raw)


async def quiet(fake, quiet_s: float = 2.5, max_s: float = 60.0) -> bool:
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
    for _ in range(20):
        await quiet(fake)
        w1 = wire(fake)
        # > 2 flushes (counter flushes every 1 s)
        await asyncio.sleep(2.5)
        raw, got = read(p)
        if wire(fake) == w1:
            return raw, got, w1
    return raw, got, wire(fake)
