"""service/bg_lane.py — one Creator's background lane sub-cap, shared by the event loop
and worker threads, and the loop-admitted slot a worker borrows (server._bg_admission,
server._priority_lane). Stdlib only, no server import.
"""
from __future__ import annotations

import asyncio
import collections
import threading
from dataclasses import dataclass


@dataclass(slots=True, eq=False)   # eq=False: deque.remove matches the waiter by identity
class _Waiter:
    granted: bool
    loop: asyncio.AbstractEventLoop | None   # None: a thread blocked in acquire()
    wake: asyncio.Future | threading.Event


class BgLane:
    """One Creator's background sub-cap, one count shared by the event loop and
    worker threads (it was a threading semaphore, acquired in the worker).

    That shape let a flood of background reads each take a worker thread FIRST and
    then block on the sub-cap, so the thread pools filled with waiters and a user's
    tap waited for a thread, not a lane. Now a background request waits for its slot
    ON THE LOOP (`admit`, through server._bg_admission) before any thread is taken, and
    its worker borrows that slot (`BgLease`). A server-side caller already in a
    thread (server._priority_lane_background) still blocks in `acquire()`, counted as
    `threads_waiting_background`. One FIFO for both kinds, so the cap is exact and
    neither starves the other. `acquire(blocking=False)` / `release()` keep the
    semaphore's API (release past zero raises ValueError, as BoundedSemaphore)."""

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
        """Take a slot, waiting on the loop. Returns whether it had to wait."""
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
            if granted:  # handed over as we were cancelled: pass it on
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
            w.granted = True  # the slot moves to `w`: `held` stays
        if w.loop is None:
            w.wake.set()
            return
        try:
            w.loop.call_soon_threadsafe(_grant, w.wake)
        except RuntimeError:  # its loop is closed: nobody will take it
            self.release()


def _grant(fut: asyncio.Future) -> None:
    if not fut.done():  # cancelled meanwhile: `admit`'s handler passes the slot on
        fut.set_result(None)


_lease_lock = threading.Lock()


class BgLease:
    """A background slot the loop took for one flight or request (server._bg_admission).
    server._priority_lane borrows it in the worker instead of acquiring; one borrower at
    a time (a second, e.g. a parallel child, acquires as usual). Freed when the
    owner left AND no worker holds it: a cancelled request whose thread is still on
    OF keeps the slot until that thread is done."""

    __slots__ = ("aid", "lane", "waited", "in_use", "closed")

    def __init__(self, aid: str, lane: BgLane, waited: float) -> None:
        self.aid, self.lane, self.waited = aid, lane, waited
        self.in_use = self.closed = False

    def borrow(self, aid: str) -> bool:
        with _lease_lock:
            if aid != self.aid or self.in_use or self.closed:
                return False
            self.in_use = True
            return True

    def take_wait(self) -> float:
        w, self.waited = self.waited, 0.0
        return w

    def give_back(self) -> None:
        with _lease_lock:
            self.in_use = False
            free = self.closed
        if free:
            self.lane.release()

    def close(self) -> None:
        with _lease_lock:
            self.closed = True
            free = not self.in_use
        if free:
            self.lane.release()
