from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from auth import assert_account_owned
from db.engine import get_session
from db.models import AccountAiConfig
from automation_rules_api import ensure_kind_rule
from automations.autoreply import _PURPOSE, _defaults
from automations._common import resolve_model
import inbound_describe
import llm_client

log = logging.getLogger("of-relay.autoreply_config_api")

router = APIRouter()

_INT_KNOBS = {
    "silence_min_minutes": (0, 1440),
    "silence_max_minutes": (2, 10080),
    "step_in_max_minutes": (0, 10080),
    "max_nudges": (0, 10),
    "min_gap_minutes": (1, 1440),
    "new_fan_hours": (1, 8760),
    "new_fan_max_spend_cents": (0, 10_000_000),
    "last_n_messages": (2, 60),
}

# Executor floor (_MIN_EVERY_S): a 0-minute delay replies within one tick; an empty tick stops before per-account loads, so it stays cheap.
_EVERY_S = 30


def _validate(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise HTTPException(422, "config must be an object")
    out: dict[str, Any] = {}
    for b in ("enabled", "info_not_required", "folders_enabled", "new_fans_enabled",
              "describe_photos", "skip_photo_only"):
        if b in cfg:
            out[b] = bool(cfg[b])
    for k, (lo, hi) in _INT_KNOBS.items():
        if k in cfg and cfg[k] is not None:
            try:
                out[k] = max(lo, min(int(cfg[k]), hi))
            except (TypeError, ValueError):
                raise HTTPException(422, f"{k} must be a number")
    if "list_ids" in cfg:
        # A built-in name ("fans") is refused: "every fan" is the empty pick, and a name would read as a folder nobody is in.
        raw = cfg["list_ids"] or []
        if not isinstance(raw, (list, tuple)):
            raise HTTPException(422, "list_ids must be a list of OF list ids")
        ids: list[int] = []
        for x in raw:
            if isinstance(x, bool) or not str(x).strip().isdigit():
                raise HTTPException(422, "list_ids must be numeric OF list ids")
            if int(x) not in ids:
                ids.append(int(x))
        out["list_ids"] = ids[:50]
    if "folder_max_spend_cents" in cfg:
        cap = cfg["folder_max_spend_cents"]
        if cap is None:
            out["folder_max_spend_cents"] = None
        else:
            try:
                out["folder_max_spend_cents"] = max(0, min(int(cap), 10_000_000))
            except (TypeError, ValueError):
                raise HTTPException(422, "folder_max_spend_cents must be a number or null")
    if "quiet_hours_json" in cfg:
        qh = cfg["quiet_hours_json"]
        if qh is None:
            out["quiet_hours_json"] = None
        elif (isinstance(qh, (list, tuple)) and len(qh) == 2
              and all(isinstance(x, (int, float)) for x in qh)):
            out["quiet_hours_json"] = [int(qh[0]) % 24, int(qh[1]) % 24]
        else:
            raise HTTPException(422, "quiet_hours_json must be [start,end] or null")
    if (out.get("silence_max_minutes") is not None
            and out.get("silence_min_minutes") is not None
            and out["silence_max_minutes"] <= out["silence_min_minutes"]):
        raise HTTPException(422, "silence_max_minutes must be > silence_min_minutes")
    if (out.get("step_in_max_minutes") and out.get("silence_min_minutes") is not None
            and out["step_in_max_minutes"] < out["silence_min_minutes"]):
        raise HTTPException(422, "step_in_max_minutes must be >= silence_min_minutes")
    return out


@router.get("/admin/autoreply-config")
async def get_autoreply_config(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        row = await s.get(AccountAiConfig, account_id)
    stored: dict = {}
    if row is not None and row.autoreply_config_json:
        try:
            stored = json.loads(row.autoreply_config_json) or {}
        except Exception:
            stored = {}
    model = await resolve_model(account_id, _PURPOSE)
    provider = llm_client.MODELS[model].provider
    available = await llm_client.llm_key_available(account_id, provider, _PURPOSE)
    vision = await inbound_describe.key_available(account_id)
    return {"account_id": account_id, "config": stored, "defaults": _defaults(),
            "llm_key": {"provider": provider, "available": available},
            "vision_key": {"provider": inbound_describe.PROVIDER, "available": vision}}


class _ConfigBody(BaseModel):
    account_id: str
    config: dict


@router.put("/admin/autoreply-config")
async def put_autoreply_config(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    clean = _validate(body.config)
    # The save replaces the stored blob, so the engine reads posted keys over the defaults: validate the merged result.
    eff = {**_defaults(), **clean}
    if eff["enabled"] and not eff["folders_enabled"] and not eff["new_fans_enabled"]:
        raise HTTPException(422, "pick who gets replies: folders or new fans")
    now = datetime.utcnow()
    payload = json.dumps(clean)
    async with get_session() as s:
        await s.execute(
            sqlite_insert(AccountAiConfig)
            .values(account_id=body.account_id, utc_offset=0,
                    autoreply_config_json=payload, updated_at=now)
            .on_conflict_do_update(
                index_elements=["account_id"],
                set_={"autoreply_config_json": payload, "updated_at": now})
        )
        # Blob and the engine's rule switch in one session so they can't disagree; only when SENT, so a save omitting it can't park a running rule.
        if "enabled" in clean:
            action = await ensure_kind_rule(
                s, body.account_id, "autoreply", enable=bool(clean["enabled"]),
                every_seconds=_EVERY_S if clean["enabled"] else None)
            log.info("autoreply_rule_sync account=%s action=%s enabled=%s",
                     body.account_id, action, clean["enabled"])
    log.info("autoreply_config_saved account=%s cfg=%s", body.account_id, clean)
    return {"account_id": body.account_id, "config": clean}
