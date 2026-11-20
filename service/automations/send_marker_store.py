"""service/automations/send_marker_store.py — the send-once marker's reads and
writes (its rules: send_marker_decide), over either marked table (funnel_state,
followup_state: the same three columns). Each sender keeps only its own replay
and the unconfirmed-sends API's entries; this holds the shared SQL.

  marked_rows(model, *where, join=)    the marked rows (detached), oldest mark first
  read(model, keys, *where, join=)     (sending_at, unconfirmed_at) of one row, None = no row
  mark(model, keys, ctx)               sending_at = the wall clock NOW + ctx; -> the mark time
  unconfirm(model, keys, marked_at, **v)  may have sent: only while that mark still stands
  clear(model, keys, if_sending_at=, **v) the marker off (+ v), only while that mark stands
  landed(account_id, fan_id, since, kind, **tags)  an outbound `messages` row of the step?
  untagged_out(account_id, fan_id, since)  the first untagged outbound row since (a hint)
  tag_out(account_id, fan_id, since, message_id, kind, **tags)  the user-confirmed hint row tagged
  untag_out(account_id, message_id, kind)  tag_out undone
  settle(rows, replay, boot_ts, now)   replay(row) for each UNCONFIRMED row, try/log/skip

`keys` = {column: value} naming one row. Every conditional write matches the mark
it read (`sending_at = <read>`), so a Retry, a settle and a live attempt never
overwrite each other's outcome. Invariant: `unconfirmed_at` set => `sending_at` set.
"""
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
    """The marker, committed right before an attempt's first OF call: the wall
    clock at the write (not a tick's `now`: a serial tick can be minutes old)."""
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
    """True iff the row still carried that mark (and is now unmarked)."""
    async with get_session() as s:
        res = await s.execute(
            update(model).where(*_match(model, keys), model.sending_at == if_sending_at)
            .values(**{**CLEARED, **values}))
    return (res.rowcount or 0) > 0


async def landed(account_id: str, fan_id: int, since: datetime, kind: str, **tags) -> bool:
    """A sent bubble writes its outbound `messages` row (automation_kind + `tags`):
    one at/after `since` (the mark less the OF-clock slack) is the proof."""
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
    """An outbound row that can be the id-less send's live-feed copy: untagged, not
    stamped with an employee (a chatter's CRM send is a human's, never the step's)
    and inside the attempt's window (`since` + the in-flight lease)."""
    return [Message.account_id == str(account_id), Message.fan_id == int(fan_id),
            Message.direction == "out", Message.created_at >= since,
            Message.created_at <= since + timedelta(seconds=smd.LOOKUP_SLACK_S + smd.IN_FLIGHT_MAX_S),
            Message.automation_kind.is_(None), Message.mass_run_id.is_(None),
            Message.sent_by_employee_id.is_(None)]


async def untagged_out(account_id: str, fan_id: int, since: datetime) -> tuple | None:
    """(message_id, created_at, body) of the first outbound `messages` row at/after
    `since` with no automation tag (the live feed's copy of a send that never got its
    id): only a hint for the user's "It went through", never proof (a human's message
    looks the same)."""
    async with get_session() as s:
        return (await s.execute(
            select(Message.message_id, Message.created_at, Message.body)
            .where(*_untagged_out(account_id, fan_id, since))
            .order_by(Message.created_at).limit(1)
        )).first()


async def tag_out(account_id: str, fan_id: int, since: datetime, message_id: int,
                  kind: str, **tags) -> bool:
    """The hint row the user confirmed as the send gets the step's tags (what the
    sender writes on a confirmed send), so the funnel's "replied since our last
    message" baseline moves past it; only while it is still an untagged outbound
    row of that fan since `since`. True iff tagged."""
    async with get_session() as s:
        res = await s.execute(
            update(Message).where(Message.message_id == int(message_id),
                                  *_untagged_out(account_id, fan_id, since))
            .values(automation_kind=kind, **tags))
    return (res.rowcount or 0) > 0


async def untag_out(account_id: str, message_id: int, kind: str) -> None:
    """`tag_out` undone (the step it was tagged for could not be saved as sent)."""
    async with get_session() as s:
        await s.execute(
            update(Message).where(Message.account_id == str(account_id),
                                  Message.message_id == int(message_id),
                                  Message.direction == "out", Message.automation_kind == kind)
            .values(automation_kind=None, mass_run_id=None, funnel_step=None))


async def settle(rows: list, replay: Callable[[object], Awaitable[None]],
                 boot_ts: datetime, now: datetime) -> None:
    """UNCONFIRMED rows only (an IN_FLIGHT one may still be writing); one bad row
    never stops the caller."""
    for r in rows:
        if smd.marker_state(r.sending_at, r.unconfirmed_at, boot_ts, now) != smd.UNCONFIRMED:
            continue
        try:
            await replay(r)
        except Exception:
            log.warning("send-once settle failed table=%s fan=%s", r.__tablename__,
                        r.fan_id, exc_info=True)
