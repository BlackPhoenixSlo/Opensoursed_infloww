"""service/ultra_run.py — Ultra plans: store, OK, run, cancel, recover (docs/plans/ultra-mode/issues/06).

  propose   validate (ultra_decide) + the send chain on every send's text (send_chain), then validate the
            post-chain plan again (a chained text must not look like a reference) → an `awaiting_ok` row
            holding the post-chain plan and its sha256. A chain refusal names the step and the stage.
  submit    the same check for an in-app `planning` row (ultra_plan) → that row `awaiting_ok`.
  approve   the owner's OK (cookie, the sha256 the card showed) → `running` + the executor task.
  view      the owner's plan with its card and step states (each: state, error, open_url); an
            `awaiting_ok` plan past ultra_decide.OK_TTL is `expired` here (a flip from awaiting_ok only). A
            `planning` row adds its progress (turns, last tool), never model text.
  cancel    `planning` → `cancelled` (the loop stops at its next turn);
            `awaiting_ok` → `cancelled` now (steps skipped); `running` → a flag the executor reads before each step; a
            `running` plan with no executor in this process (its end could not be saved) → `interrupted`;
            `needs_you` → the flag + wakes the run (no run here → `interrupted`).
  pick      the owner's ids for a `needs_you` judge (cookie) → that step `done`, the plan `running`, the run woken.
  recover   on relay start: `running` / `planning` / `needs_you` → `interrupted`, `started` steps → `uncertain`.

The executor is an in-memory asyncio task holding the approving owner's Cookie (never stored). It runs the
steps in order through `toolbox.call`, writing each step `started` BEFORE the call, so a crash or a lost
answer leaves `uncertain`, never a silent resend. Each save lands only while the row is running / needs_you;
a miss (ended elsewhere) stops the run before any further call. A send that may have gone out stops the run
and is never retried; neither route takes an idempotency key, so that record is the guard. No DB session is held across
a call (toolbox module doc). A judge step (ultra_judge) picks media ids with one model call (≤ the run's
upd.MAX_SPEND_MC); `confirm` parks the run `needs_you` (one `ultra_needs_you` notification) on an in-memory
Event until `pick` or `cancel`, no timeout. A send using its picks has them written into its `started` state
(`resolved`) before the call (ultra_decide.may_send). A saved end files one `ultra_done` notification. A cancelled executor task (shutdown)
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
import ultra_card as uc
import ultra_decide as ud
import ultra_judge
import ultra_judge_decide as uj
import ultra_plan_decide as upd
from db.engine import get_session
from db.models import Account, BioProfile, UltraPlan

log = logging.getLogger("of-relay.ultra")

OWNER_UNREAD = "could not read whose bio page this is; nothing was changed"
STEP_TIMEOUT_S = 180.0  # one step's call; a send past it is uncertain (it may still finish)
_TASKS: dict[str, asyncio.Task | None] = {}  # this process's runs; None = an OK flipping it to running
_CANCEL: set[str] = set()
_WAIT: dict[str, asyncio.Event] = {}  # runs parked `needs_you`: set by pick / cancel


def _plan(row: UltraPlan) -> ud.Plan:
    data = json.loads(row.plan_json)
    return ud.Plan(data["summary"], tuple(data["steps"]))


async def _chained(plan: ud.Plan) -> ud.Plan:
    steps, errors = [], []
    for s in plan.steps:
        if uj.is_judge(s):
            steps.append(s)
            continue
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


async def checked(raw: Any, owned: frozenset[str]) -> ud.Plan:
    """Validate, run the send chain, validate the post-chain plan again. PlanError when refused."""
    return ud.validate_plan((await _chained(ud.validate_plan(raw, owned))).raw(), owned)


def _stored(plan: ud.Plan, now: datetime) -> dict[str, Any]:
    """An `awaiting_ok` row's columns for a checked plan (its OK window starts `now`)."""
    body = plan.as_json()
    return {"plan_json": json.dumps(body), "plan_sha256": ud.digest(body), "status": "awaiting_ok",
            "created_at": now, "step_states": json.dumps(ud.initial_states(plan))}


def _proposed(pid: str, plan: ud.Plan, now: datetime) -> dict[str, Any]:
    return {"plan_id": pid, "status": "awaiting_ok", "expires_at": (now + ud.OK_TTL).isoformat() + "Z",
            "steps": plan.as_json()["steps"]}


async def propose(raw: Any, owner_user_id: str, owned: frozenset[str], source: str) -> dict[str, Any]:
    """Store a valid plan as `awaiting_ok`: {plan_id, status, expires_at, steps} of the stored row. PlanError
    when refused (nothing stored)."""
    plan, pid, now = await checked(raw, owned), secrets.token_hex(16), datetime.utcnow()
    async with get_session() as s:
        s.add(UltraPlan(id=pid, owner_user_id=owner_user_id, source=source, **_stored(plan, now)))
    return _proposed(pid, plan, now)


async def submit(plan_id: str, raw: Any, owned: frozenset[str]) -> dict[str, Any] | None:
    """A `planning` row's plan: checked like `propose`, then that row → `awaiting_ok` (as propose's answer).
    PlanError when refused (row unchanged); None when the row is no longer `planning` (cancelled)."""
    plan, now = await checked(raw, owned), datetime.utcnow()
    return _proposed(plan_id, plan, now) if await _flip(plan_id, "planning", _stored(plan, now)) else None


async def _row(plan_id: str, owner_user_id: str) -> UltraPlan | None:
    async with get_session() as s:
        row = await s.get(UltraPlan, plan_id)
        if row is None or row.owner_user_id != owner_user_id:
            return None
        if ud.expired(row.status, row.created_at, datetime.utcnow()):  # only from awaiting_ok: an OK may win
            await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id, UltraPlan.status == "awaiting_ok")
                            .values(status="expired", finished_at=datetime.utcnow())
                            .execution_options(synchronize_session=False))
            await s.refresh(row)
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
    names = await _names({a["account_id"] for s in plan.steps
                          if isinstance((a := s.get("args", {})).get("account_id"), str)})
    out = {"id": row.id, "status": row.status, "source": row.source, "summary": plan.summary,
           "sha256": row.plan_sha256, "steps": list(plan.steps), "card": uc.card(plan, names),
           "step_states": states,
           "created_at": row.created_at.isoformat() + "Z",
           # no plan yet (planning, or a loop that ended without one) → no OK window
           "expires_at": (row.created_at + ud.OK_TTL).isoformat() + "Z" if row.plan_sha256 else None,
           "approved_at": row.approved_at.isoformat() + "Z" if row.approved_at else None,
           "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None}
    planning = json.loads(row.plan_json).get("planning")
    if planning is not None:
        out["planning"] = planning
    return out


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
    if row.status == "planning":
        if await _flip(plan_id, "planning", {"status": "cancelled", "finished_at": datetime.utcnow()}):
            return
        row = await _row(plan_id, owner_user_id) or row  # its plan landed first
    if row.status == "awaiting_ok":
        if await _flip(plan_id, "awaiting_ok", {"status": "cancelled", "finished_at": datetime.utcnow(),
                                                "step_states": json.dumps(ud.close(json.loads(row.step_states)))}):
            return
        row = await _row(plan_id, owner_user_id) or row  # an OK (or expiry) got there first
    if row.status in ud.RUN_LIVE and plan_id in _TASKS:
        _CANCEL.add(plan_id)
        if plan_id in _WAIT:
            _WAIT[plan_id].set()
        return
    if row.status in ud.RUN_LIVE:  # no executor here: its end was never saved
        if await _flip(plan_id, row.status, {"status": "interrupted",
                                            "step_states": json.dumps(ud.close(json.loads(row.step_states))),
                                            "finished_at": datetime.utcnow()}):
            return
        row = await _row(plan_id, owner_user_id) or row
    raise Refused(409, f"this plan is {row.status}")


async def pick(plan_id: str, owner_user_id: str, step_id: str, ids: Any) -> None:
    """The owner's picks for the `needs_you` judge `step_id`, or Refused (404; 409 not waiting; 422 bad ids)."""
    row = await _row(plan_id, owner_user_id)
    if row is None:
        raise Refused(404, "plan not found")
    states = json.loads(row.step_states)
    i = next((i for i, s in enumerate(states) if s["id"] == step_id), None)
    if row.status != "needs_you" or i is None or states[i]["state"] != "needs_you" or plan_id not in _WAIT:
        raise Refused(409, f"this plan is {row.status}; step {step_id!r} is not waiting for your pick")
    if why := uj.owner_pick(states[i], ids):
        raise Refused(422, why)
    states[i] = uj.done(step_id, ids, "owner")
    if not await _flip(plan_id, "needs_you", {"status": "running", "step_states": json.dumps(states)}):
        raise Refused(409, "this plan is no longer waiting for your pick")
    if plan_id in _WAIT:
        _WAIT[plan_id].set()


async def _states(plan_id: str) -> list[dict[str, Any]]:
    async with get_session() as s:
        return json.loads((await s.get(UltraPlan, plan_id)).step_states)


async def _judge(plan_id: str, owner_user_id: str, i: int, step: dict[str, Any], states: list[dict[str, Any]],
                 results: dict[str, Any], spent: int) -> tuple[ud.PlanStatus | None, list[dict[str, Any]], int]:
    """Run judge step `i`: (a stop status or None, the states, the run's spend). Its ids land in results."""
    sid = step["id"]
    if spent >= upd.MAX_SPEND_MC:
        states[i] = uj.failed(sid, upd.RUN_SPEND_CAPPED)
        return "capped", states, spent
    try:
        cands = uj.candidates([ud.resolve(r, results) for r in step["refs"]])
    except (KeyError, ValueError):
        states[i] = uj.failed(sid, "no candidate list at " + ", ".join(
            f"${r['step']}.{r['path']}" for r in step["refs"]))
        return "failed", states, spent
    await _save(plan_id, [*states[:i], {"id": sid, "state": "started"}, *states[i + 1:]])
    states[i] = {"id": sid, "state": "started"}  # only once saved: a failed save leaves it pending (skipped)
    v = await ultra_judge.ask(step, cands, owner_user_id)
    spent += v.cost_mc
    if plan_id in _CANCEL:  # cancelled during the call: its picks are dropped, no needs_you, no notification
        states[i] = {"id": sid, "state": "skipped"}
        return "cancelled", states, spent
    if v.ids is None:
        states[i] = uj.failed(sid, v.error or "no picks")
        return ("capped" if v.capped else "failed"), states, spent
    if not step["confirm"]:
        states[i] = uj.done(sid, v.ids, "ai")
    else:
        _WAIT[plan_id] = ev = asyncio.Event()  # before the save: a cancel from here on wakes it
        try:
            states[i] = uj.needs_you(step, cands, v.ids)
            await _save(plan_id, states, "needs_you")
            await _notify(owner_user_id, plan_id, f"Ultra plan needs you: {step['question']}", "ultra_needs_you",
                          f"{plan_id}:{sid}")
            if plan_id not in _CANCEL:
                await ev.wait()
        finally:
            _WAIT.pop(plan_id, None)
        states = await _states(plan_id)  # the pick wrote the step done (and the plan running)
        if plan_id in _CANCEL or states[i]["state"] != "done":
            return "cancelled", states, spent
    results[sid] = {"ids": states[i]["result"]["ids"]}
    return None, states, spent


_OWNED_BY = {"bio_page": BioProfile}  # ud.OwnerCheck.kind → the table whose row's account_id is its Creator


async def _owner(check: ud.OwnerCheck) -> str | None:
    """The Creator of the row a step names (ud.owner_check), None when no such row."""
    table = _OWNED_BY[check.kind]
    async with get_session() as s:
        return (await s.execute(select(table.account_id).where(table.id == str(check.ref)))).scalar()


class _Lost(Exception):
    """The row is no longer running / needs_you (something else ended it): the run stops, nothing more is called."""


async def _save(plan_id: str, states: list[dict[str, Any]], status: ud.PlanStatus = "running") -> None:
    """Write the run's states (and status) only while the row is still running / needs_you; else _Lost."""
    values: dict[str, Any] = {"step_states": json.dumps(states), "status": status}
    if status in ud.FINAL:
        values["finished_at"] = datetime.utcnow()
    async with get_session() as s:
        won = (await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id,
                                                       UltraPlan.status.in_(sorted(ud.RUN_LIVE)))
                               .values(**values))).rowcount
    if won != 1:
        raise _Lost(f"plan {plan_id} is no longer running")


async def _step(tool: td.Tool, args: dict[str, Any], creds: toolbox.Creds, key: str) -> dict[str, Any] | None:
    """The call's result, or None when it raised or ran past STEP_TIMEOUT_S (shielded: a send keeps going)."""
    try:
        return await asyncio.wait_for(asyncio.shield(toolbox.call(tool, args, creds, plan_step=key)), STEP_TIMEOUT_S)
    except Exception:
        log.exception("ultra step %s: no answer", key)
        return None


async def _run(plan_id: str, owner_user_id: str, plan: ud.Plan, creds: toolbox.Creds) -> None:
    states, results, spent = ud.initial_states(plan), {}, 0
    by_id = {s["id"]: s for s in plan.steps}
    status: ud.PlanStatus = "done"
    try:
        for i, step in enumerate(plan.steps):
            if plan_id in _CANCEL:
                status = "cancelled"
                break
            if uj.is_judge(step):
                stop, states, spent = await _judge(plan_id, owner_user_id, i, step, states, results, spent)
                if stop:
                    status = stop
                    break
                continue
            tool = ud.TOOLS[step["tool"]]
            try:
                args = ud.substitute(step, results)
            except KeyError as e:
                states[i] = ud.step_end(step["id"], tool.effect, td.error(422, f"no value for {e.args[0]}"))
                status = "failed"
                break
            if chk := ud.owner_check(step, args, by_id):
                try:
                    why = None if await _owner(chk) == chk.want else td.error(409, chk.refused)
                except Exception:
                    log.exception("ultra plan %s: owner check failed", plan_id)
                    why = td.error(503, OWNER_UNREAD)
                if why:
                    states[i] = ud.step_end(step["id"], tool.effect, why)
                    status = "failed"
                    break
            start = ud.started(step, args)
            await _save(plan_id, [*states[:i], start, *states[i + 1:]])
            states[i] = start  # only once saved: a failed save leaves it pending (skipped), never uncertain
            result = await _step(tool, args, creds, f"{plan_id}:{step['id']}")
            states[i] = ud.step_end(step["id"], tool.effect, result, resolved=states[i].get("resolved"))
            if states[i]["state"] != "done":
                status = "failed"
                break
            results[step["id"]] = result
    except _Lost:  # cancelled / interrupted elsewhere: its end is not ours to write
        log.warning("ultra plan %s: no longer running; executor stops", plan_id)
        status = "failed"
    except asyncio.CancelledError:  # not an Exception: the task was cancelled (shutdown) mid-run; never `done`
        log.warning("ultra plan %s: executor cancelled", plan_id)
        status = "interrupted"
        raise
    except Exception:
        log.exception("ultra plan %s: executor crashed", plan_id)
        status = "failed"
    finally:
        states, saved = ud.close(states), False
        try:
            await asyncio.shield(_save(plan_id, states, status))  # a second cancel must not lose the end
            saved = True
        except Exception:  # row left as is: a `running` one is ended by a cancel (no executor here) or the next start
            log.exception("ultra plan %s: could not save its end", plan_id)
        finally:
            _CANCEL.discard(plan_id)
            _TASKS.pop(plan_id, None)
    if saved:  # the notification says what the page shows: only a saved end
        await _notify(owner_user_id, plan_id, uc.report_text(plan.summary, status, states))


async def _notify(owner_user_id: str, plan_id: str, text: str, kind: str = "ultra_done", key: str = "") -> None:
    try:
        from notifications_api import Notice, notify  # lazy: notifications_api imports settings
        await notify(owner_user_id, [Notice(kind, text, data={"href": ud.plan_path(plan_id)},
                                            dedupe=f"{kind}:{key or plan_id}")])
    except Exception:
        log.exception("%s notification failed (plan=%s)", kind, plan_id)


async def recover() -> int:
    """Relay start: every `running` / `planning` / `needs_you` plan → `interrupted` (`started` steps `uncertain`)."""
    async with get_session() as s:
        rows = (await s.execute(select(UltraPlan).where(
            UltraPlan.status.in_(sorted(ud.LIVE))))).scalars().all()
        for row in rows:
            row.status, states = ud.recovered(row.status, json.loads(row.step_states))
            row.step_states, row.finished_at = json.dumps(states), datetime.utcnow()
    return len(rows)
