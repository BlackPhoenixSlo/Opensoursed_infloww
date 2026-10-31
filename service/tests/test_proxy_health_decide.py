#!/usr/bin/env python3
"""proxy_health_decide.decide(state, event) -> (state', effects, next): the down / confirm / recheck /
failover rules of service/proxy_health.py as tables (docs/adr/0030). Pure: no lock, no clock, no I/O.

Pins: DOWN_AFTER counted errors start one watcher (never while one runs, never on a bad proxy); a
watcher goes on exactly while its state warrants one (bad, or at DOWN_AFTER: a proxy back up mid-recheck
then at DOWN_AFTER again goes back to the confirm phase, same watcher) and ends releasing its claim
(Unwatch) in its last step's decide, so an error right after it starts the next; the
confirm waits CONFIRM_GAP_S from the streak's first error and is skipped after a reset; a failed
confirm is bad + announced once, unless a call got through while it probed (ADR 0030: not bad; a new
streak since is waited out and confirmed by the same watcher; a streak is its counter, not its start time);
rechecks double from the base up to RECHECK_MAX_S; the failover
comes with the FAILOVER_AFTER_RECHECKS-th failed recheck and once with every later one; an answer
brings it back (announced once); Gone drops the entry and ends the loop; FailedOver stamps only;
announces happen on transitions only, save the matrix's `kept:` cells (a call racing a probe, or a step
one watcher per label never reaches); decide never mutates its input.

Runs under pytest (parametrized tables) or as a script (the repo's convention, no pytest needed):
    ./venv/bin/python service/tests/test_proxy_health_decide.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import proxy_health_decide as ph  # noqa: E402
from proxy_health_decide import (  # noqa: E402
    DOWN_AFTER, FAILOVER_AFTER_RECHECKS, RECHECK_MAX_S, Announce, ArmRecheck, CallErr, CallOk, Confirm, ConfirmDue,
    ConfirmResult, Failover, FailedOver, Gone, Recheck, RecheckDue, RecheckResult, RecheckWait, Unwatch, Wait, Watch,
    decide)

try:
    import pytest
    table = pytest.mark.parametrize
except ImportError:  # script mode: the runner below calls each row
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark


def _kinds(effects, logs: bool = False) -> list[str]:
    return [type(e).__name__ + (f"({e.down})" if isinstance(e, Announce) else "") for e in effects
            if logs or not isinstance(e, ph.Log)]


def _st(**kw) -> dict:
    return {**ph.blank(), **kw}


DOWN = _st(errors=DOWN_AFTER, first_error_at=0.0, streak=1, down=True, rechecks_failed=0, bad_since=1.0)


# ── the error count to the watcher ──
@table("before, watching, start", [
    (_st(), False, False),                                           # 1st error
    (_st(errors=DOWN_AFTER - 2, first_error_at=5.0), False, False),
    (_st(errors=DOWN_AFTER - 1, first_error_at=5.0), False, True),   # the DOWN_AFTER-th: confirm starts
    (_st(errors=DOWN_AFTER - 1, first_error_at=5.0), True, False),   # a watcher already runs: one per label
    (_st(errors=DOWN_AFTER, first_error_at=5.0), False, True),       # past it, no watcher (it ended): again
    ({**DOWN, "errors": DOWN_AFTER + 4}, False, False),              # already bad: its recheck loop owns it
    (None, False, False),                                            # no entry yet: made, count 1
])
def test_error_count_starts_one_watcher(before, watching, start):
    st, effects, nxt = decide(before, CallErr(now=100.0, error="CONNECT tunnel failed", watching=watching))
    assert _kinds(effects) == (["Watch"] if start else []) and nxt is None, effects
    assert st["errors"] == (before or ph.blank())["errors"] + 1
    assert st["last_error"] == "CONNECT tunnel failed" and st["last_error_at"] == 100.0


@table("errors_before, first_after", [(0, 100.0), (1, 5.0), (DOWN_AFTER, 5.0)])
def test_streak_start_is_its_first_error(errors_before, first_after):
    before = _st(errors=errors_before, first_error_at=5.0 if errors_before else None, streak=4)
    st, _, _ = decide(before, CallErr(now=100.0, error=None, watching=False))
    assert st["first_error_at"] == first_after
    assert st["streak"] == (4 if errors_before else 5), "a new streak, a new number"
    assert st["last_error"] == "error", "no message: 'error'"


def test_error_text_is_capped():
    st, _, _ = decide(None, CallErr(now=1.0, error="x" * 500, watching=False))
    assert len(st["last_error"]) == 200


def test_streak_of_calls_starts_exactly_one_watcher():
    """The shell's view: Watch claims the label, so later errors see watching=True."""
    st, watching, starts = None, False, []
    for i in range(DOWN_AFTER + 3):
        st, effects, _ = decide(st, CallErr(now=float(i), error="e", watching=watching))
        if Watch() in effects:
            starts.append(i + 1)
            watching = True
    assert starts == [DOWN_AFTER], starts


@table("last_step, at_last", [
    (ConfirmDue(now=104.0, gap=30.0), _st(errors=0, streak=1)),   # a blip: an answer reset it in the wait
    (ConfirmResult(now=134.0, ok=True, streak=1),                 # a blip: the confirm answers
     _st(errors=DOWN_AFTER, first_error_at=100.0, streak=1)),
    (RecheckResult(ok=True), {**DOWN, "rechecking": True}),       # back up: the recheck answers
])
def test_an_error_right_after_the_watchers_last_step_starts_a_new_one(last_step, at_last):
    """N1: the claim is released in the same decide as the watcher's last step (Unwatch), so the
    DOWN_AFTER-th error of a streak that lands right after it reads watching=False and gets its Watch
    (a release after the watcher returned would leave the proxy at DOWN_AFTER, nobody watching)."""
    st, effects, nxt = decide(at_last, last_step)
    assert nxt is None and effects[-1] == Unwatch(), (effects, nxt)
    watching = False   # released in that same decide
    for i in range(DOWN_AFTER):
        st, effects, _ = decide(st, CallErr(now=140.0 + i, error="e", watching=watching))
        watching = watching or Watch() in effects
    assert _kinds(effects) == ["Watch"] and watching, effects


# ── the confirm's wait ──
AT_100 = _st(errors=DOWN_AFTER, first_error_at=100.0, streak=1)    # DOWN_AFTER reached, streak 1 began at 100


@table("state, now, expect", [
    (AT_100, 100.0, Wait(30.0, ConfirmDue)),                               # gap from the first error
    (AT_100, 118.0, Wait(12.0, ConfirmDue)),
    (AT_100, 130.0, Confirm(1)),                                           # gap over: probe now, for streak 1
    (AT_100, 500.0, Confirm(1)),
    ({**AT_100, "first_error_at": 125.0, "streak": 2}, 130.0, Wait(25.0, ConfirmDue)),   # a new streak in the wait: from it
    (_st(errors=0, streak=1), 130.0, None),                                # an answer reset it: a blip, no confirm
    (_st(errors=DOWN_AFTER - 1, first_error_at=100.0, streak=1), 130.0, None),
    ({**DOWN}, 130.0, ArmRecheck()),                                       # already bad: keeps rechecking, claimed
    (None, 130.0, None),                                                   # gone
])
def test_confirm_waits_the_gap(state, now, expect):
    st, effects, nxt = decide(state, ConfirmDue(now=now, gap=30.0))
    assert st is state, "the wait writes nothing"
    assert effects == ([] if expect else [Unwatch()]) and nxt == expect, "no confirm: the watcher ends, unclaimed"


@table("ok, kinds, then, down, errors", [
    (True, ["Unwatch"], None, False, 0),                         # answers: a blip, the count restarts, silent
    (False, ["Announce(True)"], ArmRecheck(), True, DOWN_AFTER),   # fails: bad, announced once, rechecks start
])
def test_confirm_result(ok, kinds, then, down, errors):
    before = {**AT_100, "rechecks_failed": 5}
    st, effects, nxt = decide(before, ConfirmResult(now=140.0, ok=ok, streak=1))
    assert _kinds(effects) == kinds and nxt == then, (effects, nxt)
    assert st["down"] is down and st["errors"] == errors
    if down:
        assert st["bad_since"] == 140.0 and st["rechecks_failed"] == 0
    else:
        assert st["first_error_at"] is None


@table("during_probe, kinds, then, write", [
    # the probe confirms streak 1 (first error at 100), fails at 140; gap 30
    (AT_100, ["Announce(True)"], ArmRecheck(), {"down": True, "bad_since": 140.0, "rechecks_failed": 0}),
    ({**AT_100, "errors": DOWN_AFTER + 2}, ["Announce(True)"], ArmRecheck(),          # same streak, more errors
     {"down": True, "bad_since": 140.0, "rechecks_failed": 0}),
    (_st(streak=1), ["Unwatch"], None, {}),                                          # a call got through: reset
    (_st(errors=1, first_error_at=120.0, streak=2), ["Unwatch"], None, {}),         # then a new error: not at the bar
    ({**AT_100, "first_error_at": 120.0, "streak": 2}, [], Wait(0.0, ConfirmDue), {}),   # a whole new streak: ConfirmDue waits it
    ({**AT_100, "first_error_at": 105.0, "streak": 2}, [], Wait(0.0, ConfirmDue), {}),   # ... already waited out: confirms
    ({**AT_100, "streak": 2}, [], Wait(0.0, ConfirmDue), {}),                            # same start time, another streak
])
def test_failed_confirm_after_a_call_got_through_is_not_bad(during_probe, kinds, then, write):
    """ADR 0030: bad only from a failed confirm with no call through meanwhile; a call that got through
    reset the streak the probe confirms. A new streak at DOWN_AFTER since: the same watcher waits it out."""
    st, effects, nxt = decide(during_probe, ConfirmResult(now=140.0, ok=False, streak=1))
    assert (_kinds(effects), nxt, st) == (kinds, then, {**during_probe, **write})


# ── the recheck loop, driven as proxy_health's shell drives it ──
def _announced(effects) -> list[str]:
    return [k for k in _kinds(effects) if k.startswith("Announce")]


def _drive(outcomes: list, base: float = 2.0, max_steps: int = 50):
    """From a just-confirmed bad proxy: ArmRecheck → RecheckWait → Wait(s, RecheckDue) → RecheckDue → Recheck →
    RecheckResult(outcome) (or an injected event: Gone, CallOk run during the wait).
    Returns (state, sleeps, announces in order, failovers' recheck numbers)."""
    st, effects, then = decide({**AT_100, "first_error_at": 0.0},
                               ConfirmResult(now=10.0, ok=False, streak=1))
    log, sleeps, failover_at = _announced(effects), [], []
    script, n = list(outcomes), 0
    while then == ArmRecheck() and max_steps:
        max_steps -= 1
        st, effects, then = decide(st, RecheckWait(now=10.0, base=base))
        if then is None:
            assert effects == [Unwatch()]
            break
        assert then.then is RecheckDue, then
        sleeps.append(then.s)
        assert st["next_recheck_at"] == 10.0 + then.s
        nxt = script.pop(0) if script else False
        if not isinstance(nxt, bool):                    # something happens during the sleep
            st, more, _ = decide(st, nxt)
            log += _announced(more)
            nxt = script.pop(0) if script else False
        st, effects, then = decide(st, RecheckDue())
        if then != Recheck():
            assert effects == [Unwatch()] and then is None, (effects, then)
            break
        assert st["rechecking"] and st["next_recheck_at"] is None
        n += 1
        st, effects, then = decide(st, RecheckResult(ok=nxt))
        log += _announced(effects)
        if Failover() in effects:
            failover_at.append(n)
            st, more, _ = decide(st, FailedOver(now=11.0, moved=("c1",)))
            log += _announced(more)
    return st, sleeps, log, failover_at


@table("outcomes, failovers, back", [
    ([True], [], True),                                    # the first recheck answers: back, nobody moved
    ([False, True], [], True),                             # one failure: not yet
    ([False, False, True], [2], True),                     # FAILOVER_AFTER_RECHECKS-th: the move, exactly once
    ([False, False, False, True], [2, 3], True),           # and again at every later failure (nobody may have moved)
    ([False] * 6 + [True], [2, 3, 4, 5, 6], True),
])
def test_recheck_then_failover_sequence(outcomes, failovers, back):
    st, sleeps, log, failover_at = _drive(outcomes)
    assert FAILOVER_AFTER_RECHECKS == 2
    assert failover_at == failovers, failover_at
    assert log.count("Announce(True)") == 1 and log.count("Announce(False)") == (1 if back else 0), log
    assert log[-1] == "Announce(False)" and not st["down"] and st["rechecks_failed"] == 0
    assert st.get("rechecking") is False and st["next_recheck_at"] is None
    assert len(sleeps) == len(outcomes)
    assert st.get("failed_over", 0) == len(failovers), "FailedOver counts the moved Creators"


@table("base, failed, delay", [
    (2.0, 0, 2.0), (2.0, 1, 4.0), (2.0, 2, 8.0), (20.0, 4, 320.0), (20.0, 5, RECHECK_MAX_S),
    (20.0, 50, RECHECK_MAX_S), (20.0, 100000, RECHECK_MAX_S),   # a proxy dead for years: no overflow
    (1000.0, 0, 1000.0), (1000.0, 1, RECHECK_MAX_S),            # a base over the cap is honoured once
])
def test_recheck_backoff(base, failed, delay):
    st, effects, nxt = decide({**DOWN, "rechecks_failed": failed}, RecheckWait(now=50.0, base=base))
    assert effects == [] and nxt == Wait(delay, RecheckDue) and st["next_recheck_at"] == 50.0 + delay


def test_recheck_sleeps_double():
    _, sleeps, _, _ = _drive([False] * 4 + [True], base=5.0)
    assert sleeps == [5.0, 10.0, 20.0, 40.0, 80.0], sleeps


def test_gone_mid_recheck_ends_the_loop():
    st, sleeps, log, failover_at = _drive([False, Gone(), False])
    assert st is None, "the entry is dropped"
    assert sleeps == [2.0, 4.0] and failover_at == [], (sleeps, failover_at)
    assert log == ["Announce(True)"], "nothing announced, nobody moved after the label left"
    st, effects, nxt = decide(DOWN, Gone())
    assert st is None and _kinds(effects) == ["Unwatch"] and nxt is None


def test_answer_during_the_sleep_ends_the_loop():
    st, sleeps, log, _ = _drive([False, CallOk(now=12.0), False])
    assert log == ["Announce(True)", "Announce(False)"], "back once, by the call; no recheck probe after"
    assert not st["down"] and sleeps == [2.0, 4.0]


def test_failing_recheck_after_a_call_brought_it_back():
    """The race: a call brought the proxy back while the recheck probe ran, then the probe failed. The
    failure is counted (as before) but moves nobody, the proxy stays up, and the watcher ends (below the
    bar; at it: test_back_at_the_bar_mid_recheck_keeps_the_watcher)."""
    up = {**_st(), "rechecks_failed": 1, "rechecking": True}
    st, effects, nxt = decide(up, RecheckResult(ok=False))
    assert effects == [Unwatch()] and nxt is None, (effects, nxt)
    assert st["down"] is False and st["rechecks_failed"] == 2 and st["rechecking"] is False


def _back_at_the_bar(st):
    """A call answered (the proxy is back up), then DOWN_AFTER errors while the watcher still holds the
    claim (watching=True: no Watch, no second watcher)."""
    st, _, _ = decide(st, CallOk(now=200.0))
    for i in range(DOWN_AFTER):
        st, effects, _ = decide(st, CallErr(now=201.0 + i, error="e", watching=True))
        assert Watch() not in effects, effects
    return st


@table("before, step", [
    ({**DOWN, "next_recheck_at": 210.0}, RecheckDue()),        # the answer + streak in the recheck's sleep
    (DOWN, RecheckWait(now=205.0, base=2.0)),                  # ... between a failed confirm / recheck and the arm
    ({**DOWN, "rechecking": True}, RecheckResult(ok=False)),   # ... during the recheck probe, which then fails
])
def test_back_at_the_bar_mid_recheck_keeps_the_watcher(before, step):
    """F1 (N1's class, recheck phase): the same watcher goes back to the confirm phase, never Unwatch."""
    st, effects, nxt = decide(_back_at_the_bar(before), step)
    assert Unwatch() not in effects and nxt == Wait(0.0, ConfirmDue), (effects, nxt)
    st, effects, nxt = decide(st, ConfirmDue(now=240.0, gap=30.0))
    assert effects == [] and nxt == Confirm(st["streak"]), (effects, nxt)   # its new streak gets confirmed


def test_failed_over_only_stamps():
    before = {**DOWN, "rechecks_failed": FAILOVER_AFTER_RECHECKS, "failed_over": 2}
    st, effects, nxt = decide(before, FailedOver(now=99.0, moved=("a", "b", "c")))
    assert st == {**before, "failed_over_at": 99.0, "failed_over": 5}
    assert _kinds(effects) == [] and len(effects) == 1 and nxt is None, "a log line, nothing else"
    st, effects, _ = decide(before, FailedOver(now=99.0, moved=()))
    assert st["failed_over"] == 2 and st["failed_over_at"] == 99.0 and st["down"], "nobody moved: stays bad"
    assert decide(None, FailedOver(now=1.0, moved=("a",)))[0]["failed_over"] == 1


# ── every state × every event: the whole transition table, pinned as it is ──
# The shapes decide tells apart. down: bad, its next recheck armed; rechecking: a recheck in flight whose
# failure is the FAILOVER_AFTER_RECHECKS-th; due: in flight, failover already due; failed_over: just failed
# over (FailedOver stamped).
_D = {**AT_100, "down": True, "bad_since": 105.0, "rechecks_failed": 0,
      "rechecking": False, "next_recheck_at": 130.0}
_R = {**_D, "rechecking": True, "next_recheck_at": None, "rechecks_failed": FAILOVER_AFTER_RECHECKS - 1}
_RD = {**_R, "rechecks_failed": FAILOVER_AFTER_RECHECKS}
STATES = {
    "none": None,
    "healthy": _st(),
    "suspect": _st(errors=DOWN_AFTER - 1, first_error_at=100.0, streak=1),
    "threshold": AT_100,   # DOWN_AFTER reached, confirm not yet run
    "down": _D,
    "rechecking": _R,
    "due": _RD,
    "failed_over": {**_RD, "rechecking": False, "failed_over_at": 108.0, "failed_over": 2},
}
EVENTS = {   # one clock for all: now=110, the streak began at 100, the confirm gap is 30, the recheck base 10
    "call_ok": CallOk(now=110.0), "call_err": CallErr(now=110.0, error="boom", watching=False),
    "call_err_watching": CallErr(now=110.0, error="boom", watching=True),
    "confirm_due": ConfirmDue(now=110.0, gap=30.0),
    "confirm_ok": ConfirmResult(now=110.0, ok=True, streak=1),   # the probe is for streak 1
    "confirm_bad": ConfirmResult(now=110.0, ok=False, streak=1),
    "recheck_wait": RecheckWait(now=110.0, base=10.0), "recheck_due": RecheckDue(),
    "recheck_ok": RecheckResult(ok=True), "recheck_bad": RecheckResult(ok=False),
    "gone": Gone(), "failed_over": FailedOver(now=110.0, moved=("a",)),
}


def _cell(before, ev) -> tuple:
    """(effect kinds incl. Log, next, state'); decide must leave `before` as it was."""
    frozen = copy.deepcopy(before)
    after, effects, nxt = decide(before, ev)
    assert before == frozen, "decide never mutates its input"
    return _kinds(effects, logs=True), nxt, after


# The writes the matrix repeats (state' == {**state, **write}).
LAST_ERR = {"last_error": "boom", "last_error_at": 110.0}
FIRST_ERR = {"errors": 1, "first_error_at": 110.0, "streak": 1, **LAST_ERR}   # a streak's first error
MORE_ERR = {"errors": DOWN_AFTER + 1, **LAST_ERR}                             # one past DOWN_AFTER
CONFIRM_RESET = {"errors": 0, "first_error_at": None}                # the confirm answered: count restarts
CONFIRMED_BAD = {"down": True, "bad_since": 110.0, "rechecks_failed": 0}
RECHECK_IN_FLIGHT = {"rechecking": True, "next_recheck_at": None}
RECHECK_FAILED_1 = {"rechecking": False, "rechecks_failed": 1}
RECHECK_FAILED_PAST_DUE = {"rechecking": False, "rechecks_failed": FAILOVER_AFTER_RECHECKS + 1}
FAILED_OVER_ONE = {"failed_over_at": 110.0, "failed_over": 1}                # FailedOver(moved=("a",))
MATRIX = [
    # state, event, effects, next, write: state' == {**(state or blank()), **write}; write None = no entry
    # ── none ──
    ("none", "call_ok", [], None, ph._UP),
    ("none", "call_err", [], None, FIRST_ERR),
    ("none", "call_err_watching", [], None, FIRST_ERR),
    ("none", "confirm_due", ["Unwatch"], None, None),
    ("none", "confirm_ok", ["Unwatch"], None, None),
    ("none", "confirm_bad", ["Unwatch"], None, None),
    ("none", "recheck_wait", ["Unwatch"], None, None),
    ("none", "recheck_due", ["Unwatch"], None, None),
    # kept: announced though there is no entry
    ("none", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, None),
    ("none", "recheck_bad", ["Unwatch"], None, None),
    ("none", "gone", ["Log", "Unwatch"], None, None),
    # kept: creates an entry; unreachable (only Gone drops it, same thread)
    ("none", "failed_over", ["Log"], None, FAILED_OVER_ONE),
    # ── healthy ──
    ("healthy", "call_ok", [], None, ph._UP),
    ("healthy", "call_err", [], None, FIRST_ERR),
    ("healthy", "call_err_watching", [], None, FIRST_ERR),
    ("healthy", "confirm_due", ["Unwatch"], None, {}),
    ("healthy", "confirm_ok", ["Log", "Unwatch"], None, CONFIRM_RESET),
    # ADR 0030: a call got through during the confirm probe (healthy, or suspect again), then the probe
    # failed: not bad, nothing announced; below the bar: the watcher ends (at it: the confirm tables above).
    ("healthy", "confirm_bad", ["Log", "Unwatch"], None, {}),
    ("healthy", "recheck_wait", ["Unwatch"], None, {}),
    ("healthy", "recheck_due", ["Unwatch"], None, {}),
    # kept (race): a call brought it back during the recheck probe (healthy, suspect or threshold again),
    # then the probe answers too: announced a second time (one extra refetch in open tabs).
    ("healthy", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, ph._UP),
    ("healthy", "recheck_bad", ["Unwatch"], None, RECHECK_FAILED_1),   # counted; below the bar: ends
    ("healthy", "gone", ["Log", "Unwatch"], None, None),
    ("healthy", "failed_over", ["Log"], None, FAILED_OVER_ONE),
    # ── suspect ──
    ("suspect", "call_ok", [], None, ph._UP),
    ("suspect", "call_err", ["Watch"], None, {"errors": DOWN_AFTER, **LAST_ERR}),
    ("suspect", "call_err_watching", [], None, {"errors": DOWN_AFTER, **LAST_ERR}),
    ("suspect", "confirm_due", ["Unwatch"], None, {}),
    ("suspect", "confirm_ok", ["Log", "Unwatch"], None, CONFIRM_RESET),
    # kept: unreachable (a confirm is for a streak at DOWN_AFTER, and a streak's count never drops):
    # bad, as threshold. A new streak below the bar after a call got through: the table above.
    ("suspect", "confirm_bad", ["Log", "Announce(True)"], ArmRecheck(), CONFIRMED_BAD),
    ("suspect", "recheck_wait", ["Unwatch"], None, {}),
    ("suspect", "recheck_due", ["Unwatch"], None, {}),
    ("suspect", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, ph._UP),      # kept (race): as healthy
    ("suspect", "recheck_bad", ["Unwatch"], None, RECHECK_FAILED_1),
    ("suspect", "gone", ["Log", "Unwatch"], None, None),
    ("suspect", "failed_over", ["Log"], None, FAILED_OVER_ONE),
    # ── threshold ──
    ("threshold", "call_ok", [], None, ph._UP),
    ("threshold", "call_err", ["Watch"], None, MORE_ERR),
    ("threshold", "call_err_watching", [], None, MORE_ERR),
    ("threshold", "confirm_due", [], Wait(20.0, ConfirmDue), {}),                        # 100 + 30 - 110
    ("threshold", "confirm_ok", ["Log", "Unwatch"], None, CONFIRM_RESET),
    ("threshold", "confirm_bad", ["Log", "Announce(True)"], ArmRecheck(), CONFIRMED_BAD),
    # F1: a call brought it back mid-recheck, then DOWN_AFTER errors while this watcher held the claim
    # (they started none): the same watcher goes back to the confirm phase, never Unwatch.
    ("threshold", "recheck_wait", [], Wait(0.0, ConfirmDue), {}),
    ("threshold", "recheck_due", [], Wait(0.0, ConfirmDue), {}),
    ("threshold", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, ph._UP),    # kept (race): as healthy
    ("threshold", "recheck_bad", [], Wait(0.0, ConfirmDue), RECHECK_FAILED_1),   # F1, as recheck_wait
    ("threshold", "gone", ["Log", "Unwatch"], None, None),
    ("threshold", "failed_over", ["Log"], None, FAILED_OVER_ONE),
    # ── down ──
    ("down", "call_ok", ["Log", "Announce(False)"], None, ph._UP),
    ("down", "call_err", [], None, MORE_ERR),   # bad: no second watcher
    ("down", "call_err_watching", [], None, MORE_ERR),
    # kept: unreachable (a bad proxy is only rechecked); bad keeps the watcher rechecking. Same below.
    ("down", "confirm_due", [], ArmRecheck(), {}),
    ("down", "confirm_ok", ["Log"], ArmRecheck(), CONFIRM_RESET),   # kept: stays down
    # kept: re-announced, bad_since and rechecks_failed reset; unreachable (one watcher per label, its
    # confirm before its rechecks; a bad proxy starts none). Same for rechecking, due, failed_over.
    ("down", "confirm_bad", ["Log", "Announce(True)"], ArmRecheck(), CONFIRMED_BAD),
    ("down", "recheck_wait", [], Wait(10.0, RecheckDue), {"next_recheck_at": 120.0}),
    ("down", "recheck_due", [], Recheck(), RECHECK_IN_FLIGHT),
    ("down", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, ph._UP),
    ("down", "recheck_bad", [], ArmRecheck(), RECHECK_FAILED_1),
    ("down", "gone", ["Log", "Unwatch"], None, None),
    ("down", "failed_over", ["Log"], None, FAILED_OVER_ONE),
    # ── rechecking ──
    ("rechecking", "call_ok", ["Log", "Announce(False)"], None, ph._UP),
    ("rechecking", "call_err", [], None, MORE_ERR),
    ("rechecking", "call_err_watching", [], None, MORE_ERR),
    ("rechecking", "confirm_due", [], ArmRecheck(), {}),
    ("rechecking", "confirm_ok", ["Log"], ArmRecheck(), CONFIRM_RESET),
    ("rechecking", "confirm_bad", ["Log", "Announce(True)"], ArmRecheck(), CONFIRMED_BAD),   # kept: as down
    ("rechecking", "recheck_wait", [], Wait(20.0, RecheckDue), {"next_recheck_at": 130.0}),
    ("rechecking", "recheck_due", [], Recheck(), RECHECK_IN_FLIGHT),
    ("rechecking", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, ph._UP),
    ("rechecking", "recheck_bad", ["Failover"], ArmRecheck(),
     {"rechecking": False, "rechecks_failed": FAILOVER_AFTER_RECHECKS}),
    ("rechecking", "gone", ["Log", "Unwatch"], None, None),
    ("rechecking", "failed_over", ["Log"], None, FAILED_OVER_ONE),
    # ── due ──
    ("due", "call_ok", ["Log", "Announce(False)"], None, ph._UP),
    ("due", "call_err", [], None, MORE_ERR),
    ("due", "call_err_watching", [], None, MORE_ERR),
    ("due", "confirm_due", [], ArmRecheck(), {}),
    ("due", "confirm_ok", ["Log"], ArmRecheck(), CONFIRM_RESET),
    ("due", "confirm_bad", ["Log", "Announce(True)"], ArmRecheck(), CONFIRMED_BAD),   # kept: as down
    ("due", "recheck_wait", [], Wait(40.0, RecheckDue), {"next_recheck_at": 150.0}),
    ("due", "recheck_due", [], Recheck(), RECHECK_IN_FLIGHT),
    ("due", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, ph._UP),
    ("due", "recheck_bad", ["Failover"], ArmRecheck(), RECHECK_FAILED_PAST_DUE),
    ("due", "gone", ["Log", "Unwatch"], None, None),
    ("due", "failed_over", ["Log"], None, FAILED_OVER_ONE),
    # ── failed_over ──
    ("failed_over", "call_ok", ["Log", "Announce(False)"], None, ph._UP),
    ("failed_over", "call_err", [], None, MORE_ERR),
    ("failed_over", "call_err_watching", [], None, MORE_ERR),
    ("failed_over", "confirm_due", [], ArmRecheck(), {}),
    ("failed_over", "confirm_ok", ["Log"], ArmRecheck(), CONFIRM_RESET),
    ("failed_over", "confirm_bad", ["Log", "Announce(True)"], ArmRecheck(), CONFIRMED_BAD),   # kept: as down
    ("failed_over", "recheck_wait", [], Wait(40.0, RecheckDue), {"next_recheck_at": 150.0}),
    ("failed_over", "recheck_due", [], Recheck(), RECHECK_IN_FLIGHT),
    ("failed_over", "recheck_ok", ["Log", "Announce(False)", "Unwatch"], None, ph._UP),
    ("failed_over", "recheck_bad", ["Failover"], ArmRecheck(), RECHECK_FAILED_PAST_DUE),
    ("failed_over", "gone", ["Log", "Unwatch"], None, None),
    ("failed_over", "failed_over", ["Log"], None, {"failed_over_at": 110.0, "failed_over": 3}),
]


@table("state, event, effects, then, write", MATRIX)
def test_every_state_and_event(state, event, effects, then, write):
    before = STATES[state]
    want = None if write is None else {**(before or ph.blank()), **write}
    got = _cell(before, EVENTS[event])
    assert got == (effects, then, want), f"{state} × {event}: {got}"


def test_matrix_is_exhaustive():
    import typing
    assert FAILOVER_AFTER_RECHECKS == 2, "the recheck delays and Failover cells above assume it"
    assert ph._UP == {"errors": 0, "first_error_at": None, "down": False, "rechecks_failed": 0,
                      "next_recheck_at": None, "rechecking": False}, "the matrix's answer cells write ph._UP"
    assert {type(e) for e in EVENTS.values()} == set(typing.get_args(ph.Event)), "an event class is missing"
    cells = [(s, e) for s, e, *_ in MATRIX]
    assert len(cells) == len(set(cells)), "one row per state × event"
    assert set(cells) == {(s, e) for s in STATES for e in EVENTS}


# The events only the watcher sends (each named by its last `next`, or by its probe: Gone).
WATCHER_STEPS = (ConfirmDue, ConfirmResult, RecheckWait, RecheckDue, RecheckResult, Gone)


def _warrants_a_watcher(st) -> bool:
    """Bad (it is rechecked), or not bad at DOWN_AFTER errors (it is to be confirmed)."""
    return st is not None and (st["down"] or st["errors"] >= DOWN_AFTER)


def test_the_watcher_goes_on_exactly_while_the_state_warrants_one():
    """The claim's invariant over the whole matrix (F2): after any watcher step, the watcher goes on
    (a next move, no Unwatch) when its state' warrants a watcher, and ends (next None, Unwatch as the last
    effect) when it does not: no proxy is left bad or at DOWN_AFTER with the claim released, and no claim
    outlives the need. A step outside the watcher never touches the claim's release and has no next."""
    for state, event, effects, then, write in MATRIX:
        ev, before = EVENTS[event], STATES[state]
        after = None if write is None else {**(before or ph.blank()), **write}
        if not isinstance(ev, WATCHER_STEPS):
            assert "Unwatch" not in effects and then is None, (state, event, effects, then)
        elif _warrants_a_watcher(after):
            assert then is not None and "Unwatch" not in effects, (state, event, effects, then)
        else:
            assert then is None and effects[-1:] == ["Unwatch"] and effects.count("Unwatch") == 1, \
                (state, event, effects, then)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
