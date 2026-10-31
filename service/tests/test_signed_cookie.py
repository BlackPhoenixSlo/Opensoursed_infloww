#!/usr/bin/env python3
"""
signed_cookie — table tests over the dotted HMAC cookie owner and chatter
sessions carry. The golden strings were minted by the code before the
extraction (auth._make_cookie / _make_impersonate_cookie, chatters._make_cookie
at fbde43777, secrets and clocks as below), so a cookie a browser holds today
still verifies:

  case_make_golden:       make() gives the old bytes for each cookie kind.
  case_parse_table:       golden, legacy whole-second stamp, tampered sig or
                          field, bad format, wrong secret, unsigned-number stamp.
  case_wrappers_golden:   auth / chatters' private helpers still mint and read
                          the same bytes under their own secrets, never each other's;
                          session_stamps.sign's scoped (2FA ticket) bytes.

Run: ./venv/bin/python service/tests/test_signed_cookie.py   (exit 0 = pass)
"""
from __future__ import annotations

import os

OWNER_SECRET = "golden-session-secret-W13"
CHATTER_SECRET = "golden-chatter-secret-W13"
os.environ["SESSION_SECRET"] = OWNER_SECRET            # before any service import
os.environ["CHATTER_SESSION_SECRET"] = CHATTER_SECRET

import _harness  # noqa: E402  MUST be first service import (binds a temp DB; never touched)

from datetime import datetime  # noqa: E402

import signed_cookie  # noqa: E402

OS, CS = OWNER_SECRET.encode(), CHATTER_SECRET.encode()

# Minted by the old code: auth.now_ms -> 1761900000123, chatters.now_ms ->
# 1761900000456, auth.datetime.utcnow() -> 2026-10-31 12:00:00 (local epoch, CET).
OWNER = "u-owner-1.1761900000123.2c2b9db9b9b801d2ece2247adcb60bcf9286469603a2ba3881bb03cb363ab903"
CHATTER = "c-chatter-1.1761900000456.38e9d4e21a9b413e93cab19baeee6dabc235f1b715529562f193f92f82e8af8a"
IMPERSONATE = ("u-friend-2.u-founder-1.1793444400."
               "4cefcd65141850da3cac51f9e2aa45ea9fb499eaf9289d686facf1ef3ff1f5d0")
OWNER_LEGACY_SECS = ("u-owner-1.1761900000."
                     "d4728bf2b588672afe8f60a196be6ce2dd29bd9347c3f519a5d3ef0c592c2765")
IMP_ISSUED = 1793444400
# session_stamps.sign("u-owner-1.1761900000123.ticket", "account-security") at fbde43777.
SCOPED_SIG = "e8d604baa7293be20914af8c3261c2e2b8a6460f7c9b60d8428242cc993c4c5e"


def _flip(c: str) -> str:
    return "0" if c != "0" else "1"


def case_make_golden():
    assert signed_cookie.make(OS, "u-owner-1", "1761900000123") == OWNER
    assert signed_cookie.make(CS, "c-chatter-1", "1761900000456") == CHATTER
    assert signed_cookie.make(OS, "u-friend-2", "u-founder-1", str(IMP_ISSUED)) == IMPERSONATE
    assert signed_cookie.sign(CS, "c-chatter-1.1761900000456") == CHATTER.rsplit(".", 1)[1]


# (label, secret, value) -> parse_issued result
ISSUED_TABLE = [
    ("owner golden", OS, OWNER, ("u-owner-1", 1761900000123)),
    ("chatter golden", CS, CHATTER, ("c-chatter-1", 1761900000456)),
    ("legacy whole seconds read as ms", OS, OWNER_LEGACY_SECS, ("u-owner-1", 1761900000000)),
    ("tampered sig", OS, OWNER[:-1] + _flip(OWNER[-1]), None),
    ("tampered user id", OS, "u-owner-2" + OWNER[len("u-owner-1"):], None),
    ("tampered stamp", OS, OWNER.replace("1761900000123", "1761900000124"), None),
    ("two parts", OS, OWNER.rsplit(".", 1)[0], None),
    ("four parts", OS, "x." + OWNER, None),
    ("empty", OS, "", None),
    ("wrong secret (chatter cookie under owner secret)", OS, CHATTER, None),
    ("wrong secret (owner cookie under chatter secret)", CS, OWNER, None),
    ("signed but not a number", OS, signed_cookie.make(OS, "u-owner-1", "soon"), None),
    ("impersonate shape is not a session", OS, IMPERSONATE, None),
]

# (label, value, n_fields) -> parse result under the owner secret
PARSE_TABLE = [
    ("impersonate golden", IMPERSONATE, 3, ["u-friend-2", "u-founder-1", str(IMP_ISSUED)]),
    ("impersonate tampered founder", IMPERSONATE.replace("u-founder-1", "u-founder-9"), 3, None),
    ("impersonate wrong field count", IMPERSONATE, 2, None),
    ("session as impersonate", OWNER, 3, None),
]


def case_parse_table():
    bad = []
    for label, secret, value, want in ISSUED_TABLE:
        got = signed_cookie.parse_issued(secret, value)
        if got != want:
            bad.append(f"{label}: {got!r} != {want!r}")
    for label, value, n, want in PARSE_TABLE:
        got = signed_cookie.parse(OS, value, n)
        if got != want:
            bad.append(f"{label}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_wrappers_golden():
    import auth
    import chatters
    import session_stamps
    assert session_stamps.SESSION_SECRET == OS and chatters._SESSION_SECRET == CS

    class _DT(datetime):
        @classmethod
        def utcnow(cls):
            return datetime(2026, 10, 31, 12, 0, 0)

    saved = auth.now_ms, chatters.now_ms, auth.datetime
    auth.now_ms = lambda: 1761900000123
    chatters.now_ms = lambda: 1761900000456
    auth.datetime = _DT
    try:
        assert auth._make_cookie("u-owner-1") == OWNER
        assert chatters._make_cookie("c-chatter-1") == CHATTER
        # The epoch is the naive utcnow() read in local time, as before: golden in
        # the TZ it was minted in (CET), the same formula anywhere.
        imp_issued = str(int(_DT.utcnow().timestamp()))
        assert auth._make_impersonate_cookie("u-friend-2", "u-founder-1") == signed_cookie.make(
            OS, "u-friend-2", "u-founder-1", imp_issued)
    finally:
        auth.now_ms, chatters.now_ms, auth.datetime = saved
    assert auth._parse_cookie_issued(OWNER) == ("u-owner-1", 1761900000123)
    assert auth._parse_cookie(OWNER) == "u-owner-1"
    assert auth._parse_cookie_issued(CHATTER) is None
    assert chatters._parse_cookie_issued(CHATTER) == ("c-chatter-1", 1761900000456)
    assert chatters._parse_cookie(CHATTER) == "c-chatter-1"
    assert chatters._parse_cookie(OWNER) is None
    assert auth._parse_impersonate_cookie(IMPERSONATE) == ("u-friend-2", "u-founder-1", IMP_ISSUED)
    assert auth._parse_impersonate_cookie(IMPERSONATE[:-1] + _flip(IMPERSONATE[-1])) is None
    assert auth._parse_impersonate_cookie(
        signed_cookie.make(OS, "u-friend-2", "u-founder-1", "later")) is None
    assert chatters._sign("c-chatter-1.1761900000456") == CHATTER.rsplit(".", 1)[1]
    assert session_stamps.sign("u-owner-1.1761900000123.ticket", "account-security") == SCOPED_SIG


if __name__ == "__main__":
    _harness.run()
