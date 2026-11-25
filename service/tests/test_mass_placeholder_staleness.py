#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.unsend_messages as a12  # noqa: E402,F401 — module under test (registers)
import messages as messages_api  # noqa: E402 — seed endpoint under test
from attribution import mass_placeholder_message_id  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassBroadcastCache, MassRun, Message  # noqa: E402

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


def _use_fake() -> FakeClient:
    fake = FakeClient()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add_cast(aid: str, qid: int, *, hours_old: float) -> None:
    async with get_session() as s:
        s.add(MassBroadcastCache(
            account_id=aid, queue_id=qid,
            sent_at=datetime.utcnow() - timedelta(hours=hours_old),
            body_text="flash deal just for u", is_free=True, is_tip=False,
            media_count=0, is_canceled=False, can_unsend=True,
            fetched_at=datetime.utcnow(),
        ))


async def _add_run(aid: str, qid: int) -> int:
    async with get_session() as s:
        mr = MassRun(account_id=aid, queue_id=qid,
                     automation_kind="ppv_send", status="ok",
                     completed_at=datetime.utcnow())
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _add_placeholder(aid: str, fan_id: int, run_id: int, *,
                           hours_old: float, price_cents: int = 999) -> int:
    mid = mass_placeholder_message_id(run_id)
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=mid, direction="out",
            body="stop bein shy n open it already", media_count=0,
            price_cents=price_cents, is_unsent=False, mass_run_id=run_id,
            temp_id=f"mass:{run_id}:{fan_id}",
            created_at=datetime.utcnow() - timedelta(hours=hours_old),
        ))
    return mid


async def _msg(aid: str, fan_id: int, mid: int) -> Message | None:
    async with get_session() as s:
        return await s.get(Message, (aid, fan_id, mid))


async def case_mass_sweep_flips_placeholder_rows():
    aid = "9301"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 1001, hours_old=10)
    run_id = await _add_run(aid, 1001)
    mid = await _add_placeholder(aid, 111, run_id, hours_old=10)
    await _add_placeholder(aid, 222, run_id, hours_old=10)

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [1001], fake.cancel_calls
    assert r["unsent"] == 1, r
    for fan in (111, 222):
        row = await _msg(aid, fan, mid)
        assert row is not None and row.is_unsent is True, (
            f"placeholder for fan {fan} not flipped — the seed will keep "
            f"resurrecting this unsent broadcast in the chat pane"
        )
        assert row.unsent_reason == "automation:unsend_messages", row.unsent_reason
    print("[ok] case_mass_sweep_flips_placeholder_rows")


async def case_mass_sweep_without_run_still_unsends():
    aid = "9302"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 2001, hours_old=10)

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [2001], fake.cancel_calls
    assert r["unsent"] == 1, r
    print("[ok] case_mass_sweep_without_run_still_unsends")


async def case_seed_endpoint_filters_stale_placeholders():
    aid, fan = "9303", 777
    await _seed_account(aid)
    run_fresh = await _add_run(aid, 3001)
    run_stale = await _add_run(aid, 3002)
    mid_fresh = await _add_placeholder(aid, fan, run_fresh, hours_old=0.5)
    mid_stale = await _add_placeholder(aid, fan, run_stale, hours_old=48)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=88001,
                      direction="out", body="hey", media_count=0,
                      is_unsent=False,
                      created_at=datetime.utcnow() - timedelta(days=30)))

    resp = await messages_api.list_messages(aid, fan, limit=50, before_id=None)
    got = {m["message_id"] for m in resp["messages"]}

    assert mid_fresh in got, "fresh placeholder (live send bridge) must seed"
    assert mid_stale not in got, "stale placeholder leaked into the chat seed"
    assert 88001 in got, "real old row wrongly caught by the placeholder cutoff"
    print("[ok] case_seed_endpoint_filters_stale_placeholders")


async def case_sweep_spares_funnel_step_messages():
    aid, fan = "9304", 555
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 4001, hours_old=10)
    run_id = await _add_run(aid, 4001)
    mid_ph = await _add_placeholder(aid, fan, run_id, hours_old=10)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=77002,
                      direction="out", body="step 2 tease", media_count=0,
                      is_unsent=False, mass_run_id=run_id, funnel_step=2,
                      created_at=datetime.utcnow() - timedelta(hours=9)))

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [4001], fake.cancel_calls
    assert r["unsent"] == 1, r
    ph = await _msg(aid, fan, mid_ph)
    assert ph is not None and ph.is_unsent is True, "broadcast placeholder must flip"
    step = await _msg(aid, fan, 77002)
    assert step is not None and step.is_unsent is False, (
        "funnel step message wrongly flipped — it's still live on OF"
    )
    print("[ok] case_sweep_spares_funnel_step_messages")


async def case_seed_endpoint_keeps_ledger_tips():
    from transaction_ingest import _TIP_MSG_ID_BASE
    aid, fan = "9305", 888
    await _seed_account(aid)
    tip_mid = _TIP_MSG_ID_BASE + 42
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=tip_mid,
                      direction="in", body="tipped you $8", media_count=0,
                      is_tip=True, is_unsent=False,
                      created_at=datetime.utcnow() - timedelta(days=90)))

    resp = await messages_api.list_messages(aid, fan, limit=50, before_id=None)
    got = {m["message_id"] for m in resp["messages"]}
    assert tip_mid in got, (
        "90d-old ledger tip aged out of the seed — inline tip history is "
        "seed-only and must be permanent"
    )
    print("[ok] case_seed_endpoint_keeps_ledger_tips")


async def _main():
    await case_mass_sweep_flips_placeholder_rows()
    await case_mass_sweep_without_run_still_unsends()
    await case_seed_endpoint_filters_stale_placeholders()
    await case_sweep_spares_funnel_step_messages()
    await case_seed_endpoint_keeps_ledger_tips()
    print("all cases passed")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
