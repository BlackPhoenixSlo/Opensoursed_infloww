#!/usr/bin/env python3
"""raw_json sweep NULLs only old payloads, in batches, and leaves rows and recent payloads intact.

Run: ./venv/bin/python service/tests/test_raw_json_retention.py   (exit 0 = green)
"""
import _harness

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402
from unittest.mock import patch  # noqa: E402

from sqlalchemy import event, func, select  # noqa: E402

import db_retention  # noqa: E402
from db.engine import engine, get_session  # noqa: E402
from db.models import Account, Message  # noqa: E402

ACCT = "acct_raw"


async def _seed(n_old: int, n_recent: int) -> None:
    old = datetime.utcnow() - timedelta(days=90)
    recent = datetime.utcnow() - timedelta(hours=1)
    async with get_session() as s:
        await s.execute(Message.__table__.delete())
        await s.execute(Account.__table__.delete().where(Account.id == ACCT))
        s.add(Account(id=ACCT))
        mid = 1
        for ts, n in ((old, n_old), (recent, n_recent)):
            for _ in range(n):
                s.add(Message(account_id=ACCT, fan_id=1, message_id=mid, direction="in",
                              created_at=ts, raw_json='{"x":1}'))
                mid += 1
        s.add(Message(account_id=ACCT, fan_id=1, message_id=mid, direction="in", created_at=old, raw_json=None))
        await s.commit()


async def _count(*where) -> int:
    async with get_session() as s:
        stmt = select(func.count()).select_from(Message)
        for w in where:
            stmt = stmt.where(w)
        return int((await s.execute(stmt)).scalar() or 0)


async def case_raw_json_sweep_drains_backlog_in_bounded_runs() -> None:
    db_retention._RAW_JSON_RETAIN_S = 60 * 24 * 60 * 60
    db_retention._RAW_JSON_BATCH = 3
    await _seed(n_old=7, n_recent=4)
    with patch.object(db_retention, "monotonic", side_effect=[0, 0, 0, 120]):
        await db_retention._raw_json_sweep()
    assert await _count(Message.raw_json.isnot(None)) == 5
    await db_retention._raw_json_sweep()
    assert await _count() == 12
    assert await _count(Message.raw_json.isnot(None)) == 4
    old_cut = datetime.utcnow() - timedelta(days=60)
    assert await _count(Message.created_at < old_cut, Message.raw_json.isnot(None)) == 0
    await db_retention._raw_json_sweep()
    assert await _count(Message.raw_json.isnot(None)) == 4


async def case_raw_json_sweep_rechecks_age_before_update() -> None:
    await _seed(n_old=1, n_recent=0)
    refreshed = False

    def refresh_before_write(_conn, cursor, statement, _params, _ctx, _many):
        nonlocal refreshed
        if statement.startswith("UPDATE messages SET raw_json = NULL"):
            cursor.execute("UPDATE messages SET created_at = CURRENT_TIMESTAMP WHERE message_id = 1")
            refreshed = True

    event.listen(engine.sync_engine, "before_cursor_execute", refresh_before_write)
    try:
        await db_retention._raw_json_sweep()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", refresh_before_write)
    assert refreshed
    assert await _count(Message.raw_json.isnot(None)) == 1


_harness.run()
