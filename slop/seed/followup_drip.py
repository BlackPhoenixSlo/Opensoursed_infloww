from __future__ import annotations

import json
from datetime import timedelta

from . import World, fans as _fans, ts

MSG_ID_BASE = 9_000_900_000_000
CASES = ("due1", "due2", "gap", "cap", "reply", "restart", "waiting",
         "reply_expired", "restart_expired", "cooling")

_PLAN = {
    "due1": ([("in", 40, 0), ("out", 30, 0)], None),
    "due2": ([("in", 80, 0), ("out", 70, 0), ("out", 40, 1)],
             ("tracking", 1, 70, None, None, {1: 40})),
    "gap": ([("in", 80, 0), ("out", 70, 0), ("out", 14, 1)],
            ("tracking", 1, 70, None, None, {1: 14})),
    "cap": ([("in", 210, 0), ("out", 200, 0), ("out", 174, 1), ("out", 136, 1)],
            ("tracking", 1, 200, None, None, {1: 174, 2: 136})),
    "reply": ([("in", 90, 0), ("out", 80, 0), ("out", 54, 1), ("in", 5, 0)],
              ("tracking", 1, 80, None, None, {1: 54})),
    "restart": ([("in", 140, 0), ("out", 130, 0), ("out", 104, 1), ("out", 66, 1), ("out", 10, 1), ("in", 2, 0)],
                ("all_sent_waiting", 1, 130, None, None, {1: 104, 2: 66, 3: 10})),
    "waiting": ([("in", 140, 0), ("out", 130, 0), ("out", 104, 1), ("out", 66, 1), ("out", 10, 1)],
                ("all_sent_waiting", 1, 130, None, None, {1: 104, 2: 66, 3: 10})),
    "reply_expired": ([("in", 90, 0), ("out", 80, 0), ("in", 30, 0), ("out", 29, 0)],
                      ("reply_cooldown", 1, 80, 30, 4, {})),
    "restart_expired": ([("in", 240, 0), ("out", 230, 0), ("out", 204, 1), ("out", 166, 1), ("out", 110, 1),
                         ("in", 80, 0), ("out", 78, 0)],
                        ("restart_cooldown", 1, 230, 80, 8, {1: 204, 2: 166, 3: 110})),
    "cooling": ([("in", 60, 0), ("out", 50, 0), ("in", 16, 0)],
                ("reply_cooldown", 1, 50, 16, -10, {})),
}
KILL_FAN_OFFSET = 900_000
KILL_MSG_ID_BASE = MSG_ID_BASE + 9_000_000
KILL_SPEND_CENTS = 2500
BAD_TZ_RAW = "x"
_IN, _OUT, _NUDGE = "u up?", "hey you", "thinking of you 😘"


def seed(w: World, fans: dict[str, list[dict]], threads: list[dict], frac: float = 1.0) -> dict:
    rng = w.rng("followup_drip")
    threaded = {(t["account_id"], t["fan_id"]) for t in threads}
    seq = MSG_ID_BASE
    cases: dict[tuple[str, int], str] = {}
    mrows, crows, srows = [], [], []

    def at(hours: float):
        return w.now - timedelta(hours=hours)

    for aid, fl in fans.items():
        pool = [f for f in fl if f["spend_cents"] >= 100 and (aid, f["id"]) not in threaded]
        rng.shuffle(pool)
        pool = pool[:round(len(pool) * frac)]
        for k, f in enumerate(pool):
            case = CASES[k % len(CASES)]
            cases[(aid, f["id"])] = case
            msgs, st = _PLAN[case]
            last = None
            for direction, hours, nudge in msgs:
                seq += 1
                body = _NUDGE if nudge else (_IN if direction == "in" else _OUT)
                mrows.append((aid, f["id"], seq, direction, f["name"] if direction == "in" else aid, body,
                              "followup" if nudge else None, ts(at(hours)), ts(at(hours))))
                last = (seq, at(hours), body)
            unread = 1 if msgs[-1][0] == "in" else 0
            crows.append((aid, f["id"], last[0], ts(last[1]), last[2], unread))
            if st:
                phase, cycle, anchor, reply, until, steps = st
                srows.append((aid, f["id"], phase, cycle, ts(at(anchor)),
                              ts(at(reply)) if reply is not None else None,
                              ts(at(until)) if until is not None else None,
                              json.dumps({str(s): at(hh).isoformat() for s, hh in steps.items()}),
                              1 if phase == "completed" else 0, ts(w.now)))
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, automation_kind, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,'[]',0,0,NULL,0,0,0,?,?,?)", mrows)
        con.executemany(
            "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, "
            "unread_count, is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')", crows)
        con.executemany(
            "INSERT INTO followup_state(account_id, fan_id, phase, cycle, silence_started_at, fan_last_reply_at, "
            "cooldown_until, messages_sent, completed, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", srows)
    con.close()
    out = {"cases": cases}
    w.data["followup_drip"] = out
    return out


def seed_bad_tz_rule(w: World, account_id: str) -> int:
    con = w.sql()
    with con:
        rid = con.execute(
            "INSERT INTO automation_rules(account_id, name, kind, trigger_json, steps_json, is_enabled, "
            "created_at) VALUES (?, 'follow-up (hand-edited: bad tz)', 'send_followup', ?, '{}', 1, ?)",
            (account_id, json.dumps({"daily_at": ["00:00"], "tz_offset_minutes": BAD_TZ_RAW}),
             ts(w.now))).lastrowid
    con.close()
    return rid


def seed_kill(w: World, aids: list[str]) -> dict[str, dict]:
    index = {c["id"]: i for i, c in enumerate(w.data["creators"])}
    out: dict[str, dict] = {}
    frows, mrows, crows = [], [], []
    seq = KILL_MSG_ID_BASE
    for a in aids:
        fid = _fans.FAN_ID_BASE + index[a] * 1_000_000 + KILL_FAN_OFFSET
        sub_at = w.now - timedelta(days=3)
        f = {"id": fid, "account_id": a, "name": "Kai K.", "username": f"u{fid}", "spend_cents": KILL_SPEND_CENTS}
        out[a] = f
        frows.append((a, fid, f["username"], f["name"], None, 0, "[]", 0, 0, "[]", "[]", "[]", "{}",
                      KILL_SPEND_CENTS, 0, 0, None, None, ts(w.now - timedelta(hours=1)), ts(sub_at),
                      ts(w.now + timedelta(days=30)), "active", 0, "idle", 0, 0, "slop",
                      ts(sub_at), ts(w.now)))
        last = None
        for direction, hours, _nudge in _PLAN["due1"][0]:
            seq += 1
            at = w.now - timedelta(hours=hours)
            body = _IN if direction == "in" else _OUT
            mrows.append((a, fid, seq, direction, f["name"] if direction == "in" else a, body, None, ts(at), ts(at)))
            last = (seq, at, body)
        crows.append((a, fid, last[0], ts(last[1]), last[2], 0))
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO fans(account_id, fan_id, of_username, of_display_name, avatar_url, is_name_real, "
            "recent_events, likes_boobs, likes_ass, family_names, pets, communication_style, custom_fields, "
            "lifetime_spend_cents, is_bot, turn_counter, last_message_received_at, last_message_sent_at, "
            "last_online_at, subscribed_at, subscription_expires_at, "
            "subscription_status, is_followed, deep_convo_state, deep_convo_skip_level, deep_convo_skip_remaining, "
            "source, created_at, updated_at, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]')", frows)
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, automation_kind, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,'[]',0,0,NULL,0,0,0,?,?,?)", mrows)
        con.executemany(
            "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, "
            "unread_count, is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')", crows)
    con.close()
    return out
