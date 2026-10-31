"""The run slot pool's break-it-once faults (service/run_slot_decide.py, checked by
scenarios/2026-10-30-run-slot-pool.py, where every Creator's run asks the real pool at once):
lib/faults.py merges `register(Fault)` into FAULTS. The check names live here and the
scenario imports them, so a target can never name a check that does not exist.

Both patch `run_slot_decide.decide` in the relay process (run_slot.SlotPool calls it through
the module, so the patch is what the real pool runs); the shell and everything else are as shipped.
"""
from __future__ import annotations

from dataclasses import replace

CAP = ("run slots: never more automation runs hold a slot at once than the pool's size, and the "
       "pool fills up when more runs ask than it has slots")
FIFO = ("run slots: runs that queue for a slot get it in the order they asked (FIFO, nobody "
        "overtaken), and every one gets it")


def _fresh_runs_served_last_first() -> None:
    """A fresh run that has to wait is queued at the FRONT of the fresh queue, not the back:
    the newest waiter is served first (the bug class of a fairness rule turned around:
    the first runs to ask can starve while new ones keep arriving). Counts, the cap and
    who may go straight in are untouched, so only the order check can see it."""
    import run_slot_decide as rsd

    real = rsd.decide

    def lifo(p, ev):
        p2, eff = real(p, ev)
        if isinstance(ev, rsd.Acquire) and ev.waiter in p2.fresh:   # it had to wait
            p2 = replace(p2, fresh=(ev.waiter, *p2.fresh[:-1]))
        return p2, eff

    rsd.decide = lifo


def _automation_ignores_the_cap() -> None:
    """Every automation run is let straight in, whatever is free (`free` goes below 0): the
    pool's size bounds nothing (the bug class of a dropped limit). Nobody queues, so the
    order check stays green; only the cap check can see it."""
    import run_slot_decide as rsd

    real = rsd.decide

    def uncapped(p, ev):
        if isinstance(ev, rsd.Acquire) and ev.tier != rsd.OP:
            return replace(p, free=p.free - 1), [rsd.Grant(ev.waiter, False)]
        return real(p, ev)

    rsd.decide = uncapped


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-run-slot-pool --break [--fault=...] (any scale: 7+ Creators, 4 slots)
        "run-slot-fresh-runs-served-last-first": Fault(_fresh_runs_served_last_first, (FIFO,)),
        "run-slot-automation-ignores-the-cap": Fault(_automation_ignores_the_cap, (CAP,)),
    }
