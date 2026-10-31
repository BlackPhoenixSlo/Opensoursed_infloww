"""
stats.py — read-only admin reporting endpoints.

Read paths, all driven by the already-persisted SQLite tables:

  GET /admin/stats/revenue          → transactions, grouped by day or kind
  POST /admin/stats/xlsx            → the reports' Excel export (reads nothing)

Employee reports' per-employee and chatting-stats live in stats_employees.py,
sales-records in stats_sales_records.py, per-model in stats_per_model.py, Fan
reports in stats_fans.py, and grok-cost, grok-calls, per-automation,
automation-runs and attribution-coverage in stats_ops.py; their routers are
included here.

Revenue is derived from rows the ingest path already wrote (event_transcoder
for transactions, kept in the rollups) and OF's own daily figures
(of_stats_daily). We never hit OF here and never recompute counters that
already live denormalized on `fans` / `chats`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

import csv_export
import of_stats_daily
from db.engine import get_session
import of_top_up
import stats_employees
import stats_fans
import stats_ops
import stats_per_model
import stats_sales_records
import stats_window
import tx_rollup
import xlsx_io
from attribution_backfill import REVERSED_STATUSES, TRACKED_STATUSES

# Attribution is read from the row (`transactions.credit_*`) and money from the
# rollups (`tx_daily`, `tx_hourly`), all kept by triggers (tx_rollup.py); the view
# `per_employee_revenue_with_attribution` stays only as their oracle.


# Moved to stats_window.py; the old names stay for the routes below and for
# importers (messages.py and transactions.py `from stats import _parse_date`).
stats_guard = stats_window.stats_guard
_parse_date = stats_window.parse_date
scope_ids = stats_window.scope_ids
# Also moved there; the old names stay for the tests (test_chatting_series.py).
_bucket_allowed = stats_window.bucket_allowed
_range_days = stats_window.range_days
_bucket_edges = stats_window.bucket_edges
# Moved to stats_per_model.py / stats_ops.py; the old names stay for the tests
# (test_of_stats_daily.py, test_stats_revenue.py, test_fansly_revenue.py,
# test_automation_attribution.py).
per_model = stats_per_model.per_model
_kind_bucket = stats_per_model._kind_bucket
per_automation = stats_ops.per_automation


router = APIRouter(dependencies=[Depends(stats_guard)])


# Statuses we count toward revenue. `pending` ("loading" in OF's vocab)
# clears in ~7d so excluding it lags reality by a week — the dashboard
# would underreport an account that's actively earning. Including it
# matches OF's own /statistics page (which counts pending subs the moment
# they fire). If a pending row later flips to `chargedback`/`refunded`
# the next ingest tick updates the row in place and the metric self-
# corrects. `refund_pending` (was cleared, now being returned) is
# excluded — that money is leaving.


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

    ASSUMPTION: the zone applies to the Analytics reports' routes: revenue
    (here), per-automation and attribution-coverage (stats_ops.py), per-model
    (stats_per_model.py), fan-report (stats_fans.py), sales-records
    (stats_sales_records.py), per-employee and chatting-stats
    (stats_employees.py, the latter via `_report_prefs`);
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


# ── Revenue ──────────────────────────────────────────────────────

# `group_by=hour_of_week`'s local slot, "<ISO weekday> <hour>", written by
# `_day_sums(fmt=)` and read back by `_week_slot`.
_WEEK_SLOT = "%u %H"


def _week_slot(slot: str) -> dict[str, int]:
    """A `_WEEK_SLOT` string as `{weekday, hour}`."""
    weekday, hour = slot.split()
    return {"weekday": int(weekday), "hour": int(hour)}


# Moved to of_top_up.py. revenue calls the module global `_of_top_ups` by name and
# per_model (stats_per_model.py) reads `stats._of_top_ups` at call time, so assigning
# `stats._of_top_ups` (slop fault of-zero-erases-db-sale) bites.
_of_top_up_rows = of_top_up.rows_sql
_of_top_ups = of_top_up.top_ups
_plus = of_top_up.plus


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


# Grok cost, Grok calls and per-automation (stats_ops.py), included here so the
# route order holds.
router.include_router(stats_ops.router)


# Per-fan data and Fan reports (stats_fans.py), included here so the route order holds.
router.include_router(stats_fans.router)


# Automation runs (stats_ops.py), included here so the route order holds.
router.include_router(stats_ops.runs_router)


# Per-employee and Chatting statistics (stats_employees.py), included here
# so the route order holds.
router.include_router(stats_employees.router)


# Attribution coverage (stats_ops.py), included here so the route order holds.
router.include_router(stats_ops.coverage_router)


# Per-model KPIs (stats_per_model.py), included here so the route order holds.
router.include_router(stats_per_model.router)


# Sales records (stats_sales_records.py), included here so the route order holds.
router.include_router(stats_sales_records.router)


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
