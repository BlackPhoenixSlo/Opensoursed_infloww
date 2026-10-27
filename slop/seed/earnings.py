"""Earnings: what OnlyFans' Statistics holds for each Creator, and the part of it
the ledger caught.

OF's side goes to `$DEMO_SHOTS_TMP/of-statistics.json` (lib/relay.py's fake
`earnings_chart` / `my_profile_stats` / `subscribers_chart` answer from it):
per Creator, net cents and a count per UTC day and Statements category, for
`history_days` complete days before today. One Creator has a free page (no
subscriptions, as an owner's Rhy), posts sell on a few days, streams never, and
each Creator has one chargeback day in the last 30 days whose tips net is
negative (the ledger holds no tip that day: max(OF, ledger) reads $0).

The ledger's side is `transactions` rows (source 'ledger', as the payouts ingest
writes them: gross, OF's net at 80%, cleared after 7 days else pending): a
trickle (`trickle` of OF's money) in the month before the Creator was connected
(`connected_days` ago, which `accounts.created_at` is set to), most of it
(`capture`) since, and some sales today, which OF has no complete day for yet.

Two days OF and the ledger disagree on (`w.data["earnings_cases"]`):
  zero day      `zero_back` days ago OF charts $0 for every Creator while the
                ledger holds one pending $14 PPV message (app.inflowwww.com,
                2026-10-25: the sale OF's figure must not erase)
  midnight      for the first Creator, a PPV message at 23:30 in `midnight_tz`
                on the day `midnight_back` days ago, which is 06:30 UTC the next
                day and OF charts on that UTC day; that Creator has no other
                sale from the day before to the day after the next (a report in
                that zone sees this one sale alone)
Deterministic from the World's seed."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from . import World, ts

KIND = {"subscribes": "subscription", "tips": "tip", "messages": "ppv_message", "post": "ppv_post"}
TX_ID_BASE = 8_100_000_000


def _day_net(rng, c: str, base: dict, weekday: int) -> tuple[int, int]:
    """One day of one category: (net cents, sales)."""
    b = base[c]
    if b <= 0 or (c == "post" and rng.random() > 0.08):
        return 0, 0
    net = round(b * (1.25 if weekday >= 4 else 1.0) * math.exp(rng.gauss(0, 0.45)) * 100)
    avg = {"subscribes": 900, "tips": 1600, "messages": 2400, "post": 700}[c]
    return net, max(1, round(net / avg))


ZERO_SALE_CENTS = 1400     # the $14 PPV message of the zero day
MIDNIGHT_SALE_CENTS = 2500


def seed(w: World, creators: list[dict], tmp: Path, *, history_days: int, connected_days: int,
         capture: float = 0.96, trickle: float = 0.03, zero_back: int = 2, midnight_back: int = 6,
         midnight_tz: str = "America/Los_Angeles") -> dict:
    rng = w.rng("earnings")
    today = w.now.date()
    zero_day = (today - timedelta(days=zero_back)).isoformat()
    local_day = today - timedelta(days=midnight_back)
    tz = ZoneInfo(midnight_tz)
    midnight_at = (datetime.combine(local_day, time(23, 30), tzinfo=tz).astimezone(timezone.utc)
                   .replace(tzinfo=None))
    quiet = {(local_day + timedelta(days=k)).isoformat() for k in (-1, 0, 1, 2)}
    connected = today - timedelta(days=connected_days)
    truth: dict[str, dict] = {}
    ledger: list[tuple] = []
    tx_id = TX_ID_BASE
    con = w.sql()
    fans = {c["id"]: [f["id"] for f in w.data.get("fans", {}).get(c["id"], [])] or [1] for c in creators}
    for i, c in enumerate(creators):
        aid = c["id"]
        base = {"messages": rng.uniform(900, 3600), "tips": rng.uniform(120, 520),
                "subscribes": 0.0 if i == 0 else rng.uniform(40, 190), "post": rng.uniform(2, 14)}
        earned: dict[str, dict[str, list[int]]] = {}
        refund_day = (today - timedelta(days=rng.randint(12, 29))).isoformat()  # in the last 30 days
        for back in range(history_days, 0, -1):
            d = today - timedelta(days=back)
            day = earned[d.isoformat()] = {}
            for cat in KIND:
                net, n = _day_net(rng, cat, base, d.weekday())
                if cat == "tips" and d.isoformat() == refund_day:
                    net, n = -round(base["tips"] * 60), 0  # chargebacks over the day's tips
                if net or n:
                    day[cat] = [net, n]
        earned[zero_day] = {}
        if i == 0:
            for d in quiet:
                earned[d] = {}
            earned[midnight_at.date().isoformat()] = {"messages": [round(MIDNIGHT_SALE_CENTS * 0.8), 1]}
        visitors = {d: rng.randint(200, 3000) for d in earned}
        new_subs = {d: rng.randint(0, 40) for d in earned}
        renewals = {d: rng.randint(0, 25) for d in earned}
        truth[aid] = {"earnings": earned, "visitors": visitors, "new_subs": new_subs, "renewals": renewals}

        # The ledger: rows summing to a share of each day's OF gross, split into sales.
        def rows_for(d, gross_cents: int, kind: str, *, until: datetime | None = None):
            nonlocal tx_id
            while gross_cents > 0:
                amt = min(gross_cents, rng.choice((500, 1000, 1500, 2500, 5000, 10000)))
                gross_cents -= amt
                at = datetime.combine(d, datetime.min.time()) + timedelta(seconds=rng.randint(0, 86_399))
                if until is not None and at >= until:
                    at = until - timedelta(seconds=rng.randint(60, 3600))
                net = round(amt * 0.8)
                tx_id += 1
                status = "cleared" if (today - d).days > 7 else "pending"
                ledger.append((aid, rng.choice(fans[aid]), kind, amt, "USD", ts(at), ts(w.now), str(tx_id), status,
                               net, amt - net, 0, "ledger"))
        for back in range(30 + connected_days, 0, -1):
            d = today - timedelta(days=back)
            share = capture if d >= connected else trickle
            if d.isoformat() == zero_day or (i == 0 and d.isoformat() in quiet):
                continue
            for cat, (net, _n) in earned.get(d.isoformat(), {}).items():
                if net > 0:
                    rows_for(d, round(net / 0.8 * share), KIND[cat])

        def one_sale(at: datetime, gross: int) -> None:
            nonlocal tx_id
            tx_id += 1
            net = round(gross * 0.8)
            ledger.append((aid, rng.choice(fans[aid]), "ppv_message", gross, "USD", ts(at), ts(w.now), str(tx_id),
                           "cleared" if (today - at.date()).days > 7 else "pending", net, gross - net, 0, "ledger"))
        one_sale(datetime.combine(date.fromisoformat(zero_day), time(19, 0, 3)), ZERO_SALE_CENTS)
        if i == 0:
            one_sale(midnight_at, MIDNIGHT_SALE_CENTS)
        for cat, mean in (("messages", base["messages"]), ("tips", base["tips"])):
            rows_for(today, round(mean * 100 / 0.8 * 0.4), KIND[cat], until=w.now)
        con.execute("UPDATE accounts SET created_at=? WHERE id=?",
                    (ts(datetime.combine(connected, datetime.min.time()) + timedelta(hours=9)), aid))
    with con:
        con.executemany(
            "INSERT INTO transactions(account_id, fan_id, kind, amount_cents, currency, occurred_at, ingested_at, "
            "provider_transaction_id, status, net_cents, fee_cents, vat_cents, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ledger)
    con.close()
    (tmp / "of-statistics.json").write_text(json.dumps(truth))
    w.data["of_statistics"] = truth
    w.data["ledger_rows"] = len(ledger)
    w.data["connected"] = connected.isoformat()
    w.data["earnings_cases"] = {
        "zero_day": zero_day, "zero_sale_cents": ZERO_SALE_CENTS,
        "midnight": {"account_id": creators[0]["id"], "tz": midnight_tz, "local_day": local_day.isoformat(),
                     "utc": ts(midnight_at), "gross_cents": MIDNIGHT_SALE_CENTS}}
    return truth
