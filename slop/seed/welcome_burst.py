"""send_welcome's world (scenarios/2026-10-30-welcome-burst.py): per Creator, three kinds of
subscriber OnlyFans' subscribe feed shows at once, and the rows the product left for each.

  new          brand-new subs: no `fans` row, no messages, no claim (fresh ids, above the
               Creator's seeded fans: FAN_ID_BASE + i * 1e6 + NEW_ID_OFFSET + k).
  welcomed     renewals of fans the welcome already greeted: their `welcome_sent` claim and
               the two outbound rows that burst wrote (greeting + question,
               `automation_kind='welcome'`), 2..30 days ago. Two outbound rows is at the
               NOT-NEW tolerance (> 2 is established), so only the claim keeps them out.
  established  renewals with a real history: 4 outbound + 10 inbound rows, 3..60 days ago
               (> 2 out, > 8 in), no claim (they pre-date the automation).

Both renewal kinds are picked from the Creator's seeded fans without a thread (no other
history). Every seeded message is older than 2 days, past the 12 h contact guard, so the
guard never decides a case. `of_welcome_on`: the Creators whose OnlyFans welcome
(`replyOnSubscribe` + a `reply_on_subscribe` template) is on, `round(frac * Creators)`, at
least one, never all (when there are 2+). `feed`: per Creator, the notification items OF
serves (`type: subscribed`, `createdAt` 1..30 min ago, `user`), newest first, renewals mixed
in; the scenario writes it to `of-welcome.json` (lib/welcome_relay.py).

Sizes are the scenario's (`--set new=`, `welcomed=`, `established=`, `of_on_frac=`), randomness only `w.rng("welcome_burst")`.
Declared: the seeded welcome rows carry no `sent_by_employee_id` (the product's attribution
resolves the system Automation employee); nothing else differs from what it writes.
"""
from __future__ import annotations

from datetime import timedelta

from . import World, ts
from .fans import FAN_ID_BASE

MSG_ID_BASE = 9_000_980_000_000   # above threads' / followup_drip's / house_funnel's, below the relay's
NEW_ID_OFFSET = 900_000
QUESTION = "what are you up to rn?"
_FIRST = ("Alex", "Ben", "Carl", "Dan", "Eli", "Finn", "Gus", "Hank", "Ivan", "Jack", "Kyle", "Liam")
_IN, _OUT = ("hey", "you up?", "nice pic", "lol", "send more"), ("hi babe", "miss you", "check inbox")


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seed(w: World, fans: dict[str, list[dict]], threads: list[dict], *, new: int, welcomed: int,
         established: int, of_on_frac: float) -> dict:
    """-> {new, welcomed, established: {aid: [fan ids]}, of_welcome_on: [aid], feed: {aid: [items]}};
    also in w.data["welcome_burst"]."""
    rng = w.rng("welcome_burst")
    threaded = {(t["account_id"], t["fan_id"]) for t in threads}
    aids = [c["id"] for c in w.data["creators"]]
    n_on = max(1, round(len(aids) * of_on_frac))
    if len(aids) > 1:
        n_on = min(n_on, len(aids) - 1)
    of_on = sorted(rng.sample(aids, n_on))
    out = {"new": {}, "welcomed": {}, "established": {}, "of_welcome_on": of_on, "feed": {}}
    seq = MSG_ID_BASE
    mrows, crows, wrows = [], [], []

    def msg(aid, f, direction, at, body, kind=None):
        nonlocal seq
        seq += 1
        mrows.append((aid, f["id"], seq, direction, f["name"] if direction == "in" else aid, body, kind,
                      ts(at), ts(at)))
        return seq

    for ci, aid in enumerate(aids):
        pool = [f for f in fans[aid] if (aid, f["id"]) not in threaded]
        rng.shuffle(pool)
        assert len(pool) >= welcomed + established, f"{aid}: {len(pool)} thread-less fans"
        wel, est = pool[:welcomed], pool[welcomed:welcomed + established]
        base = FAN_ID_BASE + ci * 1_000_000 + NEW_ID_OFFSET
        fresh = []
        for k in range(new):
            first = rng.choice(_FIRST)
            fresh.append({"id": base + k, "username": f"{first.lower()}_{base + k}", "name": first})
        for f in wel:
            at = w.now - timedelta(days=rng.uniform(2, 30))
            wrows.append((aid, f["id"], f["username"], ts(at)))
            msg(aid, f, "out", at, f"Hey {f['name'][0]}-{f['name'][0]}-{f['name'][0]}-Cute "
                                   f"{f['name'].split()[0]} ! !!", "welcome")
            last = msg(aid, f, "out", at + timedelta(seconds=20), QUESTION, "welcome")
            crows.append((aid, f["id"], last, ts(at + timedelta(seconds=20)), QUESTION, 0))
        for f in est:
            at = w.now - timedelta(days=rng.uniform(3, 60))
            last = None
            for j in range(14):
                d = "out" if j in (0, 3, 7, 10) else "in"     # 4 out, 10 in
                t, body = at + timedelta(hours=j), rng.choice(_OUT if d == "out" else _IN)
                last = (msg(aid, f, d, t, body), t, body)
            crows.append((aid, f["id"], last[0], ts(last[1]), last[2], 0))
        subs = [(s["id"], s["username"], s["name"]) for s in fresh] + \
               [(f["id"], f["username"], f["name"]) for f in wel + est]
        rng.shuffle(subs)
        mins = sorted(rng.sample(range(60, 1800), len(subs)))
        out["feed"][aid] = [{"type": "subscribed", "createdAt": _iso(w.now - timedelta(seconds=s)),
                             "user": {"id": fid, "username": un, "name": nm}}
                            for (fid, un, nm), s in zip(subs, mins)]
        out["new"][aid] = [s["id"] for s in fresh]
        out["welcomed"][aid] = [f["id"] for f in wel]
        out["established"][aid] = [f["id"] for f in est]
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
            "INSERT INTO welcome_sent(account_id, fan_id, fan_username, sent_at) VALUES (?,?,?,?)", wrows)
    con.close()
    w.data["welcome_burst"] = out
    return out
