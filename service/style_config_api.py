from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from auth import assert_account_owned
from db.engine import get_session
from db.models import AccountAiConfig
from automations._common import (
    STYLE_AUTOMATIONS, STYLE_CONSISTENCY_KEYS, typo_flag_key, nonnative_flag_key, spacing_flag_key,
    FACTGROUND_KEY, PAINFUL_TEXTING_KEY, CAT_STICKERS_KEY,
    CAT_STICKER_SKIP_PCT_KEY,
    CAT_STICKER_SOLO_PCT_KEY, CAT_STICKER_GAP_MIN_KEY,
    _parse_style_config)
from automations._daylog import DAY_LOG_DEFAULT, DAY_LOG_ENABLED_KEY

# Numbers, not checkboxes: the bool coercion in _persist must never touch these.
_NUMERIC_KNOBS: dict[str, tuple[float, float]] = {
    CAT_STICKER_SKIP_PCT_KEY: (0.0, 100.0),
    CAT_STICKER_SOLO_PCT_KEY: (5.0, 100.0),
    CAT_STICKER_GAP_MIN_KEY: (0.0, 7 * 24 * 60.0),
}


def _clamp_num(key: str, v) -> float:
    default, hi = _NUMERIC_KNOBS[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return min(max(float(v), 0.0), hi)

log = logging.getLogger("of-relay.style_config_api")

router = APIRouter()


def _defaults() -> dict[str, Any]:
    # Reflect the RUNTIME tri-state default, not flat False: a default-ON entry reported off would render unchecked and an unrelated save would stamp it explicit.
    from automations._common import _style_default
    out = {k: _style_default(k) for k in STYLE_AUTOMATIONS}
    out.update({typo_flag_key(k): _style_default(k) for k in STYLE_AUTOMATIONS})
    out.update({nonnative_flag_key(k): _style_default(k) for k in STYLE_AUTOMATIONS})
    out.update({spacing_flag_key(k): _style_default(k) for k in STYLE_AUTOMATIONS})
    out["strip_emojis"] = False
    # OFF and not tri-state: costs a second LLM call per reply, so load_consistency_flags needs an explicit True.
    out.update({k: False for k in STYLE_CONSISTENCY_KEYS})
    out[FACTGROUND_KEY] = True
    out[PAINFUL_TEXTING_KEY] = True
    out[CAT_STICKERS_KEY] = True
    out.update({k: d for k, (d, _) in _NUMERIC_KNOBS.items()})
    return out


def _resolved_view(stored: dict) -> dict[str, Any]:
    from automations._common import _resolve_style_flag
    if not isinstance(stored, dict):
        stored = {}
    out = {k: _resolve_style_flag(stored, k, k) for k in STYLE_AUTOMATIONS}
    out.update({typo_flag_key(k): _resolve_style_flag(stored, k, typo_flag_key(k))
                for k in STYLE_AUTOMATIONS})
    out.update({spacing_flag_key(k): _resolve_style_flag(stored, k, spacing_flag_key(k))
                for k in STYLE_AUTOMATIONS})
    out.update({nonnative_flag_key(k): _resolve_style_flag(stored, k, nonnative_flag_key(k))
                for k in STYLE_AUTOMATIONS})
    out["strip_emojis"] = bool(stored.get("strip_emojis"))
    # Not _resolve_style_flag: its tri-state default could render this checked and bill a second LLM call per reply.
    out.update({k: bool(stored.get(k, False)) for k in STYLE_CONSISTENCY_KEYS})
    # DEFAULT ON: absent resolves True, so a save doesn't flip an implicit-ON flag to explicit-OFF.
    out[FACTGROUND_KEY] = bool(stored.get(FACTGROUND_KEY, True))
    out[PAINFUL_TEXTING_KEY] = bool(stored.get(PAINFUL_TEXTING_KEY, True))
    out[CAT_STICKERS_KEY] = bool(stored.get(CAT_STICKERS_KEY, True))
    out.update({k: _clamp_num(k, stored.get(k)) for k in _NUMERIC_KNOBS})
    out[DAY_LOG_ENABLED_KEY] = bool(stored.get(DAY_LOG_ENABLED_KEY, DAY_LOG_DEFAULT))
    return out


def _persist(cfg: dict) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        cfg = {}
    # Only gate on what reaches style_config_json: a key absent here is dropped silently on a 200 and its loader never sees True. Add new load_*_flags keys here.
    known = set(STYLE_AUTOMATIONS) \
        | {typo_flag_key(k) for k in STYLE_AUTOMATIONS} \
        | {nonnative_flag_key(k) for k in STYLE_AUTOMATIONS} \
        | {spacing_flag_key(k) for k in STYLE_AUTOMATIONS} \
        | set(STYLE_CONSISTENCY_KEYS) \
        | {"strip_emojis", FACTGROUND_KEY, PAINFUL_TEXTING_KEY, CAT_STICKERS_KEY,
           DAY_LOG_ENABLED_KEY}
    out: dict[str, Any] = {k: bool(v) for k, v in cfg.items() if k in known}
    # bool() would turn "skip 30%" into True.
    out.update({k: _clamp_num(k, cfg[k]) for k in _NUMERIC_KNOBS if k in cfg})
    return out


@router.get("/admin/style-config")
async def get_style_config(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        row = await s.get(AccountAiConfig, account_id)
    # Parse chokepoint: legacy-key normalization lives in it; raw json.loads would show a pre-rename blob's flags as absent.
    stored = _parse_style_config(row.style_config_json) if row is not None else {}
    return {"account_id": account_id, "config": _resolved_view(stored),
            "defaults": _defaults()}


class _ConfigBody(BaseModel):
    account_id: str
    config: dict


@router.put("/admin/style-config")
async def put_style_config(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    now = datetime.utcnow()
    async with get_session() as s:
        # MERGE partial updates so two surfaces never wipe each other's flags.
        row = await s.get(AccountAiConfig, body.account_id)
        stored = _parse_style_config(row.style_config_json) if row is not None else {}
        # Persist only explicit keys so an untouched realism flag stays ABSENT -> its default at load time.
        clean = _persist({**stored, **(body.config or {})})
        payload = json.dumps(clean)
        await s.execute(
            sqlite_insert(AccountAiConfig)
            .values(account_id=body.account_id, utc_offset=0,
                    style_config_json=payload, updated_at=now)
            .on_conflict_do_update(
                index_elements=["account_id"],
                set_={"style_config_json": payload, "updated_at": now})
        )
    log.info("style_config_saved account=%s cfg=%s", body.account_id, clean)
    return {"account_id": body.account_id, "config": _resolved_view(clean)}
