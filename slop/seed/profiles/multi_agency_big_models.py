from __future__ import annotations

from .. import World, agency, fans, threads
from .. import creators as creators_seed

AGENCIES, CREATORS, BIG, UI_MODELS = 5, 20, 3, 5


async def build(w: World, creators: int = CREATORS) -> World:
    await agency.seed(w, n=AGENCIES)
    ags = [a["user_id"] for a in w.data["agencies"]]
    owners = [ags[0]] * UI_MODELS + [ags[1 + i % (AGENCIES - 1)] for i in range(creators - UI_MODELS)]
    cs = creators_seed.seed(w, creators, owners=owners)
    big = {c["id"] for c in cs[:BIG]}
    for c in cs:
        c["big"] = c["id"] in big
    fs = fans.seed(w, cs, {c["id"]: int(w.size["big_fans_per_creator" if c["big"] else "fans_per_creator"])
                           for c in cs})
    threads.seed(w, fs)
    return w
