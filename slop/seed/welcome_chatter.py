from __future__ import annotations

import json
from datetime import timedelta

from ..lib.wcfi_relay import PERSONA
from . import World, ts

KIND = "welcome_chatter_for_info"
# above threads' / followup_drip's / house_funnel's ids, below the relay's bands
MSG_ID_BASE = 9_000_980_000_000
SWEEP_EVERY_S = 86_400
LAST_FIRE_MIN = 30
ELIGIBLE = ("open", "double")
SKIPPED = ("blacklisted", "skiplisted", "muted", "promo")
CYCLE = ("open", "blacklisted", "double", "skiplisted", "muted", "promo",
         "open", "double", "open", "double", "open", "double")
PROMO_LINE = "<p><strong>FLASH SALE!!</strong> 70% off my VIP page onlyfans.com/slop-peer</p>"
_IN, _OUT = ("hey gorgeous", "how was your day"), ("hiii you 😘", "long day, better now")


def seed(w: World, fans: dict[str, list[dict]], threads: list[dict], live: int) -> dict:
    rng = w.rng("welcome_chatter")
    threaded = {(t["account_id"], t["fan_id"]) for t in threads}
    aids = sorted(fans)
    per = {a: live // len(aids) + (1 if i < live % len(aids) else 0) for i, a in enumerate(aids)}
    con = w.sql()
    rules: dict[str, int] = {}
    with con:
        for a in aids:
            con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents)"
                        " VALUES (?, 0, 100)", (a,))
            con.execute("UPDATE account_ai_config SET persona=?, webhook_config_json=? WHERE account_id=?",
                        (PERSONA, json.dumps({"enabled": True, "delay_seconds": 0, "jitter_seconds": 0}), a))
            rid = con.execute(
                "INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, is_enabled, created_at)"
                " VALUES (?,?,?,?,?,1,?)", (a, "Welcome chatter", KIND, json.dumps({"every_seconds": SWEEP_EVERY_S}),
                                            "{}", ts(w.now - timedelta(days=2)))).lastrowid
            fired = w.now - timedelta(minutes=LAST_FIRE_MIN)
            con.execute("INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts, rule_id,"
                        " created_at) VALUES (?,?,?,?,?,?,?,?)", (a, KIND, "{}", ts(fired), "done", 1, rid, ts(fired)))
            rules[a] = rid

    seq = MSG_ID_BASE
    cases: dict[tuple[str, int], str] = {}
    mrows, crows, brows, srows, fan_upd = [], [], [], [], []
    for a in aids:
        pool = [f for f in fans[a] if (a, f["id"]) not in threaded]
        rng.shuffle(pool)
        for k, f in enumerate(pool[:per[a]]):
            case = CYCLE[k % len(CYCLE)]
            cases[(a, f["id"])] = case
            t0 = w.now - timedelta(hours=rng.randint(24, 72))
            hist = [("in", rng.choice(_IN)), ("out", rng.choice(_OUT))]
            if case == "double":
                hist.append(("in", "u there?"))
            elif case == "promo":
                hist = [("in", PROMO_LINE)]
            last = None
            for j, (d, body) in enumerate(hist):
                seq += 1
                at = t0 + timedelta(minutes=5 * j)
                mrows.append((a, f["id"], seq, d, f["name"] if d == "in" else a, body, ts(at), ts(at)))
                last = (seq, at, body, d)
            crows.append((a, f["id"], last[0], ts(last[1]), last[2], 1 if last[3] == "in" else 0))
            if case == "blacklisted":
                brows.append((f["id"], "slop: blacklisted by the team", ts(w.now - timedelta(days=1))))
            elif case == "skiplisted":
                srows.append((a, f["id"], "manual_restrict", ts(w.now - timedelta(days=1))))
            elif case == "muted":
                fan_upd.append((1, "creator_we_follow", f["spend_cents"], a, f["id"]))
            elif case == "promo":
                fan_upd.append((0, "creator_we_follow", 0, a, f["id"]))
    with con:
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, is_unsent, is_promise, created_at, ingested_at) "
            "VALUES (?,?,?,?,?,?,'[]',0,0,NULL,0,0,0,?,?)", mrows)
        con.executemany(
            "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, "
            "unread_count, is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')", crows)
        con.executemany("INSERT INTO blacklist(fan_id, reason, added_at) VALUES (?,?,?)", brows)
        con.executemany("INSERT INTO skip_list(account_id, fan_id, reason, added_at) VALUES (?,?,?,?)", srows)
        con.executemany("UPDATE fans SET is_muted=?, source=?, lifetime_spend_cents=?, turn_counter=0 "
                        "WHERE account_id=? AND fan_id=?", fan_upd)
    con.close()
    out = {"cases": cases, "rules": rules}
    w.data["welcome_chatter"] = out
    return out
