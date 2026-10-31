"""of_stats_parse — OnlyFans' Statistics replies read as per-UTC-day figures,
for of_stats_daily to store. Pure: no DB, no client, no clock.

A reply in a shape not checked here (not one point per consecutive day, a
weekly bucket, categories not adding up to OF's own total) parses to None:
of_stats_daily stores nothing for it. The days kept are only those in the
[first, last] asked; of_stats_daily asks through yesterday, so today (still
counting) is never stored. Shapes: service/tests/fixtures/of_statistics_reads.json.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# OF's Statements categories (its sidebar's, without the total) and the ledger
# kind each counts as, so every report's channel mapping reads them unchanged.
EARNINGS = ("subscribes", "tips", "messages", "post", "stream")
EARNINGS_KIND = {"subscribes": "subscription", "tips": "tip", "messages": "ppv_message",
                 "post": "ppv_post", "stream": "ppv_stream"}
# The key OF answers a category under when it differs from the filter's name
# (measured on two live accounts 2026-10-25: filter[messages_*] -> "chat_messages").
REPLY_KEY = {"messages": "chat_messages"}
# OF's own total of every category, stored as its own row: the day's check, and
# the mark that a day was read by a parser that reads every category
# (of_stats_daily `_earnings_days`).
TOTAL = "total"
_OF_FEE = 0.2  # OF keeps 20% of gross: gross = net / 0.8 when a reply has no gross


def points(series: Any, first: date, last: date) -> dict[str, int] | None:
    """`[{date, count}]` as {UTC day: count} for the days in [first, last], or
    None when it is not one point per consecutive day with a whole count."""
    if not isinstance(series, list):
        return None
    days: list[date] = []
    out: dict[str, int] = {}
    for p in series:
        try:
            at = datetime.fromisoformat(str(p["date"]).replace("Z", "+00:00"))
            n = p["count"]
        except (KeyError, TypeError, ValueError):
            return None
        if isinstance(n, bool) or not isinstance(n, (int, float)) or n != int(n) or n < 0:
            return None
        days.append(at.date())
        if first <= at.date() <= last:
            out[at.date().isoformat()] = int(n)
    if any((b - a).days != 1 for a, b in zip(days, days[1:])):
        return None
    return out


def amounts(series: Any) -> dict[date, float] | None:
    """`[{date, count}]` as {UTC day: amount}, or None when it is not one point
    per consecutive UTC day with a number. An amount may be negative (a day of
    chargebacks). A point must be stamped at a UTC midnight (OF's are, e.g.
    `2026-10-21T00:00:00+00:00`, measured 2026-10-25): a day cut at another
    zone's midnight would not line up with the ledger's UTC days."""
    if not isinstance(series, list):
        return None
    out: dict[date, float] = {}
    for p in series:
        try:
            at = datetime.fromisoformat(str(p["date"]).replace("Z", "+00:00"))
            n = p["count"]
        except (KeyError, TypeError, ValueError):
            return None
        if isinstance(n, bool) or not isinstance(n, (int, float)):
            return None
        if at.utcoffset() not in (None, timedelta(0)) or at.time() != datetime.min.time():
            return None
        out[at.date()] = float(n)
    days = list(out)
    if len(days) != len(series) or any((b - a).days != 1 for a, b in zip(days, days[1:])):
        return None
    return out


def earnings(reply: Any, first: date, last: date) -> dict[str, dict[str, tuple[int, int, int]]] | None:
    """OF's `/earnings/chart` reply as {day: {category: (net, gross, sales)}} in
    cents for every day in [first, last], plus `TOTAL`, or None when it is not
    that chart or does not add up. Each category is read under OF's reply key
    (`REPLY_KEY`: messages answer as `chat_messages`). A day it has no point
    for is zero. A day's gross is its net at the category's gross/net over the
    reply (OF sends gross only as the period total), or net / 0.8 when that
    total is zero. The check: OF's own `total` series must be there and each
    day's categories must sum to it (within a cent each); a reply that names
    money under a key we do not read, or no total, is not stored (the bug of
    2026-10-25: every PPV message read as $0 for want of `chat_messages`)."""
    if not isinstance(reply, dict) or not isinstance(reply.get(TOTAL), dict):
        return None
    per: dict[str, tuple[dict[date, float], dict[date, float], float]] = {}
    for c in (*EARNINGS, TOTAL):
        block = reply.get(REPLY_KEY.get(c, c))
        if block is None:
            continue
        if not isinstance(block, dict):
            return None
        amount = amounts(block.get("chartAmount"))
        count = amounts(block["chartCount"]) if "chartCount" in block else {}
        if amount is None or count is None:
            return None
        try:
            net_total, gross_total = float(block.get("total") or 0), float(block.get("gross") or 0)
        except (TypeError, ValueError):
            return None
        ratio = gross_total / net_total if net_total > 0 and gross_total > 0 else 1 / (1 - _OF_FEE)
        per[c] = (amount, count, ratio)
    out: dict[str, dict[str, tuple[int, int, int]]] = {}
    day = first
    while day <= last:
        row = out[day.isoformat()] = {}
        for c in EARNINGS:
            amount, count, ratio = per.get(c, ({}, {}, 1.0))
            net = round(amount.get(day, 0.0) * 100)
            row[c] = (net, round(net * ratio), int(count.get(day, 0)))
        total = round(per[TOTAL][0].get(day, 0.0) * 100)
        if abs(total - sum(net for net, _g, _n in row.values())) > len(EARNINGS):
            return None
        row[TOTAL] = (total, sum(g for _n, g, _s in row.values()), int(per[TOTAL][1].get(day, 0)))
        day += timedelta(days=1)
    return out
