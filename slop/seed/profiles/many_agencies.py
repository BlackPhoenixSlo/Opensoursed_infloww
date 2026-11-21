"""Many small Agencies on ONE relay (chatter-crowd `--layout=agencies`): `agencies` Agencies x
`models_per_agency` Creators each (default 20 x 5 = 100 models), no big Creator: a small
agency (~$10k/mo over 5 models, ~$2k/mo a model) runs one chatter and normal fan traffic.
Agency 0 is the run's owner (`w.owner`). Every Creator `fans_per_creator` fans; threads as
seed/threads.py. Product-writable rows only (the same seeders as one_agency), deterministic
from --seed.

The scenario passes its knobs in `w.data["many_agencies"]` ({"agencies": n, "models_per_agency":
m}; ctx.build calls build(w) with no arguments); missing: the defaults below."""
from __future__ import annotations

from .. import World, agency, fans, threads
from .. import creators as creators_seed

AGENCIES, MODELS_PER_AGENCY = 20, 5


async def build(w: World) -> World:
    knobs = w.data.get("many_agencies") or {}
    n_ag = int(knobs.get("agencies") or AGENCIES)
    per = int(knobs.get("models_per_agency") or MODELS_PER_AGENCY)
    if n_ag < 2 or per < 2:
        raise ValueError(f"many_agencies: agencies={n_ag}, models_per_agency={per}: need >= 2 each "
                         "(another Agency keeps isolation live; 2 Creators keep the access-change probe live)")
    await agency.seed(w, n=n_ag)
    ags = [a["user_id"] for a in w.data["agencies"]]
    cs = creators_seed.seed(w, n_ag * per, owners=[a for a in ags for _ in range(per)])
    for c in cs:
        c["big"] = False
    fs = fans.seed(w, cs, int(w.size["fans_per_creator"]))
    threads.seed(w, fs)
    return w
