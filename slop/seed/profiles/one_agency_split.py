from __future__ import annotations

from .. import World
from . import one_agency

RELAYS, MODELS = 2, 30


def halves(n: int) -> list[int]:
    return [n - n // RELAYS * (RELAYS - 1)] + [n // RELAYS] * (RELAYS - 1)


async def build_fleet(ws: list[World]) -> list[World]:
    if len(ws) != RELAYS:
        raise ValueError(f"one_agency_split is {RELAYS} relays, got {len(ws)}")
    knobs = {"models": MODELS, **{k: v for k, v in (ws[0].data.get("one_agency") or {}).items() if v is not None}}
    s = one_agency.shape(knobs)
    for w, m, b in zip(ws, halves(s.models), halves(s.big)):
        w.data["one_agency"] = s._replace(models=m, big=b)._asdict()
        await one_agency.build(w)
    ids = [c["id"] for w in ws for c in w.data["creators"]]
    assert len(ids) == len(set(ids)), "two relays drew the same Creator id; change --seed"
    return ws
