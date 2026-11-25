from __future__ import annotations

from . import World

PASSWORD = "slop-chatter-password"


async def seed(w: World, owner_http, owner_id: str, usernames: list[str], *, password: str = PASSWORD,
               account_ids: list[list[str]] | None = None) -> list[dict]:
    from slop.lib.client import Http

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
