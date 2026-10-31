"""service/smart_list_rules.py — the Smart Lists rule engine, pure.

The DSL (`rules_json`) is documented in smart_lists_api's module docstring.
Here: the field / operator sets, `resolve(rules, fans)` over already-normalised
fan dicts (smart_lists_api `_normalise_fan`), `_validate_rules` for storage and
the rule readers (`_windows_in_rules`, `uses_subscription_facts`). No I/O, no DB.
smart_lists_api re-exports the names its importers use.
A bad rule raises fastapi's HTTPException(422) here on purpose: the routes answer
its exact text/status as-is (kept, not mapped, by design).
"""
from __future__ import annotations

from typing import Any, Iterable

from fastapi import HTTPException

from attribution_backfill import PPV_KINDS, TIP_KINDS

# ── DSL definition ────────────────────────────────────────────────────

SUB_KINDS = ("subscription", "rebill")
# money field -> transaction kinds summed (None = every kind)
_SUM_FIELDS = {
    "total_spend": None,
    "ppv_spend": PPV_KINDS,
    "tips_spend": TIP_KINDS,
    "subscription_spend": SUB_KINDS,
}
_LEDGER_MONEY = set(_SUM_FIELDS) | {"highest_spend", "last_spend_amount"}
_DATE_FIELDS = {"last_purchase_at", "last_message_sent_at", "sub_start",
                "expires_at", "resubscribed_at", "idle_days"}
_SCOPED = _LEDGER_MONEY | {"last_purchase_at"}
_ENUMS = {"status": ("active", "expired"), "renew": ("on", "off")}

# v1 fields (kept verbatim: saved lists and auto_follow targets use them)
_NUMERIC_FIELDS = {"lifetime_spend", "recent_spend", "last_active_days"} | _LEDGER_MONEY
_TAG_FIELDS = {"tag"}
_FIELDS = _NUMERIC_FIELDS | _DATE_FIELDS | set(_ENUMS) | _TAG_FIELDS

_NUMERIC_OPS = {">", ">=", "<", "<=", "==", "!=", "between"}
_DATE_OPS = {"within_last", "more_than", "between"}
_ENUM_OPS = {"==", "!="}
_TAG_OPS = {"has", "not_has"}

SCOPES = ("creator", "org")
TIMEFRAMES = ("all", "today", "yesterday", "this_week", "7d", "30d", "90d")

_MAX_RULES = 20


def _window_days(days: Any) -> int:
    """A recent_spend window in days, clamped to 1..3650. Raises TypeError /
    ValueError when `days` is not an integer."""
    return max(1, min(int(days), 3650))


def _num_cmp(a: float, op: str, b: Any) -> bool:
    if op == "between":
        lo, hi = b
        return float(lo) <= a <= float(hi)
    b = float(b)
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    return False


def fact_key(rule: dict) -> str:
    """Where a v2 rule's value lives in the normalised fan's `facts` dict."""
    field = rule.get("field")
    if field in _LEDGER_MONEY or field == "last_purchase_at":
        scope = rule.get("scope") or "creator"
        if field in ("last_spend_amount", "last_purchase_at"):
            return f"{field}:{scope}"
        return f"{field}:{scope}:{rule.get('timeframe') or 'all'}"
    return str(field)


def _eval_rule(rule: dict, fan: dict) -> bool:
    """Evaluate ONE rule against a normalised fan dict. Unknown field / bad
    shape → False (never matches), so a malformed rule can only ever SHRINK a
    segment, never leak fans into it."""
    field = rule.get("field")
    op = rule.get("op")
    value = rule.get("value")

    if field in _LEDGER_MONEY:
        cents = (fan.get("facts") or {}).get(fact_key(rule)) or 0
        return _num_cmp(float(cents), op, value)

    if field in _DATE_FIELDS:
        ago = (fan.get("facts") or {}).get(fact_key(rule))
        if ago is None:
            return False  # no date → never matches a date rule
        if op == "within_last":
            return 0 <= ago <= float(value)
        if op == "more_than":
            return ago > float(value)
        if op == "within_next":
            return -float(value) <= ago < 0
        if op == "between":
            lo, hi = value
            return float(lo) <= ago <= float(hi)
        return False

    if field in _ENUMS:
        cur = (fan.get("status") if field == "status" else fan.get("renew")) or ""
        cur, want = str(cur).lower(), str(value or "").lower()
        return cur == want if op == "==" else (cur != want if op == "!=" else False)

    if field == "lifetime_spend":
        return _num_cmp(float(fan.get("lifetime_spend") or 0), op, value)

    if field == "recent_spend":
        days = int(rule.get("days") or 30)
        rs = fan.get("recent_spend") or {}
        # keys may be int (from the resolver) or str (from JSON round-trips)
        cents = rs.get(days, rs.get(str(days), 0))
        return _num_cmp(float(cents or 0), op, value)

    if field == "last_active_days":
        la = fan.get("last_active_days")
        if la is None:
            return False  # never active → fails any recency threshold
        return _num_cmp(float(la), op, value)

    if field == "tag":
        tags = {str(t).lower() for t in (fan.get("tags") or [])}
        present = str(value or "").lower() in tags
        if op == "has":
            return present
        if op == "not_has":
            return not present
        return False

    return False


def resolve(rules_obj: dict | None, fans: Iterable[dict]) -> list[int]:
    """PURE. Return the sorted fan_id list matching `rules_obj` over `fans`.

    `rules_obj` = {"match": "all"|"any", "rules": [...]}. Empty/absent rules →
    EVERY fan matches (a blank segment is "everyone", not "no one"). `fans` is
    an iterable of dicts shaped by `_normalise_fan`.
    """
    rules_obj = rules_obj or {}
    rules = rules_obj.get("rules") or []
    match = str(rules_obj.get("match") or "all").lower()
    out: list[int] = []
    for fan in fans:
        fid = fan.get("fan_id")
        if fid is None:
            continue
        if not rules:
            out.append(int(fid))
            continue
        results = [_eval_rule(r, fan) for r in rules]
        ok = all(results) if match != "any" else any(results)
        if ok:
            out.append(int(fid))
    return sorted(out)


# ── Validation (persisted rules) ──────────────────────────────────────

def _number(field: str, v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{field} value must be a number")


def _value_for(field: str, op: str, raw: Any) -> Any:
    """A numeric value, or [lo, hi] for `between`."""
    if op != "between":
        return _number(field, raw)
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise HTTPException(422, f"{field} between needs [low, high]")
    lo, hi = _number(field, raw[0]), _number(field, raw[1])
    if lo > hi:
        raise HTTPException(422, f"{field} between needs low <= high")
    return [lo, hi]


def _validate_rules(rules_obj: Any) -> dict:
    """Coerce + bound-check a rules object for storage. Raises 422 on anything
    the resolver couldn't act on (so a bad rule is rejected at write time, not
    silently dropped at read)."""
    if rules_obj is None:
        return {"match": "all", "rules": []}
    if not isinstance(rules_obj, dict):
        raise HTTPException(422, "rules must be an object")
    match = str(rules_obj.get("match") or "all").lower()
    if match not in ("all", "any"):
        raise HTTPException(422, "match must be 'all' or 'any'")
    raw = rules_obj.get("rules") or []
    if not isinstance(raw, list):
        raise HTTPException(422, "rules.rules must be a list")
    if len(raw) > _MAX_RULES:
        raise HTTPException(422, f"at most {_MAX_RULES} rules")
    clean: list[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            raise HTTPException(422, "each rule must be an object")
        field = r.get("field")
        op = r.get("op")
        if field not in _FIELDS:
            raise HTTPException(422, f"unknown field {field!r}")
        entry: dict[str, Any] = {"field": field, "op": op}
        if field in _NUMERIC_FIELDS:
            if op not in _NUMERIC_OPS:
                raise HTTPException(422, f"{field} needs a numeric operator ({', '.join(sorted(_NUMERIC_OPS))})")
            entry["value"] = _value_for(field, op, r.get("value"))
            if field == "recent_spend":
                days = r.get("days", 30)
                try:
                    entry["days"] = _window_days(days)
                except (TypeError, ValueError):
                    raise HTTPException(422, "recent_spend days must be an integer")
        elif field in _DATE_FIELDS:
            ops = _DATE_OPS | ({"within_next"} if field == "expires_at" else set())
            if op not in ops:
                raise HTTPException(422, f"{field} needs one of {', '.join(sorted(ops))}")
            entry["value"] = _value_for(field, op, r.get("value"))
            if min(entry["value"] if op == "between" else [entry["value"]]) < 0:
                raise HTTPException(422, f"{field} days cannot be negative")
        elif field in _ENUMS:
            if op not in _ENUM_OPS:
                raise HTTPException(422, f"{field} needs == or !=")
            val = str(r.get("value") or "").lower()
            if val not in _ENUMS[field]:
                raise HTTPException(422, f"{field} must be one of {', '.join(_ENUMS[field])}")
            entry["value"] = val
        else:  # tag
            if op not in _TAG_OPS:
                raise HTTPException(422, "tag needs 'has' or 'not_has'")
            entry["value"] = str(r.get("value") or "")
            if not entry["value"]:
                raise HTTPException(422, "tag value cannot be blank")
        if field in _SCOPED:
            scope = r.get("scope") or "creator"
            if scope not in SCOPES:
                raise HTTPException(422, f"scope must be one of {', '.join(SCOPES)}")
            entry["scope"] = scope
        if field in _LEDGER_MONEY and field != "last_spend_amount":
            tf = r.get("timeframe") or "all"
            if tf not in TIMEFRAMES:
                raise HTTPException(422, f"timeframe must be one of {', '.join(TIMEFRAMES)}")
            entry["timeframe"] = tf
        clean.append(entry)
    return {"match": match, "rules": clean}


# ── Rule readers ──────────────────────────────────────────────────────

def _windows_in_rules(rules_obj: dict) -> set[int]:
    """The distinct v1 recent_spend windows (days) a rules object references."""
    out: set[int] = set()
    for r in (rules_obj.get("rules") or []):
        if r.get("field") == "recent_spend":
            try:
                out.add(_window_days(r.get("days") or 30))
            except (TypeError, ValueError):
                continue
    return out


def uses_subscription_facts(rules_obj: dict) -> bool:
    """Does this rules object read the roster snapshot? (The sync worker
    refreshes the roster first, and syncs nothing off a stale one.)"""
    return any(r.get("field") in ("status", "renew", "sub_start", "expires_at", "resubscribed_at",
                                  "idle_days")
               for r in (rules_obj.get("rules") or []))
