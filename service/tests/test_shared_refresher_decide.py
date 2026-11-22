#!/usr/bin/env python3
"""shared_refresher_decide (phase-01 seam 1), as tables. Pure: no clock, no I/O; `now` is passed.

  case_cycle_and_floor:      Knob 10 -> 60 on both tiers; a tab cycle below the lease cycle reads at the lease cycle.
  case_cycle_spread:         `cycle_s` per Creator in [0.9 x tier, tier], >= 60, stable per Creator, spread.
  case_lease_gain_and_loss:  a lease gain or loss changes `cycle_s`: one Publish; next due within the new cycle.
  case_restart_spread:       50 Creators first seen together: first reads spread inside FLOOR_S, not in one tick.
  case_fifty_by_thirty:      50 Creators x 30 clamps, 10 leased: one Read per due Creator; gaps = its own cycle.
  case_first_read_spread:    never read: due at first_seen + h(aid) x FLOOR_S, inside FLOOR_S, stable per Creator.
  case_due_at_last_plus_cycle: due at `last + cycle_s`, not before.
  case_due_after_warm:       a Creator due (or held) that a warm just read (its Last refresh, shared_refresher.note_refresh)
                             waits for its next slot: not due now, due at the warm's ask + `cycle_s`.
  case_skips:                not tracked, tracked but not readable, warm-pending, in flight, held: no Read.
  case_tracked_empty:        the last tab closed: no effect.
  case_flat_in_subscribers:  one Read per Creator, however many tabs see it (`tracked` is a set).
  case_publish_on_first_track_and_change: entering `tracked` publishes once; re-entry keeps Last refresh, publishes.
  case_after_read:           ok writes Last refresh (the ask time); a failure keeps it, holds the Creator FLOOR_S.
  case_backoff_ladder:       failures in a row hold max(60, purchase_poll_decide.ladder_s(n)) from each ask, `at`
                             kept, reset on ok; ticked, a failing Creator's attempts are never under 60 s apart;
                             a 1025th failure in a row still holds 900 s (no exponent overflow).
  case_live_of:              dead map -> "dead"; tracked, not readable (deactivated, no session, Fansly) -> None, never
                             "down"; socket stamp set -> "up", unset -> "down".
  case_dead_skip:            a Dead session: no Read, `live` "dead", `cycle_s` None, published.
  case_live_flip_publishes_without_read: up -> down -> up publishes each flip with no Read; `live_since` restarts on
                             each change, kept while unchanged, dropped with `live` None or untrack.
  case_changed:              `at` alone, a slot's `at` alone -> no change; values, `live`, `cycle_s`, first track ->
                             change; the plan publishes a moved value with no Read.
  case_window_due:           socket down now; reconnected after the window's last read; a contributor asked -> due;
                             no window held, or none of these (WS-kept since the read) -> not due.

Run: ./venv/bin/python service/tests/test_shared_refresher_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import shared_refresher_decide as d  # noqa: E402
from shared_refresher_decide import Inputs, Knobs, Publish, Read, State  # noqa: E402

K = Knobs(lease_cycle_s=120.0, tab_cycle_s=600.0)
A, B = "9101", "9102"


def _reads(effects) -> list[str]:
    return [e.account_id for e in effects if isinstance(e, Read)]


def _pubs(effects) -> list[str]:
    return [e.account_id for e in effects if isinstance(e, Publish)]


def _inp(now, tracked, readable=None, **kw) -> Inputs:
    tracked = frozenset(tracked)
    return Inputs(now=now, tracked=tracked, readable=tracked if readable is None else frozenset(readable), **kw)


def case_cycle_and_floor():
    assert d.FLOOR_S == 60.0 and d.SPREAD == 0.1
    assert Knobs() == K, "defaults: lease 120, tab 600"
    low = Knobs(lease_cycle_s=10.0, tab_cycle_s=10.0)
    for aid in (A, B, "1", "x" * 40):
        assert d.cycle_s(True, aid, low) == 60.0, "a lease Knob under the floor reads at the floor"
        assert d.cycle_s(False, aid, low) == 60.0, "a tab Knob under the floor reads at the floor"
        inv = Knobs(lease_cycle_s=300.0, tab_cycle_s=120.0)
        assert d.cycle_s(False, aid, inv) == d.cycle_s(True, aid, inv), "tab cycle below lease -> lease"
        assert 270.0 <= d.cycle_s(False, aid, inv) <= 300.0


def case_cycle_spread():
    aids = [str(i) for i in range(200)] + [A, B, "x" * 40]
    for aid in aids:
        lc, tc = d.cycle_s(True, aid, K), d.cycle_s(False, aid, K)
        assert 108.0 <= lc <= 120.0, (aid, lc)
        assert 540.0 <= tc <= 600.0, (aid, tc)
        assert lc >= 60.0 and tc >= 60.0
        assert d.cycle_s(True, aid, K) == lc and d.cycle_s(False, aid, K) == tc, "stable per Creator"
        assert d.cycle_s(True, aid, Knobs(lease_cycle_s=60.0)) == 60.0, "never under 60, even spread"
    assert len({round(d.cycle_s(False, a, K)) for a in aids}) > 40, "periods differ per Creator: slots drift apart"


def case_first_read_spread():
    for aid in (A, B, "1", "x" * 40):
        h = d.h(aid)
        assert 0.0 <= h < 1.0 and d.h(aid) == h, aid
        assert d.due_at(None, 600.0, aid, 1000.0) == 1000.0 + h * d.FLOOR_S
    hs = {round(d.h(str(i)), 3) for i in range(200)}
    assert len(hs) > 150, "first reads spread, not bunched"
    # In plan: never due before its spread slot, always due inside FLOOR_S of first being seen.
    st, _ = d.plan(State(), _inp(0.0, [A]), K)
    slot = d.h(A) * d.FLOOR_S
    assert slot > 1.0, "fixture: A's slot is not at 0"
    assert _reads(d.plan(st, _inp(slot - 0.01, [A]), K)[1]) == []
    assert _reads(d.plan(st, _inp(slot, [A]), K)[1]) == [A]
    assert _reads(d.plan(st, _inp(d.FLOOR_S, [A]), K)[1]) == [A]


def case_due_at_last_plus_cycle():
    st = d.after_read(State(), A, True, 100.0)
    c = d.cycle_s(False, A, K)
    assert d.due_at(100.0, c, A, 0.0) == 100.0 + c
    for now, want in ((100.0, []), (100.0 + c - 0.001, []), (100.0 + c, [A]), (100.0 + c + 5, [A])):
        assert _reads(d.plan(st, _inp(now, [A]), K)[1]) == want, now


def case_due_after_warm():
    c = d.cycle_s(False, A, K)
    due = d.after_read(State(), A, True, 0.0)                 # last read long ago: due now
    held = d.after_read(due, A, False, 9_000.0)                # and held by a failed attempt
    now = 10_000.0
    assert _reads(d.plan(due, _inp(now, [A]), K)[1]) == [A], "fixture: due before the warm"
    for st in (due, held):
        warmed = d.after_read(st, A, True, now)               # the warm's kept /users/me, at its ask time
        assert warmed.last[A] == now and A not in warmed.held, warmed
        for t, want in ((now, []), (now + c - 0.001, []), (now + c, [A])):
            assert _reads(d.plan(warmed, _inp(t, [A]), K)[1]) == want, (t, want)


def _read_long_ago(*aids) -> State:
    st = State()
    for aid in aids:
        st = d.after_read(st, aid, True, 0.0)
    return st


def case_skips():
    st = _read_long_ago(A, B)
    now = 10_000.0
    assert _reads(d.plan(st, _inp(now, [], readable=[A]), K)[1]) == [], "readable but not tracked"
    assert _reads(d.plan(st, _inp(now, [A], readable=[]), K)[1]) == [], "tracked, not readable (dead, no pump, Fansly)"
    assert _reads(d.plan(st, _inp(now, [A], warm_pending=frozenset({A})), K)[1]) == [], "warm-pending"
    assert _reads(d.plan(st, _inp(now, [A], in_flight=frozenset({A})), K)[1]) == [], "in flight: no second Read"
    held = d.after_read(st, A, False, now)
    assert _reads(d.plan(held, _inp(now + 1, [A]), K)[1]) == [], "held after a failed attempt"
    assert _reads(d.plan(st, _inp(now, [A, B], in_flight=frozenset({A})), K)[1]) == [B]


def case_tracked_empty():
    st = d.after_read(State(), A, True, 0.0)
    st, _ = d.plan(st, _inp(1.0, [A]), K)
    st2, eff = d.plan(st, _inp(10_000.0, []), K)
    assert eff == [], eff
    assert st2.last == {A: 0.0}, "leaving `tracked` keeps the Last refresh"


def case_flat_in_subscribers():
    # The shell unions every tab's clamp into one set: 1 tab or 30 tabs on A and B is the same input.
    clamps = [frozenset({A, B})] * 30
    tracked = frozenset().union(*clamps)
    _, eff = d.plan(_read_long_ago(A, B), _inp(10_000.0, tracked), K)
    assert sorted(_reads(eff)) == [A, B] and len(_reads(eff)) == 2, eff


def case_publish_on_first_track_and_change():
    st, eff = d.plan(State(), _inp(0.0, [A]), K)
    assert _pubs(eff) == [A], "entering `tracked` publishes"
    st, eff = d.plan(st, _inp(5.0, [A]), K)
    assert _pubs(eff) == [], "nothing changed: no publish"
    st = d.after_read(st, A, True, 5.0)
    st, eff = d.plan(st, _inp(10.0, [A]), K)
    assert _pubs(eff) == [] and _reads(eff) == [], "a landed read moves `at` only: no publish"
    st, eff = d.plan(st, _inp(15.0, [A], readable=[]), K)
    assert _pubs(eff) == [A] and st.shown[A]["cycle_s"] is None, "not readable any more: `cycle_s` null, published"
    st, eff = d.plan(st, _inp(20.0, []), K)
    assert eff == [] and A not in st.shown
    st, eff = d.plan(st, _inp(25.0, [A]), K)
    assert _pubs(eff) == [A] and _reads(eff) == [], "re-entry publishes once, keeps Last refresh (no burst read)"
    assert st.shown[A] == {"cycle_s": d.cycle_s(False, A, K), "live": "down", "values": {}}, "readable, no socket"
    assert 540.0 <= st.shown[A]["cycle_s"] <= 600.0


def case_lease_gain_and_loss():
    st, _ = d.plan(State(), _inp(0.0, [A]), K)
    st = d.after_read(st, A, True, 100.0)
    st, eff = d.plan(st, _inp(105.0, [A]), K)
    assert eff == [], eff
    st, eff = d.plan(st, _inp(110.0, [A], leased=frozenset({A})), K)
    assert _pubs(eff) == [A] and _reads(eff) == [], "a lease gain changes `cycle_s`: published once, no burst read"
    lc = st.shown[A]["cycle_s"]
    assert 108.0 <= lc <= 120.0, lc
    st, eff = d.plan(st, _inp(115.0, [A], leased=frozenset({A})), K)
    assert eff == [], "still leased: no second publish"
    assert _reads(d.plan(st, _inp(100.0 + 107.9, [A], leased=frozenset({A})), K)[1]) == [], "inside 0.9 x lease"
    assert _reads(d.plan(st, _inp(100.0 + 120.0, [A], leased=frozenset({A})), K)[1]) == [A], "due in the lease cycle"
    st, eff = d.plan(st, _inp(118.0, [A]), K)
    assert _pubs(eff) == [A] and 540.0 <= st.shown[A]["cycle_s"] <= 600.0, "a lease loss publishes the tab cycle"
    assert _reads(d.plan(st, _inp(100.0 + 120.0, [A]), K)[1]) == [], "back on the tab cycle: not due at 120 s"


def case_restart_spread():
    aids = [str(9000 + i) for i in range(50)]
    st, eff = d.plan(State(), _inp(0.0, aids), K)
    first: dict[str, float] = {a: 0.0 for a in _reads(eff)}
    t = 0.0
    while t < d.FLOOR_S:
        t += 5.0
        st, eff = d.plan(st, _inp(t, aids, in_flight=frozenset(first)), K)
        for a in _reads(eff):
            first.setdefault(a, t)
    assert sorted(first) == sorted(aids), "every Creator read inside FLOOR_S of the restart"
    per_tick: dict[float, int] = {}
    for at in first.values():
        per_tick[at] = per_tick.get(at, 0) + 1
    assert max(per_tick.values()) <= 50 // 4, ("no burst: a 5 s tick carries a fraction", per_tick)
    assert len(per_tick) >= 8, per_tick


def case_fifty_by_thirty():
    aids = [str(7000 + i) for i in range(50)]
    leased = frozenset(aids[:10])
    clamps = [frozenset(aids[i % 5::5]) | frozenset(aids[:10]) for i in range(30)]
    tracked = frozenset().union(*clamps)
    assert tracked == frozenset(aids)
    st, _ = d.plan(_read_long_ago(*aids), _inp(10_000.0, tracked, leased=leased), K)
    _, eff = d.plan(st, _inp(10_000.0, tracked, leased=leased), K)
    assert sorted(_reads(eff)) == sorted(aids) and len(_reads(eff)) == 50, "one Read per due Creator"
    reads: dict[str, list[float]] = {a: [] for a in aids}
    t = 10_000.0
    while t < 10_000.0 + 1800.0:
        st, eff = d.plan(st, _inp(t, tracked, leased=leased), K)
        got = _reads(eff)
        assert len(got) == len(set(got)), got
        for a in got:
            reads[a].append(t)
            st = d.after_read(st, a, True, t)
        t += 5.0
    for a in aids:
        tier = 120.0 if a in leased else 600.0
        gaps = [y - x for x, y in zip(reads[a], reads[a][1:])]
        assert gaps and all(0.9 * tier <= g <= tier + 5.0 for g in gaps), (a, tier, gaps)


def case_after_read():
    st = d.after_read(State(), A, True, 50.0)
    assert st.last == {A: 50.0} and A not in st.held
    st = d.after_read(st, A, False, 700.0)
    assert st.last == {A: 50.0}, "a failure keeps Last refresh"
    assert st.held == {A: 700.0 + d.FLOOR_S}
    assert _reads(d.plan(st, _inp(700.0 + d.FLOOR_S - 0.01, [A]), K)[1]) == [], "attempts never under FLOOR_S apart"
    assert _reads(d.plan(st, _inp(700.0 + d.FLOOR_S, [A]), K)[1]) == [A]
    st = d.after_read(st, A, True, 760.0)
    assert A not in st.held and st.last[A] == 760.0, "ok clears the hold"


def case_backoff_ladder():
    """Failures in a row (a 429 or any other) climb the purchases poll's Backoff ladder: held max(60, ladder_s(n))
    from each ask, `at` kept; an ok resets it."""
    st = d.after_read(State(), A, True, 0.0)
    t, holds = 1000.0, []
    for _ in range(8):
        st = d.after_read(st, A, False, t)
        holds.append(st.held[A] - t)
        assert st.last == {A: 0.0}, "a failure keeps Last refresh"
        t = st.held[A]
    assert holds == [60.0, 60.0, 120.0, 240.0, 480.0, 900.0, 900.0, 900.0], holds
    st = d.after_read(st, A, True, t)
    assert A not in st.held and st.last[A] == t, "ok writes Last refresh, clears the hold"
    st = d.after_read(st, A, False, t + 600.0)
    assert st.held[A] == t + 660.0, "the ladder restarts after an ok"
    # Ticked every 5 s, each Read failing: never two attempts under 60 s apart, gaps follow the ladder.
    st, reads, now = _read_long_ago(B), [], 10_000.0
    while now < 12_000.0:
        if _reads(d.plan(st, _inp(now, [B]), K)[1]) == [B]:
            reads.append(now)
            st = d.after_read(st, B, False, now)
        now += 5.0
    gaps = [y - x for x, y in zip(reads, reads[1:])]
    assert gaps == [60.0, 60.0, 120.0, 240.0, 480.0, 900.0][:len(gaps)] and len(gaps) >= 5, gaps
    # W30-mu #6: a Creator failing for weeks (step ~1025 at 900 s each, ~10 days) once overflowed the ladder's
    # exponent (OverflowError in after_read: no hold written, read every 5 s tick); it stays held 900 s.
    st = d.after_read(State(step={A: 1024}), A, False, t)
    assert st.held[A] == t + 900.0 and st.step[A] == 1025, (st.held, st.step)
    assert _reads(d.plan(st, _inp(t + 5.0, [A]), K)[1]) == [], "held: no Read on the next tick"



def case_live_of():
    up = {A: 5.0}
    assert d.live_of(A, up, frozenset({A}), False) == "dead", "in the Dead-session map"
    assert d.live_of(A, up, frozenset({A}), True) == "dead"
    assert d.live_of(A, {}, frozenset(), False) is None, "deactivated / no session: no socket expected"
    assert d.live_of(A, {A: None}, frozenset(), False) is None, "never 'down' without a pump"
    assert d.live_of(A, up, frozenset(), False) is None, "Fansly (not OF, not readable): None even with a stamp"
    assert d.live_of(A, up, frozenset(), True) == "up", "socket stamp set"
    assert d.live_of(A, {A: None}, frozenset(), True) == "down", "socket stamp unset"
    assert d.live_of(A, {}, frozenset(), True) == "down"


def case_dead_skip():
    st = _read_long_ago(A)
    st, eff = d.plan(st, _inp(10_000.0, [A], readable=[], dead=frozenset({A}), ws_since={A: 1.0}), K)
    assert _reads(eff) == [] and _pubs(eff) == [A], eff
    assert st.shown[A] == {"cycle_s": None, "live": "dead", "values": {}}, st.shown[A]
    st, eff = d.plan(st, _inp(10_005.0, [A], readable=[], dead=frozenset({A})), K)
    assert eff == [], "still dead: no Read, no publish"
    _, eff = d.plan(st, _inp(10_010.0, [A], readable=[A], dead=frozenset({A})), K)
    assert eff == [], "dead wins over a racing `readable`: no Read, still 'dead'"


def case_live_flip_publishes_without_read():
    st = _read_long_ago(A)
    st, _ = d.plan(st, _inp(0.0, [A], ws_since={A: 0.0}), K)          # read at 0: not due for a Cycle
    assert st.shown[A]["live"] == "up" and st.live_since == {A: 0.0}
    st, eff = d.plan(st, _inp(5.0, [A], ws_since={A: 0.0}), K)
    assert eff == [] and st.live_since == {A: 0.0}, "unchanged: no publish, `live_since` kept"
    st, eff = d.plan(st, _inp(10.0, [A], ws_since={}), K)
    assert eff == [Publish(A)] and st.shown[A]["live"] == "down", ("socket drop: published, no Read", eff)
    assert st.live_since == {A: 10.0}, "`live_since` restarts on the change"
    st, eff = d.plan(st, _inp(15.0, [A], ws_since={A: 12.0}), K)
    assert eff == [Publish(A)] and st.shown[A]["live"] == "up" and st.live_since == {A: 15.0}, "reconnect: published"
    st, eff = d.plan(st, _inp(20.0, [A], readable=[], dead=frozenset({A})), K)
    assert eff == [Publish(A)] and st.shown[A]["live"] == "dead" and st.live_since == {A: 20.0}
    st, eff = d.plan(st, _inp(25.0, [A], readable=[]), K)
    assert eff == [Publish(A)] and st.shown[A]["live"] is None and A not in st.live_since, "`live` None: no since"
    st, _ = d.plan(st, _inp(30.0, [A], ws_since={A: 29.0}), K)
    assert st.live_since == {A: 30.0}
    st, eff = d.plan(st, _inp(35.0, []), K)
    assert eff == [] and st.live_since == {}, "untracked: forgotten with its view"


def case_changed():
    """P1 Contract 3: `at` alone, a slot's `at` alone: no change; values, `live`, `cycle_s`, first track: change."""
    base = {"cycle_s": 120.0, "live": "up", "values": {"unread_total": {"n": 3, "at": 1000}}}

    def w(**kw):
        return {**base, **kw}

    def slot(v):
        return w(values={"unread_total": v})

    assert d.changed(None, base), "first track"
    assert not d.changed(w(at=1000), w(at=2000)), "`at` alone"
    assert not d.changed(base, slot({"n": 3, "at": 2000})), "a slot's `at` alone"
    assert d.changed(base, slot({"n": 2, "at": 1000})), "a slot's value"
    assert d.changed(base, slot({"n": 2, "at": 2000})), "a slot's value with its `at`"
    assert d.changed(base, slot(None)), "a slot's value to null"
    assert d.changed(slot(None), base), "a slot's first value"
    assert d.changed(base, w(values={})), "a slot gone"
    assert d.changed(base, w(values={**base["values"], "notif_count": 2})), "a slot added"
    assert d.changed(w(values={"notif_count": 2}), w(values={"notif_count": 3})), "a scalar slot"
    assert d.changed(base, w(live="down")), "`live`"
    assert d.changed(base, w(cycle_s=600.0)), "`cycle_s`"
    # The plan publishes a moved value with no Read, and nothing for a moved slot `at`.
    st = _read_long_ago(A)
    st, _ = d.plan(st, _inp(0.0, [A], values={A: {"unread_total": {"n": 3, "at": 1}}}), K)
    assert st.shown[A]["values"] == {"unread_total": {"n": 3, "at": 1}}, st.shown[A]
    st, eff = d.plan(st, _inp(5.0, [A], values={A: {"unread_total": {"n": 3, "at": 2}}}), K)
    assert eff == [], ("a slot's `at` alone: no publish", eff)
    st, eff = d.plan(st, _inp(10.0, [A], values={A: {"unread_total": {"n": 4, "at": 3}}}), K)
    assert eff == [Publish(A)], ("a moved value: published, no Read", eff)
    st, eff = d.plan(st, _inp(15.0, [A]), K)
    assert eff == [Publish(A)] and st.shown[A]["values"] == {}, "no contributor: `values` empty"


def case_window_due():
    """P1 `window_due(window_at, ws_since, asked)`: one clock (monotonic) for the window's read and the socket stamp."""
    rows = [  # (window_at, ws_since, asked, due, why)
        (100.0, None, False, True, "socket down now"),
        (100.0, 150.0, False, True, "reconnected after the window's last read"),
        (100.0, 50.0, True, True, "a contributor asked"),
        (100.0, 50.0, False, False, "WS-kept since the read: none of these"),
        (100.0, 100.0, False, False, "connected at the read itself: kept (roster-counts' `fetched_at >= live_since`)"),
        (None, None, False, False, "no window held, socket down"),
        (None, 50.0, True, False, "no window held, asked"),
    ]
    for window_at, ws_since, asked, due, why in rows:
        assert d.window_due(window_at, ws_since, asked) is due, why


def case_after_read_never_moves_last_back():
    """A warm's newer Last refresh (note_refresh during an overrunning job) outlives that job's older ask time."""
    st = d.after_read(d.State(last={"A": 50.0}), "A", True, 20.0)
    assert st.last["A"] == 50.0, st.last
    assert d.after_read(st, "A", True, 80.0).last["A"] == 80.0


_harness.run()
