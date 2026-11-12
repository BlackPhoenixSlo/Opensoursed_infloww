#!/usr/bin/env python3
"""Standalone bio process and retained counter lifecycle on a throwaway relay-initialized DB."""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError  # noqa: E402
from sqlalchemy import event  # noqa: E402
from bio_pages import app as bio_app  # noqa: E402
from bio_pages import store  # noqa: E402
from db.models import BioProfile, BioLink  # noqa: E402

PID = "p00000000000001"
con = sqlite3.connect(_harness.DB_PATH)
con.execute("INSERT INTO users(id, username, password) VALUES ('u1', 'u1', 'x')")
con.execute("INSERT INTO bio_profiles(id, owner_user_id, username) VALUES (?, 'u1', 'alice')", (PID,))
con.execute("INSERT INTO bio_links(id, profile_id, link_id, title, destination, tracking) "
            "VALUES ('l00000000000001', ?, 'k00000000001', 'Go', 'https://example.test/go', 1)", (PID,))
con.commit()
con.close()


def _port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def case_selected_columns_match_models():
    for names, model in ((store._PROFILE_COLS, BioProfile), (store._LINK_COLS, BioLink)):
        assert set(names.split(", ")) <= set(model.__table__.columns.keys())


def case_process_shutdown_flushes():
    for trial in range(5):
        port = _port()
        env = dict(os.environ, BIO_PORT=str(port), BIO_PRIMARY_HOSTS="localhost", BIO_FLUSH_SECONDS="0.1",
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", "bio_pages.app:app", "--host", "127.0.0.1",
                              "--port", str(port), "--no-proxy-headers"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        lock = None
        try:
            for _ in range(100):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/internal/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.05)
            else:
                raise AssertionError("bio did not start")
            lock = sqlite3.connect(_harness.DB_PATH, timeout=0)
            lock.execute("BEGIN IMMEDIATE")
            with httpx.Client(base_url=f"http://127.0.0.1:{port}") as cl:
                for _ in range(20):
                    assert cl.post("/v/alice").status_code == 204
                    r = cl.get("/.netlify/functions/reveal?id=k00000000001",
                               headers={"Sec-Fetch-Site": "same-origin"})
                    assert r.status_code == 200 and r.json()["realUrl"] == "https://example.test/go"
            time.sleep(0.3)  # a flush has taken the batch and is waiting on BEGIN IMMEDIATE
            p.send_signal(signal.SIGTERM)
            time.sleep(0.3)
            lock.rollback()
            lock.close()
            lock = None
            status = p.wait(timeout=20)
            con = sqlite3.connect(_harness.DB_PATH)
            counts = con.execute("SELECT SUM(views), SUM(clicks) FROM bio_daily").fetchone()
            con.close()
            assert counts == (20 * (trial + 1), 20 * (trial + 1)), (trial, status, counts)
        finally:
            if lock is not None:
                lock.rollback()
                lock.close()
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)


def case_busy_keeps_batch():
    async def go():
        await store.record("view", PID, "", "US", "", "")
        c = sqlite3.connect(_harness.DB_PATH, timeout=0)
        c.execute("BEGIN IMMEDIATE")
        try:
            assert await store.flush() is False
            assert store._batch
        finally:
            c.rollback()
            c.close()
        assert await store.flush() is True
        assert not store._batch
    asyncio.run(go())


def case_bound_starts_early_flush():
    async def go():
        old = store.MAX_KEYS
        store.MAX_KEYS = 1
        try:
            await store.record("view", PID, "", "CA", "", "")
            assert store._flush_task is not None
            await store._flush_task
            assert not store._batch
        finally:
            store.MAX_KEYS = old
    asyncio.run(go())


def case_flush_snapshot_leaves_new_arrivals_for_next_tick():
    async def go():
        await store.record("view", PID, "", "US", "", "snapshot_old")
        loop = asyncio.get_running_loop()
        new_task = None

        def during_insert(_conn, _cursor, statement, _params, _context, _executemany):
            nonlocal new_task
            if "INSERT INTO bio_daily" in statement and new_task is None:
                new_task = loop.create_task(store.record("view", PID, "", "US", "", "snapshot_new"))

        event.listen(store.engine.sync_engine, "before_cursor_execute", during_insert)
        try:
            assert await store.flush() is True
            assert new_task is not None
            await new_task
            assert store.pending() == (1, 1, 0), store.pending()
        finally:
            event.remove(store.engine.sync_engine, "before_cursor_execute", during_insert)
        assert await store.flush() is True
        assert store.pending() == (0, 0, 0)
    asyncio.run(go())


def case_chunked_busy_batch_exactly_once():
    async def go():
        c = sqlite3.connect(_harness.DB_PATH, timeout=0)
        c.execute("BEGIN IMMEDIATE")
        try:
            for i in range(2500):
                await store.record("view", PID, "", "US", "", str(i))
            assert await store.flush() is False
            assert store.pending() == (2500, 2500, 0)
        finally:
            c.rollback()
            c.close()
        assert await store.flush() is True
        assert store.pending() == (0, 0, 0)
        con = sqlite3.connect(_harness.DB_PATH)
        got = con.execute("SELECT COUNT(*), SUM(views), SUM(clicks) FROM bio_daily WHERE code GLOB '[0-9]*'").fetchone()
        con.close()
        assert got == (2500, 2500, 0), got
    asyncio.run(go())


def case_missing_table_does_not_crash():
    async def go():
        await store.record("view", PID, "", "GB", "", "")
        c = sqlite3.connect(_harness.DB_PATH)
        c.execute("ALTER TABLE bio_daily RENAME TO bio_daily_hidden")
        c.commit()
        try:
            real = store.profile_with_links
            async def missing(_name):
                raise OperationalError("SELECT", {}, Exception("no such table"))
            store.profile_with_links = missing
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bio_app.app),
                                         base_url="http://localhost") as client:
                assert (await client.get("/api/profiles/alice.json")).status_code == 503
            store.profile_with_links = real
            assert await store.flush() is False and store._batch
        finally:
            store.profile_with_links = real
            c.execute("ALTER TABLE bio_daily_hidden RENAME TO bio_daily")
            c.commit()
            c.close()
        assert await store.flush() is True
    asyncio.run(go())


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _daily_for(pid: str) -> tuple:
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        return con.execute("SELECT COALESCE(SUM(views),0), COALESCE(SUM(clicks),0) FROM bio_daily "
                           "WHERE profile_id = ?", (pid,)).fetchone()
    finally:
        con.close()


def case_orphan_key_never_poisons_flush():
    """A buffered key for a profile deleted before the flush (FK gone) is dropped with one counted error line;
    every other key still lands and flush answers True (Consult 6 hard gate)."""
    async def go():
        con = sqlite3.connect(_harness.DB_PATH)
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("INSERT INTO bio_profiles(id, owner_user_id, username) VALUES ('p0000000000gone', 'u1', 'gone')")
        con.commit()
        before = _daily_for(PID)
        await store.record("view", PID, "", "US", "", "orphan_ok")
        await store.record("view", "p0000000000gone", "", "US", "", "")
        await store.record("click", "p0000000000gone", "l00000000000001", "US", "", "")
        await store.record("click", PID, "l00000000000001", "US", "", "orphan_ok")
        con.execute("DELETE FROM bio_profiles WHERE id = 'p0000000000gone'")
        con.commit()
        con.close()
        logs = _Logs()
        logging.getLogger("of-relay.bio").addHandler(logs)
        try:
            assert await store.flush() is True
        finally:
            logging.getLogger("of-relay.bio").removeHandler(logs)
        assert store.pending() == (0, 0, 0), store.pending()
        assert _daily_for(PID) == (before[0] + 1, before[1] + 1), _daily_for(PID)
        assert _daily_for("p0000000000gone") == (0, 0)
        dropped = [ln for ln in logs.lines if "orphan" in ln]
        assert len(dropped) == 1 and "keys=2" in dropped[0] and "views=1" in dropped[0] and "clicks=1" in dropped[0], \
            logs.lines
        assert await store.flush() is True
    asyncio.run(go())


def case_batch_hard_cap_under_db_failure():
    """A DB that stays locked never grows the batch past BATCH_CAP: new keys are dropped with a counted, rate-limited
    error; keys already held keep counting and land once the DB frees."""
    async def go():
        old = store.MAX_KEYS, store.BATCH_CAP
        store.MAX_KEYS, store.BATCH_CAP = 3, 5
        lock = sqlite3.connect(_harness.DB_PATH, timeout=0)
        lock.execute("BEGIN IMMEDIATE")
        logs = _Logs()
        logging.getLogger("of-relay.bio").addHandler(logs)
        try:
            before = _daily_for(PID)
            for i in range(50):
                await store.record("view", PID, "", "US", "", f"cap{i}")
                if store._flush_task:
                    await store._flush_task
            assert len(store._batch) <= store.BATCH_CAP, len(store._batch)
            kept = set(store._batch)
            for key in kept:
                await store.record("view", *key[1:])  # same key: still counts
            assert all(store._batch[k][0] == 2 for k in kept), store._batch
            capped = [ln for ln in logs.lines if "batch full" in ln]
            assert 1 <= len(capped) <= 2, logs.lines
            assert "dropped=" in capped[0]
        finally:
            logging.getLogger("of-relay.bio").removeHandler(logs)
            lock.rollback()
            lock.close()
            store.MAX_KEYS, store.BATCH_CAP = old
        assert await store.flush() is True
        assert _daily_for(PID)[0] == before[0] + 2 * len(kept)
        store._retry_after = 0.0
    asyncio.run(go())


def case_cap_counts_inflight_during_failed_flush():
    async def go():
        old_cap, old_max, old_write = store.BATCH_CAP, store.MAX_KEYS, store._write
        entered = asyncio.Event()
        release = asyncio.Event()

        async def failing_write(rows):
            entered.set()
            await release.wait()
            raise OperationalError("INSERT", {}, Exception("database is locked"))

        store.BATCH_CAP, store.MAX_KEYS, store._write = 5, 100, failing_write
        try:
            for i in range(3):
                await store.record("view", PID, "", "US", "", f"flight{i}")
            task = asyncio.create_task(store.flush())
            await entered.wait()
            for i in range(3):
                await store.record("view", PID, "", "US", "", f"flight{i}")
            for i in range(3, 10):
                await store.record("view", PID, "", "US", "", f"flight{i}")
            assert len(store._batch.keys() | store._inflight_keys) <= store.BATCH_CAP, \
                f"pending={len(store._batch)} in-flight=3 cap={store.BATCH_CAP}"
            assert all(store._batch[next(k for k in store._batch if k[-1] == f"flight{i}")][0] == 1
                       for i in range(3)), store._batch
            release.set()
            assert await task is False
            assert not store._inflight_keys
            assert len(store._batch) <= store.BATCH_CAP
            assert all(store._batch[next(k for k in store._batch if k[-1] == f"flight{i}")][0] == 2
                       for i in range(3)), store._batch
        finally:
            release.set()
            store.BATCH_CAP, store.MAX_KEYS, store._write = old_cap, old_max, old_write
            store._batch.clear()
            store._retry_after = 0
    asyncio.run(go())


def case_inflight_cleared_on_cancel():
    async def go():
        old_write = store._write
        entered = asyncio.Event()

        async def held(_rows):
            entered.set()
            await asyncio.Event().wait()

        store._write = held
        try:
            await store.record("view", PID, "", "US", "", "cancelled")
            task = asyncio.create_task(store.flush())
            await entered.wait()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert not store._inflight_keys
        finally:
            store._write = old_write
            store._batch.clear()
    asyncio.run(go())


def case_non_sqlite_fk_race_retries_live_rows():
    from sqlalchemy.exc import IntegrityError

    old_engine = store.engine
    live_id, gone_id = PID, "deleted_profile"

    class Result:
        def __init__(self, ids):
            self.ids = ids

        def scalars(self):
            return self.ids

    class Conn:
        selects = 0
        writes = 0
        rolls = 0
        commits = 0

        async def execute(self, statement, params=None):
            if statement is store._LIVE_QUERY:
                self.selects += 1
                return Result([live_id, gone_id] if self.selects == 1 else [live_id])
            self.writes += 1
            if self.writes == 1:
                raise IntegrityError("INSERT", params, Exception("foreign key"))
            assert [r["profile_id"] for r in params] == [live_id]

        async def rollback(self):
            self.rolls += 1

        async def commit(self):
            self.commits += 1

    class Engine:
        url = type("URL", (), {"get_backend_name": lambda self: "postgresql"})()

        def __init__(self):
            self.conn = Conn()

        def connect(self):
            class Context:
                async def __aenter__(_self):
                    return self.conn

                async def __aexit__(_self, *_):
                    pass
            return Context()

    engine = Engine()
    store.engine = engine
    try:
        rows = [dict(day="2026-11-11", profile_id=pid, link_id="", country="US", in_app="", code="",
                     views=1, clicks=0) for pid in (live_id, gone_id)]
        assert asyncio.run(store._write(rows)) == [rows[1]]
        assert (engine.conn.selects, engine.conn.writes, engine.conn.rolls, engine.conn.commits) == (2, 2, 1, 1)
    finally:
        store.engine = old_engine


def case_pool_and_interface_failures_requeue():
    async def go():
        original = store._write
        for i, error in enumerate((TimeoutError("pool busy"), InterfaceError("INSERT", {}, Exception("disconnect")))):
            key = f"transient{i}"
            await store.record("view", PID, "", "US", "", key)

            async def fail(_rows):
                raise error

            store._write = fail
            try:
                assert await store.flush() is False
                assert any(k[-1] == key for k in store._batch)
            finally:
                store._write = original
            assert await store.flush() is True
        assert store.pending() == (0, 0, 0)
    asyncio.run(go())


_harness.run()
