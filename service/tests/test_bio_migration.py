#!/usr/bin/env python3
"""Bio migration matches create_all on temp SQLite and drops its five tables."""
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

BIO = {"bio_profiles", "bio_links", "bio_custom_domains", "bio_spare_domains", "bio_daily"}
MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
LATER = {"background_image"}  # bio_profiles column of 0122 (test_bio_background_migration.py)


def _shape(path):
    con = sqlite3.connect(path)
    try:
        return {t: (tuple(r[1] for r in con.execute(f"PRAGMA table_info({t})") if r[1] not in LATER),
                    tuple(sorted(r[1] for r in con.execute(f"PRAGMA index_list({t})")))) for t in BIO}
    finally:
        con.close()


def case_upgrade_and_downgrade():
    with tempfile.TemporaryDirectory(prefix="bio_migration_") as tmp:
        old = Path(tmp) / "old.db"
        fresh = Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        with engine.begin() as con:
            con.execute(sa.text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
            con.execute(sa.text("CREATE TABLE accounts (id VARCHAR PRIMARY KEY)"))
            con.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)"))
            con.execute(sa.text("INSERT INTO alembic_version VALUES ('0114_tracking_click_labels')"))
        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS))
        prior = os.environ["CHATTERLY_DB_URL"]
        os.environ["CHATTERLY_DB_URL"] = url
        try:
            command.upgrade(cfg, "0115_bio_pages")
        finally:
            os.environ["CHATTERLY_DB_URL"] = prior
        assert set(sa.inspect(engine).get_table_names()) >= BIO
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        assert _shape(old) == _shape(fresh)
        os.environ["CHATTERLY_DB_URL"] = url
        try:
            command.downgrade(cfg, "0114_tracking_click_labels")
        finally:
            os.environ["CHATTERLY_DB_URL"] = prior
        assert not (set(sa.inspect(engine).get_table_names()) & BIO)
        engine.dispose()
        full.dispose()


_harness.run()
