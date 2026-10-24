#!/usr/bin/env python3
"""The event_inbox writer batches commits (20-feed scale).

  • Everything already queued is written in ONE insert_events call, then each
    event is transcoded in queue order — one account's frames keep their order.
  • A batch the DB refuses is retried row by row, so one bad payload costs its
    own row, not the batch.
  • `typing` frames are transcoded (Fan touch) but never written to event_inbox.
  • A provider id dedups instead of failing the insert (the partial index's
    WHERE must be in the ON CONFLICT target, or SQLite refuses it).

Run:  ./venv/bin/python service/tests/test_persist_batch.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

import event_transcoder  # noqa: E402
import events  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import EventInbox  # noqa: E402
from db.repo import insert_events  # noqa: E402

A, B = "5101", "5102"


async def _run_worker(items, *, insert=None):
    """Queue `items` (event dicts), run the worker until it has drained them,
    and return (insert_events calls, transcoded events in order)."""
    calls: list[list[dict]] = []
    transcoded: list[dict] = []
    real_insert = events.insert_events

    async def _insert(rows):
        calls.append(list(rows))
        await (insert or real_insert)(rows)

    async def _transcode(ev):
        transcoded.append(ev)

    orig_t = event_transcoder.transcode
    events.insert_events, event_transcoder.transcode = _insert, _transcode
    events._persist_queue = asyncio.Queue()
    try:
        for ev in items:
            events._persist_queue.put_nowait(
                (ev["__account_id"], events._first_real_key(ev),
                 {k: v for k, v in ev.items() if not k.startswith("__")}, ev))
        task = asyncio.create_task(events._persist_worker_loop())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(transcoded) >= len(items):
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        events.insert_events, event_transcoder.transcode = real_insert, orig_t
        events._persist_queue = None
    return calls, transcoded


async def _inbox(account_id):
    async with get_session() as s:
        return (await s.execute(select(EventInbox.event_type)
                                .where(EventInbox.account_id == account_id)
                                .order_by(EventInbox.id))).scalars().all()


async def case_queued_events_share_one_commit_and_keep_order():
    items = [{"__account_id": A if i % 2 else B, "api2_chat_message": {"n": i}}
             for i in range(50)]
    calls, transcoded = await _run_worker(items)
    assert len(calls) == 1 and len(calls[0]) == 50, [len(c) for c in calls]
    assert transcoded == items, "transcode order must be queue order"
    assert [r["payload"]["api2_chat_message"]["n"] for r in calls[0]] == list(range(50))
    assert len(await _inbox(A)) == 25 and len(await _inbox(B)) == 25


async def case_batch_failure_falls_back_row_by_row():
    acct = "5103"

    async def _flaky(rows):
        if len(rows) > 1 or rows[0]["payload"].get("toasts") == "bad":
            raise RuntimeError("refused")
        await insert_events(rows)

    items = [{"__account_id": acct, "toasts": "ok1"},
             {"__account_id": acct, "toasts": "bad"},
             {"__account_id": acct, "toasts": "ok2"}]
    calls, transcoded = await _run_worker(items, insert=_flaky)
    assert [len(c) for c in calls] == [3, 1, 1, 1], [len(c) for c in calls]
    assert transcoded == items, "a failed write must not skip the transcode"
    assert await _inbox(acct) == ["toasts", "toasts"], "the two good rows must land"


async def case_typing_transcoded_not_persisted():
    acct = "5104"
    items = [{"__account_id": acct, "typing": {"id": 77}},
             {"__account_id": acct, "api2_chat_message": {"n": 1}}]
    calls, transcoded = await _run_worker(items)
    assert transcoded == items, "typing must still reach the transcoder"
    assert [r["event_type"] for c in calls for r in c] == ["api2_chat_message"], calls
    assert await _inbox(acct) == ["api2_chat_message"]


async def case_provider_id_dedups_instead_of_failing():
    acct = "5105"
    row = {"account_id": acct, "source": "of_ws", "event_type": "x",
           "payload": {"id": 1}, "provider_event_id": "x:1"}
    await insert_events([row, dict(row)])
    await insert_events([dict(row)])
    assert await _inbox(acct) == ["x"], "a re-delivery must be skipped, not duplicated"


_harness.run()
