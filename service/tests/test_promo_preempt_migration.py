#!/usr/bin/env python3
from __future__ import annotations

import _harness

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
PREV, REV = "0125_promo_campaign_expiry", "0126_promo_preempt"
TABLES = ("promo_create_reservations", "promo_keep_state")
COLS = ("recreates_left", "keep_host_id", "keep_warning", "keep_warning_at", "keep_ticked_at", "preempt")


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def _shape(path) -> dict:
    con = sqlite3.connect(path)
    try:
        out = {}
        for t in ("promo_campaigns", *TABLES):
            cols = tuple(sorted(tuple(r[1:]) for r in con.execute(f"PRAGMA table_info({t})")))
            idx = tuple(sorted(" ".join(r[0].split()) for r in con.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (t,))))
            out[t] = (cols, idx)
        return out
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


def case_rv_c04_upgrade_dedupes_legacy_double_kept_and_downgrade():
    with tempfile.TemporaryDirectory(prefix="promo_preempt_migration_") as tmp:
        old, fresh = Path(tmp) / "old.db", Path(tmp) / "fresh.db"
        url = f"sqlite:///{old}"
        engine = sa.create_engine(url)
        Base.metadata.create_all(engine)
        with engine.begin() as con:
            for t in TABLES:
                con.execute(sa.text(f"DROP TABLE {t}"))
            con.execute(sa.text("DROP INDEX uq_promo_keep_one"))
            for c in COLS:
                con.execute(sa.text(f"ALTER TABLE promo_campaigns DROP COLUMN {c}"))
            con.execute(sa.text("PRAGMA foreign_keys=OFF"))
            con.execute(sa.text(
                "INSERT INTO promo_campaigns (account_id, name, discount_percent, price_cents, subscribe_counts, "
                "subscribe_days, promo_type, status, subscriber_count, auto_reactivate, reactivate_count, "
                "created_at) VALUES ('a1', 'P', 50, 0, 10, 0, 'all', 'active', 0, 1, 0, '2026-11-19')"))
            for name, made in (("D1", "2026-11-01"), ("D3", "2026-11-03"), ("D2", "2026-11-02")):
                con.execute(sa.text(
                    "INSERT INTO promo_campaigns (account_id, name, discount_percent, price_cents, "
                    "subscribe_counts, subscribe_days, promo_type, status, subscriber_count, auto_reactivate, "
                    "reactivate_count, created_at) VALUES ('a2', :n, 50, 0, 10, 0, 'all', 'active', 0, 1, 0, :c)"),
                    {"n": name, "c": made})
        _alembic(url, command.stamp, PREV)
        _alembic(url, command.upgrade, REV)
        full = sa.create_engine(f"sqlite:///{fresh}")
        Base.metadata.create_all(full)
        assert _shape(old) == _shape(fresh), (_shape(old), _shape(fresh))
        assert any("uq_promo_create_open" in i and "WHERE state IN" in i
                   for i in _shape(old)["promo_create_reservations"][1]), _shape(old)
        with engine.connect() as con:
            assert con.execute(sa.text(
                "SELECT name, recreates_left, keep_host_id, keep_warning, keep_ticked_at, preempt FROM promo_campaigns "
                "WHERE account_id = 'a1'")).all() == [("P", None, None, None, None, 1)]
            dup = con.execute(sa.text(
                "SELECT name, auto_reactivate, keep_warning, keep_warning_at IS NOT NULL FROM promo_campaigns "
                "WHERE account_id = 'a2' ORDER BY name")).all()
            assert dup == [("D1", 0, "kept_duplicate", 1), ("D2", 0, "kept_duplicate", 1),
                           ("D3", 1, None, 0)], dup
        try:
            with engine.begin() as con:
                con.execute(sa.text("UPDATE promo_campaigns SET auto_reactivate = 1 WHERE name = 'D1'"))
        except sa.exc.IntegrityError:
            pass
        else:
            raise AssertionError("a second Kept campaign for one Creator must be refused")
        with engine.begin() as con:
            ins = ("INSERT INTO promo_create_reservations (account_id, source, state, terms_json, created_at) "
                   "VALUES ('a1', 'auto_ended', :st, '{}', '2026-11-19')")
            for st in ("created", "failed", "pending"):
                con.execute(sa.text(ins), {"st": st})
        try:
            with engine.begin() as con:
                con.execute(sa.text(ins), {"st": "unknown"})
        except sa.exc.IntegrityError:
            pass
        else:
            raise AssertionError("a second open reservation for one Creator must be refused")
        _alembic(url, command.upgrade, REV)
        assert _shape(old) == _shape(fresh)
        _alembic(url, command.downgrade, PREV)
        insp = sa.inspect(engine)
        assert not set(TABLES) & set(insp.get_table_names())
        assert not set(COLS) & {c["name"] for c in insp.get_columns("promo_campaigns")}
        assert "uq_promo_keep_one" not in {i["name"] for i in insp.get_indexes("promo_campaigns")}
        with engine.connect() as con:
            assert con.execute(sa.text("SELECT name FROM promo_campaigns WHERE account_id = 'a1'")).all() == [("P",)]
        with engine.begin() as con:
            con.execute(sa.text("ALTER TABLE promo_campaigns ADD COLUMN keep_host_id VARCHAR"))
        _alembic(url, command.upgrade, REV)
        assert _shape(old) == _shape(fresh)
        engine.dispose()
        full.dispose()


def case_rv_c04_init_db_catchup_dedupes_double_kept():
    import asyncio
    _harness.bootstrap()
    from db.engine import init_db
    con = sqlite3.connect(str(_harness.DB_PATH))
    try:
        con.execute("DROP INDEX uq_promo_keep_one")
        con.execute("PRAGMA foreign_keys=OFF")
        for name, ticked in (("K1", "2026-11-05"), ("K2", "2026-11-06")):
            con.execute(
                "INSERT INTO promo_campaigns (account_id, name, discount_percent, price_cents, subscribe_counts, "
                "subscribe_days, promo_type, status, subscriber_count, auto_reactivate, reactivate_count, "
                "created_at, keep_ticked_at, preempt) VALUES ('b1', ?, 50, 0, 10, 0, 'all', 'active', 0, 1, 0, "
                "'2026-11-01', ?, 1)", (name, ticked))
        con.commit()
    finally:
        con.close()
    asyncio.run(init_db())
    con = sqlite3.connect(str(_harness.DB_PATH))
    try:
        got = con.execute("SELECT name, auto_reactivate, keep_warning FROM promo_campaigns "
                          "WHERE account_id = 'b1' ORDER BY name").fetchall()
        idx = {r[1] for r in con.execute("PRAGMA index_list(promo_campaigns)")}
    finally:
        con.close()
    assert got == [("K1", 0, "kept_duplicate"), ("K2", 1, None)], got
    assert "uq_promo_keep_one" in idx, idx


_harness.run()
