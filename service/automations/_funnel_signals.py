from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from db.engine import get_session
from db.models import Message

from ._funnel_routing import strip_html


async def last_funnel_out_at(account_id: str, fan_id: int, mass_run_id: int) -> datetime | None:
    async with get_session() as s:
        ts = (await s.execute(
            select(func.max(Message.created_at)).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.mass_run_id == int(mass_run_id),
                Message.direction == "out",
            )
        )).scalar_one_or_none()
    return ts


async def replied_recipient_fans(account_id: str, mass_run_id: int) -> set[int]:
    async with get_session() as s:
        last_out = (
            select(
                Message.fan_id.label("fan_id"),
                func.max(Message.created_at).label("out_at"),
            )
            .where(
                Message.account_id == str(account_id),
                Message.mass_run_id == int(mass_run_id),
                Message.direction == "out",
            )
            .group_by(Message.fan_id)
            .subquery()
        )
        inbound_after = (
            select(Message.message_id)
            .where(
                Message.account_id == str(account_id),
                Message.fan_id == last_out.c.fan_id,
                Message.direction == "in",
                Message.is_unsent.is_(False),
                Message.created_at > last_out.c.out_at,
            )
            .exists()
        )
        rows = (await s.execute(
            select(last_out.c.fan_id).where(inbound_after)
        )).all()
    return {int(r[0]) for r in rows}


async def latest_reply(
    account_id: str, fan_id: int, since: datetime | None,
) -> tuple[bool, str]:
    async with get_session() as s:
        q = select(Message.body).where(
            Message.account_id == str(account_id),
            Message.fan_id == int(fan_id),
            Message.direction == "in",
            Message.is_unsent.is_(False),
        )
        if since is not None:
            q = q.where(Message.created_at > since)
        q = q.order_by(Message.created_at.desc(), Message.message_id.desc()).limit(1)
        row = (await s.execute(q)).first()
    if row is None:
        return False, ""
    return True, (strip_html(row[0]) if row[0] else "")


async def has_fan_paid_ppv(account_id: str, fan_id: int, since: datetime | None) -> bool:
    async with get_session() as s:
        q = select(Message.message_id).where(
            Message.account_id == str(account_id),
            Message.fan_id == int(fan_id),
            Message.direction == "out",
            Message.is_paid.is_(True),
        )
        if since is not None:
            q = q.where(func.coalesce(Message.purchased_at, Message.created_at) > since)
        hit = (await s.execute(q.limit(1))).first()
    return hit is not None


async def last_inbound_at(
    account_id: str, fan_id: int, *, since: datetime | None = None,
) -> datetime | None:
    async with get_session() as s:
        q = select(func.max(Message.created_at)).where(
            Message.account_id == str(account_id),
            Message.fan_id == int(fan_id),
            Message.direction == "in",
            Message.is_unsent.is_(False),
        )
        if since is not None:
            q = q.where(Message.created_at > since)
        return (await s.execute(q)).scalar_one_or_none()
