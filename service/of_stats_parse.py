from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

EARNINGS = ("subscribes", "tips", "messages", "post", "stream")
EARNINGS_KIND = {"subscribes": "subscription", "tips": "tip", "messages": "ppv_message",
                 "post": "ppv_post", "stream": "ppv_stream"}
# OF answers messages under "chat_messages" despite filter[messages_*] (measured on two live accounts).
REPLY_KEY = {"messages": "chat_messages"}
TOTAL = "total"
_OF_FEE = 0.2


def points(series: Any, first: date, last: date) -> dict[str, int] | None:
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
