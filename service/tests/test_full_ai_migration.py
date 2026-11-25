#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from db.models import Base  # noqa: E402

TABLE = "ai_decisions"
PRIOR, REV = "0116_scrape_history_deferred", "0117_full_ai_decisions"
TEST_CHAT, BEFORE_TEST_CHAT = "0119_full_ai_test_chat", "0118_owner_tokens"
NEW_COLUMNS = (("ai_decisions", "reply_json"), ("account_ai_config", "full_ai_config_json"))
OFFERS = "0120_full_ai_offers"
OFFER_INDEX = "uq_ai_decisions_offer_message"
ATTEMPT, BEFORE_ATTEMPT = "0130_ai_decisions_offer_attempt", "0129_keep_running_rules_heal"
OFFER_COLUMNS = {"offer_price_cents": "INTEGER", "offer_list_cents": "INTEGER",
                 "offer_media_json": "TEXT", "offer_item_ref": "TEXT", "offer_message_id": "BIGINT",
                 "outcome": "VARCHAR", "outcome_at": "DATETIME", "join_src": "VARCHAR"}
MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
COLUMNS = ("id", "account_id", "fan_id", "mode", "trigger_kind", "trigger_key", "parent_id",
           "anchor_message_id", "anchor_created_at", "arm", "salt_ver", "route", "heat",
           "route_row", "question_version", "router_model", "writer_model", "jev_json",
           "jev_ms", "jev_error", "status", "created_at", "updated_at", "reply_json",
           *OFFER_COLUMNS, "offer_attempt_at")


_OLD_TABLES = ("CREATE TABLE accounts (id VARCHAR PRIMARY KEY)",
               "CREATE TABLE users (id VARCHAR PRIMARY KEY)",
               "CREATE TABLE actions (id INTEGER PRIMARY KEY)",
               "CREATE TABLE account_ai_config (account_id VARCHAR PRIMARY KEY)",
               "CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)")


def _cols(path, table) -> dict[str, tuple[str, int]]:
    con = sqlite3.connect(path)
    try:
        return {r[1]: (r[2], r[3]) for r in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


def _shape(path):
    con = sqlite3.connect(path)
    try:
        cols = tuple((r[1], r[2], r[3]) for r in con.execute(f"PRAGMA table_info({TABLE})"))
        idx = {}
        for r in con.execute(f"PRAGMA index_list({TABLE})"):
            idx[r[1]] = (r[2], tuple(c[2] for c in con.execute(f"PRAGMA index_info('{r[1]}')")))
        return cols, idx
    finally:
        con.close()


def _partial(path) -> bool:
    con = sqlite3.connect(path)
    try:
        (sql,) = con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                             (OFFER_INDEX,)).fetchone()
        return "WHERE offer_message_id IS NOT NULL" in sql
    finally:
        con.close()


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def _alembic(url: str, fn, rev: str) -> None:
    prior = os.environ["CHATTERLY_DB_URL"]
    os.environ["CHATTERLY_DB_URL"] = url
    try:
        fn(_cfg(), rev)
    finally:
        os.environ["CHATTERLY_DB_URL"] = prior


def _to_attempt(url: str) -> None:
    _alembic(url, command.upgrade, OFFERS)
    _alembic(url, command.stamp, BEFORE_ATTEMPT)
    _alembic(url, command.upgrade, ATTEMPT)


def case_upgrade_matches_create_all():
    with tempfile.TemporaryDirectory(prefix="full_ai_migration_") as tmp:
        old, fresh = Path(tmp) / "old.db", Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        with engine.begin() as con:
            for ddl in _OLD_TABLES:
                con.execute(sa.text(ddl))
            con.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PRIOR}')"))
        _to_attempt(url)
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        got, want = _shape(old), _shape(fresh)
        assert tuple(c[0] for c in got[0]) == COLUMNS, got[0]
        assert got == want, (got, want)
        assert want[1]["uq_ai_decisions_turn"] == (1, ("account_id", "fan_id", "mode", "trigger_key")), want[1]
        assert want[1]["ix_ai_decisions_fan_time"] == (0, ("account_id", "fan_id", "created_at")), want[1]
        assert want[1]["ix_ai_decisions_acct_mode_time"] == (0, ("account_id", "mode", "created_at")), want[1]
        assert want[1][OFFER_INDEX] == (1, ("account_id", "offer_message_id")), want[1]
        assert _partial(old) and _partial(fresh)

        _alembic(url, command.stamp, PRIOR)
        _to_attempt(url)
        assert _shape(old) == want

        _alembic(url, command.downgrade, BEFORE_ATTEMPT)
        _alembic(url, command.stamp, OFFERS)
        _alembic(url, command.downgrade, PRIOR)
        assert TABLE not in sa.inspect(engine).get_table_names()
        engine.dispose()
        full.dispose()


def case_single_head():
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()
    assert len(heads) == 1 and REV in {r.revision for r in script.iterate_revisions(heads[0], PRIOR)}, heads
    assert TEST_CHAT in {r.revision for r in script.iterate_revisions(heads[0], PRIOR)}, heads
    assert script.get_revision(TEST_CHAT).down_revision == BEFORE_TEST_CHAT


def case_0119_adds_nullable_columns():
    with tempfile.TemporaryDirectory(prefix="full_ai_migration_") as tmp:
        old = Path(tmp) / "old.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        with engine.begin() as con:
            for ddl in _OLD_TABLES:
                con.execute(sa.text(ddl))
            con.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PRIOR}')"))
        _alembic(url, command.upgrade, BEFORE_TEST_CHAT)
        for table, col in NEW_COLUMNS:
            assert col not in _cols(old, table), (table, col)
        _alembic(url, command.upgrade, TEST_CHAT)
        for table, col in NEW_COLUMNS:
            assert _cols(old, table)[col] == ("TEXT", 0), (table, _cols(old, table))
        _alembic(url, command.stamp, BEFORE_TEST_CHAT)
        _alembic(url, command.upgrade, TEST_CHAT)
        _alembic(url, command.downgrade, BEFORE_TEST_CHAT)
        for table, col in NEW_COLUMNS:
            assert col not in _cols(old, table), (table, col)
        engine.dispose()


def case_init_db_adds_0119_columns():
    import asyncio

    from db.engine import init_db
    path = _harness.DB_PATH
    con = sqlite3.connect(path)
    try:
        for table, col in NEW_COLUMNS:
            con.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        con.commit()
    finally:
        con.close()
    for table, col in NEW_COLUMNS:
        assert col not in _cols(path, table)
    asyncio.run(init_db())
    for table, col in NEW_COLUMNS:
        assert _cols(path, table)[col] == ("TEXT", 0), (table, _cols(path, table))


def case_init_db_creates_it():
    import asyncio

    from db.engine import init_db
    path = _harness.DB_PATH
    con = sqlite3.connect(path)
    try:
        assert con.execute("SELECT COUNT(*) FROM alembic_version").fetchone()[0] == 1
        con.execute(f"DROP TABLE {TABLE}")
        con.commit()
    finally:
        con.close()
    asyncio.run(init_db())
    cols, idx = _shape(path)
    assert tuple(c[0] for c in cols) == COLUMNS, cols
    assert idx["uq_ai_decisions_turn"] == (1, ("account_id", "fan_id", "mode", "trigger_key")), idx
    assert idx["ix_ai_decisions_fan_time"] == (0, ("account_id", "fan_id", "created_at")), idx
    assert idx["ix_ai_decisions_acct_mode_time"] == (0, ("account_id", "mode", "created_at")), idx
    con = sqlite3.connect(path)
    try:
        con.execute("DROP INDEX ix_ai_decisions_acct_mode_time")
        con.commit()
    finally:
        con.close()
    asyncio.run(init_db())
    assert _shape(path)[1]["ix_ai_decisions_acct_mode_time"] == (0, ("account_id", "mode", "created_at"))


def case_duplicate_turn_key_refused():
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        con.execute("INSERT OR IGNORE INTO accounts (id, is_active_default, created_at) "
                    "VALUES ('dup_acct', 0, CURRENT_TIMESTAMP)")
        row = ("INSERT INTO ai_decisions (account_id, fan_id, mode, trigger_kind, trigger_key, route, "
               "heat, route_row, question_version, status, created_at, updated_at) VALUES "
               "('dup_acct', 7, 'shadow', 'inbound', '101', 'chat', 1, 'otherwise', 'v', 'planned', "
               "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        con.execute(row)
        try:
            con.execute(row)
        except sqlite3.IntegrityError as e:
            assert "UNIQUE" in str(e), e
        else:
            raise AssertionError("a second row on one Turn key was accepted")
        con.execute(row.replace("'shadow'", "'test'"))
    finally:
        con.close()

def _old_db(tmp, rev: str):
    old = Path(tmp) / "old.db"
    url = f"sqlite:///{old}"
    engine = sa.create_engine(url)
    with engine.begin() as con:
        for ddl in _OLD_TABLES:
            con.execute(sa.text(ddl))
        con.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PRIOR}')"))
    _alembic(url, command.upgrade, rev)
    return old, url, engine


def case_0120_adds_offer_columns():
    with tempfile.TemporaryDirectory(prefix="full_ai_migration_") as tmp:
        old, url, engine = _old_db(tmp, TEST_CHAT)
        assert not set(OFFER_COLUMNS) & set(_cols(old, TABLE))
        assert OFFER_INDEX not in _shape(old)[1]
        _alembic(url, command.upgrade, OFFERS)
        cols = _cols(old, TABLE)
        assert {c: cols[c] for c in OFFER_COLUMNS} == {c: (t, 0) for c, t in OFFER_COLUMNS.items()}, cols
        assert _shape(old)[1][OFFER_INDEX] == (1, ("account_id", "offer_message_id"))
        assert _partial(old)
        before = _shape(old)
        _alembic(url, command.stamp, TEST_CHAT)
        _alembic(url, command.upgrade, OFFERS)
        assert _shape(old) == before
        _alembic(url, command.downgrade, TEST_CHAT)
        assert not set(OFFER_COLUMNS) & set(_cols(old, TABLE))
        assert OFFER_INDEX not in _shape(old)[1]
        assert "reply_json" in _cols(old, TABLE)
        engine.dispose()


def case_init_db_adds_0120():
    import asyncio

    from db.engine import init_db
    path = _harness.DB_PATH
    con = sqlite3.connect(path)
    try:
        con.execute(f"DROP INDEX {OFFER_INDEX}")
        for col in OFFER_COLUMNS:
            con.execute(f"ALTER TABLE {TABLE} DROP COLUMN {col}")
        con.commit()
    finally:
        con.close()
    assert not set(OFFER_COLUMNS) & set(_cols(path, TABLE))
    asyncio.run(init_db())
    cols = _cols(path, TABLE)
    assert {c: cols[c][1] for c in OFFER_COLUMNS} == dict.fromkeys(OFFER_COLUMNS, 0), cols
    assert _shape(path)[1][OFFER_INDEX] == (1, ("account_id", "offer_message_id"))
    assert _partial(path)


def case_duplicate_offer_message_refused():
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        con.execute("INSERT OR IGNORE INTO accounts (id, is_active_default, created_at) "
                    "VALUES ('offer_acct', 0, CURRENT_TIMESTAMP)")
        row = ("INSERT INTO ai_decisions (account_id, fan_id, mode, trigger_kind, trigger_key, route, "
               "heat, route_row, question_version, status, offer_message_id, created_at, updated_at) "
               "VALUES ('offer_acct', 7, 'test', 'test', '{key}', 'sell_now', 1, 'sell', 'v', 'sent', "
               "{mid}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        con.execute(row.format(key="t1", mid="NULL"))
        con.execute(row.format(key="t2", mid="NULL"))
        con.execute(row.format(key="t3", mid="555"))
        try:
            con.execute(row.format(key="t4", mid="555"))
        except sqlite3.IntegrityError as e:
            assert "UNIQUE" in str(e), e
        else:
            raise AssertionError("a second row on one offer_message_id was accepted")
        con.execute(row.format(key="t5", mid="556"))
    finally:
        con.close()


def case_head_is_0120():
    script = ScriptDirectory.from_config(_cfg())
    assert len(script.get_heads()) == 1, script.get_heads()
    assert script.get_revision(OFFERS).down_revision == TEST_CHAT


def case_0130_adds_offer_attempt_at():
    with tempfile.TemporaryDirectory(prefix="full_ai_migration_") as tmp:
        old, url, engine = _old_db(tmp, OFFERS)
        _alembic(url, command.stamp, BEFORE_ATTEMPT)
        assert "offer_attempt_at" not in _cols(old, TABLE)
        _alembic(url, command.upgrade, ATTEMPT)
        assert _cols(old, TABLE)["offer_attempt_at"] == ("DATETIME", 0), _cols(old, TABLE)
        before = _shape(old)
        _alembic(url, command.stamp, BEFORE_ATTEMPT)
        _alembic(url, command.upgrade, ATTEMPT)
        assert _shape(old) == before
        _alembic(url, command.downgrade, BEFORE_ATTEMPT)
        assert "offer_attempt_at" not in _cols(old, TABLE)
        assert "join_src" in _cols(old, TABLE)
        engine.dispose()
    assert ScriptDirectory.from_config(_cfg()).get_revision(ATTEMPT).down_revision == BEFORE_ATTEMPT


LEGACY = ((1, "live", "sending", 1000, None, None, True),
          (2, "live", "sent", 1000, None, None, True),
          (3, "live", "unconfirmed", 1000, None, None, True),
          (4, "live", "sent", 1000, 555, None, False),
          (5, "live", "no_send", 1000, None, None, False),
          (6, "live", "sent", None, None, None, False),
          (7, "test", "sent", 1000, None, None, False),
          (8, "live", "sent", 0, None, None, False),
          (9, "live", "sent", 1000, None, "bought", False))
LEGACY_MEDIA = 7401
ATTEMPT_MARKER = "20261122_full_ai_offer_attempt"


def _seed_legacy(con, acct: str, at: str, rows=LEGACY) -> None:
    for fan, mode, status, price, mid, outcome, _ in rows:
        con.execute(sa.text(
            "INSERT INTO ai_decisions (account_id, fan_id, mode, trigger_kind, trigger_key, route, heat, "
            "route_row, question_version, status, created_at, updated_at, offer_price_cents, offer_media_json, "
            "offer_message_id, outcome) VALUES (:a, :f, :m, 'inbound', :k, 'sell_now', 2, 'sell', 'v', :s, :t, :t, "
            ":p, :media, :mid, :o)"),
            {"a": acct, "f": fan, "m": mode, "k": str(100 + fan), "s": status, "t": at, "p": price,
             "media": f'{{"locked": [{LEGACY_MEDIA}], "previews": []}}', "mid": mid, "o": outcome})


def _attempts(con, acct: str) -> dict[int, object]:
    return dict(con.execute(sa.text("SELECT fan_id, offer_attempt_at FROM ai_decisions WHERE account_id = :a"),
                            {"a": acct}).all())


def _want(at: str, rows=LEGACY) -> dict[int, object]:
    return {fan: at if stamped else None for fan, *_, stamped in rows}


def case_0130_marks_legacy_attempts():
    at = "2026-11-20 10:00:00.000000"
    with tempfile.TemporaryDirectory(prefix="full_ai_migration_") as tmp:
        old, url, engine = _old_db(tmp, OFFERS)
        _alembic(url, command.stamp, BEFORE_ATTEMPT)
        with engine.begin() as con:
            _seed_legacy(con, "legacy", at)
        _alembic(url, command.upgrade, ATTEMPT)
        with engine.begin() as con:
            got = _attempts(con, "legacy")
            _seed_legacy(con, "later", at, LEGACY[:1])
        assert got == _want(at), got
        _alembic(url, command.stamp, BEFORE_ATTEMPT)
        _alembic(url, command.upgrade, ATTEMPT)
        with engine.begin() as con:
            assert _attempts(con, "later") == {1: None}, _attempts(con, "later")
        engine.dispose()


def case_init_db_marks_legacy_attempts_once():
    import asyncio
    from datetime import datetime, timedelta

    from automations import full_ai_live, full_ai_settle
    from db.engine import get_session, init_db
    from db.models import Message

    acct, created = "legacy_boot", datetime.utcnow().replace(microsecond=0) - timedelta(hours=1)
    at = created.strftime("%Y-%m-%d %H:%M:%S.%f")
    engine = sa.create_engine(f"sqlite:///{_harness.DB_PATH}")
    with engine.begin() as con:
        con.execute(sa.text("INSERT OR IGNORE INTO accounts (id, is_active_default, created_at) "
                            "VALUES (:a, 0, CURRENT_TIMESTAMP)"), {"a": acct})
        con.execute(sa.text("DELETE FROM data_migrations WHERE name = :n"), {"n": ATTEMPT_MARKER})
        _seed_legacy(con, acct, at)
        con.execute(sa.text("ALTER TABLE ai_decisions DROP COLUMN offer_attempt_at"))
    asyncio.run(init_db())
    with engine.begin() as con:
        got = _attempts(con, acct)
        _seed_legacy(con, "legacy_boot_2", at, LEGACY[:1])
    stamped = {f: v is not None for f, v in got.items()}
    assert stamped == {f: s for f, *_, s in LEGACY}, got

    async def after_boot():
        reaped = await full_ai_live.reap(acct)
        async with get_session() as s:
            s.add(Message(account_id=acct, fan_id=2, message_id=974_001, direction="out", body="for u",
                          created_at=created + timedelta(seconds=5), price_cents=1000,
                          media_ids=f"[{LEGACY_MEDIA}]", media_count=1))
        return reaped, await full_ai_settle.settle_pull(acct, 2)

    reaped, settled = asyncio.run(after_boot())
    asyncio.run(init_db())
    with engine.begin() as con:
        kept = con.execute(sa.text("SELECT status, offer_price_cents FROM ai_decisions WHERE account_id = :a "
                                   "AND fan_id = 1"), {"a": acct}).one()
        linked = con.execute(sa.text("SELECT offer_message_id FROM ai_decisions WHERE account_id = :a "
                                     "AND fan_id = 2"), {"a": acct}).scalar()
        again = _attempts(con, "legacy_boot_2")
        con.execute(sa.text("DELETE FROM data_migrations WHERE name = :n"), {"n": ATTEMPT_MARKER})
    asyncio.run(init_db())
    with engine.begin() as con:
        dev = _attempts(con, "legacy_boot_2")
        marked = con.execute(sa.text("SELECT 1 FROM data_migrations WHERE name = :n"),
                             {"n": ATTEMPT_MARKER}).first() is not None
    engine.dispose()
    assert (reaped, tuple(kept)) == (1, ("unconfirmed", 1000)), (reaped, kept)
    assert (settled, linked) == (1, 974_001), (settled, linked)
    assert again == {1: None}, again
    assert (dev, marked) == ({1: None}, True), (dev, marked)


_harness.run()
