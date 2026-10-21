#!/usr/bin/env python3
"""
/admin/stats/revenue — response contract, status parity, net basis, day+kind.

This endpoint shipped 2026-05-22 and had **zero tests** until this file. That
absence is why "the response is byte-identical for existing callers" was an
argued claim rather than an enforced one — eleven call sites across two
frontends read it, and nothing checked their shape.

The file is deliberately split in two halves:

  PINNING — the four cases that describe the endpoint as it was BEFORE this
  work. They must pass against the unmodified stats.py (that is the receipt
  for "byte-identical") and must KEEP passing afterwards. If one of these
  breaks, an existing caller breaks with it.

      case_day_shape             exact key set + one row per day, kind is None
      case_kind_shape            exact key set + one row per kind, desc by total
      case_account_filter        account_id narrows to one account
      case_bare_to_is_inclusive  `to=YYYY-MM-DD` covers through 23:59:59

  BEHAVIOUR — the cases this work adds. They were RED before the change.

      case_status_filter_excludes_reversals   chargedback/refund_pending are
          not earnings. Before: revenue() had no status predicate at all while
          per-model filtered ("cleared","pending"), so the KPI card and the
          creators table on the same screen summed different row sets and could
          never reconcile.
      case_all_pending_window_is_not_zero     the guard against "correcting"
          the filter to cleared-only. Every transaction in a current week is
          written `pending` and clears later; a cleared-only filter renders the
          default dashboard view $0.00.
      case_revenue_reconciles_with_per_model  the acceptance criterion of the
          whole task, as code.
      case_include_net_sums_of_net            net comes from OF's own per-row
          `net_cents`, not gross x 0.8.
      case_net_null_is_disclosed_not_imputed  a WS-pumped row lands before the
          ledger backfills net. Never COALESCE it to amount_cents (that labels
          gross as net); report a count instead.
      case_by_kind_nested                     the combined day+kind mode nests
          kinds under each day rather than emitting N flat rows per day.
      case_by_kind_absent_is_byte_identical   the flag creates no key when off.
      case_by_kind_rejects_group_by_kind      an unsatisfiable flag combination
          is a 400, not a silent no-op.
      case_status_reversed_reads_reversals    `status=reversed` reads the
          chargebacks and refunds (Creator reports' Chargebacks chart).
      case_per_model_refunds_not_pending      per-model's Refunds figure, and a
          reversal is never pending revenue.
      case_hour_of_week_folds_into_zone       the Earnings heatmap's weekday x
          hour read, in the report zone (whole-hour and part-hour zones).

Run: ./venv/bin/python service/tests/test_stats_revenue.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, text  # noqa: E402

import stats  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Transaction  # noqa: E402


async def _create_attribution_view() -> None:
    """per_model() reads `per_employee_revenue_with_attribution`, which is a SQL
    VIEW created by alembic — and the harness bootstraps with create_all(), which
    creates tables only. Load the migration's own SQL so the test uses the real
    definition rather than a hand-copied one that could drift from it."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(
        here, "db", "migrations", "versions", "20260710_0200_attr_view_orphan_rows.py"
    )
    spec = importlib.util.spec_from_file_location("mig_attr_view", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    async with get_session() as s:
        await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
        await s.execute(text(mig._NEW_VIEW_SQL))
        await s.commit()

A1 = "1000001"
A2 = "1000002"

# The exact key set every row of the legacy day/kind responses carries. Pinned
# as a set so an accidental extra key is a failure, not a silent addition.
LEGACY_KEYS = {"day", "kind", "total_cents", "count"}


def _tx(account_id, kind, cents, when, status="cleared", net=None):
    """A ledger row. `net` defaults to OF's real-world shape (gross - 20% fee);
    pass net=None explicitly via NO_NET to model a not-yet-backfilled WS row."""
    return Transaction(
        account_id=account_id,
        kind=kind,
        amount_cents=cents,
        occurred_at=datetime.fromisoformat(when),
        status=status,
        net_cents=(cents * 8 // 10) if net is _DEFAULT else net,
        fee_cents=(cents - (cents * 8 // 10)) if net is _DEFAULT else None,
        currency="USD",
        source="ledger",
    )


class _Default:
    pass


_DEFAULT = _Default()


def _seed():
    async def go():
        async with get_session() as s:
            s.add(Account(id=A1, nickname="Alpha"))
            s.add(Account(id=A2, nickname="Beta"))
            rows = [
                # ── A1, 2026-07-01 — two kinds, both counted
                _tx(A1, "ppv_message", 10_000, "2026-07-01T09:00:00", net=_DEFAULT),
                _tx(A1, "tip", 2_500, "2026-07-01T18:30:00", net=_DEFAULT),
                # ── A1, 2026-07-02 — one kind, plus the reversals
                _tx(A1, "ppv_message", 5_000, "2026-07-02T12:00:00", net=_DEFAULT),
                # money that LEFT: must not count as earnings once filtered
                _tx(A1, "ppv_message", 9_900, "2026-07-02T13:00:00",
                    status="chargedback", net=_DEFAULT),
                _tx(A1, "tip", 1_100, "2026-07-02T14:00:00",
                    status="refund_pending", net=_DEFAULT),
                # a row at the very end of the last day — proves `to` inclusivity
                _tx(A1, "subscription", 500, "2026-07-02T23:59:58", net=_DEFAULT),
                # ── A2 — separate account, so the account filter has something to exclude
                _tx(A2, "rebill", 7_000, "2026-07-01T10:00:00", net=_DEFAULT),
                # ── A2 — a WS-pumped row the ledger has not backfilled net onto yet
                _tx(A2, "ppv_message", 3_000, "2026-07-01T11:00:00", net=None),
            ]
            for r in rows:
                s.add(r)
            await s.commit()
        await _create_attribution_view()

    asyncio.run(go())


_seed()

WIN = {"from_": "2026-07-01", "to": "2026-07-02"}


def _rows(**kw):
    """Call the endpoint function in-process.

    EVERY optional parameter must be passed explicitly. Outside a request
    FastAPI never resolves its `Query(...)` defaults, so an omitted argument
    arrives as a `Query` object — which reaches SQLAlchemy as
    "type 'Query' is not supported", and, worse for the boolean flags, is
    TRUTHY. Omitting `by_kind` here would silently enable it. Production is
    unaffected (FastAPI resolves the defaults per request); this is purely an
    artifact of calling the endpoint function in-process.
    """
    kw = {"account_id": None, "include_net": False, "by_kind": False, "status": "tracked", **WIN, **kw}
    return asyncio.run(stats.revenue(**kw))["rows"]


# ─────────────────────────── PINNING ───────────────────────────


def case_day_shape():
    rows = _rows(group_by="day")
    assert len(rows) == 2, f"one row per day with data, got {rows}"
    for r in rows:
        assert set(r.keys()) == LEGACY_KEYS, f"extra/missing key: {sorted(r.keys())}"
        assert r["kind"] is None, f"day mode must null the kind field: {r}"
        assert isinstance(r["total_cents"], int) and isinstance(r["count"], int), r
    assert [r["day"] for r in rows] == ["2026-07-01", "2026-07-02"], rows
    # Ordered by day ascending — the chart callers plot in array order.
    assert rows[0]["day"] < rows[1]["day"], rows


def case_kind_shape():
    rows = _rows(group_by="kind")
    for r in rows:
        assert set(r.keys()) == LEGACY_KEYS, f"extra/missing key: {sorted(r.keys())}"
        assert r["day"] is None, f"kind mode must null the day field: {r}"
    kinds = [r["kind"] for r in rows]
    assert len(kinds) == len(set(kinds)), f"one row per kind, got {kinds}"
    totals = [r["total_cents"] for r in rows]
    assert totals == sorted(totals, reverse=True), f"kind mode sorts desc: {rows}"


def case_account_filter():
    a1 = sum(r["total_cents"] for r in _rows(group_by="day", account_id=A1))
    a2 = sum(r["total_cents"] for r in _rows(group_by="day", account_id=A2))
    both = sum(r["total_cents"] for r in _rows(group_by="day"))
    assert a1 > 0 and a2 > 0, (a1, a2)
    assert both == a1 + a2, f"unfiltered must equal the sum of the parts: {both} != {a1}+{a2}"


def case_bare_to_is_inclusive():
    """A bare `to` date covers through 23:59:59.999999 of that day.

    The dashboard's segment picker only ever sends bare dates, and its
    Today/Yesterday cases send from == to. If `to` truncated to midnight, every
    such window would silently drop its last (or only) day.
    """
    rows = _rows(group_by="kind", to="2026-07-02")
    subs = [r for r in rows if r["kind"] == "subscription"]
    assert subs, "the 23:59:58 subscription row must be inside a bare `to=2026-07-02`"
    assert subs[0]["total_cents"] == 500, subs


# ────────────────────────── BEHAVIOUR ──────────────────────────


def case_status_filter_excludes_reversals():
    """chargedback + refund_pending are money leaving; they are not earnings.

    Before this change revenue() had NO status predicate while per-model
    filtered to ("cleared","pending") — so the two surfaces on one screen
    summed different rows and could never agree.
    """
    total = sum(r["total_cents"] for r in _rows(group_by="day", account_id=A1))
    # 10_000 + 2_500 + 5_000 + 500 = 18_000; the 9_900 chargeback and the
    # 1_100 refund_pending must be absent.
    assert total == 18_000, f"reversals leaked into the total: {total} (expected 18000)"


def case_all_pending_window_is_not_zero():
    """Guard against 'correcting' the filter to status='cleared'.

    models.py claims `WHERE status='cleared'` is the contract. It is not: the
    ledger writes rows `pending` and clears them ~7 days later, so on the live
    box every transaction in the current week is pending and none is cleared.
    A cleared-only filter renders the dashboard's default view $0.00.
    """
    async def go():
        async with get_session() as s:
            s.add(_tx(A1, "tip", 4_242, "2026-07-05T10:00:00",
                      status="pending", net=_DEFAULT))
            await s.commit()

    asyncio.run(go())
    rows = _rows(group_by="kind", from_="2026-07-05", to="2026-07-05", account_id=A1)
    total = sum(r["total_cents"] for r in rows)
    assert total == 4_242, (
        f"an all-pending window must report its revenue, got {total}. "
        "If this is 0, someone filtered to cleared-only."
    )


def case_revenue_reconciles_with_per_model():
    """The acceptance criterion of the whole task.

    The KPI card reads revenue(); the creators table reads per_model(). They
    must sum the same rows over the same window, or the dashboard contradicts
    itself no matter how the scope is fixed.
    """
    rev = sum(r["total_cents"] for r in _rows(group_by="kind"))
    pm = asyncio.run(stats.per_model(account_id=None, engagement=False, **WIN))
    table = sum(m["total_revenue_cents"] for m in pm["per_model"])
    assert rev == table, f"card {rev} != table {table} — they sum different row sets"


def case_include_net_sums_of_net():
    """Net is OF's own per-row figure, not an assumed percentage.

    On production every row satisfies net == gross - fee, and OF's cut happens
    to be exactly 20% today — which is precisely why a hardcoded x0.8 looks
    validated. Reading net_cents stays correct if OF ever changes the rate.
    """
    rows = _rows(group_by="kind", account_id=A1, include_net=True)
    for r in rows:
        assert "net_cents" in r and "net_missing_count" in r, sorted(r.keys())
    gross = sum(r["total_cents"] for r in rows)
    net = sum(r["net_cents"] for r in rows)
    assert gross == 18_000, gross
    assert net == 14_400, f"expected the seeded 80% net, got {net}"
    # OF's own fee rides along (the Earnings ledger's Platform fee), and VAT: none seeded.
    assert sum(r["fee_cents"] for r in rows) == gross - net, rows
    assert sum(r["vat_cents"] for r in rows) == 0, rows
    # And the legacy shape must NOT carry these keys.
    for r in _rows(group_by="kind", account_id=A1):
        assert set(r.keys()) == LEGACY_KEYS, f"net keys leaked without the flag: {r}"


def case_net_null_is_disclosed_not_imputed():
    """A WS-pumped row arrives before the ledger backfills its net.

    Never COALESCE a null net to amount_cents — that silently labels gross as
    net. Sum what exists and report how many rows are missing.
    """
    rows = _rows(group_by="kind", account_id=A2, include_net=True)
    by_kind = {r["kind"]: r for r in rows}
    ppv = by_kind["ppv_message"]
    assert ppv["total_cents"] == 3_000, ppv
    assert ppv["net_cents"] == 0, f"a null net must not be imputed from gross: {ppv}"
    assert ppv["net_missing_count"] == 1, f"the missing row must be disclosed: {ppv}"
    rebill = by_kind["rebill"]
    assert rebill["net_missing_count"] == 0, rebill


def case_per_model_net_reconciles():
    """The card's NET total must equal the table's, exactly as gross does.

    Without net on per-model, flipping the dashboard's basis to Net would make
    the headline and the creators table disagree by OF's ~20% cut — recreating
    the original complaint in a different basis.
    """
    rev = _rows(group_by="kind", include_net=True)
    card_net = sum(r["net_cents"] for r in rev)
    pm = asyncio.run(stats.per_model(account_id=None, engagement=False, **WIN))
    table_net = sum(m["total_net_revenue_cents"] for m in pm["per_model"])
    assert card_net == table_net, f"net card {card_net} != net table {table_net}"
    # And the missing-net disclosure survives the trip (A2 has one such row).
    assert sum(m["net_missing_count"] for m in pm["per_model"]) == 1, pm["per_model"]


def case_by_kind_nested():
    """Combined day+kind nests kinds under each day.

    A FLAT day-x-kind row list would break two existing callers outright:
    TotalRevenueChart.tsx and dashboard.js's loadTrend both consume with plain
    assignment (`byDay[r.day] = r.total_cents`), not accumulation, so they would
    silently keep only the last kind per day. Nesting makes that impossible and
    matches per-employee's existing `per_account[]` pattern.
    """
    rows = _rows(group_by="day", account_id=A1, by_kind=True)
    assert len(rows) == 2, f"still ONE row per day, not one per (day,kind): {rows}"
    for r in rows:
        assert "by_kind" in r and isinstance(r["by_kind"], list), r
        assert r["kind"] is None, "the parent row keeps the day-mode shape"
        child = sum(c["total_cents"] for c in r["by_kind"])
        assert child == r["total_cents"], (
            f"nested kinds must sum to the day total: {child} != {r['total_cents']}"
        )
        for c in r["by_kind"]:
            assert set(c.keys()) == {"kind", "total_cents", "count"}, sorted(c.keys())
            assert c["kind"] is not None, c
    d1 = rows[0]
    assert {c["kind"] for c in d1["by_kind"]} == {"ppv_message", "tip"}, d1


def case_by_kind_absent_is_byte_identical():
    """The flag must create no key when it is off — the compatibility property."""
    off = _rows(group_by="day", account_id=A1)
    for r in off:
        assert "by_kind" not in r, f"key created without the flag: {r}"
        assert set(r.keys()) == LEGACY_KEYS, sorted(r.keys())


def case_by_kind_rejects_group_by_kind():
    """An unsatisfiable flag combination is a 400, never a silent no-op.

    Silently ignoring by_kind on a kind-grouped query is how contracts rot: the
    caller believes it asked for a second dimension and gets the first.
    """
    try:
        _rows(group_by="kind", by_kind=True)
    except HTTPException as e:
        assert e.status_code == 400, e.status_code
        assert "by_kind" in str(e.detail), e.detail
        return
    raise AssertionError("by_kind=true with group_by=kind must raise 400")


def case_status_reversed_reads_reversals():
    """`status=reversed` sums the chargebacks and refunds, by kind and by the sale's day."""
    by_kind = {r["kind"]: r["total_cents"] for r in _rows(group_by="kind", account_id=A1, status="reversed")}
    assert by_kind == {"ppv_message": 9_900, "tip": 1_100}, by_kind
    days = _rows(group_by="day", account_id=A1, status="reversed")
    assert [(r["day"], r["total_cents"], r["count"]) for r in days] == [("2026-07-02", 11_000, 2)], days


def case_per_model_refunds_not_pending():
    """per-model's `refunded_cents` is the window's reversals; a reversal is not pending revenue."""
    pm = {m["account_id"]: m for m in asyncio.run(stats.per_model(account_id=None, **WIN))["per_model"]}
    assert pm[A1]["refunded_cents"] == 11_000, pm[A1]
    assert pm[A1]["refunded_net_cents"] == 9_900 * 8 // 10 + 1_100 * 8 // 10, pm[A1]
    assert pm[A2]["refunded_cents"] == 0, pm[A2]
    assert pm[A1]["pending_revenue_cents"] == 0, f"a reversal counted as pending: {pm[A1]}"
    assert pm[A1]["pending_clears_by"] is None, pm[A1]


def _slots(zone: str | None, **kw) -> list[tuple[int, int, int]]:
    """`group_by=hour_of_week` for A1 with the report zone `zone`."""
    real = stats._report_zone

    async def fake(_account_id):
        return ZoneInfo(zone) if zone else None

    stats._report_zone = fake
    try:
        rows = _rows(group_by="hour_of_week", account_id=A1, **kw)
    finally:
        stats._report_zone = real
    for r in rows:
        assert set(r) >= {"weekday", "hour", "total_cents", "count"} and "day" not in r, r
    return [(r["weekday"], r["hour"], r["total_cents"]) for r in rows]


def case_hour_of_week_folds_into_zone():
    """The Earnings heatmap's read: each sale at its weekday and hour in the report zone
    (2026-07-01 is a Wednesday, ISO weekday 3)."""
    assert _slots(None) == [(3, 9, 10_000), (3, 18, 2_500), (4, 12, 5_000), (4, 23, 500)]
    # New York, UTC-4 in July: the hours move back four, the window's edges with them.
    assert _slots("America/New_York") == [(3, 5, 10_000), (3, 14, 2_500), (4, 8, 5_000), (4, 19, 500)]
    # Kolkata, UTC+5:30, read by the minute: 18:30 UTC is Thursday's midnight, and the
    # 23:59:58 sale is past the window's local end.
    assert _slots("Asia/Kolkata") == [(3, 14, 10_000), (4, 0, 2_500), (4, 17, 5_000)]
    # The reversals fold the same way.
    assert _slots(None, status="reversed") == [(4, 13, 9_900), (4, 14, 1_100)]


def case_hour_buckets_by_local_hour():
    """Creator reports' Hour (roadmap W5 5.4): one row per hour with sales,
    keyed 'YYYY-MM-DDTHH:00' under `day`, kinds nested as by day; the hours
    sum to the day read. Hour-precision bounds cut the window by the hour."""
    rows = _rows(group_by="hour", account_id=A1, by_kind=True)
    assert [(r["day"], r["total_cents"]) for r in rows] == [
        ("2026-07-01T09:00", 10_000), ("2026-07-01T18:00", 2_500), ("2026-07-02T12:00", 5_000),
        ("2026-07-02T23:00", 500)], rows
    assert rows[0]["by_kind"] == [{"kind": "ppv_message", "total_cents": 10_000, "count": 1}], rows[0]
    days = _rows(group_by="day", account_id=A1)
    assert sum(r["total_cents"] for r in rows) == sum(r["total_cents"] for r in days), (rows, days)
    narrow = _rows(group_by="hour", account_id=A1, from_="2026-07-01T10:00:00Z", to="2026-07-02T12:59:59.999Z")
    assert [r["day"] for r in narrow] == ["2026-07-01T18:00", "2026-07-02T12:00"], narrow


def _rows_in(zone: str, **kw):
    """`_rows` with the Agency's report time zone `zone`."""
    real = stats._report_zone

    async def _zone(_account_id):
        return ZoneInfo(zone)
    stats._report_zone = _zone
    try:
        return _rows(**kw)
    finally:
        stats._report_zone = real


def case_hour_buckets_cut_a_half_hour_zone_by_the_minute():
    """Asia/Kolkata (UTC+5:30): each sale lands in its local hour, read by the
    minute, so 18:30Z opens 2 Jul 00:00 there and 09:00Z is 14:30."""
    rows = _rows_in("Asia/Kolkata", group_by="hour", account_id=A1,
                    from_="2026-07-01T00:00:00Z", to="2026-07-02T23:59:59Z")
    assert [(r["day"], r["total_cents"]) for r in rows] == [
        ("2026-07-01T14:00", 10_000), ("2026-07-02T00:00", 2_500), ("2026-07-02T17:00", 5_000),
        ("2026-07-03T05:00", 500)], rows


def case_hour_buckets_hold_both_runs_of_the_hour_a_daylight_saving_end_repeats():
    """America/New_York's daylight saving ends Sun 1 Nov 2026 at 06:00Z (2 AM
    EDT back to 1 AM EST): 1 AM runs twice, and its bucket holds both, 05:30Z
    and 06:30Z; 07:30Z is 2 AM EST. The local day is 25 hours long."""
    async def _add(rows):
        async with get_session() as s:
            s.add_all(rows)
            await s.commit()
    asyncio.run(_add([_tx(A2, "tip", 100, "2026-11-01T05:30:00", net=_DEFAULT),
                      _tx(A2, "tip", 200, "2026-11-01T06:30:00", net=_DEFAULT),
                      _tx(A2, "tip", 400, "2026-11-01T07:30:00", net=_DEFAULT)]))
    try:
        rows = _rows_in("America/New_York", group_by="hour", account_id=A2, from_="2026-11-01", to="2026-11-01")
        assert [(r["day"], r["total_cents"], r["count"]) for r in rows] == [
            ("2026-11-01T01:00", 300, 2), ("2026-11-01T02:00", 400, 1)], rows
        days = _rows_in("America/New_York", group_by="day", account_id=A2, from_="2026-11-01", to="2026-11-01")
        assert [(r["day"], r["total_cents"]) for r in days] == [("2026-11-01", 700)], days
    finally:
        async def _drop():
            async with get_session() as s:
                await s.execute(delete(Transaction).where(Transaction.occurred_at >= datetime(2026, 11, 1)))
                await s.commit()
        asyncio.run(_drop())


_harness.run(
    case_day_shape,
    case_kind_shape,
    case_account_filter,
    case_bare_to_is_inclusive,
    case_status_filter_excludes_reversals,
    case_all_pending_window_is_not_zero,
    case_revenue_reconciles_with_per_model,
    case_include_net_sums_of_net,
    case_net_null_is_disclosed_not_imputed,
    case_per_model_net_reconciles,
    case_by_kind_nested,
    case_by_kind_absent_is_byte_identical,
    case_by_kind_rejects_group_by_kind,
    case_status_reversed_reads_reversals,
    case_per_model_refunds_not_pending,
    case_hour_of_week_folds_into_zone,
    case_hour_buckets_by_local_hour,
    case_hour_buckets_cut_a_half_hour_zone_by_the_minute,
    case_hour_buckets_hold_both_runs_of_the_hour_a_daylight_saving_end_repeats,
)
