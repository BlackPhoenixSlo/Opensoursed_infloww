#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, SkipList  # noqa: E402
from automations._common import is_unreachable_fan_error, skip_unreachable_fan  # noqa: E402


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


def _ofapi(msg: str) -> Exception:
    return Exception(
        f'400 for https://onlyfans.com/api2/v2/chats/9/messages\n'
        f'{{"error":{{"code":0,"message":"{msg}"}}}}'
    )


async def _skip_ids(acct: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(SkipList.account_id == str(acct)))).all()
    return {int(r[0]) for r in rows}


def case_detects_permanent_vs_transient():
    assert is_unreachable_fan_error(_ofapi("Cannot send message to this user"))
    assert is_unreachable_fan_error(_ofapi("User not found"))
    assert not is_unreachable_fan_error(Exception("CONNECT tunnel failed, response 403"))
    assert not is_unreachable_fan_error(Exception("read timed out"))


def case_cannot_send_skiplists_fan():
    async def go():
        await _seed_account("111")
        skipped = await skip_unreachable_fan("111", 222, _ofapi("Cannot send message to this user"))
        assert skipped is True
        assert 222 in await _skip_ids("111")
    asyncio.run(go())


def case_user_not_found_skiplists_fan():
    async def go():
        await _seed_account("111")
        assert await skip_unreachable_fan("111", 333, _ofapi("User not found")) is True
        assert 333 in await _skip_ids("111")
    asyncio.run(go())


def case_transient_error_is_not_skiplisted():
    async def go():
        got = await skip_unreachable_fan("111", 444, Exception("CONNECT tunnel failed, response 403"))
        assert got is False
        assert 444 not in await _skip_ids("111")
    asyncio.run(go())


def case_idempotent_on_repeat():
    async def go():
        await _seed_account("111")
        await skip_unreachable_fan("111", 555, _ofapi("User not found"))
        await skip_unreachable_fan("111", 555, _ofapi("User not found"))
        assert 555 in await _skip_ids("111")
    asyncio.run(go())


# A fan skip-listed under another reason must upgrade to 'unreachable' and be paused, else engines keep selecting him.
def case_upgrades_existing_reason_and_pauses():
    async def go():
        await _seed_account("111")
        async with get_session() as s:
            s.add(SkipList(account_id="111", fan_id=666, reason="too_long",
                           added_at=datetime.utcnow()))
        await skip_unreachable_fan("111", 666, _ofapi("User not found"))
        async with get_session() as s:
            row = await s.get(SkipList, ("111", 666))
            assert row is not None and row.reason == "unreachable", row
            fan = await s.get(Fan, ("111", 666))
            assert fan is not None and fan.automation_paused_until is not None
            assert fan.automation_paused_until > datetime.utcnow(), fan.automation_paused_until
    asyncio.run(go())


_harness.run(
    case_detects_permanent_vs_transient,
    case_cannot_send_skiplists_fan,
    case_user_not_found_skiplists_fan,
    case_transient_error_is_not_skiplisted,
    case_idempotent_on_repeat,
    case_upgrades_existing_reason_and_pauses,
)
