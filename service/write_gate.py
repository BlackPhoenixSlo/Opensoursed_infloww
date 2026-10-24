"""service/write_gate.py — one account's OnlyFans write spacing, operator first.

OnlyFans throttles writes per account, so `automation_executor.of_write_paced`
starts each write on an account at least its gap (11 s) after the one before.
This is the gate it waits at. Two rules (ADR 0025):

- SPACING: every grant is at least the previous grant's gap after it. A write
  arriving at an idle gate (nobody waiting, the gap since the last grant
  passed) goes at once; any other waits for its turn.
- ORDER: the waiters are served operator first (a write a person started in
  the app: a chat delete, a vault import, an operator's run), then automation,
  each in arrival order, but an operator never takes two turns in a row while
  automation waits: the tiers alternate. An operator write therefore waits at
  most two gaps (the write in flight and one automation write), never behind
  the whole automation backlog; and an automation write waits at most two gaps
  behind a streaming operator leg (a priority mass's sends, every one in the
  operator tier, would otherwise hold automation for the whole leg while it
  keeps its run slot, and a mass send its broadcast_lock). The spacing OF sees
  is the same as before.

The wait is a plain `await` on a future: it yields the event loop and holds
nothing but the caller's own state. The caller decides what it holds while it
waits (`of_write_paced` keeps the run's slot: see the note there).

A cancelled waiter is skipped when its turn comes. One cancelled in the same
loop turn it was granted spends that turn (the spacing never shrinks).

Pure asyncio, no relay imports, so a model or test can import it as the real gate.
"""
from __future__ import annotations

import asyncio
from collections import deque


class WriteGate:
    __slots__ = ("next_at", "_op", "_auto", "_timer", "_last_op")

    def __init__(self) -> None:
        self.next_at = 0.0               # loop time the next write may start
        self._op: deque[tuple[asyncio.Future, float]] = deque()
        self._auto: deque[tuple[asyncio.Future, float]] = deque()
        self._timer: asyncio.TimerHandle | None = None
        self._last_op = False            # the last grant was an operator's

    def waiting(self) -> tuple[int, int]:
        """(operator, automation) writers waiting."""
        return (sum(not f.done() for f, _ in self._op), sum(not f.done() for f, _ in self._auto))

    async def turn(self, gap: float, *, operator: bool = False) -> float:
        """Wait for this write's turn; the seconds waited. The next write may
        start `gap` seconds after this one does."""
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
        if now < self.next_at:               # moved on by a caller since it was armed
            self._arm(loop)
            return
        while self._op or self._auto:
            # Operator first, but not twice in a row while automation waits.
            q = self._auto if (self._auto and (self._last_op or not self._op)) else self._op
            fut, gap = q.popleft()
            if not fut.done():               # skip the cancelled
                fut.set_result(None)
                self.next_at = now + gap
                self._last_op = q is self._op
                break
        if self._op or self._auto:
            self._arm(loop)
