"""service/full_ai_api.py — the Full AI Chatter page's read: one Creator's
Shadow Decision rows of today (`ai_decisions`, automations/full_ai_chat.py).

  GET /admin/full-ai/today?account_id=
      → {since, counts: {route: n for every Route, zeros included},
         jev_failed, rows: [{id, created_at, fan_id, fan_name, route, heat,
                             row, jev_ms, jev_failed}]}
      newest first, at most `ROWS` rows, mode shadow only. `since` is midnight
      of today in the Agency's report zone (`stats._report_zone`; UTC without
      one). A row is Jev-failed when its `jev_error` is set.

Guards: the account's owner (`assert_account_owned`); the page's role grant
is the middleware's (permissions.PAGE_MAP["/full-ai-chatter"]). The page's
switch rides the shared rule routes (`full_ai_chat` in OPT_IN_KINDS).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, get_args

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select

from auth import assert_account_owned
from automations.full_ai_chat import MODE
from automations.full_ai_decide import Route
from db.engine import get_session
from db.models import AiDecision, Fan
from isotime import iso_z

ROUTES: tuple[str, ...] = get_args(Route)
ROWS = 50

router = APIRouter()


async def _since(account_id: str) -> datetime:
    """Today's midnight in the report zone, as naive UTC (the rows' clock)."""
    import stats  # stats imports half the service; the zone reader is all this needs
    zone = await stats._report_zone(account_id) or timezone.utc
    midnight = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/admin/full-ai/today")
async def full_ai_today(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    since = await _since(account_id)
    today = (AiDecision.account_id == account_id, AiDecision.mode == MODE, AiDecision.created_at >= since)
    async with get_session() as s:
        counts, jev_failed = dict.fromkeys(ROUTES, 0), 0
        for route, n, failed in (await s.execute(
                select(AiDecision.route, func.count(), func.count(AiDecision.jev_error))
                .where(*today).group_by(AiDecision.route))).all():
            counts[route] = n
            jev_failed += failed
        rows = (await s.execute(
            select(AiDecision, Fan.of_display_name, Fan.of_username)
            .outerjoin(Fan, and_(Fan.account_id == AiDecision.account_id, Fan.fan_id == AiDecision.fan_id))
            .where(*today)
            .order_by(AiDecision.created_at.desc(), AiDecision.id.desc())
            .limit(ROWS))).all()
    return {
        "since": iso_z(since),
        "counts": counts,
        "jev_failed": jev_failed,
        "rows": [{
            "id": d.id, "created_at": iso_z(d.created_at), "fan_id": str(d.fan_id),
            "fan_name": display or username or None, "route": d.route, "heat": d.heat,
            "row": d.route_row, "jev_ms": d.jev_ms, "jev_failed": d.jev_error is not None,
        } for d, display, username in rows],
    }
