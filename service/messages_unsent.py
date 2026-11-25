from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from sqlalchemy import Select, or_, select, tuple_, update

# Must not import messages (messages imports it).
from db.engine import get_session
from db.models import MassBroadcastCache, MassRun, Message
from of_shapes import queue_id as _frame_queue_id


# An accepted unsend must be mirrored onto `messages`, or the chat pane's cold-start seed repaints it as an EMPTY locked shell.

async def mark_unsent(
    account_id: str,
    message_id: int,
    fan_id: int | None = None,
    reason: str = "manual:chat",
) -> int:
    # PK is (account_id, fan_id, message_id) and nothing indexes message_id: with fan_id this is a seek, without it a scan; the fallback keeps a bodyless unsend from leaving a stale row.
    stmt = (
        update(Message)
        .where(
            Message.account_id == str(account_id),
            Message.message_id == int(message_id),
        )
        .values(is_unsent=True, unsent_reason=reason,
                unsent_at=datetime.utcnow())
    )
    if fan_id is not None:
        stmt = stmt.where(Message.fan_id == int(fan_id))
    async with get_session() as s:
        res = await s.execute(stmt)
    return res.rowcount or 0


async def mark_mass_runs_unsent(
    account_id: str,
    mass_run_ids: Sequence[int] | Select,
    reason: str = "manual:queue",
) -> int:
    async with get_session() as s:
        res = await s.execute(
            update(Message)
            .where(
                Message.account_id == str(account_id),
                Message.mass_run_id.in_(mass_run_ids),
                # Funnel follow-ups stay live on OF when the queue is canceled; purchasers keep their paid copy (OF cancel only pulls it from non-buyers).
                Message.funnel_step.is_(None),
                Message.purchased_at.is_(None),
                Message.is_unsent.is_(False),
            )
            .values(is_unsent=True, unsent_reason=reason,
                    unsent_at=datetime.utcnow())
        )
    return res.rowcount or 0


async def mark_queue_copies_unsent(
    account_id: str,
    queue_id: int,
    *,
    body: str | None,
    sent_at: datetime | None,
    reason: str = "manual:queue",
) -> tuple[int, int]:
    # A LIST-audience blast writes no mass_run_id and the inbox poll/scrape never tag its rows, so untagged copies are recognised by queueId or body.
    # Poll-written rows carry no raw_json: match on normalized body within ±_BLAST_COPY_SLACK of sent_at.
    # One session, one commit with the MassRun.unsent_at stamp: a crash between the writes must not leave copies hidden and the run still spliceable.
    from attribution import _BLAST_COPY_SLACK
    slack = _BLAST_COPY_SLACK
    now = datetime.utcnow()
    where = [
        Message.account_id == str(account_id),
        Message.direction == "out",
        Message.mass_run_id.is_(None),
        Message.funnel_step.is_(None),
        Message.purchased_at.is_(None),
        Message.is_unsent.is_(False),
    ]
    if sent_at is not None:
        where.append(Message.created_at >= sent_at - slack)
        # The id branch reaches past the window (copy delivered late), so the upper bound is an OR.
        where.append(or_(
            Message.created_at <= sent_at + slack,
            Message.raw_json.like("%queueId%"),
        ))
    else:
        where.append(Message.created_at >= now - timedelta(days=7))
        where.append(Message.raw_json.like("%queueId%"))

    flipped = 0
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.message_id, Message.body,
                   Message.created_at, Message.raw_json).where(*where)
        )).all()
        hits = unsent_targets(int(queue_id), rows, body=body, sent_at=sent_at)
        if hits:
            res = await s.execute(
                update(Message)
                .where(
                    Message.account_id == str(account_id),
                    tuple_(Message.fan_id, Message.message_id).in_(hits),
                )
                .values(is_unsent=True, unsent_reason=reason, unsent_at=now)
            )
            flipped = res.rowcount or 0
        stamped = (await s.execute(
            update(MassRun)
            .where(
                MassRun.account_id == str(account_id),
                MassRun.queue_id == int(queue_id),
                MassRun.unsent_at.is_(None),
            )
            .values(unsent_at=now)
        )).rowcount or 0
    return flipped, stamped


async def mark_queue_unsent(
    account_id: str,
    queue_id: int,
    reason: str = "manual:queue",
) -> int:
    # The queue -> runs lookup is a subquery so the whole broadcast flips in ONE statement: a per-run loop could stop half-applied.
    run = await mark_mass_runs_unsent(
        account_id,
        select(MassRun.id).where(
            MassRun.account_id == str(account_id),
            MassRun.queue_id == int(queue_id),
        ),
        reason=reason,
    )
    body, sent_at = await _queue_body_and_stamp(account_id, int(queue_id))
    copies, _stamped = await mark_queue_copies_unsent(
        account_id, int(queue_id), body=body, sent_at=sent_at, reason=reason)
    return run + copies


def _queue_id_of(raw_json: str | None) -> int | None:
    # Structural, not substring: a substring test would pair a blast with any row that merely mentions the word.
    if not raw_json:
        return None
    try:
        obj = json.loads(raw_json)
    except (ValueError, TypeError):
        return None
    return _frame_queue_id(obj)


def unsent_targets(
    queue_id: int | None,
    rows: Iterable[tuple[int, int, str | None, datetime | None, str | None]],
    *,
    body: str | None,
    sent_at: datetime | None,
) -> list[tuple[int, int]]:
    # The body branch is only honest INSIDE the window, and only for a row with no queueId (another blast's queueId means that blast's copy).
    from attribution import _BLAST_COPY_SLACK, _norm_body
    slack = _BLAST_COPY_SLACK.total_seconds()
    key = _norm_body(body) if body else ""
    hits: list[tuple[int, int]] = []
    for fan_id, message_id, row_body, created_at, raw_json in rows:
        row_qid = _queue_id_of(raw_json)
        if queue_id is not None and row_qid is not None:
            if row_qid == int(queue_id):
                hits.append((int(fan_id), int(message_id)))
            continue
        if not key or sent_at is None or created_at is None:
            continue
        if abs((created_at - sent_at).total_seconds()) > slack:
            continue
        if _norm_body(row_body) == key:
            hits.append((int(fan_id), int(message_id)))
    return hits


async def _queue_body_and_stamp(
    account_id: str, queue_id: int,
) -> tuple[str | None, datetime | None]:
    async with get_session() as s:
        row = (await s.execute(
            select(MassRun.body, MassRun.sent_at).where(
                MassRun.account_id == str(account_id),
                MassRun.queue_id == int(queue_id),
                MassRun.sent_at.is_not(None),
            ).order_by(MassRun.id.desc())
        )).first()
        if row is not None and (row[0] or row[1]):
            return row[0], row[1]
        cached = (await s.execute(
            select(MassBroadcastCache.body_text, MassBroadcastCache.sent_at).where(
                MassBroadcastCache.account_id == str(account_id),
                MassBroadcastCache.queue_id == int(queue_id),
            )
        )).first()
    return (cached[0], cached[1]) if cached is not None else (None, None)
