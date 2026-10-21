#!/usr/bin/env python3
"""
The indexes that keep `scheduled_jobs` / `automation_runs` answerable, and the
query plans that are the actual point of them.

WHAT WENT WRONG. `ix_jobs_due` leads on `run_at`, and every hot query here
bounds `run_at <= now` — an open range starting at the oldest row. So the
planner walked that index from the beginning of time and filtered status /
account_id / kind row by row. Harmless while the table held a dozen rows a day;
on 2026-08-12 the engines came on and it started taking ~20k/day. Measured
2026-08-25 against the live 1.5 GB DB (263,790 jobs, of which 316 were actually
pending or running):

    executor supervisor tick        6,767 ms   every 30 s
    GET /admin/automation-rules       754 ms   polled every 30 s
    GET /admin/stats/automation-runs 1,256 ms  polled every 60 s

and after the indexes below: 2.2 ms, 0.4 ms, 1.6 ms.

WHY THIS TEST IS ABOUT PLANS, NOT ABOUT EXISTENCE. An index that exists and is
not chosen buys nothing, and — the part that is easy to miss — ADDING one can
un-choose another. Measured on a snapshot while picking this set: shipping
`ix_runs_account_started` WITHOUT `ix_runs_account_kind_started` makes the
planner prefer it for `_last_run` too, which then walks the whole account
partition filtering kind. That is 0.2 ms → 156 ms for `_last_run` and 285 ms →
1,443 ms for the max_runs counter: FIVE TIMES WORSE than adding no index at
all. `case_last_run_keeps_its_kind_index` is that regression, pinned. A test
that only asserted `index in sqlite_master` would have passed happily through
it.

WHY IT DROPS THEM AND RE-RUNS init_db. There is no `alembic upgrade` in this
service (see db/engine.py) — a new index reaches an existing box exactly one
way, through the additive-INDEX catch-up in `init_db()`. A fresh harness DB
gets them from `create_all` instead, which is the path prod never takes. So the
test bootstraps, DROPs the five, and re-runs `init_db()`: that is a real
pre-change prod DB, built without duplicating a line of DDL.

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_automation_queue_indexes.py

Exit 0 = all pass.
"""
from __future__ import annotations

import _harness  # noqa: F401  # MUST be first — binds a throwaway DB (prod-fallback guard)

import asyncio
import sqlite3

_harness.bootstrap()

from db.engine import init_db  # noqa: E402

# The five this change adds. Each names the call site it exists for, because an
# index whose reason is not written down is an index nobody dares delete.
_NEW = {
    # _has_pending_job (automation_rules_api), _claim_due_job and
    # _materialize_due_rules' pending guard — all (account, kind, status) + a
    # run_at bound.
    "ix_jobs_account_kind_status_run": "scheduled_jobs",
    # _due_job_pairs — status-first, no account, once per supervisor tick.
    "ix_jobs_status_run": "scheduled_jobs",
    # The cadence anchor, `max(created_at) WHERE rule_id = ?`, which had no
    # usable index at all and full-scanned once per rule per tick.
    "ix_jobs_rule_created": "scheduled_jobs",
    # _last_run + the max_runs counter, both (account_id, kind).
    "ix_runs_account_kind_started": "automation_runs",
    # /admin/stats/automation-runs — clamp_account_filter turns the card's
    # unqualified call into `account_id IN (<every account you own>)`.
    "ix_runs_account_started": "automation_runs",
}

# Pre-existing, and deliberately kept: init_db()'s catch-up can CREATE a missing
# index but never DROPS a stale one, so removing either from the model would
# leave it on disk on every box that already has it while quietly changing the
# planner's menu on a fresh one. Two different schemas from one models.py is
# worse than one redundant index.
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
    """Rewind this DB to the shape prod was in before the change."""
    c = sqlite3.connect(_db_path())
    try:
        for name in _NEW:
            c.execute(f"DROP INDEX IF EXISTS {name}")
        c.commit()
    finally:
        c.close()


# ── cases ─────────────────────────────────────────────────────────────

def case_catch_up_creates_them_on_a_table_that_already_exists() -> None:
    """The only path by which a new index reaches a live box.

    `create_all` does NOT retroactively add indexes to a table it finds already
    present — it skips the table whole — so this is emphatically not the same
    assertion as "the model declares them".
    """
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
    """Relays restart constantly (deploys, autoheal). Boot must be idempotent."""
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
    """The plans, which are the actual deliverable.

    Each `sql` is the shape of a real call site, not an approximation of one.
    Equality-constrained leading columns decide these plans, so they hold on an
    empty table exactly as they do on 263k rows — which is why this suite needs
    no fixture data and stays fast.
    """
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
            "select account_id,kind from scheduled_jobs where status='pending' "
            "and run_at<=? group by account_id,kind",
            ("2026-09-01",),
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
    """The regression that shipping half this index set would cause.

    With `ix_runs_account_started` present but `ix_runs_account_kind_started`
    gone, the planner prefers the account-only index for `_last_run` and then
    walks that whole account's runs discarding the wrong kinds. Measured on a
    prod snapshot: `_last_run` 0.2 ms → 156 ms, max_runs counter 285 ms →
    1,443 ms — five times SLOWER than shipping no new index at all. The two must
    travel together; this case fails the moment they stop.
    """
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
