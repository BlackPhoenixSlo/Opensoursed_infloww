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
a spill connection after SPILL_AFTER_S instead of waiting on itself. Spills stop
at MAX_SPILL (the pool's max_overflow): past it a checkout waits for a returned
connection, up to WAIT_MAX_S, then raises TimeoutError, which server.py's
_DbBusy503 answers 503 + Retry-After.
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


async def _hold_all(eng, n: int):
    """`n` tasks each hold one connection until `release` is set; returns once all hold."""
    release, holding = asyncio.Event(), asyncio.Semaphore(0)

    async def hold() -> None:
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
            holding.release()
            await release.wait()

    tasks = [asyncio.create_task(hold()) for _ in range(n)]
    for _ in range(n):
        await holding.acquire()
    return release, tasks


async def case_spills_stop_at_the_cap_and_the_next_checkout_waits_for_a_returned_connection():
    """The 2026-11-09 thread storm (relay-admission medium/200: 2,856 spills, one
    thread each): with pool_size + cap connections out, one more checkout opens
    nothing, waits, and gets the first one returned."""
    path, eng, opened = _temp_engine()
    try:
        pool = eng.sync_engine.pool
        pool._timeout, pool._max_overflow = 0.2, 4   # small knobs, same code path
        cap = engine_mod.POOL_SIZE + 4
        release, tasks = await _hold_all(eng, cap)
        assert len(opened) == cap and pool.spills == 4, (len(opened), pool.spills)

        async def late() -> int:
            async with eng.connect() as conn:
                return (await conn.execute(text("SELECT 7"))).scalar()

        t = asyncio.create_task(late())
        await asyncio.sleep(0.5)               # past the spill wait: capped, still waiting
        assert not t.done() and pool.capped == 1, (t.done(), pool.capped)
        release.set()
        assert await asyncio.wait_for(t, 5) == 7
        await asyncio.gather(*tasks)
        assert len(opened) == cap, f"{len(opened)} connections opened, cap {cap}"
    finally:
        await _cleanup(path, eng)


async def case_a_checkout_at_the_cap_raises_timeout_after_wait_max_s_and_503s():
    from sqlalchemy.exc import TimeoutError as PoolTimeout
    path, eng, opened = _temp_engine()
    wait_max = engine_mod.WAIT_MAX_S
    try:
        pool = eng.sync_engine.pool
        pool._timeout, pool._max_overflow = 0.1, 2
        engine_mod.WAIT_MAX_S = 0.3
        release, tasks = await _hold_all(eng, engine_mod.POOL_SIZE + 2)
        t0 = time.monotonic()
        try:
            async with eng.connect():
                raise AssertionError("checked out past the cap")
        except PoolTimeout as e:
            assert "DB pool busy" in str(e), e
        waited = time.monotonic() - t0
        assert 0.35 <= waited < 3, waited
        assert len(opened) == engine_mod.POOL_SIZE + 2, len(opened)
        release.set()
        await asyncio.gather(*tasks)
    finally:
        engine_mod.WAIT_MAX_S = wait_max
        await _cleanup(path, eng)

    # server.py's outer layer answers that TimeoutError 503 + Retry-After
    import server
    sent: list[dict] = []

    async def app(scope, receive, send):
        raise PoolTimeout("DB pool busy")

    async def send(msg):
        sent.append(msg)

    await server._DbBusy503(app)({"type": "http", "method": "GET", "path": "/x", "headers": []},
                                 None, send)
    assert sent[0]["status"] == 503, sent[0]
    assert (b"retry-after", b"5") in sent[0]["headers"], sent[0]["headers"]


if __name__ == "__main__":
    _harness.run()
