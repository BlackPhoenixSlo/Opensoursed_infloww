"""service/assistant_edit.py — do-mode's `mass_edit`: change settings on EXISTING Auto mass rules.

Spec D11 (owner 2026-11-12, overrides the pilot's "never edit an existing rule /
never touch another account"): the help bot may bulk-edit the asker's existing
Auto mass rules — here, or on every model the session owns — but never turns a
rule ON. The LLM only says WHAT changes (`Edit`); everything else is here:

  • `clean_changes` — the change spec, whitelisted + clamped (the draft's
    output AND the apply route's input go through it; never trust either).
  • `apply_changes(kind, payload, every_seconds, is_enabled, changes)` — pure,
    keyed by kind (`APPLIERS`, mass_premade only). Raises `Skip(reason)` when a
    rule would become invalid (price without media, online-only without a list).
  • `plan_rules` — pure: which rules match, their before→after diffs, the ones
    already matching and the ones skipped. `resolve_rules` is its DB read.
  • `apply_one` — the apply route's per-rule write: reload the row the session
    owns, compare `rule_version`, re-apply the change spec to the FRESH row
    (never a client payload), validate as the editor's PATCH does, write only
    if the row is still the one read (conditional UPDATE), cancel queued jobs
    when it was switched off, log the old steps hash. Any failure = that
    rule's skip.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update

from auth import clamp_account_filter
from db.engine import get_session
from db.models import Account, AutomationRule

log = logging.getLogger("of-relay.assistant_edit")

EDIT_FLOW = "mass_edit"
KIND = "mass_premade"
MIN_EVERY_S, MAX_EVERY_S = 5 * 60, 168 * 3600      # the draft's interval range
MIN_UNSEND_H, MAX_UNSEND_H = 0.08, 168.0
MAX_SKIP_H = 168.0
PRICE_MIN, PRICE_MAX = 3, 200                       # priority_mass _PRICE_MIN/_PRICE_MAX ($)
MEDIA_MAX = 40                                      # MediaPool MEDIA_MAX
ONE_MODEL_ONLY = ("price", "media_count")           # never on scope "all"
MAX_RULES = 500

LABELS = {
    "unsend_after_hours": "Unsend after",
    "online_only": "Online fans only",
    "every_seconds": "Every",
    "exclude_last_chat_hours": "Skip fans chatted with in the last",
    "price": "Price",
    "media_count": "Photos per mass",
    "is_enabled": "Enabled",
}
ONE_MODEL_NOTE = "Price and photo count change on one model at a time — ask on that model."
CHANGED_SINCE = "changed since you saw it"


class Skip(Exception):
    """This rule can't take the change; `str(e)` is the reason the user reads."""


# ── What the LLM may say ──────────────────────────────────────────────

class EditEvery(BaseModel):
    value: float | None = Field(None, allow_inf_nan=False)
    unit: str | None = None


class EditChanges(BaseModel):
    unsend_after_hours: float | None = Field(None, allow_inf_nan=False)   # 0 = off
    online_only: bool | None = None
    every: EditEvery | None = None
    exclude_last_chat_hours: float | None = Field(None, allow_inf_nan=False)  # 0 = off
    price: float | None = Field(None, allow_inf_nan=False)
    media_count: float | None = Field(None, allow_inf_nan=False)
    disable_rule: bool = False

    @model_validator(mode="before")
    @classmethod
    def _null_disable(cls, v):
        if isinstance(v, dict) and v.get("disable_rule") is None:
            v = {k: x for k, x in v.items() if k != "disable_rule"}
        return v


class Edit(BaseModel):
    scope: str = "this"
    match: str | None = None
    changes: EditChanges = Field(default_factory=EditChanges)

    @model_validator(mode="before")
    @classmethod
    def _nulls(cls, v):
        if isinstance(v, dict):
            v = {k: x for k, x in v.items() if not (x is None and k in ("scope", "changes"))}
        return v


# ── The change spec (pure) ────────────────────────────────────────────

def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


def clean_changes(raw: Any) -> dict[str, Any]:
    """Whitelist + clamp a change spec. Keys: unsend_after_hours (0 = off),
    online_only, every_seconds, exclude_last_chat_hours (0 = off), price
    (0 = free), media_count, disable_rule (only True is kept — nothing here
    turns a rule on). Anything else, or a wrong type, is dropped."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    if (u := _num(raw.get("unsend_after_hours"))) is not None:
        out["unsend_after_hours"] = 0 if u <= 0 else round(_clamp(u, MIN_UNSEND_H, MAX_UNSEND_H), 3)
    if isinstance(raw.get("online_only"), bool):
        out["online_only"] = raw["online_only"]
    if (e := _num(raw.get("every_seconds"))) is not None and e > 0:
        out["every_seconds"] = int(round(_clamp(e, MIN_EVERY_S, MAX_EVERY_S)))
    if (h := _num(raw.get("exclude_last_chat_hours"))) is not None:
        out["exclude_last_chat_hours"] = 0 if h <= 0 else round(_clamp(h, 0.01, MAX_SKIP_H), 2)
    if (p := _num(raw.get("price"))) is not None:
        out["price"] = 0 if p <= 0 else round(_clamp(p, PRICE_MIN, PRICE_MAX), 2)
    if (m := _num(raw.get("media_count"))) is not None and m > 0:
        out["media_count"] = int(_clamp(round(m), 1, MEDIA_MAX))
    if raw.get("disable_rule") is True:
        out["disable_rule"] = True
    return out


def changes_of(c: EditChanges) -> dict[str, Any]:
    """The LLM's changes → the raw (unclamped) change spec `clean_changes` takes."""
    out: dict[str, Any] = {}
    for k in ("unsend_after_hours", "online_only", "exclude_last_chat_hours", "price", "media_count"):
        if getattr(c, k) is not None:
            out[k] = getattr(c, k)
    if c.every is not None and c.every.value:
        mult = 3600 if (c.every.unit or "").lower().startswith("h") else 60
        out["every_seconds"] = c.every.value * mult
    if c.disable_rule:
        out["disable_rule"] = True
    return out


# ── Appliers (pure) ───────────────────────────────────────────────────

def _int_ids(v: Any) -> list:
    return [x for x in v if isinstance(x, int) and not isinstance(x, bool)
            or isinstance(x, str) and x.strip().lstrip("+-").isdigit()] if isinstance(v, list) else []


def _has_media(it: dict) -> bool:
    """mass_premade `has_media_source`: an int-able media id or a folder."""
    return bool(_int_ids(it.get("media_files"))) or it.get("media_folder_id") is not None


def _pos(v: Any) -> float | None:
    n = _num(v)
    return n if n is not None and n > 0 else None


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0) or (
        isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"))


def _set_or_pop(it: dict, key: str, value: Any) -> None:
    if value is None:
        it.pop(key, None)
    else:
        it[key] = value


Befores = list[tuple[Any, int]]      # each distinct prior value, with how many messages had it


def _apply_mass_premade(payload: dict, ch: dict[str, Any]) -> list[tuple[str, Befores, Any]]:
    """Mutates `payload["messages"]` items; returns (field, befores, after) per
    changed field — every distinct prior value across the messages, with its
    count (rwl W30 F7: $5 and $50 both show, never only the first)."""
    msgs = payload.get("messages")
    items = [m for m in msgs if isinstance(m, dict)] if isinstance(msgs, list) else []
    if not items:
        raise Skip("has no message to change")
    seen: dict[str, dict[Any, int]] = {}
    afters: dict[str, Any] = {}
    changed: set[str] = set()

    def note(key: str, before: Any, after: Any) -> None:
        counts = seen.setdefault(key, {})
        counts[before] = counts.get(before, 0) + 1
        afters[key] = after
        if before != after:
            changed.add(key)

    for it in items:
        if "unsend_after_hours" in ch:
            before = _pos(it.get("unsend_after_hours"))
            after = ch["unsend_after_hours"] or None
            _set_or_pop(it, "unsend_after_hours", after)
            note("unsend_after_hours", before, after)
        if "online_only" in ch:
            # The sender also reads `filters.online` as online-only (send_mass_decide, readyMadeContent filtersOf).
            filters = it.get("filters") if isinstance(it.get("filters"), dict) else None
            before = bool(it.get("online_only")) or _truthy((filters or {}).get("online"))
            if ch["online_only"] and not it.get("user_lists"):
                raise Skip("online-only needs a fan list on the rule")
            _set_or_pop(it, "online_only", True if ch["online_only"] else None)
            if not ch["online_only"] and filters is not None and "online" in filters:
                filters.pop("online")
                if not filters:
                    it.pop("filters")
                if not it.get("user_lists") and not it.get("recipients") and not it.get("filters"):
                    raise Skip("its only audience is online fans — pick a fan list in the form first")
            note("online_only", before, ch["online_only"])
        if "exclude_last_chat_hours" in ch:
            before = _pos(it.get("exclude_last_chat_hours"))
            after = ch["exclude_last_chat_hours"] or None
            _set_or_pop(it, "exclude_last_chat_hours", after)
            note("exclude_last_chat_hours", before, after)
        if "price" in ch:
            before = _pos(it.get("price"))
            after = ch["price"] or None
            if after and not _has_media(it):
                raise Skip("a price needs photos — this rule has no folder or media")
            _set_or_pop(it, "price", after)
            note("price", before, after)
        if "media_count" in ch:
            if not _has_media(it):
                raise Skip("photo count needs a folder or media on the rule")
            before = int(_pos(it.get("media_count")) or 1)
            it["media_count"] = ch["media_count"]
            note("media_count", before, ch["media_count"])
    return [(k, list(seen[k].items()), afters[k]) for k in seen if k in changed]


APPLIERS: dict[str, Callable[[dict, dict[str, Any]], list[tuple[str, Befores, Any]]]] = {
    KIND: _apply_mass_premade,
}


def apply_changes(kind: str, payload: dict, every_seconds: int | None, is_enabled: bool,
                  changes: dict[str, Any]) -> tuple[dict, int | None, bool, list[dict]]:
    """Pure: the rule after the change → (payload, every_seconds,
    is_enabled, diffs[{field, label, before, after}]). `every_seconds` None =
    the rule runs at set times (an `every` change is then a Skip). Never
    turns a rule on. Raises Skip."""
    fn = APPLIERS.get(kind)
    if fn is None:
        raise Skip("not an Auto mass rule")
    ch = clean_changes(changes)
    out = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    diffs = fn(out, ch)
    every = every_seconds
    if "every_seconds" in ch:
        if every_seconds is None:
            raise Skip("runs at set times — change its schedule in the form")
        if ch["every_seconds"] != every_seconds:
            diffs.append(("every_seconds", [(every_seconds, 1)], ch["every_seconds"]))
            every = ch["every_seconds"]
    enabled = bool(is_enabled)
    if ch.get("disable_rule") and enabled:
        diffs.append(("is_enabled", [(True, 1)], False))
        enabled = False
    return out, every, enabled, [_diff(k, b, a, enabled) for k, b, a in diffs]


def _sends_more(key: str, befores: Befores, after: Any) -> bool:
    """The change makes SOME message send more (or charge differently) right away — every prior value read, not
    only the first message's: a shorter interval, fewer skip-recent hours, online-only off, a price change, more
    media."""
    a, priors = _num(after), [_num(v) if key != "online_only" else v for v, _ in befores]
    if key == "every_seconds":
        return a is not None and any(b is not None and a < b for b in priors)
    if key == "exclude_last_chat_hours":
        return any((b or 0) > (a or 0) for b in priors)
    if key == "online_only":
        return not after and any(bool(b) for b in priors)
    if key == "price":
        return True
    if key == "media_count":
        return a is not None and any((b or 0) < a for b in priors)
    return False


def _diff(key: str, befores: Befores, after: Any, enabled: bool) -> dict[str, Any]:
    """`live` (rwl W30 S1): decided here, over every prior value, for a rule that stays on — the card only shows it."""
    d = {"field": key, "label": LABELS[key], "before": befores[0][0], "after": after,
         "text": diff_text(key, befores, after), "live": bool(enabled) and _sends_more(key, befores, after)}
    if len(befores) > 1:
        d["befores"] = [{"value": v, "count": c} for v, c in befores]
    return d


# ── Wording (pure): the ONE formatter the plan card and the summary read (rwl W30 F12) ──

def _fmt_num(x: float) -> str:
    x = round(float(x), 2)
    return str(int(x)) if x.is_integer() else f"{x:g}"


def _hours_text(h: float) -> str:
    return f"{_fmt_num(round(h * 60))} min" if h < 1 else f"{_fmt_num(h)}h"


def value_text(key: str, v: Any) -> str:
    """A value in plain words: "8h", "never", "every 90s", "$15", "on"."""
    n = _num(v)
    if key == "unsend_after_hours":
        return _hours_text(n) if n and n > 0 else "never"
    if key == "exclude_last_chat_hours":
        return _hours_text(n) if n and n > 0 else "off"
    if key == "every_seconds":
        if not n or n <= 0:
            return "—"
        sec = int(n)
        return _hours_text(sec / 3600) if sec % 60 == 0 else f"{sec}s"
    if key == "price":
        return f"${_fmt_num(n)}" if n and n > 0 else "free"
    if key == "media_count":
        return str(int(n)) if n and n > 0 else "1"
    return "on" if v else "off"


def diff_text(key: str, befores: Befores, after: Any) -> str:
    """"Unsend after 8h → never"; several prior values: "Price $5 (1 message), $50 (2 messages) → $10"."""
    if len(befores) > 1:
        before = ", ".join(f"{value_text(key, v)} ({c} message{'s' if c != 1 else ''})" for v, c in befores)
    else:
        before = value_text(key, befores[0][0])
    return f"{LABELS[key]} {before} → {value_text(key, after)}"


_CHANGE_ORDER = ("unsend_after_hours", "every_seconds", "online_only", "exclude_last_chat_hours", "price",
                 "media_count")


def change_lines(changes: dict[str, Any]) -> list[str]:
    """The change spec's lines: "Unsend after → never", …, "Switch off" last."""
    out = [f"{LABELS[k]} → {value_text(k, changes[k])}" for k in _CHANGE_ORDER if k in changes]
    if changes.get("disable_rule"):
        out.append("Switch off")
    return out


def rule_version(account_id: str, steps_json: str | None, trigger_json: str | None, is_enabled: Any) -> str:
    """What the plan card saw: a changed payload, schedule or switch since → a skip. The model is in it
    (rwl W30 C1): a deleted rule's reused id on another model never passes as the planned rule."""
    raw = f"{account_id}|{steps_json or ''}|{trigger_json or ''}|{int(bool(is_enabled))}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def every_of(trigger_json: str | None) -> tuple[dict, int | None]:
    """(trigger dict, its every_seconds or None for a clock / missing trigger)."""
    try:
        t = json.loads(trigger_json or "{}")
    except (TypeError, ValueError):
        t = {}
    t = t if isinstance(t, dict) else {}
    e = t.get("every_seconds")
    ok = isinstance(e, (int, float)) and not isinstance(e, bool) and not t.get("daily_at")
    return t, (int(e) if ok else None)


def payload_of(steps_json: str | None) -> dict:
    try:
        p = json.loads(steps_json or "{}")
    except (TypeError, ValueError):
        return {}
    return p if isinstance(p, dict) else {}


# ── Matching + plan (pure) ────────────────────────────────────────────

def _norm(s: str | None) -> str:
    """Letters and digits in any script, casefolded (rwl W30 F6: "夜" stays "夜", never "")."""
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())


_GENERIC = {"automass", "automasses", "mass", "masses", "all", "allautomasses", "allmasses",
            "every", "everything", "my", "mine", "rule", "rules", "automassrule", "automassrules",
            "myautomass", "myautomasses", "allmyautomasses", "automasse", "massdm", "massdms"}


def name_matches(match: str | None, name: str | None) -> bool:
    """Case/space-insensitive contains; no match or a generic one ("auto masses")
    = every rule. A supplied name that normalises to nothing selects none."""
    if match is None:
        return True
    m, n = _norm(match), _norm(name)
    if not m:
        return False
    if m in _GENERIC:
        return True
    return bool(n) and (m in n or (len(n) >= 3 and n in m))


@dataclass
class RuleRow:
    id: int
    account_id: str
    name: str
    kind: str
    steps_json: str | None
    trigger_json: str | None
    is_enabled: bool


@dataclass
class EditPlan:
    rules: list[dict] = field(default_factory=list)
    already: int = 0
    skipped: list[dict] = field(default_factory=list)
    matched: int = 0
    overflow: int = 0          # rules that would change but are past MAX_RULES: not on the card (said)
    left_out: int = 0          # "all": managed models the opt-in gate dropped (said, rule names never read)


def plan_rules(rows: Iterable[RuleRow], changes: dict[str, Any], match: str | None,
               names: dict[str, str]) -> EditPlan:
    """Which rules change and how. `rows`: the Auto mass rules in scope;
    `names`: account id → display name."""
    plan = EditPlan()
    for r in sorted(rows, key=lambda r: ((names.get(r.account_id) or r.account_id).lower(),
                                         (r.name or "").lower(), r.id)):
        if r.kind != KIND or not name_matches(match, r.name):
            continue
        plan.matched += 1
        _, every = every_of(r.trigger_json)
        try:
            _, _, _, diffs = apply_changes(KIND, payload_of(r.steps_json), every, r.is_enabled, changes)
        except Skip as e:
            plan.skipped.append({"id": r.id, "name": r.name, "account_id": r.account_id,
                                 "account_name": names.get(r.account_id) or r.account_id,
                                 "reason": str(e)})
            continue
        if not diffs:
            plan.already += 1
            continue
        plan.rules.append({
            "id": r.id, "account_id": r.account_id,
            "account_name": names.get(r.account_id) or r.account_id,
            "name": r.name, "is_enabled": bool(r.is_enabled),
            "version": rule_version(r.account_id, r.steps_json, r.trigger_json, r.is_enabled),
            "diffs": diffs})
    return plan


# ── DB: the rules in scope, and the per-rule write ────────────────────

Allowed = Callable[[str], Awaitable[bool]]


async def scope_accounts(scope: str, account_id: str, allowed: Allowed) -> tuple[list[str], int]:
    """(accounts, left out). "this" = the focused account; "all" = every account
    the session owns (`clamp_account_filter`) that passes `allowed` (the opt-in
    gate), and how many it dropped (rwl W30 C2: said, never silent). No clamp
    (unauthed dev hatch) never widens to every account in the DB (rwl W30 M14):
    "all" reads as the focused account only."""
    if scope != "all":
        return [account_id], 0
    ids = clamp_account_filter(None)
    if ids is None:
        ids = [account_id]
    owned = list(dict.fromkeys(ids))
    ok = [a for a in owned if await allowed(a)]
    return ok, len(owned) - len(ok)


async def resolve_rules(scope: str, account_id: str, changes: dict[str, Any], match: str | None,
                        allowed: Allowed) -> EditPlan:
    accounts, left_out = await scope_accounts(scope, account_id, allowed)
    if not accounts:
        return EditPlan(left_out=left_out)
    async with get_session() as s:
        rules = (await s.execute(select(AutomationRule).where(
            AutomationRule.kind == KIND, AutomationRule.account_id.in_(accounts)))).scalars().all()
        rows = [RuleRow(r.id, r.account_id, r.name or "", r.kind, r.steps_json, r.trigger_json,
                        bool(r.is_enabled)) for r in rules]
        accts = (await s.execute(select(Account.id, Account.nickname).where(
            Account.id.in_(accounts)))).all()
    names = {a: (nick or a) for a, nick in accts}
    # Match over every rule, THEN cap the card (rwl W30 F3): the cut is counted, never silent.
    plan = plan_rules(rows, changes, match, names)
    plan.left_out = left_out
    if len(plan.rules) > MAX_RULES:
        plan.overflow = len(plan.rules) - MAX_RULES
        plan.rules = plan.rules[:MAX_RULES]
    return plan


def left_out_note(n: int) -> str:
    """Models the opt-in gate dropped from "every model" (rwl W30 C2); no rule names."""
    return (f"{n} model{'s' if n != 1 else ''} left out — your role can't edit "
            f"{'their' if n != 1 else 'its'} Auto mass.")


def overflow_note(n: int) -> str:
    return (f"{n} more rule{'s' if n != 1 else ''} not shown and not changed — "
            "narrow the request (a rule name or one model).")


async def apply_one(rule_id: int, version: str, changes: dict[str, Any], *, home: str,
                    allowed: Allowed) -> dict[str, Any]:
    """One rule of an approved plan → {id, ok, reason?, diffs?}. A 401 is
    re-raised (session gone); any other refusal or failure is this rule's skip
    (rwl W30 F4: the response always lists every rule, never an error after
    earlier rules committed). The write is conditional on the row still being
    the one this call read (F5): a concurrent edit in between → CHANGED_SINCE."""
    from automation_registry import canonical_kind
    from automation_rules_api import _cancel_queued, _load_owned, _validate_payload_for_kind

    def skip(reason: str) -> dict[str, Any]:
        return {"id": rule_id, "ok": False, "reason": reason}

    ch = clean_changes(changes)
    try:
        async with get_session() as s:
            try:
                rule = await _load_owned(s, rule_id)
            except HTTPException as e:
                if e.status_code == 401:
                    raise
                return skip("not found" if e.status_code == 404 else "not allowed")
            if canonical_kind(rule.kind) != KIND:
                return skip("not an Auto mass rule")
            if not await allowed(rule.account_id):
                return skip("not allowed")
            if rule_version(rule.account_id, rule.steps_json, rule.trigger_json, rule.is_enabled) != version:
                return skip(CHANGED_SINCE)
            if rule.account_id != home and any(k in ch for k in ONE_MODEL_ONLY):
                return skip(ONE_MODEL_NOTE)
            seen = (rule.steps_json, rule.trigger_json, bool(rule.is_enabled))
            trig, every = every_of(rule.trigger_json)
            was_enabled = seen[2]
            old_hash = hashlib.sha1((rule.steps_json or "").encode()).hexdigest()[:12]
            payload, every2, enabled, diffs = apply_changes(
                KIND, payload_of(rule.steps_json), every, was_enabled, ch)
            if not diffs:
                return {"id": rule_id, "ok": True, "reason": "already set", "diffs": []}
            try:
                values: dict[str, Any] = {"steps_json": json.dumps(_validate_payload_for_kind(KIND, payload))}
            except HTTPException as e:
                return skip(f"the change isn't valid on this rule ({e.detail})")
            if every2 != every:
                trig["every_seconds"] = every2
                values["trigger_json"] = json.dumps(trig)
            if was_enabled and not enabled:
                values["is_enabled"] = False
            res = await s.execute(
                update(AutomationRule)
                .where(AutomationRule.id == rule.id, AutomationRule.account_id == rule.account_id,
                       AutomationRule.steps_json == seen[0],
                       AutomationRule.trigger_json == seen[1], AutomationRule.is_enabled == seen[2])
                .values(**values).execution_options(synchronize_session=False))
            if res.rowcount != 1:
                return skip(CHANGED_SINCE)
            if values.get("is_enabled") is False:
                await _cancel_queued(s, [rule.id])
            account_id, name = rule.account_id, rule.name
    except Skip as e:
        return skip(str(e))
    except HTTPException as e:
        if e.status_code == 401:
            raise
        log.warning("assistant_edit_apply_refused rule=%s status=%s detail=%r", rule_id, e.status_code, e.detail)
        return skip("not allowed" if e.status_code == 403 else "couldn't be changed")
    except Exception:
        log.exception("assistant_edit_apply_failed rule=%s", rule_id)
        return skip("couldn't be saved — try again")
    log.info("assistant_edit_applied rule=%s account=%s name=%r old_steps=%s fields=%s enabled=%s",
             rule_id, account_id, name, old_hash, ",".join(d["field"] for d in diffs), enabled)
    return {"id": rule_id, "ok": True, "diffs": diffs}
