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
STEP_TIMEOUT_S = 180.0
_TASKS: dict[str, asyncio.Task | None] = {}
_CANCEL: set[str] = set()
_WAIT: dict[str, asyncio.Event] = {}


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
    return ud.validate_plan((await _chained(ud.validate_plan(raw, owned))).raw(), owned)


def _stored(pid: str, plan: ud.Plan, now: datetime) -> dict[str, Any]:
    body = plan.as_json()
    return {"plan_json": json.dumps(body), "plan_sha256": ud.digest(body, pid), "status": "awaiting_ok",
            "created_at": now, "step_states": json.dumps(ud.initial_states(plan))}


def _proposed(pid: str, plan: ud.Plan, now: datetime) -> dict[str, Any]:
    return {"plan_id": pid, "status": "awaiting_ok", "expires_at": (now + ud.OK_TTL).isoformat() + "Z",
            "steps": plan.as_json()["steps"]}


async def propose(raw: Any, owner_user_id: str, owned: frozenset[str], source: str) -> dict[str, Any]:
    plan, pid, now = await checked(raw, owned), secrets.token_hex(16), datetime.utcnow()
    async with get_session() as s:
        s.add(UltraPlan(id=pid, owner_user_id=owner_user_id, source=source, **_stored(pid, plan, now)))
    return _proposed(pid, plan, now)


async def submit(plan_id: str, raw: Any, owned: frozenset[str]) -> dict[str, Any] | None:
    plan, now = await checked(raw, owned), datetime.utcnow()
    return _proposed(plan_id, plan, now) if await flip(plan_id, "planning", _stored(plan_id, plan, now)) else None


async def _row(plan_id: str, owner_user_id: str) -> UltraPlan | None:
    async with get_session() as s:
        row = await s.get(UltraPlan, plan_id)
        if row is None or row.owner_user_id != owner_user_id:
            return None
        if ud.expired(row.status, row.created_at, datetime.utcnow()):
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
    row = await _row(plan_id, owner_user_id)
    if row is None:
        raise Refused(404, "plan not found")
    if row.status != "awaiting_ok":
        raise Refused(409, f"this plan is {row.status}; it can no longer be approved")
    if sha256 != row.plan_sha256:
        raise Refused(409, "the plan changed since this card was shown; reload it and check again")
    if ud.digest(json.loads(row.plan_json), plan_id) != row.plan_sha256:
        raise Refused(409, "this plan was stored in an older form; propose it again")
    if plan_id in _TASKS:
        raise Refused(409, "this plan was already approved or cancelled")
    _TASKS[plan_id] = None
    won = 0
    try:
        async with get_session() as s:
            rc = (await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id, UltraPlan.status == "awaiting_ok")
                                  .values(status="running", approved_at=datetime.utcnow()))).rowcount
        won = rc
    finally:
        if won != 1:
            _TASKS.pop(plan_id, None)
    if won != 1:
        raise Refused(409, "this plan was already approved or cancelled")
    _TASKS[plan_id] = asyncio.create_task(_run(plan_id, owner_user_id, _plan(row), creds))


async def flip(plan_id: str, frm: ud.PlanStatus, values: dict[str, Any], *also: Any) -> bool:
    async with get_session() as s:
        return (await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id, UltraPlan.status == frm, *also)
                                .values(**values))).rowcount == 1


async def cancel(plan_id: str, owner_user_id: str) -> None:
    row = await _row(plan_id, owner_user_id)
    if row is None:
        raise Refused(404, "plan not found")
    if row.status == "planning":
        if await flip(plan_id, "planning", {"status": "cancelled", "finished_at": datetime.utcnow()}):
            return
        row = await _row(plan_id, owner_user_id) or row
    if row.status == "awaiting_ok":
        if await flip(plan_id, "awaiting_ok", {"status": "cancelled", "finished_at": datetime.utcnow(),
                                                "step_states": json.dumps(ud.close(json.loads(row.step_states)))}):
            return
        row = await _row(plan_id, owner_user_id) or row
    if row.status in ud.RUN_LIVE and plan_id in _TASKS:
        _CANCEL.add(plan_id)
        if plan_id in _WAIT:
            _WAIT[plan_id].set()
        return
    if row.status in ud.RUN_LIVE:
        if await flip(plan_id, row.status, {"status": "interrupted",
                                            "step_states": json.dumps(ud.close(json.loads(row.step_states))),
                                            "finished_at": datetime.utcnow()}):
            return
        row = await _row(plan_id, owner_user_id) or row
    raise Refused(409, f"this plan is {row.status}")


async def pick(plan_id: str, owner_user_id: str, step_id: str, ids: Any) -> None:
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
    # Only over the states read: a stale tab's pick never lands on a later judge.
    if not await flip(plan_id, "needs_you", {"status": "running", "step_states": json.dumps(states)},
                      UltraPlan.step_states == row.step_states):
        raise Refused(409, "this plan is no longer waiting for your pick")
    if plan_id in _WAIT:
        _WAIT[plan_id].set()


async def _states(plan_id: str) -> list[dict[str, Any]]:
    async with get_session() as s:
        return json.loads((await s.get(UltraPlan, plan_id)).step_states)


async def _judge(plan_id: str, owner_user_id: str, i: int, step: dict[str, Any], states: list[dict[str, Any]],
                 results: dict[str, Any], spent: int) -> tuple[ud.PlanStatus | None, list[dict[str, Any]], int]:
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
    states[i] = {"id": sid, "state": "started"}
    v = await ultra_judge.ask(step, cands, owner_user_id)
    spent += v.cost_mc
    if plan_id in _CANCEL:
        states[i] = {"id": sid, "state": "skipped"}
        return "cancelled", states, spent
    if v.ids is None:
        states[i] = uj.failed(sid, v.error or "no picks")
        return ("capped" if v.capped else "failed"), states, spent
    if not step["confirm"]:
        states[i] = uj.done(sid, v.ids, "ai")
    else:
        _WAIT[plan_id] = ev = asyncio.Event()
        try:
            states[i] = uj.needs_you(step, cands, v.ids)
            await _save(plan_id, states, "needs_you")
            await _notify(owner_user_id, plan_id, f"Ultra plan needs you: {step['question']}", "ultra_needs_you",
                          f"{plan_id}:{sid}")
            if plan_id not in _CANCEL:
                await ev.wait()
        finally:
            _WAIT.pop(plan_id, None)
        states = await _states(plan_id)
        if plan_id in _CANCEL or states[i]["state"] != "done":
            return "cancelled", states, spent
    results[sid] = {"ids": states[i]["result"]["ids"]}
    return None, states, spent


_OWNED_BY = {"bio_page": BioProfile}


async def _owner(check: ud.OwnerCheck) -> str | None:
    table = _OWNED_BY[check.kind]
    async with get_session() as s:
        return (await s.execute(select(table.account_id).where(table.id == str(check.ref)))).scalar()


class _Lost(Exception):
    pass


async def _save(plan_id: str, states: list[dict[str, Any]], status: ud.PlanStatus = "running") -> None:
    values: dict[str, Any] = {"step_states": json.dumps(states), "status": status}
    if status in ud.FINAL:
        values["finished_at"] = datetime.utcnow()
    async with get_session() as s:
        won = (await s.execute(update(UltraPlan).where(UltraPlan.id == plan_id,
                                                       UltraPlan.status.in_(sorted(ud.RUN_LIVE)))
                               .values(**values))).rowcount
    if won != 1:
        raise _Lost(f"plan {plan_id} is no longer running")


async def _step(tool: td.Tool, args: dict[str, Any], creds: toolbox.Creds, key: str,
                owner: str) -> dict[str, Any] | None:
    try:
        pid = key.partition(":")[0]
        return await asyncio.wait_for(asyncio.shield(toolbox.call(tool, args, creds, plan_step=key, plan_owner=owner,
                                                                  live=lambda: pid not in _CANCEL)),
                                      STEP_TIMEOUT_S)
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
            # Checkpoint before the call so recovery marks an unfinished step uncertain instead of replaying it.
            await _save(plan_id, [*states[:i], start, *states[i + 1:]])
            if plan_id in _CANCEL:
                status = "cancelled"
                break
            states[i] = start
            result = await _step(tool, args, creds, f"{plan_id}:{step['id']}", owner_user_id)
            if result is not None and (result.get("error") or {}).get("detail") == toolbox.NOT_LIVE:
                states[i] = {"id": step["id"], "state": "skipped"}
                status = "cancelled"
                break
            states[i] = ud.step_end(step["id"], tool.effect, result, resolved=states[i].get("resolved"),
                                    ended_at=datetime.utcnow().isoformat() + "Z")
            if states[i]["state"] != "done":
                status = "failed"
                break
            results[step["id"]] = result
    except _Lost:
        log.warning("ultra plan %s: no longer running; executor stops", plan_id)
    except asyncio.CancelledError:
        log.warning("ultra plan %s: executor cancelled", plan_id)
        status = "interrupted"
        raise
    except Exception:
        log.exception("ultra plan %s: executor crashed", plan_id)
        status = "failed"
    finally:
        states, saved = ud.close(states), False
        try:
            await asyncio.shield(_save(plan_id, states, status))
            saved = True
        except _Lost:
            pass
        except Exception:
            log.exception("ultra plan %s: could not save its end", plan_id)
        finally:
            _CANCEL.discard(plan_id)
            _TASKS.pop(plan_id, None)
    if saved:
        await _notify(owner_user_id, plan_id, uc.report_text(plan.summary, status, states))


async def _notify(owner_user_id: str, plan_id: str, text: str, kind: str = "ultra_done", key: str = "") -> None:
    try:
        from notifications_api import Notice, notify
        await notify(owner_user_id, [Notice(kind, text, data={"href": ud.plan_path(plan_id)},
                                            dedupe=f"{kind}:{key or plan_id}")])
    except Exception:
        log.exception("%s notification failed (plan=%s)", kind, plan_id)


async def recover() -> int:
    async with get_session() as s:
        rows = (await s.execute(select(UltraPlan).where(
            UltraPlan.status.in_(sorted(ud.LIVE))))).scalars().all()
        for row in rows:
            row.status, states = ud.recovered(row.status, json.loads(row.step_states))
            row.step_states, row.finished_at = json.dumps(states), datetime.utcnow()
    return len(rows)
