from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from soak.world import now_utc

_STATE = "_soak_payout_history"
_KINDS = ("subscribes", "tips", "chat_messages")
_LEDGER = (("Tip", "tips"), ("Payment for message", "chat_messages"), ("Subscription", "subscribes"))


def history(fake) -> list[tuple[str, datetime, float, float]]:
    if _STATE not in fake.__dict__:
        at = now_utc()
        rows = []
        for n, f in enumerate(fake.world.fans, 1):
            gross = 5.0 * n
            rows.append((_KINDS[n % 3], at - timedelta(days=(n - 1) * 9, minutes=1), gross, round(gross * 0.8, 2)))
        fake.__dict__[_STATE] = rows
    return fake.__dict__[_STATE]


def _ledger(fake) -> list[tuple[str, datetime, float, float]]:
    out = []
    for r in fake.world.transactions:
        kind = next((k for word, k in _LEDGER if str(r.get("description", "")).startswith(word)), None)
        if kind:
            at = datetime.fromisoformat(str(r["createdAt"]).replace("Z", "+00:00"))
            out.append((kind, at, float(r.get("amount") or 0), float(r.get("net") or 0)))
    return out


def _bound(v: str | None, end: bool) -> datetime | None:
    if not v:
        return None
    v = v.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            d = datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return d + timedelta(days=1, seconds=-1) if end else d
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _sums(rows) -> dict[str, float]:
    return {"total_net": round(sum(r[3] for r in rows), 2), "total_gross": round(sum(r[2] for r in rows), 2)}


# `start`/`end` are ignored, as OF ignores them; only startDate/endDate bound the range
def stats(fake, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    lo, hi = _bound(start_date, False), _bound(end_date, True)
    sales = [r for r in history(fake) + _ledger(fake)
             if (lo is None or r[1] >= lo) and (hi is None or r[1] <= hi)]
    months: dict[str, Any] = {}
    for key in sorted({int(r[1].replace(day=1, hour=0, minute=0, second=0).timestamp()) for r in sales}, reverse=True):
        rows = [r for r in sales if int(r[1].replace(day=1, hour=0, minute=0, second=0).timestamp()) == key]
        m: dict[str, Any] = {}
        for kind in _KINDS:
            items = [{"time": int(r[1].timestamp()), "net": r[3], "gross": r[2]} for r in rows if r[0] == kind]
            if items:
                m[kind] = items
        months[str(key)] = {**m, **_sums(rows)}
    total = {kind: _sums([r for r in sales if r[0] == kind]) for kind in _KINDS if any(r[0] == kind for r in sales)}
    return {"list": {"months": months, "total": {**total, "all": _sums(sales)}}}


async def _stats(fake, req: Request, ok) -> Response:
    p = req.query_params
    return ok(req, stats(fake, p.get("startDate"), p.get("endDate")))


ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/payouts/stats"), _stats),
]
