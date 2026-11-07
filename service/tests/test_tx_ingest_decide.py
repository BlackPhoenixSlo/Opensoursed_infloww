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
from collections import Counter  # noqa: E402
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
        ("chargedback -> cleared (dispute lost) puts the old amount back", row("p1"),
         {"p1": held(row("p1", amount=7.0, status="undo"))}, (), (),
         ("patch", "tip", 700, False, "status_flip", (0, 1))),
        ("refunded -> refund_pending (still revenue) puts it back", row("p1", status="pending_return"),
         {"p1": held(row("p1", status="refunded"))}, (), (),
         ("patch", "tip", 500, False, "status_flip", (0, 1))),
        ("chargedback -> failed: leaves the settled reversal, puts it back", row("p1", status="failed"),
         {"p1": held(row("p1", status="undo"))}, (), (),
         ("patch", "tip", 500, False, "status_flip", (0, 1))),
        ("cleared -> failed: no delta (as before)", row("p1", status="failed"),
         {"p1": held(row("p1"))}, (), (),
         ("patch", "tip", 0, False, "status_flip", (0, 1))),
        ("WS twin adopted already charged back takes the WS bump off", row("p1", status="undo"), {},
         [WsTip(9, FAN, 495, NOW)], (),
         ("promote", "tip", -495, False, "ledger_promote", (0, 1))),
        ("WS twin adopted already refunded takes the WS bump off", row("p1", status="refunded"), {},
         [WsTip(9, FAN, 500, NOW)], (),
         ("promote", "tip", -500, False, "ledger_promote", (0, 1))),
        ("WS twin adopted refund_pending: still revenue, reconcile only", row("p1", status="pending_return"),
         {}, [WsTip(9, FAN, 500, NOW)], (),
         ("promote", "tip", 0, False, "ledger_promote", (0, 1))),
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


def case_reversal_oscillation_nets_one_amount():
    # Lifetime follows status: however OF's statuses bounce, the sale is off once.
    for name, statuses, want in [
        ("cleared -> chargedback -> refund_pending -> chargedback", ["undo", "pending_return", "undo"], -500),
        ("cleared -> chargedback -> cleared", ["undo", "done"], 0),
        ("cleared -> refund_pending -> chargedback -> refunded", ["pending_return", "undo", "refunded"], -500),
        ("chargedback -> cleared -> chargedback -> cleared", ["undo", "done", "undo", "done"], 0),
        ("cleared -> chargedback -> failed -> cleared", ["undo", "failed", "done"], 0),
    ]:
        ops = plan([row("p1", status=st) for st in statuses], {"p1": held(row("p1"))})
        assert sum(o.lifetime_delta for o in ops) == want, (name, [o.lifetime_delta for o in ops])
    ops = plan([row("p1", status="done")], {"p1": held(row("p1", status="undo"))})
    assert ops[0].status_flip == ("chargedback", "cleared") and ops[0].lifetime_delta == 500, ops


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

def case_third_failure_pauses_1800_s():
    s = ScanState()
    statuses = []
    for _ in range(3):
        s = d.scan_after_failure(s, False, NOW, error="OF 500")
        statuses.append(s.current_status)
    assert statuses == ["error", "error", "paused"], statuses
    assert s.consecutive_failures == 3
    assert s.paused_until == NOW + timedelta(seconds=1800), s.paused_until
    assert d.is_paused(s, NOW + timedelta(seconds=1799)) and not d.is_paused(s, NOW + timedelta(seconds=1800))


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
    done = ScanState(fully_backfilled=True)
    full, phase = d._DEFAULT_FULL_EVERY_S, 437
    # NOW (12:00 UTC) is a 7200 s boundary of the epoch, so with phase 437 this
    # account's current period began 437 s ago, at B.
    B = NOW - timedelta(seconds=phase)
    assert d.full_bucket(B, full_every_s=full, phase_s=phase) == d.full_bucket(NOW, full_every_s=full, phase_s=phase)
    assert d.full_bucket(B - timedelta(seconds=1), full_every_s=full, phase_s=phase) \
        == d.full_bucket(NOW, full_every_s=full, phase_s=phase) - 1
    table = [
        # (name, state, last_full_at, phase, want)
        ("no scan row", None, None, 0, "backfill"),
        ("never backfilled", ScanState(), None, 0, "backfill"),
        ("backfilling, full walk recent", ScanState(), NOW, 0, "backfill"),
        ("just restarted: no full walk in this process", done, None, phase, "refresh"),
        ("full walk at the start of this period", done, B, phase, "recent"),
        ("full walk 5 min ago, same period", done, NOW - timedelta(minutes=5), phase, "recent"),
        ("full walk 1 s before this period", done, B - timedelta(seconds=1), phase, "refresh"),
        ("10 min ago is the previous period at this phase", done, NOW - timedelta(minutes=10), phase, "refresh"),
        ("phase 0: NOW is the boundary, 1 s ago was the last period", done, NOW - timedelta(seconds=1), 0, "refresh"),
        ("phase 0: a walk at NOW", done, NOW, 0, "recent"),
        ("a walk stamped in a later period (clock stepped back)", done, NOW + timedelta(hours=3), phase, "refresh"),
        ("hours ago", done, NOW - timedelta(hours=5), phase, "refresh"),
    ]
    for name, st, last, ph, want in table:
        got = d.decide_mode(st, now=NOW, last_full_at=last, phase_s=ph)
        assert got == want, (name, got, want)
    assert d.decide_mode(done, now=NOW, last_full_at=NOW - timedelta(seconds=950), full_every_s=900) == "refresh"
    assert d.window_for("recent", ScanState(), NOW) == (NOW - timedelta(hours=24), NOW)
    assert d.window_for("recent", ScanState(), NOW, recent_h=12) == (NOW - timedelta(hours=12), NOW)
    assert d.window_for("refresh", ScanState(), NOW) == (NOW - timedelta(days=7), NOW)
    assert d.window_for("backfill", ScanState(), NOW) == (NOW - timedelta(days=90), NOW)
    floor, oldest = NOW - timedelta(days=30), NOW - timedelta(days=4)
    assert d.window_for("backfill", ScanState(backfill_floor=floor, oldest_seen_occurred_at=oldest), NOW) \
        == (floor, oldest)


def case_recent_start_date_is_date_only_a_day_early():
    for start, want in [
        (datetime(2026, 11, 6, 12, 0), "2026-11-05"),
        (datetime(2026, 11, 7, 0, 0), "2026-11-06"),
        (datetime(2026, 11, 6, 23, 59, 59), "2026-11-05"),
        (datetime(2026, 1, 1, 5, 0), "2025-12-31"),
    ]:
        got = d.recent_start_date(start)
        assert got == want and __import__("re").fullmatch(r"\d{4}-\d{2}-\d{2}", got), (start, got, want)


_rng = __import__("random").Random(7)
FLEET = [str(_rng.randrange(10**8, 10**9)) for _ in range(50)]   # 50 OF-like Creator ids, deterministic


def _full_ticks(aid: str, tick_s: float, hours: float, t0: datetime) -> list[int]:
    """The supervisor's ticks for one account from a restart at t0: which tick indexes walk full
    (decide at the tick, stamp the walk's start, as run_one_tick does)."""
    done, last, out = ScanState(fully_backfilled=True), None, []
    ph = d.full_phase_s(aid)
    for n in range(int(hours * 3600 / tick_s)):
        now = t0 + timedelta(seconds=n * tick_s)
        if d.decide_mode(done, now=now, last_full_at=last, phase_s=ph) == "refresh":
            out.append(n)
            last = now
    return out


def case_full_phase_deterministic_in_period():
    got = [d.full_phase_s(a) for a in FLEET]
    assert all(0 <= g < 7200 and isinstance(g, int) for g in got), got
    assert got == [d.full_phase_s(a) for a in FLEET], "phase must not change between calls"
    assert d.full_phase_s("80000112") == __import__("zlib").crc32(b"80000112") % 7200
    assert d.full_phase_s("80000112", 3600) == __import__("zlib").crc32(b"80000112") % 3600


def case_restart_herd_spreads_within_one_period_then_exact_period():
    t0 = NOW + timedelta(seconds=123)
    second = Counter()
    for aid in FLEET:
        fulls = _full_ticks(aid, 900, 26, t0)
        assert fulls[0] == 0, (aid, fulls[:3])                        # restart: everyone full at once
        assert 1 <= fulls[1] <= 8, (aid, fulls[:3])                   # then within one period
        assert {b - a for a, b in zip(fulls[1:], fulls[2:])} == {8}, (aid, fulls)   # 7200 s walk to walk
        second[fulls[1]] += 1
    spread = [second[n] for n in range(1, 9)]
    print(f"    full-walk phase spread of 50 Creators over the 8 ticks of a period: {spread}")
    # crc32 phases are ~uniform: 50 into 8 ticks is ~6 each with multinomial noise (a max of 12-14 is
    # normal at n=50); the bound is "no tick carries a third of the fleet", vs all 50 at the restart.
    assert sum(spread) == 50 and max(spread) <= 16 and min(spread) >= 1, spread
    # Ticks that run late (cycle overrun): walk to walk stays 7200 s +/- one tick.
    for aid in FLEET[:10]:
        fulls = _full_ticks(aid, 905, 26, t0)
        gaps = {(b - a) * 905 for a, b in zip(fulls[1:], fulls[2:])}
        assert all(7200 - 905 <= g <= 7200 + 905 for g in gaps), (aid, gaps)


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
    # OF calls it `done` again (dispute lost): the amount comes back with the row.
    rows[2] = row(7_700_000_002, amount=3.0, status="done", at=NOW - timedelta(minutes=2))
    assert await ti._write_page(aid, rows) == (0, 5)
    assert _ledger_txns() == 1
    assert await _lifetime(aid) == 1500
    rows[2] = row(7_700_000_002, amount=3.0, status="undo", at=NOW - timedelta(minutes=2))
    assert await ti._write_page(aid, rows) == (0, 5)
    _ledger_txns()
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
