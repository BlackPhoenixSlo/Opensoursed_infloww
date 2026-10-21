"""fan_insights_api.py — Fan insights' money figures for one fan, in one read.

  GET /admin/fans/{account_id}/{fan_id}/insights

Every figure comes from our own tables (`transactions`, `messages`); no
OnlyFans call. The route sits under /admin/fans, so Role enforcement already
maps it to the pages that open Fan insights (permissions._MASS).

  spending_power    Infloww's "willingness to spend based on transaction
                    history on organization's creators over the last month"
                    (docs/infloww-screens.md › Fan insights panel). Org-wide.
  chargeback_risk   High (>66%) / Medium (33-66%) / Low (0-33%). Org-wide.
  ppv_recent        Buy rate, Highest and Lowest price over the last 30 PPVs
                    this creator sent the fan (Infloww's PPV timeline figures;
                    its chart and Copy as draft are not built). Per account.

Profile's Local time is not here: it follows Location, so it rides the fan row
(fans._row_to_dict › local_timezone).

"Org" is every account the signed-in principal can see (a chatter's is the
union across linked owners, as `assert_account_owned` reads it). OF fan ids are
global, so one fan's rows on several creators add up.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import case, func, select

from auth import assert_account_owned, require_actor_account_ids
from db.engine import get_session
from db.models import Message, Transaction
# Money that never landed or was taken back; the rest (cleared and pending
# payout holds) is spend, as fans.fan_ppv_history counts it.
from fans import _NON_REVENUE_STATUSES as _NON_REVENUE

router = APIRouter()

# Money taken back after it landed: Chargeback risk's numerator.
_REVERSED = ("chargedback", "refunded", "refund_pending")

_SPEND_WINDOW = timedelta(days=30)
# Fewer org spenders than this in the window and a percentile means nothing.
_MIN_POPULATION = 20
# (share of spenders at or above this fan, label), tightest first.
_TIERS = ((0.01, "Top 1%"), (0.05, "Top 5%"), (0.10, "Top 10%"),
          (0.25, "Top 25%"), (0.50, "Top 50%"))
_PPV_WINDOW = 30


def _org_filter(account_ids: frozenset[str] | None):
    """`transactions.account_id IN org`, or no clause for an unclamped caller."""
    return () if account_ids is None else (Transaction.account_id.in_(account_ids),)


def spending_power_label(spend_cents: int, rank: int, population: int,
                         has_history: bool) -> str:
    """No Spending History: no spend ever, org-wide. Insufficient Data: fewer
    than _MIN_POPULATION fans spent in the window. Bottom: nothing this window,
    or below the top half. Else the tightest tier holding rank / population,
    where rank is 1 + the spenders with a strictly larger 30-day total."""
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
    """pct = reversed cents / paid cents x 100, over the fan's org lifetime."""
    if pct is None:
        return None
    if pct > 66:
        return "High"
    if pct > 33:
        return "Medium"
    return "Low"


async def _spending_power(s, fan_id: int, org: tuple) -> dict[str, Any]:
    since = datetime.utcnow() - _SPEND_WINDOW
    # One statement: the org's 30-day spend per fan once, as a CTE, then this
    # fan's total (an uncorrelated scalar read of it), the spender count and
    # how many spent more.
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
    """The last _PPV_WINDOW priced messages this creator sent the fan (unsent
    ones dropped). Buy rate = unlocked / sent, as a whole percent."""
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
