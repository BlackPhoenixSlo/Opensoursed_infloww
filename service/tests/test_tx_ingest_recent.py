#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import logging  # noqa: E402
import re  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import of_client  # noqa: E402
import transaction_ingest as ti  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Transaction, TransactionScanHistory  # noqa: E402

ACCT = "77001"
OLDEST = datetime(2026, 8, 1)
ti._PAGE_SLEEP_S = 0.0


class _Fake:

    def __init__(self, pages):
        self.pages, self.calls, self.wire = list(pages), [], []

    def transactions(self, **kw):
        self.calls.append(kw)
        rec = of_client.OFClient.__new__(of_client.OFClient)
        rec.get_json = lambda path, params=None: self.wire.append(params) or {}
        of_client.OFClient.transactions(rec, **kw)
        p = self.pages.pop(0) if self.pages else {"list": [], "hasMore": False}
        if callable(p):
            p()
        return p


def _row(pid: str, at: datetime) -> dict:
    return {"id": pid, "user": {"id": 555}, "amount": 5.0, "net": 4.0, "fee": 1.0,
            "createdAt": at.isoformat() + "Z", "status": "done", "description": "Tip from u555"}


def _page(rows, more=False) -> dict:
    return {"list": rows, "hasMore": more}


def _boom():
    raise RuntimeError("OF 500")


async def _ready() -> None:
    async with get_session() as s:
        if await s.get(Account, ACCT) is None:
            s.add(Account(id=ACCT, nickname="recent"))
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        if row is None:
            row = TransactionScanHistory(account_id=ACCT)
            s.add(row)
        row.fully_backfilled = True
        row.backfill_floor = OLDEST
        row.oldest_seen_occurred_at = OLDEST
        row.newest_seen_occurred_at = None
        row.current_status = "ok"
        row.consecutive_failures = 0
        row.paused_until = None
        row.last_full_at = None
        row.full_walk_failures = 0
        row.last_error = None
    ti._recent_window_warned.discard(ACCT)
    ti._recent_empty_warned.discard(ACCT)


async def _set_full(at: datetime | None) -> None:
    async with get_session() as s:
        (await s.get(TransactionScanHistory, ACCT)).last_full_at = at


async def _full() -> datetime | None:
    return (await _scan()).last_full_at


def _restart() -> None:
    ti._recent_window_warned.clear()
    ti._recent_empty_warned.clear()
    ti._reinstated.clear()
    assert not hasattr(ti, "_last_full_at"), "the full-walk watermark is in memory again"


def _period_start() -> datetime:
    full, ph = ti._FULL_EVERY_S, ti.full_phase_s(ACCT, ti._FULL_EVERY_S)
    b = ti.full_bucket(datetime.utcnow(), full_every_s=full, phase_s=ph)
    return datetime(1970, 1, 1) + timedelta(seconds=b * full - ph)


async def _tick(fake: _Fake) -> tuple[str, dict]:
    mode = await ti._decide_mode(ACCT)
    orig = ti._client_for
    ti._client_for = lambda _aid: fake
    try:
        return mode, await ti.run_one_tick(ACCT, mode=mode)
    finally:
        ti._client_for = orig


async def _scan() -> TransactionScanHistory:
    async with get_session() as s:
        return await s.get(TransactionScanHistory, ACCT)


async def _health() -> tuple[str, str, int]:
    from tx_ingest_admin_api import admin_ingest_tx_health
    h = {a["account_id"]: a for a in (await admin_ingest_tx_health())["accounts"]}[ACCT]
    return h["tier"], h["current_status"], h["full_walk_failures"]


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _near(a: datetime, b: datetime, s: float = 5.0) -> bool:
    return abs((a - b).total_seconds()) <= s


async def case_recent_tick_is_one_call_over_24h():
    await _ready()
    full_at = _period_start()
    await _set_full(full_at)
    now = datetime.utcnow()
    fake = _Fake([_page([_row("r1", now - timedelta(hours=3)), _row("r2", now - timedelta(hours=20))])])
    mode, res = await _tick(fake)
    assert mode == "recent", mode
    assert res["error"] is None and res["pages"] == 1 and res["rows_inserted"] == 2, res
    assert len(fake.calls) == 1, fake.calls
    c = fake.calls[0]
    assert _near(_at(c["start"]), now - timedelta(hours=24)) and _near(_at(c["end"]), now), c
    assert (c["limit"], c["offset"]) == (ti._PAGE_LIMIT, 0), c
    # OF answers an ISO startDate with nothing, so the wire carries a date-only one.
    sd = fake.wire[0]["startDate"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", sd), f"startDate must be date-only, never ISO: {sd!r}"
    assert sd == (_at(c["start"]) - timedelta(days=1)).date().isoformat(), (sd, c["start"])
    assert await _full() == full_at, "a recent walk must not reset the full-walk clock"
    row = await _scan()
    assert row.current_status == "ok" and _near(row.last_scan_at, datetime.utcnow()), row.current_status
    assert row.oldest_seen_occurred_at == OLDEST, row.oldest_seen_occurred_at
    assert (row.fully_backfilled, row.backfill_floor) == (True, OLDEST)


async def case_due_full_walks_7d_and_stamps():
    await _ready()
    await _set_full(_period_start() - timedelta(seconds=1))
    now = datetime.utcnow()
    fake = _Fake([_page([_row("f1", now - timedelta(days=1))], more=True),
                  _page([_row("f2", now - timedelta(days=6))])])
    before = datetime.utcnow()
    mode, res = await _tick(fake)
    assert mode == "refresh", mode
    assert res["error"] is None and res["pages"] == 2, res
    assert [c["offset"] for c in fake.calls] == [0, 1], fake.calls
    assert all(_near(_at(c["start"]), now - timedelta(days=7)) for c in fake.calls), fake.calls
    assert not any("startDate" in w for w in fake.wire), fake.wire
    stamped = await _full()
    assert stamped is not None and stamped >= before, stamped
    assert (await ti._decide_mode(ACCT)) == "recent", "right after a full walk the next is recent"
    _restart()
    assert (await ti._decide_mode(ACCT)) == "recent", "a restart re-walked an account not due"
    assert await _full() == stamped
    await _set_full(_period_start() - timedelta(seconds=1))
    _restart()
    assert (await ti._decide_mode(ACCT)) == "refresh"


async def case_backfill_sends_a_date_only_start_date():
    await _ready()
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        row.fully_backfilled = False
        row.oldest_seen_occurred_at = None
    fake = _Fake([_page([_row("b1", datetime.utcnow() - timedelta(days=2))])])
    mode, res = await _tick(fake)
    assert mode == "backfill" and res["error"] is None and fake.wire, (mode, res, fake.wire)
    assert fake.wire == [{"limit": 100, "offset": 0, "startDate": "2026-07-31"}], fake.wire


def _second_429():
    from types import SimpleNamespace
    raise of_client.OFAPIError("HTTP 429", response=SimpleNamespace(status_code=429, text="Too Many Requests"))


async def case_failed_full_stamps_its_period():
    for boom in (_boom, _second_429):
        await _ready()
        await _set_full(_period_start() - timedelta(seconds=1))
        fake = _Fake([_page([_row(f"x1{boom.__name__}", datetime.utcnow() - timedelta(days=2))], more=True),
                      boom])
        before = datetime.utcnow()
        mode, res = await _tick(fake)
        assert mode == "refresh" and res["error"], (mode, res)
        row = await _scan()
        assert row.current_status == "error" and row.consecutive_failures == 1, \
            (row.current_status, row.consecutive_failures)
        assert row.last_error and res["error"][:40] in row.last_error, row.last_error
        assert row.last_full_at is not None and row.last_full_at >= before, \
            f"a failed full walk ({boom.__name__}) did not spend its period"
        assert row.full_walk_failures == 1 and row.last_error.startswith("full_walk_failed: "), row.last_error
        assert (await ti._decide_mode(ACCT)) == "recent", "a failed full walk re-walked in its period"
        _restart()
        fail_err = res["error"]
        mode, res = await _tick(_Fake([_page([_row(f"ok{boom.__name__}", datetime.utcnow() - timedelta(hours=1))])]))
        row = await _scan()
        assert mode == "recent" and res["error"] is None, (mode, res)
        assert (row.current_status, row.consecutive_failures, row.full_walk_failures) == (
            "ok", 0, 1), (row.current_status, row.consecutive_failures, row.full_walk_failures)
        assert row.last_error.startswith("full_walk_failed: ") and fail_err[:40] in row.last_error, row.last_error
        assert await _health() == ("yellow", "full_walk_failed", 1)
        await _set_full(_period_start() - timedelta(seconds=1))
        mode, res = await _tick(_Fake([_page([])]))
        row = await _scan()
        assert mode == "refresh" and res["error"] is None, (mode, res)
        assert (row.current_status, row.full_walk_failures, row.last_error) == ("ok", 0, None), row.current_status


async def case_truncated_full_stamps():
    await _ready()
    same = _page([_row("t1", datetime.utcnow() - timedelta(days=2))], more=True)
    fake = _Fake([same, same])
    await _set_full(_period_start() - timedelta(seconds=1))
    before = datetime.utcnow()
    mode, res = await _tick(fake)
    assert mode == "refresh" and res["error"] is None and res["pages"] == 1, (mode, res)
    assert len(fake.calls) == 2, fake.calls
    assert (await _full()) >= before, "a walk cut short by the repeated-page guard did not stamp"
    row = await _scan()
    assert (row.current_status, row.full_walk_failures, row.last_error) == (
        "ok", 1, "full_walk_failed: cut_short: repeated_page"), (row.current_status, row.last_error)
    assert await _health() == ("yellow", "full_walk_failed", 1)
    assert (await ti._decide_mode(ACCT)) == "recent"


def _refused():
    from curl_cffi.requests.exceptions import ProxyError
    raise ProxyError("Failed to perform, curl: (56) CONNECT tunnel failed, response 403.")


async def case_refused_full_counts_only_after_a_page():
    for first, want_stamp, want_count in ((False, False, 0), (True, True, 1)):
        await _ready()
        due = _period_start() - timedelta(seconds=1)
        await _set_full(due)
        pages = ([_page([_row("rf1", datetime.utcnow() - timedelta(days=2))], more=True)] if first else []) + [_refused]
        before = datetime.utcnow()
        mode, res = await _tick(_Fake(pages))
        row = await _scan()
        assert mode == "refresh" and res["error"] and res["pages"] == int(first), (mode, res)
        assert (row.current_status, row.consecutive_failures, row.full_walk_failures) == (
            "idle", 0, want_count), (first, row.current_status, row.consecutive_failures, row.full_walk_failures)
        assert (row.last_full_at >= before) == want_stamp and (row.last_full_at == due) != want_stamp, row.last_full_at
        assert (await ti._decide_mode(ACCT)) == ("recent" if want_stamp else "refresh"), first


async def case_unseeded_backfilled_account_seeds_once():
    await _ready()
    before = datetime.utcnow()
    assert (await ti._decide_mode(ACCT)) == "recent", "an unseeded backfilled account walked full"
    seeded = await _full()
    assert seeded is not None and seeded >= before, seeded
    _restart()
    assert (await ti._decide_mode(ACCT)) == "recent" and await _full() == seeded, "seeded twice"
    await _set_full(_period_start() - timedelta(seconds=1))
    assert (await ti._decide_mode(ACCT)) == "refresh"
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        row.fully_backfilled, row.last_full_at = False, None
    assert (await ti._decide_mode(ACCT)) == "refresh" and await _full() is None


async def case_admin_run_refresh_forces_and_stamps():
    await _ready()
    await _set_full(_period_start())
    assert (await ti._decide_mode(ACCT)) == "recent"
    fake = _Fake([_page([_row("adm1", datetime.utcnow() - timedelta(days=1))])])
    orig = ti._client_for
    ti._client_for = lambda _aid: fake
    before = datetime.utcnow()
    try:
        res = await ti.supervised_tick(ACCT, "refresh")
    finally:
        ti._client_for = orig
    assert res.get("error") is None and len(fake.calls) == 1 and "startDate" not in fake.wire[0], (res, fake.wire)
    assert (await _full()) >= before
    assert (await ti._decide_mode(ACCT)) == "recent"


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs: list[str] = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


async def case_window_ignored_warns_once():
    await _ready()
    await _set_full(_period_start())
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        for n in range(2):
            now = datetime.utcnow()
            fake = _Fake([_page([_row(f"w{n}a", now - timedelta(hours=2)),
                                 _row(f"w{n}b", now - timedelta(days=5))])])
            mode, res = await _tick(fake)
            assert mode == "recent" and res["error"] is None and res["rows_inserted"] == 2, (mode, res)
    finally:
        ti.log.removeHandler(grab)
    hits = [m for m in grab.msgs if m.startswith("ingest_tx_recent_window_ignored")]
    assert len(hits) == 1, grab.msgs
    assert f"account={ACCT} " in hits[0] and "oldest=" in hits[0] and "window_start=" in hits[0], hits
    assert re.search(r"window_start=\d{4}-\d{2}-\d{2}$", hits[0]), hits
    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(Transaction).where(
            Transaction.account_id == ACCT, Transaction.provider_transaction_id.in_(
                ["w0a", "w0b", "w1a", "w1b"])))).scalar()
    assert n == 4, f"rows outside the window must still land (got {n})"


async def case_inside_slack_no_warning():
    await _ready()
    await _set_full(_period_start())
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        now = datetime.utcnow()
        sd = datetime.fromisoformat(ti.recent_start_date(now - timedelta(hours=ti._RECENT_WINDOW_H)))
        await _tick(_Fake([_page([_row("s1", now - timedelta(hours=24, minutes=30)),
                                  _row("s2", sd - timedelta(hours=23))])]))
    finally:
        ti.log.removeHandler(grab)
    assert not [m for m in grab.msgs if "recent_window_ignored" in m], grab.msgs


async def _set_newest(at: datetime) -> None:
    async with get_session() as s:
        (await s.get(TransactionScanHistory, ACCT)).newest_seen_occurred_at = at


async def case_recent_empty_walk_warns_once():
    await _ready()
    await _set_full(_period_start())
    await _set_newest(datetime.utcnow() - timedelta(hours=2))
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        for _ in range(2):
            mode, res = await _tick(_Fake([_page([])]))
            assert mode == "recent" and res["error"] is None and res["rows_inserted"] == 0, (mode, res)
    finally:
        ti.log.removeHandler(grab)
    hits = [m for m in grab.msgs if m.startswith("ingest_tx_recent_walk_empty")]
    assert len(hits) == 1, grab.msgs
    assert re.fullmatch(rf"ingest_tx_recent_walk_empty account={ACCT} start_date=\d{{4}}-\d{{2}}-\d{{2}} "
                        r"newest_seen=\S+", hits[0]), hits
    assert (await _scan()).current_status == "ok"


async def case_quiet_account_empty_walk_no_warning():
    await _ready()
    await _set_full(_period_start())
    await _set_newest(datetime.utcnow() - timedelta(days=5))
    grab = _Grab()
    ti.log.addHandler(grab)
    try:
        mode, res = await _tick(_Fake([_page([])]))
    finally:
        ti.log.removeHandler(grab)
    assert mode == "recent" and res["error"] is None, (mode, res)
    assert not [m for m in grab.msgs if "recent_walk_empty" in m], grab.msgs


async def case_supervisor_passes_the_mode():
    await _ready()
    ticked = []

    async def _sup(aid, mode):
        ticked.append((aid, mode))
        return {}

    async def _only():
        return [ACCT]

    saved = ti.supervised_tick, ti.live_account_ids
    ti.supervised_tick, ti.live_account_ids = _sup, _only
    try:
        await _set_full(_period_start() - timedelta(seconds=1))
        await ti.supervisor_cycle()
        await _set_full(_period_start())
        await ti.supervisor_cycle()
    finally:
        ti.supervised_tick, ti.live_account_ids = saved
    assert ticked == [(ACCT, "refresh"), (ACCT, "recent")], ticked


async def case_health_exposes_last_full_attempt_at():
    from tx_ingest_admin_api import admin_ingest_tx_health
    await _ready()
    at = datetime(2026, 11, 7, 9, 30)
    await _set_full(at)
    _restart()
    rows = {a["account_id"]: a for a in (await admin_ingest_tx_health())["accounts"]}
    assert rows[ACCT]["last_full_attempt_at"] == at.isoformat(), rows[ACCT]
    await _set_full(None)
    rows = {a["account_id"]: a for a in (await admin_ingest_tx_health())["accounts"]}
    assert rows[ACCT]["last_full_attempt_at"] is None, rows[ACCT]


@contextmanager
def _legacy_db(tag: str, revision: str, column: str, row: str):
    import asyncio
    import importlib
    import os
    import sqlite3
    import tempfile
    from pathlib import Path

    import sqlalchemy as sa
    import sqlalchemy.dialects.sqlite  # noqa: F401
    from sqlalchemy.schema import CreateTable

    old = Path(tempfile.gettempdir()) / f"tx_scan_{tag}_{os.getpid()}.db"
    old.unlink(missing_ok=True)
    acct_ddl, ddl = (str(CreateTable(m.__table__).compile(dialect=sa.dialects.sqlite.dialect()))
                     for m in (Account, TransactionScanHistory))
    con = sqlite3.connect(old)
    con.executescript(f"""
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('{revision}');
        {acct_ddl};
        {ddl};
        ALTER TABLE transaction_scan_history DROP COLUMN {column};
        INSERT INTO transaction_scan_history {row};
    """)
    con.commit()
    con.close()
    db_engine = importlib.import_module("db.engine")
    prev = db_engine.DATABASE_URL
    try:
        db_engine.DATABASE_URL = f"sqlite+aiosqlite:///{old}"
        asyncio.run(db_engine.init_db())
    finally:
        db_engine.DATABASE_URL = prev
    con = sqlite3.connect(old)
    cols = {r[1] for r in con.execute("PRAGMA table_info(transaction_scan_history)")}
    val = con.execute(f"SELECT {column} FROM transaction_scan_history").fetchone()
    con.close()
    try:
        yield old, cols, val
    finally:
        old.unlink(missing_ok=True)


def _migration_roundtrip(db, file: str, revision: str, down_revision: str, column: str) -> None:
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    versions = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"
    spec = importlib.util.spec_from_file_location(f"mig_{revision}", versions / file)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert (mig.revision, mig.down_revision) == (revision, down_revision)
    downs = [line for f in versions.glob("*.py") for line in f.read_text().splitlines()
             if line.startswith("down_revision") and down_revision in line]
    assert len(downs) == 1, f"{down_revision} must have exactly one child: {downs}"
    eng = sa.create_engine(f"sqlite:///{db}")

    def step(fn):
        with eng.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                fn()

    def has() -> bool:
        return column in {c["name"] for c in sa.inspect(eng).get_columns("transaction_scan_history")}

    try:
        step(mig.upgrade)
        assert has()
        step(mig.downgrade)
        step(mig.downgrade)
        assert not has()
        step(mig.upgrade)
        step(mig.upgrade)
        assert has()
    finally:
        eng.dispose()


def case_legacy_schema_gains_last_full_at():
    with _legacy_db("old", "0105_of_consent_accepts", "last_full_at",
                    "(account_id, fully_backfilled) VALUES ('legacy1', 1)") as (db, cols, val):
        assert "last_full_at" in cols and val == (None,), (sorted(cols), val)
        _migration_roundtrip(db, "20261108_1300_tx_scan_last_full_at.py", "0106_tx_scan_last_full_at",
                             "0105_of_consent_accepts", "last_full_at")


def case_legacy_schema_gains_backfill_stalls():
    import transaction_ingest_decide as d
    with _legacy_db("stalls", "0106_tx_scan_last_full_at", "backfill_stalls",
                    "(account_id, fully_backfilled, current_status) VALUES ('legacy2', 0, 'idle')") as (_, cols, val):
        assert "backfill_stalls" in cols and val == (None,), (sorted(cols), val)
    facts = ti.scan_facts(TransactionScanHistory(account_id="legacy2", fully_backfilled=False,
                                                 current_status="idle", backfill_stalls=val[0]))
    assert facts.backfill_stalls == 0 and not d.walk_started(facts), facts
    assert d.decide_mode(facts, now=datetime(2026, 11, 8)).mode == "backfill", "a NULL is no stall"


def case_legacy_schema_gains_full_walk_failures():
    import transaction_ingest_decide as d
    from tx_ingest_admin_api import _tx_ingest_tier
    with _legacy_db("fwf", "0110_assistant_turn_thread", "full_walk_failures",
                    "(account_id, fully_backfilled, current_status) VALUES ('legacy3', 1, 'ok')") as (db, cols, val):
        assert "full_walk_failures" in cols and val == (None,), (sorted(cols), val)
        facts = ti.scan_facts(TransactionScanHistory(account_id="legacy3", fully_backfilled=True,
                                                     current_status="ok", full_walk_failures=val[0]))
        ok = d.scan_after_success(facts, mode="recent", inserted=0, patched=0, last_marker=None, rows_min=None,
                                  rows_max=None, floor_reached=True, now=datetime(2026, 11, 10)).state
        assert (facts.full_walk_failures, _tx_ingest_tier(5.0, ok.current_status, ok.full_walk_failures)) == (
            0, "green"), "a NULL is no failed full walk"
        _migration_roundtrip(db, "20261111_0100_tx_scan_full_walk_failures.py", "0111_tx_scan_full_walk_failures",
                             "0110_assistant_turn_thread", "full_walk_failures")


_harness.run()
