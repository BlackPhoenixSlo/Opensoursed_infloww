#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

import asyncio  # noqa: E402
import os  # noqa: E402

os.environ.pop("CHATTERLY_DB_NULLPOOL", None)
os.environ["CHATTERLY_DB_POOL_SIZE"] = "1"
os.environ["CHATTERLY_DB_MAX_SPILL"] = "0"
os.environ["CHATTERLY_DB_SPILL_AFTER_S"] = "0.02"
os.environ["CHATTERLY_DB_WAIT_MAX_S"] = "0.05"

from sqlalchemy import exc as sqla_exc, text  # noqa: E402

from db import of_writer  # noqa: E402
from db.engine import engine  # noqa: E402


async def _insert(conn, items):
    for value in items:
        await conn.execute(text("INSERT INTO cap_writer (value) VALUES (:value)"),
                           {"value": value})
    return items


async def case_of_writer_commits_with_pool_saturated():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS cap_writer (value INTEGER NOT NULL)"))
    of_writer.start()
    try:
        async with engine.connect() as held:
            await held.execute(text("SELECT 1"))
            assert engine.pool.checkedout() == 1, engine.pool.status()
            result = (await asyncio.gather(of_writer.write(_insert, 7),
                                           return_exceptions=True))[0]
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT value FROM cap_writer"))).scalars().all()
    finally:
        await of_writer.stop()
        await engine.dispose()
    assert (result, rows) == (7, [7]), f"writer result={result!r}, committed rows={rows!r}"


async def case_a_request_checkout_at_the_cap_still_times_out():
    try:
        async with engine.connect() as held:
            await held.execute(text("SELECT 1"))
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            except sqla_exc.TimeoutError:
                pass
            else:
                raise AssertionError("a request checkout at the cap was admitted")
    finally:
        await engine.dispose()


_harness.run()
