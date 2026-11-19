#!/usr/bin/env python3
"""promo_campaigns.finish_days + expires_at migration (0125) matches create_all on temp SQLite, keeps rows,
is idempotent (inspector guard), downgrades, and is the one head."""
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
PREV, REV = "0124_vault_account_settings", "0125_promo_campaign_expiry"
NEW = ("finish_days", "expires_at")


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def _cols(path) -> tuple:
    con = sqlite3.connect(path)
    try:
        return tuple(sorted((r[1], r[2], r[3], r[4]) for r in con.execute("PRAGMA table_info(promo_campaigns)")))
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
    heads = script.get_heads()
    assert len(heads) == 1 and REV in {r.revision for r in script.iterate_revisions(heads[0], PREV)}, heads
    assert script.get_revision(REV).down_revision == PREV


def case_upgrade_and_downgrade():
    with tempfile.TemporaryDirectory(prefix="promo_expiry_migration_") as tmp:
        old, fresh = Path(tmp) / "old.db", Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        Base.metadata.create_all(engine)   # today's schema, then back to 0124's promo_campaigns
        with engine.begin() as con:
            for c in NEW:
                con.execute(sa.text(f"ALTER TABLE promo_campaigns DROP COLUMN {c}"))
            con.execute(sa.text("PRAGMA foreign_keys=OFF"))
            con.execute(sa.text(
                "INSERT INTO promo_campaigns (account_id, name, discount_percent, price_cents, subscribe_counts, "
                "subscribe_days, promo_type, status, subscriber_count, auto_reactivate, reactivate_count, "
                "created_at) VALUES ('a1', 'P', 50, 0, 10, 0, 'all', 'active', 0, 1, 0, '2026-11-19')"))
        _alembic(url, command.stamp, PREV)
        _alembic(url, command.upgrade, REV)
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        assert _cols(old) == _cols(fresh) and set(NEW) <= {c[0] for c in _cols(old)}, (_cols(old),)
        with engine.connect() as con:
            assert con.execute(sa.text(
                "SELECT name, finish_days, expires_at FROM promo_campaigns")).all() == [("P", None, None)]
        _alembic(url, command.downgrade, PREV)
        assert not set(NEW) & {c["name"] for c in sa.inspect(engine).get_columns("promo_campaigns")}
        with engine.connect() as con:
            assert con.execute(sa.text("SELECT name FROM promo_campaigns")).all() == [("P",)]
        # Inspector guard: one column already there (init_db catch-up) still upgrades cleanly.
        with engine.begin() as con:
            con.execute(sa.text("ALTER TABLE promo_campaigns ADD COLUMN finish_days INTEGER"))
        _alembic(url, command.upgrade, REV)
        assert _cols(old) == _cols(fresh)
        engine.dispose()
        full.dispose()


_harness.run()
