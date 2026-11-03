#!/usr/bin/env python3
"""
session_stamps.session_verdict, impersonation_verdict and blocks_write —
table tests over a signed-in cookie's fate on one request, as
auth.session_middleware (30-day idle, LAST_SEEN_TOUCH_S) and
chatters._session_identity (30-day idle, LAST_SEEN_TOUCH_S) apply it, and
over an impersonate cookie's. Both session comparisons are strict: exactly at
a threshold is still the shorter fate.

  case_table:       ok / touch / expired at and around each boundary, revoked
                    (issued before, at, after sessions_valid_after).
  case_thresholds:  the callers' numbers are unchanged.
  case_impersonation: session_stamps.impersonation_verdict (auth._apply_impersonation): TTL
                    strict (age == ttl applies), founder binding, a None parse clears.
  case_impersonate_malformed: every cookie shape auth._parse_impersonate_cookie rejects
                    parses to None and so clears; a good one applies.
  case_blocks_write: session_stamps.blocks_write (auth.session_middleware): every mutating
                    method x exempt / non-exempt path; GET/HEAD/OPTIONS and not impersonating
                    never block.

Run: ./venv/bin/python service/tests/test_session_verdict.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from datetime import datetime, timedelta  # noqa: E402

from session_stamps import blocks_write, impersonation_verdict, session_verdict  # noqa: E402

IDLE, TOUCH, IMP_TTL = 30 * 24 * 3600, 300, 3600
NOW = datetime(2026, 10, 31, 12, 0, 0)
NOW_S = int(NOW.timestamp())
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
    assert auth.IMPERSONATE_TTL_SECONDS == IMP_TTL


# (label, parsed cookie, signed-in founder) -> verdict
IMP_TABLE = [
    ("fresh, own founder: apply", ("u2", "f1", NOW_S), "f1", "apply"),
    ("issued in the future (clock skew): apply", ("u2", "f1", NOW_S + 60), "f1", "apply"),
    ("ttl - 1 s: apply", ("u2", "f1", NOW_S - IMP_TTL + 1), "f1", "apply"),
    ("ttl boundary exactly: apply", ("u2", "f1", NOW_S - IMP_TTL), "f1", "apply"),
    ("ttl + 1 s: clear", ("u2", "f1", NOW_S - IMP_TTL - 1), "f1", "clear"),
    ("another founder: clear", ("u2", "f1", NOW_S), "f9", "clear"),
    ("another founder and stale: clear", ("u2", "f1", NOW_S - IMP_TTL - 1), "f9", "clear"),
    ("impersonating oneself, own founder: apply", ("f1", "f1", NOW_S), "f1", "apply"),
    ("malformed (parse None): clear", None, "f1", "clear"),
]


def case_impersonation():
    bad = []
    for label, parsed, founder, want in IMP_TABLE:
        got = impersonation_verdict(parsed, NOW, founder, ttl=IMP_TTL)
        if got != want:
            bad.append(f"{label}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_impersonate_malformed():
    import auth
    import session_stamps
    import signed_cookie
    sec = session_stamps.SESSION_SECRET

    def mk(*fields):
        return signed_cookie.make(sec, *fields)

    good = mk("u2", "f1", str(NOW_S))
    shapes = [
        ("empty", ""),
        ("no dots", "garbage"),
        ("bad signature", good[:-1] + ("0" if good[-1] != "0" else "1")),
        ("signed under another secret", signed_cookie.make(b"other", "u2", "f1", str(NOW_S))),
        ("2 fields (a session cookie)", mk("u2", str(NOW_S))),
        ("4 fields", mk("u2", "f1", str(NOW_S), "x")),
        ("non-int stamp, valid signature", mk("u2", "f1", "soon")),
    ]
    bad = []
    for label, raw in shapes:
        parsed = auth._parse_impersonate_cookie(raw)
        if parsed is not None:
            bad.append(f"{label}: parsed {parsed!r}")
        elif impersonation_verdict(parsed, NOW, "f1", ttl=IMP_TTL) != "clear":
            bad.append(f"{label}: not cleared")
    assert auth._parse_impersonate_cookie(good) == ("u2", "f1", NOW_S)
    assert impersonation_verdict(auth._parse_impersonate_cookie(good), NOW, "f1", ttl=IMP_TTL) == "apply"
    assert not bad, "\n".join(bad)


# (method, path, impersonating) -> blocked
BLOCKS_TABLE = [
    ("POST", "/admin/messages", True, True),
    ("PATCH", "/admin/messages", True, True),
    ("PUT", "/admin/users/u2", True, True),
    ("DELETE", "/admin/users/u2", True, True),
    ("POST", "/", True, True),
    ("POST", "/auth", True, True),                   # no slash: not under /auth/
    ("POST", "/api/auth/logout", True, True),
    ("DELETE", "/admin/Impersonate", True, True),    # case-sensitive
    ("POST", "/admin/impersonate", True, False),
    ("DELETE", "/admin/impersonate", True, False),
    ("PATCH", "/admin/impersonate/exit", True, False),
    ("PUT", "/admin/impersonated", True, False),     # a prefix, as ever
    ("POST", "/auth/logout", True, False),
    ("DELETE", "/auth/", True, False),
    ("GET", "/admin/messages", True, False),
    ("HEAD", "/admin/users/u2", True, False),
    ("OPTIONS", "/admin/messages", True, False),
    ("POST", "/admin/messages", False, False),
    ("DELETE", "/admin/users/u2", False, False),
    ("GET", "/admin/messages", False, False),
]


def case_blocks_write():
    bad = []
    for method, path, imp, want in BLOCKS_TABLE:
        got = blocks_write(method, path, imp)
        if got is not want:
            bad.append(f"{method} {path} impersonating={imp}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


if __name__ == "__main__":
    _harness.run()
