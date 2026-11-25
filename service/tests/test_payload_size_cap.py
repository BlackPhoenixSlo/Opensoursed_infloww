#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import db_retention  # noqa: E402 — provides evict_payloads_once
from db.engine import get_session  # noqa: E402
from db.models import Account, EventInbox, Fan, Message, Transaction  # noqa: E402

BIG = 50_000
N_OLD = 60
N_RECENT = 10
FLOOR_S = 2 * 24 * 60 * 60
_OLD_TS = datetime.utcnow() - timedelta(days=10)
_RECENT_TS = datetime.utcnow() - timedelta(hours=1)

RECENT_BYTES = 2 * N_RECENT * BIG
BUDGET = 2_000_000


async def _reset_and_seed() -> None:
    async with get_session() as s:
        for M in (EventInbox, Message, Fan, Transaction, Account):
            await s.execute(M.__table__.delete())

        acct = "acct_test"
        s.add(Account(id=acct))
        mid = 0
        for ts, n in ((_OLD_TS, N_OLD), (_RECENT_TS, N_RECENT)):
            for i in range(n):
                s.add(EventInbox(
                    account_id=None, source="ws", provider_event_id=None,
                    event_type="message", payload_json="e" * BIG, received_at=ts,
                ))
                mid += 1
                s.add(Message(
                    account_id=acct, fan_id=1000 + mid, message_id=mid,
                    direction="in", sender_name="", body="hi",
                    media_ids="[]", raw_json="m" * BIG, created_at=ts,
                ))

        for f in range(3):
            s.add(Fan(account_id=acct, fan_id=9000 + f))
        s.add(Transaction(
            account_id=acct, kind="tip", amount_cents=500,
            occurred_at=_OLD_TS,
        ))
        await s.commit()


async def _counts() -> dict:
    async with get_session() as s:
        async def c(stmt):
            return int((await s.execute(stmt)).scalar() or 0)
        return {
            "events": await c(select(func.count()).select_from(EventInbox)),
            "events_recent": await c(
                select(func.count()).select_from(EventInbox)
                .where(EventInbox.received_at >= _RECENT_TS)),
            "messages": await c(select(func.count()).select_from(Message)),
            "msg_raw_present": await c(
                select(func.count()).select_from(Message)
                .where(Message.raw_json.isnot(None))),
            "msg_raw_recent": await c(
                select(func.count()).select_from(Message)
                .where(Message.raw_json.isnot(None), Message.created_at >= _RECENT_TS)),
            "fans": await c(select(func.count()).select_from(Fan)),
            "txns": await c(select(func.count()).select_from(Transaction)),
            "event_bytes": await c(
                select(func.coalesce(func.sum(func.length(EventInbox.payload_json)), 0))),
            "raw_bytes": await c(
                select(func.coalesce(func.sum(func.length(Message.raw_json)), 0))),
        }


async def case_evicts_under_budget_keeps_floor_and_rows():
    await _reset_and_seed()
    before = await _counts()
    seeded_total = (N_OLD + N_RECENT)
    assert before["events"] == seeded_total, before
    assert before["messages"] == seeded_total, before
    assert before["event_bytes"] + before["raw_bytes"] > BUDGET, "seed not over budget"

    summary = await db_retention.evict_payloads_once(
        budget_bytes=BUDGET, floor_s=FLOOR_S, batch=16)

    after = await _counts()
    logical = after["event_bytes"] + after["raw_bytes"]
    assert logical <= BUDGET, f"still over budget: {logical} > {BUDGET}"
    assert summary["after_bytes"] == logical, summary
    assert summary["freed_bytes"] > 0, summary

    assert after["events_recent"] == N_RECENT, after
    assert after["msg_raw_recent"] == N_RECENT, after
    assert after["event_bytes"] >= N_RECENT * BIG, after
    assert after["raw_bytes"] >= N_RECENT * BIG, after

    assert after["messages"] == before["messages"], (after, before)
    assert after["fans"] == before["fans"] == 3, (after, before)
    assert after["txns"] == before["txns"] == 1, (after, before)
    assert after["events"] == N_RECENT, after


async def case_second_pass_is_idempotent_noop():
    before = await _counts()
    summary = await db_retention.evict_payloads_once(
        budget_bytes=BUDGET, floor_s=FLOOR_S, batch=16)
    after = await _counts()
    assert summary["freed_bytes"] == 0, summary
    assert summary["deleted_events"] == 0 and summary["nulled_messages"] == 0, summary
    assert after == before, ("idempotent pass mutated state", before, after)


async def case_zero_budget_still_honors_floor():
    await _reset_and_seed()
    before = await _counts()
    summary = await db_retention.evict_payloads_once(budget_bytes=0, floor_s=FLOOR_S, batch=16)
    after = await _counts()

    assert after["events"] == N_RECENT, after
    assert after["msg_raw_present"] == N_RECENT, after
    assert after["events_recent"] == N_RECENT, after
    assert after["msg_raw_recent"] == N_RECENT, after
    assert after["event_bytes"] + after["raw_bytes"] == RECENT_BYTES, after
    assert summary["floor_bound"] == 1, summary
    assert after["messages"] == before["messages"], (after, before)
    assert after["fans"] == 3 and after["txns"] == 1, after


async def case_prune_event_inbox_is_unconditional_age_delete():
    await _reset_and_seed()
    before = await _counts()
    assert before["events"] == N_OLD + N_RECENT, before

    summary = await db_retention.prune_event_inbox_once(max_age_s=FLOOR_S, batch=16)

    after = await _counts()
    assert summary["deleted_events"] == N_OLD, summary
    assert after["events"] == N_RECENT, after
    assert after["events_recent"] == N_RECENT, after
    assert after["messages"] == before["messages"], (after, before)
    assert after["msg_raw_present"] == before["msg_raw_present"], (after, before)
    assert after["fans"] == 3 and after["txns"] == 1, after
    again = await db_retention.prune_event_inbox_once(max_age_s=FLOOR_S, batch=16)
    assert again["deleted_events"] == 0, again


_harness.run(
    case_evicts_under_budget_keeps_floor_and_rows,
    case_second_pass_is_idempotent_noop,
    case_zero_budget_still_honors_floor,
    case_prune_event_inbox_is_unconditional_age_delete,
)
