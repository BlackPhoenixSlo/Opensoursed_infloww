"""A run's concurrency slot, handed back while the run only waits.

The supervisor bounds automation runs with a slot pool (`_run_sem` /
`_bulk_sem`, automation_executor). Most of a chat run's slot time is not work:
it is `hold_with_typing` (the bot "typing" each bubble, ~20 s a reply). Holding
a slot through that wait is what made the slots, not the CPU, OF or LLM, the
first ceiling as the model count grows (ADR 0025).

`released(seconds, budget_s=...)` wraps such a wait: the run gives its permit
back, sleeps, and takes a permit again before it does real work. Everything
that orders and dedupes a run is NOT a slot and stays held across the wait:
the `(account, kind)` in-flight guard and run lock, the claimed job row, the
fan lease. So the freed permit can only go to a DIFFERENT (account, kind)
pair; per-fan ordering, cooldown and dedupe are untouched.

THE RULES the pool and `released()` keep:

- An operator's run (a job started from the app: `hold(pool, operator=True)`)
  never waits behind automation. It takes one of the pool's `reserve` permits,
  which only operator runs may use; with those busy it takes a shared permit
  ahead of every queued automation run, take-backs included. Automation never
  uses the reserve, so it stays at `n` permits; operators add at most
  `reserve` on top while they overflow nothing.
- A run taking its slot back is served before any fresh `hold()`: `SlotPool`
  keeps FIFO queues and drains the "back" one before the "fresh" one. A run
  mid-reply holds a fan lease and its run lock; a fresh run holds nothing yet.
- The take-back is bounded, once per run: all of a run's waits to take its
  slot back add up to at most `budget_s` (the caller passes
  `rhythm.INLINE_MAX_S`, 120 s). A reply has up to 7 holds and one run can
  answer several fans, so a per-hold bound would let the waits add up past
  the 900 s fan lease; a run-wide one keeps every reply inside it (holds of
  at most 60 s of typing a bubble, plus 120 s of waits). Past it, `SlotLost`
  is raised: the reply stops where it is (nothing more is sent). If part of
  the reply already landed (`SlotLost.sent`), the sender records it first
  (its "sent" path: state, cooldown) and then re-raises, so the next run does
  not send it again. The run ends as an error the executor retries.
- A run whose slot is gone never does slot work again. Cancelled, or raised,
  during the wait or the take-back: the slot stays released (`hold()`'s exit
  is a no-op, the count stays exact) and every later `released()` of that run
  raises `SlotLost`, so a caller that swallowed the cancel still sends nothing.
- Holds under `AUTOMATION_RELEASE_SLOT_MIN_HOLD_S` (default 3 s: an enter
  press, a jittered gap, a sticker beat) keep the slot: releasing them buys
  nothing and costs a queue.
- THE KILL SWITCH is `AUTOMATION_RELEASE_SLOT_ON_HOLD` (a lane_config switch,
  default 1 = on): 0 and no hold releases, no run lends its slot. The old one
  still works: a floor of 120 or more (`LEND_OFF_FLOOR_S`; no hold is that
  long, `rhythm.INLINE_MAX_S`) is off too. Both are read on every hold, so a
  value saved from the Concurrency panel applies at once (an env var, as
  always, at restart). `release_on()` is the one check.

Never release during a wait made while holding a lock another run may wait for
(e.g. `audiences.broadcast_lock`): the run would need a slot back to finish,
and the slots could all be held by runs waiting for its lock. No typing hold
runs under such a lock today; the write spacing in `of_write_paced`, which
does, never releases at all.

The slot lives in a ContextVar set by the run's own task. A task spawned
inside a run copies the context but is not the owner, so it never releases
the permit (only the owning task may). Outside a run (an operator write from
server.py) there is no slot and `released()` is a plain pass-through.

LENDING (send_welcome's paced pool, `_run_pool.run_paced`). A run whose slot
work happens in child tasks wraps them in `lend()`, and each child does its
work inside `borrowed()`. The children then share the one permit: it is held
while ANY of them is working, and handed back only while ALL of them sit in a
hold (and the run itself only waits for them). So per permit the work in
flight is what it was before (the pool's own concurrency, all on one slot);
only the waits stop pinning it. A child's take-back goes through the same
"back" queue and the same run-wide budget; children that need it at the same
time share one take-back (`_taking`). A child cancelled or raising mid-hold
leaves without taking the slot back, but does not end its siblings' slot
work: only a spent budget does (`lost`). After the body the run takes its
slot back like any hold. Lending is off with release (the kill switch):
then children keep the slot through their holds, as before.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
from collections import deque
from typing import AsyncIterator

import lane_config

log = logging.getLogger("of-relay.run_slot")


# A floor this high (rhythm.INLINE_MAX_S: no hold is that long) is the old
# kill switch, kept: no hold releases, and no run lends its slot.
LEND_OFF_FLOOR_S = 120


# Run slots by active models when nobody set AUTOMATION_MAX_CONCURRENT_RUNS
# (ADR 0025, the busy sweep after the operator tier): 4 up to 20 models, one
# more for each started 15 after (5 at 21-35, 6 at 36-50), clamped to 4..16.
AUTO_RUNS_MIN = 4
AUTO_RUNS_MAX = 16
AUTO_RUNS_FLAT_UNTIL = 20
AUTO_RUNS_PER_SLOT = 15


def auto_runs(models: int) -> int:
    """The run slots `models` active creators get by default."""
    extra = -(-(models - AUTO_RUNS_FLAT_UNTIL) // AUTO_RUNS_PER_SLOT)   # ceil
    return max(AUTO_RUNS_MIN, min(AUTO_RUNS_MAX, AUTO_RUNS_MIN + extra))


def release_floor_s() -> int:
    """The shortest hold that hands its slot back (and the kill switch). Read
    on every hold; the literals are what the panel and the timing model read."""
    return lane_config.resolve_live("AUTOMATION_RELEASE_SLOT_MIN_HOLD_S", 3)   # never "restart to apply"


def release_on() -> bool:
    """Do holds hand their slot back (and runs lend it)? The kill switch:
    `AUTOMATION_RELEASE_SLOT_ON_HOLD`=0 turns it off, as does the old floor of
    `LEND_OFF_FLOOR_S` or more. Read on every hold."""
    on = lane_config.resolve_switch("AUTOMATION_RELEASE_SLOT_ON_HOLD", True)
    return release_floor_s() < LEND_OFF_FLOOR_S and on


release_on()   # registers the floor and the switch with the Concurrency panel at import



class SlotLost(Exception):
    """The run gave its slot back and does not have it any more (the take-back
    budget is spent, or the run was cancelled mid-wait). Send nothing more.
    `sent`: how many bubbles of the reply already landed, set by the sender
    that knows, so its caller can record them before re-raising."""

    sent = 0


class SlotPool:
    """`asyncio.Semaphore(n)` with priority queues: `acquire(operator=True)`
    (a run an operator started) first, then `acquire(back=True)` (a run taking
    its slot back), then `acquire()` (a fresh run). Each queue is FIFO.
    `reserve` more permits serve operator runs only. `acquire` returns whether
    the permit came from the reserve; `release(reserve=...)` returns it there."""

    def __init__(self, n: int, reserve: int = 0) -> None:
        self.n = n
        self.free = n
        self.reserve = reserve
        self.reserve_free = reserve
        self._op: deque[asyncio.Future] = deque()
        self._back: deque[asyncio.Future] = deque()
        self._fresh: deque[asyncio.Future] = deque()

    def queued(self) -> tuple[int, int]:
        """(re-acquirers, fresh acquirers) queued."""
        return (sum(not f.done() for f in self._back), sum(not f.done() for f in self._fresh))

    def queued_operator(self) -> int:
        return sum(not f.done() for f in self._op)

    async def acquire(self, *, back: bool = False, operator: bool = False) -> bool:
        if operator:
            if self.reserve_free > 0:
                self.reserve_free -= 1
                return True
            if self.free > 0 and not self.queued_operator():
                self.free -= 1
                return False
            q = self._op
        else:
            if (self.free > 0 and not self.queued_operator() and not self.queued()[0]
                    and (back or not self.queued()[1])):
                self.free -= 1
                return False
            q = self._back if back else self._fresh
        fut = asyncio.get_running_loop().create_future()
        q.append(fut)
        try:
            return await fut
        except BaseException:
            if fut.done() and not fut.cancelled():
                self.release(reserve=fut.result())   # granted as we were cancelled: pass it on
            else:
                with contextlib.suppress(ValueError):
                    q.remove(fut)
            raise

    def resize(self, n: int) -> None:
        """Change the shared permits to `n`, live. Growing serves waiters now;
        shrinking takes effect as runs end (`free` may dip below 0 meanwhile:
        nobody is granted until it is above 0 again). The reserve is unchanged."""
        self.free += n - self.n
        self.n = n
        self._grant()

    def release(self, *, reserve: bool = False) -> None:
        if reserve:
            while self._op:              # a reserve permit goes to an operator run, or back
                fut = self._op.popleft()
                if not fut.done():
                    fut.set_result(True)
                    return
            self.reserve_free += 1
            return
        self.free += 1
        self._grant()

    def _grant(self) -> None:
        while self.free > 0 and (self._op or self._back or self._fresh):
            fut = (self._op or self._back or self._fresh).popleft()
            if not fut.done():
                self.free -= 1
                fut.set_result(False)


class RunSlot:
    """One permit of `pool`, held by the task that acquired it."""

    __slots__ = ("pool", "held", "lost", "owner", "releases", "waited_s",
                 "lending", "busy", "borrowers", "_taking", "operator", "reserve")

    def __init__(self, pool: SlotPool, *, operator: bool = False) -> None:
        self.pool = pool
        self.operator = operator         # an operator's run: the top tier, may use the reserve
        self.reserve = False             # the permit held came from the pool's reserve
        self.held = False
        self.lost = False                # given back and never taken again
        self.owner: asyncio.Task | None = None
        self.releases = 0                # holds that gave it back
        self.waited_s = 0.0              # total time spent taking it back (the run's budget)
        self.lending = False             # inside lend(): children share the permit
        self.busy = 0                    # borrowers working (not in a hold) right now
        self.borrowers = 0               # borrowers alive (working or in a hold)
        self._taking: asyncio.Lock | None = None

    def release(self) -> None:
        if self.held:
            self.held = False
            self.pool.release(reserve=self.reserve)

    async def take_back(self, budget_s: float) -> float:
        """Queue (ahead of fresh runs) for the permit, within what is left of
        the run's take-back budget; the wait, or SlotLost past the budget."""
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
        """A borrower starts working: make sure the shared permit is held
        (one take-back for every borrower that needs it now). Its wait."""
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
    """One child task's share of a lent slot (`borrowed()`); its own counters,
    so a child timing its hold leaves out only its own wait."""

    __slots__ = ("slot", "working", "releases", "waited_s")

    def __init__(self, slot: RunSlot) -> None:
        self.slot = slot
        self.working = False
        self.releases = 0                # holds of this child (the slot went back if all were idle)
        self.waited_s = 0.0              # this child's waits for the shared take-back

    @property
    def lost(self) -> bool:
        return self.slot.lost


_CURRENT: contextvars.ContextVar[RunSlot | None] = contextvars.ContextVar("run_slot", default=None)
_BORROW: contextvars.ContextVar[_Borrow | None] = contextvars.ContextVar("run_slot_borrow", default=None)


def _borrow() -> _Borrow | None:
    """This task's share of a lent slot, if it is a borrower of a slot still lent."""
    b = _BORROW.get()
    return b if b is not None and b.slot.lending and _CURRENT.get() is b.slot else None


@contextlib.asynccontextmanager
async def hold(pool: SlotPool, *, operator: bool = False) -> AsyncIterator[RunSlot]:
    """`async with sem:` for a run, made releasable by `released()` inside it.
    `operator`: a run an operator started from the app (see the rules)."""
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
    """Is this task working for an operator's run (its owner, a borrower, or
    any task it spawned: `run_of_task`, the same test dm_rate makes)? Its OF
    writes take the write gate's operator tier (write_gate.py)."""
    r = run_of_task()
    return bool(r is not None and r.operator)


def current() -> RunSlot | _Borrow | None:
    """The current run's slot, if this task owns one, or this task's share of
    a lent one (`borrowed()`). Its counters: `releases`, `waited_s`, `lost`."""
    b = _borrow()
    if b is not None:
        return b
    slot = _CURRENT.get()
    return slot if slot is not None and slot.owner is asyncio.current_task() else None


def run_of_task() -> RunSlot | None:
    """The run this task works for: its owner, a borrower, or any task the
    run spawned (the context is inherited), held or already ended. None
    outside every run (the app's own requests). For whose work it is, not
    for the slot's counters (`current`)."""
    return _CURRENT.get()


def waited_s() -> float:
    """This task's take-back wait so far (0 outside a run): the run's total
    for its owner, its own for a borrower. A caller timing a hold subtracts
    it to leave the slot queue out."""
    slot = current()
    return slot.waited_s if slot is not None else 0.0


@contextlib.asynccontextmanager
async def lend(*, budget_s: float) -> AsyncIterator[None]:
    """The owning run lends its slot to the child tasks it spawns in the body:
    they work inside `borrowed()`, and the permit is held only while one of
    them works. After the body the run takes its slot back (SlotLost past the
    run's budget). A no-op outside a run, in a borrower, or with release off.
    See the module docstring, LENDING."""
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
            slot.lost = slot.lost or not slot.held   # ending; never queue just to drop it
    if slot.held:
        return                       # a child was working at the end, or nobody released
    if slot.lost:
        raise SlotLost("this run gave its slot back and lost it; it sends nothing more")
    try:
        await slot.take_back(budget_s)
    except SlotLost:
        raise
    except BaseException:
        slot.lost = True             # cancelled while queued: the run is ending
        raise


@contextlib.asynccontextmanager
async def borrowed(*, budget_s: float) -> AsyncIterator[None]:
    """A child task's work on its parent's lent slot (`lend()`): the permit is
    held for the body, except for the body's holds (`released()`). A plain
    pass-through when the slot is not lent (the child shares it as before)."""
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


@contextlib.asynccontextmanager
async def released(seconds: float, *, budget_s: float) -> AsyncIterator[None]:
    """Give the current run's slot back for the body (a pure wait of about
    `seconds`), then take it back, ahead of fresh runs, as long as the run's
    take-back waits stay within `budget_s` in all. See the module docstring."""
    b = _borrow()
    if b is not None:
        async with _released_borrowed(b, seconds, budget_s):
            yield
        return
    slot = current()
    if slot is None or slot.lending:     # the lending owner only waits on its children
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
            slot.lost = True    # cancelled or raised mid-wait: the run is ending, don't queue
    try:
        await slot.take_back(budget_s)
    except SlotLost:
        raise
    except BaseException:
        slot.lost = True        # cancelled while queued: the run is ending
        raise


@contextlib.asynccontextmanager
async def _released_borrowed(b: _Borrow, seconds: float, budget_s: float) -> AsyncIterator[None]:
    """`released()` for a borrower: it stops working for the hold (the permit
    goes back if every borrower is idle) and works again after it."""
    slot = b.slot
    if slot.lost:
        raise SlotLost("this run gave its slot back and lost it; it sends nothing more")
    if not b.working or seconds < release_floor_s() or not release_on():
        yield
        return
    b.working = False
    b.releases += 1
    slot.idle()
    yield                    # cancelled / raised mid-hold: this child leaves idle; siblings go on
    b.waited_s += await slot.work(budget_s)
    b.working = True
