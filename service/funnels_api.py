from __future__ import annotations

import json
import logging
from typing import Any

from datetime import datetime, timedelta

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from auth import assert_account_owned
from db.engine import get_session
from db.models import MASS_RUN_OK, FunnelAccountMedia, FunnelState, MassMessageFunnel, MassRun
from permissions import require_opt_in_page

# Only Auto Funnel writes funnels, so every write needs that page (opt-in for a chatter); reads stay open.
# Funnels are GLOBAL (no account_id): these routes gate on owner auth and do not scope by account, unlike the account-scoped /media routes.
_AUTO_FUNNEL = "/growth/auto-funnel"

log = logging.getLogger("of-relay.funnels_api")

router = APIRouter()



async def ensure_funnel_walker(account_id: str) -> str:
    # A funnel mass sends only the opener: steps run only while an ENABLED reply_mass_funnel rule WITH a cadence exists.
    # A cadence-less row (Reply Instant, trigger {}) is never ticked, so it gets the catalog cadence; a tuned cadence is kept.
    from automation_registry import kind_family
    from automation_rules_api import _CATALOG, ensure_kind_rule
    from db.models import AutomationRule

    kind = "reply_mass_funnel"
    async with get_session() as s:
        action = await ensure_kind_rule(s, account_id, kind, enable=True)
        rule = (await s.execute(
            select(AutomationRule).where(
                AutomationRule.account_id == str(account_id),
                AutomationRule.kind.in_(kind_family(kind)),
                AutomationRule.is_enabled.is_(True),
            ).order_by(AutomationRule.id)
        )).scalars().first()
        if rule is not None:
            try:
                trig = json.loads(rule.trigger_json or "{}")
            except (TypeError, ValueError):
                trig = {}
            if not isinstance(trig, dict) or not (
                    trig.get("every_seconds") or trig.get("daily_at")):
                rule.trigger_json = json.dumps(
                    {"every_seconds": int(_CATALOG[kind]["cadence_default_s"])})
                if action == "unchanged":
                    action = "cadence"
    if action != "unchanged":
        log.info("funnel_walker_ensured account=%s action=%s", account_id, action)
    return action



def _whole_int(key: str, val: Any) -> int:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise HTTPException(422, f"{key} must be a whole number")
    n = int(val)
    if n != val:
        raise HTTPException(422, f"{key} must be a whole number")
    return n


def _nonempty_messages(step: dict) -> list[str]:
    msgs = step.get("messages")
    if not isinstance(msgs, list):
        return []
    return [str(m) for m in msgs if str(m).strip()]


# Mirrors reply_mass_funnel._is_generated.
def _is_generated(step: dict) -> bool:
    if _nonempty_messages(step):
        return False
    return bool(step.get("generate") or (isinstance(step.get("prompt"), str)
                                         and step["prompt"].strip()))


_NEXT_KEYS = frozenset({"bought", "ignored", "default", "keyword"})


def _validate_next(idx: int, step: dict) -> None:
    nxt = step.get("next")
    if nxt is None:
        return
    if not isinstance(nxt, dict):
        raise HTTPException(422, f"step[{idx}].next must be an object")
    for k in nxt:
        if k not in _NEXT_KEYS:
            raise HTTPException(
                422, f"step[{idx}].next has unknown key {k!r} "
                     "(allowed: bought, ignored, default, keyword)")
    for k in ("bought", "ignored", "default"):
        if k in nxt:
            _whole_int(f"step[{idx}].next.{k}", nxt[k])
    if "keyword" in nxt:
        kw = nxt["keyword"]
        if not isinstance(kw, dict) or not kw:
            raise HTTPException(
                422, f"step[{idx}].next.keyword must be a non-empty object "
                     "of {{word: step}}")
        for word, target in kw.items():
            if not str(word).strip():
                raise HTTPException(422, f"step[{idx}].next.keyword has a blank keyword")
            _whole_int(f"step[{idx}].next.keyword[{word!r}]", target)


def _next_targets(step: dict) -> list[tuple[str, int]]:
    nxt = step.get("next")
    if not isinstance(nxt, dict):
        return []
    out: list[tuple[str, int]] = []
    for k in ("bought", "ignored", "default"):
        if k in nxt:
            out.append((k, int(nxt[k])))
    kw = nxt.get("keyword")
    if isinstance(kw, dict):
        for word, target in kw.items():
            out.append((f"keyword[{word!r}]", int(target)))
    return out


def _validate_intervals(idx: int, step: dict) -> None:
    iv = step.get("check_intervals_min")
    if iv is None:
        return
    if not isinstance(iv, list) or not iv:
        raise HTTPException(422, f"step[{idx}].check_intervals_min must be a non-empty list")
    for x in iv:
        n = _whole_int(f"step[{idx}].check_intervals_min", x)
        if n <= 0:
            raise HTTPException(422, f"step[{idx}].check_intervals_min must be positive ints")


def _validate_step(idx: int, step: Any) -> dict:
    if not isinstance(step, dict):
        raise HTTPException(422, f"step[{idx}] must be an object")

    if "step" not in step:
        raise HTTPException(422, f"step[{idx}] is missing 'step'")
    s_no = _whole_int(f"step[{idx}].step", step["step"])
    if s_no < 1:
        raise HTTPException(422, f"step[{idx}].step must be >= 1")

    stype = step.get("type")
    if stype is not None and stype != "paid_ppv":
        raise HTTPException(422, f"step[{idx}] has unknown type {stype!r} (only 'paid_ppv')")
    is_ppv = stype == "paid_ppv"

    if not _is_generated(step) and not _nonempty_messages(step):
        raise HTTPException(
            422, f"step[{idx}] needs non-empty 'messages' or 'prompt'/'generate': true")

    if is_ppv:
        if "price" in step and step["price"] is not None:
            price = _whole_int(f"step[{idx}].price", step["price"])
            if price < 0:
                raise HTTPException(422, f"step[{idx}].price must be >= 0")
        # Media is NOT a funnel-step field: vault ids are per-account (see funnel_account_media); legacy media_files pass through unvalidated.
        if "locked_text" in step and not isinstance(step["locked_text"], bool):
            raise HTTPException(422, f"step[{idx}].locked_text must be true or false")
    else:
        _validate_intervals(idx, step)

    _validate_next(idx, step)

    return step


def _validate_steps(steps: Any) -> list[dict]:
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise HTTPException(422, "steps must be a list")
    out = [_validate_step(i, st) for i, st in enumerate(steps)]
    # A dangling `next` target would strand a fan mid-storyline.
    step_numbers = {int(st["step"]) for st in out}
    for i, st in enumerate(out):
        for label, target in _next_targets(st):
            if target not in step_numbers:
                raise HTTPException(
                    422, f"step[{i}].next.{label} → step {target} references no "
                         "existing step")
    try:
        json.dumps(out)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"steps are not JSON-serialisable: {e}")
    return out



def _safe_steps(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [s for s in parsed if isinstance(s, dict)] if isinstance(parsed, list) else []


def _safe_indices(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _summary(fn: MassMessageFunnel) -> dict[str, Any]:
    return {
        "id": fn.id,
        "name": fn.name,
        "description": fn.description,
        "opening_message": fn.opening_message,
        "step_count": len(_safe_steps(fn.steps_json)),
    }


def _full(fn: MassMessageFunnel) -> dict[str, Any]:
    return {
        **_summary(fn),
        "steps": _safe_steps(fn.steps_json),
        # Opener-media columns are stored but NOT consumed: send_mass_message uses only opening_message.
        "vault_folder": fn.vault_folder,
        "media_indices": _safe_indices(fn.media_indices),
        "opening_vault_folder": fn.opening_vault_folder,
        "opening_media_indices": _safe_indices(fn.opening_media_indices),
    }



class FunnelCreate(BaseModel):
    name: str = Field(..., min_length=1)
    opening_message: str = Field(..., min_length=1)
    description: str | None = None
    steps: list[dict[str, Any]] | None = None
    vault_folder: str | None = None
    media_indices: Any | None = None
    opening_vault_folder: str | None = None
    opening_media_indices: Any | None = None


class FunnelUpdate(BaseModel):
    name: str | None = None
    opening_message: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]] | None = None
    vault_folder: str | None = None
    media_indices: Any | None = None
    opening_vault_folder: str | None = None
    opening_media_indices: Any | None = None



async def _account_stats(s, account_id: str) -> dict[int, dict[str, Any]]:
    from automations.reply_mass_funnel import DISCOVERY_WINDOW_DAYS
    cutoff = datetime.utcnow() - timedelta(days=DISCOVERY_WINDOW_DAYS)
    open_run = case((and_(MassRun.started_at >= cutoff, MassRun.discovery_closed_at.is_(None),
                          MassRun.unsent_at.is_(None)), 1), else_=0)
    rows = (await s.execute(
        select(MassRun.funnel_id, func.max(MassRun.started_at),
               func.count(distinct(FunnelState.fan_id)), func.max(open_run))
        .outerjoin(FunnelState, and_(FunnelState.mass_run_id == MassRun.id,
                                     FunnelState.status == "pending"))
        .where(MassRun.account_id == str(account_id), MassRun.funnel_id.is_not(None),
               MassRun.status == MASS_RUN_OK)
        .group_by(MassRun.funnel_id)
    )).all()
    return {int(fid): {"last_started_at": last.isoformat() if last else None,
                       "active_fans": int(fans or 0), "listening": bool(listening)}
            for fid, last, fans, listening in rows}


@router.get("/admin/funnels")
async def list_funnels(account_id: str | None = None) -> dict[str, Any]:
    """`?account_id=` adds that model's `stats` to every funnel (never-started → zeros)."""
    if account_id:
        assert_account_owned(account_id)
    async with get_session() as s:
        rows = (await s.execute(
            select(MassMessageFunnel).order_by(MassMessageFunnel.name)
        )).scalars().all()
        if not account_id:
            return {"funnels": [_summary(fn) for fn in rows]}
        stats = await _account_stats(s, account_id)
        none = {"last_started_at": None, "active_fans": 0, "listening": False}
        return {"funnels": [{**_summary(fn), "stats": stats.get(fn.id, none)} for fn in rows]}


@router.get("/admin/funnels/{funnel_id}")
async def get_funnel(funnel_id: int) -> dict[str, Any]:
    async with get_session() as s:
        fn = await s.get(MassMessageFunnel, funnel_id)
        if fn is None:
            raise HTTPException(404, "funnel not found")
        return _full(fn)


def _indices_json(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val
    try:
        return json.dumps(val)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"media_indices is not JSON-serialisable: {e}")


@router.post("/admin/funnels")
async def create_funnel(body: FunnelCreate = Body(...)) -> dict[str, Any]:
    await require_opt_in_page(_AUTO_FUNNEL)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name cannot be blank")
    opening = body.opening_message.strip()
    if not opening:
        raise HTTPException(422, "opening_message cannot be blank")
    steps = _validate_steps(body.steps)

    async with get_session() as s:
        fn = MassMessageFunnel(
            name=name,
            description=(body.description.strip() if body.description else None),
            opening_message=opening,
            steps_json=json.dumps(steps),
            vault_folder=body.vault_folder,
            media_indices=_indices_json(body.media_indices) or "[]",
            opening_vault_folder=body.opening_vault_folder,
            opening_media_indices=_indices_json(body.opening_media_indices),
        )
        s.add(fn)
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            raise HTTPException(409, f"a funnel named {name!r} already exists")
        out = _full(fn)
    log.info("funnel_created id=%s name=%s steps=%d", out["id"], name, len(steps))
    return out


@router.put("/admin/funnels/{funnel_id}")
async def update_funnel(funnel_id: int, body: FunnelUpdate = Body(...)) -> dict[str, Any]:
    await require_opt_in_page(_AUTO_FUNNEL)
    async with get_session() as s:
        fn = await s.get(MassMessageFunnel, funnel_id)
        if fn is None:
            raise HTTPException(404, "funnel not found")
        if body.name is not None:
            nm = body.name.strip()
            if not nm:
                raise HTTPException(422, "name cannot be blank")
            fn.name = nm
        if body.opening_message is not None:
            om = body.opening_message.strip()
            if not om:
                raise HTTPException(422, "opening_message cannot be blank")
            fn.opening_message = om
        if body.description is not None:
            fn.description = body.description.strip() or None
        if body.steps is not None:
            fn.steps_json = json.dumps(_validate_steps(body.steps))
        if body.vault_folder is not None:
            fn.vault_folder = body.vault_folder
        if body.media_indices is not None:
            fn.media_indices = _indices_json(body.media_indices) or "[]"
        if body.opening_vault_folder is not None:
            fn.opening_vault_folder = body.opening_vault_folder
        if body.opening_media_indices is not None:
            fn.opening_media_indices = _indices_json(body.opening_media_indices)
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            raise HTTPException(409, f"a funnel named {fn.name!r} already exists")
        out = _full(fn)
    log.info("funnel_updated id=%s", funnel_id)
    return out


@router.delete("/admin/funnels/{funnel_id}")
async def delete_funnel(funnel_id: int) -> dict[str, Any]:
    await require_opt_in_page(_AUTO_FUNNEL)
    async with get_session() as s:
        fn = await s.get(MassMessageFunnel, funnel_id)
        if fn is None:
            raise HTTPException(404, "funnel not found")
        # Don't orphan live funnel_state: a mass_run anchored here is still being walked by reply_mass_funnel.
        refs = (await s.execute(
            select(func.count()).select_from(MassRun).where(MassRun.funnel_id == funnel_id)
        )).scalar_one()
        if refs:
            raise HTTPException(
                409, f"funnel is referenced by {refs} mass run(s); cannot delete")
        await s.delete(fn)
    log.info("funnel_deleted id=%s", funnel_id)
    return {"deleted": funnel_id}



# A funnel's TEXT is global, its MEDIA per-account (OF vault ids don't carry between models). reply_mass_funnel does int(m) on each, so ints or digit strings only.
def _vault_ids(key: str, raw: Any) -> list[int]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(422, f"{key} must be a list of vault ids")
    out: list[int] = []
    for m in raw:
        if isinstance(m, bool) or not (
            isinstance(m, int) or (isinstance(m, str) and m.isdigit())
        ):
            raise HTTPException(422, f"{key} must be raw vault ids (int/digit-string)")
        out.append(int(m))
    return out


# Previews are clamped to ids in that step's media set: a free teaser is a SUBSET of the locked send.
def _validate_steps_media(raw: Any) -> dict[str, dict]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(422, "steps_media must be an object keyed by step number")
    out: dict[str, dict] = {}
    for k, v in raw.items():
        ks = str(k)
        if not ks.isdigit():
            raise HTTPException(422, f"steps_media key {k!r} must be a step number")
        if not isinstance(v, dict):
            raise HTTPException(422, f"steps_media[{ks}] must be an object")
        media = _vault_ids(f"steps_media[{ks}].media_files", v.get("media_files"))
        previews = _vault_ids(f"steps_media[{ks}].previews", v.get("previews"))
        previews = [m for m in previews if m in media]
        if media or previews:
            out[ks] = {"media_files": media, "previews": previews}
    return out


def _media_payload(row: FunnelAccountMedia | None, funnel_id: int, account_id: str) -> dict[str, Any]:
    if row is None:
        return {"funnel_id": funnel_id, "account_id": account_id,
                "opening_media_ids": [], "steps_media": {}}
    try:
        opening = json.loads(row.opening_media_ids or "[]")
    except (TypeError, ValueError):
        opening = []
    try:
        steps_media = json.loads(row.steps_media_json or "{}")
    except (TypeError, ValueError):
        steps_media = {}
    return {
        "funnel_id": funnel_id,
        "account_id": account_id,
        "opening_media_ids": opening if isinstance(opening, list) else [],
        "steps_media": steps_media if isinstance(steps_media, dict) else {},
    }


class FunnelMediaBody(BaseModel):
    opening_media_ids: list[Any] | None = None
    steps_media: dict[str, Any] | None = None


@router.get("/admin/funnels/{funnel_id}/media/{account_id}")
async def get_funnel_media(funnel_id: int, account_id: str) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        if await s.get(MassMessageFunnel, funnel_id) is None:
            raise HTTPException(404, "funnel not found")
        row = await s.get(FunnelAccountMedia, (funnel_id, account_id))
    return _media_payload(row, funnel_id, account_id)


@router.put("/admin/funnels/{funnel_id}/media/{account_id}")
async def put_funnel_media(
    funnel_id: int, account_id: str, body: FunnelMediaBody = Body(...)
) -> dict[str, Any]:
    assert_account_owned(account_id)
    await require_opt_in_page(_AUTO_FUNNEL, account_id)
    opening = _vault_ids("opening_media_ids", body.opening_media_ids)
    steps_media = _validate_steps_media(body.steps_media)
    now = datetime.utcnow()
    opening_json = json.dumps(opening)
    steps_json = json.dumps(steps_media)
    async with get_session() as s:
        if await s.get(MassMessageFunnel, funnel_id) is None:
            raise HTTPException(404, "funnel not found")
        await s.execute(
            sqlite_insert(FunnelAccountMedia)
            .values(funnel_id=funnel_id, account_id=account_id,
                    opening_media_ids=opening_json, steps_media_json=steps_json,
                    created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["funnel_id", "account_id"],
                set_={"opening_media_ids": opening_json,
                      "steps_media_json": steps_json, "updated_at": now})
        )
        row = await s.get(FunnelAccountMedia, (funnel_id, account_id))
        out = _media_payload(row, funnel_id, account_id)
    log.info("funnel_media_saved funnel=%s account=%s opener=%d steps=%d",
             funnel_id, account_id, len(opening), len(steps_media))
    return out


@router.delete("/admin/funnels/{funnel_id}/media/{account_id}")
async def delete_funnel_media(funnel_id: int, account_id: str) -> dict[str, Any]:
    assert_account_owned(account_id)
    await require_opt_in_page(_AUTO_FUNNEL, account_id)
    async with get_session() as s:
        row = await s.get(FunnelAccountMedia, (funnel_id, account_id))
        if row is not None:
            await s.delete(row)
    log.info("funnel_media_cleared funnel=%s account=%s", funnel_id, account_id)
    return {"cleared": True, "funnel_id": funnel_id, "account_id": account_id}
