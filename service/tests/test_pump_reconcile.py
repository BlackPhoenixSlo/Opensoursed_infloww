#!/usr/bin/env python3
"""service/pump_reconcile.py: the pump supervisor's pass, as tables.

  case_reconcile_table: one row per roster/pump situation -> the actions, in order.
  case_one_account_sweep: every (session, deactivated, parked, pump) of one account ->
      at most one action; never a pump for an ineligible or parked account; Stop iff a
      pump and not eligible; eligible, not parked and no running pump -> exactly one
      Start or Restart.
  case_restart_backoff_table: (restarts since the last healthy run, how long the exited
      pump ran) -> (attempt, delay): 0 at once, then 15 s doubling to the 300 s cap; a
      healthy run (>= 60 s) resets.
  case_restart_due_table: (restarts, started, exited, parked) -> (attempt, due): due is
      the exit plus the backoff; a parked exit resets the count like a healthy run.

Run: ./venv/bin/python service/tests/test_pump_reconcile.py
"""
from __future__ import annotations

import _harness  # noqa: F401  (first: sys.path + the temp-DB guard)

import itertools

from pump_reconcile import HEALTHY_RUN_S, Restart, Start, Stop, reconcile, restart_backoff, restart_due

RUNNING, DONE = False, True

# (label, with_session, deactivated, parked, pump_done {account: done}, expected)
RECONCILE = [
    ("nothing -> empty plan", set(), set(), set(), {}, []),
    ("new account with a session -> Start", {"a"}, set(), set(), {}, [Start("a")]),
    ("running pump, account eligible -> nothing", {"a"}, set(), set(), {"a": RUNNING}, []),
    ("deactivated with a running pump -> Stop", {"a"}, {"a"}, set(), {"a": RUNNING}, [Stop("a")]),
    ("deactivated, no pump -> nothing", {"a"}, {"a"}, set(), {}, []),
    ("session lost, pump running -> Stop", set(), set(), set(), {"a": RUNNING}, [Stop("a")]),
    ("account deleted, pump done -> Stop", set(), set(), set(), {"a": DONE}, [Stop("a")]),
    ("pump exited, account still eligible -> Restart", {"a"}, set(), set(), {"a": DONE}, [Restart("a")]),
    ("parked, no pump -> nothing", {"a"}, set(), {"a"}, {}, []),
    ("parked, its pump exited on the dead session -> left in place", {"a"}, set(), {"a"}, {"a": DONE}, []),
    ("parked, pump still running -> nothing", {"a"}, set(), {"a"}, {"a": RUNNING}, []),
    ("parked and deactivated, pump done -> Stop", {"a"}, {"a"}, {"a"}, {"a": DONE}, [Stop("a")]),
    ("parked and session lost, pump done -> Stop", set(), set(), {"a"}, {"a": DONE}, [Stop("a")]),
    ("deactivated without a session (parked list stale) -> nothing", set(), {"a"}, {"a"}, {}, []),
    # Starts by id first, then Stops/Restarts in pump_done's iteration order.
    ("mixed roster: Starts sorted, then pumps in pump_done order",
     {"e", "c", "a", "b", "d", "p"}, {"q"}, {"p"},
     {"e": RUNNING, "x": RUNNING, "b": DONE, "q": RUNNING, "z": DONE, "p": DONE},
     [Start("a"), Start("c"), Start("d"), Stop("x"), Restart("b"), Stop("q"), Stop("z")]),
]


def case_reconcile_table() -> None:
    bad = []
    for label, *args, want in RECONCILE:
        got = reconcile(*args)
        if got != want:
            bad.append(f"{label}: got {got!r}, want {want!r}")
    assert not bad, "\n  " + "\n  ".join(bad)


def case_one_account_sweep() -> None:
    bad = []
    for has_session, off, dead, pump in itertools.product(
            (True, False), (True, False), (True, False), (None, RUNNING, DONE)):
        pumps = {} if pump is None else {"a": pump}
        acts = reconcile({"a"} if has_session else set(), {"a"} if off else set(),
                         {"a"} if dead else set(), pumps)
        eligible = has_session and not off
        row = (has_session, off, dead, pump, acts)
        if len(acts) > 1:
            bad.append(("two actions", row))
        if any(isinstance(x, (Start, Restart)) for x in acts) and (not eligible or dead):
            bad.append(("pump for an ineligible or parked account", row))
        if (Stop("a") in acts) != (pump is not None and not eligible):
            bad.append(("Stop iff a pump and not eligible", row))
        if eligible and not dead and pump is not RUNNING and not (
                len(acts) == 1 and isinstance(acts[0], (Start, Restart))):
            bad.append(("eligible, not parked, no running pump: exactly one Start or Restart", row))
    assert not bad, bad


# (label, attempts, ran_s, (attempt, delay_s))
BACKOFF = [
    ("first restart -> at once", 0, 0.0, (0, 0.0)),
    ("second -> 15 s (the old cadence)", 1, 0.5, (1, 15.0)),
    ("third -> 30 s", 2, 0.5, (2, 30.0)),
    ("fourth -> 60 s", 3, 10.0, (3, 60.0)),
    ("sixth -> 240 s", 5, 0.0, (5, 240.0)),
    ("seventh -> capped 300 s", 6, 0.0, (6, 300.0)),
    ("far past the cap -> 300 s", 40, 0.0, (40, 300.0)),
    ("just short of healthy -> no reset", 4, HEALTHY_RUN_S - 0.1, (4, 120.0)),
    ("healthy run -> reset, at once", 4, HEALTHY_RUN_S, (0, 0.0)),
    ("long healthy run after many crashes -> reset", 40, 3600.0, (0, 0.0)),
]


def case_restart_backoff_table() -> None:
    bad = []
    for label, attempts, ran_s, want in BACKOFF:
        got = restart_backoff(attempts, ran_s)
        if got != want:
            bad.append(f"{label}: got {got!r}, want {want!r}")
    assert not bad, "\n  " + "\n  ".join(bad)
    # A crash loop the caller drives (store attempt + 1): delays never shrink, cap holds.
    n, seen = 0, []
    for _ in range(12):
        a, d = restart_backoff(n, 0.0)
        seen.append(d)
        n = a + 1
    assert seen == sorted(seen) and seen[-1] == 300.0 and seen[:4] == [0.0, 15.0, 30.0, 60.0], seen


# (label, attempts, started, exited, parked, (attempt, due))
DUE = [
    ("first crash -> at its exit", 0, 100.0, 100.5, False, (0, 100.5)),
    ("second crash -> exit + 15 s", 1, 200.0, 200.5, False, (1, 215.5)),
    ("fourth crash -> exit + 60 s", 3, 0.0, 5.0, False, (3, 65.0)),
    ("crash after a healthy run -> at once", 3, 0.0, HEALTHY_RUN_S, False, (0, HEALTHY_RUN_S)),
    # phase D's case: restart attempt 2 ran 5 s, then parked on a dead session; the probe
    # unparks it -> the next pass restarts at once, not 60 s later.
    ("parked after crash-restarts -> reset, at once", 2, 300.0, 305.0, True, (0, 305.0)),
    ("parked, first run -> at once", 0, 0.0, 1.0, True, (0, 1.0)),
]


def case_restart_due_table() -> None:
    bad = []
    for label, attempts, started, exited, parked, want in DUE:
        got = restart_due(attempts, started, exited, parked)
        if got != want:
            bad.append(f"{label}: got {got!r}, want {want!r}")
    assert not bad, "\n  " + "\n  ".join(bad)


_harness.run()
