from __future__ import annotations

from .. import World, agency, creators, fans, of_sessions, threads


async def build(w: World) -> World:
    await agency.seed(w)
    cs = creators.seed(w, int(w.data.pop("flat_creators", 0) or w.size["creators"]))
    of_sessions.seed(w, cs)
    fs = fans.seed(w, cs)
    threads.seed(w, fs)
    return w
