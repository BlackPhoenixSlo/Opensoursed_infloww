#!/usr/bin/env python3
"""Retention sweep for the append-only audit/log tables (server.evict_audit_logs_once).

automation_runs / grok_calls / scheduled_jobs(terminal) / actions had NO prune
and grew unbounded — creeping the DB back up after the raw-payload columns were
capped. This seeds OLD + RECENT rows in each, runs one sweep with a 7-day
window, and asserts:
  • OLD rows are deleted, RECENT rows survive,
  • scheduled_jobs deletes ONLY terminal (done/error) rows — pending/running stay,
  • a window of 0 disables that table entirely,
  • the returned per-table counts match.

Run: ./venv/bin/python service/tests/test_audit_retention.py   (exit 0 = green)
"""
import _harness  # MUST be first — sets sys.path / binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import server  # noqa: E402 — provides evict_audit_logs_once
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Action, AutomationRun, GrokCall, ScheduledJob,
)

_OLD = datetime.utcnow() - timedelta(days=30)      # well past any window
_RECENT = datetime.utcnow() - timedelta(hours=1)   # well inside every window
ACCT = "acct_test"


async def _reset_and_seed() -> None:
    async with get_session() as s:
        # scheduled_jobs FKs accounts → delete it before the Account row.
        for M in (AutomationRun, GrokCall, ScheduledJob, Action, Account):
            await s.execute(M.__table__.delete())
        s.add(Account(id=ACCT))
        for ts in (_OLD, _RECENT):
            s.add(AutomationRun(kind="gen_info", started_at=ts, status="ok"))
            s.add(GrokCall(purpose="gen_info", model="m", endpoint="/chat",
                           prompt_json="{}", called_at=ts))
            s.add(Action(action="send", at=ts))
        # scheduled_jobs: OLD terminal (deleted), OLD pending (KEPT — not terminal),
        # RECENT done (kept — inside window).
        s.add(ScheduledJob(account_id=ACCT, kind="x", payload_json="{}",
                           run_at=_OLD, status="done", created_at=_OLD))
        s.add(ScheduledJob(account_id=ACCT, kind="x", payload_json="{}",
                           run_at=_OLD, status="pending", created_at=_OLD))
        s.add(ScheduledJob(account_id=ACCT, kind="x", payload_json="{}",
                           run_at=_RECENT, status="done", created_at=_RECENT))
        await s.commit()


async def _count(model, *where) -> int:
    async with get_session() as s:
        stmt = select(func.count()).select_from(model)
        for w in where:
            stmt = stmt.where(w)
        return int((await s.execute(stmt)).scalar() or 0)


def _set_windows(seconds: int) -> None:
    server._AUTOMATION_RUNS_RETAIN_S = seconds
    server._GROK_CALLS_RETAIN_S = seconds
    server._SCHEDULED_JOBS_RETAIN_S = seconds
    server._ACTIONS_RETAIN_S = seconds


async def case_sweep_deletes_old_keeps_recent_and_terminal_only():
    await _reset_and_seed()
    _set_windows(7 * 24 * 60 * 60)  # OLD(30d) out, RECENT(1h) in
    res = await server.evict_audit_logs_once()

    # plain time-based tables: 1 old gone, 1 recent kept.
    assert res["automation_runs"] == 1, res
    assert res["grok_calls"] == 1, res
    assert res["actions"] == 1, res
    assert await _count(AutomationRun) == 1
    assert await _count(GrokCall) == 1
    assert await _count(Action) == 1

    # scheduled_jobs: ONLY the old TERMINAL (done) row is deleted; the old
    # pending row + the recent done row survive.
    assert res["scheduled_jobs"] == 1, res
    assert await _count(ScheduledJob) == 2
    assert await _count(ScheduledJob, ScheduledJob.status == "pending") == 1
    assert await _count(ScheduledJob, ScheduledJob.status == "done",
                        ScheduledJob.created_at >= _RECENT) == 1


async def case_zero_window_disables_a_table():
    await _reset_and_seed()
    _set_windows(7 * 24 * 60 * 60)
    server._ACTIONS_RETAIN_S = 0  # disable actions only
    res = await server.evict_audit_logs_once()
    assert "actions" not in res, res          # skipped entirely
    assert await _count(Action) == 2          # both rows survive
    assert res["automation_runs"] == 1, res   # the others still swept


_harness.run(
    case_sweep_deletes_old_keeps_recent_and_terminal_only,
    case_zero_window_disables_a_table,
)
