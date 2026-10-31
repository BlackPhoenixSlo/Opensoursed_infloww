"""The run slot pool (service/run_slot_decide.py, lib/run_slot_faults.py names the checks) under
every Creator's follow-up run asking at once.

World: `agency_pool` (`agency_inbox`'s shape with at least 7 Creators, so more runs ask than
the pool's 4 slots at every scale) + seed/followup_drip.py (lib/followup.py `setup`, as
2026-10-30-followup-drip). Load: two follow-up ticks, each `POST /__slop/run-automation` (kind
`send_followup`) for every Creator at once (`send_followup` holds its slot for the whole run, so
all are fresh runs; the first tick nudges, the second finds every due fan held by the gap).

Invariants, from the hook's ask / got / done stamps: never more runs holding a slot than the
pool's size, and it fills when more ask (CAP); queued runs are granted in the order they asked,
every one (FIFO). Small (7 Creators, 4 slots) queues 3 per tick, medium (10) 6; a run where
nobody queued SKIPs both with that reason. Budget: the hook's round trip per run (slot wait included), p95,
vs the last green run.

Faked or bypassed, declared: as lib/followup.py (DeepSeek at its HTTP boundary, OF's send, the
supervisor's cadence, the DM rate via the real route). No `--users` streams: this flow is the
pool, not the fan-out (2026-10-30-followup-drip watches that). SLOP_LIVE=1: every check SKIPs.

Break-it-once, at any scale: run-slot-fresh-runs-served-last-first (FIFO, the scenario's FAULT)
and --fault=run-slot-automation-ignores-the-cap (CAP) patch the pool's decide().
"""
from __future__ import annotations

import asyncio

from slop.lib import followup
from slop.lib import run_slot_faults as slots

PROFILE = "agency_pool"   # docstring: more Creators than run slots at every scale
UI = False
FAULT = "run-slot-fresh-runs-served-last-first"
P95_VS_LAST = (1.5, 300)


def _slot_checks(ctx, ticks: list[dict]) -> None:
    """The run slot pool from outside (service/run_slot_decide.py): every run's ask / got /
    done on the hook's one counter (lib/relay.py `/__slop/run-automation`). A run that went
    straight in got the very next stamp after its ask (no await between them), so one that
    waited is exact. Only these runs use the pool here (no supervisor, no take-backs:
    send_followup has no typing hold), so they are all fresh runs and FIFO is the rule."""
    got = [t["slot"] for t in ticks if (t["slot"] or {}).get("done") is not None]
    lost = [t["aid"] for t in ticks if (t["slot"] or {}).get("done") is None]
    n = max((s["n"] for s in got), default=0)

    def peak(start: str) -> int:
        cur = top = 0
        for _, d in sorted([(s[start], 1) for s in got] + [(s["done"], -1) for s in got]):
            cur += d
            top = max(top, cur)
        return top

    held, asking = peak("got"), peak("ask")
    waited = sorted((s for s in got if s["got"] != s["ask"] + 1), key=lambda s: s["ask"])
    by_ask = [s["got"] for s in sorted(got, key=lambda s: s["ask"])]
    overtaken = sum(1 for a, b in zip(by_ask, by_ask[1:]) if b < a)
    waits = sorted(s["wait_ms"] for s in waited)
    ctx.metric("run_slots", {"n": n, "runs": len(ticks), "peak_asking": asking, "peak_held": held,
                             "waited": len(waited), "wait_ms_max": waits[-1] if waits else 0,
                             "wait_ms_p50": waits[len(waits) // 2] if waits else 0})
    if asking <= n and not lost:
        why = f"at most {asking} runs asked at once for {n} slots: nobody queued"
        ctx.skip(slots.CAP, why)
        ctx.skip(slots.FIFO, why)
        return
    ctx.check(slots.CAP, not lost and held <= n and held == min(n, asking),
              slots=n, peak_held=held, peak_asking=asking, lost=lost[:5])
    ctx.check(slots.FIFO, not lost and overtaken == 0, slots=n, waited=len(waited),
              overtaken=overtaken, lost=lost[:5], wait_ms_max=waits[-1] if waits else 0)


async def run(ctx) -> None:
    if followup.refuse_live(ctx, (slots.CAP, slots.FIFO)):
        return
    await followup.setup(ctx, PROFILE)
    aids = [c["id"] for c in ctx.world.data["creators"]]
    ticks = []
    for stage in ("tick1", "tick2"):
        ctx.rec.stage = stage
        ticks += await asyncio.gather(*(followup.tick(ctx, a) for a in aids))
    ctx.rec.stage = None
    _slot_checks(ctx, ticks)
    bad = [t["aid"] for t in ticks if t["status"] != 200]
    ms = sorted(t["ms"] for t in ticks)
    p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
    ctx.metric("p95_vs_last_green", {"run-automation round trip, slot wait included": round(p95, 1)})
    ctx.note(f"{len(ticks)} runs over {len(aids)} Creators, {len(bad)} non-200; round trip p95 {p95:.0f} ms")
