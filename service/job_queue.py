"""
The scheduled_jobs queue and the automation_runs rows, moved out of
automation_executor (which re-exports, as the same objects, the names it uses
or that others read as `ax.<name>`; patch queue internals on job_queue).

A route handler only INSERTs a job (`enqueue_job`); the executor claims it
(`_claim_due_job`), opens a run row (`_open_run`) and closes run + job in one
commit (`_finalize_run`). A failed job is parked by `_park_failed_job`, which
writes what `run_decide.park` decides (retry, error, or cancelled when its rule
went off mid-run).
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import NamedTuple, assert_never

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import write_telemetry
from db.engine import get_session
from db.models import AutomationRule, AutomationRun, ScheduledJob
from proxies import scrub_pool_secrets  # persisted run/job text names no Inflowwww proxy
from automation_registry import canonical_kind, kind_family
import events
import run_decide

log = logging.getLogger("of-relay.automation")

_MAX_JOB_ATTEMPTS = 3   # transient-failure retries before a job is parked 'error'


# ── automation_runs telemetry ────────────────────────────────────────

async def _open_run(account_id: str | None, kind: str) -> int:
    """Insert a 'running' automation_runs row up-front so the dashboard shows
    in-flight runs, and return its id for the finalizer."""
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
) -> None:
    """Close the run row and, in the same transaction, the job it ran (if
    any): `job_status` is written as-is, or run_decide.JOB_RETRY parks a failure. One
    commit, so `rule_run_finished` never reaches a client that would still
    read the job as running."""
    async with get_session() as s:
        # The job first: a missing run row must not leave it running.
        if job_id is not None:
            if job_status == run_decide.JOB_RETRY:
                await _park_failed_job(s, job_id, error_text or "")
            else:
                await _write_job(s, job_id, job_status, error_text)
        run = await s.get(AutomationRun, run_id)
        if run is None:  # pragma: no cover — defensive
            return
        run.status = status
        run.completed_at = datetime.utcnow()
        # The one place run results are persisted: an automation's `repr(e)` in
        # its stats (nudge_online_fire, …) or
        # the run's error can carry a pool proxy's host or credentials.
        run.stats_json = scrub_pool_secrets(json.dumps(stats, default=str)) if stats is not None else None
        run.error_text = scrub_pool_secrets(error_text)
        # Rule lists, run history and the error badge refresh on this instead
        # of polling (events.STATE_TYPES).
        events.on_commit(s, "rule_run_finished", account_id=run.account_id, run_id=run_id,
                         kind=run.kind, status=status, rule_id=current_rule_id())


# ── scheduled_jobs queue ─────────────────────────────────────────────

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
    """Public trigger seam: a route handler calls THIS (insert a row + return)
    instead of running an automation inline. Returns the new job id.

    `session`: insert in the caller's open transaction (it commits or rolls
    back with the caller's other writes); without it, in a session of its own."""
    job = ScheduledJob(
        account_id=account_id,
        kind=canonical_kind(kind),  # new rows never mint a retired token
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


# One fan's queued Smart Messages follow-up step (`{"follow_up": ...}`, see
# lifecycle_messages.schedule_follow_ups), not its rule firing. A backlog of them
# must not starve the rule: they never hold back its next run in the
# materializer, and a due run of the rule is claimed ahead of them.
_FOLLOW_UP_JOB = func.coalesce(ScheduledJob.payload_json, "").contains('"follow_up"', autoescape=True)


async def _claim_due_job(account_id: str, kind: str) -> _ClaimedJob | None:
    """Claim the earliest due pending job for (account, kind): flip it to
    'running' and bump attempts in one transaction so a concurrent tick can't
    grab the same row. Returns a detached (id, payload) tuple or None.

    Queries by kind_family: a pre-rename job row (migration 0062 not yet run)
    still claims under its kind's live name — without this, run_once (which
    canonicalizes at entry) would never claim it and the row would re-dispatch
    an UNBOUND default-payload run every tick."""
    now = datetime.utcnow()
    auto_emp = await _automation_employee()
    async with get_session() as s:
        row = (
            await s.execute(
                select(ScheduledJob)
                .where(
                    ScheduledJob.account_id == account_id,
                    ScheduledJob.kind.in_(kind_family(kind)),
                    ScheduledJob.status == "pending",
                    ScheduledJob.run_at <= now,
                )
                # An operator's job (started from the app) before automation's:
                # the supervisor took this run's slot in the operator tier.
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


# The rule the CURRENT run belongs to (its claimed job's `rule_id`), for the
# automations that enqueue follow-on jobs (auto_posts / mass_premade drips and
# resends): stamping it on those jobs is what lets switching the rule OFF cancel
# the rest of the list. A ContextVar, not a payload key, so the payload an
# automation sees stays exactly the rule's `steps_json`.
_current_rule_id: ContextVar[int | None] = ContextVar("_current_rule_id", default=None)


def current_rule_id() -> int | None:
    """Rule id of the job this run claimed, or None (a one-shot / direct call)."""
    return _current_rule_id.get()


# Job status + reason a rule's queued work gets when its rule goes OFF/away.
JOB_CANCELLED = "cancelled"
RULE_OFF_REASON = "rule switched off"


async def _rule_is_live(s, rule_id: int) -> bool:
    """True iff the rule still exists AND is switched on."""
    rule = await s.get(AutomationRule, int(rule_id))
    return rule is not None and bool(rule.is_enabled)


async def enabled_rule_id(account_id: str, kind: str, *, session=None) -> int | None:
    """Id of the account's ENABLED rule of `kind` (any legacy alias; lowest id),
    or None. THE one "is this automation switched on?" read for kinds whose
    rule is their on/off (webhook W7 gating, nudge fires, welcome_turn).
    `session`: read through the caller's (webhook_dispatch reads a DM's
    questions through one)."""
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


# Payload marker on a rule's FOLLOW-ON jobs (a drip / resend an automation
# enqueues mid-run). They carry the rule's id so switching it OFF reaches them,
# but they are not the rule firing: the materializer's cadence anchor skips them.
FOLLOWUP_MARK = run_decide.FOLLOWUP_MARK   # "_followup"


async def rule_last_fired_at(s, rule_id: int) -> datetime | None:
    """When this rule last enqueued its own job: THE cadence anchor, shared by
    the materializer and the rules API's `next_due_at` so the two agree. A
    same-kind one-shot (rule_id NULL) and the rule's follow-on drips/resends
    (FOLLOWUP_MARK) are not the rule firing — see `_materialize_due_rules`."""
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
    """Enqueue the next leg of the CURRENT run's work (drip / resend / repost).

    Inside a rule-made run the job carries that rule (`current_rule_id()`) and
    is inserted only if the rule is still live — checked in the insert's own
    session, so a rule switched OFF while this run was in flight (after its
    queued jobs were cancelled) cannot get a fresh follow-on. Dropped → None.
    Outside a rule (Run-now, a direct call) it is a plain enqueue_job."""
    rid = current_rule_id()
    if rid is None:
        return await enqueue_job(account_id, kind, payload=payload, run_at=run_at,
                                 created_by_employee_id=created_by_employee_id)
    async with get_session() as s:
        if not await _rule_is_live(s, rid):
            log.info("automation_followup_dropped_rule_off account=%s kind=%s rule=%s",
                     account_id, kind, rid)
            return None
        return await enqueue_job(
            account_id, kind, payload={**payload, FOLLOWUP_MARK: True}, run_at=run_at,
            rule_id=rid, created_by_employee_id=created_by_employee_id, session=s,
        )


MISSED_WHILE_OFF_REASON = "missed: the Creator was deactivated"


async def cancel_jobs_missed_while_off(account_id: str, deactivated_at: datetime) -> int:
    """On reactivation: cancel the Creator's pending jobs that fell due while
    it was off, so a two-week-old scheduled send or drip doesn't fire late. A
    recurring rule loses only its stale job; the materializer mints its next
    one on its usual cadence. Jobs due before the deactivation stay, as do
    future ones. Cleanup jobs (the `unsend_messages` family: a story's
    delete/hide, a post's delete, a mass send's unsend) are never cancelled:
    late, they still take down what went out. Returns how many were cancelled."""
    async with get_session() as s:
        ids = (await s.execute(
            select(ScheduledJob.id).where(
                ScheduledJob.account_id == account_id,
                ScheduledJob.status == "pending",
                ScheduledJob.run_at >= deactivated_at,
                ScheduledJob.run_at <= datetime.utcnow(),
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
    """A Fan's scheduled-send list refreshes on this instead of polling; sent
    after the commit, so a refetch reads the job's new state."""
    if job.kind == "scheduled_send":
        events.on_commit(s, "scheduled_send_changed", account_id=job.account_id, job_id=job.id)


async def _mark_job_failure(job_id: int, err: str) -> None:
    async with get_session() as s:
        await _park_failed_job(s, job_id, err)


async def _park_failed_job(s, job_id: int, err: str) -> None:
    """Park a failed job. Retry (status back to 'pending' with a backoff) while
    attempts remain; otherwise leave it 'error' for inspection."""
    err = scrub_pool_secrets(err)
    job = await s.get(ScheduledJob, job_id)
    if job is None:  # pragma: no cover
        return
    _announce_scheduled_send(s, job)
    job.last_error = err[:500]
    # A retry must not outlive its rule: the operator switched it OFF (or
    # deleted it) while this attempt ran — don't requeue work they stopped.
    # Row rule_id first, run_once reads the tag first: kept as before the move.
    # The orders only differ on a job carrying both, and no producer writes
    # both (webhook_dispatch tags `_rule_id` on a rule-less row).
    rid = job.rule_id or run_decide.payload_rule_id(job.payload_json)
    live = None if rid is None else await _rule_is_live(s, rid)
    match decision := run_decide.park(job.attempts or 0, live, _MAX_JOB_ATTEMPTS):
        case run_decide.Cancelled():
            job.status = JOB_CANCELLED
            job.last_error = f"{RULE_OFF_REASON} ({err})"[:500]
        case run_decide.Retry(backoff_s=backoff_s):
            job.status = "pending"
            job.run_at = datetime.utcnow() + timedelta(seconds=backoff_s)
        case run_decide.Error():
            job.status = "error"
        case _:
            assert_never(decision)


async def _automation_employee() -> int:
    """The system Automation employee's id (cached), or -1 without one. Jobs
    automation enqueues for itself (auto_posts' delete/resend) carry it."""
    from employees import get_automation_employee_id  # local: avoid load cycle
    try:
        return await get_automation_employee_id()
    except LookupError:
        return -1


def _by_operator(auto_emp: int):
    """SQL: an operator started this job. The app stamps the acting employee
    (owner or chatter) as `created_by_employee_id` on what it enqueues; a job
    automation enqueued has none, or the Automation employee."""
    col = ScheduledJob.created_by_employee_id
    return and_(col.is_not(None), col != auto_emp)
