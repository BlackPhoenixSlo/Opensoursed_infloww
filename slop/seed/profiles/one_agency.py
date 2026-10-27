"""One chatting Agency holding all 50 models on ONE relay (18-chatter-crowd.md §10, the
owner's real case). Agency 0 (the run's owner, `w.owner`) has the 50 Creators; 9 are big,
as in `fleet_failover` (3 per shard there), so the fan-DM mix is the same: 9 x 50/min +
41 x 5/min. Big: `big_fans_per_creator` fans each, the rest `fans_per_creator`; threads as
seed/threads.py.

Plus a neighbour Agency with 1 normal Creator and no chatters (`w.data["no_chatters"]`): an
instance is multi-agency, and it keeps the "nothing of another Agency" checks live (no
chatter and not the owner may ever see it)."""
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
