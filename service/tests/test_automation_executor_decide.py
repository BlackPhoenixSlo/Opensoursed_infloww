#!/usr/bin/env python3
"""
dispatch_plan — table tests over the automation dispatch rules' pure helpers (the shell is
automation_executor: `_materialize_due_rules` reads the DB facts in its gate order and calls
these; `_drain_due_jobs_once` spawns what plan_dispatch returns). No DB, no loop:

  case_trigger_table:          what a decoded trigger_json fires on: non-positive / bool /
                               string intervals and an empty or non-list daily_at -> None;
                               an interval wins over a clock; tz_offset_minutes coerced to int,
                               0 by default.
  case_bad_tz_table:           a clock's tz_offset_minutes outside the API's 422 contract ("x",
                               "", "1.5", "60", 9999, True, NaN) -> None from trigger_of and
                               parse_trigger alike (skipped, never raised: one bad row must not
                               abort the pass); parse_trigger logs it once per raw value,
                               trigger_of never; null / absent -> 0; an interval ignores it.
  case_next_due_table:         next_due, the shown next fire: interval never fired / mid-cadence
                               / overdue; clock before / after today's slot, owed, tomorrow, tz
                               offset; max_runs reached -> None; no valid slot -> None; max_runs with no
                               run_count -> ValueError (plan_rule's contract).
  case_next_due_agrees_with_due: over a day of `now`s, next_due <= now iff interval_due /
                               clock_due (one voice with the materializer).
  case_max_runs_table:         max_runs > 0 kept as int (2.5 -> 2); 0, negative, bool, string,
                               Infinity / 1e400 / NaN ignored (the shell disables the rule at
                               runs >= max_runs); a non-finite every_seconds is no interval.
  case_interval_cadence_table: due at every_seconds since the rule's own last job; a poke
                               shortens the wait down to min(every, POKE_FLOOR_S), not below.
  case_clock_trigger_table:    a daily_at slot is due once per day after it passes, in the
                               trigger's local offset; a later slot still owed is due.
  case_quiet_hours_table:      inside the creator-local band; wrap, dict form, [0,0], half
                               hours, no clock (never inside), malformed (never inside).
  case_plan_rule_table:        one rule's step: busy (a running poked pair re-pokes), run limit,
                               due, in that precedence; then a band -> CheckQuiet, else Enqueue.
                               A poke never makes a clock rule due.
  case_plan_rule_needs_runs:   max_runs set and run_count None -> ValueError (shell invariant).
  case_quiet_plan_table:       the band gate: inside -> Skip; outside -> Enqueue; no clock ->
                               Enqueue(no_clock=True) (the shell warns once).
  case_dispatch_order_table:   operator first, then kind rank, then least recently served,
                               then account id; in-flight pairs not spawned; the bulk lane.
  case_dispatch_never_mutates: inputs untouched.
  case_parse_iso_table:        isotime.parse_iso (the shell's `_parse_iso`): naive UTC out; an
                               offset converted, Z, naive, fractional; garbage / non-str -> None.

Run: ./venv/bin/python service/tests/test_automation_executor_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import logging  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from isotime import parse_iso  # noqa: E402

from dispatch_plan import (  # noqa: E402
    POKE_FLOOR_S, CheckQuiet, Clock, Disable, Enqueue, Interval, Pair, Repoke, Skip, Spawn, clock_due,
    in_quiet_hours, interval_due, next_due, parse_trigger, plan_dispatch, plan_rule, quiet_plan,
    trigger_of,
)

NOW = datetime(2026, 10, 30, 12, 0, 0)
K = "send_followup"


def case_trigger_table():
    rows = [   # (decoded trigger_json, Interval | Clock | None)
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
    rows = [   # (tz_offset_minutes, Clock's tz_off_min | None = skipped)
        ("x", None), ("", None), ("1.5", None), ("60", None), (9999, None), (-9999, None),
        (841, None), (-721, None), (True, None), (False, None), (float("nan"), None),
        (float("inf"), None), ([60], None), ({"m": 60}, None),
        (None, 0), (0, 0), (840, 840), (-720, -720), (1.5, 1), (-90.0, -90), (330, 330),
    ]
    for raw, want in rows:
        for parse in (trigger_of, parse_trigger):
            got = parse({"daily_at": ["09:00"], "tz_offset_minutes": raw})
            assert got == (None if want is None else Clock(("09:00",), want, None)), (parse, raw, got)
    assert parse_trigger({"daily_at": ["09:00"]}) == Clock(("09:00",), 0, None)   # absent
    # an interval never reads the zone
    assert parse_trigger({"every_seconds": 60, "tz_offset_minutes": "x"}) == Interval(60, None)
    # parse_trigger logs once per distinct raw value, with the value; trigger_of never
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
    rows = [   # (trigger, last_fired, run_count, next_due)
        (Interval(3600, None), None, None, NOW),                                  # never fired: due now
        (Interval(3600, None), NOW - timedelta(minutes=20), None, NOW + timedelta(minutes=40)),
        (Interval(3600, None), NOW - timedelta(hours=3), None, NOW - timedelta(hours=2)),   # overdue
        (Clock(("09:00",), 0, None), None, None, NOW.replace(hour=9)),             # after today's slot, owed
        (Clock(("09:00",), 0, None), NOW.replace(hour=9, minute=1), None, NOW.replace(hour=9) + d),
        (Clock(("13:00",), 0, None), None, None, NOW.replace(hour=13)),            # before today's slot
        (Clock(("13:00",), 0, None), NOW - d, None, NOW.replace(hour=13)),
        (Clock(("09:00", "15:00"), 0, None), NOW.replace(hour=9, minute=1), None, NOW.replace(hour=15)),
        (Clock(("13:00",), 120, None), None, None, NOW.replace(hour=11)),          # 13:00 at UTC+2 = 11:00 UTC
        (Clock(("13:00",), 120, None), NOW.replace(hour=11, minute=5), None, NOW.replace(hour=11) + d),
        (Clock(("11:30",), -60, None), None, None, NOW.replace(hour=12, minute=30)),   # UTC-1
        (Clock(("00:30",), 720, None), None, None, NOW.replace(hour=12, minute=30)),   # local day is tomorrow
        (Clock(("bad", "25:00"), 0, None), None, None, None),                      # no valid slot
        (Interval(3600, 3), None, 3, None),                                        # max_runs reached
        (Interval(3600, 3), None, 5, None),
        (Clock(("09:00",), 0, 2), None, 2, None),
        (Interval(3600, 3), None, 2, NOW),                                         # one run left
    ]
    for trig, last, runs, want in rows:
        got = next_due(trig, last, NOW, run_count=runs)
        assert got == want, (trig, last, runs, got, want)
    for trig in (Interval(3600, 3), Clock(("09:00",), 0, 2)):   # max_runs, run_count not given
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
                if not due:   # and at that instant it is due
                    if isinstance(trig, Interval):
                        assert interval_due(trig.every, last, nd, False), (trig, last, nd)
                    else:
                        assert clock_due(nd, trig.times, trig.tz_off_min, last), (trig, last, now, nd)


def case_max_runs_table():
    inf, nan = float("inf"), float("nan")
    rows = [(3, 3), (2.5, 2), (1, 1), (0, None), (-1, None), (True, None), ("3", None), (None, None),
            (inf, None), (1e400, None), (-inf, None), (nan, None)]   # stored Infinity: no OverflowError
    for mx, want in rows:
        for parse in (trigger_of, parse_trigger):
            assert parse({"every_seconds": 60, "max_runs": mx}).max_runs == want, (parse, mx)
            assert parse({"daily_at": ["09:00"], "max_runs": mx}).max_runs == want, (parse, mx)
    # a non-finite every_seconds is no interval (a clock beside it still applies)
    for every in (inf, 1e400, nan):
        assert trigger_of({"every_seconds": every}) is None, every
        assert trigger_of({"every_seconds": every, "daily_at": ["09:00"]}) == Clock(("09:00",), 0, None)


def case_interval_cadence_table():
    rows = [   # (every, age_s or None, poked, due)
        (3600, None, False, True),                 # never fired
        (3600, 3599, False, False),
        (3600, 3600, False, True),
        (3600, 4000, False, True),
        (3600, POKE_FLOOR_S, True, True),          # a poke: due from the floor
        (3600, POKE_FLOOR_S - 1, True, False),     # under the floor: spent, the cadence covers it
        (3600, POKE_FLOOR_S, False, False),        # ... and without the poke, not due
        (30, 29, True, False),                     # floor = min(every, 60) = 30
        (30, 30, False, True),
        (0.5, 0.5, False, True),
        (3600, -5, False, False),                  # a job stamped in the future
        (3600, -5, True, False),
    ]
    for every, age, poked, want in rows:
        last = None if age is None else NOW - timedelta(seconds=age)
        got = interval_due(every, last, NOW, poked)
        assert got is want, (every, age, poked, got)


def case_clock_trigger_table():
    rows = [   # (daily_at, tz_offset_minutes, last_fired, due)
        (["09:00"], 0, None, True),
        (["09:00"], 0, NOW.replace(hour=8), True),              # last job before today's slot
        (["09:00"], 0, NOW.replace(hour=9, minute=1), False),
        (["13:00"], 0, None, False),                            # not yet today
        (["13:00"], 120, None, True),                           # 13:00 at UTC+2 = 11:00 UTC
        (["11:30"], -60, None, False),                          # 11:30 at UTC-1 = 12:30 UTC
        (["bad", "25:00", "09:60", 9], 0, None, False),
        (["09:00", "11:00"], 0, NOW.replace(hour=10), True),    # the 11:00 slot is still owed
        (["09:00", "11:00"], 0, NOW.replace(hour=11, minute=1), False),
        (["09:00", "11:00"], 0, None, True),
    ]
    for times, off, last, want in rows:
        got = clock_due(NOW, times, off, last)
        assert got is want, (times, off, last, got)


def case_quiet_hours_table():
    rows = [   # (band json, tz_off_min, now hour UTC, inside)
        ("[11, 13]", 0, 12, True),
        ("[11, 13]", 0, 13, False),                 # end exclusive
        ("[11, 13]", 120, 12, False),               # 14:00 local
        ("[22, 6]", 0, 23, True),                   # wraps past midnight
        ("[22, 6]", 0, 5, True),
        ("[22, 6]", 0, 6, False),
        ('{"start": 11, "end": 13}', 0, 12, True),
        ("[0, 0]", 0, 12, False),                   # disabled
        ("[11, 13]", None, 12, False),              # no clock: no local band (the shell warns once)
        ("[12, 13]", 330, 6, True),                 # +5:30: 06:40 UTC is 12:10 local
        ("[12, 13]", 330, 5, False),                # 05:40 UTC is 11:10 local
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
    rows = [   # (trig, busy, poked, last_fired, run_count, band, plan)
        (hourly, None, False, None, None, None, E),
        (hourly, None, False, old, None, None, E),
        (hourly, None, False, fresh, None, None, Skip("not_due")),
        (hourly, None, True, fresh, None, None, E),                       # a poke past the floor
        (hourly, "pending", False, None, None, None, Skip("busy")),
        (hourly, "pending", True, None, None, None, Skip("busy")),        # that job will see it
        (hourly, "running", False, None, None, None, Skip("busy")),
        (hourly, "running", True, None, None, None, Repoke()),
        (capped, None, False, None, 2, None, E),
        (capped, None, False, None, 3, None, Disable(3, 3)),
        (capped, None, False, None, 4, None, Disable(4, 3)),
        (clock, None, False, None, None, None, E),
        (clock, None, False, slot_done, None, None, Skip("not_due")),
        (clock, None, True, slot_done, None, None, Skip("not_due")),      # a poke: no clock slot
        (clock, "running", True, slot_done, None, band, Repoke()),
        (clock, None, True, None, None, band, CheckQuiet(band)),
        (hourly, None, False, None, None, band, CheckQuiet(band)),
        (hourly, None, False, None, None, "", E),                         # unset band: no clock read
        # precedence: busy > run limit > due > quiet band
        (capped, "running", True, fresh, 3, band, Repoke()),
        (capped, "pending", False, fresh, 3, band, Skip("busy")),
        (capped, None, False, fresh, 3, band, Disable(3, 3)),
        (hourly, None, False, fresh, None, band, Skip("not_due")),
    ]
    for trig, busy, poked, last, runs, qh, want in rows:
        got = plan_rule(trig, busy=busy, poked=poked, last_fired=last, run_count=runs,
                        quiet_hours_json=qh, now=NOW)
        assert got == want, (trig, busy, poked, last, runs, qh, got)


def case_plan_rule_needs_runs():
    try:
        plan_rule(Interval(3600, 3), busy=None, poked=False, last_fired=None, run_count=None,
                  quiet_hours_json=None, now=NOW)
    except ValueError:
        pass
    else:
        raise AssertionError("max_runs set, run_count None: must raise")
    # busy wins before the run limit is looked at (the shell reads run_count anyway)
    assert plan_rule(Interval(3600, 3), busy="pending", poked=False, last_fired=None,
                     run_count=None, quiet_hours_json=None, now=NOW) == Skip("busy")


def case_quiet_plan_table():
    band = "[11, 13]"   # NOW is 12:00 UTC: inside at offset 0
    rows = [   # (band, tz_off_min, plan)
        (band, 0, Skip("quiet_hours")),
        (band, 120, Enqueue(no_clock=False)),        # 14:00 local
        (band, -120, Enqueue(no_clock=False)),       # 10:00 local
        (band, None, Enqueue(no_clock=True)),        # no clock: band cannot apply, warn
        ("[0, 0]", None, Enqueue(no_clock=True)),    # disabled band, no clock: still warns (as HEAD)
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
    served = {"b": 100.0, "d": 50.0}   # f never served (0.0), then d, then b
    got = plan_dispatch(pairs, set(), served, lambda k: rank(k, 50), {"scrape_chats"})
    assert [(s.account_id, s.kind) for s in got] == [
        ("e", "scheduled_send"), ("c", "send_welcome"), ("f", "send_followup"),
        ("d", "send_followup"), ("b", "send_followup"), ("a", "scrape_chats")], got
    assert got[0] == Spawn("e", "scheduled_send", True, False)
    assert got[-1] == Spawn("a", "scrape_chats", False, True)
    # in flight: not spawned again; the rest keep their order
    got = plan_dispatch(pairs, {("f", "send_followup"), ("a", "scrape_chats")}, served,
                        lambda k: rank(k, 50), {"scrape_chats"})
    assert [s.account_id for s in got] == ["e", "c", "d", "b"], got
    # a tie on everything but the account id: id order
    got = plan_dispatch([Pair("z", K, False), Pair("m", K, False)], set(), {}, lambda k: 4, set())
    assert [s.account_id for s in got] == ["m", "z"], got
    # the same pair twice: one spawn
    assert len(plan_dispatch([Pair("a", K, False), Pair("a", K, True)], set(), {}, lambda k: 4, set())) == 1
    assert plan_dispatch([], set(), {}, lambda k: 4, set()) == []


def case_dispatch_never_mutates():
    inflight, served, pairs = {("x", K)}, {"a": 1.0}, [Pair("a", K, False), Pair("x", K, False)]
    plan_dispatch(pairs, inflight, served, lambda k: 4, set())
    assert inflight == {("x", K)} and served == {"a": 1.0} and pairs == [Pair("a", K, False), Pair("x", K, False)]


def case_parse_iso_table():
    rows = [   # (input, naive UTC datetime | None)
        ("2026-10-30T12:00:00+00:00", datetime(2026, 10, 30, 12, 0)),
        ("2026-10-30T12:00:00Z", datetime(2026, 10, 30, 12, 0)),
        ("2026-10-30T12:00:00+02:00", datetime(2026, 10, 30, 10, 0)),      # converted, not dropped
        ("2026-10-30T01:30:00-05:30", datetime(2026, 10, 30, 7, 0)),
        ("2026-10-30T23:00:00-02:00", datetime(2026, 10, 31, 1, 0)),       # across midnight
        ("2026-10-30T12:00:00", datetime(2026, 10, 30, 12, 0)),            # naive: taken as UTC
        ("2026-10-30T12:00:00.250+00:00", datetime(2026, 10, 30, 12, 0, 0, 250000)),
        ("2026-10-30T12:00:00.123456Z", datetime(2026, 10, 30, 12, 0, 0, 123456)),
        ("garbage", None), ("", None), (None, None), (12345, None), (["2026-10-30"], None),
    ]
    for raw, want in rows:
        got = parse_iso(raw)
        assert got == want and (got is None or got.tzinfo is None), (raw, got)


_harness.run()
