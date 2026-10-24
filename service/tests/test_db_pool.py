#!/usr/bin/env python3
"""
The relay's pooled SQLite engine (db/engine.py `_make_engine`, pooled): a file
DB keeps its connections between sessions, and a reused connection still has
the PRAGMAs set on connect: WAL, busy_timeout, foreign_keys. Built on its own
temp file and driven in one event loop, as the relay drives it; the harness's
own engine stays on NullPool.

The pool is bounded (`_SpillQueuePool`, 03-write-storm): a burst of sessions far
larger than the pool opens no more than POOL_SIZE connections and every write in
it lands; a task that nests a second session while the pool is exhausted gets
a spill connection after SPILL_AFTER_S instead of waiting on itself.
"""
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

import asyncio
import importlib
import tempfile
import time
import uuid
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

engine_mod = importlib.import_module("db.engine")


def case_the_harness_engine_keeps_null_pool():
    assert isinstance(engine_mod.engine.pool, NullPool), type(engine_mod.engine.pool)


async def case_a_reused_pooled_connection_keeps_wal_busy_timeout_and_foreign_keys():
    path = Path(tempfile.gettempdir()) / f"chatterly_pool_{uuid.uuid4().hex}.db"
    eng = engine_mod._make_engine(f"sqlite+aiosqlite:///{path}", pooled=True)
    try:
        assert isinstance(eng.pool, AsyncAdaptedQueuePool), type(eng.pool)
        seen: set[int] = set()
        for _ in range(20):
            async with eng.connect() as conn:
                raw = await conn.get_raw_connection()
                seen.add(id(raw.driver_connection))
                got = [(await conn.execute(text(f"PRAGMA {p}"))).scalar()
                       for p in ("journal_mode", "busy_timeout", "foreign_keys")]
                assert got == ["wal", 30000, 1], got
        assert len(seen) == 1, f"sequential sessions opened {len(seen)} connections, not one reused"
        assert eng.pool.checkedin() == 1, eng.pool.status()
    finally:
        await eng.dispose()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)



def _temp_engine():
    path = Path(tempfile.gettempdir()) / f"chatterly_pool_{uuid.uuid4().hex}.db"
    eng = engine_mod._make_engine(f"sqlite+aiosqlite:///{path}", pooled=True)
    opened = []
    event.listen(eng.sync_engine, "connect", lambda *_a: opened.append(1))
    return path, eng, opened


async def _cleanup(path, eng):
    await eng.dispose()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


async def case_a_burst_of_200_writers_opens_at_most_pool_size_connections_and_loses_no_write():
    """The write-storm regression: 200 sessions at once (a stalled relay's backlog).
    Unbounded overflow opened one connection per session (200 threads, 200 schema
    parses); bounded, they queue for POOL_SIZE connections and every row lands."""
    path, eng, opened = _temp_engine()
    try:
        async with eng.begin() as conn:
            await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))

        async def write(i: int) -> None:
            async with eng.begin() as conn:
                await conn.execute(text("INSERT INTO t (id, v) VALUES (:i, 'x')"), {"i": i})
                await asyncio.sleep(0.005)  # an await inside the transaction, as the ORM's are

        await asyncio.gather(*(write(i) for i in range(200)))
        async with eng.connect() as conn:
            n = (await conn.execute(text("SELECT COUNT(*) FROM t"))).scalar()
        assert n == 200, f"{n} of 200 writes landed"
        assert len(opened) <= engine_mod.POOL_SIZE, f"{len(opened)} connections opened for a 200-session burst"
        assert eng.pool.spills == 0, eng.pool.spills
    finally:
        await _cleanup(path, eng)


async def case_a_nested_session_on_an_exhausted_pool_spills_instead_of_waiting_on_itself():
    """POOL_SIZE tasks each hold a connection and open a second: none can be served
    from the pool, so each waits SPILL_AFTER_S, then gets an extra connection."""
    path, eng, opened = _temp_engine()
    try:
        held = asyncio.Event()
        n_in = 0

        async def nest() -> int:
            nonlocal n_in
            async with eng.connect() as outer:
                await outer.execute(text("SELECT 1"))
                n_in += 1
                if n_in == engine_mod.POOL_SIZE:
                    held.set()
                await held.wait()
                async with eng.connect() as inner:
                    return (await inner.execute(text("SELECT 2"))).scalar()

        t0 = time.monotonic()
        got = await asyncio.wait_for(asyncio.gather(*(nest() for _ in range(engine_mod.POOL_SIZE))),
                                     engine_mod.SPILL_AFTER_S + 10)
        waited = time.monotonic() - t0
        assert got == [2] * engine_mod.POOL_SIZE, got
        assert eng.pool.spills == engine_mod.POOL_SIZE, eng.pool.spills
        assert waited >= engine_mod.SPILL_AFTER_S * 0.9, waited
        assert eng.pool.checkedin() == engine_mod.POOL_SIZE, eng.pool.status()  # spills closed on return
    finally:
        await _cleanup(path, eng)


if __name__ == "__main__":
    _harness.run()
