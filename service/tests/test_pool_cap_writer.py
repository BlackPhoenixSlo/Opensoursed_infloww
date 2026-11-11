#!/usr/bin/env python3
"""The OF-cache writer (db/of_writer) commits when the DB pool is at its cap.

Request traffic at the cap waits WAIT_MAX_S and raises (server.py: 503); the
writer carries inbound WS frames (event_inbox, messages) whose SSE already went
out, so a timeout there loses them. Its checkout spills past the cap instead
(db/engine.py UNCAPPED, set inside the writer task: the ContextVar must reach
the pool's _do_get through SQLAlchemy's greenlet, which this proves).

  case_of_writer_commits_with_pool_saturated: pool of 1, no spills, the one
      connection held; a writer op still commits.
  case_a_request_checkout_at_the_cap_still_times_out: the same saturation, a
      plain checkout raises TimeoutError (#386's anti-storm cap kept).

Run: ./venv/bin/python service/tests/test_pool_cap_writer.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import asyncio  # noqa: E402
import os  # noqa: E402

# The real bounded pool, a fast timeout and one available checkout.
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
            await held.execute(text("SELECT 1"))  # the pool's sole slot
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
