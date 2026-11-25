#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from datetime import datetime, timedelta  # noqa: E402

import json  # noqa: E402
from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.unsend_messages as a12  # noqa: E402,F401 — module under test (registers)
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
import messages as messages_api  # noqa: E402 — the chat pane's DB seed
from db.models import (  # noqa: E402
    Account, MassBroadcastCache, MassRun, Message,
)

KIND = "unsend_messages"


class FakeClient:
    def __init__(self, user_id: str = "999"):
        self.user_id = user_id
        self.cancel_calls: list[int] = []

    def cancel_scheduled(self, queue_id):
        self.cancel_calls.append(int(queue_id))
        return {"success": True}

    def mass_message_history(self, **_kw):
        return {"items": [], "hasMore": False}


class PagingClient(FakeClient):

    def __init__(self, items: list[dict], *, page_size: int = 100):
        super().__init__()
        self.items = items
        self.page_size = page_size
        self.history_offsets: list[int] = []

    def mass_message_history(self, *, start_date, end_date, limit, offset):
        self.history_offsets.append(offset)
        size = min(limit, self.page_size)
        page = self.items[offset:offset + size]
        return {"items": page, "hasMore": offset + size < len(self.items)}


def _use_fake() -> FakeClient:
    fake = FakeClient()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _of_item(qid: int, *, hours_old: float, is_free=True, media_count=0,
             is_tip=False) -> dict:
    sent = datetime.utcnow() - timedelta(hours=hours_old)
    return {
        "id": qid, "date": sent.isoformat() + "+00:00", "text": "hey babe",
        "isFree": is_free, "isTip": is_tip, "mediaCount": media_count,
        "isCanceled": False, "canUnsend": True,
    }


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add_cast(aid: str, qid: int, *, hours_old: float, is_free=True,
                    media_count=0, is_tip=False, is_canceled=False,
                    can_unsend=True) -> None:
    async with get_session() as s:
        s.add(MassBroadcastCache(
            account_id=aid, queue_id=qid,
            sent_at=datetime.utcnow() - timedelta(hours=hours_old),
            body_text="hey babe 😘", is_free=is_free, is_tip=is_tip,
            media_count=media_count, is_canceled=is_canceled,
            can_unsend=can_unsend, fetched_at=datetime.utcnow(),
        ))


async def _is_canceled(aid: str, qid: int) -> bool:
    async with get_session() as s:
        row = await s.get(MassBroadcastCache, (aid, qid))
    return bool(row and row.is_canceled)


async def case_mass_text_sweep_unsends_only_free_textless_old():
    aid = "9101"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 1001, hours_old=10)
    await _add_cast(aid, 1002, hours_old=10, is_free=False)
    await _add_cast(aid, 1003, hours_old=10, media_count=2)
    await _add_cast(aid, 1004, hours_old=2)
    await _add_cast(aid, 1005, hours_old=10, is_canceled=True)

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [1001], fake.cancel_calls
    assert r["unsent"] == 1, r
    assert await _is_canceled(aid, 1001), "eligible cache row not flipped"
    assert not await _is_canceled(aid, 1002)
    print("[ok] case_mass_text_sweep_unsends_only_free_textless_old")


async def case_mass_text_default_8h():
    aid = "9102"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 2001, hours_old=9)
    await _add_cast(aid, 2002, hours_old=7)

    r = await run_once(aid, KIND, payload={"policy": {"mass_text": True}})

    assert fake.cancel_calls == [2001], fake.cancel_calls
    assert r["unsent"] == 1, r
    print("[ok] case_mass_text_default_8h")


async def case_mass_text_dry_run_previews():
    aid = "9103"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 3001, hours_old=10)

    r = await run_once(aid, KIND,
                       payload={"policy": {"mass_text_hours": 8}, "dry_run": True})

    assert r["dry_run"] is True, r
    assert r["targets"] == 1, r
    assert r["would_unsend"][0]["queue_id"] == 3001, r
    assert fake.cancel_calls == [], "dry_run must not call OF"
    assert not await _is_canceled(aid, 3001), "dry_run must not flip the cache"
    print("[ok] case_mass_text_dry_run_previews")


async def case_mass_only_policy_skips_per_chat():
    from db.models import Message
    aid = "9104"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 4001, hours_old=10)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=777, message_id=88001, direction="out",
                      body="hey", media_count=0, is_unsent=False,
                      created_at=datetime.utcnow() - timedelta(hours=12)))

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [4001], fake.cancel_calls
    assert r["unsent"] == 1, r
    async with get_session() as s:
        msg = await s.get(Message, (aid, 777, 88001))
    assert msg is not None and msg.is_unsent is False, "per-chat bubble wrongly unsent"
    print("[ok] case_mass_only_policy_skips_per_chat")


# A priced PPV is never auto-unsent before 24h: 47% of mass-PPV revenue lands >4h after send (measured).
async def case_priced_ppv_floor_protects_under_24h():
    aid = "9109"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 6001, hours_old=12, is_free=False)
    await _add_cast(aid, 6002, hours_old=26, is_free=False)
    r = await run_once(aid, KIND, payload={"policy": {"mass_price_hours": 4}})
    assert fake.cancel_calls == [6002], fake.cancel_calls
    assert r["unsent"] == 1, r
    print("[ok] case_priced_ppv_floor_protects_under_24h")


async def case_mass_media_and_price_classes():
    aid = "9105"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 5001, hours_old=10, media_count=3)
    await _add_cast(aid, 5002, hours_old=26, is_free=False)
    await _add_cast(aid, 5003, hours_old=10, is_free=False, media_count=2)
    await _add_cast(aid, 5004, hours_old=10)

    r = await run_once(aid, KIND, payload={
        "policy": {"mass_media_hours": 8, "mass_price_hours": 8}})

    assert sorted(fake.cancel_calls) == [5001, 5002], fake.cancel_calls
    assert r["unsent"] == 2, r
    print("[ok] case_mass_media_and_price_classes")


async def case_mass_refresh_paginates_then_sweeps():
    aid = "9106"
    await _seed_account(aid)
    fake = PagingClient(items=[
        _of_item(6001, hours_old=10, is_free=False),
        _of_item(6002, hours_old=10, media_count=2),
        _of_item(6003, hours_old=240),
    ], page_size=2)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.history_offsets == [0, 2], fake.history_offsets
    assert fake.cancel_calls == [6003], fake.cancel_calls
    assert r["unsent"] == 1, r
    async with get_session() as s:
        cached = (await s.execute(
            select(MassBroadcastCache.queue_id).where(MassBroadcastCache.account_id == aid)
        )).scalars().all()
    assert sorted(cached) == [6001, 6002, 6003], cached
    assert await _is_canceled(aid, 6003), "swept cache row not flipped"
    print("[ok] case_mass_refresh_paginates_then_sweeps")


async def case_refresh_keeps_local_cancel():
    aid = "9107"
    await _seed_account(aid)
    await _add_cast(aid, 7001, hours_old=240, is_canceled=True, can_unsend=False)
    fake = PagingClient(items=[
        _of_item(7001, hours_old=240),
        _of_item(7002, hours_old=240),
    ])
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [7002], fake.cancel_calls
    assert r["unsent"] == 1, r
    assert await _is_canceled(aid, 7001), "local cancel was resurrected by the refresh"
    assert r["mass_refresh_failed"] is False, r
    print("[ok] case_refresh_keeps_local_cancel")


# OF's queue cancel only pulls a broadcast from non-buyers; a purchaser keeps the paid copy in chat.
async def case_mass_flip_spares_purchased_rows():
    from db.models import MassRun, Message
    aid = "9108"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 8001, hours_old=26, is_free=False)
    base = datetime.utcnow() - timedelta(hours=26)
    async with get_session() as s:
        s.add(MassRun(id=81, account_id=aid, queue_id=8001, recipient_count=3))
        s.add(Message(account_id=aid, fan_id=701, message_id=5_000_000_000_000_701,
                      direction="out", body="ppv", media_count=1, price_cents=399,
                      mass_run_id=81, is_unsent=False, created_at=base))
        s.add(Message(account_id=aid, fan_id=702, message_id=5_000_000_000_000_702,
                      direction="out", body="ppv", media_count=1, price_cents=399,
                      mass_run_id=81, is_unsent=False, created_at=base,
                      purchased_at=base + timedelta(hours=1)))
        s.add(Message(account_id=aid, fan_id=703, message_id=88003,
                      direction="out", body="step2", media_count=0,
                      mass_run_id=81, funnel_step=2, is_unsent=False,
                      created_at=base))

    r = await run_once(aid, KIND, payload={"policy": {"mass_price_hours": 8}})

    assert fake.cancel_calls == [8001], fake.cancel_calls
    assert r["unsent"] == 1, r
    async with get_session() as s:
        plain = await s.get(Message, (aid, 701, 5_000_000_000_000_701))
        bought = await s.get(Message, (aid, 702, 5_000_000_000_000_702))
        follow = await s.get(Message, (aid, 703, 88003))
    assert plain is not None and plain.is_unsent is True, \
        "plain recipient mirror row must flip is_unsent"
    assert bought is not None and bought.is_unsent is False, \
        "PURCHASED row must stay live — the fan keeps their paid copy on OF"
    assert follow is not None and follow.is_unsent is False, \
        "funnel follow-up row must stay live"
    print("[ok] case_mass_flip_spares_purchased_rows")




async def _add_copy(aid: str, fan_id: int, message_id: int, *, body: str,
                    minutes_after: float, sent_at: datetime,
                    raw_json: str | None = None, mass_run_id: int | None = None,
                    purchased_at: datetime | None = None,
                    funnel_step: int | None = None,
                    automation_kind: str | None = None) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=message_id,
            direction="out", body=body, media_count=0, is_unsent=False,
            created_at=sent_at + timedelta(minutes=minutes_after),
            raw_json=raw_json, mass_run_id=mass_run_id,
            purchased_at=purchased_at, funnel_step=funnel_step,
            automation_kind=automation_kind))


async def _flipped(aid: str, fan_id: int, message_id: int) -> bool:
    async with get_session() as s:
        row = await s.get(Message, (aid, fan_id, message_id))
    return bool(row and row.is_unsent)


async def case_mass_unsend_flips_the_poll_copies():
    aid, other = "9201", "9202"
    await _seed_account(aid)
    await _seed_account(other)
    fake = _use_fake()
    qid = 46605849959
    sent_at = datetime.utcnow() - timedelta(hours=5)
    ours = "come see what i just shot\nits filthy"
    echo = "come see what i just shot<br />\nits filthy"
    async with get_session() as s:
        for _ in range(2):
            s.add(MassRun(account_id=aid, queue_id=qid, automation_kind="mass_premade",
                          audience_filter="{}", recipient_count=0, status="ok",
                          completed_at=sent_at, body=ours, sent_at=sent_at))
    await _add_cast(aid, qid, hours_old=5)

    await _add_copy(aid, 801, 80001, body=echo, minutes_after=6, sent_at=sent_at)
    await _add_copy(aid, 802, 80002, body=ours, minutes_after=0.5, sent_at=sent_at)
    await _add_copy(aid, 803, 80003, body=echo, minutes_after=40, sent_at=sent_at,
                    raw_json=json.dumps({"id": 80003, "queueId": qid,
                                         "isFromQueue": True}))
    await _add_copy(aid, 804, 80004, body=echo, minutes_after=45, sent_at=sent_at,
                    raw_json=json.dumps({"id": 80004, "queueId": str(qid)}))
    await _add_copy(aid, 805, 80005, body=ours, minutes_after=180, sent_at=sent_at)
    await _add_copy(aid, 806, 80006, body=ours, minutes_after=5, sent_at=sent_at,
                    purchased_at=sent_at + timedelta(minutes=20))
    await _add_copy(aid, 807, 80007, body=ours, minutes_after=5, sent_at=sent_at,
                    funnel_step=2)
    await _add_copy(other, 808, 80008, body=ours, minutes_after=5, sent_at=sent_at)

    res = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 4}})
    assert fake.cancel_calls == [qid], fake.cancel_calls
    stats = res
    assert stats["copies_flipped"] == 4, stats
    assert stats["rows_flipped"] == 1, stats

    for fan_id, mid in ((801, 80001), (802, 80002), (803, 80003), (804, 80004)):
        assert await _flipped(aid, fan_id, mid), (fan_id, mid, "copy left live")
    for fan_id, mid in ((805, 80005), (806, 80006), (807, 80007)):
        assert not await _flipped(aid, fan_id, mid), (fan_id, mid, "wrongly flipped")
    assert not await _flipped(other, 808, 80008), "another account's row flipped"

    async with get_session() as s:
        runs = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid,
                                  MassRun.queue_id == qid))).scalars().all()
        assert len(runs) == 2 and all(r.unsent_at is not None for r in runs), \
            [(r.id, r.unsent_at) for r in runs]

    seeded = await messages_api.list_messages(aid, 801, limit=50, before_id=None)
    assert [m["message_id"] for m in seeded["messages"]] == [], seeded["messages"]
    print("[ok] case_mass_unsend_flips_the_poll_copies")


async def case_the_re_apply_repairs_a_late_copy():
    aid = "9203"
    await _seed_account(aid)
    _use_fake()
    qid = 46605849970
    sent_at = datetime.utcnow() - timedelta(hours=5)
    async with get_session() as s:
        s.add(MassRun(account_id=aid, queue_id=qid, automation_kind="mass_premade",
                      audience_filter="{}", recipient_count=0, status="ok",
                      completed_at=sent_at, body="just say please", sent_at=sent_at,
                      unsent_at=datetime.utcnow() - timedelta(minutes=10)))
    await _add_copy(aid, 811, 81001, body="just say please",
                    minutes_after=3, sent_at=sent_at)
    await _add_cast(aid, 46605849971, hours_old=1)

    res = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 4}})
    assert res["targets"] == 0, res
    assert res["copies_flipped"] == 1, res
    assert await _flipped(aid, 811, 81001), "the late copy was never repaired"

    res2 = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 4}})
    assert res2["copies_flipped"] == 0, res2
    print("[ok] case_the_re_apply_repairs_a_late_copy")

async def _main():
    await case_mass_text_sweep_unsends_only_free_textless_old()
    await case_mass_text_default_8h()
    await case_mass_text_dry_run_previews()
    await case_mass_only_policy_skips_per_chat()
    await case_priced_ppv_floor_protects_under_24h()
    await case_mass_media_and_price_classes()
    await case_mass_refresh_paginates_then_sweeps()
    await case_refresh_keeps_local_cancel()
    await case_mass_flip_spares_purchased_rows()
    await case_mass_unsend_flips_the_poll_copies()
    await case_the_re_apply_repairs_a_late_copy()
    print("all cases passed")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
