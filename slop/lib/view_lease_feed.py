"""The purchases-feed reads scenarios/2026-11-09-view-lease-purchases-tiers.py and its legs
(lib/view_lease_tiers_<leg>_leg.py) share: a purchases poll is a fake-OF call on POLL_ROUTE with `type=purchases`
and not the rail's page size (RAIL_LIMIT: the rail's, the bell's and the App-open warm's copies of their lists).
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs

POLL_ROUTE = "GET /api2/v2/users/notifications"
RAIL_LIMIT = "20"       # app/lib/notifText.ts NOTIF_PAGE_SIZE: the rail's and bell's lists, never the feed poll's


async def until(pred, timeout_s: float, step: float = 0.05) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(step)
    return False


def is_feed(c: dict) -> bool:
    """A fake-OF call is a purchases-feed read (the poll's: `type=purchases`, not a rail-sized list page)."""
    q = parse_qs(c.get("query") or "")
    return (c["route"] == POLL_ROUTE and (q.get("type") or [""])[0] == "purchases"
            and (q.get("limit") or [""])[0] != RAIL_LIMIT)


def feed(fake, aid: str, lo: float, hi: float = float("inf")) -> list[tuple[float, int]]:
    """`aid`'s purchases-feed calls (t0, status) in [lo, hi]."""
    with fake.lock:
        return [(c["t0"], c["status"]) for c in fake.calls
                if c["account"] == aid and c["t0"] is not None and lo <= c["t0"] <= hi and is_feed(c)]


async def next_poll(fake, aid: str, timeout_s: float) -> bool:
    """Until `aid`'s next purchases-feed call (one arriving from now on) is answered."""
    t0 = time.time()
    return await until(lambda: bool(feed(fake, aid, t0)), timeout_s)
