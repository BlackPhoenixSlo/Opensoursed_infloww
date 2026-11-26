from __future__ import annotations

import json
from datetime import datetime, timedelta

from _send_kill import Driver, Wire, WireOF, db_row, seed_account

FAN = 72001


def _ungate(aid: str) -> None:
    import automation_executor as ax
    ax._write_gates.pop(aid, None)


async def _run_job(ctx) -> dict:
    import automation_executor as ax
    _ungate(ctx["aid"])
    return await ax.run_once(ctx["aid"], ctx["kind"])


async def _job_due(ctx) -> dict:
    from db.engine import get_session
    from db.models import ScheduledJob
    from sqlalchemy import update
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(
            ScheduledJob.account_id == ctx["aid"], ScheduledJob.status == "pending")
            .values(run_at=datetime.utcnow() - timedelta(seconds=1)))
    return await _run_job(ctx)


def _job_status(ctx) -> str | None:
    row = db_row("SELECT status FROM scheduled_jobs WHERE id=?", (ctx["job"],))
    return row[0] if row else None


async def _scheduled_setup(aid: str, wire: Wire):
    from automation_executor import enqueue_job
    from automations import scheduled_send  # noqa: F401
    await seed_account(aid)
    job = await enqueue_job(aid, "scheduled_send", payload={
        "fan_id": FAN, "text": "later babe", "send_purpose": "manual"},
        run_at=datetime.utcnow() - timedelta(seconds=60))
    return {"aid": aid, "of": WireOF(wire, aid), "kind": "scheduled_send", "job": job}


async def _mass_setup(aid: str, wire: Wire, *, premade: bool = False):
    from automation_executor import enqueue_job
    from automations import mass_premade, send_mass_message  # noqa: F401
    await seed_account(aid)
    message = {"text": "hi all", "included_users": [FAN]}
    kind = "mass_premade" if premade else "send_mass_message"
    job = await enqueue_job(aid, kind, payload={"messages": [message]} if premade else message)
    return {"aid": aid, "of": WireOF(wire, aid), "kind": kind, "job": job}


async def _premade_setup(aid: str, wire: Wire):
    return await _mass_setup(aid, wire, premade=True)


def _mass_run_status(ctx) -> str | None:
    row = db_row("SELECT status FROM mass_runs WHERE account_id=? ORDER BY id DESC LIMIT 1",
                 (ctx["aid"],))
    return row[0] if row else None


async def _priority_setup(aid: str, wire: Wire):
    import automations.priority_mass as pm
    from db.engine import get_session
    from db.models import PriorityMassRecipient, PriorityMassRun
    await seed_account(aid)
    async with get_session() as s:
        run = PriorityMassRun(
            account_id=aid, status=pm.RUNNING, text="hey you", media_json="[]",
            previews_json="[]", price_cents=0, locked_text=False,
            audience_json=json.dumps({"user_lists": ["fans"], "excluded_user_lists": []}))
        s.add(run)
        await s.flush()
        rid = int(run.id)
        s.add(PriorityMassRecipient(run_id=rid, fan_id=FAN, status=pm.PENDING,
                                    updated_at=datetime.utcnow()))
    await pm.ensure_leg(aid, rid)
    return {"aid": aid, "of": WireOF(wire, aid), "kind": pm.KIND, "run": rid}


def _recipient_status(ctx) -> str | None:
    row = db_row("SELECT status FROM priority_mass_recipients WHERE run_id=? AND fan_id=?",
                 (ctx["run"], FAN))
    return row[0] if row else None


async def _lifecycle_setup(aid: str, wire: Wire):
    import automations.lifecycle_messages as lm
    from automation_executor import enqueue_job
    await seed_account(aid)
    await enqueue_job(aid, lm.BIRTHDAY, run_at=datetime.utcnow() - timedelta(minutes=1),
                      payload={"follow_up": {
                          "fan_id": FAN, "steps": [{"text": "f1", "delay_minutes": 5}],
                          "anchor": None, "event": "2026", "step": 1, "tries": 0}})
    return {"aid": aid, "of": WireOF(wire, aid), "kind": lm.BIRTHDAY}


def _lifecycle_claimed(ctx) -> bool:
    return bool(db_row(
        "SELECT 1 FROM lifecycle_message_claims WHERE account_id=? AND kind=? AND fan_id=? "
        "AND event_key=?", (ctx["aid"], ctx["kind"], FAN, "2026|follow_up:1")))


async def _lifecycle_initial_setup(aid: str, wire: Wire):
    import automations.lifecycle_messages as lm
    from automation_executor import enqueue_job
    from db.engine import get_session
    from db.models import AutomationRule, Fan

    await seed_account(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=FAN, birthday=now.strftime("%m-%d")))
        s.add(AutomationRule(account_id=aid, name=lm.BIRTHDAY, kind=lm.BIRTHDAY, trigger_json="{}",
                             steps_json=json.dumps({"enabled": True, "text": "happy birthday",
                                                    "enabled_at": (now - timedelta(days=1)).isoformat()})))
    job = await enqueue_job(aid, lm.BIRTHDAY, run_at=now - timedelta(minutes=1), payload={})
    return {"aid": aid, "of": WireOF(wire, aid), "kind": lm.BIRTHDAY, "job": job}


def _initial_claim(ctx, *, sent: bool = False) -> bool:
    return bool(db_row(
        "SELECT 1 FROM lifecycle_message_claims WHERE account_id=? AND kind=? AND fan_id=? "
        "AND event_key=? AND (? = 0 OR message_idx IS NOT NULL)",
        (ctx["aid"], ctx["kind"], FAN, str(datetime.utcnow().year), sent)))


DRIVERS = [
    Driver(
        kind="mass_premade",
        setup=_premade_setup,
        first=_run_job,
        tick=_job_due,
        resend=None,
        pre_write=lambda ctx: _mass_run_status(ctx) == "running",
        post_update=lambda ctx: _mass_run_status(ctx) == "ok" and _job_status(ctx) == "done",
    ),
    Driver(
        kind="lifecycle_initial",
        setup=_lifecycle_initial_setup,
        first=_run_job,
        tick=_job_due,
        resend=None,
        pre_write=_initial_claim,
        post_update=lambda ctx: _initial_claim(ctx, sent=True),
    ),
    Driver(
        kind="scheduled_send",
        setup=_scheduled_setup,
        first=_run_job,
        tick=_job_due,
        resend=None,
        pre_write=lambda ctx: _job_status(ctx) == "running",
        post_update=lambda ctx: _job_status(ctx) == "done" and bool(db_row(
            "SELECT 1 FROM messages WHERE account_id=? AND fan_id=?", (ctx["aid"], FAN))),
    ),
    Driver(
        kind="mass_job",
        setup=_mass_setup,
        first=_run_job,
        tick=_job_due,
        resend=None,
        pre_write=lambda ctx: _mass_run_status(ctx) == "running",
        post_update=lambda ctx: _mass_run_status(ctx) == "ok" and _job_status(ctx) == "done",
    ),
    Driver(
        kind="priority_mass",
        setup=_priority_setup,
        first=_run_job,
        tick=_job_due,
        resend=None,
        pre_write=lambda ctx: _recipient_status(ctx) == "claimed",
        post_update=lambda ctx: _recipient_status(ctx) == "sent",
    ),
    Driver(
        kind="lifecycle",
        setup=_lifecycle_setup,
        first=_run_job,
        tick=_job_due,
        resend=None,
        pre_write=_lifecycle_claimed,
        post_update=lambda ctx: bool(db_row(
            "SELECT 1 FROM messages WHERE account_id=? AND fan_id=? AND automation_kind=?",
            (ctx["aid"], FAN, ctx["kind"]))),
    ),
]
