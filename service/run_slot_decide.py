"""
The run slot pool's who-goes-next rules as a pure transition (docs/reducer-scan.md
"Non-React" 6; the rules in words: run_slot.py's module docstring):

    decide(pool, event) -> (pool', effects)

`pool` is a frozen `Pool`: the shared permits (`n`, `free`), the operator-only
reserve (`reserve`, `reserve_free`) and three FIFO queues of waiter ids, served
in this order: `op` (a run an operator started), `back` (a run taking its slot
back), `fresh` (a new run). No futures, no loop, no clock here: the shell
(`run_slot.SlotPool`) numbers each waiter, calls decide, keeps pool', and
performs the effects in order (resolves the waiter's future, or parks it).

Events (one per SlotPool entry point):

  Acquire(waiter, tier)   a run asks for a permit (tier: OP / BACK / FRESH)
  Release(reserve)        a run hands its permit back (to the reserve or shared); also
                          a waiter granted one as it was cancelled, passing it on
  Resize(n)               the shared permits change live
  Cancelled(waiter, tier) a queued waiter's task was cancelled: it leaves its tier's queue

Effect: Grant(waiter, reserve) (resolve its future with `reserve`); an Acquire with no
Grant parked the waiter in its tier. A waiter cancelled before its task ran its handler
is still queued and may be granted: the shell then feeds that permit straight back as a
Release (asyncio.Semaphore's pattern), so it goes to the next waiter in the same order.

Invariant (every reachable state; the tests' seeded walk asserts it): a free shared
permit means no queue holds anyone, and a free reserve permit means no operator waits.
So "straight in" needs only the free count: queued runs are never passed.

Importable without side effects (stdlib only).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Union, assert_never

Tier = Literal["op", "back", "fresh"]
OP: Tier = "op"
BACK: Tier = "back"
FRESH: Tier = "fresh"


@dataclass(frozen=True)
class Pool:
    n: int                        # shared permits (automation and operators)
    free: int                     # shared permits not held; < 0 after a shrink until runs end
    reserve: int = 0              # operator-only permits
    reserve_free: int = 0
    op: tuple[int, ...] = ()      # queued waiters, FIFO per tier
    back: tuple[int, ...] = ()
    fresh: tuple[int, ...] = ()


def new_pool(n: int, reserve: int = 0) -> Pool:
    return Pool(n=n, free=n, reserve=reserve, reserve_free=reserve)


# ── events ──
@dataclass(frozen=True)
class Acquire:
    waiter: int
    tier: Tier


@dataclass(frozen=True)
class Release:
    reserve: bool = False


@dataclass(frozen=True)
class Resize:
    n: int


@dataclass(frozen=True)
class Cancelled:
    waiter: int
    tier: Tier                    # the queue it parked in (its Acquire's)


Event = Union[Acquire, Release, Resize, Cancelled]


# ── effect ──
@dataclass(frozen=True)
class Grant:
    waiter: int
    reserve: bool                 # the permit came from the reserve (it goes back there)


def _queue(p: Pool, tier: Tier) -> tuple[int, ...]:
    match tier:
        case "op":
            return p.op
        case "back":
            return p.back
        case "fresh":
            return p.fresh
        case _:
            assert_never(tier)


def _with_queue(p: Pool, tier: Tier, q: tuple[int, ...]) -> Pool:
    match tier:
        case "op":
            return replace(p, op=q)
        case "back":
            return replace(p, back=q)
        case "fresh":
            return replace(p, fresh=q)
        case _:
            assert_never(tier)


def _drain(p: Pool) -> tuple[Pool, list[Grant]]:
    """Hand the free shared permits to waiters: operators, then take-backs, then fresh runs."""
    out: list[Grant] = []
    while p.free > 0 and (p.op or p.back or p.fresh):
        tier: Tier = OP if p.op else BACK if p.back else FRESH
        q = _queue(p, tier)
        p = _with_queue(replace(p, free=p.free - 1), tier, q[1:])
        out.append(Grant(q[0], False))
    return p, out


def decide(p: Pool, ev: Event) -> tuple[Pool, list[Grant]]:
    match ev:
        case Acquire(waiter=w, tier=tier):
            if tier == OP and p.reserve_free > 0:     # only operators use the reserve
                return replace(p, reserve_free=p.reserve_free - 1), [Grant(w, True)]
            if p.free > 0:                            # free => nobody queued (the invariant)
                return replace(p, free=p.free - 1), [Grant(w, False)]
            return _with_queue(p, tier, _queue(p, tier) + (w,)), []

        case Release(reserve=True):             # a reserve permit goes to an operator run, or back
            if p.op:
                return replace(p, op=p.op[1:]), [Grant(p.op[0], True)]
            return replace(p, reserve_free=p.reserve_free + 1), []

        case Release():
            return _drain(replace(p, free=p.free + 1))

        case Resize(n=n):                       # the reserve is unchanged
            return _drain(replace(p, free=p.free + n - p.n, n=n))

        case Cancelled(waiter=w, tier=tier):    # gone already (granted, or never parked): no-op
            return _with_queue(p, tier, tuple(x for x in _queue(p, tier) if x != w)), []

        case _:
            assert_never(ev)
