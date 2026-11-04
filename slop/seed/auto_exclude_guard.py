"""Auto_Exclude past the 20k backstop (scenarios/2026-11-03-auto-exclude-25k.py): per Creator, fans
whose recent chat puts them in the product's contact guard, plus the OF side the scenario hands to
lib/auto_exclude_relay.py (its pre-made Auto_Exclude, roster, refused ids).

Per Creator `aid` with list size `n` (`sizes[aid]`), fan ids from AE_FAN_BASE + Creator index x 1M:
  guard    n - stale + refused fans, each with one outbound message GUARD_AGE_MIN..MAX ago (inside
           the 6 h outbound window, BROADCAST_DEFAULT_OUTBOUND_H, for the whole run) and its chats row,
           as the product writes a 1:1 send.
  refused  `refused` of the guard: OF refuses to list them (a deleted account, declared): never on the
           pre-made list, not on the roster.
  stale    ~STALE_FRAC of n: on the list from an older send, last message STALE_AGE days ago (out of
           every window).
  open     OPEN_FRAC of n: subscribed, never messaged; a send reaches them.
  members  the pre-made Auto_Exclude: (guard - refused) | stale, exactly n ids.
  roster   members | open: OF's fans roster.
Rows: `fans` (as seed/fans.py), `messages` + `chats` (as seed/threads.py); their INSERTs are
copied here on purpose: seed/fans.py and seed/threads.py belong to other flows (not this task's to
change), and they seed by count, not by a given id set. Deterministic from
`w.rng("auto_exclude_guard")`. Output in `w.data["auto_exclude_guard"]`: {aid: {...sets above}}.
"""
from __future__ import annotations

from datetime import timedelta

from . import World, ts

AE_FAN_BASE = 820_000_000
MSG_ID_BASE = 9_100_000_000_000      # below the relay's synthetic bands, above seed/threads.py's
STALE_FRAC = 0.10
OPEN_FRAC = 0.05
GUARD_AGE_MIN = (10, 240)            # minutes ago, (min, max)
STALE_AGE = (2, 9)                   # days ago
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
        rng.shuffle(ids)                       # guard / stale / open interleave in id (= OF page) order
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
