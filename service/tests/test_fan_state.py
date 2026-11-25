#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

from automations.fan_state import fan_state, put_fan_state, set_fan_state  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, VaultSend  # noqa: E402


async def _seed(aid: str, fan_id: int = 1, blob: dict | None = None) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=fan_id,
                  custom_fields=json.dumps(blob) if blob is not None else None))
        await s.commit()


async def _blob(aid: str, fan_id: int = 1) -> dict:
    async with get_session() as s:
        raw = (await s.execute(select(Fan.custom_fields).where(
            Fan.account_id == aid, Fan.fan_id == fan_id))).scalar_one()
    return json.loads(raw) if raw else {}


async def case_read_is_pure_and_type_guarded():
    detached = Fan(account_id="x", fan_id=1, custom_fields=json.dumps({
        "_hot_teaser": {"rung": 3},
        "_junk": "a string where a dict belongs",
        "_alsojunk": [1, 2],
    }))
    assert fan_state(detached, "_hot_teaser") == {"rung": 3}
    assert fan_state(detached, "_never_set") == {}
    assert fan_state(detached, "_junk") == {}, "a str slot must not escape as a str"
    assert fan_state(detached, "_alsojunk") == {}
    assert fan_state(None, "_x") == {}
    assert fan_state(Fan(account_id="x", fan_id=2), "_x") == {}
    assert fan_state(Fan(account_id="x", fan_id=3, custom_fields="{not json"), "_x") == {}


async def case_write_preserves_siblings():
    aid = "siblings"
    await _seed(aid, blob={"_hot_teaser": {"rung": 2, "at": "yesterday"},
                           "_typo_fix": {"since": 9}})

    await set_fan_state(aid, 1, "_bot_dare", {"at": "now"})

    blob = await _blob(aid)
    assert blob["_hot_teaser"] == {"rung": 2, "at": "yesterday"}, \
        f"a sibling automation's state was clobbered: {blob}"
    assert blob["_typo_fix"] == {"since": 9}, blob
    assert blob["_bot_dare"] == {"at": "now"}, blob

    await set_fan_state(aid, 1, "_hot_teaser", None)
    blob = await _blob(aid)
    assert "_hot_teaser" not in blob, blob
    assert blob["_typo_fix"] == {"since": 9} and blob["_bot_dare"] == {"at": "now"}, blob


async def case_write_merges_against_the_stored_row():
    aid = "stale"
    await _seed(aid, blob={"_typo_fix": {"since": 1}})

    async with get_session() as s:
        stale = (await s.execute(select(Fan).where(
            Fan.account_id == aid, Fan.fan_id == 1))).scalar_one()
        assert fan_state(stale, "_hot_teaser") == {}

    # `stale` was loaded before another key was stamped; a writer serializing its own copy would drop it.
    await set_fan_state(aid, 1, "_hot_teaser", {"rung": 5})
    await set_fan_state(aid, 1, "_bot_dare", {"at": "now"})

    blob = await _blob(aid)
    assert blob.get("_hot_teaser") == {"rung": 5}, \
        f"a key written after our caller's read was lost: {blob}"
    assert blob.get("_bot_dare") == {"at": "now"}, blob
    assert blob.get("_typo_fix") == {"since": 1}, blob


async def case_in_session_write_is_atomic_with_its_caller():
    aid = "atomic"
    await _seed(aid, blob={"_typo_fix": {"since": 4}})

    async with get_session() as s:
        s.add(VaultSend(account_id=aid, fan_id=1, media_id=77, price_cents=0))
        fan = await s.get(Fan, (aid, 1))
        put_fan_state(fan, "_image_reply", {"at": "now"})
        await s.commit()

    blob = await _blob(aid)
    assert blob["_image_reply"] == {"at": "now"}, blob
    assert blob["_typo_fix"] == {"since": 4}, f"sibling lost on the in-session path: {blob}"
    async with get_session() as s:
        n = len((await s.execute(select(VaultSend.media_id).where(
            VaultSend.account_id == aid))).scalars().all())
    assert n == 1, "the send rows and the stamp must land together"

    async with get_session() as s:
        s.add(VaultSend(account_id=aid, fan_id=1, media_id=88, price_cents=0))
        fan = await s.get(Fan, (aid, 1))
        # A rollback takes both the send row and the stamp: the point of sharing the transaction.
        put_fan_state(fan, "_image_reply", {"at": "rolled-back"})
        await s.rollback()
    blob = await _blob(aid)
    assert blob["_image_reply"] == {"at": "now"}, \
        f"the stamp survived a rolled-back send: {blob}"


async def case_missing_fan_never_raises():
    aid = "nofan"
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        await s.commit()
    await set_fan_state(aid, 999, "_bot_dare", {"at": "now"})


_harness.run(
    case_read_is_pure_and_type_guarded,
    case_write_preserves_siblings,
    case_write_merges_against_the_stored_row,
    case_in_session_write_is_atomic_with_its_caller,
    case_missing_fan_never_raises,
)
