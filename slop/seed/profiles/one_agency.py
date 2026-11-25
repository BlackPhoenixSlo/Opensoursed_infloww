from __future__ import annotations

from .. import World, agency, fans, threads
from .. import creators as creators_seed

MODELS, BIG, NEIGHBOUR_MODELS = 50, 9, 1


async def build(w: World) -> World:
    await agency.seed(w, n=2)
    main, neighbour = (a["user_id"] for a in w.data["agencies"])
    cs = creators_seed.seed(w, MODELS + NEIGHBOUR_MODELS, owners=[main] * MODELS + [neighbour] * NEIGHBOUR_MODELS)
    for i, c in enumerate(cs):
        c["big"] = i < BIG
    fs = fans.seed(w, cs, {c["id"]: int(w.size["big_fans_per_creator" if c["big"] else "fans_per_creator"])
                           for c in cs})
    threads.seed(w, fs)
    w.data["no_chatters"] = {neighbour}
    return w
