"""Owed customs: fans with a DM tip that `customs_watch` marked as an order, as the product
leaves them (`service/customs_api.py` lists them, `automations/_customs` writes the mark).

Per owed fan, by SQL: his thread (he asks for a custom voice note, the creator agrees on the
spec, he tips, the creator thanks him; `messages` + the `chats` row, as the transcoder writes
them; the tip is `is_tip=1, price_cents=0` as OF sends it), the tip's `transactions` row
(`kind='tip'`, `source='ws'`, `status='pending'`, its `message_id`, as transaction_ingest
writes a DM tip), an enabled `customs_watch` rule on his Creator, and `fans.customs_owed_at` =
the tip's time (customs_watch stamps the tip's
time, not the sweep's). Every line carries the fan's own `tag`, so a pane or a clipboard
shows whose thread it is. Fans are picked from those with no seeded thread, deterministic
from the seed. `w.data["customs"]` = one dict per owed fan, oldest tip first.

`write_of_truth(path, fan)`: OnlyFans' side of one owed fan's thread (his newest message, as
OF holds it) for lib/relay.py's `get_messages`, so a Pull's real scrape has something to read.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from . import World, ts

CUSTOMS_ID_BASE = 9_200_000_000_000
TIP_CENTS = 10_000
TAGS = ("PINEAPPLE", "WALNUT", "MANGO", "PEPPER")
CALLS = ("Dennis", "Marco", "Tobias", "Kenji")  # the name he asks to be called, one per tag


def seed(w: World, n: int = 2) -> list[dict]:
    rng = w.rng("customs")
    creators = w.data["creators"]
    threaded = {(t["account_id"], t["fan_id"]) for t in w.data.get("threads", [])}
    mid = CUSTOMS_ID_BASE
    out, mrows, crows, trows = [], [], [], []
    for i in range(n):
        c = creators[i % len(creators)]  # a different Creator per fan where there are enough
        pool = [f for f in w.data["fans"][c["id"]] if (c["id"], f["id"]) not in threaded
                and all(o["fan_id"] != f["id"] for o in out)]
        f = rng.choice(pool)
        tag = TAGS[i % len(TAGS)]
        call = CALLS[i % len(CALLS)]
        tip_at = w.now - timedelta(hours=6 - i, minutes=rng.randint(0, 20))  # oldest first = fan 0
        lines = [  # (minutes from the tip, direction, body, is_tip)
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
        # The mark is customs_watch's, so each owed fan's Creator has that rule enabled.
        con.executemany("INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, is_enabled,"
                        " created_at) VALUES (?, 'customs_watch', 'customs_watch', '{}', '{}', 1, ?)",
                        [(aid, ts(w.now - timedelta(days=14))) for aid in sorted({o["account_id"] for o in out})])
        con.executemany("UPDATE fans SET customs_owed_at=? WHERE account_id=? AND fan_id=?",
                        [(ts(o["tip_at"]), o["account_id"], o["fan_id"]) for o in out])
    con.close()
    w.data["customs"] = out
    return out


def write_of_truth(path: Path, f: dict) -> None:
    """`of-truth.jsonl` at `path`: fan `f`'s newest seeded message, as OF holds it."""
    mid, at, body, direction = f["newest"]
    sender = int(f["fan_id"]) if direction == "in" else int(f["account_id"])
    with path.open("w") as fh:
        fh.write(json.dumps({"account_id": f["account_id"], "fan_id": f["fan_id"], "message": {
            "id": int(mid), "text": f"<p>{body}</p>", "price": 0, "isFree": True, "mediaCount": 0,
            "media": [], "fromUser": {"id": sender},
            "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"}}) + "\n")
