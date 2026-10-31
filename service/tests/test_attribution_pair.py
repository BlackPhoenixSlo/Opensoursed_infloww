#!/usr/bin/env python3
"""
attribution_pair — table tests over attribution.py's pure half. No DB, no OF.

  case_pair_table:           pair_placeholders: exact twin; two candidates, nearest wins;
                             `<br />` echo == stored `\\n`; 6 h pairs, 6 h + 1 s refused;
                             no twin; two stubs one real (no double adopt); media-only
                             key refused; unusable clock refused; a row another run
                             holds is left, and does not fence a later pair.
  case_pair_order_independent: the same rows in any order give the same pairs.
  case_adopt_windows_table:  adopt_windows: none, one, overlap merges, touching merges,
                             apart stays two, unsorted input, a burst is one range.
  case_hard_yield_table:     hard_yield per sender kind (human 1:1, mass, automation,
                             unknown, sentinel lookup failed).
  case_manual_yield_table:   manual_yield_s: absent / bad JSON / non-numeric -> 60,
                             0 disables, positive passes through, NEGATIVE -> 0 (pinned:
                             clamps, so it disables; it is not "bad -> default").

Run: ./venv/bin/python service/tests/test_attribution_pair.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import itertools  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from attribution import _MASS_PLACEHOLDER_BASE as BASE  # noqa: E402
from attribution_pair import adopt_windows, hard_yield, manual_yield_s, pair_placeholders  # noqa: E402

MAX = 6 * 3600.0
T0 = datetime(2026, 10, 31, 12, 0, 0)
CAP = "filmed somethin earlier\nthought of u"
ECHO = "filmed somethin earlier<br />thought of u"


@dataclass
class Row:
    message_id: int
    body: str | None
    created_at: datetime | None
    mass_run_id: int | None = None


def ph(run: int, at=T0, body=CAP) -> Row:
    return Row(BASE + run, body, at, run)


def real(mid: int, at=T0, body=ECHO, run=None) -> Row:
    return Row(mid, body, at, run)


def s(n: float) -> datetime:
    return T0 + timedelta(seconds=n)


def ids(pairs) -> list[tuple[int, int]]:
    return [(p.message_id, r.message_id) for p, r in pairs]


def _table(rows, fn) -> None:
    bad = []
    for rid, args, want in rows:
        got = fn(*args)
        if got != want:
            bad.append(f"{rid}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_pair_table():
    _table([
        ("exact twin", ([ph(1)], [real(10, s(3), body=CAP)]), [(BASE + 1, 10)]),
        ("two candidates, nearest wins",
         ([ph(1)], [real(10, s(600)), real(11, s(5)), real(12, s(-900))]), [(BASE + 1, 11)]),
        ("<br /> echo pairs with stored newline", ([ph(1)], [real(10, s(2))]), [(BASE + 1, 10)]),
        ("<br/> swapped for the newline pairs too",
         ([ph(1)], [real(10, s(2), body="filmed somethin earlier<br/>thought of u")]), [(BASE + 1, 10)]),
        ("exactly 6 h pairs", ([ph(1)], [real(10, s(MAX))]), [(BASE + 1, 10)]),
        ("6 h + 1 s refused", ([ph(1)], [real(10, s(MAX + 1))]), []),
        ("6 h + 1 s before refused", ([ph(1)], [real(10, s(-MAX - 1))]), []),
        ("no twin: other caption", ([ph(1)], [real(10, s(1), body="something else")]), []),
        ("no twin: no real rows", ([ph(1)], []), []),
        ("two stubs, one real: one adopt, the nearer",
         ([ph(1, s(-60)), ph(2, s(-5))], [real(10)]), [(BASE + 2, 10)]),
        ("two stubs, two reals: each its own nearest",
         ([ph(1, s(0)), ph(2, s(100))], [real(10, s(2)), real(11, s(103))]),
         [(BASE + 1, 10), (BASE + 2, 11)]),
        ("media-only stub never pairs", ([ph(1, body="<photo>")], [real(10, body="<photo>")]), []),
        ("unusable clock never pairs", ([ph(1, at=None)], [real(10)]), []),
        ("row held by another run is left",
         ([ph(1)], [real(10, s(1), run=2)]), []),
        ("row held by the same run pairs", ([ph(1)], [real(10, s(1), run=1)]), [(BASE + 1, 10)]),
        ("row held by a run, stub has none: left",
         ([Row(BASE + 9, CAP, T0, None)], [real(10, s(1), run=2)]), []),
        ("another run's row does not fence: next-nearest still pairs",
         ([ph(1)], [real(10, s(1), run=2), real(11, s(30))]), [(BASE + 1, 11)]),
        ("same caption 2 days apart: the old stub keeps waiting",
         ([ph(1, s(-2 * 86400)), ph(2, s(0))], [real(10, s(4))]), [(BASE + 2, 10)]),
    ], lambda phs, reals: ids(pair_placeholders(phs, reals, MAX)))


def case_pair_order_independent():
    phs = [ph(1, s(0)), ph(2, s(50)), ph(3, s(4000))]
    reals = [real(10, s(3)), real(11, s(48)), real(12, s(200))]
    want = None
    for pp in itertools.permutations(phs):
        for rr in itertools.permutations(reals):
            got = sorted(ids(pair_placeholders(list(pp), list(rr), MAX)))
            want = got if want is None else want
            assert got == want, (got, want)
    assert want == [(BASE + 1, 10), (BASE + 2, 11), (BASE + 3, 12)], want


def case_adopt_windows_table():
    H = timedelta(hours=6)
    _table([
        ("no stamps", ([],), []),
        ("one stamp", ([s(0)],), [(s(-MAX), s(MAX))]),
        ("overlap merges", ([s(0), s(3600)],), [(s(-MAX), s(3600 + MAX))]),
        ("touching merges", ([s(0), s(2 * MAX)],), [(s(-MAX), s(3 * MAX))]),
        ("1 s past touching stays two", ([s(0), s(2 * MAX + 1)],),
         [(s(-MAX), s(MAX)), (s(MAX + 1), s(3 * MAX + 1))]),
        ("unsorted input", ([s(2 * 86400), s(0)],),
         [(s(-MAX), s(MAX)), (s(2 * 86400 - MAX), s(2 * 86400 + MAX))]),
        ("a burst is one range", ([s(i) for i in range(50)],), [(s(-MAX), s(49 + MAX))]),
        ("a nested stamp keeps the wider end", ([s(0), s(10), s(5)],), [(s(-MAX), s(10 + MAX))]),
    ], lambda stamps: adopt_windows(stamps, H))


def case_hard_yield_table():
    AUTO = 2
    _table([
        ("human 1:1", (None, 7, AUTO), True),
        ("human mass", (42, 7, AUTO), False),
        ("automation 1:1", (None, AUTO, AUTO), False),
        ("automation mass", (42, AUTO, AUTO), False),
        ("unknown 1:1", (None, None, AUTO), False),
        ("unknown mass", (42, None, AUTO), False),
        ("sentinel lookup failed, 1:1: no yield", (None, 7, None), False),
        ("sentinel lookup failed, mass", (42, 7, None), False),
    ], lambda run, by, auto: hard_yield(mass_run_id=run, sent_by=by, automation_id=auto))


def case_manual_yield_table():
    _table([
        ("None", (None,), 60),
        ("empty string", ("",), 60),
        ("bad JSON", ("{nope",), 60),
        ("JSON null", ("null",), 60),
        ("JSON list", ("[1]",), 60),
        ("JSON number", ("5",), 60),
        ("key absent", ('{"other": 1}',), 60),
        ("key null", ('{"manual_yield_minutes": null}',), 60),
        ("0 disables", ('{"manual_yield_minutes": 0}',), 0),
        ("positive passes through", ('{"manual_yield_minutes": 5}',), 300),
        ("fraction", ('{"manual_yield_minutes": 0.5}',), 30),
        ("under a second truncates to 0", ('{"manual_yield_minutes": 0.01}',), 0),
        ("numeric string parses", ('{"manual_yield_minutes": "2"}',), 120),
        ("non-numeric string -> 60", ('{"manual_yield_minutes": "abc"}',), 60),
        ("list value -> 60", ('{"manual_yield_minutes": [1]}',), 60),
        ("NaN -> 60", ('{"manual_yield_minutes": NaN}',), 60),
        ("Infinity -> 60", ('{"manual_yield_minutes": Infinity}',), 60),
        ("negative clamps to 0 (pinned)", ('{"manual_yield_minutes": -3}',), 0),
    ], manual_yield_s)


_harness.run()
