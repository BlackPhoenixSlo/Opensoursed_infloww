#!/usr/bin/env python3
"""
purchase_poll_decide — the purchases poll's tier and due decisions (phase-01 1a), as tables.
No DB, no loop; `now` is passed.

  case_tier_table:   (leased, seller) -> fast when either, slow otherwise.
  case_due_table:    no state -> due; fast every tick (30 s, half a tick of slack for a cycle
                     landing early); slow every 300 s; a Creator gaining Demand is due on the
                     next tick.
  case_first_idle_state_spreads: an Idle Creator never polled comes due within SLOW_S at a stable
                     per-Creator phase; 200 Creators spread over the 10 cycles.
  case_ladder_asked_wait_and_rung: the hold is max(OF's ask, the rung): "allow 1 seconds" still climbs.
  case_hold_counts_from_the_answer: last-ok = the poll's start, the hold from OF's answer.
  case_demand_cap:   a Demand Creator's hold never passes 120 s, a longer ask included; no poll before it.
  case_reset_on_ok_and_outcomes / case_due_respects_the_hold_and_the_interval /
  case_polled_and_first_idle_state_keep_the_rest / case_catch_up_after_a_gap.
  (The knobs' parse: test_env_knob.py.)

Run: ./venv/bin/python service/tests/test_purchase_poll_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import purchase_poll_decide as d  # noqa: E402
from purchase_poll_decide import PollState  # noqa: E402


def case_tier_table():
    for leased, seller, want in ((True, False, "fast"), (False, True, "fast"), (True, True, "fast"),
                                 (False, False, "slow")):
        assert d.tier(leased, seller) == want, (leased, seller)


def case_due_table():
    assert (d.FAST_S, d.SLOW_S) == (30.0, 300.0)
    rows = [
        # (state, tier, now, due)
        (None, "fast", 0, True),
        (None, "slow", 0, True),
        (PollState(100), "fast", 100, False),
        (PollState(100), "fast", 114.9, False),
        (PollState(100), "fast", 129.98, True),     # the next cycle, a hair early
        (PollState(100), "fast", 130, True),
        (PollState(100), "slow", 130, False),
        (PollState(100), "slow", 370, False),       # 9 ticks
        (PollState(100), "slow", 399.9, True),      # the 10th tick
        (PollState(100), "slow", 400, True),
    ]
    for state, tier, now, want in rows:
        assert d.due(state, tier, now) is want, (state, tier, now, want)
    # Idle polled at 100, leased at 110: the 130 tick polls it (fast now).
    assert d.due(PollState(100), d.tier(True, False), 130)


def case_first_idle_state_spreads():
    slots = round(d.SLOW_S / d.FAST_S)                                # 10 cycles of 30 s
    ids = [str(100_000 + 37 * i) for i in range(200)]
    first_due = {}
    for aid in ids:
        st = d.first_idle_state(aid, 1000.0, None)
        assert st == d.first_idle_state(aid, 1000.0, None), "stable per Creator"
        k = next(k for k in range(slots + 1) if d.due(st, "slow", 1000.0 + k * d.FAST_S))
        assert k < slots, (aid, k)                                     # due within one SLOW_S
        first_due[aid] = k
    per_cycle = [sum(1 for k in first_due.values() if k == c) for c in range(slots)]
    assert max(per_cycle) <= 2 * len(ids) / slots, per_cycle           # spread, not one cycle
    assert min(per_cycle) >= 1, per_cycle


RL = d.Outcome("rate_limited")
OK = d.Outcome("ok")
ALLOW1 = d.Outcome("rate_limited", retry_after_s=1.0)     # OF's usual body: "Please allow 1 seconds"


def _after(state, outcome, now):
    """A poll started and answered at `now`."""
    return d.after(state, outcome, now, now)


def _holds(state, tier, now):
    """The seconds from `now` until a poll may start (1 s steps): `due` and the gate (no look-ahead) both
    say yes, the tier interval set aside."""
    s = d.PollState(None, state.last_ok_s, state.step, state.held_at, state.hold_s)
    return next(k for k in range(0, 2000) if d.due(s, tier, now + k) and not d.held(s, tier, now + k, 0.0))


def _first_poll(s, cycles):
    """The first loop cycle that polls: `due` (a tick ahead) and the _single_flight gate (none)."""
    return next(t for t in cycles if d.due(s, "fast", t) and not d.held(s, "fast", t, 0.0))


def case_ladder_asked_wait_and_rung():
    """30 -> 60 -> 120 -> 240 -> 480 -> 900 -> 900 (Idle); the hold is the longer of OF's ask and the rung,
    so OF's usual "allow 1 seconds" never stops the climb, and a longer ask wins."""
    assert (d.BACKOFF_BASE_S, d.BACKOFF_MAX_S, d.BACKOFF_DEMAND_MAX_S, d.CATCHUP_MAX_PAGES) == (30, 900, 120, 3)
    for outcome in (RL, ALLOW1):
        s, holds = None, []
        for _ in range(7):
            s = _after(s, outcome, 1000.0)
            holds.append(_holds(s, "slow", 1000.0))
        assert holds == [30, 60, 120, 240, 480, 900, 900], (outcome, holds)
    s = _after(None, d.Outcome("rate_limited", retry_after_s=45.0), 0.0)
    assert _holds(s, "slow", 0.0) == 45, "an ask over the rung: the ask"
    s = _after(s, d.Outcome("rate_limited", retry_after_s=7.0), 0.0)
    assert _holds(s, "slow", 0.0) == 60, "an ask under the climbed rung: the rung"
    s = _after(s, d.Outcome("rate_limited", retry_after_s=2000.0), 0.0)
    assert d.held(s, "slow", 1999.9, 0.0) and not d.held(s, "slow", 2000.0, 0.0), "uncapped for an Idle Creator"


def case_hold_counts_from_the_answer():
    """last-ok is the poll's start; a hold runs from OF's answer, so a slow answer never shortens OF's wait."""
    s = d.after(None, OK, 10.0, 12.5)
    assert s.last_ok_s == 10.0
    s = d.after(s, d.Outcome("rate_limited", retry_after_s=40.0), 20.0, 23.0)
    assert s.held_at == 23.0 and s.last_ok_s == 10.0, s
    assert d.held(s, "fast", 62.9, 0.0) and not d.held(s, "fast", 63.0, 0.0)


def case_demand_cap():
    """A Demand Creator's hold never passes 120 s, a longer ask included, and no poll starts before it: `due` looks a
    tick ahead, the gate (look-ahead 0) holds until held_at + hold_s; a Creator gaining Demand mid-hold is capped
    from its last failure."""
    s = None
    for _ in range(6):
        s = _after(s, RL, 0.0)                         # 900 s asked by the rung
    assert d.hold_s(s, "fast") == 120 and d.hold_s(s, "slow") == 900
    assert d.held(s, "fast", 119.9, 0.0) and not d.held(s, "fast", 120.0, 0.0), "the gate: the cap, never before"
    ticks = [k * d.FAST_S for k in range(10)]
    assert _first_poll(s, ticks) == 120, "cycles 30 s apart from the answer: 120 s"
    off = [0.5 + k * d.FAST_S for k in range(10)]      # cycles a hair after the answer
    assert d.due(s, "fast", 120.5 - d.FAST_S), "due: the next tick would pass the cap"
    assert d.held(s, "fast", 120.5 - d.FAST_S, 0.0), "the gate: inside the cap, no poll"
    assert _first_poll(s, off) == 120.5, "the first cycle at or after the cap"
    s = _after(None, d.Outcome("rate_limited", retry_after_s=600.0), 0.0)
    assert _first_poll(s, ticks) == 120, "the cap wins over a longer ask"
    s = _after(None, d.Outcome("rate_limited", retry_after_s=45.0), 0.0)
    assert _first_poll(s, ticks) == 60, "an ask under the cap: honoured, next tick"
    idle = None
    for _ in range(6):
        idle = _after(idle, RL, 0.0)
    assert _holds(idle, "slow", 0.0) == 900, "Idle: the rung"
    assert d.held(idle, "slow", 500.0, 0.0) and not d.held(idle, "fast", 120.0, 0.0), "gaining Demand: capped"


def case_reset_on_ok_and_outcomes():
    s = None
    for _ in range(4):
        s = _after(s, RL, 0.0)
    s = _after(s, OK, 10.0)
    assert not d.held(s, "slow", 10.0, 0.0) and s.last_ok_s == 10.0 and s.step == 0
    assert _holds(_after(s, RL, 10.0), "slow", 10.0) == 30, "after an ok the ladder starts again"
    # unauthorized (a 401 the strict classifier does not call dead) climbs like a 429
    u = None
    holds = []
    for _ in range(3):
        u = _after(u, d.Outcome("unauthorized"), 0.0)
        holds.append(_holds(u, "slow", 0.0))
    assert holds == [30, 60, 120], holds
    # dead holds nothing: no hold, no rung; the poll schedule kept
    dead = _after(d.PollState(5.0, 4.0, 3, 4.0, 120.0), d.Outcome("dead", reason="wrong_user"), 9.0)
    assert dead == d.PollState(5.0, 4.0), dead
    # error: no climb, no hold (today's retry on the next due cycle); no failure is ever an ok
    e = d.PollState(5.0, 4.0)
    for kind in ("error", "rate_limited", "unauthorized", "dead"):
        assert _after(e, d.Outcome(kind), 9.0).last_ok_s == 4.0, kind
    assert _after(e, d.Outcome("error"), 9.0) == e
    assert _after(None, d.Outcome("error"), 9.0) == d.PollState()
    assert d.due(_after(None, d.Outcome("error"), 9.0), "fast", 9.0)


def case_due_respects_the_hold_and_the_interval():
    s = _after(d.PollState(100.0), RL, 100.2)               # held 30 s from OF's answer
    assert not d.due(s, "fast", 130.0) and d.due(s, "fast", 130.2)
    s = _after(d.PollState(100.0), d.Outcome("rate_limited", retry_after_s=40.0), 100.2)
    assert not d.due(s, "fast", 130.0) and d.due(s, "fast", 160.0), "OF's 40 s honoured: the second tick"
    s = _after(d.PollState(100.0), RL, 100.0)
    assert not d.due(s, "slow", 131.0) and d.due(s, "slow", 400.0), "Idle: the slow interval still applies"


def case_polled_and_first_idle_state_keep_the_rest():
    """The loop's stamps move `last_s` only: the hold and last-ok stay."""
    s = d.after(None, d.Outcome("rate_limited", retry_after_s=40.0), 3.0, 4.0)
    assert d.polled(s, 50.0) == d.PollState(50.0, None, 1, 4.0, 40.0)
    assert d.polled(None, 50.0) == d.PollState(50.0)
    st = d.first_idle_state("8801", 1000.0, s)
    assert (st.step, st.held_at, st.hold_s) == (1, 4.0, 40.0) and st.last_s is not None


def case_catch_up_after_a_gap():
    assert d.catch_up(None, 0.0), "no state (a restart): page back"
    assert d.catch_up(d.PollState(0.0), 0.0), "never an ok poll: page back"
    ok = _after(d.PollState(0.0), OK, 100.0)
    assert not d.catch_up(ok, 130.0), "one fast interval: no"
    assert not d.catch_up(ok, 160.0), "fast + one tick: no"
    assert d.catch_up(ok, 160.1), "longer: page back"
    assert d.catch_up(ok, 100.0 + d.SLOW_S), "an Idle Creator's slow gap: page back"


_harness.run()
