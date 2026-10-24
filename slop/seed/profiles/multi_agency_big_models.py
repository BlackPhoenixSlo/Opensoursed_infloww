"""Five Agencies, twenty Creators; three of them big. Agency 0 (the run's owner,
the one the UI signs in as) holds the 3 big Creators plus 2 normal ones, so its
All Models inbox has 5 models; the other 15 Creators spread over Agencies 1-4.
Big: `big_fans_per_creator` fans each (small 2k, medium 10k, huge 50k); normal:
`fans_per_creator` (50 / 500 / 5k). Threads as seed/threads.py."""
from __future__ import annotations

from .. import World, agency, creators, fans, threads

AGENCIES, CREATORS, BIG, UI_MODELS = 5, 20, 3, 5


async def build(w: World) -> World:
    await agency.seed(w, n=AGENCIES)
    ags = [a["user_id"] for a in w.data["agencies"]]
    owners = [ags[0]] * UI_MODELS + [ags[1 + i % (AGENCIES - 1)] for i in range(CREATORS - UI_MODELS)]
    cs = creators.seed(w, CREATORS, owners=owners)
    big = {c["id"] for c in cs[:BIG]}
    for c in cs:
        c["big"] = c["id"] in big
    fs = fans.seed(w, cs, {c["id"]: int(w.size["big_fans_per_creator" if c["big"] else "fans_per_creator"])
                           for c in cs})
    threads.seed(w, fs)
    return w
