#!/usr/bin/env python3
"""of_coerce: the shared OF value coercers as tables. Pure: no DB, no I/O.

Pins: cents round half-to-even off float(v) * 100 (0.005 → 0, True → 100); cents_or_none
keeps None/""/non-numeric as None, cents_or_zero folds them to 0. strip_tags drops every
tag and trims; a lone "<" with no ">" is kept. json_list reads only a JSON list ([] for
empty/bad/non-list) and maps items through `coerce`. The pure decide modules alias these
very functions (the shells' aliases need a DB import; their own tests cover them).

Runs under pytest (parametrized tables) or as a script (the repo's convention, no pytest needed):
    ./venv/bin/python service/tests/test_of_coerce.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import event_transcode_decide as td  # noqa: E402
import transaction_ingest_decide as tid  # noqa: E402
from of_coerce import cents_or_none, cents_or_zero, json_list, strip_tags  # noqa: E402

try:
    import pytest
    table = pytest.mark.parametrize
except ImportError:  # script mode: the runner below calls each row
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark


@table("v,want_none,want_zero", [
    (9.99, 999, 999),
    ("9.99", 999, 999),
    (0, 0, 0),
    (0.005, 0, 0),          # 0.5 → round half-to-even → 0 (measured)
    ("", None, 0),
    (None, None, 0),
    ("abc", None, 0),
    (True, 100, 100),       # bool is an int to float(); callers that care guard it
    ([], None, 0),          # float([]) TypeError
    ("inf", None, 0),       # OverflowError off round(inf)
])
def test_cents(v, want_none, want_zero):
    assert cents_or_none(v) == want_none
    assert cents_or_zero(v) == want_zero


@table("s,want", [
    (None, ""),
    ("", ""),
    ("  hi ", "hi"),
    ("<p>a</p>", "a"),
    ("<p>a<br/>b</p>", "ab"),
    ("a < b", "a < b"),
])
def test_strip_tags(s, want):
    assert strip_tags(s) == want


@table("raw,coerce,want", [
    (None, None, []),
    ("", None, []),
    ("[1,2]", None, [1, 2]),
    ("{}", None, []),
    ("bad", None, []),
    ("[1,2]", str, ["1", "2"]),
])
def test_json_list(raw, coerce, want):
    assert json_list(raw, coerce) == want


def test_decide_aliases():
    assert td.to_cents is cents_or_zero and td.strip_html is strip_tags
    assert tid._to_cents is cents_or_none and tid._strip_html is strip_tags


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
