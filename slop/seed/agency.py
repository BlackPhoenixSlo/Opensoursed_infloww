"""Agencies: one owner `users` row each, created through the real POST /auth/register.
The first is the run's owner (`w.owner`, `w.user_id`); every further one gets its
own signed-in session (`w.data["agencies"][i]["http"]`)."""
from __future__ import annotations

from . import World

PASSWORD = "slop-throwaway-password"


async def _register(http, username: str) -> str:
    r = await http.post("/auth/register", json={"username": username, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["user_id"]


async def seed(w: World, n: int = 1) -> str:
    from slop.lib.client import Http  # lazy: seeders stay importable without httpx

    out = []
    for i in range(n):
        http = w.owner if i == 0 else Http(str(w.owner.c.base_url), w.owner.rec)
        username = f"slop{w.seed}" if i == 0 else f"slop{w.seed}a{i}"
        out.append({"user_id": await _register(http, username), "username": username, "http": http})
    w.user_id = out[0]["user_id"]
    w.data["agency"] = {"user_id": w.user_id, "username": out[0]["username"]}
    w.data["agencies"] = out
    return w.user_id
