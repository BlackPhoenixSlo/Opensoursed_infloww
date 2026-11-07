"""Creators: `accounts` + `user_accounts` rows and the on-disk account registry
(the temp sessions/ dir the guarded relay redirected), as scripts/demo-shots/seed.py."""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

FIRST = ["Ava", "Mia", "Luna", "Zoe", "Ivy", "Nora", "Ella", "Ruby", "Skye", "Jade", "Cleo", "Lola"]
COLORS = ["#e11d48", "#7c3aed", "#0891b2", "#16a34a", "#ea580c", "#db2777", "#2563eb", "#ca8a04"]


def _add(w: World, con, i: int, aid: int, owner: str) -> dict:
    acc_dir = w.sessions / "accounts"
    acc_dir.mkdir(parents=True, exist_ok=True)
    name = f"{FIRST[i % len(FIRST)]} {chr(65 + i // len(FIRST))}{i}"
    c = {"id": str(aid), "name": name, "owner": owner, "nickname": name.split()[0], "color": COLORS[i % len(COLORS)],
         "created_at": w.now - timedelta(days=90 + i)}
    a = acc_dir / c["id"]
    a.mkdir(exist_ok=True)
    (a / "meta.json").write_text(json.dumps({
        "id": c["id"], "nickname": c["nickname"], "color": c["color"], "incogniton_profile_id": None,
        "platform": "onlyfans", "name": name, "created_at": c["created_at"].isoformat() + "Z",
        "last_used_at": w.now.isoformat() + "Z"}))
    (a / "session_slop.json").write_text("{}")
    (a / "latest.json").write_text(json.dumps({"session": "session_slop.json", "ts": w.now.isoformat() + "Z"}))
    con.execute("INSERT INTO accounts(id, nickname, color, is_active_default, created_at, last_used_at) "
                "VALUES (?,?,?,?,?,?)", (c["id"], c["nickname"], c["color"], 1 if i == 0 else 0,
                                         ts(c["created_at"]), ts(w.now)))
    con.execute("INSERT INTO user_accounts(user_id, account_id, created_at) VALUES (?,?,?)",
                (c["owner"], c["id"], ts(c["created_at"])))
    return c


def seed(w: World, n: int | None = None, owners: list[str] | None = None) -> list[dict]:
    """`owners[i]`: the Agency (users.id) Creator i belongs to; default all `w.user_id`."""
    n = int(n or w.size["creators"])
    rng = w.rng("creators")
    ids = sorted(rng.sample(range(100_000_000, 400_000_000), n))
    con = w.sql()
    with con:
        out = [_add(w, con, i, aid, owners[i] if owners else w.user_id) for i, aid in enumerate(ids)]
    con.close()
    (w.sessions / "active.json").write_text(json.dumps({"active_account_id": out[0]["id"]}))
    w.data["creators"] = out
    return out


def extra(w: World, n: int) -> list[dict]:
    """`n` more Creators of `w.user_id`, ids above seed()'s range, kept out of `w.data["creators"]`:
    a scenario's own, beside the profile's."""
    ids = sorted(w.rng("creators:extra").sample(range(400_000_000, 500_000_000), n))
    con = w.sql()
    with con:
        out = [_add(w, con, 1000 + i, aid, w.user_id) for i, aid in enumerate(ids)]
    con.close()
    return out
