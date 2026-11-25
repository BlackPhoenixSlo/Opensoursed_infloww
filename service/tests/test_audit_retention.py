#!/usr/bin/env python3
import _harness  # MUST be first: binds a throwaway temp DB (unset env falls back to PROD)

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import db_retention  # noqa: E402 — provides evict_audit_logs_once
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Action, AiDecision, AutomationRun, GrokCall, ScheduledJob,
)

_OLD = datetime.utcnow() - timedelta(days=30)
_RECENT = datetime.utcnow() - timedelta(hours=1)
ACCT = "acct_test"


async def _reset_and_seed() -> None:
    async with get_session() as s:
        # scheduled_jobs FKs accounts: delete it before the Account row
        for M in (AutomationRun, GrokCall, ScheduledJob, Action, Account):
            await s.execute(M.__table__.delete())
        s.add(Account(id=ACCT))
        for ts in (_OLD, _RECENT):
            s.add(AutomationRun(kind="gen_info", started_at=ts, status="ok"))
            s.add(GrokCall(purpose="gen_info", model="m", endpoint="/chat",
                           prompt_json="{}", called_at=ts))
            s.add(Action(action="send", at=ts))
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
    db_retention._AUTOMATION_RUNS_RETAIN_S = seconds
    db_retention._GROK_CALLS_RETAIN_S = seconds
    db_retention._SCHEDULED_JOBS_RETAIN_S = seconds
    db_retention._ACTIONS_RETAIN_S = seconds


async def case_sweep_deletes_old_keeps_recent_and_terminal_only():
    await _reset_and_seed()
    _set_windows(7 * 24 * 60 * 60)
    res = await db_retention.evict_audit_logs_once()

    assert res["automation_runs"] == 1, res
    assert res["grok_calls"] == 1, res
    assert res["actions"] == 1, res
    assert await _count(AutomationRun) == 1
    assert await _count(GrokCall) == 1
    assert await _count(Action) == 1

    assert res["scheduled_jobs"] == 1, res
    assert await _count(ScheduledJob) == 2
    assert await _count(ScheduledJob, ScheduledJob.status == "pending") == 1
    assert await _count(ScheduledJob, ScheduledJob.status == "done",
                        ScheduledJob.created_at >= _RECENT) == 1


async def case_zero_window_disables_a_table():
    await _reset_and_seed()
    _set_windows(7 * 24 * 60 * 60)
    db_retention._ACTIONS_RETAIN_S = 0
    res = await db_retention.evict_audit_logs_once()
    assert "actions" not in res, res
    assert await _count(Action) == 2
    assert res["automation_runs"] == 1, res


async def case_full_ai_test_rows_age_out_in_7_days_shadow_kept():
    aid, now = "acct_fa_retention", datetime.utcnow()
    async with get_session() as s:
        await s.execute(AiDecision.__table__.delete())
        s.add(Account(id=aid))
        for key, mode, days in (("old-test", "test", 8), ("new-test", "test", 6), ("old-shadow", "shadow", 8)):
            s.add(AiDecision(account_id=aid, fan_id=-7, mode=mode, trigger_kind=mode, trigger_key=key,
                             route="chat", heat=1, route_row="otherwise", question_version="v",
                             status="sent" if mode == "test" else "planned",
                             created_at=now - timedelta(days=days)))
        await s.commit()
    res = await db_retention.evict_audit_logs_once()
    assert res["ai_decisions"] == 1, res
    async with get_session() as s:
        left = sorted((await s.execute(select(AiDecision.trigger_key))).scalars())
    assert left == ["new-test", "old-shadow"], left


async def case_settled_test_offers_age_out_in_7_days_shadow_kept():
    aid, now = "acct_fa_retention_offer", datetime.utcnow()
    async with get_session() as s:
        await s.execute(AiDecision.__table__.delete())
        s.add(Account(id=aid))
        for key, mode, outcome in (("old-bought", "test", "bought"), ("old-declined", "test", "declined"),
                                   ("old-shadow", "shadow", None)):
            s.add(AiDecision(account_id=aid, fan_id=-7, mode=mode, trigger_kind=mode, trigger_key=key,
                             route="sell_now", heat=2, route_row="sell", question_version="v",
                             status="sent" if mode == "test" else "planned", created_at=now - timedelta(days=8),
                             offer_price_cents=1000 if outcome else None, offer_list_cents=1000 if outcome else None,
                             offer_media_json='{"locked": [1], "previews": []}' if outcome else None,
                             offer_item_ref='{"ref": 1, "kind": "offer"}' if outcome else None,
                             outcome=outcome, outcome_at=now - timedelta(days=8) if outcome else None,
                             join_src="test" if outcome else None))
        await s.commit()
    res = await db_retention.evict_audit_logs_once()
    assert res["ai_decisions"] == 2, res
    async with get_session() as s:
        left = sorted((await s.execute(select(AiDecision.trigger_key))).scalars())
    assert left == ["old-shadow"], left


_harness.run(
    case_sweep_deletes_old_keeps_recent_and_terminal_only,
    case_zero_window_disables_a_table,
    case_full_ai_test_rows_age_out_in_7_days_shadow_kept,
    case_settled_test_offers_age_out_in_7_days_shadow_kept,
)
