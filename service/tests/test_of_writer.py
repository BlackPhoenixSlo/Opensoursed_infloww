#!/usr/bin/env python3
"""db/of_writer — group commit for the OF-cache rows.

  • ops queued together commit in ONE transaction; a caller resumes after it
  • DMs of one chat coalesce (one fans + one chats upsert) and a re-delivered
    frame does not bump unread a second time
  • per-chat order holds: DM, mark-read, DM -> unread 1
  • a bad op in a batch fails alone; the rest of the batch still commits
  • stop() flushes what is queued

Run:  ./venv/bin/python service/tests/test_of_writer.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

from sqlalchemy import func, select, text  # noqa: E402

import event_transcoder as et  # noqa: E402
import messages  # noqa: E402
import webhook_dispatch  # noqa: E402
from db import of_writer, write_telemetry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Message  # noqa: E402

A = "9999101"


async def _noop(*_a, **_k):
    return None


webhook_dispatch.on_inbound_message = _noop  # type: ignore[assignment]
webhook_dispatch.on_inbound_image = _noop    # type: ignore[assignment]
messages.assert_account_owned = lambda _aid: None  # no request scope in a unit test


def _dm(fan: int, mid: int, body: str = "hi") -> dict:
    return {"__account_id": A, "api2_chat_message": {
        "id": mid, "text": body, "fromUser": {"id": fan}, "createdAt": f"2026-10-24T10:00:{mid % 60:02d}+00:00"}}


async def _setup() -> None:
    async with get_session() as s:
        if await s.get(Account, A) is None:
            s.add(Account(id=A))
    of_writer.start()


async def _unread(fan: int) -> int | None:
    async with get_session() as s:
        return (await s.execute(select(Chat.unread_count).where(
            Chat.account_id == A, Chat.fan_id == fan))).scalar_one_or_none()


async def _n_msgs(fan: int) -> int:
    async with get_session() as s:
        return (await s.execute(select(func.count()).select_from(Message).where(
            Message.account_id == A, Message.fan_id == fan))).scalar_one()


async def case_one_transaction_and_coalesced_unread():
    await _setup()
    before = write_telemetry._cur.ow_batches
    fan = 501
    # Three frames of one chat queued at once, the third a re-delivery.
    await asyncio.gather(et.transcode(_dm(fan, 10)), et.transcode(_dm(fan, 11)),
                         et.transcode(_dm(fan, 10)))
    if write_telemetry.ENABLED:
        assert write_telemetry._cur.ow_batches - before == 1, "one batch for one burst"
        assert write_telemetry._cur.ow_ops - write_telemetry._cur.ow_entries >= 2, "coalesced"
    assert await _n_msgs(fan) == 2
    assert await _unread(fan) == 2, "a re-delivered frame must not count twice"
    await et.transcode(_dm(fan, 11))  # a later replay, alone
    assert await _unread(fan) == 2
    await of_writer.stop()


async def case_per_chat_order_dm_read_dm():
    await _setup()
    fan = 502

    async def read():
        return await messages.mark_chat_read(A, fan)

    _, r, _ = await asyncio.gather(et.transcode(_dm(fan, 20)), read(), et.transcode(_dm(fan, 21)))
    assert r["cleared"] is True, r
    assert await _unread(fan) == 1, "the DM after the read stays unread"
    await of_writer.stop()


async def case_bad_op_fails_alone():
    await _setup()

    async def bad(conn, items):
        await conn.execute(text("INSERT INTO no_such_table VALUES (1)"))
        return [None] * len(items)

    fan = 503
    results = await asyncio.gather(et.transcode(_dm(fan, 30)), of_writer.write(bad, 1),
                                   et.transcode(_dm(fan, 31)), return_exceptions=True)
    assert isinstance(results[1], Exception), results
    assert await _n_msgs(fan) == 2, "the good ops of the batch still land"
    assert await _unread(fan) == 2
    await of_writer.stop()


async def case_stop_flushes_queued():
    await _setup()
    fan = 504
    tasks = [asyncio.create_task(et.transcode(_dm(fan, 40 + i))) for i in range(5)]
    await asyncio.sleep(0)  # queued, not yet committed
    await of_writer.stop()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert await _n_msgs(fan) == 5, "stop() writes what was queued"


_harness.run(
    case_one_transaction_and_coalesced_unread,
    case_per_chat_order_dm_read_dm,
    case_bad_op_fails_alone,
    case_stop_flushes_queued,
)
