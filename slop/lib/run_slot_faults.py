from __future__ import annotations

from dataclasses import replace

CAP = ("run slots: never more automation runs hold a slot at once than the pool's size, and the "
       "pool fills up when more runs ask than it has slots")
FIFO = ("run slots: runs that queue for a slot get it in the order they asked (FIFO, nobody "
        "overtaken), and every one gets it")


def _fresh_runs_served_last_first() -> None:
    import run_slot_decide as rsd

    real = rsd.decide

    def lifo(p, ev):
        p2, eff = real(p, ev)
        if isinstance(ev, rsd.Acquire) and ev.waiter in p2.fresh:
            p2 = replace(p2, fresh=(ev.waiter, *p2.fresh[:-1]))
        return p2, eff

    rsd.decide = lifo


def _automation_ignores_the_cap() -> None:
    import run_slot_decide as rsd

    real = rsd.decide

    def uncapped(p, ev):
        if isinstance(ev, rsd.Acquire) and ev.tier != rsd.OP:
            return replace(p, free=p.free - 1), [rsd.Grant(ev.waiter, False)]
        return real(p, ev)

    rsd.decide = uncapped


def register(Fault) -> dict:
    return {
        "run-slot-fresh-runs-served-last-first": Fault(_fresh_runs_served_last_first, (FIFO,)),
        "run-slot-automation-ignores-the-cap": Fault(_automation_ignores_the_cap, (CAP,)),
    }
