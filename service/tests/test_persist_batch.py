#!/usr/bin/env python3
"""The event_inbox writer batches commits (20-feed scale).

  • Everything already queued is written in ONE insert_events call, alongside each
    event's transcode, in queue order — one account's frames keep their order.
  • A batch the DB refuses is retried row by row, so one bad payload costs its
    own row, not the batch.
  • `typing` frames are transcoded (Fan touch) but never written to event_inbox.
  • A provider id dedups instead of failing the insert (the partial index's
    WHERE must be in the ON CONFLICT target, or SQLite refuses it).
  • A full queue displaces the oldest frame that is not a Fan's DM, or drops the
    incoming one when all are DMs (one `queue_full` either way); a stop transcodes
    the queued DMs first; `enqueue` never awaits or writes.

Run:  ./venv/bin/python service/tests/test_persist_batch.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

import event_transcoder  # noqa: E402
import events  # noqa: E402
import events_persist  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import EventInbox  # noqa: E402
from db.repo import insert_events  # noqa: E402

A, B = "5101", "5102"


async def _run_worker(items, *, insert=None):
    """Queue `items` (event dicts), run the worker until it has drained them,
    and return (insert_events calls, transcoded events in order)."""
    calls: list[list[dict]] = []
    transcoded: list[dict] = []
    real_insert = events_persist.insert_events

    async def _insert(rows):
        calls.append(list(rows))
        await (insert or real_insert)(rows)

    async def _transcode(ev):
        transcoded.append(ev)

    persisted: list[int] = []
    real_persist = events_persist._persist_batch

    async def _persist(rows):
        await real_persist(rows)
        persisted.append(len(rows))

    orig_t = event_transcoder.transcode
    events_persist.insert_events, event_transcoder.transcode = _insert, _transcode
    events_persist._persist_batch = _persist
    events_persist._persist_queue = asyncio.Queue()
    try:
        for ev in items:
            events_persist._persist_queue.put_nowait(events.ed.PersistItem(
                ev["__account_id"], events.ed.first_key(ev),
                {k: v for k, v in ev.items() if not k.startswith("__")}, ev))
        task = asyncio.create_task(events_persist._persist_worker_loop())
        for _ in range(100):
            await asyncio.sleep(0.01)
            # The transcodes run alongside the batch's inbox write (both go to
            # the OF-cache writer), so done = both finished.
            if len(transcoded) >= len(items) and persisted:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        events_persist.insert_events, event_transcoder.transcode = real_insert, orig_t
        events_persist._persist_batch = real_persist
        events_persist._persist_queue = None
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


# ── overflow and stop keep Inbound DM frames (phase-0A) ──
FAN = 354841559


def dm(n):
    """An Inbound DM frame (a Fan's text DM to account A)."""
    return {"__account_id": A, "api2_chat_message": {"id": n, "text": "hi", "fromUser": {"id": FAN}}}


def other(kind, n=0):
    """A frame that is not an Inbound DM: typing, toasts, ..."""
    return {"__account_id": A, kind: {"id": FAN, "n": n}}


class _Telemetry:
    """Stands in for events_persist.write_telemetry: counts drops by reason and dequeues."""
    def __init__(self):
        self.drops: dict[str, int] = {}
        self.dequeues = 0

    def drop(self, reason, n=1):
        self.drops[reason] = self.drops.get(reason, 0) + n

    def dequeued(self, n=1):
        self.dequeues += n

    async def stop(self):
        pass

    def __getattr__(self, name):        # enqueued / batch / writer / ...: not counted here
        import contextlib
        return lambda *a, **k: contextlib.nullcontext()


def _enqueue(ev):
    events_persist.enqueue(ev["__account_id"], events.ed.first_key(ev),
                           {k: v for k, v in ev.items() if not k.startswith("__")}, ev)


async def _overflow(queued, incoming):
    """Fill a maxsize-3 queue with `queued` through the real `enqueue`, then enqueue each of
    `incoming`; return (the queued frames in order, drops added, telemetry recorder)."""
    tel, real_tel = _Telemetry(), events_persist.write_telemetry
    events_persist._persist_queue = asyncio.Queue(maxsize=3)
    try:
        for ev in queued:
            _enqueue(ev)
        events_persist.write_telemetry = tel
        drops0 = events_persist._persist_drops
        for ev in incoming:
            _enqueue(ev)
        out = []
        while not events_persist._persist_queue.empty():
            out.append(events_persist._persist_queue.get_nowait().event)
        return out, events_persist._persist_drops - drops0, tel
    finally:
        events_persist.write_telemetry = real_tel
        events_persist._persist_queue = None


async def case_overflow_displaces_oldest_non_dm():
    toast = other("toasts")
    got, drops, tel = await _overflow([dm(1), other("typing"), dm(2)], [toast])
    assert got == [dm(1), dm(2), toast], got
    assert drops == 1 and tel.drops == {"queue_full": 1} and tel.dequeues == 1, (drops, tel.drops, tel.dequeues)


async def case_overflow_keeps_queued_dms():
    got, drops, tel = await _overflow([other("typing"), dm(1), dm(2)], [dm(3)])
    assert got == [dm(1), dm(2), dm(3)], got
    assert drops == 1 and tel.drops == {"queue_full": 1}


async def case_overflow_all_dms_drops_incoming():
    for incoming in (dm(4), other("typing")):
        got, drops, tel = await _overflow([dm(1), dm(2), dm(3)], [incoming])
        assert got == [dm(1), dm(2), dm(3)], (incoming, got)
        assert drops == 1 and tel.drops == {"queue_full": 1}, (incoming, drops, tel.drops)
        assert tel.dequeues == 0, (incoming, tel.dequeues)


async def case_stop_transcodes_dms_first():
    """A stop with the worker stuck on its first frame and a backlog of typing, DM, toast, DM
    transcodes the DMs first, each group in queue order, and loses nothing."""
    first, backlog = other("online"), [other("typing"), dm(1), other("toasts"), dm(2)]
    transcoded: list[dict] = []
    release = asyncio.Event()

    async def _transcode(ev):
        transcoded.append(ev)
        if ev is first:
            await release.wait()

    tel, real_tel = _Telemetry(), events_persist.write_telemetry
    orig_t = event_transcoder.transcode
    event_transcoder.transcode, events_persist.write_telemetry = _transcode, tel
    events_persist._persist_queue = asyncio.Queue()
    try:
        _enqueue(first)
        events_persist._persist_worker_task = asyncio.create_task(events_persist._persist_worker_loop())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if transcoded:
                break
        assert transcoded == [first], "the worker must hold the first frame"
        for ev in backlog:
            _enqueue(ev)
        stop = asyncio.create_task(events_persist.stop_persist_worker())
        await asyncio.sleep(0.01)
        release.set()
        await asyncio.wait_for(stop, 10)
        assert transcoded[1:] == [dm(1), dm(2), other("typing"), other("toasts")], transcoded
        assert tel.drops.get("shutdown_queued", 0) == 0 and tel.drops.get("shutdown_inflight", 0) == 0, tel.drops
    finally:
        event_transcoder.transcode, events_persist.write_telemetry = orig_t, real_tel
        events_persist._persist_queue = None
        if events_persist._persist_worker_task is not None:
            events_persist._persist_worker_task.cancel()
            events_persist._persist_worker_task = None


async def case_enqueue_never_awaits():
    """The WS pump never waits on enqueue: a plain function that queues no DB write, even on overflow."""
    import inspect

    from db import of_writer
    assert not inspect.iscoroutinefunction(events_persist.enqueue)
    queued0 = of_writer._queued
    got, drops, _ = await _overflow([dm(1), other("typing"), dm(2)], [dm(3), other("toasts")])
    assert got == [dm(1), dm(2), dm(3)] and drops == 2, (got, drops)
    assert of_writer._queued == queued0 and not of_writer._pending, "enqueue must not queue a write"


async def case_provider_id_dedups_instead_of_failing():
    acct = "5105"
    row = {"account_id": acct, "source": "of_ws", "event_type": "x",
           "payload": {"id": 1}, "provider_event_id": "x:1"}
    await insert_events([row, dict(row)])
    await insert_events([dict(row)])
    assert await _inbox(acct) == ["x"], "a re-delivery must be skipped, not duplicated"


_harness.run()
