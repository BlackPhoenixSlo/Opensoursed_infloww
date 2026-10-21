#!/usr/bin/env python3
"""SIZE cap on the raw-OF-payload bloat (server.evict_payloads_once).

Two columns hoard raw OnlyFans payloads we receive but read back only briefly:
event_inbox.payload_json (the WS/SSE firehose — every event is already
transcoded, so old envelopes are dead weight) and messages.raw_json (a
duplicate of the message that lives in its own columns). Left unbounded they
push the SQLite file past 2 GB. The cap evicts oldest-first down to a LOGICAL
byte budget — but must NEVER drop fan data and NEVER touch anything inside the
retention floor.

This test seeds oversized OLD payloads (older than the floor) + RECENT ones
(inside the floor), runs one eviction pass, and asserts:
  • logical payload bytes drop under budget,
  • RECENT payloads are untouched (floor honored),
  • messages / fans / transactions ROW counts are unchanged (zero fan-data loss
    — only the two raw envelope columns are ever deleted/NULLed),
  • a second pass is a no-op (idempotent),
  • an impossible budget of 0 STILL refuses to breach the floor.

Run: ./venv/bin/python service/tests/test_payload_size_cap.py   (exit 0 = green)
"""
import _harness  # MUST be first — sets sys.path / binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import server  # noqa: E402 — provides evict_payloads_once
from db.engine import get_session  # noqa: E402
from db.models import Account, EventInbox, Fan, Message, Transaction  # noqa: E402

# ── seed sizing ──────────────────────────────────────────────────────
BIG = 50_000                       # bytes per payload (ASCII → LENGTH == bytes)
N_OLD = 60                         # old rows per store (older than the floor)
N_RECENT = 10                     # recent rows per store (inside the floor)
FLOOR_S = 2 * 24 * 60 * 60         # 2-day retention floor
_OLD_TS = datetime.utcnow() - timedelta(days=10)    # well outside the floor
_RECENT_TS = datetime.utcnow() - timedelta(hours=1)  # well inside the floor

RECENT_BYTES = 2 * N_RECENT * BIG  # event + raw_json recent payload, kept always
BUDGET = 2_000_000                 # 2 MB — below total seed (~7 MB), above recent


async def _reset_and_seed() -> None:
    """Wipe the payload tables + reseed a known OLD/RECENT mix, plus a few
    fan/transaction rows that the evictor must never touch."""
    async with get_session() as s:
        # Children before the accounts parent (FK order).
        for M in (EventInbox, Message, Fan, Transaction, Account):
            await s.execute(M.__table__.delete())

        acct = "acct_test"
        s.add(Account(id=acct))  # parent row for the fans/transactions FK
        mid = 0
        for ts, n in ((_OLD_TS, N_OLD), (_RECENT_TS, N_RECENT)):
            for i in range(n):
                # event_inbox: account_id=None avoids the accounts FK.
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

        # Fan + transaction rows the cap must leave fully intact.
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

    summary = await server.evict_payloads_once(
        budget_bytes=BUDGET, floor_s=FLOOR_S, batch=16)

    after = await _counts()
    # 1) logical payload size is under budget now.
    logical = after["event_bytes"] + after["raw_bytes"]
    assert logical <= BUDGET, f"still over budget: {logical} > {BUDGET}"
    assert summary["after_bytes"] == logical, summary
    assert summary["freed_bytes"] > 0, summary

    # 2) the retention floor was honored — every RECENT payload is intact.
    assert after["events_recent"] == N_RECENT, after
    assert after["msg_raw_recent"] == N_RECENT, after
    assert after["event_bytes"] >= N_RECENT * BIG, after
    assert after["raw_bytes"] >= N_RECENT * BIG, after

    # 3) ZERO fan-data loss: only the raw envelope columns were touched.
    #    Message rows all survive (raw_json NULLed, never the row); fans and
    #    transactions are never referenced by the evictor at all.
    assert after["messages"] == before["messages"], (after, before)
    assert after["fans"] == before["fans"] == 3, (after, before)
    assert after["txns"] == before["txns"] == 1, (after, before)
    # old event rows were deleted; recent kept.
    assert after["events"] == N_RECENT, after


async def case_second_pass_is_idempotent_noop():
    # Continues from the prior case's already-under-budget state.
    before = await _counts()
    summary = await server.evict_payloads_once(
        budget_bytes=BUDGET, floor_s=FLOOR_S, batch=16)
    after = await _counts()
    assert summary["freed_bytes"] == 0, summary
    assert summary["deleted_events"] == 0 and summary["nulled_messages"] == 0, summary
    assert after == before, ("idempotent pass mutated state", before, after)


async def case_zero_budget_still_honors_floor():
    await _reset_and_seed()
    before = await _counts()
    # An impossible budget: evict EVERYTHING you're allowed to — but the floor
    # is a hard wall, so the recent window must survive regardless.
    summary = await server.evict_payloads_once(budget_bytes=0, floor_s=FLOOR_S, batch=16)
    after = await _counts()

    # all OLD payloads gone, all RECENT payloads kept.
    assert after["events"] == N_RECENT, after
    assert after["msg_raw_present"] == N_RECENT, after
    assert after["events_recent"] == N_RECENT, after
    assert after["msg_raw_recent"] == N_RECENT, after
    # exactly the recent payload bytes remain → floor-bound, not zero.
    assert after["event_bytes"] + after["raw_bytes"] == RECENT_BYTES, after
    assert summary["floor_bound"] == 1, summary
    # fan data still fully intact.
    assert after["messages"] == before["messages"], (after, before)
    assert after["fans"] == 3 and after["txns"] == 1, after


async def case_prune_event_inbox_is_unconditional_age_delete():
    # The forward-fix: prune_event_inbox_once deletes OLD envelopes by AGE,
    # with NO byte budget involved — and only ever touches event_inbox. This is
    # what keeps the landing table at a fixed window when the budget cap never
    # fires (the real prod failure: 360k rows under the 1.5 GB logical budget).
    await _reset_and_seed()
    before = await _counts()
    assert before["events"] == N_OLD + N_RECENT, before

    summary = await server.prune_event_inbox_once(max_age_s=FLOOR_S, batch=16)

    after = await _counts()
    # every OLD envelope gone, every RECENT one kept — no budget consulted.
    assert summary["deleted_events"] == N_OLD, summary
    assert after["events"] == N_RECENT, after
    assert after["events_recent"] == N_RECENT, after
    # messages.raw_json + every fan/txn row are NEVER touched by the inbox prune.
    assert after["messages"] == before["messages"], (after, before)
    assert after["msg_raw_present"] == before["msg_raw_present"], (after, before)
    assert after["fans"] == 3 and after["txns"] == 1, after
    # second pass is a no-op (idempotent).
    again = await server.prune_event_inbox_once(max_age_s=FLOOR_S, batch=16)
    assert again["deleted_events"] == 0, again


_harness.run(
    case_evicts_under_budget_keeps_floor_and_rows,
    case_second_pass_is_idempotent_noop,
    case_zero_budget_still_honors_floor,
    case_prune_event_inbox_is_unconditional_age_delete,
)
