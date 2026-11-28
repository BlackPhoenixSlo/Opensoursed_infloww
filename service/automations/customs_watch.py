from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

import platforms
# No of_client/automation_executor import: this only reads our transactions and writes fans.customs_owed_at; an OF/nickname path once erased the marker.
from automation_registry import register
from db.engine import get_session
from db.models import Fan, Message, MessageMedia, Transaction
from . import _customs
from ._common import coerce_ids


log = logging.getLogger("of-relay.automation.customs_watch")

_PURPOSE = "customs_watch"
# Short enough that enabling the feature does not mark every historical big tip.
_DEFAULT_LOOKBACK_H = 72
_DEFAULT_LIMIT = 200

_SETTLED_STATUSES = _customs.SETTLED_STATUSES


async def _delivered_since(account_id: str, fan_id: int,
                           since: datetime) -> bool:
    async with get_session() as s:
        hit = (await s.execute(
            select(MessageMedia.media_id)
            .join(Message,
                  (Message.account_id == MessageMedia.account_id)
                  & (Message.fan_id == MessageMedia.fan_id)
                  & (Message.message_id == MessageMedia.message_id))
            .where(MessageMedia.account_id == str(account_id),
                   MessageMedia.fan_id == int(fan_id),
                   Message.direction == "out",
                   Message.is_unsent.is_(False),
                   Message.created_at >= since,
                   MessageMedia.type.in_(_customs.DELIVERY_TYPES))
            .limit(1)
        )).first()
    return hit is not None


async def watch_flags(account_id: str) -> tuple[bool, dict]:
    from sqlalchemy import select as _select

    from db.models import AutomationRule
    try:
        async with get_session() as s:
            row = (await s.execute(
                _select(AutomationRule.is_enabled, AutomationRule.steps_json)
                .where(AutomationRule.account_id == str(account_id),
                       AutomationRule.kind == _PURPOSE)
                .order_by(AutomationRule.is_enabled.desc(), AutomationRule.id)
                .limit(1)
            )).first()
    except Exception:
        log.warning("customs_watch flags read failed account=%s", account_id,
                    exc_info=True)
        return False, {}
    if row is None:
        return False, {}
    import json as _json
    try:
        payload = _json.loads(row[1] or "{}") or {}
    except Exception:
        payload = {}
    return bool(row[0]), payload


def order_floor(payload: dict | None) -> int:
    return _customs.resolve_floor((payload or {}).get("min_cents"))




@register("customs_watch")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    if refused := platforms.lack_refusal(account_id, platforms.Lack.TIP_LEDGER):
        return {"status": "skipped", "reason": refused}
    payload = payload or {}
    lookback_h = int(payload.get("lookback_hours") or _DEFAULT_LOOKBACK_H)
    limit = int(payload.get("limit") or _DEFAULT_LIMIT)
    dry_run = bool(payload.get("dry_run"))
    floor = order_floor(payload)
    only = coerce_ids(payload.get("only_fan_ids"))
    since = datetime.utcnow() - timedelta(hours=lookback_h)

    if floor > _customs.ASK_MIN_CENTS:
        log.warning(
            "customs_watch_floor_above_ask account=%s min_cents=%s ask_min=%s "
            "— a quoted $%d custom would go unmarked; lower min_cents or "
            "raise the ask band",
            account_id, floor, _customs.ASK_MIN_CENTS,
            _customs.ASK_MIN_CENTS // 100)

    stats = {"tips_scanned": 0, "marked": 0, "cleared": 0, "already_marked": 0,
             "skipped_delivered": 0, "already_settled": 0,
             "errors": 0, "dry_run": dry_run, "min_cents": floor}

    async with get_session() as s:
        q = (select(Transaction.fan_id, Transaction.amount_cents,
                    Transaction.occurred_at)
             .where(Transaction.account_id == str(account_id),
                    Transaction.kind.in_(_customs.ORDER_KINDS),
                    # only money that arrived: refunded/charged-back tips must not mark a fan owed
                    Transaction.status.in_(_SETTLED_STATUSES),
                    Transaction.occurred_at >= since)
             .order_by(Transaction.occurred_at.desc())
             .limit(limit))
        tips = [r for r in (await s.execute(q)).all() if r[0] is not None]

    rows = [(str(account_id), int(fan_id), cents, at, None)
            for fan_id, cents, at in tips
            if not (only and int(fan_id) not in only)]
    stats["tips_scanned"] = len(rows)
    # Anchor = newest tip of the newest burst: a second order before delivery extends the wait.
    by_fan: dict[int, datetime] = {
        fan_id: anchor_at
        for (_acct, fan_id), (_total, anchor_at, _msg)
        in _customs.orders_per_fan(rows, floor).items()}

    for fan_id, tipped_at in by_fan.items():
        try:
            async with get_session() as s:
                fan = await s.get(Fan, {"account_id": str(account_id),
                                        "fan_id": int(fan_id)})
                owed = _customs.is_owed(fan)
                settled = fan.customs_cleared_at if fan else None
            # Without this the sweep re-marks a tip the operator just cleared.
            if settled is not None and tipped_at <= settled:
                stats["already_settled"] += 1
                continue
            if owed:
                stats["already_marked"] += 1
                continue
            if await _delivered_since(account_id, fan_id, tipped_at):
                stats["skipped_delivered"] += 1
                continue
            if dry_run:
                stats["marked"] += 1
                continue
            async with get_session() as s:
                # re-read in the write session: the operator may have cleared him since the snapshot
                fan = await s.get(Fan, {"account_id": str(account_id),
                                        "fan_id": int(fan_id)})
                if fan is None:
                    continue
                if not _customs.mark(fan, tipped_at):
                    stats["already_marked"] += 1
                    continue
                await s.commit()
            stats["marked"] += 1
            log.info("customs_watch OWED account=%s fan=%s tipped_at=%s",
                     account_id, fan_id, tipped_at)
        except Exception:
            stats["errors"] += 1
            log.warning("customs_watch mark failed account=%s fan=%s",
                        account_id, fan_id, exc_info=True)

    async with get_session() as s:
        owed_rows = (await s.execute(
            select(Fan.fan_id, Fan.customs_owed_at)
            .where(Fan.account_id == str(account_id),
                   Fan.customs_owed_at.is_not(None))
        )).all()

    for fan_id, owed_at in owed_rows:
        if only and int(fan_id) not in only:
            continue
        try:
            if not await _delivered_since(account_id, fan_id, owed_at):
                continue
            if dry_run:
                stats["cleared"] += 1
                continue
            async with get_session() as s:
                fan = await s.get(Fan, {"account_id": str(account_id),
                                        "fan_id": int(fan_id)})
                if fan is None:
                    continue
                if not _customs.clear(fan):
                    continue
                await s.commit()
            stats["cleared"] += 1
            log.info("customs_watch DELIVERED account=%s fan=%s owed_since=%s",
                     account_id, fan_id, owed_at)
        except Exception:
            stats["errors"] += 1
            log.warning("customs_watch clear failed account=%s fan=%s",
                        account_id, fan_id, exc_info=True)

    return stats
