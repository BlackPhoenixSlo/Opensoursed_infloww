#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select, text  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Fan, Message, created_at_text, parse_ts,
)

_AID_N = 0


def _fresh_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"acc_badts_{_AID_N}"


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fan_id: int) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id))


async def _add_msg(aid: str, fan_id: int, msg_id: int, direction: str, body: str,
                   created_at: datetime, automation_kind: str | None = None) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=msg_id,
                      direction=direction, body=body, created_at=created_at,
                      automation_kind=automation_kind))


async def _corrupt_ts(aid: str, fan_id: int, msg_id: int, value: str = "") -> None:
    async with get_session() as s:
        await s.execute(
            text("UPDATE messages SET created_at = :v WHERE account_id = :a "
                 "AND fan_id = :f AND message_id = :m"),
            {"v": value, "a": aid, "f": fan_id, "m": msg_id})


async def _seed_dirty_account(aid: str) -> None:
    now = datetime.utcnow()
    await _seed_account(aid)
    await _seed_fan(aid, 701)
    await _seed_fan(aid, 702)
    await _add_msg(aid, 701, 701001, "out", "older good row", now - timedelta(hours=3),
                   automation_kind="autoreply")
    await _add_msg(aid, 701, 701002, "in", "CORRUPT ROW BODY", now - timedelta(hours=2))
    await _add_msg(aid, 702, 702001, "in", "do you make foot content?",
                   now - timedelta(minutes=30))
    await _corrupt_ts(aid, 701, 701002)



def case_bad_cell_still_kills_the_naive_read():
    async def go():
        aid = _fresh_account()
        await _seed_dirty_account(aid)
        raised = None
        async with get_session() as s:
            try:
                (await s.execute(select(Message.fan_id, Message.created_at)
                                 .where(Message.account_id == aid))).all()
            except ValueError as exc:
                raised = exc
        assert raised is not None, (
            "the mapped DateTime column no longer raises on '' — re-read WHY "
            "created_at_text() exists before removing it")
        assert "isoformat" in str(raised), raised
    asyncio.run(go())


def case_created_at_text_defers_the_parse():
    async def go():
        aid = _fresh_account()
        await _seed_dirty_account(aid)
        async with get_session() as s:
            rows = (await s.execute(
                select(Message.fan_id, created_at_text())
                .where(Message.account_id == aid)
                # ORDER BY on the real column stays legal: type_coerce changes the Python type only.
                .order_by(Message.fan_id, Message.created_at))).all()
        assert len(rows) == 3, rows
        vals = [r[1] for r in rows]
        assert "" in vals, f"the corrupt cell must survive as raw text, got {vals}"
        assert all(isinstance(v, str) for v in vals), vals
    asyncio.run(go())


def case_parse_ts_shapes():
    good = datetime(2026, 7, 22, 10, 30, 0)
    assert parse_ts("2026-07-22 10:30:00.000000") == good
    assert parse_ts("2026-07-22T10:30:00") == good
    assert parse_ts(good) == good, "an already-typed datetime passes through"
    assert parse_ts(None) is None
    assert parse_ts("") is None, "the cell that caused the outage"
    assert parse_ts("   ") is None
    assert parse_ts("not a date") is None
    assert parse_ts(0) is None
    # Callers do utcnow() - ts, which raises on an aware operand.
    z = parse_ts("2026-07-22T10:30:00Z")
    assert z == good and z.tzinfo is None, z
    off = parse_ts("2026-07-22T12:30:00+02:00")
    assert off == good and off.tzinfo is None, off
    assert parse_ts(datetime(2026, 7, 22, 10, 30, tzinfo=timezone.utc)).tzinfo is not None, \
        "a real datetime is returned untouched — we only clean up parsed text"


_harness.run(
    case_bad_cell_still_kills_the_naive_read,
    case_created_at_text_defers_the_parse,
    case_parse_ts_shapes,
)
