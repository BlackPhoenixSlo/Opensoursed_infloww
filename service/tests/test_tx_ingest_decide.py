#!/usr/bin/env python3
"""
transaction_ingest_decide: the ledger page plan and the scan state machine,
as tables (pure, no DB) — plus cases on the real write path: a page with news
is ONE `ledger` write transaction, a quiet re-poll none; a row that fails the
page falls back row by row without losing the others; a lock timeout does not.

Run: ./venv/bin/python service/tests/test_tx_ingest_decide.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import logging  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import transaction_ingest_decide as d  # noqa: E402
from transaction_ingest_decide import Existing, ScanState, WsTip, plan_page  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, 0)
FAN = 4242

logging.getLogger("of-relay.ingest_tx").setLevel(logging.ERROR)


def row(pid, *, fan=FAN, amount=5.0, what="Tip from Bob", status="done", at=NOW):
    return {"id": pid, "user": {"id": fan} if fan else {}, "amount": amount, "net": amount * 0.8,
            "fee": amount * 0.2, "createdAt": at.isoformat() + "Z", "status": status, "description": what}


def plan(rows, existing=None, ws=(), subscribed=()):
    return plan_page(d.parse_page(rows, NOW), existing or {}, ws, subscribed_fans=subscribed)


def one(r, existing=None, ws=(), subscribed=()):
    ops = plan([r], existing, ws, subscribed)
    assert len(ops) == 1, ops
    return ops[0]


def held(r):
    """The row as already stored: every PATCH_FIELDS value equal."""
    return Existing.of(d.parse_page([r], NOW)[0])


def shape(op):
    return (op.action, op.kind, op.lifetime_delta, op.lifetime_create, op.broadcast, op.result)


# ── plan_page ───────────────────────────────────────────────────────

def case_plan_table():
    old = NOW - timedelta(days=3)
    table = [
        # (name, row, existing, ws, subscribed, (action, kind, delta, create, broadcast, result))
        ("new tip", row("p1"), {}, (), (),
         ("insert", "tip", 500, True, "insert", (1, 0))),
        ("re-poll identical: noop, nothing written", row("p1"), {"p1": held(row("p1"))}, (), (),
         ("noop", "tip", 0, False, None, (0, 1))),
        ("re-poll, description changed, no flip: patch, silent", row("p1"),
         {"p1": held(row("p1", what="Tip from Robert"))}, (), (),
         ("patch", "tip", 0, False, None, (0, 1))),
        ("re-poll, net changed: patch, silent", row("p1"), {"p1": held(row("p1", amount=5.0) | {"net": 3.0})},
         (), (), ("patch", "tip", 0, False, None, (0, 1))),
        ("loading -> cleared", row("p1"), {"p1": held(row("p1", status="loading"))}, (), (),
         ("patch", "tip", 0, False, "status_flip", (0, 1))),
        ("cleared -> chargeback takes the old amount off", row("p1", status="undo"),
         {"p1": held(row("p1", amount=7.0))}, (), (),
         ("patch", "tip", -700, False, "status_flip", (0, 1))),
        ("chargeback -> refunded: no second refund", row("p1", status="refunded"),
         {"p1": held(row("p1", amount=7.0, status="undo"))}, (), (),
         ("patch", "tip", 0, False, "status_flip", (0, 1))),
        ("WS twin adopted (same amount)", row("p1"), {}, [WsTip(9, FAN, 500, NOW + timedelta(seconds=60))], (),
         ("promote", "tip", 0, False, "ledger_promote", (0, 1))),
        ("WS twin adopted, amount reconciled", row("p1", amount=5.01), {},
         [WsTip(9, FAN, 495, NOW - timedelta(seconds=200))], (),
         ("promote", "tip", 6, False, "ledger_promote", (0, 1))),
        ("WS tip outside 300 s is no twin", row("p1"), {}, [WsTip(9, FAN, 500, NOW + timedelta(seconds=301))], (),
         ("insert", "tip", 500, True, "insert", (1, 0))),
        ("WS tip of another fan is no twin", row("p1"), {}, [WsTip(9, FAN + 1, 500, NOW)], (),
         ("insert", "tip", 500, True, "insert", (1, 0))),
        ("a PPV never fingerprints", row("p1", what="Payment for message from Bob"), {}, [WsTip(9, FAN, 500, NOW)],
         (), ("insert", "ppv_message", 500, True, "insert", (1, 0))),
        ("first subscription", row("p1", what="Subscription from Bob"), {}, (), (),
         ("insert", "subscription", 500, True, "insert", (1, 0))),
        ("rebill promote", row("p1", what="Subscription from Bob"), {}, (), (FAN,),
         ("insert", "rebill", 500, True, "insert", (1, 0))),
        ("unknown kind still inserts", row("p1", what="Mystery payout from Bob"), {}, (), (),
         ("insert", "unknown", 500, True, "insert", (1, 0))),
        ("an old insert still plans its broadcast (events caps it at 48 h)", row("p1", at=old), {}, (), (),
         ("insert", "tip", 500, True, "insert", (1, 0))),
        ("an old flip broadcasts", row("p1", at=old),
         {"p1": held(row("p1", at=old, status="loading"))}, (), (),
         ("patch", "tip", 0, False, "status_flip", (0, 1))),
        ("first sight already charged back: no revenue", row("p1", status="undo"), {}, (), (),
         ("insert", "tip", 0, False, "insert", (1, 0))),
        ("no fan: no lifetime", row("p1", fan=None), {}, (), (),
         ("insert", "tip", 0, False, "insert", (1, 0))),
        ("no provider id: skip", row(None), {}, (), (),
         ("skip", "tip", 0, False, None, (0, 0))),
    ]
    bad = []
    for name, r, existing, ws, subscribed, want in table:
        got = shape(one(r, existing, ws, subscribed))
        if got != want:
            bad.append((name, got, want))
    assert not bad, "\n".join(f"{n}: got {g} want {w}" for n, g, w in bad)


def case_insert_side_effects():
    tip = one(row("p1"))
    assert tip.synth_tip and not tip.link_ppv, tip
    ppv = one(row("p2", what="Payment for message from Bob"))
    assert ppv.link_ppv and not ppv.synth_tip, ppv
    post_tip = one(row("p3", what="Tip on post from Bob"))
    assert post_tip.kind == "tip_post" and not post_tip.synth_tip, post_tip
    chargedback_tip = one(row("p4", status="undo"))
    assert not chargedback_tip.synth_tip, "a tip that is already reversed shows no inline bubble"
    flip = one(row("p1", status="undo"), {"p1": held(row("p1"))})
    assert flip.lifetime_delta == -500 and flip.status_flip == ("cleared", "chargedback"), flip
    assert not one(row("p1"), {"p1": held(row("p1"))}).writes, "an identical re-poll writes nothing"


def case_duplicate_provider_id_inside_one_page():
    ops = plan([row("p1"), row("p1", status="undo"), row("p1", status="undo")])
    assert [shape(o) for o in ops] == [
        ("insert", "tip", 500, True, "insert", (1, 0)),
        ("patch", "tip", -500, False, "status_flip", (0, 1)),
        ("noop", "tip", 0, False, None, (0, 1)),   # the same row again: nothing to write
    ], [shape(o) for o in ops]


def case_a_numeric_provider_id_matches_its_text_column():
    # OF may send the id as a number; transactions.provider_transaction_id is text.
    assert one(row(7700000001), {"7700000001": held(row(7700000001, status="loading"))}).action == "patch"
    ops = plan([row(7700000002), row(7700000002)])
    assert [o.action for o in ops] == ["insert", "noop"], ops


def case_one_ws_twin_is_adopted_once():
    ws = [WsTip(9, FAN, 500, NOW)]
    ops = plan([row("p1"), row("p2")], ws=ws)
    assert [o.action for o in ops] == ["promote", "insert"], ops
    assert ops[0].target_id == 9


def case_newest_ws_twin_wins():
    ws = [WsTip(7, FAN, 500, NOW - timedelta(seconds=100)), WsTip(8, FAN, 500, NOW + timedelta(seconds=50))]
    assert one(row("p1"), ws=ws).target_id == 8


def case_second_subscription_in_a_page_is_a_rebill():
    ops = plan([row("p1", what="Subscription from Bob"), row("p2", what="Subscription from Bob")])
    assert [o.kind for o in ops] == ["subscription", "rebill"], [o.kind for o in ops]


def case_read_keys():
    p = d.parse_page([row("t1"), row("t2", at=NOW + timedelta(minutes=5)), row("t3", fan=None),
                      row("x1", what="Payment for message from Bob"), row("s1", fan=7, what="Subscription from Al"),
                      row("s2", fan=8, what="Recurring subscription from Cy")], NOW)
    assert d.tip_window(p, ()) == ({FAN}, NOW - timedelta(seconds=300), NOW + timedelta(seconds=600)), \
        d.tip_window(p, ())
    assert d.tip_window(p, {"t2"}) == ({FAN}, NOW - timedelta(seconds=300), NOW + timedelta(seconds=300))
    assert d.tip_window(p, {"t1", "t2"}) is None, "held rows need no twin"
    assert d.subscription_fans(p) == {7}, d.subscription_fans(p)
    no_date = d.parse_page([{"id": "n1", "amount": 1}], NOW)[0]
    assert no_date["occurred_at"] == NOW, "a row without createdAt is dated by the caller's clock"


# ── scan state machine ──────────────────────────────────────────────

def case_third_failure_pauses_600_s():
    s = ScanState()
    statuses = []
    for _ in range(3):
        s = d.scan_after_failure(s, False, NOW, error="OF 500")
        statuses.append(s.current_status)
    assert statuses == ["error", "error", "paused"], statuses
    assert s.consecutive_failures == 3
    assert s.paused_until == NOW + timedelta(seconds=600), s.paused_until
    assert d.is_paused(s, NOW + timedelta(seconds=599)) and not d.is_paused(s, NOW + timedelta(seconds=600))


def case_proxy_refusal_is_not_counted():
    s = ScanState(consecutive_failures=2, current_status="refreshing")
    for _ in range(5):
        s = d.scan_after_failure(s, True, NOW, error="CONNECT tunnel failed")
    assert (s.consecutive_failures, s.current_status, s.paused_until) == (2, "idle", None), s
    assert s.last_error == "CONNECT tunnel failed"


def case_success_table():
    t1, t2 = NOW - timedelta(days=9), NOW - timedelta(days=1)
    base = ScanState(consecutive_failures=2, last_error="x", oldest_seen_occurred_at=t2,
                     newest_seen_occurred_at=t2, rows_inserted_total=5, last_marker=7)
    table = [
        # (mode, floor_reached, want status, want fully_backfilled)
        ("backfill", True, "ok", True),
        ("backfill", False, "backfilling", False),
        ("refresh", False, "ok", False),
        ("refresh", True, "ok", False),
    ]
    for mode, floor, want_status, want_full in table:
        s = d.scan_after_success(base, mode=mode, inserted=3, patched=1, last_marker=None,
                                 rows_min=t1, rows_max=NOW, floor_reached=floor, now=NOW)
        assert (s.current_status, s.fully_backfilled) == (want_status, want_full), (mode, floor, s)
        assert (s.consecutive_failures, s.last_error, s.last_scan_at) == (0, None, NOW), s
        assert (s.oldest_seen_occurred_at, s.newest_seen_occurred_at) == (t1, NOW), s
        assert (s.rows_inserted_total, s.rows_patched_total, s.last_marker) == (8, 1, 7), s


def case_start_and_interrupt():
    floor = NOW - timedelta(days=90)
    s = d.scan_started(ScanState(current_status="ok"), "backfill", floor, NOW)
    assert (s.current_status, s.last_scan_at, s.backfill_floor) == ("backfilling", NOW, floor), s
    pinned = NOW - timedelta(days=30)
    s = d.scan_started(ScanState(backfill_floor=pinned), "backfill", floor, NOW)
    assert s.backfill_floor == pinned, "a backfill's floor is pinned by its first tick"
    s = d.scan_started(ScanState(), "refresh", NOW - timedelta(days=7), NOW)
    assert (s.current_status, s.backfill_floor) == ("refreshing", None), s
    s = d.scan_interrupted(ScanState(consecutive_failures=2, current_status="refreshing"), "interrupted_mid_tick")
    assert (s.current_status, s.last_error, s.consecutive_failures) == ("idle", "interrupted_mid_tick", 2), s


def case_window_and_mode():
    assert d.decide_mode(None) == "backfill"
    assert d.decide_mode(ScanState()) == "backfill"
    assert d.decide_mode(ScanState(fully_backfilled=True)) == "refresh"
    assert d.window_for("refresh", ScanState(), NOW) == (NOW - timedelta(days=7), NOW)
    assert d.window_for("backfill", ScanState(), NOW) == (NOW - timedelta(days=90), NOW)
    floor, oldest = NOW - timedelta(days=30), NOW - timedelta(days=4)
    assert d.window_for("backfill", ScanState(backfill_floor=floor, oldest_seen_occurred_at=oldest), NOW) \
        == (floor, oldest)


# ── the write path ──────────────────────────────────────────────────

async def _account(aid: str) -> None:
    from db.engine import get_session
    from db.models import Account, Fan
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=FAN, lifetime_spend_cents=0))


async def _lifetime(aid: str) -> int:
    from db.engine import get_session
    from db.models import Fan
    async with get_session() as s:
        return (await s.get(Fan, (aid, FAN))).lifetime_spend_cents


def _ledger_txns() -> int:
    from db import write_telemetry
    return (write_telemetry.snapshot("test")["w"].get("ledger") or {}).get("n", 0)


async def case_a_page_is_one_ledger_txn_with_its_lifetime():
    import transaction_ingest as ti
    aid = "tx_decide_1"
    await _account(aid)
    rows = [row(f"q{i}" if i % 2 else 7_700_000_000 + i, amount=1.0 + i, at=NOW - timedelta(minutes=i))
            for i in range(5)]
    _ledger_txns()
    assert await ti._write_page(aid, rows) == (5, 0)
    assert _ledger_txns() == 1, "a page must be ONE write transaction"
    assert await _lifetime(aid) == 100 + 200 + 300 + 400 + 500
    # A quiet re-poll of the same page: no write transaction at all.
    assert await ti._write_page(aid, rows) == (0, 5)
    assert _ledger_txns() == 0, "a re-poll with every field equal must take no write lock"
    # A chargeback of one row: its lifetime delta commits with the row.
    rows[2] = row(7_700_000_002, amount=3.0, status="undo", at=NOW - timedelta(minutes=2))
    assert await ti._write_page(aid, rows) == (0, 5)
    assert _ledger_txns() == 1
    assert await _lifetime(aid) == 1500 - 300
    # A lone row with nothing to write (re-poll, or no provider id): no write transaction.
    assert await ti._write_one(aid, rows[0]) == (0, 1)
    assert await ti._write_one(aid, row(None)) == (0, 0)
    assert _ledger_txns() == 0


async def case_a_bad_row_falls_back_row_by_row():
    import transaction_ingest as ti
    aid = "tx_decide_2"
    await _account(aid)
    bad = row("b1", amount=1e18)   # cents overflow SQLite's INTEGER: this row alone fails
    rows = [row("g1", amount=2.0), bad, row("g2", amount=3.0)]
    _ledger_txns()
    assert await ti._write_page(aid, rows) == (2, 0)
    assert _ledger_txns() == 1 + 3, "the failed page, then one transaction per row"
    assert await _lifetime(aid) == 500


async def case_a_lock_timeout_is_not_retried_row_by_row():
    import sqlalchemy.exc

    import transaction_ingest as ti
    rows_tried = []

    async def locked(_aid, _rows):
        raise sqlalchemy.exc.OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))

    async def one_row(_aid, raw):
        rows_tried.append(raw)
        return (1, 0)

    real = ti._ingest_rows, ti._write_one
    ti._ingest_rows, ti._write_one = locked, one_row
    try:
        try:
            await ti._write_page("tx_decide_3", [row("l1"), row("l2")])
        except sqlalchemy.exc.OperationalError:
            pass
        else:
            raise AssertionError("a lock timeout must fail the page (the tick records it)")
    finally:
        ti._ingest_rows, ti._write_one = real
    assert rows_tried == [], "a lock timeout would only repeat per row"



async def case_an_after_commit_failure_spares_the_other_rows():
    import events

    import transaction_ingest as ti
    aid = "tx_decide_4"
    await _account(aid)
    announced = []

    async def announce(account_id, fan_id, **kw):
        announced.append(kw["kind"])
        if len(announced) == 1:
            raise RuntimeError("SSE down")

    real = events.announce_transaction
    events.announce_transaction = announce
    try:
        assert await ti._write_page(aid, [row("a1"), row("a2", what="Tip on post from Bob")]) == (2, 0)
    finally:
        events.announce_transaction = real
    assert announced == ["tip", "tip_post"], "the second row's announce still runs"
    assert await _lifetime(aid) == 1000


_harness.run()
