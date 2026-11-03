#!/usr/bin/env python3
"""
send_marker_decide — table tests over the send-once marker's pure rules.

  case_marker_state_table:     NONE / IN_FLIGHT / UNCONFIRMED: `unconfirmed_at`,
                               a pre-boot mark, older than IN_FLIGHT_MAX_S (strict >).
  case_failure_outcome_table:  a raised attempt: an id'd bubble wins (SENT), an id-less
                               one is UNCONFIRMED, a raise before the mark or an
                               unreachable fan CLEARs, else may_have_sent decides.
  case_lookup_since:           the settle looks back LOOKUP_SLACK_S before the mark.

Run: ./venv/bin/python service/tests/test_send_marker_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from datetime import datetime, timedelta  # noqa: E402

from automations import send_marker_decide as smd  # noqa: E402
from automations.send_marker_decide import (  # noqa: E402
    CLEAR, IN_FLIGHT, IN_FLIGHT_MAX_S, NONE, SENT, UNCONFIRMED,
    failure_outcome, lookup_since, marker_state,
)

BOOT = datetime(2026, 11, 3, 12, 0, 0)
N = BOOT + timedelta(hours=1)


def s(secs: float) -> datetime:
    """`secs` before N."""
    return N - timedelta(seconds=secs)


def case_marker_state_table():
    rows = [
        ("no marker", None, None, NONE),
        ("fresh mark", s(1), None, IN_FLIGHT),
        ("mark at the lease edge", s(IN_FLIGHT_MAX_S), None, IN_FLIGHT),
        ("mark past the lease", s(IN_FLIGHT_MAX_S + 1), None, UNCONFIRMED),
        ("mark before boot (dead process)", BOOT - timedelta(seconds=1), None, UNCONFIRMED),
        ("fresh mark, unconfirmed", s(1), s(0), UNCONFIRMED),
        ("unconfirmed alone", None, s(0), UNCONFIRMED),
    ]
    bad = [f"{rid}: {got} != {want}" for rid, sa, ua, want in rows
           if (got := marker_state(sa, ua, BOOT, N)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)
    # boot just now: a mark of this process, seconds old, is in flight; at boot too
    assert marker_state(s(5), None, s(10), N) == IN_FLIGHT
    assert marker_state(s(10), None, s(10), N) == IN_FLIGHT


def case_failure_outcome_table():
    rows = [
        # (id, sent, returned, entered, may_have_sent, want)
        ("bubble 0 landed, bubble 1 4xx", 1, 1, True, False, SENT),
        ("landed + may have sent", 1, 1, True, True, SENT),
        ("id-less bubble, then 4xx", 0, 1, True, False, UNCONFIRMED),
        ("id-less bubble, then timeout", 0, 1, True, True, UNCONFIRMED),
        ("raise before the mark (SlotLost in a hold)", 0, 0, False, True, CLEAR),
        ("raise before the mark, surely not", 0, 0, False, False, CLEAR),
        ("first call 4xx", 0, 0, True, False, CLEAR),
        ("first call read timeout", 0, 0, True, True, UNCONFIRMED),
    ]
    bad = [f"{rid}: {got} != {want}" for rid, a, b, c, d, want in rows
           if (got := failure_outcome(a, b, c, d)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)
    # OF refused the fan itself (skip_unreachable_fan): not delivered, unless one landed
    rows = [
        ("unreachable, bubble 0 landed", 1, 1, True, True, SENT),
        ("unreachable, id-less bubble", 0, 1, True, False, CLEAR),
        ("unreachable, may have sent", 0, 0, True, True, CLEAR),
        ("unreachable before the mark", 0, 0, False, False, CLEAR),
    ]
    bad = [f"{rid}: {got} != {want}" for rid, a, b, c, d, want in rows
           if (got := failure_outcome(a, b, c, d, unreachable=True)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)


def case_lookup_since():
    assert lookup_since(N) == N - timedelta(seconds=smd.LOOKUP_SLACK_S)
    assert isinstance(smd.BOOT_TS, datetime)


_harness.run()
