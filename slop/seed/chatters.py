"""Chatters (employee logins): each one through the real endpoints, as an owner
invites and an employee signs up: POST /admin/chatters/invite (the owner's
session) -> token, then POST /chatter/register?token=... (a fresh client; the
relay links the chatter to the inviting owner and sets its session cookie,
which this seeder drops). `w.data["chatters"]`: [{username, password, owner}].
`account_ids`: the invite's Employee setup (the Creators the chatter may work,
applied on accept), one list per username; each record then also carries
`account_ids` and the relay's `chatter_id`."""
from __future__ import annotations

from . import World

PASSWORD = "slop-chatter-password"


async def seed(w: World, owner_http, owner_id: str, usernames: list[str], *, password: str = PASSWORD,
               account_ids: list[list[str]] | None = None) -> list[dict]:
    from slop.lib.client import Http  # lazy: seeders stay importable without httpx

    out = []
    fresh = Http(str(owner_http.c.base_url), owner_http.rec)
    try:
        for k, u in enumerate(usernames):
            setup = {"account_ids": list(account_ids[k])} if account_ids is not None else None
            r = await owner_http.post("/admin/chatters/invite", **({"json": setup} if setup else {}))
            r.raise_for_status()
            fresh.c.cookies.clear()
            rr = await fresh.post(f"/chatter/register?token={r.json()['token']}",
                                  json={"username": u, "password": password, "display_name": u})
            rr.raise_for_status()
            out.append({"username": u, "password": password, "owner": owner_id, "kind": "chatter",
                         **({"account_ids": setup["account_ids"], "chatter_id": rr.json().get("chatter_id")}
                            if setup else {})})
    finally:
        fresh.c.cookies.clear()
        await fresh.aclose()
    w.data.setdefault("chatters", []).extend(out)
    return out
