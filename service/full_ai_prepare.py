# Read each step's state from the job's recorded outcome, never the coroutine returning: jobs record failures and return normally.
# Started only by the owner's press: no timer, page load or sell switch.
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

import llm_client
import vault_ai_api
import vault_ai_vision
import vault_of_folders
import vault_pack_picker
import vault_runs
import vault_scripts
from db.engine import get_session
from db.models import VaultCacheRun, VaultFolder, VaultItem
from isotime import iso_z
from vault_ai_vision_decide import describe_selection

log = logging.getLogger(__name__)

STEPS = ("harvest", "describe", "folders", "feet")
# `keep` is the vault's constant, not a copy: a literal 2 left prepare content with 2 script folders, the modal with 10.
FOLDER_DEFAULTS: dict[str, Any] = {"keep": vault_scripts.DEFAULT_KEEP_SCRIPTS, "solo": False, "topics": [],
                                   "split": True}
STOPPED = "not run: an earlier step stopped the chain"
FEET = vault_pack_picker.category("feet")
CHUNK = 2000

_running: set[str] = set()
_runs: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return iso_z(datetime.utcnow())



async def read_facts(account_id: str) -> dict[str, Any]:
    async with get_session() as s:
        harvested = (await s.execute(select(VaultCacheRun.id).where(
            VaultCacheRun.account_id == account_id, vault_runs._walked()).limit(1))).first() is not None
        ai_folders = (await s.execute(select(VaultFolder.id).where(
            VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None),
            VaultFolder.name.startswith(vault_scripts.AI_FOLDER_PREFIX)).limit(1))).first() is not None
        feet_pack = (await s.execute(select(VaultFolder.id).where(
            VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None),
            VaultFolder.name.in_(FEET.folder_names)).limit(1))).first() is not None
    unflagged = len(await vault_ai_vision._flags_todo(account_id))
    return {"harvested": harvested, "undescribed": await _undescribed(account_id),
            "unflagged": unflagged, "ai_folders": ai_folders, "feet_pack": feet_pack}


def _step(name: str, state: str, detail: str = "", counts: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "state": state, "detail": detail, "counts": counts or {}}


def steps_for(facts: dict[str, Any]) -> list[dict[str, Any]]:
    todo = {"undescribed": facts["undescribed"], "unflagged": facts["unflagged"]}
    return [
        _step("harvest", "skipped", "already harvested") if facts["harvested"] else _step("harvest", "pending"),
        _step("describe", "pending", counts=todo) if not facts["harvested"] or any(todo.values())
        else _step("describe", "skipped", "every item described and flagged"),
        _step("folders", "skipped", "AI folders exist") if facts["ai_folders"] else _step("folders", "pending"),
        # An existing pack is the operator's: a second filing would put back what they took off a rung.
        _step("feet", "skipped", "Feet pack exists") if facts["feet_pack"] else _step("feet", "pending"),
    ]



async def _harvest(account_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    try:
        run_id = await vault_ai_api.claim_collect(account_id)
    except HTTPException as e:
        if e.status_code == 409:
            return _step("harvest", "busy", "a vault collect is already running")
        raise
    await vault_ai_api._run_collect(account_id, run_id, pause_every=0)
    async with get_session() as s:
        run = await s.get(VaultCacheRun, run_id)
    counts = {"seen": run.total_seen or 0, "pages": run.pages_done or 0}
    if run.status != "done":
        return _step("harvest", "failed", run.error or f"collect ended {run.status}", counts)
    return _step("harvest", "done", run.error or "", counts)


async def _budget_sentence(account_id: str) -> str:
    return (await vault_ai_vision._vision_budget(account_id))["blocked_reason"]


async def _sweep_failure(account_id: str, prog: dict[str, Any] | None) -> str | None:
    if prog is None:
        return "the sweep stopped before recording progress (see the relay log)"
    for k in ("key_error", "stop"):
        if isinstance(prog.get(k), dict):
            return f"{prog[k]['message']} {prog[k]['fix']}"
    if prog.get("capped"):
        return await _budget_sentence(account_id) or prog.get("error") or "the sweep stopped early"
    if prog.get("aborted"):
        return prog.get("error") or "the sweep stopped early"
    if prog.get("failed"):
        why = f": {prog['error']}" if prog.get("error") else ""
        return f"{prog['failed']} of {prog.get('done', prog['failed'])} items failed{why}"
    return None


def _sweep_counts(prog: dict[str, Any] | None) -> dict[str, Any]:
    if not prog or "done" not in prog:
        return {}
    return {"described": prog["done"] - prog["failed"], "failed": prog["failed"], "total": prog["total"]}


def _add(total: dict[str, Any], prog: dict[str, Any] | None) -> None:
    for k, v in _sweep_counts(prog).items():
        total[k] = total.get(k, 0) + v


async def _undescribed(account_id: str) -> int:
    async with get_session() as s:
        return int(await s.scalar(select(func.count()).select_from(VaultItem).where(
            describe_selection(account_id, "undescribed", "v2"))) or 0)


async def _describe(account_id: str, facts: dict[str, Any], progress=lambda counts: None) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    left = facts["undescribed"]
    while left:
        try:
            await vault_ai_vision._claim_describe(account_id, "qwen3-vl-30b")
        except HTTPException as e:
            if e.status_code == 409:
                return _step("describe", "busy", "a describe sweep is already running", counts)
            if e.status_code != 429:
                raise
            return _step("describe", "failed", await _budget_sentence(account_id), counts)
        except llm_client.LLMKeyError:
            return _step("describe", "failed", await _budget_sentence(account_id), counts)
        vault_ai_vision._describe_progress.pop(account_id, None)
        await vault_ai_vision._run_describe_all(account_id, "undescribed", limit=CHUNK)
        prog = vault_ai_vision._describe_progress.get(account_id)
        _add(counts, prog)
        stop = await _sweep_failure(account_id, prog)
        if stop:
            return _step("describe", "failed", stop, counts)
        before, left = left, await _undescribed(account_id)
        progress({**counts, "undescribed": left})
        if left >= before:
            break
    todo = await vault_ai_vision._flags_todo(account_id, limit=CHUNK)
    while todo:
        budget = await vault_ai_vision._vision_budget(account_id)
        if budget["key_missing"]:
            return _step("describe", "failed", budget["blocked_reason"], counts)
        if not vault_ai_vision.claim_flags(account_id):
            return _step("describe", "busy", "a flags sweep is already running", counts)
        vault_ai_vision._flags_progress.pop(account_id, None)
        await vault_ai_vision._run_flags_all(account_id, todo)
        prog = vault_ai_vision._flags_progress.get(account_id)
        counts["flagged"] = counts.get("flagged", 0) + _sweep_counts(prog).get("described", 0)
        stop = await _sweep_failure(account_id, prog)
        if stop:
            return _step("describe", "failed", stop, counts)
        prev, todo = set(todo), await vault_ai_vision._flags_todo(account_id, limit=CHUNK)
        progress({**counts, "unflagged": len(await vault_ai_vision._flags_todo(account_id))})
        if set(todo) == prev:
            break
    return _step("describe", "done", "", counts)


async def _folders(account_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    res = await vault_of_folders.build_ai_folders(account_id, **FOLDER_DEFAULTS, mirror_to_of=False)
    return _step("folders", "done", "", {"folders": res["folders"], "items": res["items"]})


async def _feet(account_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    queue = [c for c in (await vault_pack_picker.candidates(account_id, FEET, limit=2000))["candidates"]
             if not c["rung"]]
    verdicts = {c["media_id"]: c["suggested"] for c in queue if c["preselect"]}
    if verdicts:
        await vault_pack_picker.triage(account_id, FEET, verdicts)
    return _step("feet", "done", "", {"filed": len(verdicts), "to_check": sum(1 for c in queue if c["possible"])})



_RUN = {"harvest": _harvest, "describe": _describe, "folders": _folders, "feet": _feet}

async def _chain(account_id: str, run: dict[str, Any]) -> None:
    steps = run["steps"]
    try:
        for i, name in enumerate(STEPS):
            facts = await read_facts(account_id)
            decided = steps_for(facts)[i]
            if decided["state"] == "skipped":
                steps[i] = decided
                continue
            steps[i] = _step(name, "running", counts=decided["counts"])
            try:
                if name == "describe":
                    def _progress(counts: dict[str, Any], i: int = i) -> None:
                        steps[i] = _step("describe", "running", counts=counts)
                    steps[i] = await _describe(account_id, facts, _progress)
                else:
                    steps[i] = await _RUN[name](account_id, facts)
            except Exception as e:  # noqa: BLE001 — the step's failure, recorded, never the relay's
                log.exception("prepare_content %s failed account=%s", name, account_id)
                steps[i] = _step(name, "failed", f"{type(e).__name__}: {e}"[:300])
            state = steps[i]["state"]
            if state == "busy" or (state == "failed" and name != "describe"):
                for j in range(i + 1, len(STEPS)):
                    steps[j] = _step(STEPS[j], "skipped", STOPPED)
                break
    finally:
        run["finished_at"] = _now()
        _running.discard(account_id)


async def start(account_id: str) -> dict[str, Any]:
    if account_id in _running:
        return view(account_id)
    _running.add(account_id)
    try:
        steps = steps_for(await read_facts(account_id))
    except BaseException:
        _running.discard(account_id)
        raise
    run = {"run_id": uuid.uuid4().hex, "steps": steps, "started_at": _now(), "finished_at": None}
    _runs[account_id] = run
    asyncio.create_task(_chain(account_id, run))
    return view(account_id)


def view(account_id: str) -> dict[str, Any]:
    run = _runs.get(account_id)
    if run is None:
        return {"run_id": None, "steps": [], "started_at": None, "finished_at": None}
    return {**run, "steps": [dict(s) for s in run["steps"]]}
