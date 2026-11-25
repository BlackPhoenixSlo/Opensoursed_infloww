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
SWEEP_PAYLOAD = "{}"
SWEEP_EVERY_S = 4 * 3600
TICK_S = 300
FIRST_AFTER_S = 120
DUP_REASON = "duplicate full sweep"
FULL_SWEEP_MARK = '"full_sweep": true'
# Literal last_error of a job a shutdown cancelled (automation_executor writes it as a literal, no constant).
RESTART_CANCEL = "cancelled"


@dataclass(frozen=True)
class OpenJob:
    id: int
    running: bool
    automation: bool


@dataclass(frozen=True)
class Plan:
    enqueue: list[str]
    cancel: list[int]


def plan(live: Iterable[str], open_jobs: Mapping[str, Sequence[OpenJob]],
         swept_recently: set[str]) -> Plan:
    cancel: list[int] = []
    for jobs in open_jobs.values():
        pending = [j for j in jobs if j.automation and not j.running]
        keep = 0 if len(pending) < len(jobs) else 1
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
            .where(AutomationRun.kind.in_(kind_family(KIND)), AutomationRun.status == "ok",
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
        # Lazy: the executor imports widely.
        from automation_executor import enqueue_job, wake_supervisor
        async with get_session() as s:
            if p.cancel:
                cancelled = (await s.execute(
                    update(ScheduledJob)
                    .where(ScheduledJob.id.in_(p.cancel), ScheduledJob.status == "pending")
                    .values(status="cancelled", last_error=DUP_REASON)
                )).rowcount
            for aid in p.enqueue:
                await enqueue_job(aid, KIND, payload={}, session=s)
        if p.enqueue:
            wake_supervisor()
        log.info("chat_sweep_cadence live=%d enqueued=%d cancelled_duplicates=%d",
                 len(live), len(p.enqueue), cancelled)
    return {"live": len(live), "enqueued": len(p.enqueue), "cancelled": cancelled}
