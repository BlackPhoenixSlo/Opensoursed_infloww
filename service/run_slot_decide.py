from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Union, assert_never

Tier = Literal["op", "back", "fresh"]
OP: Tier = "op"
BACK: Tier = "back"
FRESH: Tier = "fresh"


@dataclass(frozen=True)
class Pool:
    n: int
    free: int
    reserve: int = 0
    reserve_free: int = 0
    op: tuple[int, ...] = ()
    back: tuple[int, ...] = ()
    fresh: tuple[int, ...] = ()


def new_pool(n: int, reserve: int = 0) -> Pool:
    return Pool(n=n, free=n, reserve=reserve, reserve_free=reserve)


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
    tier: Tier


Event = Union[Acquire, Release, Resize, Cancelled]


@dataclass(frozen=True)
class Grant:
    waiter: int
    reserve: bool


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
            if tier == OP and p.reserve_free > 0:
                return replace(p, reserve_free=p.reserve_free - 1), [Grant(w, True)]
            if p.free > 0:
                return replace(p, free=p.free - 1), [Grant(w, False)]
            return _with_queue(p, tier, _queue(p, tier) + (w,)), []

        case Release(reserve=True):
            if p.op:
                return replace(p, op=p.op[1:]), [Grant(p.op[0], True)]
            return replace(p, reserve_free=p.reserve_free + 1), []

        case Release():
            return _drain(replace(p, free=p.free + 1))

        case Resize(n=n):
            return _drain(replace(p, free=p.free + n - p.n, n=n))

        case Cancelled(waiter=w, tier=tier):
            return _with_queue(p, tier, tuple(x for x in _queue(p, tier) if x != w)), []

        case _:
            assert_never(ev)
