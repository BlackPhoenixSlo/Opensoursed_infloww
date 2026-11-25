from __future__ import annotations

from .. import World, agency, creators, fans, threads


async def build(w: World) -> World:
    await agency.seed(w)
    cs = creators.seed(w)
    fs = fans.seed(w, cs)
    threads.seed(w, fs)
    return w
