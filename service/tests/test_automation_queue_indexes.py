#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401  # MUST be first — binds a throwaway DB (prod-fallback guard)

import asyncio
import sqlite3

_harness.bootstrap()

from db.engine import init_db  # noqa: E402

_NEW = {
    "ix_jobs_account_kind_status_run": "scheduled_jobs",
    "ix_jobs_status_run": "scheduled_jobs",
    "ix_jobs_rule_created": "scheduled_jobs",
    "ix_runs_account_kind_started": "automation_runs",
    "ix_runs_account_started": "automation_runs",
}

_KEPT = {"ix_jobs_due": "scheduled_jobs", "ix_runs_kind_started": "automation_runs"}


def _db_path() -> str:
    return str(_harness.DB_PATH)


def _indexes(table: str) -> set[str]:
    c = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
    try:
        return {r[1] for r in c.execute(f"pragma index_list({table})")}
    finally:
        c.close()


def _plan(sql: str, params: tuple = ()) -> str:
    c = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
    try:
        return " | ".join(r[3] for r in c.execute("explain query plan " + sql, params))
    finally:
        c.close()


def _drop_the_new_indexes() -> None:
    c = sqlite3.connect(_db_path())
    try:
        for name in _NEW:
            c.execute(f"DROP INDEX IF EXISTS {name}")
        c.commit()
    finally:
        c.close()



def case_catch_up_creates_them_on_a_table_that_already_exists() -> None:
    _drop_the_new_indexes()
    live = _indexes("scheduled_jobs") | _indexes("automation_runs")
    assert not (set(_NEW) & live), (
        f"setup failed — these survived the DROP: {sorted(set(_NEW) & live)}"
    )

    asyncio.run(init_db())

    for name, table in _NEW.items():
        assert name in _indexes(table), (
            f"{name} missing from {table} after init_db(). The additive-INDEX "
            f"catch-up in db/engine.py is what ships it; if that loop stopped "
            f"running, every deployed box silently keeps the slow plans."
        )


def case_a_second_boot_changes_nothing() -> None:
    before = _indexes("scheduled_jobs") | _indexes("automation_runs")
    asyncio.run(init_db())
    after = _indexes("scheduled_jobs") | _indexes("automation_runs")
    assert before == after, f"second init_db() changed the index set: {before ^ after}"


def case_the_old_indexes_are_not_disturbed() -> None:
    for name, table in _KEPT.items():
        assert name in _indexes(table), (
            f"{name} disappeared from {table}. Nothing here should drop it — "
            f"init_db() has no drop path, so losing it means the MODEL lost it."
        )


def case_every_hot_query_uses_its_index() -> None:
    checks = [
        (
            "_has_pending_job / _claim_due_job / _materialize_due_rules",
            "select id from scheduled_jobs where account_id=? and kind in (?) "
            "and status in ('pending','running') and run_at<=? limit 1",
            ("a", "k", "2026-09-01"),
            "ix_jobs_account_kind_status_run",
        ),
        (
            "_due_job_pairs",
            "select account_id,kind,max(case when created_by_employee_id is not null "
            "and created_by_employee_id != ? then 1 else 0 end) from scheduled_jobs "
            "where status='pending' and run_at<=? group by account_id,kind",
            (1, "2026-09-01"),
            "ix_jobs_status_run",
        ),
        (
            "_materialize_due_rules cadence anchor",
            "select max(created_at) from scheduled_jobs where rule_id=?",
            (1,),
            "ix_jobs_rule_created",
        ),
        (
            "_last_run",
            "select * from automation_runs where account_id=? and kind=? "
            "order by started_at desc limit 1",
            ("a", "k"),
            "ix_runs_account_kind_started",
        ),
        (
            "GET /admin/stats/automation-runs (account-filtered)",
            "select * from automation_runs where account_id in (?,?) "
            "order by started_at desc limit 200",
            ("a", "b"),
            "ix_runs_account_started",
        ),
    ]
    for label, sql, params, want in checks:
        plan = _plan(sql, params)
        assert want in plan, (
            f"{label} no longer uses {want}.\n  plan: {plan}\n"
            f"  An index that exists but is not CHOSEN buys nothing — this is "
            f"the assertion that matters, not index_list()."
        )
        assert "SCAN " not in plan, (
            f"{label} fell back to a table scan.\n  plan: {plan}"
        )


def case_last_run_keeps_its_kind_index() -> None:
    plan = _plan(
        "select * from automation_runs where account_id=? and kind=? "
        "order by started_at desc limit 1", ("a", "k"),
    )
    assert "ix_runs_account_started" not in plan, (
        "_last_run regressed onto the account-only index — it will now scan the "
        f"whole account partition filtering kind.\n  plan: {plan}"
    )
    plan_count = _plan(
        "select count(*) from automation_runs where account_id=? and kind=?", ("a", "k"),
    )
    assert "ix_runs_account_kind_started" in plan_count, (
        f"the max_runs counter lost its (account, kind) index.\n  plan: {plan_count}"
    )


_harness.run(
    case_catch_up_creates_them_on_a_table_that_already_exists,
    case_a_second_boot_changes_nothing,
    case_the_old_indexes_are_not_disturbed,
    case_every_hot_query_uses_its_index,
    case_last_run_keeps_its_kind_index,
)
