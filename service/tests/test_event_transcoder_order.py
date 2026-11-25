#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

import event_transcode_decide as td  # noqa: E402
from attribution import _MASS_PLACEHOLDER_BASE  # noqa: E402
import event_transcoder as et  # noqa: E402
import webhook_dispatch  # noqa: E402
from db import of_writer  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Fan, Message  # noqa: E402

_AID = "9999101"
OLD_AT, NEW_AT = "2026-06-13T03:00:00+00:00", "2026-06-13T04:00:00+00:00"
OLD_T, NEW_T = datetime(2026, 6, 13, 3, 0), datetime(2026, 6, 13, 4, 0)

_words: list[dict] = []


async def _fake_on_inbound_message(account_id, fan_id, message_id, **kw):
    _words.append({"fan_id": fan_id, "message_id": message_id})


async def _noop(*a, **k):
    return None


webhook_dispatch.on_inbound_message = _fake_on_inbound_message  # type: ignore[assignment]
webhook_dispatch.on_inbound_image = _noop                       # type: ignore[assignment]
webhook_dispatch.on_inbound_tip = _noop                         # type: ignore[assignment]


def _dm(fan_id: int, message_id: int, created_at: str, text: str) -> dict:
    return {"api2_chat_message": {"id": message_id, "text": text, "price": 0, "isTip": False,
                                  "fromUser": {"id": fan_id}, "createdAt": created_at,
                                  "responseType": "message"},
            "__account_id": _AID}


def B(fan_id):
    return _dm(fan_id, 200, NEW_AT, "newer")


def A(fan_id, text="older"):
    return _dm(fan_id, 100, OLD_AT, text)


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID))


async def _drain_tasks() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _send(*frames) -> None:
    for f in frames:
        await et.transcode(f)
    await _drain_tasks()


async def _chat(fan_id) -> tuple:
    async with get_session() as s:
        c = await s.get(Chat, (_AID, fan_id))
        return (c.last_message_id, c.last_message_at, c.last_message_preview, c.unread_count)


async def _fan_last(fan_id):
    async with get_session() as s:
        return (await s.get(Fan, (_AID, fan_id))).last_message_received_at


async def _stored_ids(fan_id) -> list[int]:
    async with get_session() as s:
        return sorted((await s.execute(select(Message.message_id).where(
            Message.account_id == _AID, Message.fan_id == fan_id))).scalars().all())


async def case_late_older_dm_keeps_newer_chat_row():
    await _seed_account()
    fan = 700001
    await _send(B(fan), A(fan))
    assert await _chat(fan) == (200, NEW_T, "newer", 2), await _chat(fan)
    assert await _stored_ids(fan) == [100, 200], "the older DM's row is still stored"


async def case_redelivered_older_dm_no_rollback():
    await _seed_account()
    fan = 700002
    await _send(B(fan), A(fan), A(fan))
    assert await _chat(fan) == (200, NEW_T, "newer", 2), await _chat(fan)
    assert await _fan_last(fan) == NEW_T


async def case_one_batch_out_of_order():
    await _seed_account()
    fan = 700003
    sizes: list[int] = []

    async def _run(conn, items):
        sizes.append(len(items))
        return await et._write_dms(conn, items)

    def op(frame):
        m = frame["api2_chat_message"]
        return td.dm_plan(_AID, m, datetime.utcnow()), json.dumps(m)

    of_writer.start()
    try:
        tb = asyncio.create_task(of_writer.write(_run, op(B(fan)), key=(_AID, fan)))
        ta = asyncio.create_task(of_writer.write(_run, op(A(fan)), key=(_AID, fan)))
        assert await asyncio.gather(tb, ta) == [True, True]
    finally:
        await of_writer.stop()
    assert sizes == [2], ("both DMs in one batch", sizes)
    assert await _chat(fan) == (200, NEW_T, "newer", 2), await _chat(fan)
    assert await _fan_last(fan) == NEW_T


async def case_same_id_redelivery_refreshes_preview():
    await _seed_account()
    fan = 700004
    await _send(A(fan), A(fan, text="older, edited"))
    assert await _chat(fan) == (100, OLD_T, "older, edited", 1), await _chat(fan)


async def case_fan_last_received_never_moves_back():
    await _seed_account()
    fan = 700005
    await _send(B(fan), A(fan))
    assert await _fan_last(fan) == NEW_T, await _fan_last(fan)
    fan = 700006
    async with get_session() as s:
        s.add(Fan(account_id=_AID, fan_id=fan, last_message_received_at=None))
    await _send(A(fan))
    assert await _fan_last(fan) == OLD_T, await _fan_last(fan)


async def case_hooks_still_fire_on_redelivery():
    await _seed_account()
    fan = 700007
    _words.clear()
    await _send(A(fan), A(fan))
    assert _words == [{"fan_id": fan, "message_id": 100}] * 2, _words


async def case_mass_placeholder_yields_to_newer_dm():
    # Mass-send placeholder id sits above every real OF id, so id order cannot replace it; time decides.
    await _seed_account()
    fan = 700008
    ph, ph_at = _MASS_PLACEHOLDER_BASE + 42, datetime(2026, 6, 13, 3, 30)
    async with get_session() as s:
        s.add(Chat(account_id=_AID, fan_id=fan, last_message_id=ph, last_message_at=ph_at,
                   last_message_preview="mass", unread_count=0))
    await _send(A(fan))
    assert await _chat(fan) == (ph, ph_at, "mass", 1), await _chat(fan)
    await _send(B(fan))
    assert await _chat(fan) == (200, NEW_T, "newer", 2), await _chat(fan)


_harness.run()
