#!/usr/bin/env python3
"""Keep running rules heal (0129, owner 2026-11-21): each account with a Kept campaign ends
with exactly one enabled live promo_reactivate rule — a missing one created, a disabled /
dry-run one fixed (its queued job runs live too), enabled duplicates parked (their pending jobs cancelled); accounts with
no Kept campaign untouched. Idempotent; downgrade no-op; on the one head's line; init_db
runs it once (data_migrations marker).

Run: ./venv/bin/python service/tests/test_keep_running_rules_heal_migration.py
"""
from __future__ import annotations

import _harness  # MUST be first: temp DB env guard

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from db.models import Account, Base  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
PREV, REV = "0126_promo_preempt", "0129_keep_running_rules_heal"
LIVE = {"dry_run": False, "cooldown_minutes": 2, "max_reactivations": 0}
EVERY = {"every_seconds": 3600}

META = {"_recheck": "first_read", "_expiry_retries": 1, "_followup": True}   # a queued job's own keys


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


def _campaign(con, aid: str, kept: int) -> None:
    con.execute(sa.text(
        "INSERT INTO promo_campaigns (account_id, name, discount_percent, price_cents, subscribe_counts, "
        "subscribe_days, promo_type, status, subscriber_count, auto_reactivate, reactivate_count, "
        "created_at, preempt) VALUES (:a, 'T', 100, 0, 10, 3, 'all', 'active', 0, :k, 0, '2026-11-19', 1)"),
        {"a": aid, "k": kept})


def _rule(con, aid: str, on: int, steps: dict, name: str = "old") -> int:
    return con.execute(sa.text(
        "INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, is_enabled, "
        "created_at) VALUES (:a, :n, 'promo_reactivate', '{}', :s, :on, '2026-11-01') RETURNING id"),
        {"a": aid, "n": name, "s": json.dumps(steps), "on": on}).scalar_one()


def _rules(con, aid: str) -> list[tuple]:
    return [(r[0], bool(r[1]), json.loads(r[2]), json.loads(r[3])) for r in con.execute(sa.text(
        "SELECT name, is_enabled, steps_json, trigger_json FROM automation_rules "
        "WHERE account_id = :a AND kind = 'promo_reactivate' ORDER BY id"), {"a": aid})]


def case_single_head():
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()
    assert len(heads) == 1 and REV in {r.revision for r in script.iterate_revisions(heads[0], PREV)}, heads
    assert script.get_revision(REV).down_revision == PREV


def case_upgrade_heals_rules_only_for_kept_accounts():
    with tempfile.TemporaryDirectory(prefix="keep_rules_heal_") as tmp:
        url = f"sqlite:///{Path(tmp) / 'db.db'}"
        engine = sa.create_engine(url)
        Base.metadata.create_all(engine)
        with Session(engine) as s, s.begin():
            s.add_all([Account(id=aid) for aid in ("missing", "dry", "dupes", "unticked", "none")])
        with engine.begin() as con:
            _campaign(con, "missing", 1)                                    # ticked before #850: no rule
            _campaign(con, "dry", 1)
            _rule(con, "dry", 0, {"max_reactivations": 0, "dry_run": True})
            _campaign(con, "dupes", 1)
            _campaign(con, "dupes", 0)
            _rule(con, "dupes", 0, {"dry_run": True}, name="first")
            _rule(con, "dupes", 1, LIVE, name="second")
            third = _rule(con, "dupes", 1, LIVE, name="third")
            con.execute(sa.text(
                "INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts, rule_id, "
                "created_at) VALUES ('dupes', 'promo_reactivate', '{}', '2026-11-21', 'pending', 0, :r, "
                "'2026-11-21')"), {"r": third})
            dry = con.execute(sa.text("SELECT id FROM automation_rules WHERE account_id = 'dry'")).scalar_one()
            con.execute(sa.text(   # W30 F11: a job the dry-run rule already queued
                "INSERT INTO scheduled_jobs (account_id, kind, payload_json, run_at, status, attempts, rule_id, "
                "created_at) VALUES ('dry', 'promo_reactivate', :p, '2026-11-21', 'pending', 0, :r, "
                "'2026-11-21')"), {"r": dry, "p": json.dumps({"dry_run": True, **META})})
            _campaign(con, "unticked", 0)                                   # no Kept campaign: untouched
            _rule(con, "none", 0, {"dry_run": True})
        _alembic(url, command.stamp, PREV)
        _alembic(url, command.upgrade, REV)
        with engine.connect() as con:
            assert _rules(con, "missing") == [("Keep promos running", True, LIVE, EVERY)], _rules(con, "missing")
            assert _rules(con, "dry") == [("old", True, LIVE, EVERY)], _rules(con, "dry")
            assert _rules(con, "dupes") == [("first", True, LIVE, EVERY), ("second", False, LIVE, {}),
                                            ("third", False, LIVE, {})], _rules(con, "dupes")
            assert con.execute(sa.text(
                "SELECT status FROM scheduled_jobs WHERE account_id = 'dupes'")).scalar_one() == "cancelled"
            queued = con.execute(sa.text("SELECT status, payload_json FROM scheduled_jobs "
                                         "WHERE account_id = 'dry'")).one()
            # runs live, not dry; W30 F23: its own keys (a Re-check's metadata) stay
            assert (queued[0], json.loads(queued[1])) == ("pending", {**LIVE, **META}), queued
            assert _rules(con, "unticked") == [], _rules(con, "unticked")
            assert _rules(con, "none") == [("old", False, {"dry_run": True}, {})], _rules(con, "none")
            before = con.execute(sa.text("SELECT * FROM automation_rules ORDER BY id")).all()
        _alembic(url, command.downgrade, PREV)      # no-op
        _alembic(url, command.upgrade, REV)         # idempotent
        with engine.connect() as con:
            assert con.execute(sa.text("SELECT * FROM automation_rules ORDER BY id")).all() == before
        engine.dispose()


def case_init_db_heals_once():
    """A box upgrades through init_db: the heal runs once (marker), so a rule the operator
    turns off later stays off."""
    import asyncio
    _harness.bootstrap()
    from db.engine import init_db
    engine = sa.create_engine(f"sqlite:///{_harness.DB_PATH}")
    with Session(engine) as s, s.begin():
        s.add(Account(id="boot1"))
    engine.dispose()
    con = sqlite3.connect(str(_harness.DB_PATH))
    try:
        con.execute("DELETE FROM data_migrations WHERE name = '20261121_keep_running_rules_heal'")
        con.execute(
            "INSERT INTO promo_campaigns (account_id, name, discount_percent, price_cents, subscribe_counts, "
            "subscribe_days, promo_type, status, subscriber_count, auto_reactivate, reactivate_count, "
            "created_at, preempt) VALUES ('boot1', 'T', 100, 0, 10, 3, 'all', 'active', 0, 1, 0, '2026-11-01', 1)")
        con.commit()
    finally:
        con.close()
    asyncio.run(init_db())
    con = sqlite3.connect(str(_harness.DB_PATH))
    try:
        got = con.execute("SELECT is_enabled, steps_json FROM automation_rules WHERE account_id = 'boot1' "
                          "AND kind = 'promo_reactivate'").fetchall()
        assert [(on, json.loads(s)) for on, s in got] == [(1, LIVE)], got
        con.execute("UPDATE automation_rules SET is_enabled = 0 WHERE account_id = 'boot1'")
        con.commit()
    finally:
        con.close()
    asyncio.run(init_db())
    con = sqlite3.connect(str(_harness.DB_PATH))
    try:
        assert con.execute("SELECT is_enabled FROM automation_rules WHERE account_id = 'boot1'").fetchall() == [(0,)]
    finally:
        con.close()


_harness.run()
