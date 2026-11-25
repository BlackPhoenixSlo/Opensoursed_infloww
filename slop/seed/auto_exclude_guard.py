from __future__ import annotations

from datetime import timedelta

from . import World, ts

AE_FAN_BASE = 820_000_000
MSG_ID_BASE = 9_100_000_000_000  # below the relay's synthetic bands, above seed/threads.py's
STALE_FRAC = 0.10
OPEN_FRAC = 0.05
GUARD_AGE_MIN = (10, 240)
STALE_AGE = (2, 9)
LINES = ["hi babe", "thinking of you", "check your inbox", "you're sweet"]


def seed(w: World, creators: list[dict], sizes: dict[str, int], refused: dict[str, int]) -> dict[str, dict]:
    rng = w.rng("auto_exclude_guard")
    index = {c["id"]: i for i, c in enumerate(creators)}
    fan_rows, msg_rows, chat_rows = [], [], []
    seq = MSG_ID_BASE
    out: dict[str, dict] = {}
    for aid, n in sizes.items():
        n, r = int(n), int(refused.get(aid, 0))
        n_stale = int(round(n * STALE_FRAC))
        n_guard = n - n_stale + r
        n_open = int(round(n * OPEN_FRAC))
        base = AE_FAN_BASE + index[aid] * 1_000_000
        ids = list(range(base, base + n_guard + n_stale + n_open))
        rng.shuffle(ids)
        guard = set(ids[:n_guard])
        stale = set(ids[n_guard:n_guard + n_stale])
        opened = set(ids[n_guard + n_stale:])
        refuse = set(rng.sample(sorted(guard), r))
        for fid in sorted(guard | stale | opened):
            sub_at = w.now - timedelta(days=rng.randint(10, 400))
            fan_rows.append((aid, fid, f"u{fid}", f"Fan {fid % 10_000}", None, 0, "[]", 0, 0, "[]", "[]", "[]", "{}",
                             0, 0, 0, None, None, ts(w.now - timedelta(minutes=rng.randint(1, 5000))),
                             ts(sub_at), ts(w.now + timedelta(days=30)), "active", 0,
                             "idle", 0, 0, "slop", ts(sub_at), ts(w.now)))
            if fid in opened:
                continue
            at = (w.now - timedelta(minutes=rng.randint(*GUARD_AGE_MIN)) if fid in guard
                  else w.now - timedelta(days=rng.randint(*STALE_AGE), minutes=rng.randint(0, 600)))
            seq += 1
            body = rng.choice(LINES)
            msg_rows.append((aid, fid, seq, "out", aid, body, "[]", 0, 0, None, None, None, ts(at), ts(at)))
            chat_rows.append((aid, fid, seq, ts(at), body, 0))
        members = (guard - refuse) | stale
        out[aid] = {"guard": guard, "refused": refuse, "stale": stale, "open": opened,
                    "members": members, "roster": members | opened}
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO fans(account_id, fan_id, of_username, of_display_name, avatar_url, is_name_real, recent_events, "
            "likes_boobs, likes_ass, family_names, pets, communication_style, custom_fields, lifetime_spend_cents, is_bot, "
            "turn_counter, last_message_received_at, last_message_sent_at, last_online_at, subscribed_at, "
            "subscription_expires_at, subscription_status, is_followed, "
            "deep_convo_state, deep_convo_skip_level, deep_convo_skip_remaining, source, created_at, updated_at, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]')", fan_rows)
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count, "
            "price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0,0,?,?,?)", msg_rows)
        con.executemany(
            "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, unread_count, "
            "is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')", chat_rows)
    con.close()
    w.data["auto_exclude_guard"] = out
    return out
