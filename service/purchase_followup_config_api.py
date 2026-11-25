from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

import smart_message_extras as extras
from auth import assert_account_owned
from automation_rule_read import primary_rule, rule_steps, rules_of_kind
from automation_rules_api import ensure_kind_rule
from automations.purchase_followup import (
    DEFAULT_DELAY, DEFAULT_FREQUENCY, STORED_FREQUENCY, delay_of,
)
from chatters import assert_owner
from db.engine import get_session
from db.models import AutomationRule

log = logging.getLogger("of-relay.purchase_followup_config_api")

router = APIRouter()

KIND = "purchase_followup"
_RULE_NAME = "Message on purchase"
_EVERY_S = 60
_TEXT_MAX = 1000

def _defaults() -> dict[str, Any]:
    return {"enabled": False, "text": "",
            **extras.defaults(frequency=DEFAULT_FREQUENCY, delay=list(DEFAULT_DELAY))}


def _validate(cfg: Any) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise HTTPException(422, "config must be an object")
    out: dict[str, Any] = {}
    if "enabled" in cfg:
        if not isinstance(cfg["enabled"], bool):
            raise HTTPException(422, "enabled must be true or false")
        out["enabled"] = cfg["enabled"]
    if "text" in cfg:
        if not isinstance(cfg["text"], str):
            raise HTTPException(422, "text must be a string")
        out["text"] = cfg["text"].strip()[:_TEXT_MAX]
    out.update(extras.validate(cfg, delay=True))
    return out


def _public(rules: list[AutomationRule]) -> dict[str, Any]:
    if not rules:
        return _defaults()
    steps = rule_steps(primary_rule(rules))
    return {
        "enabled": any(r.is_enabled for r in rules),
        "text": str(steps.get("text") or ""),
        **extras.public(steps, frequency=STORED_FREQUENCY, delay=delay_of(steps)),
    }


@router.get("/admin/purchase-followup-config")
async def get_purchase_followup_config(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        config = _public(await rules_of_kind(s, account_id, KIND))
    return {"account_id": account_id, "config": config, "defaults": _defaults()}


class _ConfigBody(BaseModel):
    account_id: str
    config: dict


@router.put("/admin/purchase-followup-config")
async def put_purchase_followup_config(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    clean = _validate(body.config)
    async with get_session() as s:
        rules = await rules_of_kind(s, body.account_id, KIND)
        was_on = any(r.is_enabled for r in rules)
        merged = {**_public(rules), **clean}
        extras.check(merged)
        if merged["enabled"]:
            assert_owner()
            # Switching on takes the text in the same request: never a stored text edited while off.
            if not merged["text"] or (not was_on and not clean.get("text")):
                raise HTTPException(422, "a message text is required to turn this on")
        steps = rule_steps(primary_rule(rules))
        fresh = not steps
        steps.update(enabled=merged["enabled"], text=merged["text"])
        if "delay_range" in clean:
            steps.pop("delay_minutes", None)
        # A later save writes only what it posts, so an old rule's fixed delay and 24h floor survive an unrelated save.
        extras.store(steps, merged if fresh else clean)
        # Purchases made before the switch went on are never chased: stamp when it turns on.
        if merged["enabled"] and (not was_on or not steps.get("enabled_at")):
            steps["enabled_at"] = datetime.utcnow().isoformat()
        trigger = json.dumps({"every_seconds": _EVERY_S})
        if not rules and not merged["enabled"]:
            s.add(AutomationRule(account_id=body.account_id, name=_RULE_NAME, kind=KIND,
                                 trigger_json=trigger, steps_json="{}", is_enabled=False))
        # Off parks EVERY row of the kind, on wakes one (creating it when none).
        await ensure_kind_rule(s, body.account_id, KIND, enable=merged["enabled"],
                               name=_RULE_NAME, every_seconds=_EVERY_S, steps=steps)
        await s.flush()
        rules = await rules_of_kind(s, body.account_id, KIND)
        for rule in rules:
            rule.trigger_json = trigger
            rule.steps_json = json.dumps(steps)
        config = _public(rules)
    log.info("purchase_followup_config_saved account=%s enabled=%s delay=%s frequency=%s",
             body.account_id, config["enabled"], config["delay_range"], config["frequency"])
    return {"account_id": body.account_id, "config": config}
