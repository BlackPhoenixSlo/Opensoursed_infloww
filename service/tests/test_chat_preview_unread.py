#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (unset env falls back to PROD)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

import attribution  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat  # noqa: E402

AID = "acc_unread"
T_INBOUND = datetime(2026, 6, 10, 12, 0, 0)


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname="Acc Unread"))


async def _seed_chat(fan_id: int, *, unread: int, last_at, preview: str, last_id: int) -> None:
    async with get_session() as s:
        s.add(Chat(
            account_id=AID, fan_id=fan_id, unread_count=unread,
            last_message_at=last_at, last_message_preview=preview,
            last_message_id=last_id,
        ))


async def _snapshot(fan_id: int) -> dict | None:
    async with get_session() as s:
        c = await s.get(Chat, (AID, fan_id))
        if c is None:
            return None
        return {
            "unread": c.unread_count,
            "last_id": c.last_message_id,
            "last_at": c.last_message_at,
            "preview": c.last_message_preview,
        }


async def case_outbound_reply_clears_unread() -> None:
    await _seed_account()
    fan = 4242
    await _seed_chat(fan, unread=3, last_at=T_INBOUND, preview="fan said hi", last_id=1000)

    reply_at = T_INBOUND + timedelta(minutes=5)
    await attribution._advance_chat_preview(
        account_id=AID, fan_id=fan, message_id=2000,
        body="<p>hey babe!</p>", created_at=reply_at,
    )

    snap = await _snapshot(fan)
    assert snap is not None, "chat row vanished"
    assert snap["unread"] == 0, f"unread badge not cleared on outbound reply: {snap['unread']}"
    assert snap["last_id"] == 2000, snap["last_id"]
    assert snap["last_at"] == reply_at, snap["last_at"]
    assert snap["preview"] == "hey babe!", repr(snap["preview"])


async def case_newer_inbound_preserves_unread() -> None:
    await _seed_account()
    fan = 4243
    newer_inbound_at = T_INBOUND + timedelta(minutes=10)
    await _seed_chat(
        fan, unread=2, last_at=newer_inbound_at,
        preview="fan: still there?", last_id=3000,
    )

    await attribution._advance_chat_preview(
        account_id=AID, fan_id=fan, message_id=2500,
        body="<p>older reply</p>", created_at=T_INBOUND,
    )

    snap = await _snapshot(fan)
    assert snap["unread"] == 2, f"forward-only guard failed; unread={snap['unread']}"
    assert snap["last_id"] == 3000, f"newer preview was clobbered: {snap['last_id']}"
    assert snap["last_at"] == newer_inbound_at, snap["last_at"]


async def case_insert_new_chat_unread_zero() -> None:
    await _seed_account()
    fan = 4244
    assert await _snapshot(fan) is None, "precondition: chat should not exist yet"

    await attribution._advance_chat_preview(
        account_id=AID, fan_id=fan, message_id=2600,
        body="cold open", created_at=T_INBOUND,
    )

    snap = await _snapshot(fan)
    assert snap is not None, "insert path did not create the chat row"
    assert snap["unread"] == 0, snap["unread"]
    assert snap["last_id"] == 2600, snap["last_id"]


_harness.run(
    case_outbound_reply_clears_unread,
    case_newer_inbound_preserves_unread,
    case_insert_new_chat_unread_zero,
)
