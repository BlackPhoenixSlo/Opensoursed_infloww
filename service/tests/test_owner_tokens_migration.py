#!/usr/bin/env python3
"""Owner-tokens migration (0118) matches create_all on temp SQLite, is idempotent, and downgrades."""
from __future__ import annotations

import _harness  # MUST be first: temp DB env guard

import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from db.models import Base  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
PREV, REV = "0117_full_ai_decisions", "0118_owner_tokens"


def _shape(path):
    con = sqlite3.connect(path)
    try:
        cols = tuple(r[1] for r in con.execute("PRAGMA table_info(owner_tokens)"))
        idx = tuple(sorted(r[1] for r in con.execute("PRAGMA index_list(owner_tokens)")))
        via = [r for r in con.execute("PRAGMA table_info(actions)") if r[1] == "via"]
        return cols, idx, [(r[1], r[2], r[3]) for r in via]
    finally:
        con.close()


def _alembic(url: str, fn, rev: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    prior = os.environ["CHATTERLY_DB_URL"]
    os.environ["CHATTERLY_DB_URL"] = url
    try:
        fn(cfg, rev)
    finally:
        os.environ["CHATTERLY_DB_URL"] = prior


def case_upgrade_and_downgrade():
    with tempfile.TemporaryDirectory(prefix="owner_tokens_migration_") as tmp:
        old, fresh = Path(tmp) / "old.db", Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        with engine.begin() as con:
            con.execute(sa.text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
            con.execute(sa.text("CREATE TABLE actions (id INTEGER PRIMARY KEY, action VARCHAR NOT NULL)"))
            con.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)"))
            con.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PREV}')"))
        _alembic(url, command.upgrade, REV)
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        got, want = _shape(old), _shape(fresh)
        assert got[0] == want[0] and got[1] == want[1], (got, want)
        assert got[2] == [("via", "VARCHAR", 0)] == want[2], (got[2], want[2])
        _alembic(url, command.downgrade, PREV)
        assert "owner_tokens" not in sa.inspect(engine).get_table_names()
        assert "via" not in {c["name"] for c in sa.inspect(engine).get_columns("actions")}
        # Inspector guard: a DB that create_all already brought up upgrades without error.
        with engine.begin() as con:
            con.execute(sa.text("DROP TABLE actions"))
            con.execute(sa.text("DROP TABLE users"))
        Base.metadata.create_all(engine)
        _alembic(url, command.upgrade, REV)
        assert _shape(old)[0] == want[0]
        engine.dispose()
        full.dispose()


_harness.run()
