from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import select, update

from db.engine import get_session
from db.models import Message

from . import send_marker_decide as smd

log = logging.getLogger("of-relay.automation.send_marker")

CLEARED = {"sending_at": None, "sending_ctx": None, "unconfirmed_at": None}


def _is_marked(model):
    return model.sending_at.is_not(None) | model.unconfirmed_at.is_not(None)


def _match(model, keys: dict) -> list:
    return [getattr(model, k) == v for k, v in keys.items()]


def _scoped(q, join):
    return q.join(*join) if join is not None else q


async def marked_rows(model, *where, join=None) -> list:
    async with get_session() as s:
        rows = (await s.execute(
            _scoped(select(model), join).where(_is_marked(model), *where)
            .order_by(model.sending_at, model.fan_id)
        )).scalars().all()
        for r in rows:
            s.expunge(r)
    return list(rows)


async def read(model, keys: dict, *where, join=None):
    async with get_session() as s:
        return (await s.execute(
            _scoped(select(model.sending_at, model.unconfirmed_at), join)
            .where(*_match(model, keys), *where)
        )).first()


async def mark(model, keys: dict, ctx: dict) -> datetime:
    at = datetime.utcnow()
    async with get_session() as s:
        await s.execute(update(model).where(*_match(model, keys))
                        .values(sending_at=at, sending_ctx=json.dumps(ctx)))
    return at


async def unconfirm(model, keys: dict, marked_at: datetime, **values) -> None:
    async with get_session() as s:
        await s.execute(update(model).where(*_match(model, keys), model.sending_at == marked_at)
                        .values(unconfirmed_at=datetime.utcnow(), **values))


async def clear(model, keys: dict, *, if_sending_at: datetime, **values) -> bool:
    async with get_session() as s:
        res = await s.execute(
            update(model).where(*_match(model, keys), model.sending_at == if_sending_at)
            .values(**{**CLEARED, **values}))
    return (res.rowcount or 0) > 0


async def landed(account_id: str, fan_id: int, since: datetime, kind: str, **tags) -> bool:
    async with get_session() as s:
        return (await s.execute(
            select(Message.message_id).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.direction == "out",
                Message.automation_kind == kind,
                Message.created_at >= since,
                *(getattr(Message, k) == v for k, v in tags.items()),
            ).limit(1)
        )).first() is not None


def _untagged_out(account_id: str, fan_id: int, since: datetime) -> list:
    return [Message.account_id == str(account_id), Message.fan_id == int(fan_id),
            Message.direction == "out", Message.created_at >= since,
            Message.created_at <= since + timedelta(seconds=smd.LOOKUP_SLACK_S + smd.IN_FLIGHT_MAX_S),
            Message.automation_kind.is_(None), Message.mass_run_id.is_(None),
            Message.sent_by_employee_id.is_(None)]


async def untagged_out(account_id: str, fan_id: int, since: datetime) -> tuple | None:
    async with get_session() as s:
        return (await s.execute(
            select(Message.message_id, Message.created_at, Message.body)
            .where(*_untagged_out(account_id, fan_id, since))
            .order_by(Message.created_at).limit(1)
        )).first()


async def tag_out(account_id: str, fan_id: int, since: datetime, message_id: int,
                  kind: str, **tags) -> bool:
    async with get_session() as s:
        res = await s.execute(
            update(Message).where(Message.message_id == int(message_id),
                                  *_untagged_out(account_id, fan_id, since))
            .values(automation_kind=kind, **tags))
    return (res.rowcount or 0) > 0


async def untag_out(account_id: str, message_id: int, kind: str) -> None:
    async with get_session() as s:
        await s.execute(
            update(Message).where(Message.account_id == str(account_id),
                                  Message.message_id == int(message_id),
                                  Message.direction == "out", Message.automation_kind == kind)
            .values(automation_kind=None, mass_run_id=None, funnel_step=None))


async def settle(rows: list, replay: Callable[[object], Awaitable[None]],
                 boot_ts: datetime, now: datetime) -> None:
    for r in rows:
        if smd.marker_state(r.sending_at, r.unconfirmed_at, boot_ts, now) != smd.UNCONFIRMED:
            continue
        try:
            await replay(r)
        except Exception:
            log.warning("send-once settle failed table=%s fan=%s", r.__tablename__,
                        r.fan_id, exc_info=True)
