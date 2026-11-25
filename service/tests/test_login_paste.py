#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

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


PASTE_LIMIT = 64 * 1024


def _lines_of(unit: str) -> str:
    return "\n".join([unit] * (PASTE_LIMIT // (len(unit) + 1)))


CRAFTED = [
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
