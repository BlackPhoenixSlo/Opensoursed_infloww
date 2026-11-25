from __future__ import annotations

import asyncio

from slop.lib import followup
from slop.lib import run_slot_faults as slots

PROFILE = "agency_pool"
UI = False
FAULT = "run-slot-fresh-runs-served-last-first"
P95_VS_LAST = (1.5, 300)


def _slot_checks(ctx, ticks: list[dict]) -> None:
    got = [t["slot"] for t in ticks if (t["slot"] or {}).get("done") is not None]
    lost = [t["aid"] for t in ticks if (t["slot"] or {}).get("done") is None]
    n = max((s["n"] for s in got), default=0)

    def peak(start: str) -> int:
        cur = top = 0
        for _, d in sorted([(s[start], 1) for s in got] + [(s["done"], -1) for s in got]):
            cur += d
            top = max(top, cur)
        return top

    # the pool's own peak of permits out, not got..done overlap: a run frees its permit around its model call and takes it back
    held, asking = max((s.get("in_use", 0) for s in got), default=0), peak("ask")
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
