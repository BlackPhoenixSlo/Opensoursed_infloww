#!/usr/bin/env python3
"""bio_profiles.background_image migration (0122) matches create_all on temp SQLite, keeps rows, is idempotent,
downgrades, and is the one head; the bio service reads a page before the relay has added the column (no 503)."""
from __future__ import annotations

import _harness  # MUST be first: temp DB env guard

import asyncio  # noqa: E402
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
BIO_REV, PREV, REV = "0115_bio_pages", "0121_ultra_plans", "0122_bio_profile_background"


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def _cols(path) -> tuple:
    con = sqlite3.connect(path)
    try:
        # sorted: ADD COLUMN appends, create_all places it after `avatar`
        return tuple(sorted((r[1], r[2], r[3], r[4]) for r in con.execute("PRAGMA table_info(bio_profiles)")))
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
    assert script.get_revision(REV).down_revision == PREV


def case_upgrade_and_downgrade():
    with tempfile.TemporaryDirectory(prefix="bio_background_migration_") as tmp:
        old, fresh = Path(tmp) / "old.db", Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        with engine.begin() as con:
            con.execute(sa.text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
            con.execute(sa.text("CREATE TABLE accounts (id VARCHAR PRIMARY KEY)"))
            con.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)"))
            con.execute(sa.text("INSERT INTO alembic_version VALUES ('0114_tracking_click_labels')"))
        _alembic(url, command.upgrade, BIO_REV)  # bio_profiles as 0115 made it
        with engine.begin() as con:
            con.execute(sa.text("INSERT INTO users VALUES ('u1')"))
            con.execute(sa.text("INSERT INTO bio_profiles (id, owner_user_id, username) VALUES ('p1', 'u1', 'alice')"))
        _alembic(url, command.stamp, PREV)
        _alembic(url, command.upgrade, REV)
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        assert _cols(old) == _cols(fresh) and "background_image" in {c[0] for c in _cols(old)}, (_cols(old),)
        with engine.connect() as con:
            assert con.execute(sa.text("SELECT username, background_image FROM bio_profiles")).all() == [("alice", "")]
        _alembic(url, command.downgrade, PREV)
        assert "background_image" not in {c["name"] for c in sa.inspect(engine).get_columns("bio_profiles")}
        with engine.connect() as con:
            assert con.execute(sa.text("SELECT username FROM bio_profiles")).all() == [("alice",)]
        # Inspector guard: a DB that already has the column (create_all / init_db catch-up) upgrades cleanly.
        with engine.begin() as con:
            con.execute(sa.text("ALTER TABLE bio_profiles ADD COLUMN background_image VARCHAR NOT NULL DEFAULT ''"))
        _alembic(url, command.upgrade, REV)
        assert _cols(old) == _cols(fresh)
        engine.dispose()
        full.dispose()


def case_bio_reads_before_the_column():
    """A deploy starts the bio service beside the relay; only the relay's init_db adds the column."""
    from bio_pages import store
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        con.execute("CREATE TABLE bio_profiles (id VARCHAR PRIMARY KEY, username VARCHAR, display_name VARCHAR, "
                    "bio VARCHAR, avatar VARCHAR, mode VARCHAR, verified BOOLEAN)")
        con.execute("CREATE TABLE bio_links (id VARCHAR PRIMARY KEY, profile_id VARCHAR, link_id VARCHAR, "
                    "title VARCHAR, default_tracking_code VARCHAR, mode VARCHAR, icon VARCHAR, "
                    "background_image VARCHAR, is_adult BOOLEAN, tracking BOOLEAN, bot_check BOOLEAN, "
                    "sort_order INTEGER)")
        con.execute("INSERT INTO bio_profiles VALUES ('p1', 'alice', 'Alice', '', 'a.webp', '', 0)")
        con.commit()
        page = asyncio.run(store.profile_with_links("alice"))
        assert page is not None and page[0]["background_image"] == "" and page[0]["avatar"] == "a.webp", page
        assert asyncio.run(store.profile_at("bob")) is None
        con.execute("ALTER TABLE bio_profiles ADD COLUMN background_image VARCHAR NOT NULL DEFAULT 'b.webp'")
        con.commit()
        assert asyncio.run(store.profile_at("alice"))["background_image"] == "b.webp"
    finally:
        con.close()


_harness.run()
