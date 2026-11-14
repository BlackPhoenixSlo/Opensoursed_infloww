#!/usr/bin/env python3
"""login_paste (ultra-mode ticket 11): the pasted-logins parser and the credential guard, as tables. Pure.

Cases:
  case_shared_table    — every row of fixtures/login_paste_cases.json (the table app/lib/loginPaste.test.ts
                         checks too): parse's login count and bad lines by number + reason, holds_login.
                         Separators, blank lines, duplicates (any case), each str.splitlines() boundary,
                         over MAX_LOGINS, the guard's inline forms.
  case_passwords       — parse's email + password (spaces around the separator dropped, the rest of the line
                         kept); the relay only, so not in the shared table.
  case_bad_never_text  — a bad line's report holds its number and reason, never its text.
  case_fast_at_64kb    — crafted pastes at the route's 64 kB limit (remote_login_api.MAX_PASTE): parse and
                         holds_login each under 0.2 s (the relay is one process; measured ~10 ms worst).

Run: ./venv/bin/python service/tests/test_login_paste.py   (exit 0 = green)
"""
import _harness  # MUST be first (house style; this module touches no DB)

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import login_paste as lp  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "login_paste_cases.json")


def case_shared_table() -> None:
    with open(FIXTURE, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    assert len(cases) >= 40, len(cases)
    assert any(c["count"] == lp.MAX_LOGINS and c["bad"] for c in cases), "the cap row"
    for c in cases:
        ok, bad = lp.parse(c["text"])
        assert len(ok) == c["count"], (c["text"], ok)
        assert [[b.line, b.reason] for b in bad] == c["bad"], (c["text"], bad)
        assert lp.holds_login(c["text"]) is c["holds"], c["text"]


PASSWORDS = [
    # text → [(line, email, password)]
    ("a@x.com:pw1", [(1, "a@x.com", "pw1")]),
    ("  a@x.com : pw 1  ", [(1, "a@x.com", "pw 1")]),
    ("a@x.com:p:w|1", [(1, "a@x.com", "p:w|1")]),
    ("a@x.com::pw", [(1, "a@x.com", ":pw")]),
    ("\n\na@x.com:pw1\n   \nb@y.com\tpw2\n", [(3, "a@x.com", "pw1"), (5, "b@y.com", "pw2")]),
    ("a@example.com:pw1\nA@EXAMPLE.COM:pw2", [(1, "a@example.com", "pw1")]),
]


def case_passwords() -> None:
    for text, want in PASSWORDS:
        ok, _ = lp.parse(text)
        assert [(x.line, x.email, x.password) for x in ok] == want, (text, ok)


def case_bad_never_text() -> None:
    _, bad = lp.parse("secret-thing-1\nx@y.com:\nother secret-2")
    assert bad and all(set(vars(b)) == {"line", "reason"} for b in bad), bad
    assert "secret" not in repr(bad), bad


PASTE_LIMIT = 64 * 1024  # remote_login_api.MAX_PASTE (not imported: that pulls in the app)


def _lines_of(unit: str) -> str:
    return "\n".join([unit] * (PASTE_LIMIT // (len(unit) + 1)))


CRAFTED = [  # each a shape that made the earlier regexes backtrack (seconds at 64 kB)
    _lines_of("a@x.com:x" + " " * 500 + "x"),
    _lines_of("a@" + "x." * 254 + "x,"),
    _lines_of("a@x.com" + " " * 500 + "\u00a0x"),
    "a@x.com" + " " * (PASTE_LIMIT - 20) + "\u00a0x",
    "x@" + "a." * (PASTE_LIMIT // 2 - 2) + ":",
    "a@x" + "." * (PASTE_LIMIT - 10),
    "a@" * (PASTE_LIMIT // 2),
    "a.b@c.d" * (PASTE_LIMIT // 7),
]


def case_fast_at_64kb() -> None:
    for text in CRAFTED:
        assert len(text) <= PASTE_LIMIT, len(text)
        for fn in (lp.parse, lp.holds_login):
            t0 = time.perf_counter()
            fn(text)
            took = time.perf_counter() - t0
            assert took < 0.2, (fn.__name__, text[:40], took)


_harness.run()
