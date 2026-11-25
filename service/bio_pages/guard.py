from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable


# Every call is counted, refused ones too; allowed while count <= limit.
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


_reveal = FixedWindow(60)
_ping = FixedWindow(60)


def configure(limit: float, clock: Callable[[], float] = time.time) -> None:
    global _reveal, _ping
    _reveal, _ping = FixedWindow(limit, clock), FixedWindow(limit, clock)


def allow(ip: str) -> bool:
    return _reveal(ip)


def allow_ping(ip: str, username: str) -> bool:
    return _ping(f"{ip} {username.lower()[:64]}")
