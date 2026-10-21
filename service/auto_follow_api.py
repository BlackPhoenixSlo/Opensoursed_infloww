"""service/auto_follow_api.py — the Auto-follow list's numbers (Infloww parity).

Infloww's Growth → Auto-follow is one row per creator: a switch, follow counts
and a details view of the fans followed. The switch is the account's
`auto_follow` rule, flipped through `/admin/automation-rules/switch` (a rule
created there follows OF's recently-expired list, money gate on — see
`automation_rules_api._CREATE_PAYLOAD`). This module only READS.

  GET /admin/auto-follow/stats?account_id=&tz=
      → {rows: [{account_id, on, total, today, yesterday, d7, d30, last_followed_at}]}
  GET /admin/auto-follow/records?account_id=&sort=&order=&start=&end=&limit=&offset=
      → {total, rows: [{fan_id, name, username, avatar_url, total_spend_cents,
                        expires_at, followed_at, follow_count}]}

Counts: `total` and `last_followed_at` come from `follow_ping_state` (lifetime:
sum of ping_count, latest last_pinged_at); the day windows from `follow_log`,
which starts when it shipped, so a window reads 0 for follows older than that.
Days are cut at midnight in `tz` (the browser's zone; UTC when absent/invalid);
Today is today so far, 7/30 days are the last 7/30 days including today.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, select

from auth import assert_account_owned, clamp_account_filter
from automation_registry import kind_family
from db.engine import get_session
from db.models import AutomationRule, Fan, FollowLog, FollowPingState

log = logging.getLogger("of-relay.auto_follow_api")

router = APIRouter()

_KIND = "auto_follow"
_SORTS = {"followed_at", "spend", "expiry"}


def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz) if tz else ZoneInfo("UTC")
    except Exception:
        return ZoneInfo("UTC")


def _day_starts_utc(zone: ZoneInfo, now_utc: datetime) -> dict[str, datetime]:
    """Naive-UTC instants of local midnight: today, yesterday, 6 and 29 days ago."""
    local_today = now_utc.replace(tzinfo=timezone.utc).astimezone(zone).date()

    def start(days_back: int) -> datetime:
        d = local_today - timedelta(days=days_back)
        local = datetime(d.year, d.month, d.day, tzinfo=zone)
        return local.astimezone(timezone.utc).replace(tzinfo=None)

    return {"today": start(0), "yesterday": start(1), "d7": start(6), "d30": start(29)}


@router.get("/admin/auto-follow/stats")
async def auto_follow_stats(
    account_id: str | None = Query(None),
    tz: str | None = Query(None),
) -> dict[str, Any]:
    ids = clamp_account_filter(account_id)
    starts = _day_starts_utc(_zone(tz), datetime.utcnow())
    async with get_session() as s:
        def _scope(q, col):
            return q.where(col.in_(ids)) if ids is not None else q

        on_rows = (await s.execute(_scope(
            select(AutomationRule.account_id,
                   func.max(case((AutomationRule.is_enabled, 1), else_=0)))
            .where(AutomationRule.kind.in_(kind_family(_KIND))), AutomationRule.account_id)
            .group_by(AutomationRule.account_id))).all()
        life = (await s.execute(_scope(
            select(FollowPingState.account_id, func.sum(FollowPingState.ping_count),
                   func.max(FollowPingState.last_pinged_at)),
            FollowPingState.account_id).group_by(FollowPingState.account_id))).all()
        def _count(cond):
            return func.sum(case((cond, 1), else_=0))

        at = FollowLog.followed_at
        win = (await s.execute(_scope(
            select(FollowLog.account_id,
                   _count((at >= starts["yesterday"]) & (at < starts["today"])),
                   _count(at >= starts["today"]), _count(at >= starts["d7"]),
                   _count(at >= starts["d30"]))
            .where(at >= starts["d30"]),
            FollowLog.account_id).group_by(FollowLog.account_id))).all()

    rows: dict[str, dict[str, Any]] = {}

    def row(aid: str) -> dict[str, Any]:
        return rows.setdefault(aid, {
            "account_id": aid, "on": False, "total": 0, "today": 0,
            "yesterday": 0, "d7": 0, "d30": 0, "last_followed_at": None})

    for aid, on in on_rows:
        row(aid)["on"] = bool(on)
    for aid, total, last in life:
        r = row(aid)
        r["total"] = int(total or 0)
        r["last_followed_at"] = last.isoformat() if last else None
    for aid, yday, today, d7, d30 in win:
        r = row(aid)
        r.update(today=int(today or 0), yesterday=int(yday or 0),
                 d7=int(d7 or 0), d30=int(d30 or 0))
    if ids is not None:
        for aid in ids:
            row(aid)
    return {"rows": sorted(rows.values(), key=lambda r: r["account_id"])}


def _parse_dt(v: str | None, name: str) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"{name} must be an ISO date-time")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.get("/admin/auto-follow/records")
async def auto_follow_records(
    account_id: str = Query(...),
    sort: str = Query("followed_at"),
    order: str = Query("desc"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The fans one creator followed: one row per fan, at his latest follow
    (`follow_ping_state`), filtered to a follow-date range."""
    assert_account_owned(account_id)
    if sort not in _SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(_SORTS)}")
    if order not in ("asc", "desc"):
        raise HTTPException(422, "order must be asc or desc")
    lo, hi = _parse_dt(start, "start"), _parse_dt(end, "end")

    col = {"followed_at": FollowPingState.last_pinged_at,
           "spend": func.coalesce(Fan.lifetime_spend_cents, 0),
           "expiry": Fan.subscription_expires_at}[sort]
    key = col.desc() if order == "desc" else col.asc()

    base = (select(FollowPingState, Fan)
            .outerjoin(Fan, (Fan.account_id == FollowPingState.account_id)
                       & (Fan.fan_id == FollowPingState.fan_id))
            .where(FollowPingState.account_id == account_id))
    if lo is not None:
        base = base.where(FollowPingState.last_pinged_at >= lo)
    if hi is not None:
        base = base.where(FollowPingState.last_pinged_at < hi)

    async with get_session() as s:
        total = (await s.execute(
            select(func.count()).select_from(base.subquery()))).scalar() or 0
        res = (await s.execute(
            base.order_by(key, FollowPingState.fan_id.desc())
            .limit(limit).offset(offset))).all()

    out = []
    for st, fan in res:
        name = None
        if fan is not None:
            name = (fan.custom_nickname or fan.of_display_name or fan.of_username)
        out.append({
            "fan_id": int(st.fan_id),
            "name": name,
            "username": fan.of_username if fan is not None else None,
            "avatar_url": fan.avatar_url if fan is not None else None,
            "total_spend_cents": int(fan.lifetime_spend_cents or 0) if fan is not None else 0,
            "expires_at": (fan.subscription_expires_at.isoformat()
                           if fan is not None and fan.subscription_expires_at else None),
            "followed_at": st.last_pinged_at.isoformat(),
            "follow_count": int(st.ping_count or 0),
        })
    return {"account_id": account_id, "total": int(total), "rows": out}
