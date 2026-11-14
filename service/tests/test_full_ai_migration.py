#!/usr/bin/env python3
"""test_full_ai_migration — `ai_decisions` (the Decision ledger) reaches every box.

  case_upgrade_matches_create_all   0116 -> 0117 on a temp SQLite gives the
                                    columns and indexes `create_all` gives;
                                    a second upgrade over it is a no-op;
                                    downgrade drops the table
  case_single_head                  alembic has one head, 0117 on its line
  case_init_db_creates_it           init_db on an existing copy (alembic
                                    version, no table) creates it with the
                                    UNIQUE Turn key and both indexes; an existing
                                    table missing acct_mode_time gets it (catch-up)
  case_duplicate_turn_key_refused   a second row on (account, fan, mode,
                                    trigger_key) is refused by the DB

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
MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
COLUMNS = ("id", "account_id", "fan_id", "mode", "trigger_kind", "trigger_key", "parent_id",
           "anchor_message_id", "anchor_created_at", "arm", "salt_ver", "route", "heat",
           "route_row", "question_version", "router_model", "writer_model", "jev_json",
           "jev_ms", "jev_error", "status", "created_at", "updated_at")


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
            con.execute(sa.text("CREATE TABLE accounts (id VARCHAR PRIMARY KEY)"))
            con.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)"))
            con.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PRIOR}')"))
        _alembic(url, command.upgrade, REV)
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        got, want = _shape(old), _shape(fresh)
        assert tuple(c[0] for c in got[0]) == COLUMNS, got[0]
        assert got == want, (got, want)
        assert want[1]["uq_ai_decisions_turn"] == (1, ("account_id", "fan_id", "mode", "trigger_key")), want[1]
        assert want[1]["ix_ai_decisions_fan_time"] == (0, ("account_id", "fan_id", "created_at")), want[1]
        assert want[1]["ix_ai_decisions_acct_mode_time"] == (0, ("account_id", "mode", "created_at")), want[1]

        # Again over a table that is already there (a box init_db brought it to).
        _alembic(url, command.stamp, PRIOR)
        _alembic(url, command.upgrade, REV)
        assert _shape(old) == want

        _alembic(url, command.downgrade, PRIOR)
        assert TABLE not in sa.inspect(engine).get_table_names()
        engine.dispose()
        full.dispose()


def case_single_head():
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()  # later revisions chain after REV; still one head, REV on its line
    assert len(heads) == 1 and REV in {r.revision for r in script.iterate_revisions(heads[0], PRIOR)}, heads


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


_harness.run()
