from __future__ import annotations

import asyncio
import random
from urllib.parse import urlencode

THINK_S = (3.0, 15.0)


def dashboard(win: dict) -> list[str]:
    f, t = win["month"]
    return [f"/admin/stats/revenue?{urlencode({'from': f, 'to': t, 'group_by': 'kind', 'include_net': 'true'})}",
            f"/admin/stats/per-employee?{urlencode({'from': f, 'to': t})}"]


def creator_reports(win: dict, account_id: str | None = None) -> list[str]:
    (f, t), (pf, pt) = win["range"], win["prior"]
    one = {"account_id": account_id} if account_id else {}
    return [f"/admin/stats/revenue?{urlencode({'group_by': 'day', 'by_kind': 'true', 'include_net': 'true', 'from': f, 'to': t, **one})}",
            f"/admin/stats/revenue?{urlencode({'group_by': 'kind', 'include_net': 'true', 'from': f, 'to': t, **one})}",
            f"/admin/stats/revenue?{urlencode({'group_by': 'kind', 'include_net': 'true', 'from': pf, 'to': pt, **one})}",
            f"/admin/stats/per-model?{urlencode({'from': f, 'to': t, 'engagement': 'true'})}"]


async def owner(http, win: dict, creator_ids: list[str], stop: asyncio.Event, *, rounds: int = 1,
                rng: random.Random, think_s: tuple[float, float] = THINK_S) -> int:
    done = 0
    await asyncio.sleep(rng.uniform(0, think_s[1]))
    while done < rounds or not stop.is_set():
        pick = rng.choice([None, *creator_ids])
        for path in (dashboard(win) if rng.random() < 0.5 else creator_reports(win, pick)):
            await http.get(path)
        done += 1
        await asyncio.sleep(rng.uniform(*think_s))
    return done


async def crowd(http, win: dict, creator_ids: list[str], stop: asyncio.Event, users: int, *, seed: int,
                rounds: int = 1) -> int:
    rngs = [random.Random(f"{seed}:reports:{i}") for i in range(users)]
    return sum(await asyncio.gather(*(owner(http, win, creator_ids, stop, rounds=rounds, rng=r) for r in rngs)))
