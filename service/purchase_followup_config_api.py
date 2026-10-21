"""service/purchase_followup_config_api.py — read/write the purchase_followup rule.

The `purchase_followup` automation (message a fan after he buys a PPV; Smart
Messages' "Purchased" Trigger) keeps ALL its config in its automation rule:
the rule's on/off is the switch and its steps are the config
the sweep reads. No config column.

  GET /admin/purchase-followup-config?account_id=  → {account_id, config, defaults}
  PUT /admin/purchase-followup-config              → upsert the rule, returns {account_id, config}

`config` is {enabled, text, delay_range, frequency, media_ids, price_cents,
starts_at, ends_at, unsend_minutes} (the last seven: smart_message_extras).
Default (no rule) → DISABLED, on Infloww's defaults for the Trigger (after a
random 1～3 minutes, every time): the rule is only created by a save, and a
save that turns it on needs a text. A rule saved before `delay_range` reads its
old `delay_minutes` as the fixed range [d, d] (automations.purchase_followup.
delay_of) and keeps it until a save posts a `delay_range`; a save stores only
the keys it posts (all of them on the first), so switching it off or editing the
text leaves the rest as stored.
A save that leaves it ON is owner-only (it decides what goes out to fans); a
chatter with Smart Messages may read it, switch it off and edit it while off.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

import smart_message_extras as extras
from auth import assert_account_owned
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
    """Check a posted config. Unknown keys are dropped; omitted keys keep their
    stored value. Types are exact — `"false"` is not a bool and `true` is not a
    number — so nothing is coerced into switching it on."""
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


async def _rules(s, account_id: str) -> list[AutomationRule]:
    """Every row of the kind, oldest first."""
    return list((await s.execute(
        select(AutomationRule).where(
            AutomationRule.account_id == account_id,
            AutomationRule.kind == KIND).order_by(AutomationRule.id)
    )).scalars())


def _primary(rules: list[AutomationRule]) -> AutomationRule | None:
    """The row the sweep runs: the first switched on, else the first."""
    return next((r for r in rules if r.is_enabled), rules[0] if rules else None)


def _steps(rule: AutomationRule | None) -> dict:
    if rule is None or not rule.steps_json:
        return {}
    try:
        steps = json.loads(rule.steps_json)
    except Exception:
        return {}
    return steps if isinstance(steps, dict) else {}


def _public(rules: list[AutomationRule]) -> dict[str, Any]:
    if not rules:
        return _defaults()
    steps = _steps(_primary(rules))
    return {
        "enabled": any(r.is_enabled for r in rules),
        "text": str(steps.get("text") or ""),
        # What a stored rule without the newer keys runs on: every time, and its
        # old single delay.
        **extras.public(steps, frequency=STORED_FREQUENCY, delay=delay_of(steps)),
    }


@router.get("/admin/purchase-followup-config")
async def get_purchase_followup_config(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        config = _public(await _rules(s, account_id))
    return {"account_id": account_id, "config": config, "defaults": _defaults()}


class _ConfigBody(BaseModel):
    account_id: str
    config: dict


@router.put("/admin/purchase-followup-config")
async def put_purchase_followup_config(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    clean = _validate(body.config)
    async with get_session() as s:
        rules = await _rules(s, body.account_id)
        was_on = any(r.is_enabled for r in rules)
        merged = {**_public(rules), **clean}
        extras.check(merged)
        if merged["enabled"]:
            assert_owner()
            # Switching on takes the text in the same request, so the owner turns
            # on the words he is looking at, never a stored text someone else
            # edited while it was off.
            if not merged["text"] or (not was_on and not clean.get("text")):
                raise HTTPException(422, "a message text is required to turn this on")
        steps = _steps(_primary(rules))
        fresh = not steps
        steps.update(enabled=merged["enabled"], text=merged["text"])
        if "delay_range" in clean:
            steps.pop("delay_minutes", None)     # superseded by the posted range
        # A first save lands Infloww's defaults; later ones write only what they
        # post, so an old rule's fixed delay and 24h floor survive an unrelated save.
        extras.store(steps, merged if fresh else clean)
        # Purchases made before the switch went on are never chased: stamp the
        # moment it turns on, and keep the stamp while it stays on.
        if merged["enabled"] and (not was_on or not steps.get("enabled_at")):
            steps["enabled_at"] = datetime.utcnow().isoformat()
        trigger = json.dumps({"every_seconds": _EVERY_S})
        if not rules and not merged["enabled"]:
            # Saved off before it was ever on: keep the draft in a parked row.
            s.add(AutomationRule(account_id=body.account_id, name=_RULE_NAME, kind=KIND,
                                 trigger_json=trigger, steps_json="{}", is_enabled=False))
        # The switch, with the house's every-row policy: off parks EVERY row of
        # the kind, on wakes one (creating it when there is none).
        await ensure_kind_rule(s, body.account_id, KIND, enable=merged["enabled"],
                               name=_RULE_NAME, every_seconds=_EVERY_S, steps=steps)
        await s.flush()
        rules = await _rules(s, body.account_id)
        for rule in rules:                  # every row carries the same config
            rule.trigger_json = trigger
            rule.steps_json = json.dumps(steps)
        config = _public(rules)
    log.info("purchase_followup_config_saved account=%s enabled=%s delay=%s frequency=%s",
             body.account_id, config["enabled"], config["delay_range"], config["frequency"])
    return {"account_id": body.account_id, "config": config}
