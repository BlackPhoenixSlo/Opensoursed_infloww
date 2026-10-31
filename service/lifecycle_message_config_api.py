"""service/lifecycle_message_config_api.py — read/write a lifecycle Trigger's rule.

Smart Messages' Nearing expiry, Expired, Resubscribe and Birthday Triggers
(automations/lifecycle_messages) keep their whole config in the account's rule
of that kind, as purchase_followup does: the rule's on/off is the switch, its
steps are the config the sweep reads.

  GET /admin/lifecycle-message-config?account_id=&kind=  → {account_id, kind, config, defaults}
  PUT /admin/lifecycle-message-config  {account_id, kind, config}  → {account_id, kind, config}
  GET /admin/lifecycle-message-config/buyers?account_id=&kind=  → {account_id, kind, window_days, buyers}

`config` is {enabled, text, hours, messages, frequency, media_ids,
price_cents, starts_at, ends_at, unsend_minutes} (`hours` only for
expiry_message 1..120 and expired_message 12..120; null for the others; the
last six: smart_message_extras). `messages` is the Trigger's messages, one
picked per event: [{variants: [text, ...], follow_ups: [{text,
delay_minutes}], discount: {percent, months} | null}]. A save keeps exactly
what lifecycle_messages' `messages_of` reads back (its bounds are the only
ones) and is refused (422) when that would drop or change anything; a
discount is Nearing expiry only, and no more percent off than OnlyFans grants
on the page's current price (`discount_cap`). `text` is the first message's
first variant; a save that sends `text` without `messages` makes that text
the Trigger's one message. Default (no rule) → DISABLED, "once" (Infloww's start);
a rule saved before `frequency` existed reads "every", what it runs on.
A save that leaves it ON is owner-only and needs a text sent in the same
request when it turns on; every off→on restamps `enabled_at`. Nearing expiry,
Expired and Resubscribe cannot be switched on for a page OnlyFans reports as
free (`account_page`, cached; an unknown tier is not refused), as Infloww
refuses them.

Buyers: the fans a landed message of this Trigger reached who then spent
money (any sale on the ledger, pending ones included, refunds and chargebacks
left out) within `BUYERS_WINDOW_DAYS` of it, newest message first. A sale is
not tied to one message by id; the window is the tie, the same 7 days the
attribution view's tip lookback uses.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

import smart_message_extras as extras
from account_page import subscribe_price_cents
from auth import assert_account_owned
from automation_rule_read import primary_rule, rule_steps, rules_of_kind
from automation_rules_api import ensure_kind_rule
from automations.lifecycle_messages import (
    DEFAULT_FREQUENCY, DISCOUNT_KINDS, FREE_PAGE_REFUSAL, HOURS, KINDS, PAID_ONLY,
    STORED_FREQUENCY, TEXT_MAX, clamp_hours, discount_cap, messages_of,
)
from chatters import assert_owner
from db.engine import get_session
from db.models import AutomationRule, Fan, LifecycleMessageClaim, Transaction
from transaction_ingest import _NON_REVENUE_STATUSES

log = logging.getLogger("of-relay.lifecycle_message_config_api")

router = APIRouter()

_EVERY_S = 30 * 60      # the roster crawl is shared and cached for 25 minutes
BUYERS_WINDOW_DAYS = 7
_BUYERS_LIMIT = 200
_MESSAGES_SHAPE = (
    "messages must be at most 10 messages, each 1 to 10 non-empty variants, at most 5 "
    "follow-ups (a text, 1 to 10080 minutes later) and an optional discount of 5 to 60 % "
    "in steps of 5 for 1 to 12 months")


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    return kind


def _defaults(kind: str) -> dict[str, Any]:
    return {"enabled": False, "text": "", "hours": clamp_hours(kind, None), "messages": [],
            **extras.defaults(frequency=DEFAULT_FREQUENCY)}


def _stripped(v: Any) -> Any:
    return v.strip()[:TEXT_MAX] if isinstance(v, str) else v


def _as_sent(m: Any) -> dict[str, Any]:
    """A message as sent, in the read helper's shape: strings stripped, nothing
    else checked but the containers (a wrong one raises TypeError)."""
    if not isinstance(m, dict) or not isinstance(m.get("variants"), list) \
            or not isinstance(m.get("follow_ups") or [], list):
        raise TypeError
    d = m.get("discount")
    return {"variants": [_stripped(v) for v in m["variants"]],
            "follow_ups": [{"text": _stripped(f.get("text")), "delay_minutes": f.get("delay_minutes")}
                           if isinstance(f, dict) else f for f in m.get("follow_ups") or []],
            "discount": {"percent": d.get("percent"), "months": d.get("months")}
            if isinstance(d, dict) else d}


def _messages(kind: str, raw: Any) -> list[dict[str, Any]]:
    """`raw` through `messages_of`, refused when that drops or changes anything."""
    try:
        sent = [_as_sent(m) for m in raw] if isinstance(raw, list) else None
    except TypeError:
        sent = None
    if sent is None or messages_of({"messages": raw}) != sent:
        raise HTTPException(422, _MESSAGES_SHAPE)
    if kind not in DISCOUNT_KINDS and any(m["discount"] for m in sent):
        raise HTTPException(422, "a discount is offered on Nearing expiry only")
    return sent


def _validate(kind: str, cfg: Any) -> dict[str, Any]:
    """Exact types, unknown keys dropped, omitted keys keep their stored value."""
    if not isinstance(cfg, dict):
        raise HTTPException(422, "config must be an object")
    out: dict[str, Any] = {}
    if "enabled" in cfg:
        if not isinstance(cfg["enabled"], bool):
            raise HTTPException(422, "enabled must be true or false")
        out["enabled"] = cfg["enabled"]
    if "messages" in cfg:
        out["messages"] = _messages(kind, cfg["messages"])
        out["text"] = _first_text(out["messages"])
    elif "text" in cfg:
        if not isinstance(cfg["text"], str):
            raise HTTPException(422, "text must be a string")
        out["text"] = cfg["text"].strip()[:TEXT_MAX]
        out["messages"] = messages_of({"text": out["text"]})
    if "hours" in cfg and kind in HOURS:
        h = cfg["hours"]
        lo, hi = HOURS[kind]
        if isinstance(h, bool) or not isinstance(h, int) or not lo <= h <= hi:
            raise HTTPException(422, f"hours must be a whole number from {lo} to {hi}")
        out["hours"] = h
    out.update(extras.validate(cfg))
    return out


def _first_text(messages: list[dict]) -> str:
    return messages[0]["variants"][0] if messages else ""


def _public(kind: str, rules: list[AutomationRule]) -> dict[str, Any]:
    if not rules:
        return _defaults(kind)
    steps = rule_steps(primary_rule(rules))
    messages = messages_of(steps)
    return {"enabled": any(r.is_enabled for r in rules),
            "text": _first_text(messages),
            "hours": clamp_hours(kind, steps.get("hours")),
            "messages": messages,
            **extras.public(steps, frequency=STORED_FREQUENCY)}


async def _check_discounts(account_id: str, messages: list[dict]) -> None:
    """No discount above what OnlyFans grants on the page's price: a refused
    discount would burn the event (no discount, no message)."""
    top = max((m["discount"]["percent"] for m in messages if m["discount"]), default=None)
    if top is None:
        return
    price = await subscribe_price_cents(account_id)
    if price is None:
        raise HTTPException(422, "couldn't read this Creator's subscription price to check "
                                 "the discount; try again")
    cap = discount_cap(price)
    if top > cap:
        raise HTTPException(422, f"OnlyFans gives at most {cap}% off a "
                                 f"${price / 100:.2f} subscription")


@router.get("/admin/lifecycle-message-config")
async def get_lifecycle_message_config(
    account_id: str = Query(...), kind: str = Query(...),
) -> dict[str, Any]:
    assert_account_owned(account_id)
    kind = _kind(kind)
    async with get_session() as s:
        config = _public(kind, await rules_of_kind(s, account_id, kind))
    return {"account_id": account_id, "kind": kind, "config": config,
            "defaults": _defaults(kind)}


class _ConfigBody(BaseModel):
    account_id: str
    kind: str
    config: dict


@router.put("/admin/lifecycle-message-config")
async def put_lifecycle_message_config(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    kind = _kind(body.kind)
    clean = _validate(kind, body.config)
    # Asked before the session opens: they may cost one OF read on a cold cache.
    await _check_discounts(body.account_id, clean.get("messages") or [])
    if (kind in PAID_ONLY and clean.get("enabled") is True
            and await subscribe_price_cents(body.account_id) == 0):
        raise HTTPException(422, f"This Creator {FREE_PAGE_REFUSAL}")
    name = KINDS[kind]
    async with get_session() as s:
        rules = await rules_of_kind(s, body.account_id, kind)
        was_on = any(r.is_enabled for r in rules)
        merged = {**_public(kind, rules), **clean}
        extras.check(merged)
        if merged["enabled"]:
            assert_owner()
            if not merged["text"] or (not was_on and not clean.get("text")):
                raise HTTPException(422, "a message text is required to turn this on")
        steps = rule_steps(primary_rule(rules))
        steps.update(enabled=merged["enabled"], text=merged["text"],
                     messages=merged["messages"])
        extras.store(steps, merged)
        if kind in HOURS:
            steps["hours"] = merged["hours"]
        if merged["enabled"] and (not was_on or not steps.get("enabled_at")):
            steps["enabled_at"] = datetime.utcnow().isoformat()
        trigger = json.dumps({"every_seconds": _EVERY_S})
        if not rules and not merged["enabled"]:
            s.add(AutomationRule(account_id=body.account_id, name=name, kind=kind,
                                 trigger_json=trigger, steps_json="{}", is_enabled=False))
        await ensure_kind_rule(s, body.account_id, kind, enable=merged["enabled"],
                               name=name, every_seconds=_EVERY_S, steps=steps)
        await s.flush()
        rules = await rules_of_kind(s, body.account_id, kind)
        for rule in rules:
            rule.trigger_json = trigger
            rule.steps_json = json.dumps(steps)
        config = _public(kind, rules)
    log.info("lifecycle_message_config_saved account=%s kind=%s enabled=%s hours=%s",
             body.account_id, kind, config["enabled"], config["hours"])
    return {"account_id": body.account_id, "kind": kind, "config": config}


@router.get("/admin/lifecycle-message-config/buyers")
async def get_lifecycle_message_buyers(
    account_id: str = Query(...), kind: str = Query(...),
) -> dict[str, Any]:
    assert_account_owned(account_id)
    kind = _kind(kind)
    out = {"account_id": account_id, "kind": kind, "window_days": BUYERS_WINDOW_DAYS,
           "buyers": []}
    C, T = LifecycleMessageClaim, Transaction
    window = timedelta(days=BUYERS_WINDOW_DAYS)
    async with get_session() as s:
        claims = (await s.execute(
            select(C.fan_id, C.message_idx, C.created_at)
            .where(C.account_id == account_id, C.kind == kind, C.message_idx.is_not(None))
            .order_by(C.created_at.desc()).limit(_BUYERS_LIMIT * 10))).all()
        if not claims:
            return out
        ids = list({int(c.fan_id) for c in claims})
        sales: dict[int, list[tuple[datetime, int]]] = {}
        for fid, at, cents in (await s.execute(
                select(T.fan_id, T.occurred_at, T.amount_cents).where(
                    T.account_id == account_id, T.fan_id.in_(ids),
                    T.occurred_at >= min(c.created_at for c in claims),
                    T.amount_cents > 0, T.status.notin_(_NON_REVENUE_STATUSES)))).all():
            sales.setdefault(int(fid), []).append((at, int(cents)))
        names = {int(f): (u, n) for f, u, n in (await s.execute(
            select(Fan.fan_id, Fan.of_username, Fan.of_display_name).where(
                Fan.account_id == account_id, Fan.fan_id.in_(ids)))).all()}
    for c in claims:
        bought = [(at, cents) for at, cents in sales.get(int(c.fan_id), [])
                  if c.created_at <= at < c.created_at + window]
        if not bought:
            continue
        username, display = names.get(int(c.fan_id), (None, None))
        out["buyers"].append({
            "fan_id": int(c.fan_id), "username": username, "name": display,
            "message": int(c.message_idx) + 1, "sent_at": c.created_at.isoformat(),
            "spent_cents": sum(cents for _, cents in bought), "purchases": len(bought),
            "last_purchase_at": max(at for at, _ in bought).isoformat()})
        if len(out["buyers"]) >= _BUYERS_LIMIT:
            break
    return out
