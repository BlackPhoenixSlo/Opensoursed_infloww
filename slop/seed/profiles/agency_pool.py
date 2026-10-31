"""`agency_inbox`'s shape (one Agency, its Creators, their Fans, an inbox of threads) with at
least MIN_CREATORS Creators at every scale (else the scale's): more Creators than the run slot
pool's 4 slots, and enough models for a walk model by model."""
from __future__ import annotations

from .. import World, agency, creators, fans, threads

MIN_CREATORS = 7


async def build(w: World) -> World:
    await agency.seed(w)
    cs = creators.seed(w, max(MIN_CREATORS, int(w.size["creators"])))
    fs = fans.seed(w, cs)
    threads.seed(w, fs)
    return w
