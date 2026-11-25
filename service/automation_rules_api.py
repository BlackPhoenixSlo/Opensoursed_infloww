from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from auth import assert_account_owned, clamp_account_filter
from automation_catalog import (  # noqa: F401
    _CATALOG, _CREATE_PAYLOAD, _WIDGET_FOR_TYPE, _decorate_knob, _kind_catalog,
)
from automation_registry import canonical_kind, is_registered, kind_family
from db.engine import get_session
from db.models import AutomationRule, AutomationRun, Message, ScheduledJob
from dispatch_plan import TZ_MAX, TZ_MIN, Interval, next_due, trigger_of, tz_offset
from isotime import iso_plain
from job_queue import rule_last_fired_at
from permissions import require_opt_in_kind
from run_decide import payload_rule_id

log = logging.getLogger("of-relay.automation.rules_api")

router = APIRouter()

# Executor tick is 30s, so a lower cadence wastes passes; the 30-day cap is effectively "off".
_MIN_EVERY_S = 30
_MAX_EVERY_S = 30 * 24 * 60 * 60
_FALLBACK_EVERY_S = 300






def _validate_every(every_seconds: Any) -> int:
    if not isinstance(every_seconds, (int, float)) or isinstance(every_seconds, bool):
        raise HTTPException(422, "every_seconds must be a number")
    n = int(every_seconds)
    if n < _MIN_EVERY_S:
        raise HTTPException(422, f"every_seconds must be ≥ {_MIN_EVERY_S} (executor ticks every 30s)")
    if n > _MAX_EVERY_S:
        raise HTTPException(422, f"every_seconds must be ≤ {_MAX_EVERY_S}")
    return n


def _validate_trigger(trigger: Any) -> dict:
    if not isinstance(trigger, dict):
        raise HTTPException(422, "trigger must be a JSON object")
    out: dict[str, Any] = {}

    daily_at = trigger.get("daily_at")
    if daily_at is not None:
        if not isinstance(daily_at, list) or not daily_at:
            raise HTTPException(422, "daily_at must be a non-empty list of 'HH:MM'")
        norm: list[str] = []
        for t in daily_at:
            if not isinstance(t, str) or ":" not in t:
                raise HTTPException(422, f"bad time {t!r} (want 'HH:MM')")
            try:
                hh, mm = (int(x) for x in t.split(":", 1))
            except ValueError:
                raise HTTPException(422, f"bad time {t!r} (want 'HH:MM')")
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise HTTPException(422, f"time out of range: {t!r}")
            norm.append(f"{hh:02d}:{mm:02d}")
        out["daily_at"] = norm
        tz = trigger.get("tz_offset_minutes", 0)
        # dispatch_plan.tz_offset is what the materializer accepts; an explicit null stays a 422.
        off = None if tz is None else tz_offset(tz)
        if off is None:
            raise HTTPException(422, f"tz_offset_minutes must be between {TZ_MIN} and {TZ_MAX}")
        out["tz_offset_minutes"] = off
    elif trigger.get("every_seconds") is not None:
        out["every_seconds"] = _validate_every(trigger["every_seconds"])
    else:
        raise HTTPException(422, "trigger needs every_seconds or daily_at")

    max_runs = trigger.get("max_runs")
    if max_runs is not None:
        if not isinstance(max_runs, (int, float)) or isinstance(max_runs, bool) or max_runs < 1:
            raise HTTPException(422, "max_runs must be a positive integer")
        out["max_runs"] = int(max_runs)
    return out


def _validate_payload(payload: Any) -> dict:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "payload must be a JSON object")
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"payload is not JSON-serialisable: {e}")
    return payload


def _coerce_whole(key: str, val: Any) -> int:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise HTTPException(422, f"{key} must be a whole number")
    n = int(val)
    if n != val:
        raise HTTPException(422, f"{key} must be a whole number")
    return n


def _validate_payload_for_kind(kind: str, payload: Any) -> dict:
    payload = _validate_payload(payload)
    knobs = {k["key"]: k for k in _CATALOG.get(kind, {}).get("knobs", [])}
    out = dict(payload)
    for key, val in payload.items():
        kn = knobs.get(key)
        if kn is None:
            continue
        if val is None:
            # Null for a catalogued knob is dropped here, not stored; bool_knob/boolKnob keep their null clause for rows saved before.
            out.pop(key, None)
            continue
        t = kn["type"]
        if t == "int":
            n = _coerce_whole(key, val)
            lo, hi = kn.get("min"), kn.get("max")
            if lo is not None and n < lo:
                raise HTTPException(422, f"{key} must be ≥ {lo}")
            if hi is not None and n > hi:
                raise HTTPException(422, f"{key} must be ≤ {hi}")
            out[key] = n
        elif t == "bool":
            if not isinstance(val, bool):
                raise HTTPException(422, f"{key} must be true or false")
        elif t == "str":
            if not isinstance(val, str):
                raise HTTPException(422, f"{key} must be text")
            enum = kn.get("enum")
            if enum and val not in enum:
                raise HTTPException(422, f"{key} must be one of {', '.join(map(str, enum))}")
        elif t == "ids":
            if not isinstance(val, list):
                raise HTTPException(422, f"{key} must be a list of ids")
            out[key] = [_coerce_whole(key, x) for x in val]
    if kind == "welcome_chatter_for_info":
        import smart_message_extras as extras
        media = out.get("closing_ppv_media_ids") or []
        if len(media) > extras.MEDIA_MAX:
            raise HTTPException(422, f"closing_ppv_media_ids: at most {extras.MEDIA_MAX} media")
    if kind == "send_welcome":
        import smart_message_extras as extras
        out.update(extras.validate(payload, delay=True))
        extras.check(out)
    return out


def _validate_quiet_hours(qh: Any) -> list[int] | None:
    if qh is None:
        return None
    if not isinstance(qh, (list, tuple)) or len(qh) != 2:
        raise HTTPException(422, "quiet_hours must be [start_hour, end_hour]")
    try:
        start, end = int(qh[0]), int(qh[1])
    except (TypeError, ValueError):
        raise HTTPException(422, "quiet_hours must be two integers")
    if not (0 <= start < 24 and 0 <= end < 24):
        raise HTTPException(422, "quiet_hours must be hours 0-23")
    return None if start == end else [start, end]


def _safe_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _trigger_json(rule: AutomationRule) -> dict:
    try:
        t = json.loads(rule.trigger_json or "{}")
        return t if isinstance(t, dict) else {}
    except (TypeError, ValueError):
        return {}


def _payload_of(rule: AutomationRule) -> dict:
    try:
        p = json.loads(rule.steps_json or "{}")
    except (TypeError, ValueError):
        return {}
    return p if isinstance(p, dict) else {}


async def _last_run(s, account_id: str, kind: str) -> AutomationRun | None:
    return (
        await s.execute(
            select(AutomationRun)
            .where(AutomationRun.account_id == account_id, AutomationRun.kind == kind)
            .order_by(AutomationRun.started_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def _serialize(s, rule: AutomationRule) -> dict[str, Any]:
    from automation_executor import _pair_busy
    kind = canonical_kind(rule.kind)
    now = datetime.utcnow()
    trig = trigger_of(_trigger_json(rule))
    every = int(trig.every) if isinstance(trig, Interval) else None
    last = await _last_run(s, rule.account_id, kind)
    next_due_at: str | None = None
    if rule.is_enabled and trig is not None:
        fired = await rule_last_fired_at(s, rule.id)
        runs = None
        if trig.max_runs is not None:
            runs = (await s.execute(
                select(func.count()).select_from(AutomationRun)
                .where(AutomationRun.account_id == rule.account_id, AutomationRun.kind == kind)
            )).scalar_one()
        next_due_at = iso_plain(next_due(trig, fired, now, run_count=runs))
    return {
        "id": rule.id,
        "account_id": rule.account_id,
        "name": rule.name,
        "kind": kind,
        # False = no runner: the rule is inert however is_enabled reads.
        "kind_registered": is_registered(kind),
        "is_enabled": rule.is_enabled,
        "every_seconds": every,
        "trigger": _trigger_json(rule),
        "payload": _payload_of(rule),
        "quiet_hours": json.loads(rule.quiet_hours_json) if rule.quiet_hours_json else None,
        "created_at": iso_plain(rule.created_at),
        "last_run": None if last is None else {
            "status": last.status,
            "started_at": iso_plain(last.started_at),
            "completed_at": iso_plain(last.completed_at),
            "error_text": last.error_text,
            "stats": _safe_json(last.stats_json),
        },
        "next_due_at": next_due_at,
        "has_pending_job": await _pair_busy(s, rule, now) is not None,
    }



class RuleCreate(BaseModel):
    account_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    name: str | None = None
    every_seconds: int = 300
    trigger: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    quiet_hours: list[int] | None = None
    is_enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    every_seconds: int | None = None
    trigger: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    quiet_hours: list[int] | None = None
    is_enabled: bool | None = None



async def _cancel_queued(s, ids) -> int:
    # Cancel by rule, never by kind: a rule-less one-shot of the same kind must survive.
    ids = [int(i) for i in ids if i is not None]
    if not ids:
        return 0
    wanted = set(ids)
    accounts = select(AutomationRule.account_id).where(AutomationRule.id.in_(ids))
    hooked = [jid for jid, pj in (await s.execute(
        select(ScheduledJob.id, ScheduledJob.payload_json).where(
            ScheduledJob.rule_id.is_(None), ScheduledJob.status == "pending",
            ScheduledJob.account_id.in_(accounts)))).all()
        if payload_rule_id(pj) in wanted]
    res = await s.execute(
        update(ScheduledJob)
        .where(or_(ScheduledJob.rule_id.in_(ids), ScheduledJob.id.in_(hooked)),
               ScheduledJob.status == "pending")
        .values(status="cancelled", last_error="rule switched off")
    )
    if res.rowcount:
        log.info("automation_rule_jobs_cancelled rules=%s jobs=%s", ids, res.rowcount)
    return res.rowcount or 0



async def ensure_kind_rule(
    s, account_id: str, kind: str, *, enable: bool,
    name: str | None = None, every_seconds: int | None = None,
    trigger: dict[str, Any] | None = None,
    steps: dict[str, Any] | None = None,
    persist_off: bool = False,
) -> str:
    # Query kind_family: a pre-rename row keeps its retired name and matching only the canonical one would create a duplicate.
    kind = canonical_kind(kind)
    rules = list((await s.execute(
        select(AutomationRule).where(
            AutomationRule.account_id == str(account_id),
            AutomationRule.kind.in_(kind_family(kind)),
        ).order_by(AutomationRule.id)
    )).scalars())

    if trigger is not None:
        trigger_json = json.dumps(trigger)
    elif every_seconds is not None:
        trigger_json = json.dumps({"every_seconds": int(every_seconds)})
    else:
        trigger_json = None

    meta = _CATALOG.get(kind) or {}

    def _new_row(on: bool) -> AutomationRule:
        return AutomationRule(
            account_id=str(account_id), kind=kind,
            name=(name or meta.get("label") or kind),
            trigger_json=trigger_json or json.dumps({"every_seconds": int(
                meta.get("cadence_default_s") or _FALLBACK_EVERY_S)}),
            steps_json=json.dumps(steps if steps is not None
                                  else _CREATE_PAYLOAD.get(kind, {})),
            is_enabled=on)

    if not enable:
        running = [r for r in rules if r.is_enabled]
        for r in running:
            r.is_enabled = False
        await _cancel_queued(s, [r.id for r in rules])
        if persist_off:
            if not rules:
                s.add(_new_row(False))
                return "created"
            keep = running[0] if running else rules[0]
            if name:
                keep.name = name
            if trigger_json is not None:
                keep.trigger_json = trigger_json
            if steps is not None:
                keep.steps_json = json.dumps(steps)
        return "parked" if running else "unchanged"

    if not any(r.is_enabled for r in rules):
        from tenant_keys_api import require_llm_key
        await require_llm_key(str(account_id), kind)

    if not rules:
        s.add(_new_row(True))
        return "created"

    # Keep ONE row on and park other running duplicates with their queue: two live rows of a kind are two tickers.
    rule = next((r for r in rules if r.is_enabled), rules[0])
    dupes = [r for r in rules if r is not rule and r.is_enabled]
    for r in dupes:
        r.is_enabled = False
    if dupes:
        await _cancel_queued(s, [r.id for r in dupes])
    changed = not rule.is_enabled or bool(dupes)
    rule.is_enabled = True
    if name and rule.name != name:
        rule.name = name
        changed = True
    if trigger_json is not None:
        changed = changed or rule.trigger_json != trigger_json
        rule.trigger_json = trigger_json
    if steps is not None:
        payload = json.dumps(steps)
        changed = changed or rule.steps_json != payload
        rule.steps_json = payload
    return "updated" if changed else "unchanged"



@router.get("/admin/automation-kinds")
async def list_kinds() -> dict[str, Any]:
    """The registered automation kinds + payload hints — drives the editor."""
    return {"kinds": _kind_catalog()}


_SENT_KINDS: dict[str, str] = {
    "send_welcome": "welcome",
    "purchase_followup": "purchase_followup",
    "expiry_message": "expiry_message",
    "expired_message": "expired_message",
    "resubscribe_message": "resubscribe_message",
    "birthday_message": "birthday_message",
}


async def _sent_counts(s, account_ids: list[str]) -> dict[tuple[str, str], int]:
    # Counts only rows written after OF accepted the send; a welcome burst counts fans welcomed.
    if not account_ids:
        return {}
    to_kind = {v: k for k, v in _SENT_KINDS.items()}
    rows = (await s.execute(
        select(Message.account_id, Message.automation_kind, func.count(),
               func.count(func.distinct(Message.fan_id)))
        .where(Message.account_id.in_(account_ids),
               Message.automation_kind.in_(list(to_kind)))
        .group_by(Message.account_id, Message.automation_kind))).all()
    return {(acc, to_kind[ak]): int(fans if ak == "welcome" else n)
            for acc, ak, n, fans in rows}


@router.get("/admin/automation-rules")
async def list_rules(account_id: str | None = Query(None)) -> dict[str, Any]:
    account_ids = clamp_account_filter(account_id)
    async with get_session() as s:
        q = select(AutomationRule)
        if account_ids is not None:
            q = q.where(AutomationRule.account_id.in_(account_ids))
        q = q.order_by(AutomationRule.kind, AutomationRule.id)
        rules = (await s.execute(q)).scalars().all()
        sent = await _sent_counts(s, sorted({
            r.account_id for r in rules if canonical_kind(r.kind) in _SENT_KINDS}))
        out = []
        for r in rules:
            row = await _serialize(s, r)
            if row["kind"] in _SENT_KINDS:
                row["sent"] = sent.get((r.account_id, row["kind"]), 0)
            out.append(row)
        return {"rules": out}


class KindSwitch(BaseModel):
    account_id: str
    kind: str
    enable: bool


def _refuse_config_route_kind(kind: str, *, turning_off: bool = False) -> None:
    # purchase_followup is owner-only to switch on and restamps enabled_at, so only its own route may; OFF stays open here.
    if canonical_kind(kind) == "purchase_followup" and not turning_off:
        raise HTTPException(409, "purchase_followup is set at /admin/purchase-followup-config")
    from automations.lifecycle_messages import KINDS as _LIFECYCLE
    if canonical_kind(kind) in _LIFECYCLE and not turning_off:
        raise HTTPException(409, f"{kind} is set at /admin/lifecycle-message-config")
    # Full AI Chat: only its Mode page switches it on; a re-enable here could wake a parked rule still marked Live.
    if canonical_kind(kind) == "full_ai_chat" and not turning_off:
        raise HTTPException(409, "full_ai_chat is set at /admin/full-ai/mode")


@router.post("/admin/automation-rules/switch")
async def switch_kind(body: KindSwitch = Body(...)) -> dict[str, Any]:
    """Turn an automation KIND on or off for an account, in one write.

    The switch a settings tab shows. Its callers do not want to know whether the
    account already has a row, how many, or what cadence a new one gets — and a
    client that DID know parked two rules with two requests, so a failure between
    them left the account half-off. `ensure_kind_rule` is that decision, made once
    and applied inside a single transaction.
    """
    assert_account_owned(body.account_id)
    kind = canonical_kind(body.kind)
    if not is_registered(kind):
        raise HTTPException(422, f"unknown automation kind {body.kind!r}")
    await require_opt_in_kind(kind, body.account_id)
    _refuse_config_route_kind(kind, turning_off=not body.enable)
    async with get_session() as s:
        action = await ensure_kind_rule(s, body.account_id, kind, enable=body.enable)
    log.info("automation_kind_switch account=%s kind=%s enable=%s action=%s",
             body.account_id, kind, body.enable, action)
    return {"account_id": body.account_id, "kind": kind,
            "enable": body.enable, "action": action}


@router.post("/admin/automation-rules")
async def create_rule(body: RuleCreate = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    # Canonical at the write boundary: a retired kind name gets the live rule, never a fresh legacy row.
    kind = canonical_kind(body.kind)
    if not is_registered(kind):
        raise HTTPException(422, f"unknown automation kind {body.kind!r}")
    await require_opt_in_kind(kind, body.account_id)
    _refuse_config_route_kind(kind)
    trigger = (_validate_trigger(body.trigger) if body.trigger is not None
               else {"every_seconds": _validate_every(body.every_seconds)})
    payload = _validate_payload_for_kind(kind, body.payload)
    quiet = _validate_quiet_hours(body.quiet_hours)
    name = (body.name or "").strip() or kind
    if body.is_enabled:
        from tenant_keys_api import require_llm_key
        await require_llm_key(body.account_id, kind)

    async with get_session() as s:
        rule = AutomationRule(
            account_id=body.account_id,
            name=name,
            kind=kind,
            trigger_json=json.dumps(trigger),
            steps_json=json.dumps(payload),
            quiet_hours_json=json.dumps(quiet) if quiet else None,
            is_enabled=bool(body.is_enabled),
        )
        s.add(rule)
        await s.flush()
        out = await _serialize(s, rule)
    log.info("automation_rule_created id=%s account=%s kind=%s enabled=%s",
             out["id"], body.account_id, body.kind, body.is_enabled)
    return out


async def _load_owned(s, rule_id: int) -> AutomationRule:
    rule = await s.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "rule not found")
    assert_account_owned(rule.account_id)
    await require_opt_in_kind(canonical_kind(rule.kind), rule.account_id)
    return rule


@router.patch("/admin/automation-rules/{rule_id}")
async def update_rule(rule_id: int, body: RulePatch = Body(...)) -> dict[str, Any]:
    async with get_session() as s:
        rule = await _load_owned(s, rule_id)
        _refuse_config_route_kind(rule.kind, turning_off=body.is_enabled is False and all(
            getattr(body, f) is None for f in RulePatch.model_fields if f != "is_enabled"))
        if body.name is not None:
            nm = body.name.strip()
            if not nm:
                raise HTTPException(422, "name cannot be blank")
            rule.name = nm
        if body.trigger is not None:
            rule.trigger_json = json.dumps(_validate_trigger(body.trigger))
        elif body.every_seconds is not None:
            rule.trigger_json = json.dumps({"every_seconds": _validate_every(body.every_seconds)})
        if body.payload is not None:
            rule.steps_json = json.dumps(
                _validate_payload_for_kind(canonical_kind(rule.kind), body.payload))
        if body.quiet_hours is not None:
            quiet = _validate_quiet_hours(body.quiet_hours)
            rule.quiet_hours_json = json.dumps(quiet) if quiet else None
        if body.is_enabled and not rule.is_enabled:
            from tenant_keys_api import require_llm_key
            await require_llm_key(rule.account_id, canonical_kind(rule.kind))
        if body.is_enabled is not None:
            rule.is_enabled = bool(body.is_enabled)
            if not rule.is_enabled:
                await _cancel_queued(s, [rule.id])
        await s.flush()
        out = await _serialize(s, rule)
    log.info("automation_rule_updated id=%s enabled=%s", rule_id, out["is_enabled"])
    return out


@router.delete("/admin/automation-rules/{rule_id}")
async def delete_rule(rule_id: int) -> dict[str, Any]:
    async with get_session() as s:
        rule = await _load_owned(s, rule_id)
        # Before the delete: the FK nulls rule_id on its jobs, after which they look like rule-less one-shots.
        await _cancel_queued(s, [rule.id])
        await s.delete(rule)
    log.info("automation_rule_deleted id=%s", rule_id)
    return {"deleted": rule_id}


@router.post("/admin/automation-rules/{rule_id}/run-now")
async def run_now(rule_id: int, request: Request) -> dict[str, Any]:
    """Enqueue one immediate job for this rule, bypassing the cadence. The
    supervisor is woken right after enqueue so it drains and runs the job
    immediately (~5ms) instead of waiting up to a 30s poll tick. No-op-safe if
    a job is already pending for this (account, kind) — the executor dedups.
    The job carries the acting employee: an operator's job, which the
    supervisor runs in the operator tier (never behind automation)."""
    from automation_executor import enqueue_job, wake_supervisor

    async with get_session() as s:
        rule = await _load_owned(s, rule_id)
        account_id, kind = rule.account_id, canonical_kind(rule.kind)
        payload = _payload_of(rule)

    job_id = await enqueue_job(account_id, kind, payload=payload, rule_id=rule_id,
                               created_by_employee_id=await _acting_employee(request, account_id))
    wake_supervisor()
    log.info("automation_rule_run_now id=%s job=%s account=%s kind=%s",
             rule_id, job_id, account_id, kind)
    return {"enqueued_job_id": job_id, "account_id": account_id, "kind": kind}


async def _acting_employee(request: Request, account_id: str) -> int | None:
    from employees import resolve_outbound_employee_id
    try:
        return await resolve_outbound_employee_id(request, account_id)
    except Exception:
        log.warning("acting_employee_resolve_failed account=%s", account_id, exc_info=True)
        return None


class EnqueueBody(BaseModel):
    account_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    payload: dict[str, Any] | None = None
    run_at: datetime | None = None


@router.post("/admin/automation/enqueue")
async def enqueue_one_shot(
    request: Request, body: EnqueueBody = Body(...)
) -> dict[str, Any]:
    """Fire a single one-shot automation job WITHOUT a persistent rule — the
    trigger seam for action-style kinds the UI launches by hand (auto_posts,
    mass_premade, unsend_messages, the chat ↻ refresh's scrape_chats). For an
    immediate job (no `run_at`) the supervisor is woken right after enqueue so it
    drains and runs in ~5ms instead of waiting up to a 30s poll tick.
    `run_at` schedules it for the future; omitted = immediate."""
    assert_account_owned(body.account_id)
    kind = canonical_kind(body.kind)
    if not is_registered(kind):
        raise HTTPException(422, f"unknown automation kind {body.kind!r}")
    await require_opt_in_kind(kind, body.account_id)
    payload = _validate_payload_for_kind(kind, body.payload)
    employee_id = await _acting_employee(request, body.account_id)

    from automation_executor import enqueue_job, wake_supervisor
    job_id = await enqueue_job(
        body.account_id, kind,
        payload=payload, run_at=body.run_at,
        created_by_employee_id=employee_id,
    )
    if body.run_at is None:
        wake_supervisor()
    log.info("automation_enqueue_one_shot job=%s account=%s kind=%s by_emp=%s",
             job_id, body.account_id, kind, employee_id)
    return {"enqueued_job_id": job_id, "account_id": body.account_id, "kind": kind}
