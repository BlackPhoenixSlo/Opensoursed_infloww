from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

LO, HI = 12_345, 54_321
TAG = "whale"
# above seed/earnings.py's TX_ID_BASE band
TX_ID_BASE = 8_900_000_000
SHARED = 4
SHARED_TIP = 77_777
V1_LO, V1_HI = 999, 12_000
_COPIED = ("fan_id", "of_username", "of_display_name", "avatar_url", "is_name_real", "subscribed_at",
           "subscription_expires_at", "subscription_status", "is_followed", "source",
           "created_at", "updated_at")
_FRESH = {"account_id": "?", "lifetime_spend_cents": "?", "recent_events": "'[]'",
          "likes_boobs": "0", "likes_ass": "0", "family_names": "'[]'", "pets": "'[]'",
          "communication_style": "'[]'", "custom_fields": "'{}'", "is_bot": "0", "turn_counter": "0",
          "deep_convo_state": "'idle'", "deep_convo_skip_level": "0", "deep_convo_skip_remaining": "0",
          "tags": "'[]'"}
_COPY = (f"INSERT INTO fans({', '.join((*_FRESH, *_COPIED))}) SELECT {', '.join((*_FRESH.values(), *_COPIED))}"
         " FROM fans WHERE account_id=? AND fan_id=?")


def copy_lifetime(orig: int) -> int:
    return 50_000 if V1_LO <= orig <= V1_HI else 2_500


def seed(w: World, creators: list[dict], *, n: int) -> dict:
    rng = w.rng("smart_list_facts")
    con = w.sql()
    last = con.execute(
        "SELECT account_id, fan_id, MAX(CASE WHEN direction='in' THEN created_at END),"
        " MAX(CASE WHEN direction='out' THEN created_at END) FROM messages GROUP BY account_id, fan_id").fetchall()
    out: dict = {"last_message_fans": len(last), "creators": {}, "shared": []}
    tx_id = TX_ID_BASE
    txs, tags, expired = [], [], []

    def tip(aid: str, fid: int, cents: int) -> None:
        nonlocal tx_id
        tx_id += 1
        at = w.now - timedelta(days=rng.randint(8, 25), seconds=rng.randint(0, 86_399))
        net = round(cents * 0.8)
        txs.append((aid, fid, "tip", cents, "USD", ts(at), ts(w.now), str(tx_id), "cleared", net, cents - net,
                    0, "ledger"))

    for k, c in enumerate(creators):
        aid = c["id"]
        ids = [f["id"] for f in w.data["fans"][aid]]
        spent = {r[0] for r in con.execute(
            "SELECT DISTINCT fan_id FROM transactions WHERE account_id=? AND fan_id IS NOT NULL", (aid,))}
        free = [f for f in ids if f not in spent]
        bounds = dict(zip(rng.sample(free, 4), (LO, HI, LO - 1, HI + 1))) if len(free) >= 4 else {}
        for fid, cents in bounds.items():
            tip(aid, fid, cents)
        tagged = rng.sample(ids, min(n, len(ids)))
        tags += [(json.dumps([TAG]), aid, fid) for fid in tagged]
        lapsed = rng.sample(ids, min(n, len(ids)))
        expired += [(ts(w.now - timedelta(days=rng.randint(1, 60))), aid, fid) for fid in lapsed]
        rest = [f for f in free if f not in bounds]
        if k >= 1 and len(rest) >= SHARED:
            for fid in rng.sample(rest, SHARED):
                tip(aid, fid, SHARED_TIP)
                tags.append((json.dumps([TAG]), aid, fid))
                out["shared"].append({"fan_id": fid, "a": creators[k - 1]["id"], "b": aid})
        out["creators"][aid] = {"bounds": {str(f): v for f, v in bounds.items()}, "tagged": len(tagged),
                                "expired": len(lapsed)}
    if not any(v["bounds"] for v in out["creators"].values()) or not out["shared"]:
        con.close()
        raise SystemExit(f"slop: smart_list_facts: no Creator got bound fans or no shared fan was seeded "
                         f"(shared {len(out['shared'])}, bounds per Creator "
                         f"{ {a: len(v['bounds']) for a, v in out['creators'].items()} })")
    by_id = {(f["account_id"], f["id"]): f for fs in w.data["fans"].values() for f in fs}
    for s in out["shared"]:
        s["lifetime"] = copy_lifetime(by_id[(s["b"], s["fan_id"])]["spend_cents"])
    with con:
        con.executemany("UPDATE fans SET last_message_received_at=?, last_message_sent_at=?"
                        " WHERE account_id=? AND fan_id=?", [(i, o, a, f) for a, f, i, o in last])
        con.executemany(
            "INSERT INTO transactions(account_id, fan_id, kind, amount_cents, currency, occurred_at, ingested_at, "
            "provider_transaction_id, status, net_cents, fee_cents, vat_cents, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", txs)
        con.executemany("UPDATE fans SET tags=? WHERE account_id=? AND fan_id=?", tags)
        con.executemany("UPDATE fans SET subscription_status='expired', subscription_expires_at=?"
                        " WHERE account_id=? AND fan_id=?", expired)
        con.executemany(_COPY, [(s["a"], s["lifetime"], s["b"], s["fan_id"]) for s in out["shared"]])
    con.close()
    for s in out["shared"]:
        w.data["fans"][s["a"]].append({**by_id[(s["b"], s["fan_id"])], "account_id": s["a"],
                                       "spend_cents": s["lifetime"]})
    w.data["smart_list_facts"] = out
    return out
