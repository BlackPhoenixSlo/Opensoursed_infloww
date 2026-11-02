"""S4S Settings (`s4s_profiles`), S4S posts (`s4s_posts`) and Agency blocks (`s4s_blocks`), as the
owner's Settings save, the posts routes and POST /admin/s4s/blocks leave them (service/s4s_api.py).

Per Creator: a profile, opted in unless drawn opted out (`opted_out_frac`), visible in Discovery, a
Daily limit of 1-3 and the display fields an OnlyFans `/users/me` read stores (display_name = the
Creator's name, username = its nickname lowercased + the last 4 of its id); 1-3 posts, the first one
Primary (the routes make the first post Primary). Blocks: `blocks` distinct (Agency, Creator of another
Agency) pairs drawn in one sample (fewer only if fewer exist), each with the Creator's S4S projection at
block time (`s4s_requests_api._projection`); only opted-in Creators are blocked (the route 404s others).

`seed(w, creators, *, opted_out_frac, blocks)` returns w.data["s4s_profiles"]:
  {"profiles": {account_id: {profile_id, account_id, owner, opted_in, daily_limit, username,
                display_name, caption}},
   "blocks": [{agency_user_id, account_id, profile_id}]}
Randomness only from w.rng("s4s_profiles").
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

CAPTIONS = ("Come say hi, I answer every DM", "New set every Friday", "Your favourite girl next door",
            "Daily posts, no PPV spam", "Cosplay and behind the scenes", "Fitness, travel and more")


def seed(w: World, creators: list[dict], *, opted_out_frac: float = 0.1, blocks: int = 0) -> dict:
    rng = w.rng("s4s_profiles")
    con = w.sql()
    profiles: dict[str, dict] = {}
    at = ts(w.now - timedelta(days=7))
    with con:
        for i, c in enumerate(creators):
            opted_in = rng.random() >= opted_out_frac
            limit = rng.randint(1, 3)
            username = f"{c['nickname'].lower()}{c['id'][-4:]}"
            cur = con.execute(
                "INSERT INTO s4s_profiles(account_id, opted_in, discovery_visible, daily_limit, display_name, "
                "username, avatar_url, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (c["id"], 1 if opted_in else 0, 1, limit, c["name"], username, None, at, at))
            pid = cur.lastrowid
            caption = None
            for k in range(rng.randint(1, 3)):
                text = f"{rng.choice(CAPTIONS)} #{i}.{k}"
                con.execute("INSERT INTO s4s_posts(account_id, caption, is_primary, created_at, updated_at) "
                            "VALUES (?,?,?,?,?)", (c["id"], text, 1 if k == 0 else 0, at, at))
                caption = caption or text
            profiles[c["id"]] = {"profile_id": pid, "account_id": c["id"], "owner": c["owner"],
                                 "opted_in": opted_in, "daily_limit": limit, "username": username,
                                 "display_name": c["name"], "caption": caption}
        out_blocks: list[dict] = []
        listed = [p for p in profiles.values() if p["opted_in"]]
        agencies = sorted({c["owner"] for c in creators})
        candidates = [(ag, p) for ag in agencies for p in listed if p["owner"] != ag]
        for ag, p in rng.sample(candidates, min(blocks, len(candidates))):
            proj = {"profile_id": p["profile_id"], "display_name": p["display_name"], "username": p["username"],
                    "avatar_url": None, "primary_caption": p["caption"], "daily_limit": p["daily_limit"],
                    "opted_in": True}
            con.execute("INSERT INTO s4s_blocks(agency_user_id, account_id, projection_json, created_at) "
                        "VALUES (?,?,?,?)", (ag, p["account_id"], json.dumps(proj), at))
            out_blocks.append({"agency_user_id": ag, "account_id": p["account_id"], "profile_id": p["profile_id"]})
    con.close()
    w.data["s4s_profiles"] = {"profiles": profiles, "blocks": out_blocks}
    return w.data["s4s_profiles"]
