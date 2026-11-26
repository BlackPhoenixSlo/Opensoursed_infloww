from __future__ import annotations

from typing import NamedTuple

from .. import World, agency, fans, threads
from .. import creators as creators_seed

MODELS, BIG, NEIGHBOUR_MODELS = 50, 9, 1
DPM, BIG_DPM = 5.0, 50.0
GRANTS = ("narrow", "broad", "mixed")


class Shape(NamedTuple):
    models: int = MODELS
    big: int = BIG
    dpm: float = DPM
    grants: str = "narrow"


def shape(knobs: dict | None) -> Shape:
    k = {f: v for f, v in (knobs or {}).items() if v is not None}
    s = Shape(models=int(k.get("models", MODELS)), big=int(k.get("big", min(BIG, int(k.get("models", MODELS))))),
              dpm=float(k.get("dpm", DPM)), grants=str(k.get("grants", "narrow")))
    if s.models < 2:
        raise ValueError(f"one_agency: models={s.models}: need >= 2 (the access-change probe drops one of two)")
    if not 0 <= s.big <= s.models:
        raise ValueError(f"one_agency: big={s.big}: 0..models ({s.models})")
    if s.dpm <= 0:
        raise ValueError(f"one_agency: dpm={s.dpm}: DMs/min per Creator must be > 0")
    if s.grants not in GRANTS:
        raise ValueError(f"one_agency: grants={s.grants!r}: one of {', '.join(GRANTS)}")
    return s


async def build(w: World) -> World:
    s = shape(w.data.get("one_agency"))
    await agency.seed(w, n=2)
    main, neighbour = (a["user_id"] for a in w.data["agencies"])
    cs = creators_seed.seed(w, s.models + NEIGHBOUR_MODELS,
                            owners=[main] * s.models + [neighbour] * NEIGHBOUR_MODELS)
    for i, c in enumerate(cs):
        c["big"] = i < s.big
        c["dpm"] = BIG_DPM if c["big"] else s.dpm
    fs = fans.seed(w, cs, {c["id"]: int(w.size["big_fans_per_creator" if c["big"] else "fans_per_creator"])
                           for c in cs})
    threads.seed(w, fs)
    w.data["no_chatters"] = {neighbour}
    w.data["grants"] = s.grants
    return w
