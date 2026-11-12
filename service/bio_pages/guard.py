"""The bio app's in-memory limits (click-guard.js:9-38): a fixed wall-clock-minute window per key, the whole table
dropped when a new minute starts, every call counted (refused ones too), allowed while the count <= the limit.
Reveal's window is keyed by client IP; the Page View ping's by client IP and the lower-cased Username, so pings never
use up a Visitor's Reveals. One process (A2), so the counts are exact."""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable


WINDOW_S = 60
MAX_KEYS = 10_000


class FixedWindow:
    def __init__(self, limit: float, clock: Callable[[], float] = time.time):
        self.limit, self.clock = limit, clock
        self._start: int | None = None
        self._counts: OrderedDict[str, int] = OrderedDict()

    def __call__(self, key: str) -> bool:
        start = int(self.clock() * 1000) // (WINDOW_S * 1000)
        if start != self._start:
            self._start, self._counts = start, OrderedDict()
        n = self._counts.get(key, 0) + 1
        self._counts[key] = n
        self._counts.move_to_end(key)
        if len(self._counts) > MAX_KEYS:
            self._counts.popitem(last=False)
        return n <= self.limit


# Set by configure() (bio_pages.app import, or a test). The functions below stay the same objects so a slop fault
# can patch them before startup.
_reveal = FixedWindow(60)
_ping = FixedWindow(60)


def configure(limit: float, clock: Callable[[], float] = time.time) -> None:
    global _reveal, _ping
    _reveal, _ping = FixedWindow(limit, clock), FixedWindow(limit, clock)


def allow(ip: str) -> bool:
    return _reveal(ip)


def allow_ping(ip: str, username: str) -> bool:
    return _ping(f"{ip} {username.lower()[:64]}")
