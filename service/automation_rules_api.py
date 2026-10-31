"""service/automation_rules_api.py — CRUD over `automation_rules` for the
Automations control surface (the standalone /automations page).

The executor already runs the loop: `_materialize_due_rules` reads every
`is_enabled` rule each 30s tick and, when its `trigger_json={"every_seconds":N}`
cadence is due (and no job is already pending/running for that account+kind),
enqueues a `scheduled_jobs` row that the worker runs via `run_once`. This module
is just the operator's hands on that table — it never runs an automation inline.

Routes (all owner-gated via `auth`):

  GET    /admin/automation-kinds                  catalog of registered kinds + payload hints
  GET    /admin/automation-rules?account_id=      list rules (enriched: last run + next-due + pending)
  POST   /admin/automation-rules                  create a rule
  PATCH  /admin/automation-rules/{rule_id}        update name/enabled/interval/payload
  DELETE /admin/automation-rules/{rule_id}        delete a rule
  POST   /admin/automation-rules/{rule_id}/run-now  enqueue one immediate job (bypasses cadence)

A "rule" in the UI maps 1:1 to an `automation_rules` row. `every_seconds` is the
edited cadence (stored as `trigger_json`); `payload` is the per-run knob bag
(stored verbatim as `steps_json`). Both are validated here so a bad value can
never reach the executor.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from auth import assert_account_owned, clamp_account_filter
# The kind catalog lives in automation_catalog; re-exported here, as its
# callers and tests read `automation_rules_api._CATALOG` / `._kind_catalog`.
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

log = logging.getLogger("of-relay.automation.rules_api")

router = APIRouter()

# Executor tick is 30s, so a cadence below that just wastes materialize passes.
# Cap the high end at 30 days — beyond that it's effectively "off, but enabled".
_MIN_EVERY_S = 30
_MAX_EVERY_S = 30 * 24 * 60 * 60
# Only reachable for a kind with no catalog entry below — the same number the
# editor falls back to, so a rule born from a settings tab and one built by hand
# get the same cadence.
_FALLBACK_EVERY_S = 300



# Kind validity is automation_registry.is_registered — the ONE predicate
# (canonicalizes legacy names, knows scrape_chats). No local copy.


# ── Validation helpers ────────────────────────────────────────────────

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
    """Normalize a rich trigger into the stored `trigger_json` dict. Accepts:

      • {"every_seconds": N}                 — interval (existing behavior)
      • {"daily_at": ["HH:MM", ...],         — clock times (one fire per slot/day)
         "tz_offset_minutes": <int>}            local zone offset (UTC+min)
      • optional "max_runs": N on either     — auto-disable after N total runs

    Raises 422 on a malformed shape."""
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
    # Round-trips cleanly (rejects NaN/Infinity and non-serialisable values).
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"payload is not JSON-serialisable: {e}")
    return payload


def _coerce_whole(key: str, val: Any) -> int:
    """A JSON number that is a whole int (rejects bools, fractions, strings)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise HTTPException(422, f"{key} must be a whole number")
    n = int(val)
    if n != val:
        raise HTTPException(422, f"{key} must be a whole number")
    return n


def _validate_payload_for_kind(kind: str, payload: Any) -> dict:
    """`_validate_payload` (object + JSON-serialisable) PLUS per-knob value
    checks from the kind's catalog so the typed editor's contract is enforced
    server-side: int `min`/`max` bounds, `enum` membership, bool/str types, and
    id-list coercion (each id → int). Keys NOT in the catalog pass through
    untouched — forward-compat with payload fields newer than the catalog, and
    with the raw-JSON escape hatch. Returns the (coerced) payload dict."""
    payload = _validate_payload(payload)
    knobs = {k["key"]: k for k in _CATALOG.get(kind, {}).get("knobs", [])}
    out = dict(payload)
    for key, val in payload.items():
        kn = knobs.get(key)
        if kn is None:
            continue  # unknown/future knob — leave as-is
        if val is None:
            # ⚠️ A NULL FOR A CATALOGUED KNOB IS DROPPED AT THE BOUNDARY, not
            # stored and resolved later.
            #
            # `null` used to be waved through here as "an explicit null — leave
            # as-is", which made it the ONE non-boolean that reached storage for
            # a `bool` knob, and every reader downstream then had to know that
            # `null` means "absent" rather than "false". That knowledge landed at
            # eight Python read sites, at `app/lib/boolKnob.ts`, and at a
            # source-regex test that has to know every way a module might spell a
            # payload read — a lint written in `assert`s, whose own docstring
            # admits "a new spelling is a red here".
            #
            # A key that says nothing IS an absent key. Popping it makes that
            # true in the store instead of true by convention, and covers `int`,
            # `str` and `ids` at the same time — the same hole existed for all
            # four, and only the bool one had a defence built for it. `bool_knob`
            # and `boolKnob` keep their null clause: a rule written before this
            # line still carries stored nulls, so it is now a defence against
            # history rather than the contract.
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
        # "json": structured free-form — already proven serialisable above.
    if kind == "welcome_chatter_for_info":
        # The closing PPV: media with no price/caption uses the defaults (the
        # engine's `_CLOSING_PPV_DEFAULT_*`); the price bounds are the knob's.
        import smart_message_extras as extras
        media = out.get("closing_ppv_media_ids") or []
        if len(media) > extras.MEDIA_MAX:
            raise HTTPException(422, f"closing_ppv_media_ids: at most {extras.MEDIA_MAX} media")
    if kind == "send_welcome":
        # The Delayed welcome's Smart Message settings (media, price, dates,
        # Auto-unsend, the random delay), held to the same contract as the
        # other Triggers' config routes.
        import smart_message_extras as extras
        out.update(extras.validate(payload, delay=True))
        extras.check(out)
    return out


def _validate_quiet_hours(qh: Any) -> list[int] | None:
    """Opt-in quiet-hours band → `[start, end]` (creator-LOCAL hours, 0-23) or None.
    DEFAULT OFF: None / `[0, 0]` / equal start==end → None (rule fires 24/7). The
    band [start, end) wraps midnight when start > end. Same convention the executor
    enforces (`dispatch_plan.in_quiet_hours`) and nudge_online uses."""
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
    """Parse a JSON column to a dict, else None (for last_run.stats display)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _trigger_json(rule: AutomationRule) -> dict:
    """Parsed trigger_json (interval/clock + max_runs) for the editor."""
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
    """One rule + live status (last run, next-due estimate, pending job).

    `has_pending_job` is the materializer's own busy gate (automation_executor._pair_busy):
    a due pending/running job of the (account, kind), its kind_family, minus future-dated
    one-shots and fans' Smart Messages follow-up steps, so the badge and the gate agree.

    A legacy-kind row (migration 0062 not yet run on its DB) serializes under
    its CANONICAL name: runs and jobs are written canonical now, so querying
    status by the stored token would show a live rule as never-ran — and the
    UI's kind catalog only knows live names."""
    from automation_executor import _pair_busy  # local: avoid load cycle
    kind = canonical_kind(rule.kind)
    now = datetime.utcnow()
    trig = trigger_of(_trigger_json(rule))
    every = int(trig.every) if isinstance(trig, Interval) else None
    last = await _last_run(s, rule.account_id, kind)
    next_due_at: str | None = None
    if rule.is_enabled and trig is not None:
        # The materializer's own due math (dispatch_plan.next_due), interval or
        # clock, anchored on the rule's OWN jobs like it: a test or one-shot run of
        # the same kind must not move the displayed next fire. A rule that never
        # fired is due on the next tick; one at its max_runs shows none.
        fired = await rule_last_fired_at(s, rule.id)
        runs = None
        if trig.max_runs is not None:   # the pair's runs, counted as the materializer does
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
        # False = no runner: the rule is INERT however `is_enabled` reads (a
        # retired engine's leftover, or a plugin that failed to load). THE
        # kind-validity predicate — same one create/enqueue validate with, so
        # a creatable kind can never badge as unregistered. API-ready; no UI
        # consumer reads it yet.
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


# ── Request bodies ────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    account_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    name: str | None = None
    every_seconds: int = 300
    # Rich trigger (clock times / run-limit). When present it wins over
    # `every_seconds`; otherwise we store {"every_seconds": every_seconds}.
    trigger: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    # Opt-in quiet hours: [start, end] creator-local hours. Omit / [0,0] = off (24/7).
    quiet_hours: list[int] | None = None
    is_enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    every_seconds: int | None = None
    trigger: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    quiet_hours: list[int] | None = None   # pass [0,0] to clear, [s,e] to set
    is_enabled: bool | None = None


# ── OFF / DELETE reach the queue ──────────────────────────────────────

async def _cancel_queued(s, ids) -> int:
    """Cancel the still-PENDING jobs these rules queued.

    Switching a rule off used to stop only the NEXT materialization: a job it
    had already queued (a retry in backoff, one waiting out the in-flight lock,
    a drip's follow-on) still ran. Filtered by `rule_id`, never by kind — a
    rule-less one-shot of the same kind (auto_stories' delete-later cleanup,
    an "Unsend this" press) is not this rule's work and must survive. A job
    already `running` is left to finish; the executor won't requeue it.
    Callers own the transaction. Returns the number cancelled."""
    ids = [int(i) for i in ids if i is not None]
    if not ids:
        return 0
    res = await s.execute(
        update(ScheduledJob)
        .where(ScheduledJob.rule_id.in_(ids), ScheduledJob.status == "pending")
        .values(status="cancelled", last_error="rule switched off")
    )
    if res.rowcount:
        log.info("automation_rule_jobs_cancelled rules=%s jobs=%s", ids, res.rowcount)
    return res.rowcount or 0


# ── The rule behind a settings tab ────────────────────────────────────

async def ensure_kind_rule(
    s, account_id: str, kind: str, *, enable: bool,
    name: str | None = None, every_seconds: int | None = None,
    trigger: dict[str, Any] | None = None,
    steps: dict[str, Any] | None = None,
    persist_off: bool = False,
) -> str:
    """Find-or-create the account's rule for `kind` and set its switch.

    A settings tab's "Enabled" box writes that engine's CONFIG blob; what makes
    the engine tick is a row in this table, and the two used to be separate
    controls in separate panels — so a fully-configured engine could read
    "Enabled" on its own tab and never run. Every config endpoint that grew a
    fix for that hand-rolled its own find-or-create (four of them say "mirrors
    nudge_config_api._ensure_rule" in the docstring). This is that policy, once,
    in the module that owns the table.

    `enable=False` parks EVERY row of the kind: with two rows, parking one would
    leave the engine sending under a box that reads off. `enable=True` wakes the
    running-or-first row and parks (+ cancels the queue of) any other running
    duplicate, or creates one when the account has none — never a second ticker
    for the same kind.

    `name` / `every_seconds` / `steps` are written when given and left ALONE when
    not. `trigger` (a whole trigger dict, e.g. a `daily_at` clock) wins over
    `every_seconds` when both are given. A caller that owns the schedule (nudge,
    vault-ai) passes it on every save; one whose cadence the operator tunes in the rules editor
    passes nothing and keeps it. A CREATE takes its name and cadence from the
    catalog and its payload from `_CREATE_PAYLOAD` — which is NOT the editor's
    form output, so the two create paths deliberately differ; see that constant.
    An EXISTING row is never re-seeded with any of it.

    Queries `kind_family` — a pre-rename row still carries its retired name, and
    matching only the canonical one would silently create a duplicate beside it.
    Callers own the transaction; nothing here commits.

    `persist_off` (bulk roll-outs): an OFF still writes name / cadence / steps
    into the kept (parked) row — created parked when there is none — so the
    schedule an operator saved survives until the next ON.

    Returns "created" | "updated" | "parked" | "unchanged" (for the log line).
    """
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
        # Every parked row's queue, not just the ones that were running: a row
        # parked earlier can still own a pending Run-now or drip job.
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

    if not rules:
        s.add(_new_row(True))
        return "created"

    # Keep ONE row on — the running one (lowest id), else the oldest — and park
    # every other running duplicate with its queue: two live rows of one kind
    # are two tickers, and the next OFF would have to find both.
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


# ── Routes ────────────────────────────────────────────────────────────

@router.get("/admin/automation-kinds")
async def list_kinds() -> dict[str, Any]:
    """The registered automation kinds + payload hints — drives the editor."""
    return {"kinds": _kind_catalog()}


# Smart Messages' Sent column: the rule kinds it counts, by the
# `messages.automation_kind` each one's sender stamps on its outbound rows.
_SENT_KINDS: dict[str, str] = {
    "send_welcome": "welcome",
    "purchase_followup": "purchase_followup",
    "expiry_message": "expiry_message",
    "expired_message": "expired_message",
    "resubscribe_message": "resubscribe_message",
    "birthday_message": "birthday_message",
}


async def _sent_counts(s, account_ids: list[str]) -> dict[tuple[str, str], int]:
    """{(account, kind): messages it really sent} for the `_SENT_KINDS`: the
    outbound rows each sender writes only after OnlyFans accepted the send,
    read through `ix_messages_automation_kind`. A welcome is a burst of several
    rows, so it counts the fans welcomed; the others send one row per fan."""
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
    """purchase_followup is owner-only to switch on and restamps `enabled_at` on
    every off→on; only its own config route does both, so these writes refuse it.
    Switching it OFF (and nothing else) stays open here, so the Automations
    panel's toggle still stops it."""
    if canonical_kind(kind) == "purchase_followup" and not turning_off:
        raise HTTPException(409, "purchase_followup is set at /admin/purchase-followup-config")
    # The Smart Messages lifecycle Triggers: the same rule, at their own route.
    from automations.lifecycle_messages import KINDS as _LIFECYCLE
    if canonical_kind(kind) in _LIFECYCLE and not turning_off:
        raise HTTPException(409, f"{kind} is set at /admin/lifecycle-message-config")


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
    # Canonical at the write boundary: a caller still sending a retired kind
    # name gets the live rule, never a fresh legacy row.
    kind = canonical_kind(body.kind)
    if not is_registered(kind):
        raise HTTPException(422, f"unknown automation kind {body.kind!r}")
    # A My Automations kind (auto_posts, mass_premade…) needs its page, opt-in.
    await require_opt_in_kind(kind, body.account_id)
    _refuse_config_route_kind(kind)
    trigger = (_validate_trigger(body.trigger) if body.trigger is not None
               else {"every_seconds": _validate_every(body.every_seconds)})
    payload = _validate_payload_for_kind(kind, body.payload)
    quiet = _validate_quiet_hours(body.quiet_hours)
    name = (body.name or "").strip() or kind

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
    """The rule, if the session owns its Creator and, for a My Automations
    kind, may use that page (every caller writes or runs it)."""
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
        if body.quiet_hours is not None:   # [0,0] clears, [s,e] sets
            quiet = _validate_quiet_hours(body.quiet_hours)
            rule.quiet_hours_json = json.dumps(quiet) if quiet else None
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
        # Before the delete: the FK nulls `rule_id` on its jobs, after which
        # nothing could tell them apart from a rule-less one-shot.
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
    from automation_executor import enqueue_job, wake_supervisor  # local: avoid load cycle

    async with get_session() as s:
        rule = await _load_owned(s, rule_id)
        # Canonical, matching _serialize — a legacy rule must not LIST as the
        # live kind and then answer run-now with the retired token.
        account_id, kind = rule.account_id, canonical_kind(rule.kind)
        payload = _payload_of(rule)

    job_id = await enqueue_job(account_id, kind, payload=payload, rule_id=rule_id,
                               created_by_employee_id=await _acting_employee(request, account_id))
    wake_supervisor()  # drain NOW (W7 pattern) — don't wait for the 30s poll tick
    log.info("automation_rule_run_now id=%s job=%s account=%s kind=%s",
             rule_id, job_id, account_id, kind)
    return {"enqueued_job_id": job_id, "account_id": account_id, "kind": kind}


async def _acting_employee(request: Request, account_id: str) -> int | None:
    """The employee acting in the app (owner or chatter session, or the picked
    `X-Employee-Id`), as the composer stamps a send. A job carrying it is an
    operator's: the supervisor runs it ahead of automation. None outside a
    session (a script without one): the job queues as automation."""
    from employees import resolve_outbound_employee_id  # local: avoid load cycle
    try:
        return await resolve_outbound_employee_id(request, account_id)
    except Exception:
        log.warning("acting_employee_resolve_failed account=%s", account_id, exc_info=True)
        return None


class EnqueueBody(BaseModel):
    account_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    payload: dict[str, Any] | None = None
    run_at: datetime | None = None  # default: now (immediate)


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
    # Attribute the job to the acting employee: the operator tier (ADR 0025).
    employee_id = await _acting_employee(request, body.account_id)

    from automation_executor import enqueue_job, wake_supervisor  # local: avoid load cycle
    job_id = await enqueue_job(
        body.account_id, kind,
        payload=payload, run_at=body.run_at,
        created_by_employee_id=employee_id,
    )
    # Drain NOW for immediate jobs (W7 pattern). A wake with only a future-dated
    # job pending is a harmless no-op — the supervisor only claims due jobs.
    if body.run_at is None:
        wake_supervisor()
    log.info("automation_enqueue_one_shot job=%s account=%s kind=%s by_emp=%s",
             job_id, body.account_id, kind, employee_id)
    return {"enqueued_job_id": job_id, "account_id": body.account_id, "kind": kind}
