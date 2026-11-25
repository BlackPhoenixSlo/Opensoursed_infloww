from __future__ import annotations

import asyncio
import collections
import threading
from dataclasses import dataclass


# eq=False: deque.remove matches the waiter by identity
@dataclass(slots=True, eq=False)
class _Waiter:
    granted: bool
    loop: asyncio.AbstractEventLoop | None
    wake: asyncio.Future | threading.Event


# Waits for its slot on the loop before taking a thread: a flood of waiters must not fill the thread pools ahead of a user's tap
class BgLane:

    def __init__(self, cap: int) -> None:
        self.cap, self.held = cap, 0
        self._lock = threading.Lock()
        self._waiters: collections.deque[_Waiter] = collections.deque()

    def _take(self) -> bool:
        if self.held < self.cap and not self._waiters:
            self.held += 1
            return True
        return False

    def acquire(self, blocking: bool = True) -> bool:
        with self._lock:
            if self._take():
                return True
            if not blocking:
                return False
            w = _Waiter(False, None, threading.Event())
            self._waiters.append(w)
        w.wake.wait()
        return True

    async def admit(self) -> bool:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._take():
                return False
            w = _Waiter(False, loop, loop.create_future())
            self._waiters.append(w)
        try:
            await w.wake
        except BaseException:
            with self._lock:
                granted = w.granted
                if not granted:
                    self._waiters.remove(w)
            if granted:
                self.release()
            raise
        return True

    def release(self) -> None:
        with self._lock:
            if not self._waiters:
                if self.held <= 0:
                    raise ValueError("BgLane released too many times")
                self.held -= 1
                return
            w = self._waiters.popleft()
            w.granted = True
        if w.loop is None:
            w.wake.set()
            return
        try:
            w.loop.call_soon_threadsafe(_grant, w.wake)
        except RuntimeError:
            self.release()


def _grant(fut: asyncio.Future) -> None:
    if not fut.done():
        fut.set_result(None)


_lease_lock = threading.Lock()


# A parallel child waits for THIS lease, never queues on the lane: two requests each holding a slot with a child queued deadlocked cap 2; freed when owner left AND no worker holds it
class BgLease:

    __slots__ = ("aid", "lane", "waited", "in_use", "closed", "owner", "_cond")

    def __init__(self, aid: str, lane: BgLane, waited: float) -> None:
        self.aid, self.lane, self.waited = aid, lane, waited
        self.in_use = self.closed = False
        self.owner = 0
        self._cond = threading.Condition(_lease_lock)

    def borrow(self, aid: str, wait: bool = False) -> bool:
        me = threading.get_ident()
        with self._cond:
            while True:
                if aid != self.aid or self.closed:
                    return False
                if not self.in_use:
                    self.in_use, self.owner = True, me
                    return True
                if not wait or self.owner == me:
                    return False
                self._cond.wait()

    def take_wait(self) -> float:
        w, self.waited = self.waited, 0.0
        return w

    def give_back(self) -> None:
        with self._cond:
            self.in_use, self.owner = False, 0
            free = self.closed
            self._cond.notify()
        if free:
            self.lane.release()

    def close(self) -> None:
        with self._cond:
            self.closed = True
            free = not self.in_use
            self._cond.notify_all()
        if free:
            self.lane.release()
