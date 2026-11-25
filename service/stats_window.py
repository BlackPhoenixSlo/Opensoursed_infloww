from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from auth import clamp_account_filter, split_account_ids

MAX_WINDOW_DAYS = 400
MAX_ACCOUNTS = 50


def _guard_day(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _too_big(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=413, detail={"code": code, "message": message, **extra})


def stats_guard(request: Request) -> None:
    q = request.query_params
    ids = split_account_ids(*q.getlist("account_id"))
    if len(ids) > MAX_ACCOUNTS:
        raise _too_big("stats_too_many_accounts",
                       f"Too many Creators selected ({len(ids)}). Pick {MAX_ACCOUNTS} or fewer, "
                       "or clear the selection to see all.",
                       max_accounts=MAX_ACCOUNTS, accounts=len(ids))
    start = _guard_day(q.get("from") or "")
    if start is None:
        return
    raw_to = q.get("to") or ""
    end = _guard_day(raw_to) if raw_to else datetime.now(timezone.utc).replace(tzinfo=None)
    if end is None:
        return
    if len(raw_to) == 10:
        end += timedelta(days=1)
    # Elapsed time rounded: a window cut at report-zone midnights spans one more UTC date, and a DST hour is no day.
    days = round((end - start) / timedelta(days=1))
    if days > MAX_WINDOW_DAYS:
        raise _too_big("stats_window_too_long",
                       f"Date range too long ({days} days). Pick {MAX_WINDOW_DAYS} days or fewer.",
                       max_days=MAX_WINDOW_DAYS, days=days)


def parse_bound(s: str | None, field: str, zone: ZoneInfo | None = None,
                offset_min: int | None = None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid {field}: {e}") from e

    bare = "T" not in s and " " not in s
    if bare and field == "to":
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999_999)
    if bare and zone is not None:
        dt = dt.replace(tzinfo=zone)

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    # Clamp to +-14h against malformed clients.
    if bare and offset_min is not None and -14 * 60 <= offset_min <= 14 * 60:
        dt = dt + timedelta(minutes=offset_min)

    return dt


def parse_date(
    s: str | None,
    *,
    field: str,
    request: Request | None = None,
    zone: ZoneInfo | None = None,
) -> datetime | None:
    offset_min = None
    if request is not None:
        # JS getTimezoneOffset returns minutes WEST of UTC (+480 for PST).
        raw = request.headers.get("x-timezone-offset-minutes")
        if raw is not None:
            try:
                offset_min = int(raw)
            except ValueError:
                pass
    return parse_bound(s, field, zone, offset_min)


# Clamp each id: the isolation middleware sees "a,b" as one non-account id and lets it through, so this is the only tenant check.
def scope_ids(account_id: str | None) -> tuple[list[str] | None, str | None]:
    ids = split_account_ids(account_id)
    if not ids:
        return clamp_account_filter(None), None
    return [a for one in ids for a in clamp_account_filter(one)], ids[0]


def bucket_allowed(bucket: str, days: int) -> bool:
    if bucket == "hour":
        return days <= 2
    if days < 14:
        return bucket == "day"
    if days <= 31:
        return bucket in ("day", "week")
    if days <= 62:
        return bucket == "week"
    if days <= 365:
        return bucket in ("week", "month")
    return bucket == "month"


def range_days(start: datetime, end: datetime) -> int:
    return round(((end - start).total_seconds() + 0.001) / 86400)


def bucket_edges(bucket: str, start: datetime, end: datetime, zone: ZoneInfo | None,
                 week_start: str = "monday") -> list[datetime]:
    tz = zone or timezone.utc

    def utc(local: datetime) -> datetime:
        return local.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    local = start.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)
    edges: list[datetime] = []
    if bucket == "hour":
        at = utc(local.replace(minute=0, second=0, microsecond=0))
        while at <= end:
            edges.append(at)
            at += timedelta(hours=1)
        return edges
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        day -= timedelta(days=(day.weekday() + (1 if week_start == "sunday" else 0)) % 7)
    elif bucket == "month":
        day = day.replace(day=1)
    while (at := utc(day)) <= end:
        edges.append(at)
        day = ((day.replace(day=28) + timedelta(days=4)).replace(day=1) if bucket == "month"
               else day + timedelta(days=7 if bucket == "week" else 1))
    return edges
