"""An Agency with Creators, their Fans and an inbox of threads.
small 3x50 fans, medium 10x500 (5k), huge 10x5000 (50k fans) — see seed.SCALES."""
from __future__ import annotations

from .. import World, agency, creators, fans, threads


async def build(w: World) -> World:
    await agency.seed(w)
    cs = creators.seed(w)
    fs = fans.seed(w, cs)
    threads.seed(w, fs)
    return w
