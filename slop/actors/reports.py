"""Owners reading the money reports: the Dashboard's earnings card and Employee
sales, and Creator reports' Overview (Earnings summary with its growth, Earnings
trends, Creator performance), with the reads those pages make (`DashboardHeader`,
`CompetitorReports`, `usePerModel`), all Creators or one picked at random.

`windows`: {"month": (from, to), "range": (from, to), "prior": (from, to)}, ISO
instants as the app sends them. Each owner repeats its page loads until `stop`
is set and it has done at least `rounds`, a human think time (3 to 15 s) between loads."""
from __future__ import annotations

import asyncio
import random
from urllib.parse import urlencode

THINK_S = (3.0, 15.0)  # seconds between one owner's page loads


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
    await asyncio.sleep(rng.uniform(0, think_s[1]))  # owners arrive spread out, not all in one instant
    while done < rounds or not stop.is_set():
        pick = rng.choice([None, *creator_ids])
        for path in (dashboard(win) if rng.random() < 0.5 else creator_reports(win, pick)):
            await http.get(path)
        done += 1
        await asyncio.sleep(rng.uniform(*think_s))
    return done


async def crowd(http, win: dict, creator_ids: list[str], stop: asyncio.Event, users: int, *, seed: int,
                rounds: int = 1) -> int:
    """`users` owners at once; returns the page loads done."""
    rngs = [random.Random(f"{seed}:reports:{i}") for i in range(users)]
    return sum(await asyncio.gather(*(owner(http, win, creator_ids, stop, rounds=rounds, rng=r) for r in rngs)))
