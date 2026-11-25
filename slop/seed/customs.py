from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from . import World, ts

CUSTOMS_ID_BASE = 9_200_000_000_000
TIP_CENTS = 10_000
TAGS = ("PINEAPPLE", "WALNUT", "MANGO", "PEPPER")
CALLS = ("Dennis", "Marco", "Tobias", "Kenji")


def seed(w: World, n: int = 2) -> list[dict]:
    rng = w.rng("customs")
    creators = w.data["creators"]
    threaded = {(t["account_id"], t["fan_id"]) for t in w.data.get("threads", [])}
    mid = CUSTOMS_ID_BASE
    out, mrows, crows, trows = [], [], [], []
    for i in range(n):
        c = creators[i % len(creators)]
        pool = [f for f in w.data["fans"][c["id"]] if (c["id"], f["id"]) not in threaded
                and all(o["fan_id"] != f["id"] for o in out)]
        f = rng.choice(pool)
        tag = TAGS[i % len(TAGS)]
        call = CALLS[i % len(CALLS)]
        tip_at = w.now - timedelta(hours=6 - i, minutes=rng.randint(0, 20))
        lines = [
            (-40, "in", f"can you make me a custom voice note {tag}? call me {call} and whisper about the {tag.lower()}", 0),
            (-35, "out", f"mmm yes {call}, a 5 minute voice note for the {tag.lower()} one, tip 100 and I record it", 0),
            (-30, "in", f"perfect, make it 5 minutes, say {tag} three times at the end", 0),
            (0, "in", "", 1),
            (5, "out", f"thank you babe, recording your {tag.lower()} voice note tonight", 0),
        ]
        tip_mid = None
        for off, direction, body, is_tip in lines:
            mid += 1
            at = tip_at + timedelta(minutes=off)
            mrows.append((c["id"], f["id"], mid, direction, f["name"] if direction == "in" else c["id"], body,
                          is_tip, ts(at), ts(at)))
            if is_tip:
                tip_mid = mid
            last = (mid, at, body, direction)
        crows.append((c["id"], f["id"], last[0], ts(last[1]), last[2]))
        trows.append((c["id"], f["id"], "tip", TIP_CENTS, "USD", ts(tip_at), ts(tip_at), "pending",
                      round(TIP_CENTS * 0.8), TIP_CENTS - round(TIP_CENTS * 0.8), 0, "ws", tip_mid))
        out.append({"account_id": c["id"], "account_name": c["nickname"], "fan_id": f["id"],
                    "display_name": f["name"], "username": f["username"], "tag": tag, "call": call,
                    "tip_at": tip_at, "tip_message_id": tip_mid, "newest": last})
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count, "
            "price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,'[]',0,0,NULL,?,NULL,0,0,NULL,?,?)", mrows)
        con.executemany(
            "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, unread_count, "
            "is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,0,0,0,0,'[]')", crows)
        con.executemany(
            "INSERT INTO transactions(account_id, fan_id, kind, amount_cents, currency, occurred_at, ingested_at, "
            "status, net_cents, fee_cents, vat_cents, source, message_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", trows)
        con.executemany("INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, is_enabled,"
                        " created_at) VALUES (?, 'customs_watch', 'customs_watch', '{}', '{}', 1, ?)",
                        [(aid, ts(w.now - timedelta(days=14))) for aid in sorted({o["account_id"] for o in out})])
        con.executemany("UPDATE fans SET customs_owed_at=? WHERE account_id=? AND fan_id=?",
                        [(ts(o["tip_at"]), o["account_id"], o["fan_id"]) for o in out])
    con.close()
    w.data["customs"] = out
    return out


def write_of_truth(path: Path, f: dict) -> None:
    mid, at, body, direction = f["newest"]
    sender = int(f["fan_id"]) if direction == "in" else int(f["account_id"])
    with path.open("w") as fh:
        fh.write(json.dumps({"account_id": f["account_id"], "fan_id": f["fan_id"], "message": {
            "id": int(mid), "text": f"<p>{body}</p>", "price": 0, "isFree": True, "mediaCount": 0,
            "media": [], "fromUser": {"id": sender},
            "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"}}) + "\n")
