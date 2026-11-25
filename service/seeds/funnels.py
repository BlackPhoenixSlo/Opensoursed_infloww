#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

_SERVICE = Path(__file__).resolve().parent.parent
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))

from sqlalchemy import select                                   # noqa: E402
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

from db.engine import get_session                               # noqa: E402
from db.models import MassMessageFunnel                         # noqa: E402

FUNNELS: list[dict] = [
    {
        "name": "strokes",
        "opening_message": "How many strokes does it take to get you off? 😈",
        "description": ("Strokes engagement funnel — opens with a spicy question, "
                        "warms up with 3 reply steps, closes with paid PPV content."),
        "steps": [
            {"step": 1, "check_intervals_min": [2, 4, 10],
             "messages": [
                 "bet you lose count once it starts getting slopyyy",
                 "or do you stay focused even with all that pressure building? c:"]},
            {"step": 2, "check_intervals_min": [2, 4, 10],
             "messages": [
                 "i can feel you pulsating just thinking about it...",
                 "so tell me would you explode fast or last if I were the one "
                 "dictating the tempo?"]},
            {"step": 3, "check_intervals_min": [2, 4, 10],
             "messages": [
                 "how about you pull your friend out, and we find out how many "
                 "strokes it will take you to bust?",
                 "if you last long enough, I promise to praise you and reward "
                 "your hard work"]},
            # no media_files: vault ids exist in one model's vault only; media is bound per model in funnel_account_media and step 4 is held until then
            {"step": 4, "type": "paid_ppv", "price": 24,
             "messages": [
                 "if it wasn't obvious already, i love to be in control. not just "
                 "of you, but your every thought, action & desire. open this & "
                 "show me how obedient ure going to be, taking out ur cock & "
                 "slowly moving it up and down the shaft while i spread my legs "
                 "infront of your face showing just how pink it is"]},
        ],
    },
    {
        "name": "strokes_fr",
        "description": ("Strokes funnel (French) — opens with a spicy question, "
                        "warms up with 3 reply steps, closes with paid PPV content."),
        "opening_message": "Combien de va-et-vient il te faut pour jouir ? 😈",
        "vault_folder": "Mass_Messages",
        "media_indices": [4],
        "steps": [
            {"step": 1, "trigger": "any_reply", "check_intervals_min": [2, 4, 10],
             "messages": [
                 "Je parie que tu perds le compte dès que ça devient bien glissant "
                 "et tout mouillé",
                 "ou tu restes concentré même avec toute cette pression qui monte ? c:"]},
            {"step": 2, "trigger": "any_reply", "check_intervals_min": [2, 4, 10],
             "messages": [
                 "Je te sens palpiter rien qu'en y pensant...",
                 "Dis-moi, tu exploserais vite ou tu tiendrais longtemps si c'était "
                 "moi qui dictait le rythme ?"]},
            {"step": 3, "trigger": "any_reply", "check_intervals_min": [2, 4, 10],
             "messages": [
                 "Et si tu sortais ta queue, qu'on découvre combien de va-et-vient "
                 "il te faut pour décharger ?",
                 "Si tu tiens assez longtemps, je promets de te féliciter et de "
                 "récompenser tes efforts"]},
            {"step": 4, "trigger": "any_reply", "type": "paid_ppv",
             "vault_folder": "Mass_Messages", "media_indices": "all", "price": 24,
             "messages": [
                 "Au cas où c'était pas déjà clair, j'adore être aux commandes. Pas "
                 "seulement sur toi, mais sur chacune de tes pensées, tes actions et "
                 "tes désirs. Ouvre ça et montre-moi à quel point tu vas être "
                 "obéissant, en sortant ta queue et en la caressant lentement de "
                 "haut en bas pendant que j'écarte mes jambes devant ton visage pour "
                 "te montrer à quel point c'est rose et trempé"]},
        ],
    },
]


def _row(f: dict, now: datetime) -> dict:
    return dict(
        name=f["name"], description=f.get("description"),
        opening_message=f["opening_message"],
        vault_folder=f.get("vault_folder"),
        media_indices=json.dumps(f.get("media_indices", [])),
        steps_json=json.dumps(f["steps"]), updated_at=now,
    )


async def seed() -> list[tuple[int, str]]:
    now = datetime.utcnow()
    for f in FUNNELS:
        vals = _row(f, now)
        async with get_session() as s:
            await s.execute(
                sqlite_insert(MassMessageFunnel).values(**vals)
                .on_conflict_do_update(
                    index_elements=["name"],
                    set_={k: v for k, v in vals.items() if k != "name"})
            )
    return await _list()


DEFAULT_FUNNELS = ("strokes",)
# marker makes seeding once-only so a default the operator deleted is not resurrected
DEFAULTS_MARKER = "20261018_default_funnel_strokes"


async def seed_defaults_once() -> list[str]:
    from sqlalchemy import text
    from db.engine import _DATA_MIGRATIONS_DDL

    now = datetime.utcnow()
    added: list[str] = []
    async with get_session() as s:
        await s.execute(text(_DATA_MIGRATIONS_DDL))
        done = (await s.execute(
            text("SELECT 1 FROM data_migrations WHERE name = :n"),
            {"n": DEFAULTS_MARKER})).first()
        if done is not None:
            return []
        for f in FUNNELS:
            if f["name"] not in DEFAULT_FUNNELS:
                continue
            res = await s.execute(
                sqlite_insert(MassMessageFunnel).values(**_row(f, now))
                .on_conflict_do_nothing(index_elements=["name"]))
            if res.rowcount:
                added.append(f["name"])
        await s.execute(text("INSERT INTO data_migrations (name) VALUES (:n)"),
                        {"n": DEFAULTS_MARKER})
    return added


async def _list() -> list[tuple[int, str]]:
    async with get_session() as s:
        rows = (await s.execute(
            select(MassMessageFunnel.id, MassMessageFunnel.name)
            .order_by(MassMessageFunnel.id))).all()
    return [(int(i), n) for i, n in rows]


async def _main(list_only: bool):
    rows = await _list() if list_only else await seed()
    verb = "in DB" if list_only else "seeded"
    print(f"[funnels] {verb}: " + ", ".join(f"{i}:{n}" for i, n in rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="just list DB funnels")
    a = ap.parse_args()
    asyncio.run(_main(a.list))
