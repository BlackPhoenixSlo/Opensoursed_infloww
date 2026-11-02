"""Ledger at volume: the `transactions` rows the payouts ingest and the WS pump write for many
fans, the paid mass broadcasts the Message dashboard lists, and the free trial / promotion
claimers Fan reports' Traffic reads (scenarios/2026-11-01-ledger-reports-volume.py).

  transactions   `n` rows over the last `days` days, spread over the Creators by fan count, each
                 on one of the Creator's fans: kinds the ingest's KIND_CATALOG maps (tip, tip_post,
                 ppv_message, ppv_post, subscription, rebill, custom), each with that catalog's
                 description prefix and the fan's name; statuses as `_normalize_status` leaves
                 them (cleared, pending for the last 7 days, and the reversals chargedback /
                 refunded / refund_pending plus failed); ledger rows (source 'ledger') carry a
                 provider id and OF's net / fee (net = gross - round(20%); 1 in 200 with net 0,
                 as the ingest stores OF's `"net": 0`); 1 in 10 tips is a WS-pump row written as
                 event_transcoder writes it (source 'ws', status 'cleared', no provider id, no
                 net: `net_or_80` reads 80% of it), linked to its inbound tip message. The pump's
                 `fans.lifetime_spend_cents` bump is not written (no report reads it).
  paid mass      `runs` paid broadcasts per Creator (`mass_runs` closed as the manual send's close
                 step leaves them: status ok, queue_id, body, sent_at), each copy one outbound
                 `messages` row (price, `mass_run_id`) to `recipients` of its fans; a buyer's copy
                 is marked bought (is_paid, purchased_at), as the ledger link does, with its linked
                 ppv_message sale, 1 in 8 of them since refunded or charged back.
  link_claimers  1 in 5 fans claimed one of the Creator's 3 trial links / 2 promotions; 1 in 10
                 of those claimed a second one later (never after now); some without OF's
                 subscribe_at.

Amounts include ones whose 80% has a fraction >= .5 (742, 1497, 2997), so `net_or_80`'s floor
differs from a rounding. Deterministic from the World's seed (`w.rng("ledger_bulk")`); ids above
earnings' (tx 8.1e9) and below threads' history (msg 9e12). `w.data["ledger_bulk"]`: counts."""
from __future__ import annotations

from datetime import timedelta

from . import World, ts

PROVIDER_BASE = 8_300_000_000
MSG_ID_BASE = 8_500_000_000_000
LINK_OF_BASE = 77_000_000
QUEUE_BASE = 870_000_000_000

KINDS = (("tip", 24), ("tip_post", 6), ("ppv_message", 30), ("ppv_post", 10), ("subscription", 6),
         ("rebill", 18), ("custom", 6))
# transaction_ingest_decide.KIND_CATALOG: a description prefix each kind is classified from.
PREFIX = {"tip": "Tip from ", "tip_post": "Tip on post from ", "ppv_message": "Payment for message from ",
          "ppv_post": "Post purchase by ", "subscription": "Subscription from ",
          "rebill": "Recurring subscription from ", "custom": "Custom request from "}
AMOUNTS = (500, 742, 999, 1497, 1500, 2500, 2997, 5000, 10000)
SUB_AMOUNTS = (499, 999, 1499)
REVERSALS = (("chargedback", 0.03), ("refunded", 0.03), ("refund_pending", 0.02), ("failed", 0.03))
BUY_REVERSALS = (("refunded", 0.0625), ("chargedback", 0.0625))  # 1 in 8 bought copies reversed
PRICES = (999, 1497, 2500)
TX_COLS = ("account_id, fan_id, kind, message_id, amount_cents, currency, occurred_at, ingested_at, "
           "provider_transaction_id, status, net_cents, fee_cents, vat_cents, source, description")


def _status(rng, age_days: float, reversals=REVERSALS) -> str:
    x = rng.random()
    for st, p in reversals:
        if x < p:
            return st
        x -= p
    return "pending" if age_days < 7 else "cleared"


def seed(w: World, creators: list[dict], *, n: int, days: int = 60, runs: int = 4, recipients: int = 40) -> dict:
    rng = w.rng("ledger_bulk")
    fans = {c["id"]: [f["id"] for f in w.data["fans"][c["id"]]] for c in creators}
    names = {(c["id"], f["id"]): f["name"] for c in creators for f in w.data["fans"][c["id"]]}
    weights = [len(fans[c["id"]]) for c in creators]
    total_w = sum(weights)
    kinds, kw = zip(*KINDS)
    tx: list[tuple] = []
    msgs: list[tuple] = []
    claims: list[tuple] = []
    n_runs = ws_tips = paid_copies = 0
    prov = PROVIDER_BASE
    mid = MSG_ID_BASE
    con = w.sql()

    def tx_row(*, aid, fan, kind, amt, at, status, source="ledger", message_id=None):
        """One `transactions` row as its writer leaves it: the payouts ingest (source 'ledger': a provider
        id, OF's net / fee, the catalog description, ingested now) or the WS pump (source 'ws': none of
        those, ingested as it happened)."""
        nonlocal prov
        ingested, provider, net, fee, vat, desc = ts(at), None, None, None, None, None
        if source == "ledger":
            prov += 1
            fee = amt if rng.random() < 0.005 else round(amt * 0.2)
            ingested, provider, net, vat, desc = ts(w.now), str(prov), amt - fee, 0, PREFIX[kind] + names[(aid, fan)]
        tx.append((aid, fan, kind, message_id, amt, "USD", ts(at), ingested, provider, status, net, fee, vat, source,
                   desc))

    def message(*, aid, fan, direction, body, at, price=0, bought=None, is_tip=0, paid_at=None, run_id=None):
        msgs.append((aid, fan, mid, direction, "", body, "[]", 1 if price else 0, price, bought, is_tip,
                     ts(paid_at) if paid_at else None, None, run_id, None, ts(at), ts(at)))

    with con:
        # Paid mass broadcasts first (their copies precede the sales linked to them).
        for c in creators:
            aid, fl = c["id"], fans[c["id"]]
            for _ in range(runs):
                price = rng.choice(PRICES)
                sent = w.now - timedelta(seconds=rng.randint(3600, 40 * 86400))
                who = rng.sample(fl, min(recipients, len(fl)))
                n_runs += 1
                body = f"slop paid mass {n_runs}"
                run_id = con.execute(
                    "INSERT INTO mass_runs(account_id, started_by_employee_id, audience_filter, recipient_count, "
                    "automation_kind, started_at, completed_at, status, queue_id, body, sent_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, None, "{}", len(who), None, ts(sent), ts(sent + timedelta(minutes=2)), "ok",
                     QUEUE_BASE + n_runs, body, ts(sent))).lastrowid
                for k, fan in enumerate(who):
                    mid += 1
                    at = sent + timedelta(seconds=k % 120)
                    paid_at = at + timedelta(seconds=rng.randint(60, 86400)) if rng.random() < 0.15 else None
                    if paid_at is not None and paid_at > w.now:
                        paid_at = w.now - timedelta(seconds=1)
                    message(aid=aid, fan=fan, direction="out", body=body, at=at, price=price,
                            bought=1 if paid_at else 0, paid_at=paid_at, run_id=run_id)
                    paid_copies += 1
                    if paid_at:
                        st = _status(rng, (w.now - paid_at).total_seconds() / 86400, BUY_REVERSALS)
                        tx_row(aid=aid, fan=fan, kind="ppv_message", amt=price, at=paid_at, status=st, message_id=mid)

        # The bulk ledger, and each Creator's claimers.
        for c, wt in zip(creators, weights):
            aid, fl = c["id"], fans[c["id"]]
            for _ in range(round(n * wt / total_w)):
                fan = rng.choice(fl)
                kind = rng.choices(kinds, kw)[0]
                amt = rng.choice(SUB_AMOUNTS if kind in ("subscription", "rebill") else AMOUNTS)
                age = rng.uniform(0, days * 86400)
                at = (w.now - timedelta(seconds=age)).replace(microsecond=rng.randint(0, 999) * 1000)
                if kind == "tip" and rng.random() < 0.1:
                    mid += 1
                    message(aid=aid, fan=fan, direction="in", body=f"slop tip note {mid}", at=at, is_tip=1)
                    tx_row(aid=aid, fan=fan, kind="tip", amt=amt, at=at, status="cleared", source="ws", message_id=mid)
                    ws_tips += 1
                    continue
                tx_row(aid=aid, fan=fan, kind=kind, amt=amt, at=at, status=_status(rng, age / 86400))

            # Claimers: 1 in 5 fans, on one of 3 trial links / 2 promotions; 1 in 10 of them a second claim.
            links = [("trial", LINK_OF_BASE + int(aid) % 1_000_000 * 10 + j) for j in range(3)] + \
                    [("promo", LINK_OF_BASE + int(aid) % 1_000_000 * 10 + 5 + j) for j in range(2)]
            for fan in fl:
                if rng.random() >= 0.2:
                    continue
                picks = rng.sample(links, 2 if rng.random() < 0.1 else 1)
                sub = w.now - timedelta(days=rng.uniform(1, 200))
                for j, (lk, of_id) in enumerate(picks):
                    claimed = min(sub + timedelta(days=30 * j), w.now)
                    s_at = None if rng.random() < 0.15 else claimed
                    seen = min(claimed + timedelta(hours=rng.uniform(0, 48)), w.now)
                    claims.append((aid, lk, of_id, fan, None, f"u{fan}", ts(s_at) if s_at else None, ts(seen)))

        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_paid, is_tip, purchased_at, sent_by_employee_id, mass_run_id, "
            "automation_kind, created_at, ingested_at, is_unsent, is_promise) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)", msgs)
        con.executemany(f"INSERT INTO transactions({TX_COLS}) VALUES ({','.join('?' * 15)})", tx)
        con.executemany(
            "INSERT INTO link_claimers(account_id, kind, of_id, fan_id, name, username, subscribe_at, first_seen_at) "
            "VALUES (?,?,?,?,?,?,?,?)", claims)
    con.close()
    out = {"transactions": len(tx), "ws_tips": ws_tips, "paid_copies": paid_copies, "link_claimers": len(claims),
           "runs": n_runs}
    w.data["ledger_bulk"] = out
    return out
