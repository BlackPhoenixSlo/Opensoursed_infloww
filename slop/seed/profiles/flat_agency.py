"""One Agency, N Creators (w.data["flat_creators"], else the scale's `creators`), each with a captured OF
session written right after the Creator (seed/of_sessions.py: the relay's REAL OFClient, OF_WIRE runs only),
its Fans and an inbox. No neighbour Agency, no session-less Creator: every Creator is one a background job
may walk. The stub session creators.seed writes lives for the few ms until of_sessions overwrites it."""
from __future__ import annotations

from .. import World, agency, creators, fans, of_sessions, threads


async def build(w: World) -> World:
    await agency.seed(w)
    cs = creators.seed(w, int(w.data.pop("flat_creators", 0) or w.size["creators"]))
    of_sessions.seed(w, cs)
    fs = fans.seed(w, cs)
    threads.seed(w, fs)
    return w
