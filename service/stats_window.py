"""
stats_window.py — a report's window, scope and buckets, for the /admin/stats
routes (stats.py re-exports parse_date, bucket_allowed, range_days and
bucket_edges as `_parse_date`, `_bucket_allowed`, `_range_days`,
`_bucket_edges`; stats_guard and scope_ids under the same names).

  stats_guard    the 413 guard every /admin/stats route runs
  parse_bound    a `from`/`to` bound as naive UTC (pure); `parse_date` reads
                 the request's offset header for it
  scope_ids      `account_id` clamped to the caller's Creators
  bucket_*       a chart's granularity rules and its bucket edges
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from auth import clamp_account_filter, split_account_ids

# The guard (roadmap 2.15, 05 B8): like Infloww, a report over more than
# MAX_WINDOW_DAYS days or more than MAX_ACCOUNTS Creators is refused up front
# with a 413 and a hint, instead of running until it times out.
MAX_WINDOW_DAYS = 400
MAX_ACCOUNTS = 50


def _guard_day(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None  # the route's own parse answers 400
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _too_big(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=413, detail={"code": code, "message": message, **extra})


def stats_guard(request: Request) -> None:
    """Every /admin/stats route: an explicit `account_id` naming more than
    MAX_ACCOUNTS Creators (comma lists and repeats count together), or a
    `from`..`to` window longer than MAX_WINDOW_DAYS days, is a 413 whose detail carries `message`, the hint the
    UI shows (relay.ts reads `detail.message`). No filter at all (every
    Creator, the route's default window) is not refused."""
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
        end += timedelta(days=1)  # a bare `to` date counts its whole day
    # Elapsed time, not calendar dates: a window cut at the report zone's
    # midnights (the app's from/to) spans one more UTC date than it has days,
    # and rounded, so a DST change's extra hour doesn't count as a day.
    days = round((end - start) / timedelta(days=1))
    if days > MAX_WINDOW_DAYS:
        raise _too_big("stats_window_too_long",
                       f"Date range too long ({days} days). Pick {MAX_WINDOW_DAYS} days or fewer.",
                       max_days=MAX_WINDOW_DAYS, days=days)


def parse_bound(s: str | None, field: str, zone: ZoneInfo | None = None,
                offset_min: int | None = None) -> datetime | None:
    """Accept ISO-8601 ("2026-05-22" or "2026-05-22T12:00:00Z" or
    "2026-05-22T23:59:59.999-07:00"). Returns naive UTC datetime to match
    the column convention. 400 on garbage so the caller doesn't silently
    get an empty result.

    Tz handling (Work Unit X):
    - Full ISO with tzinfo (`...-07:00`, `...Z`) is converted to UTC, then
      the tzinfo is stripped — the DB stores naive UTC.
    - Bare-date inputs (YYYY-MM-DD, no time) are inclusive on the `to`
      side — the UI's <input type="date"> can only emit bare dates and
      a user picking "to=05/22" means "through end-of-day May 22", not
      "midnight May 22". `from` keeps start-of-day.
    - For bare-date inputs, `offset_min` (the `X-Timezone-Offset-Minutes`
      header, JS `Date.getTimezoneOffset()` convention: +480 for UTC-8;
      None when absent or unreadable) interprets the day boundary in that
      local zone and shifts it to UTC, only within ±14 h. A user on Pacific
      (offset=+420 during DST) querying through 2026-05-22 actually wants up
      to 2026-05-23T06:59:59.999 UTC.
    - `zone` (the caller's Agency's report time zone, `stats._report_zone`)
      makes a bare date mean that midnight (or end of day, for `to`) in the
      zone and outranks `offset_min` (docs/spec/phase-04-apply-stored-settings.md,
      stories 18 and 19).
    """
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
        # Full ISO with offset — convert to UTC then strip.
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    # Sanity-clamp to ±14h to defend against malformed clients.
    if bare and offset_min is not None and -14 * 60 <= offset_min <= 14 * 60:
        # Local-wall-clock → UTC: add the westward offset.
        dt = dt + timedelta(minutes=offset_min)

    return dt


def parse_date(
    s: str | None,
    *,
    field: str,
    request: Request | None = None,
    zone: ZoneInfo | None = None,
) -> datetime | None:
    """`parse_bound` with `offset_min` read from `request`'s offset header."""
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


def scope_ids(account_id: str | None) -> tuple[list[str] | None, str | None]:
    """`account_id` as one id or several comma-separated (roadmap 2.8), each
    clamped to the caller's Creators (`clamp_account_filter`, 403 on one that
    is not theirs; the isolation middleware reads only a single id), and the
    id the report time zone follows (the first)."""
    ids = split_account_ids(account_id)
    if not ids:
        return clamp_account_filter(None), None
    return [a for one in ids for a in clamp_account_filter(one)], ids[0]


def bucket_allowed(bucket: str, days: int) -> bool:
    """Whether a range of `days` calendar days may be shown by `bucket`, as
    Infloww's `getDisableStatus` (05-analytics M4) and the app's
    `granAllowed` (components/stats/chart.tsx): hour up to 2 days; day alone
    under 14, day or week to 31, week alone to 62, week or month to 365,
    month alone beyond."""
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
    """A report range's calendar days, as the app's `rangeDays`
    (components/stats/chart.tsx): its length in whole days, a millisecond
    added for the end of its last day and a daylight-saving hour either way
    rounded off. Midnights of any zone count alike (October in Europe, 745
    hours, is 31 days)."""
    return round(((end - start).total_seconds() + 0.001) / 86400)


def bucket_edges(bucket: str, start: datetime, end: datetime, zone: ZoneInfo | None,
                 week_start: str = "monday") -> list[datetime]:
    """The naive UTC starts of the `bucket`s of the report zone (UTC when
    None) that cover [start, end]: the first at or before `start`. Days,
    weeks and months begin at the zone's midnight, whatever its offset that
    day; hours are an hour apart in UTC, from the zone's hour holding `start`."""
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
