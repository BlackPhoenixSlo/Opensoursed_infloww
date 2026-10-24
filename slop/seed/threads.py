"""Threads: message history + the `chats` row per (Creator, Fan) for a fraction
of fans. unread_count = the trailing run of inbound messages, as the transcoder
would have left it. Message ids stay below every synthetic band the relay uses."""
from __future__ import annotations

from datetime import timedelta

from . import World, ts

HISTORY_ID_BASE = 9_000_000_000_000
LINES_IN = ["hey you", "miss me?", "what are you up to", "that pic tho", "good morning", "send more?"]
LINES_OUT = ["hi babe", "just woke up", "thinking of you", "check your inbox", "you're sweet"]


def seed(w: World, fans: dict[str, list[dict]], frac: float | None = None, msgs: int | None = None) -> list[dict]:
    frac = float(frac if frac is not None else w.size["thread_frac"])
    msgs = int(msgs or w.size["history_msgs"])
    rng = w.rng("threads")
    seq = HISTORY_ID_BASE
    threads, mrows, crows = [], [], []
    for aid, fl in fans.items():
        for f in fl:
            if rng.random() >= frac:
                continue
            t0 = w.now - timedelta(hours=rng.randint(2, 24 * 30))
            unread = 0
            last = None
            for j in range(msgs):
                seq += 1
                inbound = rng.random() < 0.55
                unread = unread + 1 if inbound else 0
                at = t0 + timedelta(minutes=7 * j)
                body = rng.choice(LINES_IN if inbound else LINES_OUT)
                mrows.append((aid, f["id"], seq, "in" if inbound else "out", f["name"] if inbound else aid, body,
                              "[]", 0, 0, None, None, None, ts(at), ts(at)))
                last = (seq, at, body)
            crows.append((aid, f["id"], last[0], ts(last[1]), last[2], unread))
            threads.append({"account_id": aid, "fan_id": f["id"], "unread": unread, "last_at": last[1], "msgs": msgs})
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count, "
            "price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0,0,?,?,?)", mrows)
        con.executemany(
            "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, unread_count, "
            "is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')", crows)
    con.close()
    w.data["threads"] = threads
    return threads
