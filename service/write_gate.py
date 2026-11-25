from __future__ import annotations

import asyncio
from collections import deque


class WriteGate:
    __slots__ = ("next_at", "_op", "_auto", "_timer", "_last_op")

    def __init__(self) -> None:
        self.next_at = 0.0
        self._op: deque[tuple[asyncio.Future, float]] = deque()
        self._auto: deque[tuple[asyncio.Future, float]] = deque()
        self._timer: asyncio.TimerHandle | None = None
        # The tiers alternate: an operator never takes two turns in a row while automation waits.
        self._last_op = False

    def waiting(self) -> tuple[int, int]:
        return (sum(not f.done() for f, _ in self._op), sum(not f.done() for f, _ in self._auto))

    async def turn(self, gap: float, *, operator: bool = False) -> float:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        if t0 >= self.next_at and not self.waiting()[0] and not self.waiting()[1]:
            self.next_at = t0 + gap
            self._last_op = operator
            return 0.0
        fut = loop.create_future()
        (self._op if operator else self._auto).append((fut, gap))
        self._arm(loop)
        await fut
        return loop.time() - t0

    def _arm(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._timer is None:
            self._timer = loop.call_at(self.next_at, self._grant, loop)

    def _grant(self, loop: asyncio.AbstractEventLoop) -> None:
        self._timer = None
        now = loop.time()
        if now < self.next_at:
            self._arm(loop)
            return
        while self._op or self._auto:
            # Operator first, but not twice in a row while automation waits.
            q = self._auto if (self._auto and (self._last_op or not self._op)) else self._op
            fut, gap = q.popleft()
            if not fut.done():
                fut.set_result(None)
                self.next_at = now + gap
                self._last_op = q is self._op
                break
        if self._op or self._auto:
            self._arm(loop)
