"""service/smart_lists_api.py — Smart Lists: saved dynamic fan segments.

A Smart List is a named query over per-fan facts, saved once and reused as a
mass-message audience (include/exclude). An ACTIVE list is also mirrored into
a real OnlyFans user list by the `smart_list_sync` automation (bulk lane,
automations/smart_list_sync.py); this module only flips the flags and queues
that work — a route never calls OnlyFans inline.

The DSL (`rules_json`):

    {
      "match": "all" | "any",          # AND vs OR across the rules (default all)
      "rules": [
        # spend, cents. scope creator|org (org = the same fan summed across the
        # agency's creators); timeframe all|today|yesterday|this_week|7d|30d|90d
        {"field": "total_spend", "op": ">=", "value": 10000, "scope": "org", "timeframe": "30d"},
        {"field": "tips_spend",  "op": "between", "value": [1000, 5000]},
        # dates, as days ago: within_last N | more_than N | between [a, b]
        # (expires_at also within_next N — the date is still ahead)
        {"field": "expires_at", "op": "within_next", "value": 3},
        {"field": "status", "op": "==", "value": "active"},   # active | expired
        {"field": "renew",  "op": "==", "value": "off"},      # on | off
        # ghost audience: newest of last purchase (no rebill), last inbound
        # message and subscription start, as days ago
        {"field": "idle_days", "op": "more_than", "value": 30},
        # v1 fields, unchanged
        {"field": "lifetime_spend",  "op": ">=", "value": 10000},   # OF's lifetime total, cents
        {"field": "recent_spend",    "op": ">=", "value": 5000, "days": 30},
        {"field": "last_active_days","op": "<=", "value": 7},       # days since last inbound
        {"field": "tag",             "op": "has","value": "whale"}  # fans.tags contains
      ]
    }

Sources: spend fields read the `transactions` ledger (cleared + pending, so a
chargeback or refund drops out); `lifetime_spend` is OF's own lifetime total on
the fan row. Subscription facts read `subscriber_snapshot` (the lifecycle
roster crawl): `status` is active when the newest complete crawl listed him and
expired when an older one did; `sub_start` is the start OF reports for the
current subscription; `resubscribed_at` is only set for returns the crawl saw.
A fan the snapshot never saw falls back to the fan row.

`resolve(rules, fans)` is a PURE function over already-normalised fan dicts
(see `_normalise_fan`) so it is trivially unit-testable without a DB.

Routes (owner-gated via `auth`, all under /admin/* so the existing relay
rewrite + share-token gate cover them):

  GET    /admin/smart-lists?account_id=            list saved segments (+ quota)
  POST   /admin/smart-lists                        create
  PATCH  /admin/smart-lists/{list_id}              update name/rules
  DELETE /admin/smart-lists/{list_id}?delete_of_list=  delete (optionally its OF list)
  POST   /admin/smart-lists/{list_id}/activate     start syncing to OnlyFans (quota)
  POST   /admin/smart-lists/{list_id}/deactivate   stop syncing (OF list kept)
  POST   /admin/smart-lists/preview                {account_id, rules} -> {count, sample}
  GET    /admin/smart-lists/{list_id}/resolve      -> {fan_ids, count} (composer expands to userIds)

PATCH, DELETE and deactivate answer 409 while the list is syncing — the lock is
a conditional UPDATE/DELETE, so it cannot interleave with the worker's claim.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Iterable

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, delete as sa_delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from attribution_backfill import PPV_KINDS, REVENUE_KINDS, TIP_KINDS, TRACKED_STATUSES
from auth import assert_account_owned
from db.engine import get_session
from db.models import (
    Fan, ScheduledJob, SmartList, SubscriberSnapshot, Transaction,
    User, UserAccount,
)

log = logging.getLogger("of-relay.smart_lists_api")

router = APIRouter()

SYNC_KIND = "smart_list_sync"
# Infloww: "A maximum of N smart lists can be active". Each active list costs
# OF writes on the account's shared pacing slot, so the cap is per creator.
# SMART_LIST_MAX_ACTIVE (default 10): Settings → System's override, else env; read at use.
def _max_active() -> int:
    import runtime_switches
    return int(runtime_switches.value("SMART_LIST_MAX_ACTIVE"))

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

_PREVIEW_SAMPLE = 25
_MAX_RULES = 20


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
                    entry["days"] = max(1, min(int(days), 3650))
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


# ── Fan loading (build normalised dicts from the DB) ──────────────────

def _days_ago(dt: datetime | None, now: datetime) -> float | None:
    return None if dt is None else (now - dt).total_seconds() / 86400.0


def _normalise_fan(row: Fan, now: datetime, recent_spend: dict[int, int],
                   facts: dict[str, Any] | None = None,
                   sub: tuple[str | None, str | None] = (None, None)) -> dict:
    """One DB Fan row -> the pure-resolver's fan dict. `recent_spend` maps each
    referenced v1 window (days) to that fan's spend in cents over the window;
    `facts` holds the v2 values keyed by `fact_key`; `sub` is the snapshot's
    (status, renew)."""
    try:
        tags = json.loads(row.tags) if row.tags else []
    except Exception:
        tags = []
    la: float | None = None
    if row.last_message_received_at is not None:
        la = max(0.0, (now - row.last_message_received_at).total_seconds() / 86400.0)
    status, renew = sub
    return {
        "fan_id": int(row.fan_id),
        "lifetime_spend": int(row.lifetime_spend_cents or 0),
        "last_active_days": la,
        "status": status or row.subscription_status,
        "renew": renew,
        "tags": tags if isinstance(tags, list) else [],
        "recent_spend": recent_spend,
        "facts": facts or {},
        # display bits for the preview sample (ignored by the resolver)
        "_name": row.custom_nickname or row.generated_nickname or row.of_display_name
                 or row.of_username or str(row.fan_id),
    }


def _windows_in_rules(rules_obj: dict) -> set[int]:
    """The distinct v1 recent_spend windows (days) a rules object references."""
    out: set[int] = set()
    for r in (rules_obj.get("rules") or []):
        if r.get("field") == "recent_spend":
            try:
                out.add(max(1, min(int(r.get("days") or 30), 3650)))
            except (TypeError, ValueError):
                continue
    return out


def _timeframe_start_end(tf: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    """[start, end) of a spend timeframe, UTC."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if tf == "today":
        return midnight, None
    if tf == "yesterday":
        return midnight - timedelta(days=1), midnight
    if tf == "this_week":
        return midnight - timedelta(days=midnight.weekday()), None
    if tf in ("7d", "30d", "90d"):
        return now - timedelta(days=int(tf[:-1])), None
    return None, None


async def org_account_ids(s, account_id: str) -> list[str]:
    """The creators a fan's Org-scope spend is summed over: every account of
    this account's agency. One owner = one agency; an account with none, or
    with several (a disputed link), counts as its own org — never a guess.
    A sibling counts only when ITS owner is exactly the same one owner, so a
    master's oversight links on other agencies' creators never join the org."""
    from tenant_keys import billable_owners, owners_of
    owners = await owners_of(account_id)
    if len(owners) != 1:
        return [str(account_id)]
    siblings = select(UserAccount.account_id).where(UserAccount.user_id == owners[0])
    links: dict[str, list[tuple[str, bool]]] = {}
    for aid, uid, is_admin in (await s.execute(
        select(UserAccount.account_id, UserAccount.user_id, User.is_admin)
        .join(User, User.id == UserAccount.user_id)
        .where(UserAccount.account_id.in_(siblings))
    )).all():
        links.setdefault(str(aid), []).append((uid, bool(is_admin)))
    ids = {aid for aid, ls in links.items() if billable_owners(ls) == owners}
    ids.add(str(account_id))
    return sorted(ids)


_LAST_REVENUE = "_last_revenue_at"  # raw datetime, folded into idle_days


async def _ledger_facts(s, account_id: str, rules: list[dict],
                        now: datetime) -> dict[int, dict[str, Any]]:
    """{fan_id: {fact_key: value}} for every ledger-backed v2 rule — one grouped
    query per distinct (scope, timeframe), one per scope for the last amount."""
    combos: set[tuple[str, str]] = set()
    last_scopes: set[str] = set()
    for r in rules:
        f = r.get("field")
        if f == "last_spend_amount":
            last_scopes.add(r.get("scope") or "creator")
        elif f == "last_purchase_at":
            combos.add((r.get("scope") or "creator", "all"))
        elif f == "idle_days":
            combos.add(("creator", "all"))
        elif f in _LEDGER_MONEY:
            combos.add((r.get("scope") or "creator", r.get("timeframe") or "all"))
    out: dict[int, dict[str, Any]] = {}
    if not combos and not last_scopes:
        return out
    T = Transaction
    org_ids = None
    if any(sc == "org" for sc, _ in combos) or "org" in last_scopes:
        org_ids = await org_account_ids(s, account_id)

    def _base(scope: str):
        ids = org_ids if scope == "org" else [str(account_id)]
        return (T.account_id.in_(ids), T.fan_id.isnot(None),
                T.status.in_(TRACKED_STATUSES))

    def _cat(kinds):
        amt = T.amount_cents if kinds is None else case((T.kind.in_(kinds), T.amount_cents), else_=0)
        return func.sum(amt)

    for scope, tf in sorted(combos):
        start, end = _timeframe_start_end(tf, now)
        q = select(T.fan_id, *(_cat(k) for k in _SUM_FIELDS.values()),
                   func.max(T.amount_cents), func.max(T.occurred_at),
                   # newest purchase, rebills excluded (idle_days)
                   func.max(case((T.kind.in_(REVENUE_KINDS), T.occurred_at)))
                   ).where(*_base(scope))
        if start is not None:
            q = q.where(T.occurred_at >= start)
        if end is not None:
            q = q.where(T.occurred_at < end)
        for fid, *vals in (await s.execute(q.group_by(T.fan_id))).all():
            facts = out.setdefault(int(fid), {})
            for field, v in zip(_SUM_FIELDS, vals[:4]):
                facts[f"{field}:{scope}:{tf}"] = int(v or 0)
            facts[f"highest_spend:{scope}:{tf}"] = int(vals[4] or 0)
            if tf == "all":
                facts[f"last_purchase_at:{scope}"] = _days_ago(vals[5], now)
                if scope == "creator":
                    facts[_LAST_REVENUE] = vals[6]

    for scope in sorted(last_scopes):
        rn = func.row_number().over(
            partition_by=T.fan_id, order_by=(T.occurred_at.desc(), T.id.desc())).label("rn")
        sub = select(T.fan_id, T.amount_cents, rn).where(*_base(scope)).subquery()
        rows = (await s.execute(select(sub.c.fan_id, sub.c.amount_cents).where(sub.c.rn == 1))).all()
        for fid, amt in rows:
            out.setdefault(int(fid), {})[f"last_spend_amount:{scope}"] = int(amt or 0)
    return out


# How old the newest roster crawl may be for a preview / resolve to trust it
# (the lifecycle sweeps re-crawl about every 25 min while they run).
_SNAPSHOT_MAX_AGE_S = 30 * 60


async def _snapshot(s, account_id: str, now: datetime, *,
                    roster_fresh: bool = False) -> dict[int, tuple]:
    """{fan_id: (status, renew, subscribe_at, expired_at, resubscribed_at)} off
    the lifecycle roster snapshot. Active = listed by the newest complete crawl.

    Only a FRESH snapshot speaks for status, renew and the current
    subscription's dates — `roster_fresh` (the caller just refreshed the
    roster, e.g. the sync worker) or a newest crawl under `_SNAPSHOT_MAX_AGE_S`.
    A stale one would call every fan who subscribed since "expired", so those
    fall back to the fan row. A recorded return (`resubscribed_at`) is history
    and stays usable either way."""
    S = SubscriberSnapshot
    rows = (await s.execute(
        select(S.fan_id, S.seen_at, S.renew_on, S.subscribe_at, S.expired_at,
               S.resubscribed_at).where(S.account_id == str(account_id))
    )).all()
    last = max((r.seen_at for r in rows), default=None)
    fresh = last is not None and (
        roster_fresh or (now - last).total_seconds() < _SNAPSHOT_MAX_AGE_S)
    out: dict[int, tuple] = {}
    for fid, seen, renew_on, sub_at, exp_at, back_at in rows:
        if not fresh:
            out[int(fid)] = (None, None, None, None, back_at)
            continue
        active = seen == last
        renew = None if not active or renew_on is None else ("on" if renew_on else "off")
        out[int(fid)] = ("active" if active else "expired", renew, sub_at, exp_at, back_at)
    return out


async def _load_normalised_fans(account_id: str, rules_obj: dict, *,
                                roster_fresh: bool = False) -> list[dict]:
    """Load every fan for the account as a normalised resolver dict, with each
    recent_spend window and every v2 fact pre-aggregated. Pure resolve() then
    filters these. `roster_fresh`: see `_snapshot`."""
    now = datetime.utcnow()
    rules = rules_obj.get("rules") or []
    windows = _windows_in_rules(rules_obj)
    async with get_session() as s:
        fan_rows = (await s.execute(
            select(Fan).where(Fan.account_id == str(account_id))
        )).scalars().all()

        spend_by_window: dict[int, dict[int, int]] = {}
        for days in windows:
            cutoff = now - timedelta(days=days)
            rows = (await s.execute(
                select(Transaction.fan_id, func.sum(Transaction.amount_cents))
                .where(Transaction.account_id == str(account_id),
                       Transaction.fan_id.isnot(None),
                       Transaction.occurred_at >= cutoff)
                .group_by(Transaction.fan_id)
            )).all()
            spend_by_window[days] = {int(fid): int(total or 0) for fid, total in rows}
        ledger = await _ledger_facts(s, account_id, rules, now)
        snap = await _snapshot(s, account_id, now, roster_fresh=roster_fresh)

    out: list[dict] = []
    for row in fan_rows:
        fid = int(row.fan_id)
        rs = {days: spend_by_window.get(days, {}).get(fid, 0) for days in windows}
        status, renew, sub_at, exp_at, back_at = snap.get(fid, (None, None, None, None, None))
        facts = dict(ledger.get(fid, {}))
        facts["last_message_sent_at"] = _days_ago(row.last_message_sent_at, now)
        facts["sub_start"] = _days_ago(sub_at or row.subscribed_at, now)
        facts["expires_at"] = _days_ago(exp_at or row.subscription_expires_at, now)
        facts["resubscribed_at"] = _days_ago(back_at, now)
        # ghost audience: days since the fan last bought (no rebill), wrote or
        # (re)subscribed — whichever is newest; no date at all = no match
        touched = [d for d in (facts.pop(_LAST_REVENUE, None), row.last_message_received_at,
                               sub_at or row.subscribed_at) if d is not None]
        facts["idle_days"] = _days_ago(max(touched), now) if touched else None
        out.append(_normalise_fan(row, now, rs, facts, (status, renew)))
    return out


def uses_subscription_facts(rules_obj: dict) -> bool:
    """Does this rules object read the roster snapshot? (The sync worker
    refreshes the roster first, and syncs nothing off a stale one.)"""
    return any(r.get("field") in ("status", "renew", "sub_start", "expires_at", "resubscribed_at",
                                  "idle_days")
               for r in (rules_obj.get("rules") or []))


# ── Serialisation ─────────────────────────────────────────────────────

def _rules_of(row: SmartList) -> dict:
    try:
        return json.loads(row.rules_json) if row.rules_json else {"match": "all", "rules": []}
    except Exception:
        return {"match": "all", "rules": []}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _serialize(row: SmartList) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "name": row.name,
        "rules": _rules_of(row),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "is_active": bool(row.is_active),
        "of_list_id": row.of_list_id,
        "sync_state": row.sync_state,
        "sync_error": row.sync_error,
        "synced_at": _iso(row.synced_at),
        "member_count": row.member_count,
    }


async def _assert_name_free(s, account_id: str, name: str, *, exclude_id: int | None = None) -> None:
    """409 if `name` is already taken on this account. UNIQUE(account_id, name)
    is the real guard; this checks first so the operator gets an accurate
    message instead of a raw IntegrityError (which a rename would otherwise
    surface as a 500)."""
    q = select(SmartList.id).where(SmartList.account_id == account_id, SmartList.name == name)
    if exclude_id is not None:
        q = q.where(SmartList.id != exclude_id)
    if (await s.execute(q)).first():
        raise HTTPException(409, f"a smart list named {name!r} already exists")


# A list deleted "with its OnlyFans list" stays as a tombstone row in this state
# until the worker has deleted that OF list — the worker only ever deletes the
# OF list a tombstone of the same account names, never an id from a payload.
DELETING = "deleting"
_LIVE = or_(SmartList.sync_state.is_(None), SmartList.sync_state != DELETING)
_NOT_SYNCING = or_(SmartList.sync_state.is_(None),
                   SmartList.sync_state.notin_(("syncing", DELETING)))
_LOCKED = "this smart list is syncing with OnlyFans — try again in a minute"


async def live_row(s, list_id: int) -> SmartList | None:
    """THE way to load one Smart List: a `deleting` tombstone reads as missing,
    so nothing (a route, auto_follow's targets) can keep acting on it."""
    row = await s.get(SmartList, int(list_id))
    return None if row is None or row.sync_state == DELETING else row


async def _owned_row(s, list_id: int) -> SmartList:
    row = await live_row(s, list_id)
    if row is None:
        raise HTTPException(404, "smart list not found")
    assert_account_owned(row.account_id)
    return row


# ── Sync plumbing (queue only — the worker does every OnlyFans write) ──

async def _queue_sync(s, account_id: str) -> None:
    """Queue a sync run in the caller's transaction, coalesced with one already
    pending — every run handles all of the account's lists and tombstones."""
    from automation_executor import enqueue_job
    pending = (await s.execute(
        select(ScheduledJob.id).where(
            ScheduledJob.account_id == str(account_id),
            ScheduledJob.kind == SYNC_KIND,
            ScheduledJob.status == "pending",
            ScheduledJob.run_at <= datetime.utcnow())
    )).first()
    if not pending:
        await enqueue_job(str(account_id), SYNC_KIND, payload={}, session=s)


def _wake() -> None:
    from automation_executor import wake_supervisor
    wake_supervisor()


# ── Routes ────────────────────────────────────────────────────────────

@router.get("/admin/smart-lists")
async def list_smart_lists(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        rows = (await s.execute(
            select(SmartList).where(SmartList.account_id == account_id, _LIVE)
            .order_by(SmartList.name)
        )).scalars().all()
    return {"lists": [_serialize(r) for r in rows], "max_active": _max_active()}


class _CreateBody(BaseModel):
    account_id: str
    name: str
    rules: dict | None = None


@router.post("/admin/smart-lists")
async def create_smart_list(body: _CreateBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    rules = _validate_rules(body.rules)
    now = datetime.utcnow()
    async with get_session() as s:
        await _assert_name_free(s, body.account_id, name)
        row = SmartList(account_id=body.account_id, name=name,
                        rules_json=json.dumps(rules), created_at=now, updated_at=now)
        s.add(row)
        try:
            await s.flush()
        except IntegrityError as e:
            # Lost a race on the name, or account_id has no accounts row. Report
            # the real reason — a blanket "already exists" here used to mask an
            # unknown-account FK failure.
            raise HTTPException(409, f"could not save smart list: {repr(e)[:160]}")
        out = _serialize(row)
    log.info("smart_list_created id=%s account=%s name=%s", out["id"], body.account_id, name)
    return out


class _UpdateBody(BaseModel):
    name: str | None = None
    rules: dict | None = None


@router.patch("/admin/smart-lists/{list_id}")
async def update_smart_list(list_id: int, body: _UpdateBody = Body(...)) -> dict[str, Any]:
    async with get_session() as s:
        row = await _owned_row(s, list_id)
        values: dict[str, Any] = {"updated_at": datetime.utcnow()}
        if body.name is not None:
            nm = body.name.strip()
            if not nm:
                raise HTTPException(422, "name cannot be blank")
            if nm != row.name:
                await _assert_name_free(s, row.account_id, nm, exclude_id=row.id)
            values["name"] = nm
        if body.rules is not None:
            values["rules_json"] = json.dumps(_validate_rules(body.rules))
        res = await s.execute(
            update(SmartList).where(SmartList.id == list_id, _NOT_SYNCING).values(**values))
        if res.rowcount != 1:
            raise HTTPException(409, _LOCKED)
        await s.refresh(row)
        if row.is_active:
            await _queue_sync(s, row.account_id)
        out = _serialize(row)
    if out["is_active"]:
        _wake()
    log.info("smart_list_updated id=%s", list_id)
    return out


@router.delete("/admin/smart-lists/{list_id}")
async def delete_smart_list(list_id: int, delete_of_list: bool = Query(False)) -> dict[str, Any]:
    """Delete the segment. `delete_of_list` also deletes the OnlyFans list it
    created: the row becomes a hidden tombstone (state `deleting`, renamed so
    its name is free again) that the worker removes once that OF list is gone."""
    async with get_session() as s:
        row = await _owned_row(s, list_id)
        account_id, of_list_id = row.account_id, row.of_list_id
        queued = bool(delete_of_list and of_list_id)
        if queued:
            stmt = (update(SmartList).where(SmartList.id == list_id, _NOT_SYNCING)
                    .values(sync_state=DELETING, is_active=False,
                            name=f"{row.name} (deleting #{list_id})"))
        else:
            stmt = sa_delete(SmartList).where(SmartList.id == list_id, _NOT_SYNCING)
        res = await s.execute(stmt)
        if res.rowcount != 1:
            raise HTTPException(409, _LOCKED)
        if queued:
            await _queue_sync(s, account_id)
    if queued:
        _wake()
    log.info("smart_list_deleted id=%s of_list=%s delete_of_list=%s",
             list_id, of_list_id, queued)
    return {"deleted": list_id, "of_list_delete_queued": queued}


@router.post("/admin/smart-lists/{list_id}/activate")
async def activate_smart_list(list_id: int) -> dict[str, Any]:
    from automation_rules_api import ensure_kind_rule
    async with get_session() as s:
        row = await _owned_row(s, list_id)
        if not row.is_active:
            # The quota is checked inside the UPDATE itself, so two activations
            # racing for the last slot cannot both win.
            cap = _max_active()
            active = (select(func.count()).select_from(SmartList)
                      .where(SmartList.account_id == row.account_id,
                             SmartList.is_active.is_(True))
                      .scalar_subquery())
            res = await s.execute(
                update(SmartList)
                .where(SmartList.id == list_id, _NOT_SYNCING, active < cap)
                .values(is_active=True, sync_error=None))
            if res.rowcount != 1:
                await s.refresh(row)
                if row.sync_state == "syncing":
                    raise HTTPException(409, _LOCKED)
                raise HTTPException(409, f"a maximum of {cap} smart lists can be active")
            await s.refresh(row)
        await ensure_kind_rule(s, row.account_id, SYNC_KIND, enable=True)
        await _queue_sync(s, row.account_id)
        await s.flush()
        out = _serialize(row)
    _wake()
    log.info("smart_list_activated id=%s", list_id)
    return out


@router.post("/admin/smart-lists/{list_id}/deactivate")
async def deactivate_smart_list(list_id: int) -> dict[str, Any]:
    """Stop syncing. The OnlyFans list stays as it is (delete removes it)."""
    async with get_session() as s:
        row = await _owned_row(s, list_id)
        res = await s.execute(
            update(SmartList).where(SmartList.id == list_id, _NOT_SYNCING)
            .values(is_active=False))
        if res.rowcount != 1:
            raise HTTPException(409, _LOCKED)
        await s.refresh(row)
        out = _serialize(row)
    log.info("smart_list_deactivated id=%s", list_id)
    return out


class _PreviewBody(BaseModel):
    account_id: str
    rules: dict | None = None


@router.post("/admin/smart-lists/preview")
async def preview_smart_list(body: _PreviewBody = Body(...)) -> dict[str, Any]:
    """Resolve a (possibly unsaved) rules object against the account's fans and
    return the match COUNT plus a small SAMPLE — the segment-builder's live
    counter."""
    assert_account_owned(body.account_id)
    rules = _validate_rules(body.rules)
    fans = await _load_normalised_fans(body.account_id, rules)
    matched_ids = set(resolve(rules, fans))
    sample = []
    for f in fans:
        if f["fan_id"] in matched_ids:
            sample.append({
                "fan_id": f["fan_id"],
                "name": f["_name"],
                "lifetime_spend_cents": f["lifetime_spend"],
                "last_active_days": None if f["last_active_days"] is None
                                    else round(f["last_active_days"], 1),
                "status": f["status"],
            })
            if len(sample) >= _PREVIEW_SAMPLE:
                break
    return {"count": len(matched_ids), "total_fans": len(fans), "sample": sample}


@router.get("/admin/smart-lists/{list_id}/resolve")
async def resolve_smart_list(list_id: int) -> dict[str, Any]:
    """Expand a saved list to the current matching fan-id set — the composer
    calls this to turn an include/exclude Smart-List chip into explicit
    userIds/excludedUsers on the send."""
    async with get_session() as s:
        row = await _owned_row(s, list_id)
        account_id = row.account_id
        rules = _rules_of(row)
    fans = await _load_normalised_fans(account_id, rules)
    fan_ids = resolve(rules, fans)
    return {"list_id": list_id, "account_id": account_id,
            "fan_ids": fan_ids, "count": len(fan_ids)}
