"""service/ultra_run.py — Ultra plans: store, OK, run, cancel, recover (docs/plans/ultra-mode/issues/06).

  propose   validate (ultra_decide) + the send chain on every send's text (send_chain), then validate the
            post-chain plan again (a chained text must not look like a reference) → an `awaiting_ok` row
            holding the post-chain plan and its sha256. A chain refusal names the step and the stage.
  approve   the owner's OK (cookie, the sha256 the card showed) → `running` + the executor task.
  view      the owner's plan with its card and step states (each: state, error, open_url); an
            `awaiting_ok` plan past ultra_decide.OK_TTL is `expired` here (nothing else reads it).
  cancel    `awaiting_ok` → `cancelled` now (steps skipped); `running` → a flag the executor reads before each step; a
            `running` plan with no executor in this process (its end could not be saved) → `interrupted`.
  recover   on relay start: `running` → `interrupted`, `started` steps → `uncertain`. No resume.

The executor is an in-memory asyncio task holding the approving owner's Cookie (never stored). It runs the
steps in order through `toolbox.call`, writing each step `started` BEFORE the call, so a crash or a lost
answer leaves `uncertain`, never a silent resend. A send that may have gone out stops the run and is never
retried; neither route takes an idempotency key, so that record is the guard. No DB session is held across
a call (toolbox module doc). The end files one `ultra_done` notification. A cancelled executor task (shutdown)
saves `interrupted` (closed steps) and re-raises; no notification.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

import send_chain
import toolbox
import toolbox_decide as td
import ultra_decide as ud
from db.engine import get_session
from db.models import Account, UltraPlan

log = logging.getLogger("of-relay.ultra")

STEP_TIMEOUT_S = 180.0  # one step's call; a send past it is uncertain (it may still finish)
_TASKS: dict[str, asyncio.Task | None] = {}  # this process's runs; None = an OK flipping it to running
_CANCEL: set[str] = set()


def _plan(row: UltraPlan) -> ud.Plan:
    data = json.loads(row.plan_json)
    return ud.Plan(data["summary"], tuple(data["steps"]))


async def _chained(plan: ud.Plan) -> ud.Plan:
    steps, errors = [], []
    for s in plan.steps:
        t, args = ud.TOOLS[s["tool"]], dict(s["args"])
        for path in t.model_text:
            v = await send_chain.run(args[path], args["account_id"])
            if v.text is None:
                errors.append({"step": s["id"], "field": path,
                               "error": f"refused by the send chain at stage {v.stage}: {v.detail}"})
            else:
                args[path] = v.text
        steps.append({**s, "args": args})
    if errors:
        raise ud.PlanError(errors)
    return ud.Plan(plan.summary, tuple(steps))


async def propose(raw: Any, owner_user_id: str, owned: frozenset[str], source: str) -> dict[str, Any]:
    """Store a valid plan as `awaiting_ok`: {plan_id, status, expires_at, steps} of the stored row. PlanError
    when refused (nothing stored)."""
    plan = ud.validate_plan((await _chained(ud.validate_plan(raw, owned))).raw(), owned)
    body, pid, now = plan.as_json(), secrets.token_hex(16), datetime.utcnow()
    async with get_session() as s:
        s.add(UltraPlan(id=pid, owner_user_id=owner_user_id, source=source, plan_json=json.dumps(body),
                        plan_sha256=ud.digest(body), status="awaiting_ok", created_at=now,
                        step_states=json.dumps(ud.initial_states(plan))))
    return {"plan_id": pid, "status": "awaiting_ok", "expires_at": (now + ud.OK_TTL).isoformat() + "Z",
            "steps": body["steps"]}


async def _row(plan_id: str, owner_user_id: str) -> UltraPlan | None:
    async with get_session() as s:
        row = await s.get(UltraPlan, plan_id)
        if row is None or row.owner_user_id != owner_user_id:
            return None
        if ud.expired(row.status, row.created_at, datetime.utcnow()):
            row.status, row.finished_at = "expired", datetime.utcnow()
            await s.flush()
        s.expunge(row)
        return row


async def _names(ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    async with get_session() as s:
        rows = (await s.execute(select(Account.id, Account.nickname).where(Account.id.in_(ids)))).all()
    return {str(i): n for i, n in rows if n}


async def view(plan_id: str, owner_user_id: str) -> dict[str, Any] | None:
    """The owner's plan, or None (unknown or another owner's)."""
    row = await _row(plan_id, owner_user_id)
    if row is None:
        return None
    plan, states = _plan(row), json.loads(row.step_states)
    names = await _names({s["args"]["account_id"] for s in plan.steps if isinstance(s["args"].get("account_id"), str)})
    return {"id": row.id, "status": row.status, "source": row.source, "summary": plan.summary,
            "sha256": row.plan_sha256, "steps": list(plan.steps), "card": ud.card(plan, names),
            "step_states": states,
            "created_at": row.created_at.isoformat() + "Z",
            "expires_at": (row.created_at + ud.OK_TTL).isoformat() + "Z",
            "approved_at": row.approved_at.isoformat() + "Z" if row.approved_at else None,
            "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None}


class Refused(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


async def approve(plan_id: str, owner_user_id: str, sha256: str, creds: toolbox.Creds) -> None:
    """The OK: start the run, or Refused (404 not the owner's; 409 expired, not awaiting OK, wrong hash)."""
    row = await _row(plan_id, owner_user_id)
    if row is None:
        raise Refused(404, "plan not found")
    if row.status != "awaiting_ok":
        raise Refused(409, f"this plan is {row.status}; it can no longer be approved")
    if sha256 != row.plan_sha256:
        raise Refused(409, "the plan changed since this card was shown; reload it and check again")
    if plan_id in _TASKS:
        raise Refused(409, "this plan was already approved or cancelled")
    _TASKS[plan_id] = None  # claimed before the flip: a cancel in between sees a live run, not a lost one
    won = 0
    try:
        async with get_session() as s:  # one OK wins: the status flips only from awaiting_ok
            won = (await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id, UltraPlan.status == "awaiting_ok")
                                   .values(status="running", approved_at=datetime.utcnow()))).rowcount
    finally:
        if won != 1:
            _TASKS.pop(plan_id, None)
    if won != 1:
        raise Refused(409, "this plan was already approved or cancelled")
    _TASKS[plan_id] = asyncio.create_task(_run(plan_id, owner_user_id, _plan(row), creds))


async def _flip(plan_id: str, frm: ud.PlanStatus, values: dict[str, Any]) -> bool:
    """`frm` → `values` only if the plan is still `frm`; whether it was."""
    async with get_session() as s:
        return (await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id, UltraPlan.status == frm)
                                .values(**values))).rowcount == 1


async def cancel(plan_id: str, owner_user_id: str) -> None:
    """Cancel, or Refused (404 not the owner's; 409 already over)."""
    row = await _row(plan_id, owner_user_id)
    if row is None:
        raise Refused(404, "plan not found")
    if row.status == "awaiting_ok":
        if await _flip(plan_id, "awaiting_ok", {"status": "cancelled", "finished_at": datetime.utcnow(),
                                                "step_states": json.dumps(ud.close(json.loads(row.step_states)))}):
            return
        row = await _row(plan_id, owner_user_id) or row  # an OK (or expiry) got there first
    if row.status == "running" and plan_id in _TASKS:
        _CANCEL.add(plan_id)
        return
    if row.status == "running":  # no executor here: its end was never saved
        if await _flip(plan_id, "running", {"status": "interrupted",
                                            "step_states": json.dumps(ud.close(json.loads(row.step_states))),
                                            "finished_at": datetime.utcnow()}):
            return
        row = await _row(plan_id, owner_user_id) or row
    raise Refused(409, f"this plan is {row.status}")


async def _save(plan_id: str, states: list[dict[str, Any]], status: ud.PlanStatus = "running") -> None:
    values: dict[str, Any] = {"step_states": json.dumps(states), "status": status}
    if status in ud.FINAL:
        values["finished_at"] = datetime.utcnow()
    async with get_session() as s:
        await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id).values(**values))


async def _step(tool: td.Tool, args: dict[str, Any], creds: toolbox.Creds, key: str) -> dict[str, Any] | None:
    """The call's result, or None when it raised or ran past STEP_TIMEOUT_S (shielded: a send keeps going)."""
    try:
        return await asyncio.wait_for(asyncio.shield(toolbox.call(tool, args, creds, plan_step=key)), STEP_TIMEOUT_S)
    except Exception:
        log.exception("ultra step %s: no answer", key)
        return None


async def _run(plan_id: str, owner_user_id: str, plan: ud.Plan, creds: toolbox.Creds) -> None:
    states, results = ud.initial_states(plan), {}
    status: ud.PlanStatus = "done"
    try:
        for i, step in enumerate(plan.steps):
            if plan_id in _CANCEL:
                status = "cancelled"
                break
            tool = ud.TOOLS[step["tool"]]
            try:
                args = ud.substitute(step, results)
            except KeyError as e:
                states[i] = ud.step_end(step["id"], tool.effect, td.error(422, f"no value for {e.args[0]}"))
                status = "failed"
                break
            states[i] = {"id": step["id"], "state": "started"}
            await _save(plan_id, states)
            result = await _step(tool, args, creds, f"{plan_id}:{step['id']}")
            states[i] = ud.step_end(step["id"], tool.effect, result)
            if states[i]["state"] != "done":
                status = "failed"
                break
            results[step["id"]] = result
    except asyncio.CancelledError:  # not an Exception: the task was cancelled (shutdown) mid-run; never `done`
        log.warning("ultra plan %s: executor cancelled", plan_id)
        status = "interrupted"
        raise
    except Exception:
        log.exception("ultra plan %s: executor crashed", plan_id)
        status = "failed"
    finally:
        states = ud.close(states)
        try:
            await asyncio.shield(_save(plan_id, states, status))  # a second cancel must not lose the end
        except Exception:  # the row stays `running`: a cancel (no executor here) or the next start ends it
            log.exception("ultra plan %s: could not save its end", plan_id)
        finally:
            _CANCEL.discard(plan_id)
            _TASKS.pop(plan_id, None)
    await _notify(owner_user_id, plan_id, ud.report_text(plan.summary, status, states))


async def _notify(owner_user_id: str, plan_id: str, text: str) -> None:
    try:
        from notifications_api import Notice, notify  # lazy: notifications_api imports settings
        await notify(owner_user_id, [Notice("ultra_done", text, data={"href": ud.plan_path(plan_id)},
                                            dedupe=f"ultra_done:{plan_id}")])
    except Exception:
        log.exception("ultra_done notification failed (plan=%s)", plan_id)


async def recover() -> int:
    """Relay start: every `running` plan → `interrupted` (its `started` steps `uncertain`). How many."""
    async with get_session() as s:
        rows = (await s.execute(select(UltraPlan).where(UltraPlan.status == "running"))).scalars().all()
        for row in rows:
            row.status, states = ud.recovered(row.status, json.loads(row.step_states))
            row.step_states, row.finished_at = json.dumps(states), datetime.utcnow()
    return len(rows)
