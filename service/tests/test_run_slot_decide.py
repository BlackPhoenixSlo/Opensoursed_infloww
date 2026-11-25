#!/usr/bin/env python3
from __future__ import annotations

import _harness

import random  # noqa: E402

from run_slot_decide import (  # noqa: E402
    BACK, FRESH, OP, Acquire, Cancelled, Grant, Pool, Release, Resize, decide, new_pool,
)


def P(n=2, free=None, reserve=0, reserve_free=None, op=(), back=(), fresh=()) -> Pool:
    return Pool(n=n, free=n if free is None else free, reserve=reserve,
                reserve_free=reserve if reserve_free is None else reserve_free,
                op=tuple(op), back=tuple(back), fresh=tuple(fresh))


def run(p: Pool, *events):
    """Fold events; every effect in order."""
    out = []
    for ev in events:
        p, eff = decide(p, ev)
        out += eff
    return p, out


def case_acquire_table():
    W = 99
    rows = [
        (P(free=1), FRESH, Grant(W, False), dict(free=0)),
        (P(free=1), BACK, Grant(W, False), dict(free=0)),
        (P(free=0), FRESH, None, dict(fresh=(W,))),
        (P(free=0, fresh=[1]), FRESH, None, dict(fresh=(1, W))),
        (P(free=0, fresh=[1]), BACK, None, dict(back=(W,))),
        (P(free=0, op=[1]), BACK, None, dict(back=(W,))),
        (P(free=-1), BACK, None, dict(back=(W,))),
        (P(free=0, reserve=1), FRESH, None, dict(fresh=(W,))),
        (P(free=0, reserve=1), BACK, None, dict(back=(W,))),
        (P(free=0, reserve=1, back=[1], fresh=[2]), OP, Grant(W, True), dict(reserve_free=0)),
        (P(free=1, reserve=1), OP, Grant(W, True), dict(reserve_free=0)),
        (P(free=1, reserve=1, reserve_free=0), OP, Grant(W, False), dict(free=0)),
        (P(free=0, reserve=1, reserve_free=0), OP, None, dict(op=(W,))),
        (P(free=0, reserve=1, reserve_free=0, op=[1]), OP, None, dict(op=(1, W))),
    ]
    for i, (p, tier, grant, changed) in enumerate(rows):
        p2, effects = decide(p, Acquire(W, tier))
        assert effects == ([grant] if grant else []), (i, tier, effects)
        want = {k: getattr(p, k) for k in Pool.__dataclass_fields__} | changed
        got = {k: getattr(p2, k) for k in Pool.__dataclass_fields__}
        assert got == want, (i, tier, got, want)


def case_priority_order():
    p = P(n=1, free=0)
    arrivals = [(1, FRESH), (2, BACK), (3, FRESH), (4, OP), (5, BACK), (6, OP), (7, FRESH)]
    p, granted = run(p, *(Acquire(w, t) for w, t in arrivals))
    assert granted == [] and len(p.op + p.back + p.fresh) == len(arrivals), (granted, p)
    p, grants = run(p, *[Release()] * len(arrivals))
    assert [g.waiter for g in grants] == [4, 6, 2, 5, 1, 3, 7], grants
    assert all(not g.reserve for g in grants)
    assert (p.free, p.op, p.back, p.fresh) == (0, (), (), ()), p
    p, eff = decide(p, Release())
    assert eff == [] and p.free == 1


def case_release_wakes_one():
    rows = [
        (P(n=2, free=0, back=[1], fresh=[2, 3]), [Grant(1, False)], 0, ((), (2, 3))),
        (P(n=2, free=0, fresh=[2, 3]), [Grant(2, False)], 0, ((), (3,))),
        (P(n=2, free=0, op=[9], fresh=[2]), [Grant(9, False)], 0, ((), (2,))),
        (P(n=2, free=0), [], 1, ((), ())),
        (P(n=2, free=-1, fresh=[2]), [], 0, ((), (2,))),
    ]
    for i, (p, eff, free, queues) in enumerate(rows):
        p2, effects = decide(p, Release())
        assert effects == eff, (i, effects)
        assert p2.free == free and (p2.back, p2.fresh) == queues, (i, p2)


def case_reserve_release_table():
    rows = [
        (P(free=0, reserve=1, reserve_free=0, op=[5, 6]), [Grant(5, True)], 0, (6,)),
        (P(free=0, reserve=1, reserve_free=0, back=[1], fresh=[2]), [], 1, ()),
        (P(free=1, reserve=2, reserve_free=0), [], 1, ()),
    ]
    for i, (p, eff, reserve_free, op) in enumerate(rows):
        p2, effects = decide(p, Release(reserve=True))
        assert effects == eff, (i, effects)
        assert (p2.reserve_free, p2.op, p2.free, p2.back, p2.fresh) == (reserve_free, op, p.free, p.back, p.fresh), (i, p2)


def case_cancel_table():
    full = P(n=1, free=0, reserve=1, reserve_free=0, op=[1], back=[2], fresh=[3, 4])
    rows = [
        (Cancelled(3, FRESH), [], (1,), (2,), (4,), 0, 0),
        (Cancelled(1, OP), [], (), (2,), (3, 4), 0, 0),
        (Cancelled(2, BACK), [], (1,), (), (3, 4), 0, 0),
        (Cancelled(42, FRESH), [], (1,), (2,), (3, 4), 0, 0),
        (Release(reserve=False), [Grant(1, False)], (), (2,), (3, 4), 0, 0),
        (Release(reserve=True), [Grant(1, True)], (), (2,), (3, 4), 0, 0),
    ]
    for i, (ev, eff, op, back, fresh, free, rf) in enumerate(rows):
        p2, effects = decide(full, ev)
        assert effects == eff, (i, effects)
        assert (p2.op, p2.back, p2.fresh, p2.free, p2.reserve_free) == (op, back, fresh, free, rf), (i, p2)
    p, eff = run(P(n=1, free=0, fresh=[3, 4]), Cancelled(3, FRESH), Release())
    assert eff == [Grant(4, False)], eff
    p, eff = decide(P(free=0, reserve=1, reserve_free=0, fresh=[3]), Release(reserve=True))
    assert eff == [] and p.reserve_free == 1 and p.fresh == (3,), (eff, p)


def case_resize_table():
    rows = [
        (P(n=1, free=0, back=[1], fresh=[2, 3]), 3, [Grant(1, False), Grant(2, False)], 0),
        (P(n=1, free=0, fresh=[2]), 4, [Grant(2, False)], 2),
        (P(n=3, free=0, fresh=[2]), 1, [], -2),
        (P(n=3, free=3), 1, [], 1),
        (P(n=2, free=0, reserve=1, reserve_free=0, op=[9]), 2, [], 0),
        (P(n=2, free=0, reserve=1, reserve_free=0, op=[9], back=[1]), 3, [Grant(9, False)], 0),
    ]
    for i, (p, n, eff, free) in enumerate(rows):
        p2, effects = decide(p, Resize(n))
        assert effects == eff, (i, effects)
        assert (p2.n, p2.free, p2.reserve, p2.reserve_free) == (n, free, p.reserve, p.reserve_free), (i, p2)
    p = P(n=1, free=-2, fresh=[7])
    p, eff = run(p, Release(), Release())
    assert eff == [] and p.free == 0
    p, eff = decide(p, Release())
    assert eff == [Grant(7, False)] and p.free == 0


def case_caps_hold_on_a_seeded_walk():
    rng = random.Random(20261030)
    p = new_pool(3, reserve=1)
    held: dict[int, tuple[str, bool]] = {}
    tiers: dict[int, str] = {}
    w = 0
    granted_last: list[int] = []
    for _ in range(2000):
        r = rng.random()
        if r < 0.45:
            w += 1
            tier = rng.choice([OP, BACK, FRESH, FRESH, BACK])
            tiers[w] = tier
            ev = Acquire(w, tier)
        elif r < 0.85 and held:
            x = rng.choice(sorted(held))
            ev = Release(held.pop(x)[1])
        elif r < 0.92 and (p.op or p.back or p.fresh):
            x = rng.choice(p.op + p.back + p.fresh)
            ev = Cancelled(x, tiers[x])
        elif r < 0.95 and granted_last:
            ev = Release(held.pop(rng.choice(granted_last))[1])
        elif r < 0.97:
            ev = Resize(rng.choice([1, 2, 3, 5]))
        else:
            granted_last = []
            continue
        queues = {t: list(getattr(p, t)) for t in (OP, BACK, FRESH)}
        p2, effects = decide(p, ev)
        granted_last = [e.waiter for e in effects if isinstance(ev, (Release, Resize))]
        for e in effects:
            if isinstance(e, Grant):
                held[e.waiter] = (tiers[e.waiter], e.reserve)
                assert not (e.reserve and tiers[e.waiter] != OP), ("automation got a reserve permit", e)
                if isinstance(ev, (Release, Resize)):
                    top = next(t for t in (OP, BACK, FRESH) if queues[t])
                    assert e.waiter == queues[top].pop(0), (ev, e, queues)
        p = p2
        shared = sum(1 for _, r_ in held.values() if not r_)
        reserved = sum(1 for _, r_ in held.values() if r_)
        assert p.free + shared == p.n, ("shared count drifted", p, shared)
        assert p.reserve_free + reserved == p.reserve, ("reserve count drifted", p, reserved)
        if any(isinstance(e, Grant) and not e.reserve for e in effects):
            assert p.free >= 0, ("granted over the cap", p, shared)
        queued = p.op + p.back + p.fresh
        assert len(set(queued)) == len(queued) and not set(queued) & set(held), ("a waiter twice", p)
        assert not (p.free > 0 and queued), ("a permit free while someone waits", p)
        assert not (p.reserve_free > 0 and p.op), ("a reserve permit free while an operator waits", p)


def case_decide_never_mutates():
    p = P(n=1, free=0, reserve=1, reserve_free=0, op=[1], back=[2], fresh=[3])
    snap = repr(p)
    for ev in (Acquire(9, FRESH), Acquire(9, OP), Release(), Release(True), Resize(3), Cancelled(2, BACK),
               Cancelled(9, OP)):
        p2, _ = decide(p, ev)
        assert repr(p) == snap and p2 is not p, ev


_harness.run()
