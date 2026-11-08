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
from dataclasses import replace  # noqa: E402
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
        ("backfill", False, "backfill_partial", False),
        ("refresh", False, "backfill_partial", False),
        ("refresh", True, "backfill_partial", False),
    ]
    for mode, floor, want_status, want_full in table:
        s = d.scan_after_success(base, mode=mode, inserted=3, patched=1, last_marker=None,
                                 rows_min=t1, rows_max=NOW, floor_reached=floor, now=NOW)
        assert (s.current_status, s.fully_backfilled) == (want_status, want_full), (mode, floor, s)
        assert (s.consecutive_failures, s.last_error, s.last_scan_at) == (0, None, NOW), s
        # Until done the seen range is the backfill's: only a backfill moves it (a refresh's
        # top would hide a gap below it from the next resumed read).
        moved = mode == "backfill"
        assert (s.oldest_seen_occurred_at, s.newest_seen_occurred_at) == (t1 if moved else t2, NOW if moved else t2), s
        assert (s.rows_inserted_total, s.rows_patched_total, s.last_marker) == (8, 1, 7), s
    done = d.scan_after_success(replace(base, fully_backfilled=True), mode="refresh", inserted=0, patched=0,
                                last_marker=None, rows_min=t1, rows_max=NOW, floor_reached=True, now=NOW)
    assert (done.oldest_seen_occurred_at, done.newest_seen_occurred_at) == (t1, NOW), "a finished account's widens"
    assert done.current_status == "ok"
    assert d.BACKFILL_PARTIAL not in d.IN_FLIGHT, "between ticks: an in-flight status would skip the next tick"


def case_a_stopped_walk_reads_stalled_until_a_tick_clears_it():
    t = NOW - timedelta(days=1)
    base = ScanState(oldest_seen_occurred_at=t, newest_seen_occurred_at=t)

    def after(state, mode, floor=False, stop=None):
        return d.scan_after_success(state, mode=mode, inserted=0, patched=0, last_marker=None, rows_min=None,
                                    rows_max=None, floor_reached=floor, now=NOW, stop_reason=stop)
    table = [
        # (stop reason, want status, want last_error)
        (None, "backfill_partial", None),
        ("tick_cap", "backfill_partial", None),
        ("no_next_marker", "backfill_stalled", "backfill_stopped: no_next_marker"),
        ("rows_not_held", "backfill_stalled", "backfill_stopped: rows_not_held"),
        ("blank_first_page", "backfill_stalled", "backfill_stopped: blank_first_page"),
    ]
    for stop, want, err in table:
        s = after(base, "backfill", stop=stop)
        assert (s.current_status, s.last_error) == (want, err), (stop, s)
    stalled = after(base, "backfill", stop="repeated_page")
    kept = after(replace(stalled, current_status="refreshing"), "refresh", floor=True)
    assert (kept.current_status, kept.last_error) == ("backfill_stalled", stalled.last_error), kept
    cap = after(stalled, "backfill", stop="tick_cap")
    assert (cap.current_status, cap.last_error) == ("backfill_partial", None), cap
    done = after(stalled, "backfill", floor=True, stop="last_page")
    assert (done.current_status, done.last_error, done.fully_backfilled) == ("ok", None, True), done
    plain = after(replace(base, last_error="OF 500"), "refresh", floor=True)
    assert (plain.current_status, plain.last_error) == ("backfill_partial", None), plain


def case_marker_of_rounds_up_so_ties_are_re_read():
    table = [
        (datetime(2026, 10, 13, 21, 49, 26), 1791928166),
        (datetime(2026, 10, 13, 21, 49, 26, 1), 1791928167),
        (datetime(2026, 10, 13, 21, 49, 26, 999999), 1791928167),
        (datetime(1970, 1, 1), 0),
    ]
    for at, want in table:
        assert d.marker_of(at) == want, (at, d.marker_of(at), want)


def case_page_span_reads_of_stamps_and_clamps_to_the_window():
    w = datetime(2026, 8, 1)
    r = lambda at: {"createdAt": at}
    table = [
        # (rows, want cursor, want newest, want below)
        ([], None, None, False),
        ([r("2026-10-13T21:49:26+00:00"), r("2026-10-13T20:00:00+00:00")],
         datetime(2026, 10, 13, 20), datetime(2026, 10, 13, 21, 49, 26), False),
        ([r("2026-10-13T21:49:26Z")], datetime(2026, 10, 13, 21, 49, 26), datetime(2026, 10, 13, 21, 49, 26), False),
        ([r("2026-10-13T21:49:26.250+00:00")], datetime(2026, 10, 13, 21, 49, 26, 250000),
         datetime(2026, 10, 13, 21, 49, 26, 250000), False),
        ([r("2026-08-02T00:00:00+00:00"), r("2026-07-20T00:00:00+00:00")],
         datetime(2026, 8, 2), datetime(2026, 8, 2), True),
        ([r("2026-07-20T00:00:00+00:00")], None, datetime(2026, 7, 20), True),
        ([r("not a date"), {}], None, None, False),
    ]
    for rows, cursor, newest, below in table:
        assert d.page_span(rows, w) == (cursor, newest, below), (rows, d.page_span(rows, w))


def case_backfill_step_table():
    table = [
        # (rows, hasMore, nextMarker, sent, first, held, below, want action, reason, marker)
        (100, True, 900, None, True, True, False, "next", "more", 900),
        (100, True, 900, 1000, False, True, False, "next", "more", 900),
        (100, True, "900", 1000, False, True, False, "next", "more", 900),
        (100, True, 900.5, 1000, False, True, False, "next", "more", 901),   # never above-precision
        (37, False, None, 1000, False, True, False, "complete", "last_page", None),
        (37, False, None, None, True, True, False, "complete", "last_page", None),
        (37, False, None, 1000, False, True, True, "complete", "last_page", None),
        (0, False, None, None, True, False, False, "complete", "empty_window", None),
        # hasMore anything but false: not an end, whatever else the page says (finding 5).
        (0, True, None, None, True, False, False, "stop", "empty_page", None),
        (0, None, None, None, True, False, False, "stop", "empty_page", None),
        (37, None, None, 1000, False, True, False, "stop", "no_has_more", None),
        (37, 0, None, 1000, False, True, False, "stop", "no_has_more", None),
        (37, "", 900, 1000, False, True, False, "stop", "no_has_more", None),
        # Not done: the offset cap's look-alike, a stuck cursor, OF ignoring startDate.
        (0, False, None, None, True, True, False, "stop", "empty_first_page_rows_held", None),
        (0, False, None, 1000, True, True, False, "stop", "empty_first_page_rows_held", None),
        (0, False, None, 1000, False, True, False, "stop", "empty_page", None),
        (0, True, 900, 1000, False, True, False, "stop", "empty_page", None),
        (100, True, None, 1000, False, True, False, "stop", "no_next_marker", None),
        (100, True, "x", 1000, False, True, False, "stop", "no_next_marker", None),
        (100, True, float("inf"), 1000, False, True, False, "stop", "no_next_marker", None),
        (100, True, float("nan"), 1000, False, True, False, "stop", "no_next_marker", None),
        (100, True, 1000, 1000, False, True, False, "stop", "marker_not_decreasing", None),
        (100, True, 1001, 1000, False, True, False, "stop", "marker_not_decreasing", None),
        (100, True, 900, 1000, False, True, True, "stop", "start_date_ignored", None),
    ]
    for rows, more, nxt, sent, first, held, below, action, reason, marker in table:
        got = d.backfill_step(rows=rows, has_more=more, next_marker=nxt, sent_marker=sent, first_page=first,
                              held_since=held, below_window=below)
        assert got == (action, reason, marker), (rows, more, nxt, sent, first, held, below, got)


def case_scan_backfill_page_table():
    hi, lo, top = NOW - timedelta(days=2), NOW - timedelta(days=5), NOW - timedelta(hours=1)
    base = ScanState(oldest_seen_occurred_at=hi, newest_seen_occurred_at=hi, rows_inserted_total=4, rows_patched_total=1)
    table = [
        # (cursor, newest, want oldest, want newest)
        (lo, top, lo, top),      # a page further down
        (top, top, hi, top),     # the cursor never moves up
        (None, top, hi, top),    # the recent read / a page not all held
        (None, None, hi, hi),
    ]
    for cursor, newest, want_old, want_new in table:
        s = d.scan_backfill_page(base, cursor=cursor, newest=newest, inserted=2, patched=3)
        assert (s.oldest_seen_occurred_at, s.newest_seen_occurred_at) == (want_old, want_new), s
        assert (s.rows_inserted_total, s.rows_patched_total) == (6, 4), s
    assert d.scan_backfill_page(ScanState(), cursor=lo, newest=None, inserted=0, patched=0).oldest_seen_occurred_at == lo


def case_backfill_tier_stays_green_between_ticks():
    from tx_ingest_admin_api import _tx_ingest_tier
    assert _tx_ingest_tier(5.0, "backfill_partial") == "green"
    assert _tx_ingest_tier(5.0, "backfilling") == "green"
    assert _tx_ingest_tier(5.0, d.BACKFILL_STALLED) == "yellow", "a stopped walk needs a look"
    assert d.BACKFILL_STALLED not in d.IN_FLIGHT, "between ticks: an in-flight status would skip the next tick"


def case_start_and_interrupt():
    floor = NOW - timedelta(days=90)
    s = d.scan_started(ScanState(current_status="ok"), "backfill", floor, NOW)
    assert (s.current_status, s.last_scan_at, s.backfill_floor) == ("backfilling", NOW, floor), s
    pinned = NOW - timedelta(days=30)
    s = d.scan_started(ScanState(backfill_floor=pinned), "backfill", floor, NOW)
    assert s.backfill_floor == pinned, "a backfill's floor is pinned by its first tick"
    s = d.scan_started(ScanState(), "refresh", NOW - timedelta(days=7), NOW)
    assert (s.current_status, s.backfill_floor) == ("refreshing", None), s
    # A legacy seen range below the window is no cursor; one inside it (startDate's day too) is.
    inside = floor - timedelta(hours=1)
    s = d.scan_started(ScanState(backfill_floor=floor, oldest_seen_occurred_at=floor - timedelta(days=2)),
                       "backfill", floor, NOW)
    assert s.oldest_seen_occurred_at is None, s
    s = d.scan_started(ScanState(backfill_floor=floor, oldest_seen_occurred_at=inside), "backfill", floor, NOW)
    assert s.oldest_seen_occurred_at == inside, s
    far = floor - timedelta(days=2)
    s = d.scan_started(ScanState(backfill_floor=floor, oldest_seen_occurred_at=far), "refresh", floor, NOW)
    assert s.oldest_seen_occurred_at == far, "only a backfill reads it as a cursor"
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
        # A walk under way still owes the period's full walk (status flips, disputes).
        ("walk started, full walk this period", ScanState(oldest_seen_occurred_at=NOW), B, phase, "backfill"),
        ("walk started, full walk due", ScanState(oldest_seen_occurred_at=NOW), B - timedelta(seconds=1), phase, "refresh"),
        ("walk started, never stamped", ScanState(oldest_seen_occurred_at=NOW), None, phase, "refresh"),
        ("walk not started, full walk due", ScanState(), B - timedelta(seconds=1), phase, "backfill"),
        ("walk stopped on its first page, full walk due",
         ScanState(last_error="backfill_stopped: blank_first_page"), None, phase, "refresh"),
        ("walk stopped on its first page, full walk done",
         ScanState(last_error="backfill_stopped: blank_first_page"), B, phase, "backfill"),
        ("a tick failed before any page: not stopped", ScanState(last_error="OF 500"), None, phase, "backfill"),
        # Unseeded (row from before the column): recent; _decide_mode persists scan_seeded's stamp.
        ("backfilled, never stamped: recent, no deploy herd", done, None, phase, "recent"),
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
        got = d.decide_mode(st if st is None else replace(st, last_full_at=last), now=NOW, phase_s=ph)
        assert got == want, (name, got, want)
    assert d.decide_mode(replace(done, last_full_at=NOW - timedelta(seconds=950)), now=NOW,
                         full_every_s=900) == "refresh"
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


def _full_ticks(aid: str, tick_s: float, hours: float, t0: datetime,
                last: datetime | None = None) -> list[int]:
    """The supervisor's ticks for one account from a boot at t0 with watermark `last` (None:
    the deploy of the column): which tick indexes walk full (seed, decide at the tick, stamp
    the walk's start, as _decide_mode and run_one_tick do)."""
    st, out = ScanState(fully_backfilled=True, last_full_at=last), []
    ph = d.full_phase_s(aid)
    for n in range(int(hours * 3600 / tick_s)):
        now = t0 + timedelta(seconds=n * tick_s)
        st = d.scan_seeded(st, now)
        if d.decide_mode(st, now=now, phase_s=ph) == "refresh":
            out.append(n)
            st = replace(st, last_full_at=now)
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
        # The deploy seeds every NULL watermark: nobody full at boot, each at its own phase.
        assert 1 <= fulls[0] <= 8, (aid, fulls[:3])
        assert {b - a for a, b in zip(fulls, fulls[1:])} == {8}, (aid, fulls)   # 7200 s walk to walk
        second[fulls[0]] += 1
    spread = [second[n] for n in range(1, 9)]
    print(f"    full-walk phase spread of 50 Creators over the 8 ticks of a period: {spread}")
    # crc32 phases are ~uniform: 50 into 8 ticks is ~6 each with multinomial noise (a max of 12-14 is
    # normal at n=50); the bound is "no tick carries a third of the fleet", vs all 50 at the boot.
    assert sum(spread) == 50 and max(spread) <= 16 and min(spread) >= 1, spread
    # Ticks that run late (cycle overrun): walk to walk stays 7200 s +/- one tick.
    for aid in FLEET[:10]:
        fulls = _full_ticks(aid, 905, 26, t0)
        gaps = {(b - a) * 905 for a, b in zip(fulls, fulls[1:])}
        assert all(7200 - 905 <= g <= 7200 + 905 for g in gaps), (aid, gaps)


def case_full_watermark_seed_failure_and_rollback():
    full, ph = d._DEFAULT_FULL_EVERY_S, 437
    B = NOW - timedelta(seconds=ph)           # start of the current period (see case_window_and_mode)
    done = ScanState(fully_backfilled=True)
    # NULL policy: a backfilled account is seeded to now (then recent); nothing else is.
    assert d.scan_seeded(done, NOW).last_full_at == NOW
    for st in (ScanState(), ScanState(oldest_seen_occurred_at=NOW), replace(done, last_full_at=B)):
        assert d.scan_seeded(st, NOW) is st, st
    assert d.decide_mode(d.scan_seeded(done, NOW), now=NOW, phase_s=ph) == "recent"
    # Seeded a second before its boundary: the boundary's tick walks full (at most one period late).
    s = d.scan_seeded(done, B - timedelta(seconds=1))
    assert d.decide_mode(s, now=B, phase_s=ph) == "refresh"
    assert d.decide_mode(s, now=B - timedelta(milliseconds=500), phase_s=ph) == "recent"
    # Configured periods: 900 s with this phase; the bucket arithmetic is the period's.
    for every in (900.0, 3600.0, 86400.0):
        p = d.full_phase_s("80000112", every)
        start = datetime(1970, 1, 1) + timedelta(
            seconds=d.full_bucket(NOW, full_every_s=every, phase_s=p) * every - p)
        st = replace(done, last_full_at=start)
        assert d.decide_mode(st, now=start + timedelta(seconds=every - 1), full_every_s=every, phase_s=p) == "recent"
        assert d.decide_mode(st, now=start + timedelta(seconds=every), full_every_s=every, phase_s=p) == "refresh"
        assert d.decide_mode(st, now=start - timedelta(seconds=1), full_every_s=every, phase_s=p) == "refresh"
    # A failed or completed full walk stamps its window end; a refusal too; recent leaves it.
    at = NOW - timedelta(minutes=3)
    f = d.scan_after_failure(replace(done, last_full_at=B - timedelta(hours=2)), False, NOW,
                             error="OF 429", full_at=at)
    assert (f.last_full_at, f.current_status, f.consecutive_failures, f.last_error) == (at, "error", 1, "OF 429")
    assert d.scan_after_failure(done, True, NOW, error="refused", full_at=at).last_full_at == at
    third = d.scan_after_failure(replace(done, consecutive_failures=2), False, NOW, error="x", full_at=at)
    assert third.current_status == "paused" and third.last_full_at == at, third
    kept = d.scan_after_failure(replace(done, last_full_at=B), False, NOW, error="x")
    assert kept.last_full_at == B
    ok = dict(inserted=0, patched=0, last_marker=None, rows_min=None, rows_max=None, now=NOW)
    assert d.scan_after_success(replace(done, last_full_at=B), mode="recent", floor_reached=True,
                                **ok).last_full_at == B
    assert d.scan_after_success(done, mode="refresh", floor_reached=False, full_at=at, **ok).last_full_at == at
    assert d.decide_mode(f, now=NOW, phase_s=ph) == "recent", "a failed full walk re-walks in its period"
    # Clock stepped back below the watermark: one refresh, which re-stamps it, then recent.
    future = replace(done, last_full_at=NOW + timedelta(hours=3))
    assert d.decide_mode(future, now=NOW, phase_s=ph) == "refresh"
    assert d.decide_mode(replace(future, last_full_at=NOW), now=NOW + timedelta(seconds=1), phase_s=ph) == "recent"
    # A boot on a persisted DB: only the accounts whose period turned over walk full.
    fulls = _full_ticks("80000112", 900, 3, NOW, last=NOW - timedelta(seconds=1))
    p = d.full_phase_s("80000112")
    same = d.full_bucket(NOW, full_every_s=full, phase_s=p) == d.full_bucket(
        NOW - timedelta(seconds=1), full_every_s=full, phase_s=p)
    assert (fulls[0] != 0) if same else (fulls[0] == 0), (fulls, same)
    due, not_due = 0, 0
    for aid in FLEET:
        p = d.full_phase_s(aid)
        last = NOW - timedelta(minutes=20)
        crossed = d.full_bucket(NOW, full_every_s=full, phase_s=p) != d.full_bucket(last, full_every_s=full, phase_s=p)
        first = _full_ticks(aid, 900, 0.25, NOW, last=last)
        assert bool(first) == crossed, (aid, first, crossed)
        due, not_due = due + crossed, not_due + (not crossed)
    assert due and not_due and due < len(FLEET) // 2, (due, not_due)


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
