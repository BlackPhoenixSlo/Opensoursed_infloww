"""Follow-up drip history (`automations.send_followup`): for the eligible fans (>= $1
lifetime spend) WITHOUT a seeded thread, one drip case per fan, each written as the
rows the drip and the chat would have left: the `messages` (his lines, the chatter's,
the earlier nudges as `automation_kind='followup'` outbound rows), the `chats` row and,
when the drip had already touched him, his `followup_state` row. Times are hours
before `w.now`, each case at least 2 h from any rule boundary (26/64/120 h steps,
18 h gap, 12 h contact guard, 168 h cap), so the tick's outcome is fixed by the case.

Cases, round-robin over a seeded shuffle of each Creator's candidates
(`w.rng("followup_drip")`); `--set followup_frac=` (default 1.0) takes a share of them:
  due1             silent 30 h, never nudged               -> step 1
  due2             anchor 70 h, step 1 40 h ago            -> step 2
  gap              anchor 70 h, step 1 14 h ago            -> held by the 18 h gap
  cap              anchor 200 h, steps 1-2 out             -> completed (7-day cap)
  reply            anchor 80 h, step 1 out, he wrote 5 h ago -> reply_cooldown 26 h
  restart          all three out, he wrote 2 h ago         -> restart_cooldown 72 h
  waiting          all three out, no reply                 -> unchanged
  reply_expired    reply_cooldown ended 4 h ago; a chatter answered him 29 h ago
                                                          -> tracking, step 1 same tick
  restart_expired  restart_cooldown ended 8 h ago; a chatter answered 78 h ago
                                                          -> tracking, cycle 2, step 1
  cooling          reply_cooldown until 10 h from now      -> unchanged
Declared: the earlier nudges carry no `sent_by_employee_id` (the product's attribution
resolves the system Automation employee); nothing else differs from what it writes.

`seed_bad_tz_rule` (not part of `seed`; only 2026-10-30-followup-drip's bad-tz phase calls it):
one enabled send_followup clock rule (`daily_at` 00:00) whose stored `tz_offset_minutes` is "x"
(lib/dispatch_tz_faults.py BAD_TZ). Declared bypass: raw SQL. No build ever wrote a non-number
there (the rules API 422s it since 0676f0921): it is a hand-edited / raw-SQL row the API
refuses, which a supervisor pass must skip without stopping.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

MSG_ID_BASE = 9_000_900_000_000   # above threads' history ids, below the relay's bands
CASES = ("due1", "due2", "gap", "cap", "reply", "restart", "waiting",
         "reply_expired", "restart_expired", "cooling")

# case -> (messages as (direction, hours ago, is a nudge), state or None)
# state: (phase, cycle, anchor h, last reply h, cooldown_until h (negative = future), {step: h})
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
BAD_TZ_RAW = "x"   # seed_bad_tz_rule's stored tz_offset_minutes
_IN, _OUT, _NUDGE = "u up?", "hey you", "thinking of you 😘"


def seed(w: World, fans: dict[str, list[dict]], threads: list[dict], frac: float = 1.0) -> dict:
    """-> {"cases": {(account_id, fan_id): case}}; also in w.data["followup_drip"]."""
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
    """One enabled send_followup clock rule on `account_id` with tz_offset_minutes "x" (the
    module docstring's declared bypass) -> its id."""
    con = w.sql()
    with con:
        rid = con.execute(
            "INSERT INTO automation_rules(account_id, name, kind, trigger_json, steps_json, is_enabled, "
            "created_at) VALUES (?, 'follow-up (hand-edited: bad tz)', 'send_followup', ?, '{}', 1, ?)",
            (account_id, json.dumps({"daily_at": ["00:00"], "tz_offset_minutes": BAD_TZ_RAW}),
             ts(w.now))).lastrowid
    con.close()
    return rid
