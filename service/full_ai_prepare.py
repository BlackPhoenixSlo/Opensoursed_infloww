"""service/full_ai_prepare.py — Prepare content: one owner-pressed chain that makes a
Creator's vault sellable for Full AI (docs/spec/phase-03b-full-ai-selling-test-chat.md).

  read_facts(account_id)  what is already done: harvested (`vault_runs._walked`), undescribed
                          (`describe_selection("undescribed")`), unflagged (`_flags_todo`), ai_folders
  steps_for(facts)        pure: which of harvest / describe / folders still need running
  start(account_id)       claim the chain and run it in the background; a running run is returned as is
  view(account_id)        the run as the status route shows it

The chain, in order, each step only if still missing (facts re-read before each step):
  harvest   the Collect button's setup (`vault_ai_api.claim_collect`) + `_run_collect`
  describe  `_claim_describe` + `_run_describe_all("undescribed")`, then the flags sweep on
            items still missing Jev flags (`_flags_todo` / `_run_flags_all`)
  folders   `vault_of_folders.build_ai_folders` with the Folder plan's defaults, never mirrored to OF
Each step reuses its job's own running guard (held → `busy`, the chain stops) and reads its
state from the job's RECORDED outcome (the run row, the sweeps' progress snapshots), never from
the coroutine returning: the jobs record failures and return normally.

Nothing starts it but the owner's press (POST /admin/full-ai/prepare-content): no timer, no
page load, no sell switch. The Turn path never imports it (it reaches the OF client).

Step states: pending | running | done | failed | busy | skipped. A cap or missing key on
describe reads the ONE budget sentence (`vault_ai_vision._vision_budget`).

ASSUMPTION: state `pending` for steps not reached yet; overturned if ticket 49's UI wants only the spec's five states.
ASSUMPTION: a restart reads `run_id: null` (progress is in memory), not `interrupted`; overturned if progress must survive restarts.
"""
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
import vault_runs
import vault_scripts
from db.engine import get_session
from db.models import VaultCacheRun, VaultFolder, VaultItem
from isotime import iso_z
from vault_ai_vision_decide import describe_selection

log = logging.getLogger(__name__)

STEPS = ("harvest", "describe", "folders")
# The Folder plan's own defaults (`useVaultCache.ts` useApplyFolderPlan), mirror always off.
FOLDER_DEFAULTS: dict[str, Any] = {"keep": 2, "solo": False, "topics": [], "split": True}
STOPPED = "not run: an earlier step stopped the chain"

_running: set[str] = set()              # accounts whose chain runs now (process-local)
_runs: dict[str, dict[str, Any]] = {}   # account → its latest run (in memory; a restart forgets it)


def _now() -> str:
    return iso_z(datetime.utcnow())


# ── What is done ─────────────────────────────────────────────────────

async def read_facts(account_id: str) -> dict[str, Any]:
    async with get_session() as s:
        harvested = (await s.execute(select(VaultCacheRun.id).where(
            VaultCacheRun.account_id == account_id, vault_runs._walked()).limit(1))).first() is not None
        undescribed = await s.scalar(select(func.count()).select_from(VaultItem).where(
            describe_selection(account_id, "undescribed", "v2")))
        ai_folders = (await s.execute(select(VaultFolder.id).where(
            VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None),
            VaultFolder.name.startswith(vault_scripts.AI_FOLDER_PREFIX)).limit(1))).first() is not None
    unflagged = len(await vault_ai_vision._flags_todo(account_id))
    return {"harvested": harvested, "undescribed": int(undescribed or 0),
            "unflagged": unflagged, "ai_folders": ai_folders}


def _step(name: str, state: str, detail: str = "", counts: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "state": state, "detail": detail, "counts": counts or {}}


def steps_for(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """harvest / describe / folders, each `pending` (to run) or `skipped` (done already).
    Before a harvest the mirror is empty, so describe can't be judged yet: pending."""
    todo = {"undescribed": facts["undescribed"], "unflagged": facts["unflagged"]}
    return [
        _step("harvest", "skipped", "already harvested") if facts["harvested"] else _step("harvest", "pending"),
        _step("describe", "pending", counts=todo) if not facts["harvested"] or any(todo.values())
        else _step("describe", "skipped", "every item described and flagged"),
        _step("folders", "skipped", "AI folders exist") if facts["ai_folders"] else _step("folders", "pending"),
    ]


# ── The steps (each returns its final step dict) ─────────────────────

async def _harvest(account_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    try:
        run_id = await vault_ai_api.claim_collect(account_id)
    except HTTPException as e:
        if e.status_code == 409:
            return _step("harvest", "busy", "a vault collect is already running")
        raise
    await vault_ai_api._run_collect(account_id, run_id, pause_every=0)   # nobody to ask: never pauses
    async with get_session() as s:
        run = await s.get(VaultCacheRun, run_id)
    counts = {"seen": run.total_seen or 0, "pages": run.pages_done or 0}
    if run.status != "done":
        return _step("harvest", "failed", run.error or f"collect ended {run.status}", counts)
    return _step("harvest", "done", run.error or "", counts)   # a capped walk: done, the cap's text


async def _budget_sentence(account_id: str) -> str:
    return (await vault_ai_vision._vision_budget(account_id))["blocked_reason"]


async def _sweep_failure(account_id: str, prog: dict[str, Any] | None) -> str | None:
    """The sweep's recorded stop, or None when it ran through clean: a key error or a stop
    (`vault_sweep.SweepStop` / breaker) reads its own message + fix, a cap the budget sentence, an abort its recorded error, any failed item "<failed> of <done> items
    failed: <first error>" (the step vocabulary has no partial: a run with failures is not done)."""
    if prog is None:
        return "the sweep stopped before recording progress (see the relay log)"
    for k in ("key_error", "stop"):   # the relay's own sentences: what is wrong + the fix
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
    """described / failed / total from a sweep snapshot (an early abort records none)."""
    if not prog or "done" not in prog:
        return {}
    return {"described": prog["done"] - prog["failed"], "failed": prog["failed"], "total": prog["total"]}


async def _describe(account_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    if facts["undescribed"]:
        try:
            await vault_ai_vision._claim_describe(account_id, "qwen3-vl-30b")
        except HTTPException as e:
            if e.status_code == 409:
                return _step("describe", "busy", "a describe sweep is already running")
            if e.status_code != 429:
                raise
            return _step("describe", "failed", await _budget_sentence(account_id))
        except llm_client.LLMKeyError:
            return _step("describe", "failed", await _budget_sentence(account_id))
        vault_ai_vision._describe_progress.pop(account_id, None)
        await vault_ai_vision._run_describe_all(account_id, "undescribed")
        prog = vault_ai_vision._describe_progress.get(account_id)
        counts = _sweep_counts(prog)
        stop = await _sweep_failure(account_id, prog)
        if stop:
            return _step("describe", "failed", stop, counts)
    todo = await vault_ai_vision._flags_todo(account_id)
    if todo:
        budget = await vault_ai_vision._vision_budget(account_id)
        if budget["key_missing"]:   # the Flags button's own refusal (`flags_all`'s 424)
            return _step("describe", "failed", budget["blocked_reason"], counts)
        if not vault_ai_vision.claim_flags(account_id):
            return _step("describe", "busy", "a flags sweep is already running", counts)
        vault_ai_vision._flags_progress.pop(account_id, None)
        await vault_ai_vision._run_flags_all(account_id, todo)   # releases the claim in its finally
        prog = vault_ai_vision._flags_progress.get(account_id)
        counts["flagged"] = _sweep_counts(prog).get("described", 0)
        stop = await _sweep_failure(account_id, prog)
        if stop:
            return _step("describe", "failed", stop, counts)
    return _step("describe", "done", "", counts)


async def _folders(account_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    res = await vault_of_folders.build_ai_folders(account_id, **FOLDER_DEFAULTS, mirror_to_of=False)
    return _step("folders", "done", "", {"folders": res["folders"], "items": res["items"]})


# ── The chain ────────────────────────────────────────────────────────

_RUN = {"harvest": _harvest, "describe": _describe, "folders": _folders}   # keyed by STEPS

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
                steps[i] = await _RUN[name](account_id, facts)
            except Exception as e:  # noqa: BLE001 — the step's failure, recorded, never the relay's
                log.exception("prepare_content %s failed account=%s", name, account_id)
                steps[i] = _step(name, "failed", f"{type(e).__name__}: {e}"[:300])
            state = steps[i]["state"]
            # A failed describe (cap, key) still leaves folders worth building on what is described.
            if state == "busy" or (state == "failed" and name != "describe"):
                for j in range(i + 1, len(STEPS)):
                    steps[j] = _step(STEPS[j], "skipped", STOPPED)
                break
    finally:
        run["finished_at"] = _now()
        _running.discard(account_id)


async def start(account_id: str) -> dict[str, Any]:
    """Claim the account's one chain (before any await) and start it; a press while it
    runs gets the running run back."""
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
    """The account's latest run (a copy), or the idle shape when none ran in this process."""
    run = _runs.get(account_id)
    if run is None:
        return {"run_id": None, "steps": [], "started_at": None, "finished_at": None}
    return {**run, "steps": [dict(s) for s in run["steps"]]}
