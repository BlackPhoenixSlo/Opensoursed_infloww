"""service/sweep_cadence.py — full chat sweeps (`scrape_chats`, payload `{}`) on a cadence.

The sweep is how an agency's outbound from another CRM (Infloww) reaches our DB: the
WS pump stores inbound only. It used to be enqueued once per account on EVERY relay
start (server._seed_chat_links_once), with no dedupe: deploys stacked up to 18
identical jobs per account on a 2-slot bulk lane (prod, 2026-11).

Now, per live account (session on disk, not deactivated, not session-dead): at most ONE
open (pending/running) `{}` sweep; a new one only when none is open AND its last full
sweep finished >= SWEEP_EVERY_S ago (never swept: at once). The anchor is the
latest job with payload exactly `{}` that ended for real, read from the DB, so
restarts change nothing:
  - ok: its `automation_runs` row (scrape_chats stamps `full_sweep` on a `{}` run
    only; `{"limit": 50}`, `fan_ids` and failed runs never carry it), `completed_at`;
  - a real error (retries spent): the job row parked 'error', at its `run_at` (the
    last attempt's due time, ~when it ran), so a failing account waits the cadence.
A restart's cancel (`last_error` RESTART_CANCEL, even with the retries spent) and an
interrupted / orphaned run never anchor: the next pass enqueues at once.

Each pass also collapses duplicates: per account the oldest pending automation `{}`
sweep stays, the rest are cancelled (DUP_REASON); none stays when one is running or
an operator's / rule's `{}` sweep is open. `fan_ids` / `chat_ids` jobs, and
operator / rule jobs, are never touched.

Runs as its own periodic task (server._start_event_pumps): first pass FIRST_AFTER_S
after boot, then every TICK_S.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Sequence

from sqlalchemy import select, update

import account_health
import accounts as account_registry
from automation_registry import kind_family
from db.engine import get_session
from db.models import AutomationRun, ScheduledJob

log = logging.getLogger("of-relay.automation")

KIND = "scrape_chats"
SWEEP_PAYLOAD = "{}"          # what enqueue_job writes for payload={}
SWEEP_EVERY_S = 4 * 3600
TICK_S = 300
FIRST_AFTER_S = 120
DUP_REASON = "duplicate full sweep"
FULL_SWEEP_MARK = '"full_sweep": true'   # scrape_chats' stats on a `{}` run (json.dumps)
RESTART_CANCEL = "cancelled"   # last_error of a job whose run a shutdown cancelled (run_decide.outcome)


@dataclass(frozen=True)
class OpenJob:
    id: int
    running: bool
    automation: bool   # no operator, no rule: the cadence's own (or a legacy restart seed's)


@dataclass(frozen=True)
class Plan:
    enqueue: list[str]
    cancel: list[int]


def plan(live: Iterable[str], open_jobs: Mapping[str, Sequence[OpenJob]],
         swept_recently: set[str]) -> Plan:
    """Pure. `open_jobs`: per account its open `{}` sweeps, oldest first.
    `swept_recently`: accounts whose last full sweep finished < SWEEP_EVERY_S ago."""
    cancel: list[int] = []
    for jobs in open_jobs.values():
        pending = [j for j in jobs if j.automation and not j.running]
        keep = 0 if len(pending) < len(jobs) else 1   # something else open: keep none
        cancel += [j.id for j in pending[keep:]]
    enqueue = [a for a in live if not open_jobs.get(a) and a not in swept_recently]
    return Plan(enqueue=enqueue, cancel=cancel)


async def _live_ids() -> list[str]:
    off = await account_health.deactivated_ids()
    dead = await account_health.dead_session_map()
    return [m["id"] for m in account_registry.list_accounts()
            if m.get("has_session") and m["id"] not in off and m["id"] not in dead]


async def tick() -> dict:
    """One pass: collapse duplicate sweeps, enqueue the due ones. Returns counts."""
    now = datetime.utcnow()
    live = await _live_ids()
    async with get_session() as s:
        rows = (await s.execute(
            select(ScheduledJob.account_id, ScheduledJob.id, ScheduledJob.status,
                   ScheduledJob.created_by_employee_id, ScheduledJob.rule_id)
            .where(ScheduledJob.kind.in_(kind_family(KIND)),
                   ScheduledJob.status.in_(("pending", "running")),
                   ScheduledJob.payload_json == SWEEP_PAYLOAD)
            .order_by(ScheduledJob.id)
        )).all()
        cutoff = now - timedelta(seconds=SWEEP_EVERY_S)
        recent = set((await s.execute(
            select(AutomationRun.account_id)
            .where(AutomationRun.kind == KIND, AutomationRun.status == "ok",
                   AutomationRun.completed_at >= cutoff,
                   AutomationRun.stats_json.contains(FULL_SWEEP_MARK, autoescape=True))
            .group_by(AutomationRun.account_id)
        )).scalars().all())
        recent |= set((await s.execute(
            select(ScheduledJob.account_id)
            .where(ScheduledJob.kind.in_(kind_family(KIND)), ScheduledJob.status == "error",
                   ScheduledJob.payload_json == SWEEP_PAYLOAD, ScheduledJob.run_at >= cutoff,
                   ScheduledJob.last_error.is_(None) | (ScheduledJob.last_error != RESTART_CANCEL))
            .group_by(ScheduledJob.account_id)
        )).scalars().all())
    open_jobs: dict[str, list[OpenJob]] = {}
    for aid, jid, status, emp, rule in rows:
        open_jobs.setdefault(aid, []).append(
            OpenJob(jid, status == "running", emp is None and rule is None))
    p = plan(live, open_jobs, recent)
    cancelled = 0
    if p.cancel or p.enqueue:
        from automation_executor import enqueue_job, wake_supervisor   # lazy: executor imports widely
        async with get_session() as s:
            if p.cancel:
                # Only still-pending rows: a claim since the read keeps its job.
                cancelled = (await s.execute(
                    update(ScheduledJob)
                    .where(ScheduledJob.id.in_(p.cancel), ScheduledJob.status == "pending")
                    .values(status="cancelled", last_error=DUP_REASON)
                )).rowcount
            for aid in p.enqueue:
                await enqueue_job(aid, KIND, payload={}, session=s)
        if p.enqueue:
            wake_supervisor()
    out = {"live": len(live), "enqueued": len(p.enqueue), "cancelled": cancelled}
    if p.cancel or p.enqueue:
        log.info("chat_sweep_cadence live=%d enqueued=%d cancelled_duplicates=%d",
                 out["live"], out["enqueued"], cancelled)
    return out
