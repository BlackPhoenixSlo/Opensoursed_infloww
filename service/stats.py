"""
stats.py — read-only admin reporting endpoints.

Four read paths, all driven by the already-persisted SQLite tables:

  GET /admin/stats/revenue          → transactions, grouped by day or kind
  GET /admin/stats/grok-cost        → grok_daily_cost rollup rows
  GET /admin/stats/automation-runs  → recent automation_runs (most recent first)
  GET /admin/stats/per-employee     → messages.sent_by_employee_id JOIN
                                       transactions on (account_id, message_id)
                                       for messages-sent / PPV / revenue per op
  GET /admin/stats/sales-records    → one row per credited share of a sale, as
                                       Employee reports credit it, with its
                                       Rule (JSON pages or CSV)

All four are derived from rows the ingest path already wrote (event_transcoder
for messages+transactions, the Grok runners for the cost tables, the automation
scheduler for runs). We never hit OF here and never recompute counters that
already live denormalized on `fans` / `chats`.
"""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, and_, case, cast, column, func, literal_column, or_, select, text
from sqlalchemy.orm import aliased

import csv_export
import of_stats_daily
from auth import clamp_account_filter, get_request_user, split_account_ids
from db.engine import get_session
from db.models import (
    Account,
    Action,
    AutomationRun,
    ClockEvent,
    Employee,
    EmployeeGroup,
    Fan,
    GrokCall,
    GrokDailyCost,
    LinkClaimer,
    LinkMeta,
    Message,
    PromoCampaign,
    SubscriberSnapshot,
    Transaction,
    TrialLinkMirror,
)
import msg_stats
import tx_rollup
import xlsx_io
from attribution_backfill import PPV_KINDS, REVENUE_KINDS, REVERSED_STATUSES, TIP_KINDS, TRACKED_STATUSES
from shift_time import minutes_up
from sales_attribution import CREDITED_KINDS, credit_context, credit_row, credited_sales

# Attribution is read from the row (`transactions.credit_*`) and money from the
# rollups (`tx_daily`, `tx_hourly`), all kept by triggers (tx_rollup.py); the view
# `per_employee_revenue_with_attribution` stays only as their oracle.


log = logging.getLogger("of-relay.stats")

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


router = APIRouter(dependencies=[Depends(stats_guard)])


# Statuses we count toward revenue. `pending` ("loading" in OF's vocab)
# clears in ~7d so excluding it lags reality by a week — the dashboard
# would underreport an account that's actively earning. Including it
# matches OF's own /statistics page (which counts pending subs the moment
# they fire). If a pending row later flips to `chargedback`/`refunded`
# the next ingest tick updates the row in place and the metric self-
# corrects. `refund_pending` (was cleared, now being returned) is
# excluded — that money is leaving.


def _parse_date(
    s: str | None,
    *,
    field: str,
    request: Request | None = None,
    zone: ZoneInfo | None = None,
) -> datetime | None:
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
    - For bare-date inputs, when an `X-Timezone-Offset-Minutes` header is
      present (JS `Date.getTimezoneOffset()` convention: +480 for UTC-8),
      the day boundary is interpreted in that local zone and shifted to
      UTC. A user on Pacific (offset=+420 during DST) querying through
      2026-05-22 actually wants up to 2026-05-23T06:59:59.999 UTC.
    - `zone` (the caller's Agency's report time zone, `_report_zone`) makes a
      bare date mean that midnight (or end of day, for `to`) in the zone
      (docs/spec/phase-04-apply-stored-settings.md, stories 18 and 19).
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

    if bare and request is not None:
        # JS getTimezoneOffset returns minutes WEST of UTC (+480 for PST).
        raw = request.headers.get("x-timezone-offset-minutes")
        if raw is not None:
            try:
                offset_min = int(raw)
            except ValueError:
                offset_min = 0
            # Sanity-clamp to ±14h to defend against malformed clients.
            if -14 * 60 <= offset_min <= 14 * 60:
                # Local-wall-clock → UTC: add the westward offset.
                dt = dt + timedelta(minutes=offset_min)

    return dt


async def _report_zone(account_id: str | None) -> ZoneInfo | None:
    """The caller's Agency's report time zone, or None for today's UTC
    midnight: no session, a chatter linked to several Agencies that names no
    Creator, an Agency with no `report_tz`, or one stored invalid (its
    default applies, spec story 8). The Agency is Phase 1's Agency context,
    a chatter's named through the Creator in `account_id`.

    ASSUMPTION: any refusal from the Agency context (401 signed out, 400/403/
    503) reads as UTC here, and the endpoint's own `clamp_account_filter`
    keeps answering who may see what. Rung 4: a report never fails over its
    day boundaries. Overturned if a report should surface that refusal.

    ASSUMPTION: the zone applies to the Analytics reports' routes here
    (revenue, per-automation, per-employee, attribution coverage, per-model);
    grok-cost and grok-calls keep UTC days, since `grok_daily_cost` is stored
    per UTC day and cannot be re-cut. The echoed `from`/`to` of coverage and
    per-model stay the UTC dates of the bounds, as before. Rung 5. Overturned
    if the AI cost views must follow the report zone too.
    """
    return (await _report_prefs(account_id))[0]


async def _report_prefs(account_id: str | None) -> tuple[ZoneInfo | None, str]:
    """`_report_zone` and the same Agency's week start ("monday", its
    default, or "sunday"), read once."""
    from employees import agency_contexts
    from settings_api import applied_blob
    try:
        contexts = await agency_contexts(account_id=account_id)
    except HTTPException:
        return None, "monday"
    if len(contexts) != 1:
        return None, "monday"
    async with get_session() as s:
        prefs = await applied_blob(s, contexts[0].agency_user_id, "preferences")
    return (ZoneInfo(prefs["report_tz"]) if prefs.get("report_tz") else None), prefs.get("week_start") or "monday"


def scope_ids(account_id: str | None) -> tuple[list[str] | None, str | None]:
    """`account_id` as one id or several comma-separated (roadmap 2.8), each
    clamped to the caller's Creators (`clamp_account_filter`, 403 on one that
    is not theirs; the isolation middleware reads only a single id), and the
    id the report time zone follows (the first)."""
    ids = split_account_ids(account_id)
    if not ids:
        return clamp_account_filter(None), None
    return [a for one in ids for a in clamp_account_filter(one)], ids[0]


async def _day_sums(s, dims: tuple[str, ...], zone: ZoneInfo | None, *, fmt: str = "%Y-%m-%d",
                    **scope: Any) -> list[Any]:
    """`tx_rollup.window_sums` per local day (`day`) in the report zone,
    each UTC hour placed by the zone's offset at that hour, so a
    daylight-saving change moves no sale across a day edge (roadmap S8); a
    zone whose offset is not a whole hour is read by the minute. `fmt`
    '%Y-%m-%dT%H:00' cuts local hours instead (still under `day`); the hour
    a daylight-saving end repeats holds both. `_WEEK_SLOT` cuts the weekday
    and hour."""
    days = None
    if tx_rollup.whole_hours(zone, scope.get("start"), scope.get("end")):
        rows = await tx_rollup.window_sums(s, dims, bucket="hour", **scope)
        days = tx_rollup.local_days({r.bucket for r in rows}, zone, fmt=fmt)
    if days is None:
        rows = await tx_rollup.window_sums(s, dims, bucket="minute", **scope)
        days = tx_rollup.local_days({r.bucket for r in rows}, zone, hourly=False, fmt=fmt)
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        if (day := days.get(r.bucket)) is None:
            continue  # an occurred_at SQLite could not parse
        key = (day, *(getattr(r, d) for d in dims))
        acc = out.setdefault(key, {"day": day, **dict(zip(dims, key[1:])), **{m: 0 for m in tx_rollup.MEASURES}})
        for m in tx_rollup.MEASURES:
            acc[m] += int(getattr(r, m) or 0)
    return list(out.values())


# ── 1. Revenue ──────────────────────────────────────────────────────

# `group_by=hour_of_week`'s local slot, "<ISO weekday> <hour>", written by
# `_day_sums(fmt=)` and read back by `_week_slot`.
_WEEK_SLOT = "%u %H"


def _week_slot(slot: str) -> dict[str, int]:
    """A `_WEEK_SLOT` string as `{weekday, hour}`."""
    weekday, hour = slot.split()
    return {"weekday": int(weekday), "hour": int(hour)}


# The OnlyFans Statements category (of_stats_daily.EARNINGS) each ledger kind's
# sales count in; a kind OF's chart has no category we read for (stream tips:
# OF's `tips_stream`; custom) is in none. Measured 2026-10-25 against two live
# Creators: ppv_message = OF's messages to the cent per UTC day; tips and
# subscriptions with rebills matched 144 of 150 (Creator, day) cells.
_OF_CATEGORY = {"subscription": "subscribes", "rebill": "subscribes", "ppv_message": "messages", "ppv": "messages",
                "tip": "tips", "tip_post": "tips", "tip_message": "tips", "ppv_post": "post", "ppv_stream": "stream"}


def _of_top_up_rows(params: tx_rollup.Binds, of_cells: dict[tuple[str, str], list[dict[str, Any]]]) -> str:
    """SQL: per (account_id, UTC day, category) OnlyFans' stored figure for a
    day of `of_cells` (one read with OF's total: of_stats_daily._earnings_days)
    with the ledger's tracked sales of the same UTC day and category (`tx_daily`,
    whole UTC days as OF's), as columns o_* and l_*."""
    accounts, days = sorted({a for a, _d in of_cells}), sorted({d for _a, d in of_cells})
    cat = " ".join(f"WHEN {params.bind(k)} THEN {params.bind(c)}" for k, c in _OF_CATEGORY.items())
    lo, hi = params.bind(days[0]), params.bind(days[-1])
    return (
        "SELECT o.account_id AS account_id, o.day AS day, o.category AS category, o.net_cents AS o_net, "
        "o.gross_cents AS o_gross, o.sales AS o_sales, COALESCE(l.net, 0) AS l_net, "
        "COALESCE(l.gross, 0) AS l_gross, COALESCE(l.sales, 0) AS l_sales "
        "FROM of_earnings_daily o JOIN of_earnings_daily t ON t.account_id = o.account_id AND t.day = o.day "
        f"AND t.category = {params.bind(of_stats_daily.TOTAL)} "
        f"LEFT JOIN (SELECT account_id, day, CASE kind {cat} END AS category, SUM(gross_cents) AS gross, "
        "SUM(net_or_80_cents) AS net, SUM(sales) AS sales FROM tx_daily "
        f"WHERE {params.in_('account_id', accounts)} AND day >= {lo} AND day <= {hi} "
        f"AND {params.in_('status', TRACKED_STATUSES)} GROUP BY account_id, day, category) l "
        "ON l.account_id = o.account_id AND l.day = o.day AND l.category = o.category "
        f"WHERE {params.in_('o.account_id', accounts)} AND o.day >= {lo} AND o.day <= {hi} "
        f"AND {params.in_('o.category', of_stats_daily.EARNINGS)}")


async def _of_top_ups(s, of_cells: dict[tuple[str, str], list[dict[str, Any]]],
                      dims: tuple[str, ...]) -> list[dict[str, Any]]:
    """What OnlyFans' own figure adds to the ledger, summed per `dims` (of
    "account_id", "day" = the UTC day) and kind: per (Creator, UTC day,
    category) of `of_cells` (of_stats_daily.earnings_window), max(OF, ledger),
    as the part over the ledger's tracked sales of the same UTC day (both cut
    days at UTC midnight: OF stamps its points 00:00+00:00), only where OF's
    net is the larger: the days before a Creator was connected, and sales the
    ledger missed. OF never takes away a sale the ledger holds (2026-10-25:
    OF's PPV messages were read as $0 and erased a real $14), so the reports
    read ledger + these. Cells shaped as `_day_sums`' (MEASURES), summed in
    SQL: a request turns a few rows, not one per Creator, day and category."""
    if not of_cells:
        return []
    params = tx_rollup.Binds()
    rows = _of_top_up_rows(params, of_cells)
    keys = ", ".join((*dims, "category"))
    sql = (f"SELECT {keys}, SUM(MAX(0, o_gross - l_gross)) AS gross_cents, SUM(o_net - l_net) AS net_cents, "
           "SUM(MAX(0, o_sales - l_sales)) AS sales, SUM(MAX(0, MAX(0, o_gross - l_gross) - (o_net - l_net))) AS fee_cents "
           f"FROM ({rows}) WHERE o_net > l_net GROUP BY {keys}")
    return [{**{d: getattr(r, d) for d in dims}, "kind": of_stats_daily.EARNINGS_KIND[r.category],
             "gross_cents": r.gross_cents, "net_cents": r.net_cents, "net_missing": 0, "net_or_80_cents": r.net_cents,
             "sales": r.sales, "fee_cents": r.fee_cents, "vat_cents": 0}
            for r in (await s.execute(text(sql), params)).all()]


def _plus(cells: list[dict[str, Any]], more: list[dict[str, Any]], dims: tuple[str, ...]) -> list[dict[str, Any]]:
    """`cells` and `more` summed per `dims`."""
    out: dict[tuple, dict[str, Any]] = {}
    for c in (*cells, *more):
        key = tuple(c[d] for d in dims)
        acc = out.setdefault(key, {**dict(zip(dims, key)), **{m: 0 for m in tx_rollup.MEASURES}})
        for m in tx_rollup.MEASURES:
            acc[m] += int(c[m] or 0)
    return list(out.values())


@router.get("/admin/stats/revenue")
async def revenue(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    group_by: str = Query("day", pattern="^(day|hour|kind|hour_of_week)$"),
    include_net: bool = Query(False),
    by_kind: bool = Query(False),
    status: str = Query("tracked", pattern="^(tracked|reversed)$"),
) -> dict[str, Any]:
    """Sum + count of `transactions.amount_cents` bucketed by `day` (UTC, or
    the caller's Agency's report time zone, `_report_zone`), by `hour` (the
    local hour, as 'YYYY-MM-DDTHH:00' under `day`; Creator reports' "Hour",
    roadmap W5 5.4) or by `kind` (ppv / tip / subscription / rebill /
    custom). When grouping by day or hour, `kind` is null in the response;
    when grouping by kind, `day` is null.
    Both filters (account_id, from/to) are optional and AND-ed together.
    `account_id` takes several comma-separated Creators in one call, summed
    (roadmap 2.8); the report zone is the first one's Agency's.

    Read from the rollups (`tx_rollup.window_sums`: whole UTC days, else
    hours, the partial hours at a window's edges from the ledger rows); by
    day, each hour lands on its local day by the zone's offset at that hour
    (`_day_sums`).

    Rows are restricted to `TRACKED_STATUSES` ("cleared", "pending"), matching
    /admin/stats/per-model. Before 2026-08-29 this endpoint applied NO status
    predicate while per-model did, so the two surfaces summed different row sets
    and the dashboard's KPI card could never reconcile with its own creators
    table. `chargedback` / `refund_pending` is money leaving and is not revenue;
    `pending` IS counted, because the ledger writes rows pending and clears them
    ~7 days later — a cleared-only filter renders the current week $0.00.

    Two opt-in flags extend the response. Both default False and, when False,
    create no keys at all — the day/kind responses are byte-identical to what
    every existing caller already parses (locked by
    service/tests/test_stats_revenue.py):

    * `include_net=true` adds `net_cents` (OF's own post-fee figure, summed from
      `transactions.net_cents`) and `net_missing_count` to every row. Null nets
      — a WS-pumped row the ledger has not backfilled yet — are counted, never
      imputed: COALESCE-ing them to `amount_cents` would silently label gross as
      net. Note `net = gross - fee`; VAT is tracked separately and NOT deducted.
      It adds `fee_cents` and `vat_cents` too (OF's own per-row fee and VAT,
      summed; a row with no net has none either, so the same count discloses it).
    * `by_kind=true` (valid only with `group_by=day` or `hour`) nests a `by_kind[]` array
      of per-kind rows under each day. Nested rather than flat on purpose: the
      day-series callers consume with plain assignment (`byDay[r.day] = …`), not
      accumulation, so a flat day-x-kind list would make them silently keep only
      the last kind per day. Mirrors /admin/stats/per-employee's `per_account[]`.

    `status=reversed` reads the reversals (`REVERSED_STATUSES`) in place of the
    earnings, grouped and flagged the same way: Creator reports' Chargebacks
    chart. A reversal is dated by its sale (`occurred_at`; the ledger keeps no
    reversal time), where Infloww dates a refund by its credit date.

    OnlyFans fills in what the ledger missed: grouped by `day` or `kind`
    (earnings, not reversals), each complete (Creator, UTC day) whose own OF
    Statistics figure is stored (`of_earnings_daily`, of_stats_daily.py) reads
    the larger of OF's and the ledger's per category (`_of_top_ups`: OF's net
    over the ledger's is added, a derived gross, fee = gross - net, no VAT; a
    sale the ledger holds is never taken away). Today, and any day not read
    from OF yet, stay the ledger's. The response then adds `history_missing_days`: the
    (Creator, day) pairs before the Creator was added with neither, which a
    growth against the window must read as unknown.

    `group_by=hour_of_week` folds the window into the report zone's weekday
    and hour (Creator reports' Earnings heatmap): rows `{weekday, hour,
    total_cents, count}` (ISO weekday, 1 = Monday; hour 0-23), only the slots
    with a sale, each UTC hour of `tx_hourly` at the zone's wall clock then.
    """
    by_time = group_by in ("day", "hour")
    if by_kind and not by_time:
        raise HTTPException(
            status_code=400,
            detail="by_kind requires group_by=day or hour (it nests kinds inside each bucket)",
        )

    account_ids, zone_id = scope_ids(account_id)
    zone = await _report_zone(zone_id)
    start = _parse_date(from_, field="from", zone=zone)
    end = _parse_date(to, field="to", zone=zone)
    statuses = REVERSED_STATUSES if status == "reversed" else TRACKED_STATUSES
    scope = {"account_ids": account_ids, "start": start, "end": end, "where": {"status": statuses}}

    # Earnings by day or kind add OnlyFans' own figure where it is over the
    # ledger's (`_of_top_ups`: max per Creator, UTC day and category); hours,
    # the heatmap and reversals stay the ledger's (OF charts no hour, no reversal).
    of_cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    gaps = None
    if status == "tracked" and group_by in ("day", "kind"):
        of_cells, gaps = await of_stats_daily.earnings_window(account_ids, start, end)

    async with get_session() as s:
        # One read, day x kind; the day rows and the nested by_kind rows are
        # both sums of it, so the children always sum to their parent day.
        if by_time:
            unit = "%Y-%m-%dT%H:00" if group_by == "hour" else "%Y-%m-%d"
            cells = await _day_sums(s, ("kind",), zone, fmt=unit, **scope)
        elif group_by == "hour_of_week":
            # `day` holds the local slot (`_WEEK_SLOT`).
            cells = await _day_sums(s, (), zone, fmt=_WEEK_SLOT, **scope)
        else:
            cells = [{"day": None, **r._asdict()}
                     for r in await tx_rollup.window_sums(s, ("kind",), **scope)]
        # OF's UTC day lands on the report day of the same date (`window_days`).
        top = await _of_top_ups(s, of_cells, ("day",) if by_time else ())
    if top:
        cells = _plus(cells, top if by_time else [{**c, "day": None} for c in top], ("day", "kind"))

    def _sum(group: list[dict[str, Any]], **keys: Any) -> SimpleNamespace:
        return SimpleNamespace(**keys, total_cents=sum(c["gross_cents"] for c in group),
                               count=sum(c["sales"] for c in group),
                               net_cents=sum(c["net_cents"] for c in group),
                               net_missing=sum(c["net_missing"] for c in group),
                               fee_cents=sum(c["fee_cents"] for c in group),
                               vat_cents=sum(c["vat_cents"] for c in group))

    grouped: dict[Any, list[dict[str, Any]]] = {}
    for c in cells:
        grouped.setdefault(c["kind"] if group_by == "kind" else c["day"], []).append(c)
    if group_by != "kind":
        rows = [_sum(grouped[d], day=d, kind=None) for d in sorted(grouped)]
    else:
        rows = sorted((_sum(g, day=None, kind=k) for k, g in grouped.items()),
                      key=lambda r: (-r.total_cents, r.kind))
    kind_rows = sorted((_sum([c], day=c["day"], kind=c["kind"]) for c in cells),
                       key=lambda r: (r.day or "", -r.total_cents, r.kind)) if by_kind else []

    def _base(r) -> dict[str, Any]:
        if group_by == "hour_of_week":
            d: dict[str, Any] = _week_slot(r.day)
        else:
            d = {"day": r.day if by_time else None,
                 "kind": r.kind if group_by == "kind" else None}
        d.update(total_cents=int(r.total_cents or 0), count=int(r.count or 0))
        if include_net:
            d["net_cents"] = int(r.net_cents or 0)
            d["net_missing_count"] = int(r.net_missing or 0)
            d["fee_cents"] = int(r.fee_cents or 0)
            d["vat_cents"] = int(r.vat_cents or 0)
        return d

    out = [_base(r) for r in rows]

    if by_kind:
        children: dict[str, list[dict[str, Any]]] = {}
        for r in kind_rows:
            c = {"kind": r.kind, "total_cents": int(r.total_cents or 0),
                 "count": int(r.count or 0)}
            if include_net:
                c["net_cents"] = int(r.net_cents or 0)
                c["net_missing_count"] = int(r.net_missing or 0)
            children.setdefault(r.day, []).append(c)
        for row in out:
            row["by_kind"] = children.get(row["day"], [])

    resp: dict[str, Any] = {"rows": out}
    if gaps is not None:
        # (Creator, day) pairs before a Creator was added with no OF earnings
        # stored: unknown, not $0.00, so a growth against this window is "-".
        resp["history_missing_days"] = gaps
    return resp


# ── 2. Grok daily cost ──────────────────────────────────────────────

@router.get("/admin/stats/grok-cost")
async def grok_cost(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
) -> dict[str, Any]:
    """Daily Grok spend rollup. Reads grok_daily_cost directly (no aggregation
    over grok_calls). When `account_id` is omitted, returns ALL rows in the
    range — including the global rollup row (account_id=NULL) and every
    per-account row; the caller can filter client-side."""
    account_ids = clamp_account_filter(account_id)
    start = _parse_date(from_, field="from")
    end = _parse_date(to, field="to")

    async with get_session() as s:
        q = select(
            GrokDailyCost.day,
            GrokDailyCost.account_id,
            GrokDailyCost.cost_cents,
            GrokDailyCost.call_count,
            GrokDailyCost.is_capped,
            GrokDailyCost.updated_at,
        )
        if account_ids is not None:
            q = q.where(GrokDailyCost.account_id.in_(account_ids))
        # `day` is a TEXT 'YYYY-MM-DD' so lexical compare equals chronological.
        if start:
            q = q.where(GrokDailyCost.day >= start.strftime("%Y-%m-%d"))
        if end:
            q = q.where(GrokDailyCost.day <= end.strftime("%Y-%m-%d"))
        q = q.order_by(GrokDailyCost.day.desc(), GrokDailyCost.account_id)
        rows = (await s.execute(q)).all()

    return {
        "rows": [
            {
                "day": r.day,
                "account_id": r.account_id,
                "cost_cents": int(r.cost_cents or 0),
                "call_count": int(r.call_count or 0),
                "is_capped": bool(r.is_capped),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


# ── 2b. Grok per-call breakdown (the cost ruler) ────────────────────

@router.get("/admin/stats/grok-calls")
async def grok_calls(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    status: str = Query("done", pattern="^(done|error|pending|all)$"),
    by: str = Query("purpose_model", pattern="^(purpose_model|purpose|model|day)$"),
) -> dict[str, Any]:
    """Aggregate `grok_calls` so you can SEE which automation costs what — the
    detail the daily rollup (`/admin/stats/grok-cost`) can't give you.

    Unlike grok_cost (which reads the pre-summed grok_daily_cost), this groups
    the raw call rows by purpose × model (default) and sums tokens, cost, and
    DeepSeek cache-hit tokens — so you can compare a window's cost before/after
    a prompt change and watch the cache-hit ratio climb.

    `cost_millicents` is the internal unit (cents×100 — sub-cent DeepSeek calls
    don't floor to 0); `cost_cents` is the human dollars figure. `cache_hit_ratio`
    is cached-input ÷ total-input over the bucket (0 when the provider — e.g.
    Grok — doesn't report cache hits). `status` defaults to 'done' so partial /
    failed calls (which carry no real cost) don't skew the numbers; pass
    status=all to include them. The time filter is on `called_at`."""
    account_ids = clamp_account_filter(account_id)
    start = _parse_date(from_, field="from")
    end = _parse_date(to, field="to")

    day_expr = func.strftime("%Y-%m-%d", GrokCall.called_at).label("day")
    # Group key columns vary by `by`; everything else is summed the same way.
    keys: dict[str, Any] = {
        "purpose_model": [GrokCall.purpose.label("purpose"),
                          GrokCall.model.label("model"),
                          GrokCall.provider.label("provider")],
        "purpose": [GrokCall.purpose.label("purpose")],
        "model": [GrokCall.model.label("model"),
                  GrokCall.provider.label("provider")],
        "day": [day_expr, GrokCall.purpose.label("purpose")],
    }[by]

    metrics = [
        func.count(GrokCall.id).label("calls"),
        func.coalesce(func.sum(GrokCall.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(GrokCall.tokens_out), 0).label("tokens_out"),
        func.coalesce(func.sum(GrokCall.cache_hit_tokens), 0).label("cache_hit_tokens"),
        func.coalesce(func.sum(GrokCall.cost_cents), 0).label("cost_millicents"),
        func.coalesce(func.avg(GrokCall.latency_ms), 0).label("avg_latency_ms"),
    ]

    async with get_session() as s:
        q = select(*keys, *metrics)
        if account_ids is not None:
            q = q.where(GrokCall.account_id.in_(account_ids))
        if status != "all":
            q = q.where(GrokCall.status == status)
        if start:
            q = q.where(GrokCall.called_at >= start)
        if end:
            q = q.where(GrokCall.called_at <= end)
        q = q.group_by(*keys).order_by(func.sum(GrokCall.cost_cents).desc())
        rows = (await s.execute(q)).all()

    out = []
    for r in rows:
        m = r._mapping
        t_in = int(m["tokens_in"] or 0)
        cache = int(m["cache_hit_tokens"] or 0)
        millicents = int(m["cost_millicents"] or 0)
        out.append({
            "day": m.get("day"),
            "purpose": m.get("purpose"),
            "model": m.get("model"),
            "provider": m.get("provider"),
            "calls": int(m["calls"] or 0),
            "tokens_in": t_in,
            "tokens_out": int(m["tokens_out"] or 0),
            "cache_hit_tokens": cache,
            "cache_hit_ratio": round(cache / t_in, 3) if t_in else 0.0,
            "cost_millicents": millicents,
            "cost_cents": round(millicents / 100, 4),
            "avg_latency_ms": int(m["avg_latency_ms"] or 0),
        })
    total_mc = sum(r["cost_millicents"] for r in out)
    total_calls = sum(r["calls"] for r in out)
    # Audit rows whose prompt redaction failed and fell back to a stub. The
    # audit write is deliberately swallowed so it can never take down a live LLM
    # call — which means a degraded audit is otherwise INVISIBLE. Non-zero here
    # is the only signal that grok_calls has stopped recording what we sent.
    from llm_client import audit_degraded_count
    return {
        "rows": out,
        "totals": {
            "calls": total_calls,
            "cost_millicents": total_mc,
            "cost_cents": round(total_mc / 100, 4),
        },
        "audit_degraded": audit_degraded_count(),
    }


@router.get("/admin/stats/per-automation")
async def per_automation(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
) -> dict[str, Any]:
    """Per-automation rollup — the "which automations earn and which cost"
    panel. Answers all four at once, per automation:

      • messages_sent  — outbound rows stamped with this automation (per-chat
                         AND mass), from `messages.automation_kind`
      • revenue_cents  — earnings attributed to this automation's messages,
                         the attribution view's answer, materialised as
                         `transactions.credit_automation_kind` (rollups)
      • llm_calls / tokens_in / tokens_out / cost — LLM spend, from
                         `grok_calls.purpose`

    The three scans key on the SAME automation token (e.g. `welcome_chatter_for_info`,
    `welcome`, `send_mass_message`) — `messages.automation_kind` and
    `grok_calls.purpose` share a vocabulary by design (see the senders). So a
    mass broadcaster shows sends + revenue with $0 LLM spend, while `gen_info`
    (an LLM-only profiler that sends nothing) shows spend with 0 sends. NULL
    (human / relay sends) is excluded — that revenue lives in /per-employee.

    LLM spend counts status='done' calls only (pending/error carry no real
    cost). `cost_millicents` is the internal unit (cents×100); `cost_cents` is
    the human dollars figure. Time filter is `created_at` / `occurred_at` /
    `called_at` respectively."""
    account_ids = clamp_account_filter(account_id)
    zone = await _report_zone(account_id)
    start = _parse_date(from_, field="from", zone=zone)
    end = _parse_date(to, field="to", zone=zone)

    agg: dict[str, dict[str, Any]] = {}

    def _bucket(kind: str) -> dict[str, Any]:
        if kind not in agg:
            agg[kind] = {
                "automation": kind,
                "messages_sent": 0,
                "revenue_cents": 0,
                "llm_calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_millicents": 0,
            }
        return agg[kind]

    async with get_session() as s:
        # ── messages_sent by automation_kind ───────────────────────────
        mq = (
            select(
                Message.automation_kind.label("kind"),
                func.count().label("n"),
            )
            .where(Message.automation_kind.is_not(None))
            .where(Message.direction == "out")
        )
        if account_ids is not None:
            mq = mq.where(Message.account_id.in_(account_ids))
        if start:
            mq = mq.where(Message.created_at >= start)
        if end:
            mq = mq.where(Message.created_at <= end)
        mq = mq.group_by(Message.automation_kind)
        for r in (await s.execute(mq)).all():
            _bucket(r.kind)["messages_sent"] = int(r.n or 0)

        # ── revenue by automation_kind (the view's rows, from the rollup) ─
        for r in await tx_rollup.window_sums(
                s, ("automation_kind",), account_ids=account_ids, start=start, end=end,
                where={"status": TRACKED_STATUSES, "kind": REVENUE_KINDS}):
            if r.automation_kind is not None:
                _bucket(r.automation_kind)["revenue_cents"] = int(r.gross_cents or 0)

        # ── LLM spend by purpose ───────────────────────────────────────
        gq = (
            select(
                GrokCall.purpose.label("kind"),
                func.count(GrokCall.id).label("calls"),
                func.coalesce(func.sum(GrokCall.tokens_in), 0).label("tin"),
                func.coalesce(func.sum(GrokCall.tokens_out), 0).label("tout"),
                func.coalesce(func.sum(GrokCall.cost_cents), 0).label("mc"),
            )
            .where(GrokCall.status == "done")
        )
        if account_ids is not None:
            gq = gq.where(GrokCall.account_id.in_(account_ids))
        if start:
            gq = gq.where(GrokCall.called_at >= start)
        if end:
            gq = gq.where(GrokCall.called_at <= end)
        gq = gq.group_by(GrokCall.purpose)
        for r in (await s.execute(gq)).all():
            b = _bucket(r.kind)
            b["llm_calls"] = int(r.calls or 0)
            b["tokens_in"] = int(r.tin or 0)
            b["tokens_out"] = int(r.tout or 0)
            b["cost_millicents"] = int(r.mc or 0)

    rows = [
        {**b, "cost_cents": round(b["cost_millicents"] / 100, 4)}
        for b in agg.values()
    ]
    # Highest earner first; ties broken by send volume.
    rows.sort(key=lambda r: (r["revenue_cents"], r["messages_sent"]), reverse=True)
    total_mc = sum(r["cost_millicents"] for r in rows)
    return {
        "rows": rows,
        "totals": {
            "messages_sent": sum(r["messages_sent"] for r in rows),
            "revenue_cents": sum(r["revenue_cents"] for r in rows),
            "llm_calls": sum(r["llm_calls"] for r in rows),
            "cost_millicents": total_mc,
            "cost_cents": round(total_mc / 100, 4),
        },
    }


# ── 3. Automation runs ──────────────────────────────────────────────

@router.get("/admin/stats/per-fan-data")
async def per_fan_data(
    account_id: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=5000),
) -> dict[str, Any]:
    """Per-fan profile data (Fan reports → User data), read from our DB. One
    account at a time (the UI picks one); with no account_id, every account the
    principal owns. Owner-gated via clamp_account_filter."""
    from fan_data import _HEADER, build_fan_data

    account_ids = clamp_account_filter(account_id)
    rows: list[dict] = []
    for aid in (account_ids or []):
        rows.extend(await build_fan_data(aid, limit))
    # Spend-desc so the highest-value fans surface first.
    rows.sort(key=lambda r: r.get("total_spend") or 0, reverse=True)
    return {"rows": rows, "count": len(rows), "columns": list(_HEADER)}


def _new_subs_q(account_ids: list[str] | None, start: datetime, end: datetime) -> Any:
    """New subs in the window: each fan whose subscription began in it, by a
    subscription sale (pending too, so a sub that fires today shows at once;
    a chargeback flips the row's status and drops it) or by OF's own roster
    (`subscriber_snapshot.subscribe_at`), which also lists free and trial
    subscribers, who leave no sale (roadmap S6). The roster holds the
    subscriptions active at its last crawl, so a free sub that has since
    lapsed is not counted. One row per (account_id, fan_id), `at` his first
    start in the window; per-model counts them, Fan reports buckets them."""
    b = tx_rollup.Binds()
    acct_in = "" if account_ids is None else " AND " + b.in_("account_id", account_ids)
    s_, e_ = b.bind(start.strftime(tx_rollup.TS_FORMAT)), b.bind(end.strftime(tx_rollup.TS_FORMAT))
    return text(
        "SELECT account_id, fan_id, MIN(at) AS at FROM ("
        "SELECT account_id, fan_id, occurred_at AS at FROM transactions WHERE kind = 'subscription' "
        f"AND fan_id IS NOT NULL AND {b.in_('status', TRACKED_STATUSES)} "
        f"AND occurred_at >= {s_} AND occurred_at <= {e_}{acct_in} "
        "UNION ALL SELECT account_id, fan_id, subscribe_at AS at FROM subscriber_snapshot "
        f"WHERE subscribe_at >= {s_} AND subscribe_at <= {e_}{acct_in}) GROUP BY account_id, fan_id"
    ).bindparams(**b).columns(column("account_id"), column("fan_id"), column("at"))


# ── Fan reports: Top fans, Traffic source, New fans (roadmap W5 5.6) ───

FAN_REPORT_FIELDS = ("account_id", "fan_id", "fan_name", "username", "total_cents", "net_or_80_cents",
                     "tips_cents", "ppv_cents", "subs_cents", "subscribed_at")
_FAN_SORTS = {"total": "total_cents", "tips": "tips_cents", "ppv": "ppv_cents", "subs": "subs_cents"}


@router.get("/admin/stats/fan-report", response_model=None)
async def fan_report(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
    sort: str = Query("total", pattern="^(total|tips|ppv|subs)$"),
    limit: int = Query(100, ge=1, le=5000),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> dict[str, Any] | StreamingResponse:
    """Fan reports over the window (default the last 30 days), for the
    caller's Creators or the ones named (`account_id`, comma list):

      top_fans  each fan's spend in the window (every kind, cleared and
                pending, as per-model's revenue): total, net (OnlyFans' net,
                else 80% of gross, the reports' `net_or_80` basis), tips, PPV
                and subscriptions; ranked by `sort`, `limit` rows.
                `subscribed_at` is his current subscription's start on OF's
                roster (`subscriber_snapshot`), Subscription length's basis;
                null for a fan the roster never listed.
      traffic   the window's spend by the free trial link or promotion each
                spender claimed (`link_claimers`; a fan under several counts
                under his earliest claim: OF's subscribe_at, else when we first
                saw it), the rest as kind null.
                Tracking links' claimers are read live from OF and never
                stored (of_tracking_api), so they are not a source here.
      growth    per day of the report zone: `new_fans`, the fans whose
                subscription began (a subscription sale or the roster's
                `subscribe_at`, each fan once, on his first day; per-model's
                new subs), and `renewed_fans`, the fans with a rebill.

    `format=csv` streams the whole top_fans ranking instead, `limit` aside,
    under the shared CSV cap (csv_export.CSV_MAX_ROWS).

    ASSUMPTION: no Total fans growth line: nothing stores the subscriber
    count per day (the roster is a current list), and rebuilding it from
    the roster would miss every fan who left before its first crawl. Rung 4.
    Overturned once a daily subscriber snapshot is kept (roadmap 5.5)."""
    account_ids, zone_account = scope_ids(account_id)
    zone = await _report_zone(zone_account)
    start = _parse_date(from_, field="from", zone=zone) if from_ else datetime.utcnow() - timedelta(days=30)
    end = _parse_date(to, field="to", zone=zone) if to else datetime.utcnow()

    T = Transaction
    scope = [T.status.in_(TRACKED_STATUSES), T.fan_id.is_not(None), T.occurred_at >= start, T.occurred_at <= end]
    if account_ids is not None:
        scope.append(T.account_id.in_(account_ids))

    def _sum_if(cond: Any) -> Any:
        return func.coalesce(func.sum(case((cond, T.amount_cents), else_=0)), 0)

    spend = (
        select(
            T.account_id, T.fan_id,
            func.sum(T.amount_cents).label("total_cents"),
            literal_column(tx_rollup.MEASURES["net_or_80_cents"][1]).label("net_or_80_cents"),
            _sum_if(T.kind.in_(TIP_KINDS)).label("tips_cents"),
            _sum_if(T.kind.in_(PPV_KINDS)).label("ppv_cents"),
            _sum_if(T.kind.in_(("subscription", "rebill"))).label("subs_cents"),
        )
        .where(*scope)
        .group_by(T.account_id, T.fan_id)
        .subquery()
    )
    top_q = (
        select(spend, Fan.of_display_name, Fan.of_username, SubscriberSnapshot.subscribe_at)
        .outerjoin(Fan, and_(Fan.account_id == spend.c.account_id, Fan.fan_id == spend.c.fan_id))
        .outerjoin(SubscriberSnapshot, and_(SubscriberSnapshot.account_id == spend.c.account_id,
                                            SubscriberSnapshot.fan_id == spend.c.fan_id))
        .order_by(spend.c[_FAN_SORTS[sort]].desc(), spend.c.total_cents.desc(), spend.c.fan_id)
    )

    def _fan(r: Any) -> dict[str, Any]:
        return {
            "account_id": r.account_id, "fan_id": int(r.fan_id),
            "fan_name": r.of_display_name, "username": r.of_username,
            "total_cents": int(r.total_cents or 0), "net_or_80_cents": int(r.net_or_80_cents or 0),
            "tips_cents": int(r.tips_cents or 0), "ppv_cents": int(r.ppv_cents or 0),
            "subs_cents": int(r.subs_cents or 0),
            "subscribed_at": r.subscribe_at.isoformat() if r.subscribe_at else None,
        }

    if format == "csv":
        async def _rows(s):
            async for r in csv_export.query_rows(s, top_q):
                yield _fan(r)

        safe = csv_export.safe_filename_part
        return csv_export.download(
            f"top-fans_{safe(from_, 'start')}_to_{safe(to, 'now')}.csv", _rows, FAN_REPORT_FIELDS,
            lambda rec: ["" if rec[k] is None else rec[k] for k in FAN_REPORT_FIELDS],
        )

    # Each fan's earliest claim, then the window's spend by that link.
    LC = LinkClaimer
    ranked = select(LC.id, LC.account_id, LC.fan_id, func.row_number().over(
        partition_by=(LC.account_id, LC.fan_id),
        order_by=(func.coalesce(LC.subscribe_at, LC.first_seen_at), LC.id)).label("n"))
    if account_ids is not None:
        ranked = ranked.where(LC.account_id.in_(account_ids))
    ranked = ranked.subquery()
    first_claim = (
        select(ranked.c.account_id, ranked.c.fan_id, ranked.c.id.label("cid"))
        .where(ranked.c.n == 1)
        .subquery()
    )
    claim = aliased(LinkClaimer)
    traffic_q = (
        select(spend.c.account_id, claim.kind, claim.of_id,
               func.count().label("fans"), func.sum(spend.c.total_cents).label("total_cents"))
        .select_from(spend)
        .outerjoin(first_claim, and_(first_claim.c.account_id == spend.c.account_id,
                                     first_claim.c.fan_id == spend.c.fan_id))
        .outerjoin(claim, claim.id == first_claim.c.cid)
        .group_by(spend.c.account_id, claim.kind, claim.of_id)
        .order_by(func.sum(spend.c.total_cents).desc())
    )

    new_q = _new_subs_q(account_ids, start, end)  # each fan on his first day in the window
    renew_q = (
        select(T.account_id, T.fan_id, T.occurred_at)
        .where(*scope, T.kind == "rebill")
    )

    async with get_session() as s:
        top = [_fan(r) for r in (await s.execute(top_q.limit(limit))).all()]
        traffic_rows = (await s.execute(traffic_q)).all()
        new_rows = (await s.execute(new_q)).all()
        renew_rows = (await s.execute(renew_q)).all()
        traffic = await _link_names(s, traffic_rows)

    def _day(at: Any) -> str:
        if isinstance(at, str):  # the text() union hands back SQLite's stored string
            at = datetime.fromisoformat(at)
        if zone is not None:
            at = at.replace(tzinfo=timezone.utc).astimezone(zone)
        return at.date().isoformat()

    growth: dict[str, dict[str, Any]] = {}

    def _bump(day: str, key: str) -> None:
        growth.setdefault(day, {"day": day, "new_fans": 0, "renewed_fans": 0})[key] += 1

    for r in new_rows:
        _bump(_day(r.at), "new_fans")
    # A fan billed twice in a day (a re-sub after a chargeback) renewed once.
    for day, _aid, _fid in {(_day(r.occurred_at), r.account_id, r.fan_id) for r in renew_rows}:
        _bump(day, "renewed_fans")

    return {"top_fans": top, "traffic": traffic, "growth": sorted(growth.values(), key=lambda g: g["day"])}


async def _link_names(s, rows: list[Any]) -> list[dict[str, Any]]:
    """Traffic rows named: a trial link by its mirror, a promotion by its
    campaign (through `link_meta.campaign_id`, which a re-armed promotion's
    earlier OF ids keep, else the campaign's current OF id), and the link's
    Source as the operator typed it."""
    keys = {(r.account_id, r.kind, int(r.of_id)) for r in rows if r.kind}
    trials: dict[tuple[str, int], str] = {}
    promos: dict[tuple[str, int], str] = {}
    metas: dict[tuple[str, str, int], Any] = {}
    if keys:
        aids = {k[0] for k in keys}
        ids = {k[2] for k in keys}
        for t in (await s.execute(select(TrialLinkMirror).where(
                TrialLinkMirror.account_id.in_(aids), TrialLinkMirror.of_trial_id.in_(ids)))).scalars():
            trials[(t.account_id, int(t.of_trial_id))] = t.name
        for m in (await s.execute(select(LinkMeta).where(
                LinkMeta.account_id.in_(aids), LinkMeta.of_id.in_(ids)))).scalars():
            metas[(m.account_id, m.kind, int(m.of_id))] = m
        camp_ids = {m.campaign_id for m in metas.values() if m.campaign_id}
        campaigns = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.account_id.in_(aids),
            or_(PromoCampaign.of_promo_id.in_(ids), PromoCampaign.id.in_(camp_ids))))).scalars().all()
        by_id = {p.id: p.name for p in campaigns}
        promos = {(p.account_id, int(p.of_promo_id)): p.name for p in campaigns if p.of_promo_id is not None}
        for (aid, kind, of_id), m in metas.items():
            if kind == "promo" and m.campaign_id in by_id:
                promos[(aid, of_id)] = by_id[m.campaign_id]
    out = []
    for r in rows:
        of_id = int(r.of_id) if r.kind else None
        meta = metas.get((r.account_id, r.kind, of_id)) if r.kind else None
        names = trials if r.kind == "trial" else promos
        out.append({
            "account_id": r.account_id, "kind": r.kind, "of_id": of_id,
            "name": names.get((r.account_id, of_id)) if r.kind else None,
            "source": meta.source if meta is not None else None,
            "fans": int(r.fans or 0), "total_cents": int(r.total_cents or 0),
        })
    return out


@router.get("/admin/stats/automation-runs")
async def automation_runs(
    kind: str | None = Query(None),
    account_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Most-recent automation runs first. `stats_json` is returned verbatim
    (TEXT, already JSON-serialized by the runner)."""
    account_ids = clamp_account_filter(account_id)
    async with get_session() as s:
        q = select(AutomationRun)
        if kind:
            # Deliberately raw: the param filters rows displayed VERBATIM, so a
            # caller matching a legacy token sees exactly the rows carrying it.
            q = q.where(AutomationRun.kind == kind)
        if account_ids is not None:
            q = q.where(AutomationRun.account_id.in_(account_ids))
        q = q.order_by(AutomationRun.started_at.desc()).limit(limit)
        rows = (await s.execute(q)).scalars().all()

    return {
        "runs": [
            {
                "id": r.id,
                "account_id": r.account_id,
                "kind": r.kind,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "status": r.status,
                "stats_json": r.stats_json,
                "error_text": r.error_text,
            }
            for r in rows
        ]
    }


# ── 4. Per-employee revenue ─────────────────────────────────────────

_UNATTRIBUTED_BUCKET = "Unattributed"


async def _only_chatters(own: set[int] | None, chatter_only: bool) -> set[int] | None:
    """The Employee ids a report may show (`own`, None for all), narrowed with
    `chatter_only` to the built-in Chatter role's (`permissions.role_holders`):
    Employee reports' "Show employees with chatter role only" (roadmap W5 5.13)."""
    if not chatter_only:
        return own
    from permissions import role_holders
    chatters = await role_holders("chatter")
    return chatters if own is None else own & chatters


def _empty_employee_row(eid: int | None, display_name: str | None) -> dict[str, Any]:
    return {
        "employee_id": eid,
        "display_name": display_name,
        "messages_sent": 0,
        "ppv_conversions": 0,
        "revenue_cents": 0,
        "revenue_by_kind": {"ppv": 0, "tip": 0},
    }


@router.get("/admin/stats/per-employee")
async def per_employee(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    by_account: bool = Query(False),
    chatter_only: bool = Query(False),
) -> dict[str, Any]:
    """Per-employee revenue rollup. Each sale is credited by its Creator's
    Agency's Sales Settings rules (`sales_attribution.credited_sales`), whose
    Converters rule credits the last human chatter who messaged the fan within
    the Agency's window of the sale (1 h by default, materialised on the row);
    summed from the hourly rollup (`grouped=True`).

    Numbers per employee:
      • messages_sent     — count of outbound messages this op wrote by hand
                             in window, no mass or automated ones (S4)
      • ppv_conversions   — PPV sales credited to the op
      • revenue_cents     — SUM(amount_cents) of the sales credited to the op

    Special bucket: a sale credited to no one (no human chatter messaged the
    fan within the Converters window, no manual assignment, or a sale a rule
    leaves Unattributed) lands in an
    "Unattributed" synthetic bucket so the revenue stays visible in the
    per-employee total. `attribution_fallback` carries
    `sales_attribution.FALLBACK_LINE` when an Agency in scope has Shift
    schedule credited by Converters because its Time tracking is off, else null.

    ``by_account=true`` adds a `per_account[]` breakdown per employee.
    ``chatter_only=true`` keeps the Employees holding the Chatter role
    (`permissions.role_holders`), no Unattributed bucket.

    Under Role enforcement a chatter whose Data scope is not "all" gets only
    its own row (`permissions.scoped_employee_ids`), no Unattributed bucket."""
    from permissions import scoped_employee_ids
    own = await _only_chatters(await scoped_employee_ids(), chatter_only)
    zone = await _report_zone(None)
    start = _parse_date(from_, field="from", zone=zone)
    end = _parse_date(to, field="to", zone=zone)
    # Clamp to the signed-in friend's accounts so per-employee rollups
    # don't mix in other friends' chatter activity.
    account_ids = clamp_account_filter(None)

    # ── Q1: messages_sent per employee: its own sends, no mass or automated
    # ones (`msg_stats.chatter_sends`, roadmap S4). ─────────────────────
    mq = (
        select(
            Message.sent_by_employee_id.label("employee_id"),
            Message.account_id.label("account_id"),
            func.count().label("messages_sent"),
        )
        .where(*await msg_stats.chatter_sends())
    )
    if account_ids is not None:
        mq = mq.where(Message.account_id.in_(account_ids))
    if start:
        mq = mq.where(Message.created_at >= start)
    if end:
        mq = mq.where(Message.created_at <= end)
    if by_account:
        mq = mq.group_by(Message.sent_by_employee_id, Message.account_id)
    else:
        mq = mq.group_by(Message.sent_by_employee_id)

    # ── Q2: each sale credited by its Creator's Agency's Sales Settings
    # rules (sales_attribution; Converters is the attribution view's answer).
    # Nothing is written, so switching a rule back restores the old figures.

    # Each task opens its OWN AsyncSession — a single AsyncSession is not
    # safe for concurrent execute() under asyncio.gather (raises
    # IllegalStateChangeError); the engine's pool hands one connection
    # per task and SQLite WAL handles parallel readers fine.
    async def _run(stmt: Any) -> list[Any]:
        async with get_session() as ss:
            return (await ss.execute(stmt)).all()

    # Label lookup only — display_name isn't sensitive and the actual
    # data isolation already happened via `clamp_account_filter` above
    # (messages/transactions are scoped to the principal's accounts).
    # Filtering this lookup by user_id used to surface bare "Employee
    # #N" labels in the table whenever a message's sent_by_employee_id
    # pointed at a row outside the principal's roster — typically a
    # chatter mirror Employee created under a co-owner, or a legacy row
    # whose owner is no longer the current user. Lookup-everything keeps
    # the table readable; no rows that weren't already visible become
    # visible, since the data join is account-scoped.
    emp_lookup_q = select(Employee.id, Employee.display_name)
    if by_account:
        acct_lookup_q = select(Account.id, Account.nickname)
        if account_ids is not None:
            acct_lookup_q = acct_lookup_q.where(Account.id.in_(account_ids))
        msg_rows, (credited, fallback), emp_rows, acct_rows = await asyncio.gather(
            _run(mq), credited_sales(account_ids, start, end, grouped=True),
            _run(emp_lookup_q), _run(acct_lookup_q),
        )
        account_labels: dict[str, str | None] = {aid: nick for aid, nick in acct_rows}
    else:
        msg_rows, (credited, fallback), emp_rows = await asyncio.gather(
            _run(mq), credited_sales(account_ids, start, end, grouped=True),
            _run(emp_lookup_q),
        )
        account_labels = {}

    names: dict[int, str | None] = {eid: dname for eid, dname in emp_rows}

    # ── Merge ───────────────────────────────────────────────────────────
    # We key by (employee_id, account_id?) so by_account=True produces a
    # per_account[] list per employee. `None` employee_id is the
    # synthetic "Unattributed" bucket holding standalone-tip orphans.
    by_emp: dict[int | None, dict[str, Any]] = {}

    def _bucket(eid: int | None) -> dict[str, Any]:
        if eid in by_emp:
            return by_emp[eid]
        if eid is None:
            row = _empty_employee_row(None, _UNATTRIBUTED_BUCKET)
        else:
            row = _empty_employee_row(eid, names.get(eid))
        if by_account:
            row["per_account"] = {}
        by_emp[eid] = row
        return row

    def _acct_sub(emp_row: dict[str, Any], aid: str | None) -> dict[str, Any]:
        sub_map: dict[str | None, dict[str, Any]] = emp_row["per_account"]
        if aid in sub_map:
            return sub_map[aid]
        sub_map[aid] = {
            "account_id": aid,
            "account_nickname": account_labels.get(aid) if aid else None,
            "messages_sent": 0,
            "ppv_conversions": 0,
            "revenue_cents": 0,
            "revenue_by_kind": {"ppv": 0, "tip": 0},
        }
        return sub_map[aid]

    # Apply message counts. Messages with sent_by_employee_id IS NULL
    # don't appear here (mq filters them out) — those land in
    # /admin/stats/attribution-coverage, not the per-employee revenue
    # rollup. The Unattributed bucket exists only for orphan tip revenue.
    for r in msg_rows:
        eid = int(r.employee_id)
        emp_row = _bucket(eid)
        emp_row["messages_sent"] += int(r.messages_sent or 0)
        if by_account:
            aid = r.account_id
            sub = _acct_sub(emp_row, aid)
            sub["messages_sent"] += int(r.messages_sent or 0)

    # Credited sales → revenue, PPV conversions and the {ppv, tip} split.
    # None-employee rows feed the synthetic "Unattributed" bucket its real
    # split (orphan PPVs and tips, and whatever a rule leaves Unattributed).
    # ASSUMPTION: each Employee sharing a split PPV sale counts it as one
    # conversion. Rung 6. Overturned if a split sale should count once in all.
    for c in credited:
        is_ppv = c.kind in PPV_KINDS
        ppv_c = c.amount_cents if is_ppv else 0
        tip_c = c.amount_cents if c.kind in TIP_KINDS else 0
        targets = [_bucket(c.employee_id)]
        if by_account:
            targets.append(_acct_sub(targets[0], c.account_id))
        for row in targets:
            row["revenue_cents"] += c.amount_cents
            row["ppv_conversions"] += c.sales if is_ppv else 0
            row["revenue_by_kind"]["ppv"] += ppv_c
            row["revenue_by_kind"]["tip"] += tip_c

    # Flatten per_account map → sorted list (highest revenue first).
    if by_account:
        for emp_row in by_emp.values():
            sub_map: dict[str | None, dict[str, Any]] = emp_row["per_account"]
            emp_row["per_account"] = sorted(
                sub_map.values(),
                key=lambda x: x["revenue_cents"],
                reverse=True,
            )

    rows = [r for r in by_emp.values() if own is None or r["employee_id"] in own]
    out = sorted(rows, key=lambda x: x["revenue_cents"], reverse=True)
    return {"employees": out, "attribution_fallback": fallback}


# The counts of a Chatting statistics row, summed over an Employee's Creators.
_CHAT_COUNTS = ("direct_messages_sent", "direct_ppvs_sent", "ppvs_unlocked", "character_count", "fans_chatted",
                "sales_cents", "ppv_sales_cents", "tip_sales_cents", "direct_message_sales_cents",
                "mass_message_sales_cents", "priority_mass_message_sales_cents", "fans_who_spent", "replies")


def _shown(eid: int | None, auto: int | None, own: set[int] | None) -> bool:
    """Whether Chatting statistics show Employee `eid`'s figures: not the
    Unattributed sales (None), not the Automation sentinel, and only the
    Data scope's own Employees when it narrows (`scoped_employee_ids`)."""
    return eid is not None and eid != auto and (own is None or eid in own)


def _pct(num: float, den: float) -> float | None:
    return round(num * 100.0 / den, 2) if den else None


async def _clocked_minutes(employee_ids: list[int], start: datetime, end: datetime) -> dict[int, int]:
    """Each Employee's Clock events clipped to [start, end], an open one
    running to now, rounded up to the minute: the Timesheet's worked time
    (`shifts_api.timesheet`, no call for this: owner-only, at most 42 days,
    and it reads Shifts too)."""
    if not employee_ids:
        return {}
    now = datetime.utcnow()
    async with get_session() as s:
        events = (await s.execute(
            select(ClockEvent.employee_id, ClockEvent.in_utc, ClockEvent.out_utc)
            .where(ClockEvent.employee_id.in_(employee_ids), ClockEvent.in_utc <= end,
                   or_(ClockEvent.out_utc.is_(None), ClockEvent.out_utc > start)))).all()
    seconds: dict[int, float] = {}
    for eid, lo, hi in events:
        worked = (min(hi or now, end) - max(lo, start)).total_seconds()
        if worked > 0:
            seconds[eid] = seconds.get(eid, 0.0) + worked
    return {eid: minutes_up(sec) for eid, sec in seconds.items()}


@router.get("/admin/stats/chatting-stats")
async def chatting_stats(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    chatter_only: bool = Query(False),
    bucket: str | None = Query(None, pattern="^(hour|day|week|month)$"),
) -> dict[str, Any]:
    """Employee reports' Chatting statistics (roadmap W5 5.2): one row per
    Employee, with the Creators it worked on (`per_account[]`), of Infloww's
    chatting metrics over the window (the last 30 days when unbounded).

      • sales_cents, ppv_sales_cents, tip_sales_cents — the sales credited
        by the Sales Settings rules, as `per_employee`'s revenue
      • direct_message_sales_cents, mass_message_sales_cents,
        priority_mass_message_sales_cents — the sales of the messages
        credited to the Employee, direct, in a mass message or in a Priority
        mass message (`msg_stats.channel_sales`)
      • direct_messages_sent, direct_ppvs_sent, ppvs_unlocked,
        character_count, fans_chatted — its own sends (`msg_stats.send_stats`);
        fans chatted add up each Creator's distinct fans
      • fans_who_spent, avg_spend_per_fan_cents — the fans who paid its
        direct messages or tipped in its chats, and their direct and tip spend
      • replies, avg_reply_seconds — `msg_stats.reply_stats`
      • golden_ratio, unlock_rate, fan_cvr — percentages, null on a zero base
      • clocked_minutes and the per-clocked-hour rates of direct and tip
        sales, messages and fans chatted: null with no clocked time, and
        always null for a chatter, as the Timesheet refuses chatters

    The Automation sentinel and the Unattributed sales get no row. Under
    Role enforcement a chatter whose Data scope is not "all" gets only its
    own row (`permissions.scoped_employee_ids`), as `per_employee`, and
    ``chatter_only=true`` keeps the Chatter role's (`permissions.role_holders`).

    `bucket` (hour, day, week or month) answers the charts instead: the
    window's time series (`_chatting_series`), of every Employee in scope
    and of each."""
    from chatters import get_request_chatter
    from permissions import scoped_employee_ids
    own = await _only_chatters(await scoped_employee_ids(), chatter_only)
    is_chatter = get_request_user() is None and get_request_chatter() is not None
    zone, week_start = await _report_prefs(None)
    end = _parse_date(to, field="to", zone=zone) or datetime.utcnow()
    start = _parse_date(from_, field="from", zone=zone) or end - timedelta(days=30)
    account_ids = clamp_account_filter(None)
    if bucket is not None:
        return await _chatting_series(bucket, start=start, end=end, zone=zone, week_start=week_start, own=own,
                                      account_ids=account_ids)

    async def _read(fn: Any) -> Any:
        async with get_session() as ss:
            return await fn(ss, account_ids=account_ids, start=start, end=end)

    sends, replies, channels, (credited, fallback), auto = await asyncio.gather(
        _read(msg_stats.send_stats), _read(msg_stats.reply_stats), _read(msg_stats.channel_sales),
        credited_sales(account_ids, start, end, grouped=True), msg_stats.automation_id())

    cells: dict[tuple[int, str], dict[str, Any]] = {}

    def _cell(eid: int | None, aid: str) -> dict[str, Any] | None:
        if not _shown(eid, auto, own):
            return None
        return cells.setdefault((int(eid), aid), {**dict.fromkeys(_CHAT_COUNTS, 0), "chat_tip_cents": 0,
                                                  "reply_seconds": 0.0})

    for r in sends:
        if (c := _cell(r.employee_id, r.account_id)) is not None:
            c.update(direct_messages_sent=int(r.messages), direct_ppvs_sent=int(r.ppvs or 0),
                     ppvs_unlocked=int(r.unlocked or 0), character_count=int(r.chars or 0),
                     fans_chatted=int(r.fans))
    for r in replies:
        if (c := _cell(r.employee_id, r.account_id)) is not None:
            c.update(replies=int(r.replies), reply_seconds=float(r.reply_seconds or 0))
    for r in channels:
        if (c := _cell(r.employee_id, r.account_id)) is not None:
            c.update(direct_message_sales_cents=r.direct_cents, mass_message_sales_cents=r.mass_cents,
                     priority_mass_message_sales_cents=r.priority_cents, chat_tip_cents=r.tip_cents,
                     fans_who_spent=r.spenders)
    for cs in credited:
        if (c := _cell(cs.employee_id, cs.account_id)) is not None:
            c["sales_cents"] += cs.amount_cents
            c["ppv_sales_cents"] += cs.amount_cents if cs.kind in PPV_KINDS else 0
            c["tip_sales_cents"] += cs.amount_cents if cs.kind in TIP_KINDS else 0

    emp_ids = sorted({eid for eid, _ in cells})
    async with get_session() as s:
        names = dict((await s.execute(select(Employee.id, Employee.display_name)
                                      .where(Employee.id.in_(emp_ids)))).all()) if emp_ids else {}
        nicks = dict((await s.execute(select(Account.id, Account.nickname)
                                      .where(Account.id.in_({aid for _, aid in cells})))).all()) if cells else {}
    clocked = {} if is_chatter else await _clocked_minutes(emp_ids, start, end)

    by_emp: dict[int, dict[str, Any]] = {}
    for (eid, aid), c in sorted(cells.items(), key=lambda kv: -kv[1]["sales_cents"]):
        row = by_emp.setdefault(eid, {"employee_id": eid, "display_name": names.get(eid), "per_account": [],
                                      **dict.fromkeys(c, 0)})
        for k, v in c.items():
            row[k] += v
        row["per_account"].append({"account_id": aid, "account_nickname": nicks.get(aid)})
    out = []
    for eid, row in by_emp.items():
        tips, seconds = row.pop("chat_tip_cents"), row.pop("reply_seconds")
        spent = row["direct_message_sales_cents"] + tips
        minutes = None if is_chatter else clocked.get(eid, 0)

        def hourly(n: float, minutes: int | None = minutes) -> float | None:
            return round(n * 60 / minutes, 2) if minutes else None
        out.append({
            **row,
            "golden_ratio": _pct(row["direct_ppvs_sent"], row["direct_messages_sent"]),
            "unlock_rate": _pct(row["ppvs_unlocked"], row["direct_ppvs_sent"]),
            "fan_cvr": _pct(row["fans_who_spent"], row["fans_chatted"]),
            "avg_spend_per_fan_cents": spent // row["fans_who_spent"] if row["fans_who_spent"] else None,
            "avg_reply_seconds": round(seconds / row["replies"]) if row["replies"] else None,
            "clocked_minutes": minutes,
            "sales_per_clocked_hour_cents": int(spent * 60 // minutes) if minutes else None,
            "messages_per_clocked_hour": hourly(row["direct_messages_sent"]),
            "fans_chatted_per_clocked_hour": hourly(row["fans_chatted"]),
        })
    out.sort(key=lambda x: x["sales_cents"], reverse=True)
    return {"employees": out, "attribution_fallback": fallback}


# A chart point's figures: Sales, and Message statistics' four lines.
_SERIES = ("sales_cents", "direct_messages_sent", "direct_ppvs_sent", "ppvs_unlocked", "fans_chatted")


def _bucket_allowed(bucket: str, days: int) -> bool:
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


def _range_days(start: datetime, end: datetime) -> int:
    """A report range's calendar days, as the app's `rangeDays`
    (components/stats/chart.tsx): its length in whole days, a millisecond
    added for the end of its last day and a daylight-saving hour either way
    rounded off. Midnights of any zone count alike (October in Europe, 745
    hours, is 31 days)."""
    return round(((end - start).total_seconds() + 0.001) / 86400)


def _bucket_edges(bucket: str, start: datetime, end: datetime, zone: ZoneInfo | None,
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


async def _chatting_series(bucket: str, *, start: datetime, end: datetime, zone: ZoneInfo | None,
                           week_start: str, own: set[int] | None, account_ids: list[str] | None) -> dict[str, Any]:
    """Employee reports' charts (roadmap W5 5.10, Infloww's Overview and
    Employee performance tabs): `series`, one point per `bucket` of the
    report zone, `start` its local wall time ("YYYY-MM-DDTHH:MM"), with
      • sales_cents — the sales credited by the Sales Settings rules, as
        Chatting statistics' Sales (every tracked status, pending too)
      • direct_messages_sent, direct_ppvs_sent, ppvs_unlocked, fans_chatted —
        Chatting statistics' own sends, fans distinct per Creator and
        Employee within the point
    summed over the Employees Chatting statistics show (`_shown`: the Data
    scope's), and `by_employee`, each one's points (no `start`: the same
    buckets in order). Weeks begin on `week_start`. 400 on a granularity the
    range's calendar days do not allow (`_bucket_allowed`)."""
    days = _range_days(start, end)
    if not _bucket_allowed(bucket, days):
        raise HTTPException(status_code=400, detail=f"Shown by {bucket} does not fit a {days}-day range")
    edges = _bucket_edges(bucket, start, end, zone, week_start)
    by = "hour" if tx_rollup.whole_hours(zone, start, end) else "minute"

    async def _sends() -> list[Any]:
        async with get_session() as ss:
            return await msg_stats.send_stats(ss, account_ids=account_ids, start=start, end=end, edges=edges)

    sends, (credited, fallback), auto = await asyncio.gather(
        _sends(), credited_sales(account_ids, start, end, grouped=True, bucket=by), msg_stats.automation_id())
    tz = zone or timezone.utc
    points = [{"start": e.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%Y-%m-%dT%H:%M"),
               **dict.fromkeys(_SERIES, 0)} for e in edges]
    by_emp: dict[int, list[dict[str, int]]] = {}

    def _add(eid: int, i: int, **figures: int) -> None:
        own_points = by_emp.setdefault(eid, [dict.fromkeys(_SERIES, 0) for _ in edges])
        for k, v in figures.items():
            own_points[i][k] += v
            points[i][k] += v
    for r in sends:
        if _shown(r.employee_id, auto, own):
            _add(int(r.employee_id), r.bucket, direct_messages_sent=int(r.messages), direct_ppvs_sent=int(r.ppvs or 0),
                 ppvs_unlocked=int(r.unlocked or 0), fans_chatted=int(r.fans))
    for cs in credited:
        if _shown(cs.employee_id, auto, own) and cs.occurred_at is not None:
            _add(int(cs.employee_id), max(0, bisect.bisect_right(edges, cs.occurred_at) - 1),
                 sales_cents=cs.amount_cents)
    return {"bucket": bucket, "series": points, "by_employee": {str(k): v for k, v in sorted(by_emp.items())},
            "attribution_fallback": fallback}


# ── 5. Attribution coverage ─────────────────────────────────────────

def _coverage_pct(attributed: int, total: int) -> float:
    """Percentage with 1-decimal rounding. 0/0 returns 0.0 — the caller
    decides whether 'no traffic' should be surfaced differently."""
    if total <= 0:
        return 0.0
    return round((attributed / total) * 100.0, 1)


@router.get("/admin/stats/attribution-coverage")
async def attribution_coverage(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
) -> dict[str, Any]:
    """% of outbound messages with `sent_by_employee_id` filled, per account.
    Window defaults to the last 7 days (UTC). Buckets, per §1.3 of the
    attribution plan:

      attributed_to_human       — employees.is_active = 1
      attributed_to_automation  — employees.display_name = 'Automation'
      unattributed_count        — messages.sent_by_employee_id IS NULL

    If migration 0011 (system Automation employee) hasn't run yet the
    automation bucket is forced to 0 and `automation_employee_present`
    is `false` — never crashes."""
    account_ids = clamp_account_filter(account_id)
    zone = await _report_zone(account_id)
    if from_:
        start = _parse_date(from_, field="from", zone=zone)
    else:
        start = datetime.utcnow() - timedelta(days=7)
    if to:
        end = _parse_date(to, field="to", zone=zone)
    else:
        end = datetime.utcnow()

    async with get_session() as s:
        # Tolerant fallback probe — done before the aggregate so we can
        # zero the automation bucket if the seed row is missing.
        auto_present_row = (await s.execute(
            select(Employee.id).where(Employee.display_name == "Automation").limit(1)
        )).first()
        automation_employee_present = auto_present_row is not None

        # LEFT JOIN messages → employees so we can bucket on employee
        # attributes (is_active, display_name) while still counting rows
        # whose sent_by_employee_id is NULL or points at a deleted employee.
        attributed_expr = case((Message.sent_by_employee_id.is_not(None), 1), else_=0)
        human_expr = case(
            (and_(Message.sent_by_employee_id.is_not(None), Employee.is_active == True), 1),  # noqa: E712
            else_=0,
        )
        automation_expr = case((Employee.display_name == "Automation", 1), else_=0)
        unattributed_expr = case((Message.sent_by_employee_id.is_(None), 1), else_=0)

        q = (
            select(
                Message.account_id.label("account_id"),
                func.count().label("outbound_total"),
                func.coalesce(func.sum(attributed_expr), 0).label("attributed_count"),
                func.coalesce(func.sum(human_expr), 0).label("attributed_to_human"),
                func.coalesce(func.sum(automation_expr), 0).label("attributed_to_automation"),
                func.coalesce(func.sum(unattributed_expr), 0).label("unattributed_count"),
            )
            .select_from(Message)
            .outerjoin(Employee, Message.sent_by_employee_id == Employee.id)
            .where(Message.direction == "out")
        )
        if start:
            q = q.where(Message.created_at >= start)
        if end:
            q = q.where(Message.created_at <= end)
        if account_ids is not None:
            q = q.where(Message.account_id.in_(account_ids))
        q = q.group_by(Message.account_id).order_by(Message.account_id)

        rows = (await s.execute(q)).all()

        # Resolve nicknames for the accounts that showed up. Separate
        # lookup keeps the aggregate query unchanged and lets accounts
        # without a row in `accounts` still render (display_name=None).
        acct_ids = [r.account_id for r in rows if r.account_id]
        nickname_by_id: dict[str, str | None] = {}
        if acct_ids:
            nick_rows = (await s.execute(
                select(Account.id, Account.nickname).where(Account.id.in_(acct_ids))
            )).all()
            nickname_by_id = {aid: nick for aid, nick in nick_rows}

    per_account = []
    totals_outbound = 0
    totals_attributed = 0
    for r in rows:
        outbound_total = int(r.outbound_total or 0)
        attributed_count = int(r.attributed_count or 0)
        attributed_to_human = int(r.attributed_to_human or 0)
        attributed_to_automation = (
            int(r.attributed_to_automation or 0) if automation_employee_present else 0
        )
        unattributed_count = int(r.unattributed_count or 0)
        per_account.append({
            "account_id": r.account_id,
            "display_name": nickname_by_id.get(r.account_id),
            "outbound_total": outbound_total,
            "attributed_count": attributed_count,
            "attributed_to_human": attributed_to_human,
            "attributed_to_automation": attributed_to_automation,
            "unattributed_count": unattributed_count,
            "coverage_pct": _coverage_pct(attributed_count, outbound_total),
        })
        totals_outbound += outbound_total
        totals_attributed += attributed_count

    return {
        "from": start.strftime("%Y-%m-%d") if start else None,
        "to": end.strftime("%Y-%m-%d") if end else None,
        "automation_employee_present": automation_employee_present,
        "per_account": per_account,
        "totals": {
            "outbound_total": totals_outbound,
            "coverage_pct": _coverage_pct(totals_attributed, totals_outbound),
        },
    }


@router.get("/admin/stats/attribution-coverage/recent")
async def attribution_coverage_recent(
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """Debugging hook for the coverage endpoint: most-recent outbound
    messages whose `sent_by_employee_id` is NULL. Used to identify which
    code paths are still leaking attribution when coverage_pct drops."""
    account_ids = clamp_account_filter(None)
    async with get_session() as s:
        q = (
            select(
                Message.account_id,
                Message.fan_id,
                Message.message_id,
                Message.created_at,
                Message.body,
                Message.media_count,
            )
            .where(Message.direction == "out", Message.sent_by_employee_id.is_(None))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        if account_ids is not None:
            q = q.where(Message.account_id.in_(account_ids))
        rows = (await s.execute(q)).all()

    return {
        "messages": [
            {
                "account_id": r.account_id,
                "fan_id": int(r.fan_id) if r.fan_id is not None else None,
                "message_id": int(r.message_id) if r.message_id is not None else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "body": (r.body or "")[:80],
                "media_count": int(r.media_count or 0),
            }
            for r in rows
        ]
    }


# ── 6. Per-model KPIs ───────────────────────────────────────────────


def _kind_bucket(kind: str | None) -> str:
    """Collapse Phase F's rich kind vocabulary to the chip buckets the
    per-model card knows about. Without this, `ppv_message`/`ppv_post`/
    `tip_post`/etc. silently fall into `custom` because the response dict
    has no key for them — they go to `custom` in the chips and the PPV
    chip shows $0 even when there is real PPV revenue.

    Feed-post sales (`ppv_post`, `tip_post`) get their own `post` bucket so
    the card can show post revenue separately — these MUST be checked before
    the generic `ppv`/`tip` prefix rules below or they'd fold into those."""
    if not kind:
        return "custom"
    if kind in ("ppv_post", "tip_post"):
        return "post"
    if kind.startswith("ppv"):
        return "ppv"
    if kind.startswith("tip"):
        return "tip"
    if kind == "subscription":
        return "subscription"
    if kind == "rebill":
        return "rebill"
    return "custom"


def _safe_div(num: int, den: int) -> int | None:
    """Integer division returning None when the denominator is 0 — the UI
    distinguishes "no data" from a real zero (a model with no new subs has
    no LTV, not LTV=0)."""
    if den <= 0:
        return None
    return int(num // den)


@router.get("/admin/stats/per-model")
async def per_model(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
    engagement: bool = Query(False),
) -> dict[str, Any]:
    """Per-OF-model KPIs for the stats dashboard. Returns one row per
    account in the window (defaults: last 30 days UTC), sorted by total
    revenue descending.

    Per-model fields:
      • account_id / display_name
      • revenue_by_kind   — {ppv, tip, subscription, rebill, custom}
      • total_revenue_cents
      • messages_sent     — an Employee's own sends, no mass or automated ones
                             (`msg_stats.chatter_sends`)
      • ppvs_sent, fans_chatted — with ``engagement=true`` only (Creator
                             reports): the priced ones among them, and the
                             fans they went to, each once
                             (`msg_stats.creator_sends`)
      • avg_reply_seconds — with ``engagement=true`` only: the Employees'
                             replies' average wait, null with none
                             (`msg_stats.reply_stats`)
      • ppv_conversions
      • new_subs_count    — DISTINCT fans whose subscription began in window,
                             free and trial ones included (see _new_subs_q)
      • active_subs_count — subscribers as of the window's end via
                             subscription_expires_at (see top-level
                             `active_subs_source`)
      • ltv_cents         — total / new_subs OR null
      • arpu_cents        — total / active OR null
      • refunded_cents    — gross of the window's reversals (REVERSED_STATUSES),
                             dated by their sale, as `status=reversed` on the
                             revenue read dates them; refunded_net_cents their
                             OF net
      • spenders_count, avg_spend_per_spender_cents,
        avg_spend_per_transaction_cents — see spenders_q
      • of_visitors, of_renewals, of_new_sub_conversion_pct, of_renew_on,
        of_renew_on_pct   — OnlyFans' Statistics over the window's UTC days
                             (`of_stats_daily.window_figures`), null unless
                             every day is stored

    The heavy sub-queries (money, new-subs, active-subs, messages) run
    concurrently via asyncio.gather to keep p95 latency under 500ms with 30+
    accounts.

    Caveat: `fans.subscription_status` is currently never populated, so we
    fall back to `subscription_expires_at > end`. If THAT column is also
    empty (nothing writes it today), the 31-day transactions fallback
    applies, else `active_subs_count` and `arpu_cents` are null for every
    model and the top-level `active_subs_source` is "unavailable"."""
    account_ids = clamp_account_filter(account_id)
    zone = await _report_zone(account_id)
    if from_:
        start = _parse_date(from_, field="from", zone=zone)
    else:
        start = datetime.utcnow() - timedelta(days=30)
    if to:
        end = _parse_date(to, field="to", zone=zone)
    else:
        end = datetime.utcnow()

    # ── Build the queries ──────────────────────────────────────────────
    # Revenue, pending and PPV conversions by (account, kind, status), one
    # read of the hourly rollup (tx_rollup.window_sums). Revenue reads every
    # kind (the attribution view drops subscription/rebill/custom), counts
    # both cleared and pending (TRACKED_STATUSES); pending is surfaced
    # separately as pending_by_kind (subset, not additional) so the UI can
    # flag what's not yet bank-cleared.
    # `net_cents` rides along with gross so the creators table can reconcile
    # against a Net-basis KPI card. Purely ADDITIVE: it adds top-level keys and
    # moves no money between the existing `revenue_by_kind` buckets — that dict
    # is a closed 6-key TypeScript interface (app/hooks/useStats.ts) consumed by
    # PerModelKpiGrid / PerEmployeeTable / CompetitorReports, and adding a key to
    # IT would silently reroute revenue into a bucket those surfaces never render.
    async def _sums() -> list[Any]:
        async with get_session() as ss:
            return await tx_rollup.window_sums(ss, ("account_id", "kind", "status"), account_ids=account_ids,
                                               start=start, end=end)

    # New subs in window, each fan once (`_new_subs_q`).
    new_fans = _new_subs_q(account_ids, start, end).subquery()
    new_subs_q = (select(new_fans.c.account_id, func.count().label("new_subs"))
                  .group_by(new_fans.c.account_id))
    window = tx_rollup.Binds()
    acct_in = "" if account_ids is None else " AND " + window.in_("account_id", account_ids)
    s_, e_ = window.bind(start.strftime(tx_rollup.TS_FORMAT)), window.bind(end.strftime(tx_rollup.TS_FORMAT))

    # Pending revenue's latest projected clearance per account:
    # max(occurred_at + payout_pending_days) over the pending rows.
    pending_q = text(
        "SELECT account_id, MAX(datetime(occurred_at, printf('%+d days', COALESCE(payout_pending_days, 0)))) "
        f"AS clears FROM transactions WHERE status = 'pending' AND occurred_at >= {s_} AND occurred_at <= {e_}{acct_in} "
        "GROUP BY account_id").bindparams(**window)

    # Q3: active subs snapshot — best available signal.
    # Per DA: `subscription_status` is never written. Use the fallback
    # path on `subscription_expires_at` unconditionally; the response
    # surfaces which source produced the count (or marks it
    # unavailable if expires_at is also empty).
    # Counted as of the window's end, not now, so a past window shows the
    # subscribers it ended with (roadmap S5).
    active_subs_q = select(
        Fan.account_id.label("account_id"),
        func.count().label("active_subs"),
    ).where(
        Fan.subscription_expires_at.is_not(None),
        Fan.subscription_expires_at > end,
        or_(Fan.subscribed_at.is_(None), Fan.subscribed_at <= end),
    )
    if account_ids is not None:
        active_subs_q = active_subs_q.where(Fan.account_id.in_(account_ids))
    active_subs_q = active_subs_q.group_by(Fan.account_id)

    # Q3b: transactions-based active-subs fallback. When
    # fans.subscription_expires_at is empty for every fan (most installs
    # today), derive "active" as DISTINCT fan_id with a cleared
    # subscription / rebill within 31 days of `end` — the period a
    # standard monthly OF sub covers. Multi-month subscribers leak out
    # of this window, so the count slightly under-reports yearly
    # subscribers. Acceptable until the WS pump populates expires_at
    # directly.
    tx_active_subs_q = select(
        Transaction.account_id.label("account_id"),
        func.count(func.distinct(Transaction.fan_id)).label("active_subs"),
    ).where(
        Transaction.kind.in_(("subscription", "rebill")),
        Transaction.status.in_(TRACKED_STATUSES),
        Transaction.fan_id.is_not(None),
        Transaction.occurred_at >= end - timedelta(days=31),
        Transaction.occurred_at <= end,
    )
    if account_ids is not None:
        tx_active_subs_q = tx_active_subs_q.where(Transaction.account_id.in_(account_ids))
    tx_active_subs_q = tx_active_subs_q.group_by(Transaction.account_id)

    # Q4: messages_sent per account: an Employee's own sends (`msg_stats.chatter_sends`).
    messages_q = select(
        Message.account_id.label("account_id"),
        func.count().label("messages_sent"),
    ).where(
        *await msg_stats.chatter_sends(),
        Message.created_at >= start,
        Message.created_at <= end,
    )
    if account_ids is not None:
        messages_q = messages_q.where(Message.account_id.in_(account_ids))
    messages_q = messages_q.group_by(Message.account_id)

    # Q4b, with `engagement` only (Creator reports, roadmap W5 5.3): the same
    # sends' PPVs and fans chatted (each fan once per Creator,
    # `msg_stats.creator_sends`, which counts the messages too), and the
    # replies' count and summed seconds (`msg_stats.reply_stats`).
    async def _messages() -> list[Any]:
        if not engagement:
            return await _run(messages_q)
        async with get_session() as ss:
            return await msg_stats.creator_sends(ss, account_ids=account_ids, start=start, end=end)

    async def _replies() -> list[Any]:
        if not engagement:
            return []
        async with get_session() as ss:
            return await msg_stats.reply_stats(ss, account_ids=account_ids, start=start, end=end)

    # Infloww's spender columns, from the ledger rows (a distinct fan count no
    # rollup keeps): the fans who bought content or tipped (REVENUE_KINDS, so a
    # subscription-only fan is no spender) and their spend on it, over them and
    # over their sales ("Average amount spent by each fan that purchased
    # content or gave tips", "... each time by fans on content or tips").
    spenders_q = select(
        Transaction.account_id.label("account_id"),
        func.count(func.distinct(Transaction.fan_id)).label("spenders"),
        func.sum(Transaction.amount_cents).label("cents"),
        func.count().label("sales"),
    ).where(
        Transaction.kind.in_(REVENUE_KINDS),
        Transaction.status.in_(TRACKED_STATUSES),
        Transaction.fan_id.is_not(None),
        Transaction.occurred_at >= start,
        Transaction.occurred_at <= end,
    )
    if account_ids is not None:
        spenders_q = spenders_q.where(Transaction.account_id.in_(account_ids))
    spenders_q = spenders_q.group_by(Transaction.account_id)

    # Run the heavy queries concurrently. AsyncSession is NOT safe to
    # share across `await` points (sa.exc.IllegalStateChangeError), so
    # each task opens its OWN session — the engine's connection pool
    # hands out one connection per task. SQLite WAL handles the parallel
    # readers fine and we keep the latency win.
    async def _run(stmt: Any) -> list[Any]:
        async with get_session() as ss:
            return (await ss.execute(stmt)).all()

    # pending_q failing must NOT 500 the dashboard — fall back to empty.
    async def _run_pending(stmt: Any) -> list[Any]:
        try:
            return await _run(stmt)
        except Exception:
            log.warning("per-model pending_q failed; reporting 0 pending", exc_info=True)
            return []

    r_sums, r_new, r_act, r_act_tx, r_msg, r_reply, r_pending, r_spend, r_of, (of_cells, _) = await asyncio.gather(
        _sums(),
        _run(new_subs_q),
        _run(active_subs_q),
        _run(tx_active_subs_q),
        _messages(),
        _replies(),
        _run_pending(pending_q),
        _run(spenders_q),
        of_stats_daily.window_figures(account_ids, start, end),
        of_stats_daily.earnings_window(account_ids, start, end),
    )

    # Account labels — single query, separate from the heavy aggregates.
    # Clamp by `account_ids` (not the bare query-param `account_id`) so the
    # seed loop below only materializes cards the principal is allowed to
    # see. Without this, a chatter/owner with 15 accounts would still get
    # a card for every account in the DB (most all-zeros).
    async with get_session() as s:
        acct_q = select(Account.id, Account.nickname)
        if account_ids is not None:
            acct_q = acct_q.where(Account.id.in_(account_ids))
        acct_rows = (await s.execute(acct_q)).all()

    # Pick the best active-subs source. Preferred path is
    # Fan.subscription_expires_at (a real expiry); fallback is the
    # 31-day transactions heuristic (Q3b); if neither has any signal we
    # mark the column unavailable so the UI renders "—" instead of a
    # misleading 0.
    expires_at_signal = any(int(r.active_subs or 0) > 0 for r in r_act)
    tx_signal = any(int(r.active_subs or 0) > 0 for r in r_act_tx)
    if expires_at_signal:
        active_subs_source: str = "subscription_expires_at"
    elif tx_signal:
        active_subs_source = "transactions_31d"
        r_act = r_act_tx
    else:
        active_subs_source = "unavailable"

    # ── Pivot rows by account_id ───────────────────────────────────────
    by_acct: dict[str, dict[str, Any]] = {}

    def _ensure(aid: str) -> dict[str, Any]:
        if aid in by_acct:
            return by_acct[aid]
        row: dict[str, Any] = {
            "account_id": aid,
            "display_name": None,
            "revenue_by_kind": {
                "ppv": 0,
                "post": 0,
                "tip": 0,
                "subscription": 0,
                "rebill": 0,
                "custom": 0,
            },
            "pending_by_kind": {
                "ppv": 0,
                "post": 0,
                "tip": 0,
                "subscription": 0,
                "rebill": 0,
                "custom": 0,
            },
            "total_revenue_cents": 0,
            # OF's own post-fee figure, summed from transactions.net_cents.
            # `net_missing_count` > 0 means some rows have no net yet (a
            # WS-pumped sale the ledger has not backfilled) — the UI must
            # disclose that rather than treat the sum as complete.
            "total_net_revenue_cents": 0,
            "net_missing_count": 0,
            "messages_sent": 0,
            "ppv_conversions": 0,
            "new_subs_count": 0,
            "active_subs_count": None if active_subs_source == "unavailable" else 0,
            "ltv_cents": None,
            "arpu_cents": None,
            "pending_revenue_cents": 0,
            "pending_clears_by": None,
            "refunded_cents": 0,
            "refunded_net_cents": 0,
            "spenders_count": 0,
            "avg_spend_per_spender_cents": None,
            "avg_spend_per_transaction_cents": None,
            "of_visitors": None,
            "of_renewals": None,
            "of_new_sub_conversion_pct": None,
            "of_renew_on": None,
            "of_renew_on_pct": None,
        }
        if engagement:
            row.update(ppvs_sent=0, fans_chatted=0, avg_reply_seconds=None)
        by_acct[aid] = row
        return row

    # Seed with every known account so models with zero traffic still show.
    nickname_by_id: dict[str, str | None] = {aid: nick for aid, nick in acct_rows}
    for aid in nickname_by_id:
        row = _ensure(aid)
        row["display_name"] = nickname_by_id[aid]

    for r in r_sums:
        row = _ensure(r.account_id)
        bucket = _kind_bucket(r.kind)
        amount = int(r.gross_cents or 0)
        if r.status in TRACKED_STATUSES:
            row["revenue_by_kind"][bucket] += amount
            row["total_revenue_cents"] += amount
            row["total_net_revenue_cents"] += int(r.net_cents or 0)
            row["net_missing_count"] += int(r.net_missing or 0)
            # PPV conversions: every tracked PPV sale in the window (a
            # re-purchase is a separate sale), the attribution view's rows.
            if r.kind in PPV_KINDS:
                row["ppv_conversions"] += int(r.sales or 0)
        # Pending is a subset of the revenue above: a reversal never clears.
        if r.status == "pending":
            row["pending_revenue_cents"] += amount
            row["pending_by_kind"][bucket] += amount
        if r.status in REVERSED_STATUSES:
            row["refunded_cents"] += amount
            row["refunded_net_cents"] += int(r.net_cents or 0)

    # OnlyFans' own figure where it is over the ledger's (`_of_top_ups`, as
    # /admin/stats/revenue reads it). Pending, refunds and PPV conversions stay
    # the ledger's (OF charts none of them).
    if of_cells:
        async with get_session() as ss:
            top = await _of_top_ups(ss, of_cells, ("account_id",))
        for c in top:
            row = _ensure(c["account_id"])
            row["revenue_by_kind"][_kind_bucket(c["kind"])] += c["gross_cents"]
            row["total_revenue_cents"] += c["gross_cents"]
            row["total_net_revenue_cents"] += c["net_cents"]

    for r in r_new:
        row = _ensure(r.account_id)
        row["new_subs_count"] = int(r.new_subs or 0)

    if active_subs_source != "unavailable":
        for r in r_act:
            row = _ensure(r.account_id)
            row["active_subs_count"] = int(r.active_subs or 0)

    for r in r_msg:
        if engagement:
            _ensure(r.account_id).update(messages_sent=int(r.messages), ppvs_sent=int(r.ppvs or 0),
                                         fans_chatted=int(r.fans))
        else:
            _ensure(r.account_id)["messages_sent"] = int(r.messages_sent or 0)

    replies: dict[str, list[float]] = {}
    for r in r_reply:
        acc = replies.setdefault(r.account_id, [0, 0.0])
        acc[0] += int(r.replies)
        acc[1] += float(r.reply_seconds or 0)
    for aid, (n, seconds) in replies.items():
        if n:
            _ensure(aid)["avg_reply_seconds"] = round(seconds / n)

    for r in r_pending:
        if r.clears is not None:
            _ensure(r.account_id)["pending_clears_by"] = r.clears[:10]

    for r in r_spend:
        row = _ensure(r.account_id)
        row["spenders_count"] = int(r.spenders)
        row["avg_spend_per_spender_cents"] = _safe_div(int(r.cents or 0), int(r.spenders))
        row["avg_spend_per_transaction_cents"] = _safe_div(int(r.cents or 0), int(r.sales))

    for aid, figures in r_of.items():
        _ensure(aid).update(figures)

    for row in by_acct.values():
        row["ltv_cents"] = _safe_div(row["total_revenue_cents"], row["new_subs_count"])
        active = row["active_subs_count"]
        row["arpu_cents"] = (
            _safe_div(row["total_revenue_cents"], active)
            if isinstance(active, int) else None
        )

    per_model_rows = sorted(
        by_acct.values(),
        key=lambda x: x["total_revenue_cents"],
        reverse=True,
    )

    return {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "active_subs_source": active_subs_source,
        "per_model": per_model_rows,
    }


# ── 7. Attribution orphans (debug) ──────────────────────────────────


# ── 9. Sales records ────────────────────────────────────────────────

# One Sales record, in order: the JSON row's keys and the CSV header.
SALES_RECORD_FIELDS = (
    "tx_id", "occurred_at", "employee_id", "employee_name", "account_id", "fan_id", "fan_label",
    "earnings_cents", "gross_cents", "net_cents", "kind", "rule", "assigned_by", "status",
)


# Who a `sales.reassign` action's actor reads as in "Assigned by" (ticket 34).
_REASSIGN_ACTORS = {"owner": "Owner", "master": "Master"}


def _assigned_by(rule: str, reassign_payload: str | None, override_id: int | None) -> str:
    """"Auto" for rule-based credit; for an override, who set it, read only
    from the sale's latest `sales.reassign` action (never the audit
    middleware's generic row) and only while that action's new Employee is
    still the override (`override_id`, `transactions.attributed_employee_id`),
    else "Manual": an override set before reassigns were recorded, or since
    by a writer that recorded none (the former ingest orphan sweep,
    attribution_backfill's history, filled empty overrides).

    ASSUMPTION: the Master reads as "Master", not by name: the payload names
    its actor `master:<users.id>`, and the page shows no owner names. Rung 5.
    Overturned if the Master's username should be shown."""
    if rule != "manual":
        return "Auto"
    if not reassign_payload:
        return "Manual"
    entry = json.loads(reassign_payload)
    if entry["after"]["employee_id"] != override_id:
        return "Manual"
    # The reassign route writes only `owner:<id>` and `master:<id>`.
    return _REASSIGN_ACTORS[entry["actor"].split(":", 1)[0]]


def _sales_record(r: Any, employee_id: int | None, cents: int, rule: str) -> dict[str, Any]:
    """One credited share of sale `r`: the Employee, amount and rule
    `sales_attribution.credit` gave it (`employee_name` is filled per batch,
    `_named`)."""
    return {
        "tx_id": int(r.tx_id),
        "occurred_at": r.occurred_at.isoformat() + "Z",
        "employee_id": employee_id,
        "employee_name": None,
        "account_id": r.account_id,
        "fan_id": int(r.fan_id) if r.fan_id is not None else None,
        "fan_label": r.of_display_name or (f"@{r.of_username}" if r.of_username else None),
        "earnings_cents": cents,
        "gross_cents": int(r.amount_cents),
        "net_cents": int(r.net_cents) if r.net_cents is not None else None,
        "kind": r.kind,
        "rule": rule,
        "assigned_by": _assigned_by(rule, r.reassign_payload, r.override_id),
        "status": r.status,
    }


@router.get("/admin/stats/sales-records", response_model=None)
async def sales_records(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: list[str] | None = Query(None),
    employee_id: list[int] | None = Query(None),
    group_id: int | None = Query(None),
    kind: list[str] | None = Query(None),
    assigned: str = Query("all", pattern="^(all|assigned|unassigned)$"),
    before_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> dict[str, Any] | StreamingResponse:
    """Sales records (docs/spec/phase-05-remaining-parity-gaps.md, item 3):
    one row per credited share of each sale Employee reports count, newest
    first: the sale credited by its Agency's Sales Settings exactly as
    Employee reports credit it (`sales_attribution.credit`, roadmap S7), so a
    Shift schedule split is one row per Employee and a sale "Exclude welcome
    messages" drops is not listed. Each row has the credited Employee, the
    `rule` that chose it (`manual`, `message`, `converters`, `shift` or
    `unassigned`; a "No one" override is `manual` with no Employee),
    "Assigned by" ("Auto" for rule-based credit; for an override "Owner"
    or "Master" from its latest `sales.reassign` action while it still
    names the override, else "Manual"; `_assigned_by`), and
    `earnings_cents`, the share Employee reports add up (net of the fee
    under "Exclude the 20% OnlyFans fee"), beside the sale's `gross_cents`
    and OnlyFans' `net_cents`.

    Filters: `from`/`to` (bare dates in the Agency's report time zone, as
    every report), `account_id*`, `employee_id*`, `group_id` (the sales
    credited to the Employees placed in that Employee group; another
    Agency's or a missing group is 404), `kind*` and `assigned` (Infloww's three-way filter: `all`, `assigned`
    rows that credit an Employee, `unassigned` rows that credit nobody, "No one" included). JSON pages by `before_id` (the last row's `tx_id`;
    `next_before_id` is null on the last page; an id outside the requested
    Creators gives an empty page). `format=csv` streams the whole filtered
    set instead, ignoring `limit` and `before_id`, read inside the response
    generator as `/admin/paid-messages` does (messages.py): `X-Row-Count`
    carries the row cap (`csv_export.CSV_MAX_ROWS`, 50,000), an upper bound
    sent before the body rather than the exact count, and a file that hits
    the cap ends in a TRUNCATED line.

    Phase 1's Agency context answers 401 with no session (whatever
    ALLOW_ANONYMOUS_ADMIN says). Rows are the caller's own Creators
    (`clamp_account_filter`); a named Creator outside them, another Agency's
    or unknown, is 404. Under Role enforcement a chatter whose Data scope is
    not "all" sees only its own Employee's sales, or with "Self and
    subordinates" also those of the Employees in the groups below its own
    (`permissions.scoped_employee_ids`); with it off, the Employee reports
    scope holds.

    ASSUMPTION: `group_id` keeps the Employees placed in that group itself,
    not those of its sub-groups, as the Manage employees rail filters to one
    group. Rung 5. Overturned if the owner wants a group to include its
    sub-groups' sales.

    ASSUMPTION: the Data scope is read across every Agency the chatter is
    linked to, the named Creator unread, as Employee reports reads it
    (`scoped_employee_ids`). Rung 4: never wider than a stored scope.
    Needs-the-human: `scoped_employee_ids` says to revisit "if per_employee
    gains a Creator filter", and this route has one (`account_id*`); reading
    every linked Agency is only ever narrower than following the named
    Creator's Agency. Overturned if the scope should follow the named
    Creator's Agency alone.

    ASSUMPTION: a single foreign `?account_id=` is refused 403 by the account
    isolation middleware (server.py) before this route's 404 runs; spec story
    55 allows 403/404 across Agencies. Rung 1 (the gate is in the code).
    Overturned if every cross-Agency Creator id must answer 404 alone.

    ASSUMPTION: rows are ordered newest first by `occurred_at`, ties by the
    higher `tx_id`, and `before_id` resumes after that sale's place in the
    order (not `tx_id < before_id`), so the Date & time column reads in
    order. Rung 5. Overturned if a cursor must be a bare id comparison.

    ASSUMPTION: a JSON page ends on a whole sale, so a page can run past
    `limit` by the rest of a split sale's shares, and `before_id` stays a
    sale id. Rung 5. Overturned if a page must hold exactly `limit` rows."""
    from employees import agency_contexts
    from permissions import scoped_employee_ids

    contexts = await agency_contexts()
    visible = clamp_account_filter(None) or []
    accounts = list(dict.fromkeys(account_id)) if account_id else list(visible)
    if any(a not in visible for a in accounts):
        raise HTTPException(status_code=404, detail="creator not found")
    if group_id is not None:
        async with get_session() as s:
            group = await s.get(EmployeeGroup, group_id)
        if group is None or group.agency_user_id not in {c.agency_user_id for c in contexts}:
            raise HTTPException(status_code=404, detail="group not found")
    own = await scoped_employee_ids()
    zone = await _report_zone(accounts[0] if account_id and len(accounts) == 1 else None)
    start = _parse_date(from_, field="from", zone=zone)
    end = _parse_date(to, field="to", zone=zone)

    t = Transaction
    # The latest `sales.reassign` action for a manual row only; matching on
    # the sale's Creator lets ix_actions_account_at narrow the audit table.
    # ASSUMPTION: this per-row subquery scans the Creator's whole audit
    # history (only (account_id, at) is indexed), once per manual row, so a
    # 50,000-row CSV of mostly overridden sales may be slow. Rung 5: no
    # migration for an unmeasured cost. Needs-the-human: if it is slow, the
    # fix is an index on actions (action, target_id). Overturned by a
    # measured slow Sales records read or Export.
    reassign = (
        select(Action.payload_json)
        .where(Action.account_id == t.account_id, Action.action == "sales.reassign",
               Action.target_type == "transaction", Action.target_id == cast(t.id, String))
        .order_by(Action.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    q = (
        select(t.id.label("tx_id"), t.occurred_at, t.account_id, t.fan_id, t.amount_cents, t.net_cents, t.kind,
               t.status, t.message_id, t.credit_employee_id, t.credit_rule, t.credit_automation_kind,
               t.credit_sender_id, t.credit_converter_id, t.credit_converter_at,
               Fan.of_display_name, Fan.of_username,
               case((t.credit_rule == "manual", reassign), else_=None).label("reassign_payload"),
               t.attributed_employee_id.label("override_id"))
        .select_from(t)
        .outerjoin(Fan, and_(Fan.account_id == t.account_id, Fan.fan_id == t.fan_id))
        .where(t.account_id.in_(accounts), t.status.in_(TRACKED_STATUSES), t.kind.in_(CREDITED_KINDS))
    )
    if start:
        q = q.where(t.occurred_at >= start)
    if end:
        q = q.where(t.occurred_at <= end)
    if kind:
        q = q.where(t.kind.in_(kind))
    q = q.order_by(t.occurred_at.desc(), t.id.desc())
    if format != "csv" and before_id is not None:
        # The cursor sale must be one of the requested Creators', so another
        # Agency's id reveals nothing about when its sales happened.
        cursor = aliased(Transaction)
        at = (select(cursor.occurred_at)
              .where(cursor.id == before_id, cursor.account_id.in_(accounts))
              .scalar_subquery())
        q = q.where(or_(t.occurred_at < at, and_(t.occurred_at == at, t.id < before_id)))

    # The Employees a share may credit: every filter naming some, intersected.
    wanted: set[int] | None = None
    async with get_session() as s:
        ctx = await credit_context(s, accounts, start, end)
        members = None if group_id is None else set(
            (await s.execute(select(Employee.id).where(Employee.group_id == group_id))).scalars())
    for keep in (set(employee_id) if employee_id else None, members, own):
        if keep is not None:
            wanted = keep if wanted is None else wanted & keep
    if wanted is not None:
        # A share credits the sale's materialised Employee, its linked
        # message's sender (Message sender), its converter candidate (a
        # Converters window other than the default), or under Shift schedule
        # whoever was on the clock (`credit`).
        q = q.where(or_(t.credit_employee_id.in_(wanted), t.credit_sender_id.in_(wanted),
                        t.credit_converter_id.in_(wanted), t.account_id.in_(ctx.shift_accounts)))

    def _records(r: Any) -> list[dict[str, Any]]:
        """Sale `r`'s shares the filters keep, one record each."""
        return [_sales_record(r, eid, cents, rule) for eid, cents, rule in credit_row(ctx, r)
                if (wanted is None or eid in wanted)
                and assigned in ("all", "unassigned" if eid is None else "assigned")]

    names: dict[int, str | None] = {}

    async def _named(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """`recs` with their Employees' names, read for the ids not read yet."""
        if new := {r["employee_id"] for r in recs} - names.keys() - {None}:
            names.update(dict.fromkeys(new))
            async with get_session() as ns:
                names.update((await ns.execute(
                    select(Employee.id, Employee.display_name).where(Employee.id.in_(new)))).tuples().all())
        for rec in recs:
            rec["employee_name"] = names.get(rec["employee_id"])
        return recs

    if format != "csv":
        # A page ends on a whole sale: a split sale's shares are never parted.
        page: list[dict[str, Any]] = []
        more = False
        async with get_session() as s:
            async for r in await s.stream(q.execution_options(yield_per=limit + 1)):
                recs = _records(r)
                if recs and len(page) >= limit:
                    more = True
                    break
                page += recs
        return {"rows": await _named(page), "next_before_id": page[-1]["tx_id"] if more else None}

    async def _all_records(s):
        batch: list[dict[str, Any]] = []
        async for r in await s.stream(q.execution_options(yield_per=500)):
            batch += _records(r)
            if len(batch) >= 500:
                for rec in await _named(batch):
                    yield rec
                batch = []
        for rec in await _named(batch):
            yield rec

    safe = csv_export.safe_filename_part
    return csv_export.download(
        f"sales-records_{safe(from_, 'start')}_to_{safe(to, 'now')}.csv", _all_records, SALES_RECORD_FIELDS,
        lambda rec: ["" if rec[k] is None else rec[k] for k in SALES_RECORD_FIELDS],
    )


# ── Excel export ────────────────────────────────────────────────────

# The widest report export is a few dozen columns; this bounds the workbook built in memory.
XLSX_MAX_CELLS = 1_000_000


class XlsxExport(BaseModel):
    sheet: str = "Report"
    rows: list[list[str | int | float | None]]


@router.post("/admin/stats/xlsx", response_model=None)
async def xlsx_export(body: XlsxExport) -> Response:
    """The reports' Excel export (roadmap W5 5.9): Creator reports and
    Employee reports build the rows from the reads already on screen
    (app/lib/reportExport.ts) and this writes them as a one-sheet .xlsx with
    the standard library (`xlsx_io.write_xlsx`), so the app ships no Excel
    library. It reads nothing: the answer holds only the rows sent. Numbers
    stay number cells; an empty cell is null. Behind the reports' page grant
    and the "export" Function permission (permissions.py)."""
    if len(body.rows) > csv_export.CSV_MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"at most {csv_export.CSV_MAX_ROWS} rows")
    if any(len(row) > xlsx_io.MAX_COLS for row in body.rows):
        raise HTTPException(status_code=413, detail=f"at most {xlsx_io.MAX_COLS} cells a row")
    if sum(len(row) for row in body.rows) > XLSX_MAX_CELLS:
        raise HTTPException(status_code=413, detail=f"at most {XLSX_MAX_CELLS} cells")
    data = xlsx_io.write_xlsx([["" if v is None else v for v in row] for row in body.rows], body.sheet)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="report.xlsx"', "Cache-Control": "no-store"})
