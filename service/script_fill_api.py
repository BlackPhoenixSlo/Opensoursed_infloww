from __future__ import annotations

import asyncio
import json
import weakref
from datetime import datetime
from typing import Any, NamedTuple

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

import permissions
import script_fill_decide as decide
import vault_ai_vision
import vault_jev_pass
import vault_settings
from agency_context import agency_context
from auth import assert_account_owned, require_actor_account_ids
from automations import full_ai_sell as fs
from automations._reserved_scripts import is_reserved_name
from db.engine import get_session
from db.models import SavedReply, UserAccount, VaultItem
from db.of_writer import immediate_session
from saved_replies_api import IDS_MAX, IN_CHUNK, sync_sequences
from vault_ai_api import assert_owner_scope

router = APIRouter(prefix="/admin/saved-replies", tags=["scripts"])

NO_VAULT_PRO = "no Vault Pro access"
_DESCRIBE_ALL = "/admin/vault-ai/describe-all"


class _PlanBody(BaseModel):
    sequence: str


class _ApplyBody(_PlanBody):
    fingerprint: str | None = None


class _UndoEntry(BaseModel):
    id: int
    media_ids: list[int] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    price_cents: int = 0
    price_set: bool = False


class _UndoBody(_PlanBody):
    undo: list[_UndoEntry] = Field(..., max_length=IDS_MAX)



async def _gate(account_id: str) -> str:
    account_id = (account_id or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail={"error": "account_id_required"})
    assert_account_owned(account_id)
    await assert_owner_scope(account_id)
    return account_id


async def _vault_pro_denied(account_id: str) -> bool:
    pages = permissions.route_pages(_DESCRIBE_ALL, "POST") or ()
    refusal, _ = await permissions.route_refusal(pages, "POST", _DESCRIBE_ALL, [account_id])
    if refusal is not None and refusal.status_code != 403:
        raise refusal
    return refusal is not None


async def _blocked_reason(account_id: str) -> str | None:
    if await _vault_pro_denied(account_id):
        return NO_VAULT_PRO
    budget = await vault_ai_vision._vision_budget(account_id)
    if budget.get("blocked_reason"):
        return str(budget["blocked_reason"])
    jev = await vault_jev_pass.plan(account_id)
    if not jev.get("ready"):
        return str(jev.get("reason") or "Jev is not ready")
    return None


async def _describe_inputs(account_id: str) -> tuple[dict[str, Any], str | None]:
    return (await vault_ai_vision.describe_coverage(account_id, decide.DESCRIBE_TARGET),
            await _blocked_reason(account_id))



_PLAN_GATES: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _plan_gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _PLAN_GATES.get(loop)
    if gate is None:
        gate = _PLAN_GATES[loop] = asyncio.Semaphore(1)
    return gate



def _row_dict(r: SavedReply) -> dict[str, Any]:
    return {"id": r.id, "script_id": r.script_id, "script_step": r.script_step, "text": r.text,
            "notes": r.notes, "price_cents": r.price_cents or 0, "media_json": r.media_json,
            "previews_json": r.previews_json}


async def _sequence(s: Any, account_id: str, sequence: str) -> list[SavedReply]:
    rows = (await s.execute(select(SavedReply).where(SavedReply.account_id == account_id,
                                                      SavedReply.script_id == sequence)
                            .order_by(SavedReply.id))).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "sequence_not_found"})
    return list(rows)


async def _used_ids(s: Any, account_id: str, sequence: str) -> set[int]:
    got = (await s.execute(select(SavedReply.media_json, SavedReply.previews_json).where(
        SavedReply.account_id == account_id, SavedReply.script_id.is_not(None),
        SavedReply.script_id != sequence))).all()
    return decide.sequence_media_ids(r._mapping for r in got)


async def _agency(account_id: str) -> str | None:
    if require_actor_account_ids() is None:
        return None
    return (await agency_context(account_id=account_id)).agency_user_id


async def _template_prices(s: Any, account_id: str, sequence: str, agency: str | None) -> dict[int, int]:
    owners = sorted((await s.execute(select(UserAccount.user_id).where(
        UserAccount.account_id == account_id))).scalars().all())
    if not owners:
        return {}
    owner = agency if agency in owners else owners[0]
    siblings = set((await s.execute(select(UserAccount.account_id).where(
        UserAccount.user_id == owner, UserAccount.account_id != account_id))).scalars().all())
    held = require_actor_account_ids()
    if held is not None:
        siblings &= set(held)
    if not siblings:
        return {}
    by: dict[str, dict[int, int]] = {}
    for acct, step, cents in (await s.execute(select(
            SavedReply.account_id, SavedReply.script_step, SavedReply.price_cents).where(
            SavedReply.account_id.in_(sorted(siblings)), SavedReply.script_id == sequence,
            SavedReply.script_step.is_not(None), SavedReply.price_cents > 0))).all():
        steps = by.setdefault(str(acct), {})
        steps[int(step)] = max(steps.get(int(step), 0), int(cents))
    if not by:
        return {}
    pick = min(by, key=lambda a: (-len(by[a]), a))
    return by[pick]


class _Vault:

    def __init__(self, items: list[dict[str, Any]], groups: list[list[int]], prints: dict[int, Any],
                 live: dict[int, tuple[str, str | None]], standard_folders: bool,
                 solo_sequences: bool) -> None:
        self.items, self.groups, self.prints = items, groups, prints
        self.live = live
        self.standard_folders = standard_folders
        self.solo_sequences = solo_sequences


async def _load_vault(account_id: str, s: Any = None) -> _Vault:
    got = await fs.load_rows(account_id)
    if isinstance(got, fs.Refusal):
        raise HTTPException(status_code=503, detail={"error": "inventory_unknown"})
    rows, groups, prints = got
    query = (select(VaultItem.media_id, VaultItem.review_state, VaultItem.operator_overrides_json,
                    VaultItem.kind, VaultItem.thumb_url)
             .where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None)))
    if s is None:
        async with get_session() as own:
            got_live = (await own.execute(query)).all()
    else:
        got_live = (await s.execute(query)).all()
    extra = {int(m): (rs, ov, kind, thumb) for m, rs, ov, kind, thumb in got_live}
    switches = await vault_settings.load(account_id)
    standard = bool(switches.get("standard_folders"))
    solo = bool(switches.get("solo_sequences", True))
    items = []
    for r in rows:
        if int(r["media_id"]) not in extra:
            continue
        rs, ov, _kind, _thumb = extra[int(r["media_id"])]
        items.append(decide.effective({**r, "account_id": account_id, "review_state": rs,
                                       "operator_overrides_json": ov}))
    live = {m: (kind, thumb) for m, (_rs, _ov, kind, thumb) in extra.items()}
    return _Vault(items, [[int(m) for m in g] for g in groups], prints, live, standard, solo)


def _vault_media(mid: int, vault: _Vault) -> dict[str, Any]:
    kind, thumb = vault.live[mid]
    entry: dict[str, Any] = {"id": mid, "type": kind}
    if thumb:
        entry["files"] = {"thumb": {"url": thumb}}
    return entry


class _PlanInputs(NamedTuple):
    recs: list[SavedReply]
    used: set[int]
    template: dict[int, int]


async def _plan_inputs(s: Any, account_id: str, sequence: str, agency: str | None) -> _PlanInputs:
    return _PlanInputs(await _sequence(s, account_id, sequence), await _used_ids(s, account_id, sequence),
                       await _template_prices(s, account_id, sequence, agency))


async def _plan(inputs: _PlanInputs, vault: _Vault, cov: dict[str, Any], blocked: str | None,
                account_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(
        decide.plan_over_vault, [_row_dict(r) for r in inputs.recs], vault.items, inputs.used, vault.groups,
        vault.prints, cov, blocked, account_id=account_id, standard_folders=vault.standard_folders,
        solo_sequences=vault.solo_sequences, live_ids=set(vault.live), template_prices=inputs.template)



@router.post("/fill/plan")
async def fill_plan(body: _PlanBody = Body(...), account_id: str = Query("")) -> dict[str, Any]:
    """The read-only Fill plan of one Sequence (spec › Contracts FillPlan). Writes nothing."""
    account_id = await _gate(account_id)
    agency = await _agency(account_id)
    cov, blocked = await _describe_inputs(account_id)
    async with _plan_gate():
        async with get_session() as s:
            inputs = await _plan_inputs(s, account_id, body.sequence, agency)
        vault = await _load_vault(account_id)
        return await _plan(inputs, vault, cov, blocked, account_id)


@router.post("/fill/apply")
async def fill_apply(body: _ApplyBody = Body(...), account_id: str = Query("")) -> dict[str, Any]:
    """Re-derive the plan and write it inside one write transaction (module docstring). 409 `stale` with the
    fresh plan when `fingerprint` is given and differs; every non-`ok` status writes nothing."""
    account_id = await _gate(account_id)
    cov, blocked = await _describe_inputs(account_id)
    agency = await _agency(account_id)
    async with _plan_gate(), immediate_session() as s:
        inputs = await _plan_inputs(s, account_id, body.sequence, agency)
        recs = inputs.recs
        vault = await _load_vault(account_id, s)
        plan = await _plan(inputs, vault, cov, blocked, account_id)
        if body.fingerprint and body.fingerprint != plan["fingerprint"]:
            raise HTTPException(status_code=409, detail={"error": "stale", "plan": plan})
        if plan["status"] != "ok":
            return {"status": plan["status"], "plan": plan, "applied": [], "undo": []}
        writes = decide.writes(plan["options"])
        by_id = {r.id: r for r in recs}
        now = datetime.utcnow()
        undo = []
        for w in writes:
            rec = by_id[w["id"]]
            rec.media_json = json.dumps([_vault_media(m, vault) for m in w["media"]])
            rec.previews_json = json.dumps(list(w["previews"]))
            if w["price_cents"] is not None:
                rec.price_cents = int(w["price_cents"])
            rec.updated_at = now
            undo.append({"id": w["id"], "media_ids": list(w["media"]), "previews": list(w["previews"]),
                         "price_cents": int(rec.price_cents or 0), "price_set": w["price_cents"] is not None})
        await sync_sequences(s, account_id, {body.sequence})
    written = {w["id"] for w in writes}
    return {"status": "ok", "plan": plan, "applied": [o for o in plan["options"] if o["id"] in written],
            "undo": undo}


@router.post("/fill/undo")
async def fill_undo(body: _UndoBody = Body(...), account_id: str = Query("")) -> dict[str, Any]:
    """Empty each row that still holds exactly its Undo entry's media, previews and price in this Sequence;
    report the rest per row (`edited`, `moved`, `missing`)."""
    account_id = await _gate(account_id)
    undone: list[int] = []
    kept: list[dict[str, Any]] = []
    async with immediate_session() as s:
        await _sequence(s, account_id, body.sequence)
        if is_reserved_name(body.sequence):
            return {"undone": [], "kept": [{"id": e.id, "reason": "reserved"} for e in body.undo]}
        ids = sorted({e.id for e in body.undo})
        rows: dict[int, SavedReply] = {}
        for at in range(0, len(ids), IN_CHUNK):
            rows.update({r.id: r for r in (await s.execute(select(SavedReply).where(
                SavedReply.account_id == account_id, SavedReply.id.in_(ids[at:at + IN_CHUNK])))).scalars()})
        now = datetime.utcnow()
        for e in body.undo:
            rec = rows.get(e.id)
            verdict = decide.undo_check(_row_dict(rec) if rec is not None else None, e.model_dump(),
                                        body.sequence)
            if verdict != "ok":
                kept.append({"id": e.id, "reason": verdict})
                continue
            rec.media_json = "[]"
            rec.previews_json = "[]"
            if e.price_set:
                rec.price_cents = 0
            rec.updated_at = now
            undone.append(e.id)
        if undone:
            await sync_sequences(s, account_id, {body.sequence})
    return {"undone": undone, "kept": kept}
