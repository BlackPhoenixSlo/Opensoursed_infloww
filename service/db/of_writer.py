from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, Hashable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import write_telemetry
from db.engine import UNCAPPED, engine

log = logging.getLogger("of-relay.of_writer")

# Best-effort cache of OnlyFans: a later OF read corrects any loss, so no durable outbox.
BATCH_MAX = 200
STOP_DRAIN_S = 5.0

Run = Callable[[Any, list], Awaitable[list]]


class _Entry:
    __slots__ = ("run", "key", "items", "futs", "t0")

    def __init__(self, run: Run, key, item, fut) -> None:
        self.run, self.key, self.items, self.futs = run, key, [item], [fut]
        self.t0 = time.monotonic()


_pending: deque[_Entry] = deque()
# Per-key coalescing: any other op on the key ends the run, so per-key order holds.
_last: dict[Hashable, _Entry] = {}
_inflight: list[_Entry] = []
_queued = 0
_wake: asyncio.Event | None = None
_task: asyncio.Task | None = None


# BEGIN IMMEDIATE takes the lock up front so a read inside never hits SQLITE_BUSY_SNAPSHOT on upgrade.
@contextlib.asynccontextmanager
async def immediate():
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("BEGIN IMMEDIATE"))
        try:
            yield conn
        except BaseException:
            with contextlib.suppress(Exception):
                await conn.execute(text("ROLLBACK"))
            raise
        await conn.execute(text("COMMIT"))


# Lock before the first read: a check and the write it guards run alone, concurrent callers cannot all pass the same check.
@contextlib.asynccontextmanager
async def immediate_session():
    async with immediate() as conn:
        s = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield s
            await s.flush()
        finally:
            await s.close()
    s.sync_session.dispatch.after_commit(s.sync_session)


def running() -> bool:
    try:
        return _task is not None and not _task.done() and _task.get_loop() is asyncio.get_running_loop()
    except RuntimeError:
        return False


async def write(run: Run, item: Any, *, key: Hashable | None = None) -> Any:
    global _queued
    if not running():
        async with immediate() as conn:
            return (await run(conn, [item]))[0]
    fut = asyncio.get_running_loop().create_future()
    e = _last.get(key) if key is not None else None
    if e is not None and e.run is run:
        e.items.append(item)
        e.futs.append(fut)
    else:
        e = _Entry(run, key, item, fut)
        _pending.append(e)
        if key is not None:
            _last[key] = e
    _queued += 1
    write_telemetry.writer_queued(_queued)
    _wake.set()
    return await fut


def _take() -> list[_Entry]:
    global _queued
    out, n = [], 0
    while _pending and (n == 0 or n + len(_pending[0].items) <= BATCH_MAX):
        e = _pending.popleft()
        if _last.get(e.key) is e:
            del _last[e.key]
        out.append(e)
        n += len(e.items)
    _queued -= n
    return out


async def _commit(batch: list[_Entry]) -> list[list]:
    async with immediate() as conn:
        results = []
        for e in batch:
            rs = await e.run(conn, e.items)
            if len(rs) != len(e.items):
                raise RuntimeError(f"{e.run.__qualname__} returned {len(rs)} results for {len(e.items)} ops")
            results.append(rs)
        return results


def _settle(e: _Entry, results: list | None, exc: BaseException | None = None) -> None:
    for i, f in enumerate(e.futs):
        if f.done():
            continue
        if exc is not None:
            f.set_exception(exc)
        else:
            f.set_result(results[i])


def _locked(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


async def _flush(batch: list[_Entry]) -> None:
    n = sum(len(e.items) for e in batch)
    t0 = time.perf_counter()
    try:
        results = await _commit(batch)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — every op's caller hears about it
        # A lock timeout (busy_timeout spent) would only repeat per op, so it fails them all.
        if n == 1 or _locked(exc):
            log.warning("of_writer: %d op(s) of %s failed: %s", n,
                        ",".join(sorted({e.run.__qualname__ for e in batch})), exc)
            write_telemetry.writer_failed(n)
            for e in batch:
                _settle(e, None, exc)
            return
        log.warning("of_writer: batch of %d failed (%s); retrying op by op", n, exc)
        for e in batch:
            for item, fut in zip(e.items, e.futs):
                one = _Entry(e.run, None, item, fut)
                one.t0 = e.t0
                await _flush([one])
        return
    now = time.monotonic()
    write_telemetry.writer_batch(n, len(batch), (time.perf_counter() - t0) * 1000,
                                 [(now - e.t0) * 1000 for e in batch])
    for e, rs in zip(batch, results):
        _settle(e, rs)


async def _loop() -> None:
    # Checkouts spill past the pool cap instead of timing out: a failed batch would drop inbound OF frames.
    UNCAPPED.set(True)
    with write_telemetry.writer("of_writer"):
        while True:
            while not _pending:
                _wake.clear()
                await _wake.wait()
            _inflight[:] = _take()
            await _flush(_inflight)
            _inflight.clear()


def start() -> None:
    global _task, _wake
    if running():
        return
    _wake = asyncio.Event()
    _task = asyncio.create_task(_loop(), name="of-writer")
    log.info("of_writer started (batch max %d)", BATCH_MAX)


async def stop() -> None:
    global _task, _queued
    if _task is None:
        return
    deadline = time.monotonic() + STOP_DRAIN_S
    while (_pending or _inflight) and not _task.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await _task
    _task = None
    left = [*_inflight, *_pending]
    write_telemetry.drop("writer_shutdown", sum(len(e.items) for e in left))
    for e in left:
        for f in e.futs:
            f.cancel()
    _inflight.clear()
    _pending.clear()
    _last.clear()
    _queued = 0
