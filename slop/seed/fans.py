"""Fans: one `fans` row per Creator x Fan (column list as scripts/demo-shots/seed.py)."""
from __future__ import annotations

from datetime import timedelta

from . import World, ts

FIRST = ["Carlos", "Mike", "Dan", "Tom", "Leo", "Sam", "Max", "Ben", "Joe", "Raj", "Ken", "Ali", "Tim", "Ian"]
LAST = "ABCDEFGHJKLMNPRSTVW"
FAN_ID_BASE = 600_000_000


def seed(w: World, creators: list[dict], per_creator: int | dict[str, int] | None = None) -> dict[str, list[dict]]:
    """`per_creator`: one size for all, or {creator id: size} (e.g. a few big Creators)."""
    sizes = per_creator if isinstance(per_creator, dict) else {}
    default = int(per_creator if isinstance(per_creator, int) else w.size["fans_per_creator"])
    rng = w.rng("fans")
    by_creator: dict[str, list[dict]] = {}
    rows = []
    for ci, c in enumerate(creators):
        fans = []
        for k in range(int(sizes.get(c["id"], default))):
            fid = FAN_ID_BASE + ci * 1_000_000 + k
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}."
            sub_at = w.now - timedelta(days=rng.randint(1, 400))
            f = {"id": fid, "account_id": c["id"], "name": name, "username": f"u{fid}",
                 "spend_cents": rng.choice([0, 0, 0, 999, 2500, 4999, 12000, 50000])}
            fans.append(f)
            rows.append((c["id"], fid, f["username"], name, None, 0, "[]", 0, 0, "[]", "[]", "[]", "{}",
                         f["spend_cents"], 0, 0, None, None, ts(w.now - timedelta(minutes=rng.randint(1, 5000))),
                         ts(sub_at), ts(w.now + timedelta(days=30)), "active", 0,
                         "idle", 0, 0, "slop", ts(sub_at), ts(w.now)))
        by_creator[c["id"]] = fans
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO fans(account_id, fan_id, of_username, of_display_name, avatar_url, is_name_real, recent_events, "
            "likes_boobs, likes_ass, family_names, pets, communication_style, custom_fields, lifetime_spend_cents, is_bot, "
            "turn_counter, last_message_received_at, last_message_sent_at, last_online_at, subscribed_at, "
            "subscription_expires_at, subscription_status, is_followed, "
            "deep_convo_state, deep_convo_skip_level, deep_convo_skip_remaining, source, created_at, updated_at, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]')", rows)
    con.close()
    w.data["fans"] = by_creator
    return by_creator
