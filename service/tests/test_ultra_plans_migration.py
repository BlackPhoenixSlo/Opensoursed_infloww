#!/usr/bin/env python3
"""Ultra-plans migration (0121) matches create_all on temp SQLite, is idempotent, downgrades, and stays on the one head's line."""
from __future__ import annotations

import _harness  # MUST be first: temp DB env guard

import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from db.models import Base  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
PREV, REV = "0120_full_ai_offers", "0121_ultra_plans"


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def _shape(path):
    con = sqlite3.connect(path)
    try:
        cols = tuple((r[1], r[2], r[3]) for r in con.execute("PRAGMA table_info(ultra_plans)"))
        idx = tuple(sorted(r[1] for r in con.execute("PRAGMA index_list(ultra_plans)")))
        return cols, idx
    finally:
        con.close()


def _alembic(url: str, fn, rev: str) -> None:
    prior = os.environ["CHATTERLY_DB_URL"]
    os.environ["CHATTERLY_DB_URL"] = url
    try:
        fn(_cfg(), rev)
    finally:
        os.environ["CHATTERLY_DB_URL"] = prior


def case_single_head():
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()  # later revisions chain after REV; still one head, REV on its line
    assert len(heads) == 1 and REV in {r.revision for r in script.iterate_revisions(heads[0], PREV)}, heads


def case_upgrade_and_downgrade():
    with tempfile.TemporaryDirectory(prefix="ultra_plans_migration_") as tmp:
        old, fresh = Path(tmp) / "old.db", Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        with engine.begin() as con:
            con.execute(sa.text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
            con.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)"))
            con.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PREV}')"))
        _alembic(url, command.upgrade, REV)
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        got, want = _shape(old), _shape(fresh)
        assert got == want and got[0], (got, want)
        _alembic(url, command.downgrade, PREV)
        assert "ultra_plans" not in sa.inspect(engine).get_table_names()
        # Inspector guard: a DB that create_all already brought up upgrades without error.
        with engine.begin() as con:
            con.execute(sa.text("DROP TABLE users"))
        Base.metadata.create_all(engine)
        _alembic(url, command.upgrade, REV)
        assert _shape(old) == want
        engine.dispose()
        full.dispose()


_harness.run()
