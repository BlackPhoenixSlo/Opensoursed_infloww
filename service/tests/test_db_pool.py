#!/usr/bin/env python3
"""
The relay's pooled SQLite engine (db/engine.py `_make_engine`, pooled): a file
DB keeps its connections between sessions, and a reused connection still has
the PRAGMAs set on connect: WAL, busy_timeout, foreign_keys. Built on its own
temp file and driven in one event loop, as the relay drives it; the harness's
own engine stays on NullPool.
"""
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

import importlib
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import text
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


if __name__ == "__main__":
    _harness.run()
