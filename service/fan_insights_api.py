from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import case, func, select

from auth import assert_account_owned, require_actor_account_ids
from db.engine import get_session
from db.models import Message, Transaction
# Never-landed or taken-back money is excluded; cleared and pending are spend.
from fans import _NON_REVENUE_STATUSES as _NON_REVENUE

router = APIRouter()

_REVERSED = ("chargedback", "refunded", "refund_pending")

_SPEND_WINDOW = timedelta(days=30)
# Fewer org spenders than this and a percentile means nothing.
_MIN_POPULATION = 20
_TIERS = ((0.01, "Top 1%"), (0.05, "Top 5%"), (0.10, "Top 10%"),
          (0.25, "Top 25%"), (0.50, "Top 50%"))
_PPV_WINDOW = 30


def _org_filter(account_ids: frozenset[str] | None):
    return () if account_ids is None else (Transaction.account_id.in_(account_ids),)


def spending_power_label(spend_cents: int, rank: int, population: int,
                         has_history: bool) -> str:
    if not has_history:
        return "No Spending History"
    if population < _MIN_POPULATION:
        return "Insufficient Data"
    if spend_cents <= 0:
        return "Bottom"
    share = rank / population
    for cut, label in _TIERS:
        if share <= cut:
            return label
    return "Bottom"


def chargeback_label(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct > 66:
        return "High"
    if pct > 33:
        return "Medium"
    return "Low"


async def _spending_power(s, fan_id: int, org: tuple) -> dict[str, Any]:
    since = datetime.utcnow() - _SPEND_WINDOW
    spend = (
        select(Transaction.fan_id.label("fan_id"),
               func.sum(Transaction.amount_cents).label("cents"))
        # refund_pending is still spend here: pending sales always count.
        .where(*org, Transaction.fan_id.is_not(None), Transaction.amount_cents > 0,
               Transaction.status.notin_(_NON_REVENUE), Transaction.occurred_at >= since)
        .group_by(Transaction.fan_id)
        .cte("spend")
    )
    mine_q = (select(func.coalesce(func.max(spend.c.cents), 0))
              .where(spend.c.fan_id == fan_id).correlate(None).scalar_subquery())
    mine, population, above = (await s.execute(
        select(mine_q, func.count(spend.c.fan_id),
               func.coalesce(func.sum(case((spend.c.cents > mine_q, 1), else_=0)), 0))
        .select_from(spend)
    )).one()
    mine = int(mine or 0)
    has_history = mine > 0 or (await s.execute(
        select(Transaction.id)
        .where(*org, Transaction.fan_id == fan_id, Transaction.amount_cents > 0,
               Transaction.status.notin_(_NON_REVENUE))
        .limit(1))).first() is not None
    return {
        "label": spending_power_label(mine, int(above) + 1, int(population), has_history),
        "spend_30d_cents": mine,
        "population": int(population),
    }


async def _chargeback_risk(s, fan_id: int, org: tuple) -> dict[str, Any]:
    paid, reversed_ = (await s.execute(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0),
               func.coalesce(func.sum(case(
                   (Transaction.status.in_(_REVERSED), Transaction.amount_cents), else_=0)), 0))
        .where(*org, Transaction.fan_id == fan_id, Transaction.amount_cents > 0,
               Transaction.status != "failed")
    )).one()
    pct = round(100 * int(reversed_) / int(paid), 1) if paid else None
    return {"label": chargeback_label(pct), "pct": pct,
            "paid_cents": int(paid), "reversed_cents": int(reversed_)}


async def _ppv_recent(s, account_id: str, fan_id: int) -> dict[str, Any]:
    rows = (await s.execute(
        select(Message.price_cents, Message.is_paid)
        .where(Message.account_id == account_id, Message.fan_id == fan_id,
               Message.direction == "out", Message.price_cents > 0,
               Message.is_unsent.is_(False))
        .order_by(Message.created_at.desc())
        .limit(_PPV_WINDOW)
    )).all()
    prices = [int(r.price_cents) for r in rows]
    bought = sum(1 for r in rows if r.is_paid)
    return {
        "count": len(rows),
        "bought": bought,
        "buy_rate_pct": round(100 * bought / len(rows)) if rows else None,
        "highest_cents": max(prices) if prices else None,
        "lowest_cents": min(prices) if prices else None,
    }


@router.get("/admin/fans/{account_id}/{fan_id}/insights")
async def fan_insights(account_id: str, fan_id: int) -> dict[str, Any]:
    assert_account_owned(account_id)
    org = _org_filter(require_actor_account_ids())
    async with get_session() as s:
        return {
            "spending_power": await _spending_power(s, fan_id, org),
            "chargeback_risk": await _chargeback_risk(s, fan_id, org),
            "ppv_recent": await _ppv_recent(s, account_id, fan_id),
        }
