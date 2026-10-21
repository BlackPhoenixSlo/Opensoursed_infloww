#!/usr/bin/env python3
"""
One corrupt `messages.created_at` cell must never silence a whole account.

The 2026-07-22 outage: a single message row for account 800000075 held the
EMPTY STRING in created_at. SQLAlchemy converts a DateTime column while
materialising the result set, so that one cell raised
`ValueError: Invalid isoformat string: ''` inside str_to_datetime — inside
.execute(), before a single row reached the consuming loop. The engine that
answered fans then scanned the whole account in ONE query, so the account
stopped replying entirely while the run log still read errors=0.

Acceptance covered here:

  case_bad_cell_still_kills_the_naive_read:
      pins the MECHANISM — selecting the mapped DateTime column over a '' cell
      still raises. If this ever stops raising the fix below is redundant, not
      broken, and the reason for it should be re-read before deleting it.
  case_created_at_text_defers_the_parse:
      created_at_text() reads the same rows as raw text without raising, and
      emits the same SQL (WHERE/ORDER BY on created_at keep working).
  case_parse_ts_shapes:
      parse_ts() unit table — good, NULL, '', junk, 'Z'-suffixed, tz-aware.

Run: ./venv/bin/python service/tests/test_bad_created_at.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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
    """Write the bad cell the way the ingest did — raw SQL, no ORM coercion."""
    async with get_session() as s:
        await s.execute(
            text("UPDATE messages SET created_at = :v WHERE account_id = :a "
                 "AND fan_id = :f AND message_id = :m"),
            {"v": value, "a": aid, "f": fan_id, "m": msg_id})


async def _seed_dirty_account(aid: str) -> None:
    """Fan 701 owns a corrupt row; fan 702's thread is clean and owed a reply."""
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


# ── Cases ─────────────────────────────────────────────────────────────

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
                # ORDER BY on the REAL column must still be legal — type_coerce
                # changes the Python-side type only, never the emitted SQL.
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
    # tz-aware input is normalised to NAIVE UTC — the callers do `utcnow() - ts`
    # arithmetic, which raises on an aware operand.
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
