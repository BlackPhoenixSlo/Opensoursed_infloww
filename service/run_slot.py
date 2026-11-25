from __future__ import annotations

import asyncio
import contextlib
import contextvars
import itertools
import logging
import math
from typing import AsyncIterator

import lane_config
import run_slot_decide as rsd

log = logging.getLogger("of-relay.run_slot")


# A floor this high (no hold is that long) is the old kill switch: no hold releases, no run lends its slot.
LEND_OFF_FLOOR_S = 120


# Slots by active models: 4 up to 20, +1 per started 15 after, clamped 4..16.
AUTO_RUNS_MIN = 4
AUTO_RUNS_MAX = 16
AUTO_RUNS_FLAT_UNTIL = 20
AUTO_RUNS_PER_SLOT = 15


def auto_runs(models: int) -> int:
    extra = -(-(models - AUTO_RUNS_FLAT_UNTIL) // AUTO_RUNS_PER_SLOT)
    return max(AUTO_RUNS_MIN, min(AUTO_RUNS_MAX, AUTO_RUNS_MIN + extra))


# Sweeps cost ~5k slot-s/day per creator (measured); 2 up to 10 models, +1 per started 10, clamped 2..8 keeps the lane <=~50% busy.
AUTO_BULK_MIN = 2
AUTO_BULK_MAX = 8
AUTO_BULK_FLAT_UNTIL = 10
AUTO_BULK_PER_SLOT = 10


def auto_bulk(models: int) -> int:
    extra = -(-(models - AUTO_BULK_FLAT_UNTIL) // AUTO_BULK_PER_SLOT)
    return max(AUTO_BULK_MIN, min(AUTO_BULK_MAX, AUTO_BULK_MIN + extra))


def release_floor_s() -> int:
    return lane_config.resolve_live("AUTOMATION_RELEASE_SLOT_MIN_HOLD_S", 3)


def release_on() -> bool:
    on = lane_config.resolve_switch("AUTOMATION_RELEASE_SLOT_ON_HOLD", True)
    return release_floor_s() < LEND_OFF_FLOOR_S and on


release_on()



class SlotLost(Exception):

    sent = 0


class SlotPool:

    def __init__(self, n: int, reserve: int = 0) -> None:
        self._p = rsd.new_pool(n, reserve)
        self._wait: dict[int, asyncio.Future] = {}
        self._ids = itertools.count()

    n = property(lambda self: self._p.n)
    free = property(lambda self: self._p.free)
    reserve = property(lambda self: self._p.reserve)
    reserve_free = property(lambda self: self._p.reserve_free)

    def _step(self, ev: rsd.Event) -> None:
        evs = [ev]
        while evs:
            self._p, grants = rsd.decide(self._p, evs.pop(0))
            for g in grants:
                fut = self._wait.pop(g.waiter)
                if fut.done():
                    evs.append(rsd.Release(g.reserve))
                else:
                    fut.set_result(g.reserve)

    def queued(self) -> tuple[int, int]:
        return len(self._p.back), len(self._p.fresh)

    def queued_operator(self) -> int:
        return len(self._p.op)

    async def acquire(self, *, back: bool = False, operator: bool = False) -> bool:
        w = next(self._ids)
        tier = rsd.OP if operator else rsd.BACK if back else rsd.FRESH
        fut = self._wait[w] = asyncio.get_running_loop().create_future()
        self._step(rsd.Acquire(w, tier))
        try:
            return await fut
        except BaseException:
            self._wait.pop(w, None)
            if fut.done() and not fut.cancelled():
                self.release(reserve=fut.result())
            else:
                self._step(rsd.Cancelled(w, tier))
            raise

    def resize(self, n: int) -> None:
        self._step(rsd.Resize(n))

    def release(self, *, reserve: bool = False) -> None:
        self._step(rsd.Release(reserve))


class RunSlot:

    __slots__ = ("pool", "held", "lost", "owner", "releases", "waited_s",
                 "lending", "busy", "borrowers", "_taking", "operator", "reserve")

    def __init__(self, pool: SlotPool, *, operator: bool = False) -> None:
        self.pool = pool
        self.operator = operator
        self.reserve = False
        self.held = False
        self.lost = False
        self.owner: asyncio.Task | None = None
        self.releases = 0
        self.waited_s = 0.0
        self.lending = False
        self.busy = 0
        self.borrowers = 0
        self._taking: asyncio.Lock | None = None

    def release(self) -> None:
        if self.held:
            self.held = False
            self.pool.release(reserve=self.reserve)

    async def take_back(self, budget_s: float) -> float:
        loop = asyncio.get_running_loop()
        t = loop.time()
        try:
            reserve = await asyncio.wait_for(self.pool.acquire(back=True, operator=self.operator),
                                             max(0.0, budget_s - self.waited_s))
        except TimeoutError:
            self.lost = True
            self.waited_s += loop.time() - t
            log.warning("run_slot take-back budget spent: %.1fs of waits this run (budget %.0fs); "
                        "the reply stops here, nothing more is sent", self.waited_s, budget_s)
            raise SlotLost(f"slot not back within the run's {budget_s:.0f}s take-back budget") from None
        self.held, self.reserve = True, reserve
        w = loop.time() - t
        self.waited_s += w
        return w

    async def work(self, budget_s: float) -> float:
        if self.lost:
            raise SlotLost("this run gave its slot back and lost it; it sends nothing more")
        loop = asyncio.get_running_loop()
        t = loop.time()
        if not self.held:
            if self._taking is None:
                self._taking = asyncio.Lock()
            async with self._taking:
                if self.lost:
                    raise SlotLost("this run gave its slot back and lost it; it sends nothing more")
                if not self.held:
                    await self.take_back(budget_s)
        self.busy += 1
        return loop.time() - t

    def idle(self) -> None:
        """A borrower stops working (a hold, or it is done): the last one to
        stop hands the permit back, if another borrower is still in a hold.
        The last borrower to finish keeps it: the run goes on with it."""
        self.busy -= 1
        if self.busy == 0 and self.borrowers > 0 and self.lending and self.held:
            self.release()
            self.releases += 1


class _Borrow:

    __slots__ = ("slot", "working", "releases", "waited_s")

    def __init__(self, slot: RunSlot) -> None:
        self.slot = slot
        self.working = False
        self.releases = 0
        self.waited_s = 0.0

    @property
    def lost(self) -> bool:
        return self.slot.lost


_CURRENT: contextvars.ContextVar[RunSlot | None] = contextvars.ContextVar("run_slot", default=None)
_BORROW: contextvars.ContextVar[_Borrow | None] = contextvars.ContextVar("run_slot_borrow", default=None)


def _borrow() -> _Borrow | None:
    b = _BORROW.get()
    return b if b is not None and b.slot.lending and _CURRENT.get() is b.slot else None


@contextlib.asynccontextmanager
async def hold(pool: SlotPool, *, operator: bool = False) -> AsyncIterator[RunSlot]:
    reserve = await pool.acquire(operator=operator)
    slot = RunSlot(pool, operator=operator)
    slot.reserve = reserve
    slot.held = True
    slot.owner = asyncio.current_task()
    token = _CURRENT.set(slot)
    try:
        yield slot
    finally:
        _CURRENT.reset(token)
        slot.release()


def operator_run() -> bool:
    r = run_of_task()
    return bool(r is not None and r.operator)


def current() -> RunSlot | _Borrow | None:
    b = _borrow()
    if b is not None:
        return b
    slot = _CURRENT.get()
    return slot if slot is not None and slot.owner is asyncio.current_task() else None


def run_of_task() -> RunSlot | None:
    return _CURRENT.get()


def waited_s() -> float:
    slot = current()
    return slot.waited_s if slot is not None else 0.0


@contextlib.asynccontextmanager
async def lend(*, budget_s: float) -> AsyncIterator[None]:
    slot = _CURRENT.get()
    if (slot is None or slot.owner is not asyncio.current_task() or slot.lending
            or not slot.held or not release_on()):
        yield
        return
    slot.lending, slot.busy, slot.borrowers = True, 0, 0
    done = False
    try:
        yield
        done = True
    finally:
        slot.lending = False
        if not done:
            slot.lost = slot.lost or not slot.held
    if slot.held:
        return
    if slot.lost:
        raise SlotLost("this run gave its slot back and lost it; it sends nothing more")
    try:
        await slot.take_back(budget_s)
    except SlotLost:
        raise
    except BaseException:
        slot.lost = True
        raise


@contextlib.asynccontextmanager
async def borrowed(*, budget_s: float) -> AsyncIterator[None]:
    slot = _CURRENT.get()
    if slot is None or not slot.lending or _BORROW.get() is not None:
        yield
        return
    b = _Borrow(slot)
    slot.borrowers += 1
    try:
        b.waited_s += await slot.work(budget_s)
        b.working = True
        token = _BORROW.set(b)
        try:
            yield
        finally:
            _BORROW.reset(token)
    finally:
        slot.borrowers -= 1
        if b.working:
            b.working = False
            slot.idle()


# Never call while holding a lock another run may wait on (e.g. broadcast_lock): the take-back can deadlock against slot holders queued on that lock.
@contextlib.asynccontextmanager
async def released(seconds: float, *, budget_s: float) -> AsyncIterator[None]:
    b = _borrow()
    if b is not None:
        async with _released_borrowed(b, seconds, budget_s):
            yield
        return
    slot = current()
    if slot is None or slot.lending:
        yield
        return
    if slot.lost:
        raise SlotLost("this run gave its slot back and lost it; it sends nothing more")
    if not slot.held or seconds < release_floor_s() or not release_on():
        yield
        return
    slot.release()
    slot.releases += 1
    done = False
    try:
        yield
        done = True
    finally:
        if not done:
            slot.lost = True
    try:
        await slot.take_back(budget_s)
    except SlotLost:
        raise
    except BaseException:
        slot.lost = True
        raise


# `aw` must not call OF (of_pacing sizes OF calls by the slots) nor hold a lock another run waits on.
async def freed(aw, *, budget_s: float):
    err: Exception | None = None
    res = None
    try:
        async with released(math.inf, budget_s=budget_s):
            try:
                res, aw = await aw, None
            except Exception as e:  # noqa: BLE001 — re-raised below, slot back first
                err, aw = e, None
    finally:
        if aw is not None and hasattr(aw, "close"):
            aw.close()
    if err is not None:
        raise err
    return res


@contextlib.asynccontextmanager
async def _released_borrowed(b: _Borrow, seconds: float, budget_s: float) -> AsyncIterator[None]:
    slot = b.slot
    if slot.lost:
        raise SlotLost("this run gave its slot back and lost it; it sends nothing more")
    if not b.working or seconds < release_floor_s() or not release_on():
        yield
        return
    b.working = False
    b.releases += 1
    slot.idle()
    yield
    b.waited_s += await slot.work(budget_s)
    b.working = True
