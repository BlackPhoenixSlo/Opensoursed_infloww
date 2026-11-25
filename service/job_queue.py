from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import NamedTuple, assert_never

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import write_telemetry
from db.engine import get_session
from db.models import AutomationRule, AutomationRun, ScheduledJob
from proxies import scrub_pool_secrets
from automation_registry import canonical_kind, kind_family
import events
import run_decide

log = logging.getLogger("of-relay.automation")

_MAX_JOB_ATTEMPTS = 3



async def _open_run(account_id: str | None, kind: str) -> int:
    async with get_session() as s:
        run = AutomationRun(
            account_id=account_id,
            kind=kind,
            started_at=datetime.utcnow(),
            status="running",
        )
        s.add(run)
        await s.flush()
        return run.id


async def _finalize_run(
    run_id: int,
    status: str,
    stats: dict | None,
    error_text: str | None,
    *,
    job_id: int | None = None,
    job_status: str = "done",
    refused: bool = False,
) -> None:
    async with get_session() as s:
        if job_id is not None:
            if job_status == run_decide.JOB_RETRY:
                await _park_failed_job(s, job_id, error_text or "", refused=refused)
            else:
                await _write_job(s, job_id, job_status, error_text)
        run = await s.get(AutomationRun, run_id)
        if run is None:  # pragma: no cover — defensive
            return
        run.status = status
        run.completed_at = datetime.utcnow()
        # The one place run results are persisted: a repr(e) or error text can carry a pool proxy's host or credentials.
        run.stats_json = scrub_pool_secrets(json.dumps(stats, default=str)) if stats is not None else None
        run.error_text = scrub_pool_secrets(error_text)
        events.on_commit(s, "rule_run_finished", account_id=run.account_id, run_id=run_id,
                         kind=run.kind, status=status, rule_id=current_rule_id())



class _ClaimedJob(NamedTuple):
    id: int
    payload_json: str
    rule_id: int | None = None


@write_telemetry.labelled("automation_enqueue")
async def enqueue_job(
    account_id: str,
    kind: str,
    *,
    payload: dict | None = None,
    run_at: datetime | None = None,
    rule_id: int | None = None,
    created_by_employee_id: int | None = None,
    session: AsyncSession | None = None,
) -> int:
    job = ScheduledJob(
        account_id=account_id,
        kind=canonical_kind(kind),
        payload_json=json.dumps(payload or {}, default=str),
        run_at=run_at or datetime.utcnow(),
        status="pending",
        rule_id=rule_id,
        created_by_employee_id=created_by_employee_id,
    )
    if session is not None:
        session.add(job)
        await session.flush()
        _announce_scheduled_send(session, job)
        return job.id
    async with get_session() as s:
        s.add(job)
        await s.flush()
        _announce_scheduled_send(s, job)
        return job.id


# A backlog of queued follow-up steps must not starve the rule firing: they never hold back its next run.
_FOLLOW_UP_JOB = func.coalesce(ScheduledJob.payload_json, "").contains('"follow_up"', autoescape=True)


JOB_FAN = case((func.json_valid(ScheduledJob.payload_json),
                func.json_extract(ScheduledJob.payload_json, "$.only_fan_ids[0]")), else_=None)
ANY_FAN = object()


async def _claim_due_job(account_id: str, kind: str, *, fan=ANY_FAN) -> _ClaimedJob | None:
    now = datetime.utcnow()
    auto_emp = await _automation_employee()
    async with get_session() as s:
        row = (
            await s.execute(
                select(ScheduledJob)
                .where(
                    ScheduledJob.account_id == account_id,
                    # kind_family: a pre-rename job row still claims under its live name, else run_once would never claim it.
                    ScheduledJob.kind.in_(kind_family(kind)),
                    ScheduledJob.status == "pending",
                    ScheduledJob.run_at <= now,
                    *(() if fan is ANY_FAN else (JOB_FAN.is_(None) if fan is None else JOB_FAN == fan,)),
                )
                .order_by(_FOLLOW_UP_JOB, ~_by_operator(auto_emp), ScheduledJob.run_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.status = "running"
        row.attempts = (row.attempts or 0) + 1
        _announce_scheduled_send(s, row)
        return _ClaimedJob(id=row.id, payload_json=row.payload_json or "{}",
                           rule_id=row.rule_id)


# A ContextVar, not a payload key: stamping the rule on follow-on jobs lets switching it OFF cancel the rest, and the payload stays the rule's steps_json.
_current_rule_id: ContextVar[int | None] = ContextVar("_current_rule_id", default=None)


def current_rule_id() -> int | None:
    return _current_rule_id.get()


_current_job_id: ContextVar[int | None] = ContextVar("_current_job_id", default=None)


def current_job_id() -> int | None:
    return _current_job_id.get()


JOB_CANCELLED = "cancelled"
RULE_OFF_REASON = "rule switched off"


async def rule_is_live(s, rule_id: int) -> bool:
    rule = await s.get(AutomationRule, int(rule_id))
    return rule is not None and bool(rule.is_enabled)


async def enabled_rule_id(account_id: str, kind: str, *, session=None) -> int | None:
    if session is None:
        async with get_session() as s:
            return await enabled_rule_id(account_id, kind, session=s)
    return (await session.execute(
        select(AutomationRule.id).where(
            AutomationRule.account_id == str(account_id),
            AutomationRule.kind.in_(kind_family(kind)),
            AutomationRule.is_enabled.is_(True),
        ).order_by(AutomationRule.id).limit(1)
    )).scalar_one_or_none()


# Follow-on drips/resends carry the rule id so OFF reaches them but are not the rule firing: the cadence anchor skips them.
FOLLOWUP_MARK = run_decide.FOLLOWUP_MARK


async def rule_last_fired_at(s, rule_id: int) -> datetime | None:
    return (
        await s.execute(
            select(func.max(ScheduledJob.created_at))
            .where(ScheduledJob.rule_id == rule_id,
                   ~ScheduledJob.payload_json.contains(
                       f'"{FOLLOWUP_MARK}"', autoescape=True))
        )
    ).scalar_one_or_none()


async def enqueue_followup(
    account_id: str,
    kind: str,
    *,
    payload: dict,
    run_at: datetime | None = None,
    created_by_employee_id: int | None = None,
) -> int | None:
    rid = current_rule_id()
    if rid is None:
        return await enqueue_job(account_id, kind, payload=payload, run_at=run_at,
                                 created_by_employee_id=created_by_employee_id)
    async with get_session() as s:
        # Checked in the insert's own session: a rule switched OFF mid-run must not get a fresh follow-on.
        if not await rule_is_live(s, rid):
            log.info("automation_followup_dropped_rule_off account=%s kind=%s rule=%s",
                     account_id, kind, rid)
            return None
        return await enqueue_job(
            account_id, kind, payload={**payload, FOLLOWUP_MARK: True}, run_at=run_at,
            rule_id=rid, created_by_employee_id=created_by_employee_id, session=s,
        )


MISSED_WHILE_OFF_REASON = "missed: the Creator was deactivated"


async def cancel_jobs_missed_while_off(account_id: str, deactivated_at: datetime) -> int:
    async with get_session() as s:
        ids = (await s.execute(
            select(ScheduledJob.id).where(
                ScheduledJob.account_id == account_id,
                ScheduledJob.status == "pending",
                ScheduledJob.run_at >= deactivated_at,
                ScheduledJob.run_at <= datetime.utcnow(),
                # Cleanup jobs are never cancelled: late, they still take down what went out.
                ScheduledJob.kind.notin_(kind_family("unsend_messages")),
            )
        )).scalars().all()
        for job_id in ids:
            await _write_job(s, job_id, JOB_CANCELLED, MISSED_WHILE_OFF_REASON)
    if ids:
        log.info("automation_jobs_missed_while_off account=%s cancelled=%d", account_id, len(ids))
    return len(ids)


async def _mark_job(job_id: int, status: str, last_error: str | None) -> None:
    async with get_session() as s:
        await _write_job(s, job_id, status, last_error)


async def _write_job(s, job_id: int, status: str, last_error: str | None) -> None:
    job = await s.get(ScheduledJob, job_id)
    if job is None:  # pragma: no cover
        return
    job.status = status
    if last_error is not None:
        job.last_error = scrub_pool_secrets(last_error)[:500]
    _announce_scheduled_send(s, job)


def _announce_scheduled_send(s, job: ScheduledJob) -> None:
    if job.kind == "scheduled_send":
        events.on_commit(s, "scheduled_send_changed", account_id=job.account_id, job_id=job.id)


async def _mark_job_failure(job_id: int, err: str) -> None:
    async with get_session() as s:
        await _park_failed_job(s, job_id, err)


async def _park_failed_job(s, job_id: int, err: str, *, refused: bool = False) -> None:
    err = scrub_pool_secrets(err)
    job = await s.get(ScheduledJob, job_id)
    if job is None:  # pragma: no cover
        return
    _announce_scheduled_send(s, job)
    prev_error, job.last_error = job.last_error, err[:500]
    attempts = job.attempts or 0
    if refused:
        attempts = run_decide.proxy_tries(prev_error) + 1
        budget, backoff_s = run_decide.PROXY_RETRIES + 1, run_decide.PROXY_RETRY_MINUTES * 60
    else:
        budget, backoff_s = _MAX_JOB_ATTEMPTS, run_decide.JOB_RETRY_BACKOFF_S
    rid = job.rule_id or run_decide.payload_rule_id(job.payload_json)
    # A retry must not outlive its rule: the operator stopped that work.
    live = None if rid is None else await rule_is_live(s, rid)
    match decision := run_decide.park(attempts, live, budget, backoff_s):
        case run_decide.Cancelled():
            job.status = JOB_CANCELLED
            job.last_error = f"{RULE_OFF_REASON} ({err})"[:500]
        case run_decide.Retry(backoff_s=wait_s):
            job.status = "pending"
            job.run_at = datetime.utcnow() + timedelta(seconds=wait_s)
            if refused:
                job.last_error = run_decide.proxy_retry_reason(attempts, err)[:500]
        case run_decide.Error():
            job.status = "error"
            if refused:
                job.last_error = run_decide.proxy_refused_reason(err)[:500]
        case _:
            assert_never(decision)


async def _automation_employee() -> int:
    from employees import get_automation_employee_id
    try:
        return await get_automation_employee_id()
    except LookupError:
        return -1


def _by_operator(auto_emp: int):
    col = ScheduledJob.created_by_employee_id
    return and_(col.is_not(None), col != auto_emp)
