"""Smart-list facts: the per-fan facts service/smart_list_rules reads that no other seeder writes.

What the rules read (smart_lists_api `_load_normalised_fans` / `_ledger_facts` / `_snapshot`):
  fans          lifetime_spend_cents, last_message_received_at, last_message_sent_at, subscribed_at,
                subscription_expires_at, subscription_status, tags
  transactions  account_id, fan_id, kind, amount_cents, status, occurred_at (spend, last purchase, idle)
  subscriber_snapshot (status / renew / sub dates; none seeded: every fan falls back to its fan row)
seed/fans.py writes lifetime_spend_cents, subscribed_at (whole days ago), subscription_expires_at,
subscription_status ('active') and tags '[]'; seed/earnings.py the ledger rows. This seeder adds:

  last message  fans.last_message_received_at / last_message_sent_at = the newest inbound / outbound
                `messages` row of the fan's thread (seed/threads.py), as the transcoder keeps them
  bound fans    per Creator in `creators` with 4+ fans without a ledger row, 4 of them get one
                cleared tip (source 'ledger') of exactly LO, HI, LO - 1 and HI + 1 cents, so
                `between [LO, HI]` and every threshold on LO / HI has a fan exactly on it and one just
                past (the big Creators always qualify; a small one whose every fan has ledger rows gets none)
  tags          `n` fans per Creator in `creators` tagged '["whale"]' (the fan panel's tag write)
  expired       `n` fans per Creator in `creators` with subscription_status 'expired' and
                subscription_expires_at 1..60 days ago (the roster crawl's write for a lapsed fan)
  shared fans   one OF user subscribed to two of `creators` (fans' PK is (account_id, fan_id)): for each
                creators[k] (k >= 1) with SHARED more ledger-free fans, SHARED of them get a cleared tip
                of SHARED_TIP cents and the whale tag there, and a fans row (same fan_id) on creators[k - 1]:
                identity and subscription columns copied, its own lifetime (copy_lifetime: inside
                [V1_LO, V1_HI] iff the original's is not), the rest as seed/fans.py writes a new fan (no
                ledger, tags, messages or AI facts). Rules on k - 1 must read k - 1's facts only.

Randomness only from w.rng("smart_list_facts"); output in w.data["smart_list_facts"]
({"creators": {id: {bounds, tagged, expired}}, "shared": [{fan_id, a, b}]}); the shared rows are
appended to w.data["fans"][a]. SystemExit (INFRA) when no Creator got bound fans or no shared fan was
seeded: the scenario's rows would test nothing there."""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

LO, HI = 12_345, 54_321          # cents
TAG = "whale"
TX_ID_BASE = 8_900_000_000       # above seed/earnings.py's TX_ID_BASE band
SHARED = 4                       # shared fans per Creator pair
SHARED_TIP = 77_777              # cents, on the shared fan's original Creator only
V1_LO, V1_HI = 999, 12_000      # the scenario's v1 lifetime `between` row
# a shared fan's row on the second Creator: identity + subscription copied from the original's row, its own
# lifetime (?), the rest seed/fans.py's new-fan values
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
    """The copy's lifetime cents (a seed/fans.py value): on the other side of [V1_LO, V1_HI] from `orig`."""
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
        # a Creator whose every fan already has ledger rows (a small one) gets none
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
