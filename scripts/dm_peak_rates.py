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
  venv/bin/python scripts/dm_peak_rates.py copy.db --chatter-peak [--weeks 4] [--json]

--chatter-peak: peak chatters P = most distinct Employees sending manual outbound
messages (messages.sent_by_employee_id, created_at) in any sliding 15 min
window over the last --weeks weeks, ending at the newest such message.

--clock received (default): event_inbox.received_at, when the relay committed
the row (the write load; a persist batch shares one instant to within ms).
--clock created: the DM's own createdAt from OnlyFans (when the fan sent it).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
BUCKETS = (("1min", 60), ("10s", 10), ("1s", 1))


def _datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _epoch(s: str | None) -> float | None:
    d = _datetime(s)
    return d.timestamp() if d is not None else None


def _epoch_us(s: str | None) -> int | None:
    d = _datetime(s)
    if d is None:
        return None
    return (d - EPOCH) // timedelta(microseconds=1)


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
            continue
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


def chatter_peak(con: sqlite3.Connection, weeks: int, span: float = 900.0) -> dict:
    con.create_function("epoch_us", 1, _epoch_us, deterministic=True)
    where = ("direction = 'out' AND sent_by_employee_id IS NOT NULL "
             "AND mass_run_id IS NULL AND automation_kind IS NULL "
             "AND NOT EXISTS (SELECT 1 FROM employees WHERE id = messages.sent_by_employee_id "
             "AND display_name = 'Automation' AND is_active = 0)")
    (newest,) = con.execute(f"SELECT MAX(epoch_us(created_at)) FROM messages WHERE {where}").fetchone()
    out = {"P": 0, "window_start": None, "window_end": None, "weeks": weeks, "senders": [], "newest": None}
    if newest is None:
        return out
    out["newest"] = _iso(newest // 1_000_000)
    rows = con.execute(
        "SELECT epoch_us(created_at) AS t, sent_by_employee_id "
        f"FROM messages WHERE {where} AND epoch_us(created_at) >= ? ORDER BY t, sent_by_employee_id",
        (newest - 7 * weeks * 86400 * 1_000_000,))
    win: deque = deque()
    seen: Counter = Counter()
    span_us = round(span * 1_000_000)
    for t, emp in rows:
        win.append((t, emp))
        seen[emp] += 1
        while t - win[0][0] >= span_us:
            _, old = win.popleft()
            seen[old] -= 1
            if not seen[old]:
                del seen[old]
        if len(seen) > out["P"]:
            out.update(P=len(seen), window_start=_iso(win[0][0] // 1_000_000),
                       window_end=_iso((win[0][0] + span_us) // 1_000_000),
                       senders=[str(e) for e in sorted(seen)])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", help="a COPY of chatterly.db (opened read-only)")
    ap.add_argument("--clock", choices=("received", "created"), default=None)
    ap.add_argument("--since", default=None, help="ISO date/time (UTC), e.g. 2026-10-01")
    ap.add_argument("--account", default=None, help="one account id")
    ap.add_argument("--top", type=int, default=None, help="top N 10 s bursts (default 10)")
    ap.add_argument("--all-events", action="store_true", default=None, help="also every event_inbox row, fleet-wide")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--chatter-peak", action="store_true",
                    help="peak distinct sending Employees in any 15 min window (copy of msg_stats predicate)")
    ap.add_argument("--weeks", type=int, default=4, help="--chatter-peak lookback (default 4)")
    a = ap.parse_args(argv)

    incompatible = [opt for opt in ("account", "all_events", "clock", "since", "top") if getattr(a, opt) is not None]
    if a.chatter_peak and incompatible:
        ap.error("--chatter-peak cannot use " + ", ".join("--" + opt.replace("_", "-") for opt in incompatible))
    clock = a.clock or "received"
    top = a.top if a.top is not None else 10

    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=30)
    if a.chatter_peak:
        try:
            if not any(row[1] == "automation_kind" for row in con.execute("PRAGMA table_info(messages)")):
                ap.error("--chatter-peak requires Alembic revision 0032_automation_kind or later")
            cp = chatter_peak(con, a.weeks)
        finally:
            con.close()
        if a.json:
            json.dump({k: cp[k] for k in ("P", "window_start", "window_end", "weeks", "senders")}, sys.stdout)
            print()
        else:
            print(f"chatter peak P={cp['P']} window {cp['window_start'] or '-'}..{cp['window_end'] or '-'} UTC "
                  f"(15 min, last {cp['weeks']} weeks to {cp['newest'] or '-'})")
        return 0
    try:
        per, fleet, rows = scan(con, clock, _epoch(a.since) if a.since else None, a.account, bool(a.all_events))
    finally:
        con.close()
    report = {"clock": clock, "since": a.since,
              "accounts": {aid: s.summary() for aid, s in sorted(per.items(), key=lambda kv: -kv[1].n)},
              "fleet_dms": fleet.summary(), "top_bursts_10s": top_bursts(per, top)}
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
    print(f"inbound DMs per account (clock={clock}; buckets wall-clock aligned, UTC)")
    print(f"{'account':<22} {'DMs':>8} {'/act.min':>8} {'peak 1 min':>27} {'peak 10 s':>27} {'peak 1 s':>27}")
    for aid, s in report["accounts"].items():
        print(line(aid, s))
    print(line("FLEET (all accounts)", report["fleet_dms"]))
    if rows is not None:
        print(line("FLEET event_inbox rows", report["fleet_event_inbox_rows"]))
    print(f"\ntop {top} bursts (10 s buckets):")
    for b in report["top_bursts_10s"]:
        print(f"  {b['at']}  {b['account_id']:<22} {b['dms_in_10s']:>4} DMs  (= {b['per_min_rate']}/min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
