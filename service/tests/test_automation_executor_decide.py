#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (unset env falls back to PROD)

import logging  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from isotime import parse_iso  # noqa: E402

from dispatch_plan import (  # noqa: E402
    POKE_FLOOR_S, REPOKE_KINDS, CheckQuiet, Clock, Disable, Enqueue, Interval, Pair, Repoke, Skip, Spawn,
    clock_due, in_quiet_hours, interval_due, next_due, parse_trigger, plan_dispatch, plan_rule, quiet_plan,
    run_key, trigger_of,
)

NOW = datetime(2026, 10, 30, 12, 0, 0)
K = "send_followup"


def case_trigger_table():
    rows = [
        ({}, None),
        ({"every_seconds": 0}, None),
        ({"every_seconds": -5}, None),
        ({"every_seconds": True}, None),
        ({"every_seconds": "60"}, None),
        ({"daily_at": []}, None),
        ({"daily_at": "09:00"}, None),
        ({"every_seconds": 60}, Interval(60, None)),
        ({"every_seconds": 0.5}, Interval(0.5, None)),
        ({"every_seconds": 60, "tz_offset_minutes": 120}, Interval(60, None)),
        ({"daily_at": ["09:00"]}, Clock(("09:00",), 0, None)),
        ({"daily_at": ["09:00"], "tz_offset_minutes": None}, Clock(("09:00",), 0, None)),
        ({"daily_at": ["09:00"], "tz_offset_minutes": 120}, Clock(("09:00",), 120, None)),
        ({"daily_at": ["09:00"], "tz_offset_minutes": 90.0}, Clock(("09:00",), 90, None)),
        ({"daily_at": ["09:00"], "max_runs": 2}, Clock(("09:00",), 0, 2)),
        ({"every_seconds": 0, "daily_at": ["09:00"]}, Clock(("09:00",), 0, None)),
        ({"every_seconds": 300, "daily_at": ["09:00"]}, Interval(300, None)),
    ]
    for trig, want in rows:
        got = parse_trigger(trig)
        assert got == want and type(got) is type(want), (trig, got)
        if isinstance(got, Clock):
            assert type(got.tz_off_min) is int, (trig, got)


def case_bad_tz_table():
    import dispatch_plan
    rows = [
        ("x", None), ("", None), ("1.5", None), ("60", None), (9999, None), (-9999, None),
        (841, None), (-721, None), (True, None), (False, None), (float("nan"), None),
        (float("inf"), None), ([60], None), ({"m": 60}, None),
        (None, 0), (0, 0), (840, 840), (-720, -720), (1.5, 1), (-90.0, -90), (330, 330),
    ]
    for raw, want in rows:
        for parse in (trigger_of, parse_trigger):
            got = parse({"daily_at": ["09:00"], "tz_offset_minutes": raw})
            assert got == (None if want is None else Clock(("09:00",), want, None)), (parse, raw, got)
    assert parse_trigger({"daily_at": ["09:00"]}) == Clock(("09:00",), 0, None)
    assert parse_trigger({"every_seconds": 60, "tz_offset_minutes": "x"}) == Interval(60, None)
    fresh, quiet = f"once-{uuid.uuid4().hex}", f"quiet-{uuid.uuid4().hex}"
    seen: list[str] = []

    class _H(logging.Handler):
        def emit(self, rec):
            seen.append(rec.getMessage())

    h = _H()
    dispatch_plan.log.addHandler(h)
    try:
        for _ in range(3):
            assert parse_trigger({"daily_at": ["09:00"], "tz_offset_minutes": fresh}) is None
            assert trigger_of({"daily_at": ["09:00"], "tz_offset_minutes": quiet}) is None
    finally:
        dispatch_plan.log.removeHandler(h)
    hits = [m for m in seen if repr(fresh) in m]
    assert len(hits) == 1 and "automation_rule_bad_tz_offset" in hits[0], seen
    assert not [m for m in seen if quiet in m], seen


def case_next_due_table():
    d = timedelta(days=1)
    rows = [
        (Interval(3600, None), None, None, NOW),
        (Interval(3600, None), NOW - timedelta(minutes=20), None, NOW + timedelta(minutes=40)),
        (Interval(3600, None), NOW - timedelta(hours=3), None, NOW - timedelta(hours=2)),
        (Clock(("09:00",), 0, None), None, None, NOW.replace(hour=9)),
        (Clock(("09:00",), 0, None), NOW.replace(hour=9, minute=1), None, NOW.replace(hour=9) + d),
        (Clock(("13:00",), 0, None), None, None, NOW.replace(hour=13)),
        (Clock(("13:00",), 0, None), NOW - d, None, NOW.replace(hour=13)),
        (Clock(("09:00", "15:00"), 0, None), NOW.replace(hour=9, minute=1), None, NOW.replace(hour=15)),
        (Clock(("13:00",), 120, None), None, None, NOW.replace(hour=11)),
        (Clock(("13:00",), 120, None), NOW.replace(hour=11, minute=5), None, NOW.replace(hour=11) + d),
        (Clock(("11:30",), -60, None), None, None, NOW.replace(hour=12, minute=30)),
        (Clock(("00:30",), 720, None), None, None, NOW.replace(hour=12, minute=30)),
        (Clock(("bad", "25:00"), 0, None), None, None, None),
        (Interval(3600, 3), None, 3, None),
        (Interval(3600, 3), None, 5, None),
        (Clock(("09:00",), 0, 2), None, 2, None),
        (Interval(3600, 3), None, 2, NOW),
    ]
    for trig, last, runs, want in rows:
        got = next_due(trig, last, NOW, run_count=runs)
        assert got == want, (trig, last, runs, got, want)
    for trig in (Interval(3600, 3), Clock(("09:00",), 0, 2)):
        try:
            next_due(trig, None, NOW)
        except ValueError:
            continue
        raise AssertionError(f"{trig}: max_runs set, run_count None: must raise")


def case_next_due_agrees_with_due():
    triggers = [Interval(3600, None), Interval(45, None),
                Clock(("09:00",), 0, None), Clock(("09:00", "21:30"), 330, None),
                Clock(("00:00", "23:59"), -720, None), Clock(("06:15",), 840, None)]
    lasts = [None, NOW - timedelta(hours=30), NOW - timedelta(hours=5), NOW - timedelta(minutes=1)]
    for trig in triggers:
        for last in lasts:
            for step in range(0, 24 * 60, 7):
                now = NOW + timedelta(minutes=step)
                nd = next_due(trig, last, now)
                if isinstance(trig, Interval):
                    due = interval_due(trig.every, last, now, False)
                else:
                    due = clock_due(now, trig.times, trig.tz_off_min, last)
                assert (nd is not None and nd <= now) is due, (trig, last, now, nd, due)
                if not due:
                    if isinstance(trig, Interval):
                        assert interval_due(trig.every, last, nd, False), (trig, last, nd)
                    else:
                        assert clock_due(nd, trig.times, trig.tz_off_min, last), (trig, last, now, nd)


def case_max_runs_table():
    inf, nan = float("inf"), float("nan")
    rows = [(3, 3), (2.5, 2), (1, 1), (0, None), (-1, None), (True, None), ("3", None), (None, None),
            (inf, None), (1e400, None), (-inf, None), (nan, None)]  # stored Infinity: no OverflowError
    for mx, want in rows:
        for parse in (trigger_of, parse_trigger):
            assert parse({"every_seconds": 60, "max_runs": mx}).max_runs == want, (parse, mx)
            assert parse({"daily_at": ["09:00"], "max_runs": mx}).max_runs == want, (parse, mx)
    for every in (inf, 1e400, nan):
        assert trigger_of({"every_seconds": every}) is None, every
        assert trigger_of({"every_seconds": every, "daily_at": ["09:00"]}) == Clock(("09:00",), 0, None)


def case_interval_cadence_table():
    rows = [
        (3600, None, False, True),
        (3600, 3599, False, False),
        (3600, 3600, False, True),
        (3600, 4000, False, True),
        (3600, POKE_FLOOR_S, True, True),
        (3600, POKE_FLOOR_S - 1, True, False),
        (3600, POKE_FLOOR_S, False, False),
        (30, 29, True, False),
        (30, 30, False, True),
        (0.5, 0.5, False, True),
        (3600, -5, False, False),
        (3600, -5, True, False),
    ]
    for every, age, poked, want in rows:
        last = None if age is None else NOW - timedelta(seconds=age)
        got = interval_due(every, last, NOW, poked)
        assert got is want, (every, age, poked, got)


def case_clock_trigger_table():
    rows = [
        (["09:00"], 0, None, True),
        (["09:00"], 0, NOW.replace(hour=8), True),
        (["09:00"], 0, NOW.replace(hour=9, minute=1), False),
        (["13:00"], 0, None, False),
        (["13:00"], 120, None, True),
        (["11:30"], -60, None, False),
        (["bad", "25:00", "09:60", 9], 0, None, False),
        (["09:00", "11:00"], 0, NOW.replace(hour=10), True),
        (["09:00", "11:00"], 0, NOW.replace(hour=11, minute=1), False),
        (["09:00", "11:00"], 0, None, True),
    ]
    for times, off, last, want in rows:
        got = clock_due(NOW, times, off, last)
        assert got is want, (times, off, last, got)


def case_quiet_hours_table():
    rows = [
        ("[11, 13]", 0, 12, True),
        ("[11, 13]", 0, 13, False),
        ("[11, 13]", 120, 12, False),
        ("[22, 6]", 0, 23, True),
        ("[22, 6]", 0, 5, True),
        ("[22, 6]", 0, 6, False),
        ('{"start": 11, "end": 13}', 0, 12, True),
        ("[0, 0]", 0, 12, False),
        ("[11, 13]", None, 12, False),
        ("[12, 13]", 330, 6, True),
        ("[12, 13]", 330, 5, False),
        (None, 0, 12, False),
        ("", 0, 12, False),
        ("{bad", 0, 12, False),
        ("[11]", 0, 12, False),
        ('["a", 13]', 0, 12, False),
    ]
    for band, off, hour, want in rows:
        got = in_quiet_hours(band, off, NOW.replace(hour=hour, minute=40))
        assert got is want, (band, off, hour, got)


def case_plan_rule_table():
    hourly, capped, clock = Interval(3600, None), Interval(3600, 3), Clock(("09:00",), 0, None)
    old, fresh = NOW - timedelta(hours=2), NOW - timedelta(seconds=POKE_FLOOR_S)
    slot_done = NOW.replace(hour=9, minute=1)
    band = "[11, 13]"
    E = Enqueue(no_clock=False)
    rows = [
        (hourly, None, False, None, None, None, E),
        (hourly, None, False, old, None, None, E),
        (hourly, None, False, fresh, None, None, Skip("not_due")),
        (hourly, None, True, fresh, None, None, E),
        (hourly, None, True, NOW - timedelta(seconds=POKE_FLOOR_S - 1), None, None,
         Repoke()),
        (hourly, None, True, NOW - timedelta(seconds=1), None, band, Repoke()),
        (Interval(30, None), None, True, NOW - timedelta(seconds=29), None, None, Repoke()),
        (hourly, None, False, NOW - timedelta(seconds=1), None, None, Skip("not_due")),
        (hourly, "pending", False, None, None, None, Skip("busy")),
        (hourly, "pending", True, None, None, None, Skip("busy")),
        (hourly, "running", False, None, None, None, Skip("busy")),
        (hourly, "running", True, None, None, None, Repoke()),
        (capped, None, False, None, 2, None, E),
        (capped, None, False, None, 3, None, Disable(3, 3)),
        (capped, None, False, None, 4, None, Disable(4, 3)),
        (clock, None, False, None, None, None, E),
        (clock, None, False, slot_done, None, None, Skip("not_due")),
        (clock, None, True, slot_done, None, None, Skip("not_due")),
        (clock, "running", True, slot_done, None, band, Repoke()),
        (clock, None, True, None, None, band, CheckQuiet(band)),
        (hourly, None, False, None, None, band, CheckQuiet(band)),
        (hourly, None, False, None, None, "", E),
        (capped, "running", True, fresh, 3, band, Repoke()),
        (capped, "pending", False, fresh, 3, band, Skip("busy")),
        (capped, None, False, fresh, 3, band, Disable(3, 3)),
        (hourly, None, False, fresh, None, band, Skip("not_due")),
    ]
    for trig, busy, poked, last, runs, qh, want in rows:
        got = plan_rule(trig, busy=busy, poked=poked, last_fired=last, run_count=runs,
                        quiet_hours_json=qh, now=NOW, kind="promo_reactivate")
        assert got == want, (trig, busy, poked, last, runs, qh, got)


# only REPOKE_KINDS keep an under-floor poke; send_welcome spends it so a busy Creator's toasts do not run welcome every minute
def case_send_welcome_underfloor_poke_spent():
    hourly = Interval(3600, None)
    under = NOW - timedelta(seconds=POKE_FLOOR_S - 1)
    for kind, want in (("send_welcome", Skip("not_due")), ("promo_reactivate", Repoke()),
                       ("purchase_followup", Repoke())):
        got = plan_rule(hourly, busy=None, poked=True, last_fired=under, run_count=None,
                        quiet_hours_json=None, now=NOW, kind=kind)
        assert got == want, (kind, got)
        got = plan_rule(hourly, busy="running", poked=True, last_fired=under, run_count=None,
                        quiet_hours_json=None, now=NOW, kind=kind)
        assert got == (Skip("busy") if kind == "send_welcome" else Repoke()), (kind, got)
    assert REPOKE_KINDS == {"promo_reactivate", "purchase_followup"}, REPOKE_KINDS


def case_rv_c15_busy_send_welcome_poke_spent_then_idle_not_rerun():
    hourly = Interval(3600, None)
    started = NOW - timedelta(seconds=POKE_FLOOR_S + 30)
    for kind, busy_want, idle_want in (("send_welcome", Skip("busy"), Skip("not_due")),
                                       ("promo_reactivate", Repoke(), Enqueue(False))):
        got = plan_rule(hourly, busy="running", poked=True, last_fired=started, run_count=None,
                        quiet_hours_json=None, now=NOW, kind=kind)
        assert got == busy_want, (kind, got)
        got = plan_rule(hourly, busy=None, poked=busy_want == Repoke(), last_fired=started,
                        run_count=None, quiet_hours_json=None, now=NOW, kind=kind)
        assert got == idle_want, (kind, got)


def case_plan_rule_needs_runs():
    try:
        plan_rule(Interval(3600, 3), busy=None, poked=False, last_fired=None, run_count=None,
                  quiet_hours_json=None, now=NOW, kind="send_welcome")
    except ValueError:
        pass
    else:
        raise AssertionError("max_runs set, run_count None: must raise")
    assert plan_rule(Interval(3600, 3), busy="pending", poked=False, last_fired=None,
                     run_count=None, quiet_hours_json=None, now=NOW, kind="send_welcome") == Skip("busy")


def case_quiet_plan_table():
    band = "[11, 13]"
    rows = [
        (band, 0, Skip("quiet_hours")),
        (band, 120, Enqueue(no_clock=False)),
        (band, -120, Enqueue(no_clock=False)),
        (band, None, Enqueue(no_clock=True)),
        ("[0, 0]", None, Enqueue(no_clock=True)),
        ("[0, 0]", 0, Enqueue(no_clock=False)),
        ("{bad", 0, Enqueue(no_clock=False)),
    ]
    for qh, off, want in rows:
        got = quiet_plan(qh, off, NOW)
        assert got == want, (qh, off, got)


def case_dispatch_order_table():
    rank = {"send_welcome": 1, "send_followup": 4, "scrape_chats": 50}.get
    pairs = [Pair("a", "scrape_chats", False), Pair("b", "send_followup", False),
             Pair("c", "send_welcome", False), Pair("d", "send_followup", False),
             Pair("e", "scheduled_send", True), Pair("f", "send_followup", False)]
    served = {"b": 100.0, "d": 50.0}
    got = plan_dispatch(pairs, set(), served, lambda k: rank(k, 50), {"scrape_chats"})
    assert [(s.account_id, s.kind) for s in got] == [
        ("e", "scheduled_send"), ("c", "send_welcome"), ("f", "send_followup"),
        ("d", "send_followup"), ("b", "send_followup"), ("a", "scrape_chats")], got
    assert got[0] == Spawn("e", "scheduled_send", True, False)
    assert got[-1] == Spawn("a", "scrape_chats", False, True)
    got = plan_dispatch(pairs, {("f", "send_followup"), ("a", "scrape_chats")}, served,
                        lambda k: rank(k, 50), {"scrape_chats"})
    assert [s.account_id for s in got] == ["e", "c", "d", "b"], got
    got = plan_dispatch([Pair("z", K, False), Pair("m", K, False)], set(), {}, lambda k: 4, set())
    assert [s.account_id for s in got] == ["m", "z"], got
    assert len(plan_dispatch([Pair("a", K, False), Pair("a", K, True)], set(), {}, lambda k: 4, set())) == 1
    assert plan_dispatch([], set(), {}, lambda k: 4, set()) == []


# the bulk lane goes by oldest due job, never last_served (process-local: empty after a restart)
def case_bulk_dispatch_goes_by_oldest_due_job():
    B = "scrape_chats"
    pairs = [Pair("a", B, False, 300.0), Pair("z", B, False, 100.0), Pair("m", B, False, 200.0)]
    for served in ({}, {"z": 999.0, "m": 1.0}):
        got = plan_dispatch(pairs, set(), served, lambda k: 50, {B})
        assert [s.account_id for s in got] == ["z", "m", "a"], (served, got)
    got = plan_dispatch([Pair("a", K, False, 1.0), Pair("b", K, False, 2.0)], set(), {"a": 9.0}, lambda k: 4, set())
    assert [s.account_id for s in got] == ["b", "a"], got


def case_dispatch_never_mutates():
    inflight, served, pairs = {("x", K)}, {"a": 1.0}, [Pair("a", K, False), Pair("x", K, False)]
    plan_dispatch(pairs, inflight, served, lambda k: 4, set())
    assert inflight == {("x", K)} and served == {"a": 1.0} and pairs == [Pair("a", K, False), Pair("x", K, False)]


def case_per_fan_dispatch_table():
    F = "full_ai_chat"
    cap = {F: 4}

    def plan(pairs, inflight=frozenset(), per_fan=cap):
        return [(s.account_id, s.kind, s.fan) for s in
                plan_dispatch(pairs, set(inflight), {}, lambda k: 4, set(), per_fan)]
    assert plan([Pair("a", F, False, 1.0, 1), Pair("a", F, False, 2.0, 2)]) == [("a", F, 1), ("a", F, 2)]
    assert plan([Pair("a", F, False, 1.0, 1), Pair("a", F, True, 2.0, 1)]) == [("a", F, 1)]
    assert plan([Pair("a", F, False, 1.0, 1), Pair("a", F, False, 2.0, 2)], {("a", F, 1)}) == [("a", F, 2)]
    six = [Pair("a", F, False, float(10 - i), i) for i in range(6)]
    assert plan(six) == [("a", F, i) for i in (5, 4, 3, 2)], plan(six)
    assert plan(six, {("a", F, 9), ("a", F, None)}) == [("a", F, 5), ("a", F, 4)]
    assert plan(six + [Pair("b", F, False, 1.0, 1)], {("a", F, i) for i in range(10, 14)}) == [("b", F, 1)]
    assert plan(six, per_fan={F: 1}) == [("a", F, 5)]
    assert len(plan_dispatch(six, set(), {}, lambda k: 4, set())) == 1
    assert plan([Pair("a", K, False, 1.0, None), Pair("a", K, False, 2.0, None)]) == [("a", K, None)]
    assert plan([Pair("a", K, False)], {("a", K)}) == []
    assert run_key("a", K, 7, cap) == ("a", K) and run_key("a", F, 7, cap) == ("a", F, 7)
    rr = [Pair(a, F, False, float(i), 10 * i + (a == "b")) for a in ("a", "b") for i in range(4)]
    rr.append(Pair("c", K, False, 9.0))
    got = plan(rr)
    assert len(got) == 9, got
    assert got[:3] == [("a", F, 0), ("b", F, 1), ("c", K, None)], got
    assert got[3:] == [("a", F, 10), ("b", F, 11), ("a", F, 20), ("b", F, 21), ("a", F, 30), ("b", F, 31)], got
    assert {acc for acc, *_ in got[:4]} == {"a", "b", "c"}, got
    got = plan(rr[:-1], {("a", F, 99), ("a", F, 98)})
    assert got[:2] == [("b", F, 1), ("b", F, 11)] and got[2] == ("a", F, 0), got


def case_parse_iso_table():
    rows = [
        ("2026-10-30T12:00:00+00:00", datetime(2026, 10, 30, 12, 0)),
        ("2026-10-30T12:00:00Z", datetime(2026, 10, 30, 12, 0)),
        ("2026-10-30T12:00:00+02:00", datetime(2026, 10, 30, 10, 0)),
        ("2026-10-30T01:30:00-05:30", datetime(2026, 10, 30, 7, 0)),
        ("2026-10-30T23:00:00-02:00", datetime(2026, 10, 31, 1, 0)),
        ("2026-10-30T12:00:00", datetime(2026, 10, 30, 12, 0)),
        ("2026-10-30T12:00:00.250+00:00", datetime(2026, 10, 30, 12, 0, 0, 250000)),
        ("2026-10-30T12:00:00.123456Z", datetime(2026, 10, 30, 12, 0, 0, 123456)),
        ("garbage", None), ("", None), (None, None), (12345, None), (["2026-10-30"], None),
    ]
    for raw, want in rows:
        got = parse_iso(raw)
        assert got == want and (got is None or got.tzinfo is None), (raw, got)


_harness.run()
