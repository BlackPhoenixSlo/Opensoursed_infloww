"""House funnel history (`automations.reply_mass_funnel`): one 3-step funnel, and per
Creator one funnel broadcast sent BROADCAST_H ago to every fan WITHOUT a seeded thread,
each written as the rows the product leaves: the `mass_message_funnels` row, its
per-Creator `funnel_account_media` (the PPV step's vault id), the `mass_runs` row
(status ok, the funnel's id, the audience_filter A10 stores for an explicit-fan send:
its recipients, no lists, unfenced), one outbound broadcast row per recipient
(`automation_kind='send_mass_message'`, tagged with the run, as A10 writes it), and, for
the fans already walking, their `funnel_state` row, the steps they were sent (tagged,
`funnel_step`), their earlier answers and the `chats` row. A seeded `funnel_state` row
carries `last_sent_step` = the step index it was last sent (current_step - 1: every seeded
walk is linear), as the walker stamps it on each send.

Cases (seeded shuffle of each Creator's recipients, `w.rng("house_funnel")`): the first
`live` fans (the scenario's repliers, `--users` over the Creators) round-robin over the
LIVE cases, the rest over the QUIET ones:
  new       answered nothing yet; answers live                 -> enrolled, step 1
  reply     step 1 sent 3 min ago; answers live                -> step 2
  ppv       steps 1-2 sent; answers live                       -> the PPV, done
  buyer     step 1 sent 60 min ago; a chatter's PPV unlocked 20 min ago; answers live
                                                               -> done offer_taken
  waiting   step 1 sent 3 min ago, no answer since             -> check_count 1, +4 min
  past_end  current_step 3, steps 1-3 sent as text (the funnel was edited since: its
            old 4-step script, now 3)                          -> done
  silent    never answered                                     -> no walk
The last JUMP_PER_CREATOR fans of each Creator's shuffled pool (never a LIVE case) are
held out of that broadcast for `seed_jump`: a second, branching funnel (JUMP_STEPS: step
1's keyword `jump` routes to step 5, and step 1, step 4 = the jump's c - 1 and step 5
each carry a different `check_intervals_min`), one more broadcast per Creator to just
those fans, seeded when the scenario calls it (after the main walk's ticks), so the main
broadcast's world and ticks never see it.
Declared: the buyer's unlock is seeded as the two rows purchase_notifications'
`_flip_paid` leaves (the chatter PPV flipped `is_paid=1`, `purchased_at` = the
notification's time, and its `purchase_notices` row), not driven through that poll (it
reads OF, offline here); the chatter PPV carries one vault media id, as every priced
OF message does; the earlier lines carry no
`sent_by_employee_id` (the product resolves the system Automation employee).
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

MSG_ID_BASE = 9_000_950_000_000   # above threads' / followup_drip's ids, below the relay's bands
BROADCAST_H = 2.0
PPV_MEDIA_ID = 7_100_000_001
PPV_PRICE = 24
CHATTER_PPV_CENTS = 1500
CHATTER_PPV_MEDIA_ID = 7_100_000_002
LIVE = ("new", "reply", "ppv", "buyer")
QUIET = ("waiting", "past_end", "silent")
OPENER = "slop funnel opener: guess what I made for you"
STEPS = [
    {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["hey you 😘", "did you like it?"]},
    {"step": 2, "messages": ["I made something just for you"]},
    {"step": 3, "type": "paid_ppv", "price": PPV_PRICE, "messages": ["open this babe"]},
]
LINES = {s["step"]: len(s["messages"]) for s in STEPS}   # step number -> lines sent
JUMP_PER_CREATOR = 2
JUMP_MSG_ID_BASE = MSG_ID_BASE + 5_000_000
JUMP_OPENER = "slop jump funnel opener: say jump"
JUMP_WORD = "jump"
JUMP_STEPS = [
    {"step": 1, "check_intervals_min": [2, 7, 10], "messages": ["jump funnel hi 😘"],
     "next": {"keyword": {JUMP_WORD: 5}}},
    {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["jump funnel step 2"]},
    {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["jump funnel step 3"]},
    {"step": 4, "check_intervals_min": [2, 13, 20], "messages": ["jump funnel step 4"]},
    {"step": 5, "check_intervals_min": [2, 19, 30], "messages": ["jump funnel step 5"]},
]
JUMP_FROM, JUMP_TO = 0, 4   # step INDEXES: step 1's keyword lands on step 5

# case -> (current_step, [(direction, minutes ago, funnel step or None)])
_PLAN = {
    "new": (None, []),
    "reply": (1, [("in", 100, None), ("out", 3, 1)]),
    "ppv": (2, [("in", 100, None), ("out", 40, 1), ("in", 20, None), ("out", 3, 2)]),
    "buyer": (1, [("in", 100, None), ("out", 60, 1)]),
    "waiting": (1, [("in", 100, None), ("out", 3, 1)]),
    "past_end": (3, [("in", 110, None), ("out", 100, 1), ("in", 90, None), ("out", 80, 2),
                     ("in", 70, None), ("out", 60, 3)]),
    "silent": (None, []),
}
_IN = "hii"

_FUNNEL_SQL = ("INSERT INTO mass_message_funnels(name, description, opening_message, media_indices, steps_json, "
               "created_at, updated_at) VALUES (?,?,?,?,?,?,?)")
_RUN_SQL = ("INSERT INTO mass_runs(account_id, funnel_id, audience_filter, recipient_count, automation_kind, "
            "started_at, completed_at, status) VALUES (?,?,?,?,?,?,?,?)")
_MSG_SQL = ("INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, automation_kind, mass_run_id, "
            "funnel_step, purchased_at, created_at, ingested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,0,0,0,?,?,?,?,?,?)")
_CHAT_SQL = ("INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, "
             "unread_count, is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')")


def _audience(fan_ids: list[int]) -> str:
    """mass_runs.audience_filter as A10 stores an explicit-fan send
    (send_mass_decide.audience_filter, same key order)."""
    return json.dumps({"user_lists": [], "included_users": list(fan_ids), "excluded_users": [],
                       "list_ids": [], "ref": None, "excluded_user_lists": [], "fence": False})


def _funnel(con, name: str, description: str, opener: str, steps: list[dict], b_at) -> int:
    made = ts(b_at - timedelta(days=3))
    return con.execute(_FUNNEL_SQL, (name, description, opener, "[]", json.dumps(steps), made, made)).lastrowid


def _run(con, aid: str, fid: int, b_at, fan_ids: list[int]) -> int:
    """A10's broadcast anchor for `fan_ids`, closed ok 2 min after it started."""
    return con.execute(_RUN_SQL, (aid, fid, _audience(fan_ids), len(fan_ids), "send_mass_message", ts(b_at),
                                  ts(b_at + timedelta(minutes=2)), "ok")).lastrowid


def _msg_row(aid, f, mid, direction, when, body, *, kind=None, run=None, step=None, price=0, paid=None,
             bought=None, media=()) -> tuple:
    return (aid, f["id"], mid, direction, f["name"] if direction == "in" else aid, body,
            json.dumps(list(media)), len(media), price, paid,
            kind, run, step, ts(bought) if bought else None, ts(when), ts(when))


def seed(w: World, fans: dict[str, list[dict]], threads: list[dict], live: int) -> dict:
    """-> {"cases": {(aid, fan_id): case}, "runs": {aid: mass_run_id}, "funnel_id": id,
    "broadcast_at": datetime, "jump_fans": {aid: [fan]}}; also in w.data["house_funnel"]."""
    rng = w.rng("house_funnel")
    threaded = {(t["account_id"], t["fan_id"]) for t in threads}
    aids = sorted(fans)
    per = {a: live // len(aids) + (1 if i < live % len(aids) else 0) for i, a in enumerate(aids)}
    b_at = w.now - timedelta(hours=BROADCAST_H)
    con = w.sql()
    with con:
        fid = _funnel(con, "slop house funnel", "slop/seed/house_funnel.py", OPENER, STEPS, b_at)
        runs = {}
        for a in aids:
            con.execute(
                "INSERT INTO funnel_account_media(funnel_id, account_id, opening_media_ids, steps_media_json, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (fid, a, "[]", json.dumps({"3": {"media_files": [PPV_MEDIA_ID], "previews": []}}),
                 ts(b_at), ts(b_at)))
            runs[a] = _run(con, a, fid, b_at, [])   # audience + count once the recipients are drawn

    seq = MSG_ID_BASE
    cases: dict[tuple[str, int], str] = {}
    mrows, crows, srows, rrows, nrows = [], [], [], [], []

    def at(minutes: float):
        return w.now - timedelta(minutes=minutes)

    def msg(aid, f, direction, when, body, *, kind=None, run=None, step=None, price=0, paid=None, bought=None,
            media=()):
        nonlocal seq
        seq += 1
        mrows.append(_msg_row(aid, f, seq, direction, when, body, kind=kind, run=run, step=step, price=price,
                              paid=paid, bought=bought, media=media))
        return seq, when, body

    jump: dict[str, list[dict]] = {}
    for a in aids:
        pool = [f for f in fans[a] if (a, f["id"]) not in threaded]
        rng.shuffle(pool)
        n_live = per[a]
        n_jump = min(JUMP_PER_CREATOR, max(0, len(pool) - n_live - len(QUIET)))
        pool, jump[a] = pool[:len(pool) - n_jump], pool[len(pool) - n_jump:]
        for k, f in enumerate(pool):
            case = LIVE[k % len(LIVE)] if k < n_live else QUIET[(k - n_live) % len(QUIET)]
            cases[(a, f["id"])] = case
            last = msg(a, f, "out", b_at, OPENER, kind="send_mass_message", run=runs[a])
            cs, hist = _PLAN[case]
            for direction, mins, step in hist:
                if direction == "in":
                    last = msg(a, f, "in", at(mins), _IN)
                else:
                    s = STEPS[step - 1]
                    for i, line in enumerate(s["messages"]):
                        last = msg(a, f, "out", at(mins) + timedelta(seconds=4 * i), line,
                                   kind="reply_mass_funnel", run=runs[a], step=step)
            if case == "buyer":   # a chatter's PPV, unlocked since the broadcast
                last = msg(a, f, "out", at(50), "something special 🔥", price=CHATTER_PPV_CENTS, paid=1,
                           bought=at(20), media=(CHATTER_PPV_MEDIA_ID,))
                nrows.append((a, f["id"], last[0], ts(at(20))))
            if cs is not None:
                rrows.append((a, fid, f["id"], runs[a], ts(at(100))))
                srows.append((runs[a], f["id"], cs, cs - 1, ts(at(1)), 0, "pending", ts(at(3))))
            crows.append((a, f["id"], last[0], ts(last[1]), last[2], 1 if last[2] == _IN else 0))
    with con:
        con.executemany(_MSG_SQL, mrows)
        con.executemany(
            "INSERT INTO purchase_notices(account_id, fan_id, message_id, notified_at) VALUES (?,?,?,?)", nrows)
        con.executemany(_CHAT_SQL, crows)
        con.executemany(
            "INSERT INTO funnel_responders(account_id, funnel_id, fan_id, mass_run_id, first_replied_at) "
            "VALUES (?,?,?,?,?)", rrows)
        con.executemany(
            "INSERT INTO funnel_state(mass_run_id, fan_id, current_step, last_sent_step, next_check_at, "
            "check_count, status, updated_at) VALUES (?,?,?,?,?,?,?,?)", srows)
        for a in aids:
            got = [f for (x, f) in cases if x == a]
            con.execute("UPDATE mass_runs SET recipient_count=?, audience_filter=? WHERE id=?",
                        (len(got), _audience(got), runs[a]))
    con.close()
    out = {"cases": cases, "runs": runs, "funnel_id": fid, "broadcast_at": b_at, "jump_fans": jump}
    w.data["house_funnel"] = out
    return out


def seed_jump(w: World, jump: dict[str, list[dict]]) -> dict:
    """The branching funnel (JUMP_STEPS) and, per Creator with held-out fans, one
    broadcast BROADCAST_H ago to just them, as A10 leaves it (the funnel, the
    `mass_runs` row, one tagged opener per recipient, its `chats` row). Nobody is
    enrolled: each answers live, so discovery enrolls him and the same tick sends
    step 1. -> {"runs": {aid: mass_run_id}, "fans": [(aid, fan_id)], "funnel_id": id}."""
    b_at = w.now - timedelta(hours=BROADCAST_H)
    aids = sorted(a for a, fl in jump.items() if fl)
    con = w.sql()
    runs, fans_out, mrows, crows = {}, [], [], []
    with con:
        fid = _funnel(con, "slop jump funnel", "slop/seed/house_funnel.py seed_jump", JUMP_OPENER, JUMP_STEPS,
                      b_at)
        seq = JUMP_MSG_ID_BASE
        for a in aids:
            runs[a] = _run(con, a, fid, b_at, [f["id"] for f in jump[a]])
            for f in jump[a]:
                seq += 1
                fans_out.append((a, f["id"]))
                mrows.append(_msg_row(a, f, seq, "out", b_at, JUMP_OPENER, kind="send_mass_message", run=runs[a]))
                crows.append((a, f["id"], seq, ts(b_at), JUMP_OPENER, 0))
        con.executemany(_MSG_SQL, mrows)
        con.executemany(_CHAT_SQL, crows)
    con.close()
    return {"runs": runs, "fans": fans_out, "funnel_id": fid}
