#!/usr/bin/env python3
"""Historical inbound-DM peak rates per account, from a COPY of the relay DB.

Read-only (opens the file with mode=ro): run it on a backup, never the live
chatterly.db. Counts `event_inbox` rows of type api2_chat_message whose
fromUser is not the account (inbound DMs) in wall-clock-aligned buckets, and
prints per account and for the whole fleet (the single SQLite writer sees the
fleet): total, mean per minute over active minutes, and the busiest 1 min,
10 s and 1 s buckets with when; then the top bursts (10 s buckets). With
--all-events the fleet line also counts every event_inbox row (each one a
persisted write, typing excluded as the relay never persists it).

  venv/bin/python scripts/dm_peak_rates.py /path/to/chatterly-copy.db
  venv/bin/python scripts/dm_peak_rates.py copy.db --since 2026-10-01 --top 20 --json

--clock received (default): event_inbox.received_at, when the relay committed
the row (the write load; a persist batch shares one instant to within ms).
--clock created: the DM's own createdAt from OnlyFans (when the fan sent it).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

BUCKETS = (("1min", 60), ("10s", 10), ("1s", 1))


def _epoch(s: str | None) -> float | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)  # the relay stores naive UTC
    return d.timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Series:
    def __init__(self) -> None:
        self.n = 0
        self.b = {name: Counter() for name, _ in BUCKETS}

    def add(self, t: float) -> None:
        self.n += 1
        for name, w in BUCKETS:
            self.b[name][int(t // w)] += 1

    def summary(self) -> dict:
        out = {"total": self.n, "active_minutes": len(self.b["1min"]),
               "mean_per_active_min": round(self.n / len(self.b["1min"]), 2) if self.b["1min"] else 0}
        for name, w in BUCKETS:
            if self.b[name]:
                k, v = max(self.b[name].items(), key=lambda kv: (kv[1], -kv[0]))
                out[f"peak_{name}"] = {"n": v, "at": _iso(k * w)}
        return out


def scan(con: sqlite3.Connection, clock: str, since: float | None, account: str | None,
         all_events: bool) -> tuple[dict[str, Series], Series, Series | None]:
    per: dict[str, Series] = {}
    fleet = Series()
    q = ("SELECT account_id, received_at, json_extract(payload_json, '$.api2_chat_message.createdAt'), "
         "json_extract(payload_json, '$.api2_chat_message.fromUser.id') "
         "FROM event_inbox WHERE event_type = 'api2_chat_message'")
    args: list = []
    if account:
        q += " AND account_id = ?"
        args.append(account)
    for aid, received, created, from_id in con.execute(q, args):
        if from_id is not None and str(from_id) == str(aid):
            continue  # an outbound echo
        t = _epoch(created if clock == "created" else received)
        if t is None or (since is not None and t < since):
            continue
        per.setdefault(str(aid), Series()).add(t)
        fleet.add(t)
    rows = None
    if all_events:
        rows = Series()
        q = "SELECT received_at FROM event_inbox" + (" WHERE account_id = ?" if account else "")
        for (received,) in con.execute(q, [account] if account else []):
            t = _epoch(received)
            if t is not None and (since is None or t >= since):
                rows.add(t)
    return per, fleet, rows


def top_bursts(per: dict[str, Series], n: int) -> list[dict]:
    allb = [(v, k, aid) for aid, s in per.items() for k, v in s.b["10s"].items()]
    allb.sort(key=lambda x: (-x[0], x[1]))
    return [{"account_id": aid, "at": _iso(k * 10), "dms_in_10s": v,
             "per_min_rate": v * 6} for v, k, aid in allb[:n]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", help="a COPY of chatterly.db (opened read-only)")
    ap.add_argument("--clock", choices=("received", "created"), default="received")
    ap.add_argument("--since", help="ISO date/time (UTC), e.g. 2026-10-01")
    ap.add_argument("--account", help="one account id")
    ap.add_argument("--top", type=int, default=10, help="top N 10 s bursts (default 10)")
    ap.add_argument("--all-events", action="store_true", help="also every event_inbox row, fleet-wide")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    a = ap.parse_args(argv)

    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=30)
    try:
        per, fleet, rows = scan(con, a.clock, _epoch(a.since) if a.since else None, a.account, a.all_events)
    finally:
        con.close()
    report = {"clock": a.clock, "since": a.since,
              "accounts": {aid: s.summary() for aid, s in sorted(per.items(), key=lambda kv: -kv[1].n)},
              "fleet_dms": fleet.summary(), "top_bursts_10s": top_bursts(per, a.top)}
    if rows is not None:
        report["fleet_event_inbox_rows"] = rows.summary()
    if a.json:
        json.dump(report, sys.stdout, indent=1)
        print()
        return 0

    def line(name: str, s: dict) -> str:
        pk = lambda k: f"{s[k]['n']:>5} @ {s[k]['at']}" if k in s else f"{'-':>5}"  # noqa: E731
        return (f"{name[:22]:<22} {s['total']:>8} {s['mean_per_active_min']:>8} "
                f"{pk('peak_1min'):>27} {pk('peak_10s'):>27} {pk('peak_1s'):>27}")
    print(f"inbound DMs per account (clock={a.clock}; buckets wall-clock aligned, UTC)")
    print(f"{'account':<22} {'DMs':>8} {'/act.min':>8} {'peak 1 min':>27} {'peak 10 s':>27} {'peak 1 s':>27}")
    for aid, s in report["accounts"].items():
        print(line(aid, s))
    print(line("FLEET (all accounts)", report["fleet_dms"]))
    if rows is not None:
        print(line("FLEET event_inbox rows", report["fleet_event_inbox_rows"]))
    print(f"\ntop {a.top} bursts (10 s buckets):")
    for b in report["top_bursts_10s"]:
        print(f"  {b['at']}  {b['account_id']:<22} {b['dms_in_10s']:>4} DMs  (= {b['per_min_rate']}/min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
