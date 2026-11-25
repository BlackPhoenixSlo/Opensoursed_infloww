#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

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
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(
        here, "db", "migrations", "versions", "20261027_0100_converters_window.py"
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

LEGACY_KEYS = {"day", "kind", "total_cents", "count"}


def _tx(account_id, kind, cents, when, status="cleared", net=None):
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
                _tx(A1, "ppv_message", 10_000, "2026-07-01T09:00:00", net=_DEFAULT),
                _tx(A1, "tip", 2_500, "2026-07-01T18:30:00", net=_DEFAULT),
                _tx(A1, "ppv_message", 5_000, "2026-07-02T12:00:00", net=_DEFAULT),
                _tx(A1, "ppv_message", 9_900, "2026-07-02T13:00:00",
                    status="chargedback", net=_DEFAULT),
                _tx(A1, "tip", 1_100, "2026-07-02T14:00:00",
                    status="refund_pending", net=_DEFAULT),
                _tx(A1, "subscription", 500, "2026-07-02T23:59:58", net=_DEFAULT),
                _tx(A2, "rebill", 7_000, "2026-07-01T10:00:00", net=_DEFAULT),
                _tx(A2, "ppv_message", 3_000, "2026-07-01T11:00:00", net=None),
            ]
            for r in rows:
                s.add(r)
            await s.commit()
        await _create_attribution_view()

    asyncio.run(go())


_seed()

WIN = {"from_": "2026-07-01", "to": "2026-07-02"}


# Called in-process, FastAPI never resolves Query defaults: an omitted flag arrives as a truthy Query object, so pass every parameter.
def _rows(**kw):
    kw = {"account_id": None, "include_net": False, "by_kind": False, "status": "tracked", **WIN, **kw}
    return asyncio.run(stats.revenue(**kw))["rows"]




def case_day_shape():
    rows = _rows(group_by="day")
    assert len(rows) == 2, f"one row per day with data, got {rows}"
    for r in rows:
        assert set(r.keys()) == LEGACY_KEYS, f"extra/missing key: {sorted(r.keys())}"
        assert r["kind"] is None, f"day mode must null the kind field: {r}"
        assert isinstance(r["total_cents"], int) and isinstance(r["count"], int), r
    assert [r["day"] for r in rows] == ["2026-07-01", "2026-07-02"], rows
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
    rows = _rows(group_by="kind", to="2026-07-02")
    subs = [r for r in rows if r["kind"] == "subscription"]
    assert subs, "the 23:59:58 subscription row must be inside a bare `to=2026-07-02`"
    assert subs[0]["total_cents"] == 500, subs




def case_status_filter_excludes_reversals():
    total = sum(r["total_cents"] for r in _rows(group_by="day", account_id=A1))
    assert total == 18_000, f"reversals leaked into the total: {total} (expected 18000)"


# Pending rows are earnings: the ledger clears them ~7 days later, so a cleared-only filter shows the current week as $0.00.
def case_all_pending_window_is_not_zero():
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
    rev = sum(r["total_cents"] for r in _rows(group_by="kind"))
    pm = asyncio.run(stats.per_model(account_id=None, engagement=False, **WIN))
    table = sum(m["total_revenue_cents"] for m in pm["per_model"])
    assert rev == table, f"card {rev} != table {table} — they sum different row sets"


def case_include_net_sums_of_net():
    rows = _rows(group_by="kind", account_id=A1, include_net=True)
    for r in rows:
        assert "net_cents" in r and "net_missing_count" in r, sorted(r.keys())
    gross = sum(r["total_cents"] for r in rows)
    net = sum(r["net_cents"] for r in rows)
    assert gross == 18_000, gross
    assert net == 14_400, f"expected the seeded 80% net, got {net}"
    assert sum(r["fee_cents"] for r in rows) == gross - net, rows
    assert sum(r["vat_cents"] for r in rows) == 0, rows
    for r in _rows(group_by="kind", account_id=A1):
        assert set(r.keys()) == LEGACY_KEYS, f"net keys leaked without the flag: {r}"


# Never COALESCE a null net to amount_cents: that would label gross as net.
def case_net_null_is_disclosed_not_imputed():
    rows = _rows(group_by="kind", account_id=A2, include_net=True)
    by_kind = {r["kind"]: r for r in rows}
    ppv = by_kind["ppv_message"]
    assert ppv["total_cents"] == 3_000, ppv
    assert ppv["net_cents"] == 0, f"a null net must not be imputed from gross: {ppv}"
    assert ppv["net_missing_count"] == 1, f"the missing row must be disclosed: {ppv}"
    rebill = by_kind["rebill"]
    assert rebill["net_missing_count"] == 0, rebill


def case_per_model_net_reconciles():
    rev = _rows(group_by="kind", include_net=True)
    card_net = sum(r["net_cents"] for r in rev)
    pm = asyncio.run(stats.per_model(account_id=None, engagement=False, **WIN))
    table_net = sum(m["total_net_revenue_cents"] for m in pm["per_model"])
    assert card_net == table_net, f"net card {card_net} != net table {table_net}"
    assert sum(m["net_missing_count"] for m in pm["per_model"]) == 1, pm["per_model"]


def case_by_kind_nested():
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
    off = _rows(group_by="day", account_id=A1)
    for r in off:
        assert "by_kind" not in r, f"key created without the flag: {r}"
        assert set(r.keys()) == LEGACY_KEYS, sorted(r.keys())


def case_by_kind_rejects_group_by_kind():
    try:
        _rows(group_by="kind", by_kind=True)
    except HTTPException as e:
        assert e.status_code == 400, e.status_code
        assert "by_kind" in str(e.detail), e.detail
        return
    raise AssertionError("by_kind=true with group_by=kind must raise 400")


def case_status_reversed_reads_reversals():
    by_kind = {r["kind"]: r["total_cents"] for r in _rows(group_by="kind", account_id=A1, status="reversed")}
    assert by_kind == {"ppv_message": 9_900, "tip": 1_100}, by_kind
    days = _rows(group_by="day", account_id=A1, status="reversed")
    assert [(r["day"], r["total_cents"], r["count"]) for r in days] == [("2026-07-02", 11_000, 2)], days


def case_per_model_refunds_not_pending():
    pm = {m["account_id"]: m for m in asyncio.run(stats.per_model(account_id=None, **WIN))["per_model"]}
    assert pm[A1]["refunded_cents"] == 11_000, pm[A1]
    assert pm[A1]["refunded_net_cents"] == 9_900 * 8 // 10 + 1_100 * 8 // 10, pm[A1]
    assert pm[A2]["refunded_cents"] == 0, pm[A2]
    assert pm[A1]["pending_revenue_cents"] == 0, f"a reversal counted as pending: {pm[A1]}"
    assert pm[A1]["pending_clears_by"] is None, pm[A1]


def _slots(zone: str | None, **kw) -> list[tuple[int, int, int]]:
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
    assert _slots(None) == [(3, 9, 10_000), (3, 18, 2_500), (4, 12, 5_000), (4, 23, 500)]
    assert _slots("America/New_York") == [(3, 5, 10_000), (3, 14, 2_500), (4, 8, 5_000), (4, 19, 500)]
    assert _slots("Asia/Kolkata") == [(3, 14, 10_000), (4, 0, 2_500), (4, 17, 5_000)]
    assert _slots(None, status="reversed") == [(4, 13, 9_900), (4, 14, 1_100)]


def case_hour_buckets_by_local_hour():
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
    real = stats._report_zone

    async def _zone(_account_id):
        return ZoneInfo(zone)
    stats._report_zone = _zone
    try:
        return _rows(**kw)
    finally:
        stats._report_zone = real


def case_hour_buckets_cut_a_half_hour_zone_by_the_minute():
    rows = _rows_in("Asia/Kolkata", group_by="hour", account_id=A1,
                    from_="2026-07-01T00:00:00Z", to="2026-07-02T23:59:59Z")
    assert [(r["day"], r["total_cents"]) for r in rows] == [
        ("2026-07-01T14:00", 10_000), ("2026-07-02T00:00", 2_500), ("2026-07-02T17:00", 5_000),
        ("2026-07-03T05:00", 500)], rows


def case_hour_buckets_hold_both_runs_of_the_hour_a_daylight_saving_end_repeats():
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
