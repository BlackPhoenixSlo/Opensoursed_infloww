from __future__ import annotations

from .. import World, agency, creators, fans, threads

MIN_CREATORS = 7


async def build(w: World) -> World:
    await agency.seed(w)
    cs = creators.seed(w, max(MIN_CREATORS, int(w.size["creators"])))
    fs = fans.seed(w, cs)
    threads.seed(w, fs)
    return w
