"""
The event_inbox persist worker of service/events.py (bounded backpressure).

SQLite is single-writer, so spawning one `asyncio.create_task` per event
for the event_inbox insert AND the transcoder upserts means under a burst
the pending-task list can balloon faster than the WAL can drain. That's
the actual failure mode at high WS ingest rates — not the DB itself, but
unbounded create_task piling up.

Solution: one bounded queue, one consumer task that drains it in order,
one event_inbox commit per batch of whatever is queued.
Producers (events.handle_event → `enqueue`) push and never block; on overflow
we drop the oldest item so freshness wins over completeness. SSE fan-out stays
inline in events.py so realtime UI is unaffected — only DB writes get queued.
What one batch writes is events_decide.persist_plan (pure); this is the shell.

events.start_persist_worker wraps start_persist_worker; slop/lib/relay.py's
stats read `_persist_queue` / `_persist_drops` here.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import events_decide as ed
from db import of_writer, write_telemetry
from db.repo import insert_events

log = logging.getLogger("of-relay.events")

_PERSIST_QUEUE_MAX = 2000
# Most event_inbox rows one commit may carry. The worker drains whatever is
# already queued, up to this, so an idle relay still writes each event at once
# and a busy one (20 feeds) amortizes one commit over everything that arrived
# while the previous one was writing.
_PERSIST_BATCH_MAX = 200
# How long shutdown waits for the queue to be written before it gives up on it.
_STOP_DRAIN_S = 5.0
_persist_queue: asyncio.Queue | None = None
_persist_worker_task: asyncio.Task | None = None
_persist_drops = 0
_persist_inflight = 0   # events the worker has taken and not finished transcoding


def enqueue(account_id: str | None, event_type: str | None, persistable: dict, event: dict) -> None:
    """Hand one OF frame to the worker. Bounded queue gives backpressure;
    on overflow we drop the oldest so a slow disk loses history, not
    the freshest events. Before the worker is started (race at startup
    between the first event and `start_persist_worker`), we fall back
    to the old fire-and-forget create_task path so we don't lose data."""
    global _persist_drops
    if _persist_queue is not None:
        item = ed.PersistItem(account_id, event_type, persistable, event)
        try:
            _persist_queue.put_nowait(item)
        except asyncio.QueueFull:
            _persist_drops += 1
            write_telemetry.drop("queue_full")
            with contextlib.suppress(asyncio.QueueEmpty):
                _persist_queue.get_nowait()
                write_telemetry.dequeued()
            try:
                _persist_queue.put_nowait(item)
            except Exception:
                pass
            if _persist_drops % 100 == 1:
                log.warning(
                    "persist queue at capacity — %d events displaced so far "
                    "(SQLite writer can't keep up; check disk / batch size)",
                    _persist_drops,
                )
        write_telemetry.enqueued(_persist_queue.qsize())
    else:
        # Pre-startup path: keep the old behavior so no event is lost.
        from event_transcoder import transcode as _transcode  # local import to avoid cycles
        rows = ed.persist_plan([ed.PersistItem(account_id, event_type, persistable, event)])
        if rows:
            asyncio.create_task(_persist_batch(rows))
        asyncio.create_task(_transcode(event))


async def _persist_batch(rows: list[dict]) -> None:
    """Write `rows` to event_inbox in one transaction; if that fails, row by
    row, so one bad payload costs only its own row. Never raises."""
    if not rows:
        return
    try:
        await insert_events(rows)
        return
    except Exception:
        if len(rows) == 1:
            log.exception("persist event failed (type=%s)", rows[0]["event_type"])
            write_telemetry.drop("persist_error")
            return
        log.warning("persist batch of %d failed; retrying row by row", len(rows),
                    exc_info=True)
    for row in rows:
        try:
            await insert_events([row])
        except Exception:
            log.exception("persist event failed (type=%s)", row["event_type"])
            write_telemetry.drop("persist_error")


def _drain_batch(first: ed.PersistItem) -> list[ed.PersistItem]:
    """`first` plus whatever is already queued, up to _PERSIST_BATCH_MAX, in
    queue order. Never waits: an idle relay writes each event at once."""
    batch = [first]
    while len(batch) < _PERSIST_BATCH_MAX:
        try:
            batch.append(_persist_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    write_telemetry.dequeued(len(batch))
    write_telemetry.batch(len(batch))
    return batch


async def _persist_worker_loop() -> None:
    """Singleton consumer that drains `_persist_queue`.

    Takes everything already queued (up to _PERSIST_BATCH_MAX) and hands its
    event_inbox rows, then each event's `transcode`, to the OF-cache writer
    together (db/of_writer): the transcodes run concurrently, but each queues
    its write before its first await, so the writer gets them in queue order,
    inbox rows first, and commits them in one transaction. One consumer, FIFO,
    so each account's events keep their order. SQLite is single-writer: the
    writes go through the one writer instead of fighting over `busy_timeout`.
    """
    global _persist_inflight
    assert _persist_queue is not None
    from event_transcoder import transcode as _transcode  # local import to avoid cycles
    while True:
        try:
            first = await _persist_queue.get()
        except asyncio.CancelledError:
            return
        batch = _drain_batch(first)
        # Taken off the queue, not yet transcoded: what a shutdown cancel loses.
        _persist_inflight = len(batch)
        rows = ed.persist_plan(batch)

        async def _one(event) -> None:
            global _persist_inflight
            try:
                await _transcode(event)
            except Exception:
                log.exception("persist worker: transcode failed")
                write_telemetry.drop("transcode_exception")
            _persist_inflight -= 1

        with write_telemetry.writer("persist"):
            await asyncio.gather(_persist_batch(rows), *(_one(it.event) for it in batch))


def start_persist_worker() -> bool:
    """Start the singleton persist worker. Idempotent: False when it already runs.

    Must be called from inside the running event loop (e.g. FastAPI's
    `@app.on_event("startup")`), after `init_db()` but before any WS pump
    spawns — otherwise the first burst of events takes the pre-startup
    fallback path in `enqueue`.
    """
    global _persist_queue, _persist_worker_task
    if _persist_worker_task is not None and not _persist_worker_task.done():
        return False
    _persist_queue = asyncio.Queue(maxsize=_PERSIST_QUEUE_MAX)
    _persist_worker_task = asyncio.create_task(
        _persist_worker_loop(), name="event-persist-worker",
    )
    log.info("persist worker started (queue maxsize=%d)", _PERSIST_QUEUE_MAX)
    of_writer.start()
    write_telemetry.start()
    return True


async def stop_persist_worker() -> None:
    """Drain, then cancel the worker — call from shutdown only, after the OF
    pumps are cancelled (no live producer). Best-effort: what is queued gets
    up to _STOP_DRAIN_S to be written (the OF-cache writer then flushes what
    it holds); whatever is left after that is lost and counted."""
    global _persist_worker_task
    if _persist_worker_task is None:
        return
    deadline = time.monotonic() + _STOP_DRAIN_S
    while ((_persist_queue is not None and _persist_queue.qsize()) or _persist_inflight) \
            and not _persist_worker_task.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    # Counted before the cancel: the queued events and the worker's batch in hand
    # (its event_inbox rows may be written; their transcodes are not).
    write_telemetry.drop("shutdown_queued", _persist_queue.qsize() if _persist_queue is not None else 0)
    write_telemetry.drop("shutdown_inflight", _persist_inflight)
    _persist_worker_task.cancel()
    try:
        await _persist_worker_task
    except (asyncio.CancelledError, Exception):
        pass
    _persist_worker_task = None
    await of_writer.stop()
    await write_telemetry.stop()
