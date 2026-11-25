# No task.cancel: it would cut an LLM call mid-reservation; the cancel route flips the row and the next progress write misses.
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime
from typing import Any

import llm_client
import toolbox
import toolbox_decide as td
import ultra_decide as ud
import ultra_plan_decide as upd
import ultra_run
from db.engine import get_session
from db.models import UltraPlan
from llm_models import MODELS

log = logging.getLogger("of-relay.ultra")

_TASKS: dict[str, asyncio.Task] = {}

CRASHED = "Planning failed — try again."
IDLE = "The planner gave no plan — rephrase the request and try again."
TURNS_CAPPED = f"Stopped at {upd.MAX_TURNS} turns without a plan — make the request smaller."
SPEND_CAPPED = f"Stopped at the {upd.MAX_SPEND_MC // 100}¢ planning budget without a plan."


def _body(prog: dict[str, Any]) -> str:
    return json.dumps({"summary": "", "steps": [], "planning": prog})


async def start(request: str, owner_user_id: str, owned: frozenset[str], creds: toolbox.Creds) -> str:
    provider = MODELS[upd.MODEL].provider
    if (await llm_client.cap_state(None, provider, upd.MODEL, user_id=owner_user_id))["capped"]:
        raise ultra_run.Refused(429, upd.DAILY_CAPPED)
    pid = secrets.token_hex(16)
    async with get_session() as s:
        s.add(UltraPlan(id=pid, owner_user_id=owner_user_id, source="ui", plan_json=_body(upd.progress(0, None)),
                        plan_sha256="", status="planning", created_at=datetime.utcnow(), step_states="[]"))
    _TASKS[pid] = asyncio.create_task(_loop(pid, request, owner_user_id, owned, creds))
    return pid


async def _read(name: str, raw_args: str, creds: toolbox.Creds) -> str:
    args = upd.parse_args(raw_args)
    if args is None:
        return upd.bad_args_text()
    try:
        result = await asyncio.wait_for(toolbox.call(upd.READ_TOOLS[name], args, creds), ultra_run.STEP_TIMEOUT_S)
    except Exception:
        log.exception("ultra planning: %s gave no answer", name)
        result = td.error(504, f"{name} gave no answer")
    return upd.result_text(result)


async def _submit(plan_id: str, raw_args: str, owned: frozenset[str]) -> tuple[str, bool]:
    args = upd.parse_args(raw_args)
    if args is None:
        return upd.bad_args_text(), False
    try:
        stored = await ultra_run.submit(plan_id, args, owned)
    except ud.PlanError as e:
        return upd.plan_error_text(e.errors), False
    return upd.result_text(stored or {}), True


async def _loop(plan_id: str, request: str, owner_user_id: str, owned: frozenset[str],
                creds: toolbox.Creds) -> None:
    msgs, turns, spent, idle, last = upd.messages(request), 0, 0, 0, None
    status: ud.PlanStatus = "failed"
    error: str | None = CRASHED
    try:
        while True:
            if upd.capped(turns, spent):
                status, error = "capped", TURNS_CAPPED if turns >= upd.MAX_TURNS else SPEND_CAPPED
                break
            if not await ultra_run.flip(plan_id, "planning", {"plan_json": _body(upd.progress(turns, last))}):
                return
            res = await llm_client.chat(model=upd.MODEL, messages=msgs, purpose=upd.PURPOSE, account_id=None,
                                        user_id=owner_user_id, tools=upd.TOOLS, temperature=0.2)
            turns, spent = turns + 1, spent + (res.cost_cents or 0)
            msgs.append({"role": "assistant", "content": res.content or "", "tool_calls": res.tool_calls}
                        if res.tool_calls else {"role": "assistant", "content": res.content or ""})
            if not res.tool_calls:
                idle += 1
                if idle >= upd.MAX_IDLE:
                    error = IDLE
                    break
                msgs.append({"role": "user", "content": upd.NUDGE})
                continue
            idle = 0
            for n, call in enumerate(res.tool_calls):
                name, raw = call["function"]["name"], call["function"]["arguments"]
                if n >= upd.MAX_CALLS:
                    msgs.append({"role": "tool", "tool_call_id": call["id"], "content": upd.too_many_text()})
                    continue
                last = upd.shown_tool(name)
                if name == upd.SUBMIT:
                    text, over = await _submit(plan_id, raw, owned)
                    if over:
                        return
                elif name in upd.READ_TOOLS:
                    text = await _read(name, raw, creds)
                else:
                    text = upd.refused_text(name)
                msgs.append({"role": "tool", "tool_call_id": call["id"], "content": text})
    except asyncio.CancelledError:
        status, error = "interrupted", None
        raise
    except Exception as e:
        if (fail := llm_client.failure(e, **upd.FAILURE_TEXT)) is None:
            log.exception("ultra planning %s crashed", plan_id)
        else:
            status, error = ("capped" if fail[0] else "failed"), fail[1]
    finally:
        _TASKS.pop(plan_id, None)
        try:
            await asyncio.shield(ultra_run.flip(plan_id, "planning", {
                "status": status, "finished_at": datetime.utcnow(),
                "plan_json": _body(upd.progress(turns, last, error))}))
        except Exception:
            log.exception("ultra planning %s: could not save its end", plan_id)
