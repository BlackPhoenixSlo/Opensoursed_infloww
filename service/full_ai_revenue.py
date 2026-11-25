from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, get_args

from sqlalchemy import func, select

from automations.full_ai_decide import Route, arm_of
from automations.full_ai_owned import TX_STATUSES
from db.engine import get_session
from db.models import AiDecision, Message, Transaction
from isotime import iso_z

WINDOW = timedelta(days=14)
LIVE = "live"
NO_HOLDOUT = "no holdout: not a comparison"
HOLDOUT = "not readable under about 480 Fans per Arm"
_ORDER = {r: i for i, r in enumerate(get_args(Route))}


# txs are already the counted statuses (`load` filters): pending sales count, refunds/chargebacks never.
# No holdout: one group `all` whatever the Arm; two treated groups side by side would read as a comparison.
def readout(live_at: datetime | None, cohort: Iterable[tuple[int, datetime, str]],
            txs: Iterable[tuple[int, datetime, int]],
            offers: Iterable[tuple[str, int | None, int | None, str | None]],
            now: datetime, holdout: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"live_since": iso_z(live_at), "note": HOLDOUT if holdout else NO_HOLDOUT,
                           "arms": {}, "routes": []}
    if live_at is None:
        return out
    money: dict[int, list[tuple[datetime, int]]] = {}
    for fan, at, cents in txs:
        money.setdefault(fan, []).append((at, cents))
    arms = {a: {"fans": 0, "in_window": 0, "complete": 0, "cents": 0, "cents_per_fan": None}
            for a in (("treatment", "holdout") if holdout else ("all",))}
    for fan, enrolled, arm in cohort:
        g = arms[arm if holdout else "all"]
        g["fans"] += 1
        if enrolled + WINDOW > now:
            g["in_window"] += 1
            continue
        g["complete"] += 1
        g["cents"] += sum(c for at, c in money.get(fan, ()) if enrolled <= at < enrolled + WINDOW)
    for g in arms.values():
        g["cents_per_fan"] = round(g["cents"] / g["complete"]) if g["complete"] else None
    routes: dict[str, dict[str, Any]] = {}
    for route, price, msg_id, outcome in offers:
        if not price or price <= 0 or msg_id is None:
            continue
        r = routes.setdefault(route, {"route": route, "offers": 0, "bought": 0, "cents": 0})
        r["offers"] += 1
        if outcome == "bought":
            r["bought"] += 1
            r["cents"] += price
    out["arms"] = arms
    out["routes"] = sorted(routes.values(), key=lambda r: _ORDER.get(r["route"], len(_ORDER)))
    return out


async def load(account_id: str) -> tuple[datetime | None, list, list, list]:
    async with get_session() as s:
        live_at = (await s.execute(select(func.min(AiDecision.created_at)).where(
            AiDecision.account_id == account_id, AiDecision.mode == LIVE))).scalar()
        if live_at is None:
            return None, [], [], []
        enrol = (select(Message.fan_id, func.min(Message.created_at).label("at"))
                 .where(Message.account_id == account_id, Message.direction == "in",
                        Message.created_at >= live_at)
                 .group_by(Message.fan_id).subquery())
        cohort = [(fan, at, arm_of(account_id, fan))
                  for fan, at in (await s.execute(select(enrol.c.fan_id, enrol.c.at))).all()]
        txs = (await s.execute(
            select(Transaction.fan_id, Transaction.occurred_at, Transaction.amount_cents)
            .join(enrol, enrol.c.fan_id == Transaction.fan_id)
            .where(Transaction.account_id == account_id, Transaction.status.in_(TX_STATUSES),
                   Transaction.occurred_at >= enrol.c.at))).all()
        offers = (await s.execute(
            select(AiDecision.route, AiDecision.offer_price_cents, AiDecision.offer_message_id,
                   AiDecision.outcome)
            .where(AiDecision.account_id == account_id, AiDecision.mode == LIVE,
                   AiDecision.offer_price_cents > 0, AiDecision.offer_message_id.is_not(None)))).all()
    return live_at, cohort, [tuple(t) for t in txs], [tuple(o) for o in offers]


async def revenue(account_id: str, now: datetime | None = None) -> dict[str, Any]:
    live_at, cohort, txs, offers = await load(account_id)
    return readout(live_at, cohort, txs, offers, now or datetime.utcnow(), holdout=False)
