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
(see `_normalise_fan`) so it is trivially unit-testable without a DB; it and
the rest of the rule engine live in smart_list_rules.

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
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, delete as sa_delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from attribution_backfill import REVENUE_KINDS, TRACKED_STATUSES
from auth import assert_account_owned
from db.engine import get_session
from db.models import (
    Fan, ScheduledJob, SmartList, SubscriberSnapshot, Transaction,
    User, UserAccount,
)
# The rule engine (DSL sets, resolve, validation, rule readers) is pure, in
# smart_list_rules. Imported here: what this module uses, plus what importers
# take from smart_lists_api (resolve, _validate_rules, uses_subscription_facts).
from smart_list_rules import (  # noqa: F401
    _LEDGER_MONEY, _SUM_FIELDS, _validate_rules, _windows_in_rules, resolve,
    uses_subscription_facts,
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

_PREVIEW_SAMPLE = 25


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
