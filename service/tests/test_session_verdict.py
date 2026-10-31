#!/usr/bin/env python3
"""
session_stamps.session_verdict — table tests over a signed-in cookie's fate
on one request, as auth.session_middleware (30-day idle, LAST_SEEN_TOUCH_S) and
chatters._session_identity (30-day idle, LAST_SEEN_TOUCH_S) apply it. Both
comparisons are strict: exactly at a threshold is still the shorter fate.

  case_table:       ok / touch / expired at and around each boundary, revoked
                    (issued before, at, after sessions_valid_after).
  case_thresholds:  the callers' numbers are unchanged.

Run: ./venv/bin/python service/tests/test_session_verdict.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from datetime import datetime, timedelta  # noqa: E402

from session_stamps import session_verdict  # noqa: E402

IDLE, TOUCH = 30 * 24 * 3600, 300
NOW = datetime(2026, 10, 31, 12, 0, 0)
ISSUED = int((NOW - timedelta(days=1)).timestamp() * 1000)
EPS = timedelta(microseconds=1)


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


# (label, issued_ms, valid_after, last_seen) -> verdict
TABLE = [
    ("just seen", ISSUED, None, NOW, "ok"),
    ("seen in the future (clock skew)", ISSUED, None, NOW + timedelta(minutes=5), "ok"),
    ("touch boundary exactly 300 s: ok", ISSUED, None, ago(seconds=TOUCH), "ok"),
    ("just past 300 s: touch", ISSUED, None, ago(seconds=TOUCH) - EPS, "touch"),
    ("a day idle: touch", ISSUED, None, ago(days=1), "touch"),
    ("idle boundary exactly 30 d: touch", ISSUED, None, ago(seconds=IDLE), "touch"),
    ("just past 30 d: expired", ISSUED, None, ago(seconds=IDLE) - EPS, "expired"),
    ("revoked after issue: expired", ISSUED, ago(hours=1), NOW, "expired"),
    ("revoked at the issue ms: ok", ISSUED, datetime.fromtimestamp(ISSUED / 1000), NOW, "ok"),
    ("revoked 1 ms after issue: expired", ISSUED,
     datetime.fromtimestamp((ISSUED + 1) / 1000), NOW, "expired"),
    ("revoked before issue, stale stamp: touch", ISSUED, ago(days=2), ago(hours=1), "touch"),
    ("revoked and idle: expired", ISSUED, ago(hours=1), ago(days=31), "expired"),
]


def case_table():
    bad = []
    for label, issued, valid_after, last_seen, want in TABLE:
        got = session_verdict(issued, valid_after, last_seen, NOW, max_idle_s=IDLE, touch_s=TOUCH)
        if got != want:
            bad.append(f"{label}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_thresholds():
    import auth
    import chatters
    assert auth.SESSION_INACTIVITY_SECONDS == IDLE
    assert chatters.SESSION_INACTIVITY_SECONDS == IDLE
    assert auth.LAST_SEEN_TOUCH_S == TOUCH
    assert chatters.LAST_SEEN_TOUCH_S == TOUCH


if __name__ == "__main__":
    _harness.run()
