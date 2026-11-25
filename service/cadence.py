from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

log = logging.getLogger("of-relay.cadence")

DEFAULT_FLOOR_S = 1.0


@asynccontextmanager
async def cadence(interval_s: float, *, floor_s: float = DEFAULT_FLOOR_S,
                  name: str = ""):
    if floor_s <= 0:
        raise ValueError("floor_s must be > 0 — a zero floor is the bug this "
                         "module exists to prevent")
    started = time.monotonic()
    # Floor holds even when the body raises (a no-backoff retry loop is a busy-wait); CancelledError skips the sleep so shutdown isn't held for a full interval.
    cancelled = False
    try:
        yield
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        if not cancelled:
            elapsed = time.monotonic() - started
            # `interval - elapsed` goes negative on an overrun and sleep(<0) spins the loop at 100% CPU (the incident this module prevents).
            delay = max(floor_s, interval_s - elapsed)
            if elapsed > interval_s and name:
                log.warning("cadence_overrun loop=%s elapsed=%.1fs interval=%.1fs "
                            "— holding the %.1fs floor", name, elapsed, interval_s, floor_s)
            await asyncio.sleep(delay)


DEFAULT_BOOT_GRACE_S = 0.0


# Holds the first cycle: at t=0 the relay is starting pumps/executor/seed scrape on the same cores, and a fleet-wide walk there contends with its own startup.
async def boot_grace(delay_s: float, *, name: str = "") -> None:
    if delay_s <= 0:
        return
    if name:
        log.info("boot_grace loop=%s holding %.0fs before first cycle", name, delay_s)
    await asyncio.sleep(delay_s)
