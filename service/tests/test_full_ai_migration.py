#!/usr/bin/env python3
"""test_full_ai_migration — `ai_decisions` (the Decision ledger) reaches every box.

  case_upgrade_matches_create_all   0116 -> 0120 on a temp SQLite gives the
                                    columns and indexes `create_all` gives;
                                    a second upgrade over it is a no-op;
                                    downgrade drops the table
  case_single_head                  alembic has one head, 0117 and 0119 on its line
  case_0119_adds_nullable_columns   0118 -> 0119 adds ai_decisions.reply_json and
                                    account_ai_config.full_ai_config_json, both
                                    nullable TEXT; again = no-op; downgrade drops them
  case_init_db_adds_0119_columns    init_db's column catch-up adds both to an old DB
  case_init_db_creates_it           init_db on an existing copy (alembic
                                    version, no table) creates it with the
                                    UNIQUE Turn key and both indexes; an existing
                                    table missing acct_mode_time gets it (catch-up)
  case_duplicate_turn_key_refused   a second row on (account, fan, mode,
                                    trigger_key) is refused by the DB
  case_0120_adds_offer_columns      0119 -> 0120 adds the 8 nullable Offer columns and the
                                    partial UNIQUE (account_id, offer_message_id); again =
                                    no-op; downgrade drops them
  case_init_db_adds_0120            init_db's catch-up adds the Offer columns and the index
  case_duplicate_offer_message_refused  a second row on (account, offer_message_id) is
                                    refused; NULL offer_message_id never clashes
  case_head_is_0120                 one head; 0120_full_ai_offers sits on 0119

Run: ./venv/bin/python service/tests/test_full_ai_migration.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first: temp DB env guard

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
OFFER_COLUMNS = {"offer_price_cents": "INTEGER", "offer_list_cents": "INTEGER",
                 "offer_media_json": "TEXT", "offer_item_ref": "TEXT", "offer_message_id": "BIGINT",
                 "outcome": "VARCHAR", "outcome_at": "DATETIME", "join_src": "VARCHAR"}
MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
COLUMNS = ("id", "account_id", "fan_id", "mode", "trigger_kind", "trigger_key", "parent_id",
           "anchor_message_id", "anchor_created_at", "arm", "salt_ver", "route", "heat",
           "route_row", "question_version", "router_model", "writer_model", "jev_json",
           "jev_ms", "jev_error", "status", "created_at", "updated_at", "reply_json",
           *OFFER_COLUMNS)


# The tables 0116 -> 0119 alter besides ai_decisions, at their pre-0117 minimum.
_OLD_TABLES = ("CREATE TABLE accounts (id VARCHAR PRIMARY KEY)",
               "CREATE TABLE users (id VARCHAR PRIMARY KEY)",
               "CREATE TABLE actions (id INTEGER PRIMARY KEY)",
               "CREATE TABLE account_ai_config (account_id VARCHAR PRIMARY KEY)",
               "CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)")


def _cols(path, table) -> dict[str, tuple[str, int]]:
    """{column: (type, notnull)} of `table`."""
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
    """The Offer index is partial: its DDL carries the NOT NULL guard."""
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


def case_upgrade_matches_create_all():
    with tempfile.TemporaryDirectory(prefix="full_ai_migration_") as tmp:
        old, fresh = Path(tmp) / "old.db", Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        with engine.begin() as con:
            for ddl in _OLD_TABLES:
                con.execute(sa.text(ddl))
            con.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PRIOR}')"))
        _alembic(url, command.upgrade, OFFERS)
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

        # Again over a table that is already there (a box init_db brought it to).
        _alembic(url, command.stamp, PRIOR)
        _alembic(url, command.upgrade, OFFERS)
        assert _shape(old) == want

        _alembic(url, command.downgrade, PRIOR)
        assert TABLE not in sa.inspect(engine).get_table_names()
        engine.dispose()
        full.dispose()


def case_single_head():
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()  # later revisions chain after REV; still one head, REV on its line
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
        _alembic(url, command.stamp, BEFORE_TEST_CHAT)     # again over columns already there
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
    # On a box whose table predates the index, init_db's index catch-up adds it.
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
        # Another mode on the same Turn is its own key.
        con.execute(row.replace("'shadow'", "'test'"))
    finally:
        con.close()

def _old_db(tmp, rev: str):
    """A pre-0117 SQLite box upgraded to `rev`: (path, url, engine)."""
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
        _alembic(url, command.stamp, TEST_CHAT)           # again over columns already there
        _alembic(url, command.upgrade, OFFERS)
        assert _shape(old) == before
        _alembic(url, command.downgrade, TEST_CHAT)
        assert not set(OFFER_COLUMNS) & set(_cols(old, TABLE))
        assert OFFER_INDEX not in _shape(old)[1]
        assert "reply_json" in _cols(old, TABLE)          # 0119's column stays
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
        con.execute(row.format(key="t2", mid="NULL"))     # NULLs never clash (every test row)
        con.execute(row.format(key="t3", mid="555"))
        try:
            con.execute(row.format(key="t4", mid="555"))
        except sqlite3.IntegrityError as e:
            assert "UNIQUE" in str(e), e
        else:
            raise AssertionError("a second row on one offer_message_id was accepted")
        con.execute(row.format(key="t5", mid="556"))       # another message id is its own key
    finally:
        con.close()


def case_head_is_0120():
    script = ScriptDirectory.from_config(_cfg())
    assert len(script.get_heads()) == 1, script.get_heads()  # later migrations chain after 0120
    assert script.get_revision(OFFERS).down_revision == TEST_CHAT


_harness.run()
