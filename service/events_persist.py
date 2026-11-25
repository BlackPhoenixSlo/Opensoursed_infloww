# Bounded, not durable: DMs are lost when 2000 DMs are already queued, a stop's drain runs out of time, or on a crash; overflow drops the oldest non-DM first (a DM costs a reply).
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

import event_transcode_decide as td
import events_decide as ed
from db import of_writer, write_telemetry
from db.repo import insert_events

log = logging.getLogger("of-relay.events")

_PERSIST_QUEUE_MAX = 2000
_PERSIST_BATCH_MAX = 200
_STOP_DRAIN_S = 5.0
_persist_queue: "_Lanes | None" = None
_persist_worker_task: asyncio.Task | None = None
_persist_drops = 0
_persist_dm_drops = 0
_persist_inflight = 0


class _Lanes:

    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self.dms: deque[tuple[int, ed.PersistItem]] = deque()
        self.rest: deque[tuple[int, ed.PersistItem]] = deque()
        self.dms_first = False
        self._seq = 0
        self._ready: asyncio.Event | None = None

    def qsize(self) -> int:
        return len(self.dms) + len(self.rest)

    def empty(self) -> bool:
        return not self.dms and not self.rest

    def put(self, item: ed.PersistItem) -> str:
        outcome = "queued"
        if self.qsize() >= self.maxsize:
            if not self.rest:
                return "dropped"
            self.rest.popleft()
            outcome = "displaced"
        self._seq += 1
        (self.dms if item.inbound_dm else self.rest).append((self._seq, item))
        if self._ready is not None:
            self._ready.set()
        return outcome

    def take(self) -> ed.PersistItem | None:
        if not self.dms or (self.rest and not self.dms_first and self.rest[0][0] < self.dms[0][0]):
            return self.rest.popleft()[1] if self.rest else None
        return self.dms.popleft()[1]

    async def get(self) -> ed.PersistItem:
        while (item := self.take()) is None:
            if self._ready is None:
                self._ready = asyncio.Event()
            self._ready.clear()
            await self._ready.wait()
        return item


def enqueue(account_id: str | None, event_type: str | None, persistable: dict, event: dict,
            prior: ed.PriorInboxRow = ed.InboxRowUnpatched.VALUE) -> None:
    global _persist_drops, _persist_dm_drops
    if _persist_queue is not None:
        item = ed.PersistItem(account_id, event_type, persistable, event, td.is_inbound_dm(event), prior)
        outcome = _persist_queue.put(item)
        if outcome != "queued":
            _persist_drops += 1
            write_telemetry.drop("queue_full")
            if _persist_drops % 100 == 1:
                log.warning(
                    "persist queue at capacity — %d events displaced so far "
                    "(SQLite writer can't keep up; check disk / batch size)",
                    _persist_drops,
                )
            if outcome == "dropped":
                if item.inbound_dm:
                    _persist_dm_drops += 1
                    if _persist_dm_drops % 100 == 1:
                        log.error("persist queue full of DMs — a Fan's DM dropped unwritten "
                                  "(%d so far, account=%s)", _persist_dm_drops, account_id)
                    _scrape_dropped_dm(account_id, event)
                return
            write_telemetry.dequeued()
        write_telemetry.enqueued(_persist_queue.qsize())
    else:
        from event_transcoder import transcode as _transcode
        rows = ed.persist_plan([ed.PersistItem(account_id, event_type, persistable, event)])
        if rows:
            asyncio.create_task(_persist_batch(rows))
        asyncio.create_task(_transcode(event, prior))


def _scrape_dropped_dm(account_id: str | None, event: dict) -> None:
    fan = td._int_id(td.route(event)[2]["fromUser"]["id"])
    if not account_id or not fan:
        return
    import webhook_dispatch  # noqa: PLC0415 — lazy: it imports the executor graph
    asyncio.create_task(webhook_dispatch.enqueue_fan_scrape(
        str(account_id), fan, DM_DROPPED_SOURCE, peek_only=True))


DM_DROPPED_SOURCE = "dm_dropped"


async def _persist_batch(rows: list[dict]) -> None:
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
    batch = [first]
    while len(batch) < _PERSIST_BATCH_MAX and (item := _persist_queue.take()) is not None:
        batch.append(item)
    write_telemetry.dequeued(len(batch))
    write_telemetry.batch(len(batch))
    return batch


async def _persist_worker_loop() -> None:
    # Each transcode queues its write before its first await, so the writer gets them in queue order, inbox rows first; one consumer keeps each account's events ordered.
    global _persist_inflight
    assert _persist_queue is not None
    from event_transcoder import transcode as _transcode
    while True:
        try:
            first = await _persist_queue.get()
        except asyncio.CancelledError:
            return
        batch = _drain_batch(first)
        _persist_inflight = len(batch)
        rows = ed.persist_plan(batch)

        async def _one(event, prior) -> None:
            global _persist_inflight
            try:
                await _transcode(event, prior)
            except Exception:
                log.exception("persist worker: transcode failed")
                write_telemetry.drop("transcode_exception")
            _persist_inflight -= 1

        with write_telemetry.writer("persist"):
            await asyncio.gather(_persist_batch(rows), *(_one(it.event, it.prior) for it in batch))


def start_persist_worker() -> bool:
    # Must run inside the event loop after init_db() but before any WS pump spawns, else the first burst takes the pre-startup fallback in enqueue.
    global _persist_queue, _persist_worker_task
    if _persist_worker_task is not None and not _persist_worker_task.done():
        return False
    _persist_queue = _Lanes(_PERSIST_QUEUE_MAX)
    _persist_worker_task = asyncio.create_task(
        _persist_worker_loop(), name="event-persist-worker",
    )
    log.info("persist worker started (queue maxsize=%d)", _PERSIST_QUEUE_MAX)
    of_writer.start()
    write_telemetry.start()
    return True


async def stop_persist_worker() -> None:
    global _persist_worker_task
    if _persist_worker_task is None:
        return
    if _persist_queue is not None:
        _persist_queue.dms_first = True
    deadline = time.monotonic() + _STOP_DRAIN_S
    while ((_persist_queue is not None and _persist_queue.qsize()) or _persist_inflight) \
            and not _persist_worker_task.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    queued = _persist_queue.qsize() if _persist_queue is not None else 0
    if queued or _persist_inflight:
        log.error("persist stop: %d queued (%d Fans' DMs) and %d in flight lost unwritten",
                  queued, len(_persist_queue.dms) if _persist_queue is not None else 0, _persist_inflight)
    write_telemetry.drop("shutdown_queued", queued)
    write_telemetry.drop("shutdown_inflight", _persist_inflight)
    _persist_worker_task.cancel()
    try:
        await _persist_worker_task
    except (asyncio.CancelledError, Exception):
        pass
    _persist_worker_task = None
    await of_writer.stop()
    await write_telemetry.stop()
