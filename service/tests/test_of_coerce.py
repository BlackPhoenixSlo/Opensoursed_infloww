#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import event_transcode_decide as td  # noqa: E402
import transaction_ingest_decide as tid  # noqa: E402
from of_coerce import cents_or_none, cents_or_zero, json_list, strip_tags  # noqa: E402

try:
    if __name__ == "__main__":
        raise ImportError
    import pytest
    table = pytest.mark.parametrize
except ImportError:
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark


@table("v,want_none,want_zero", [
    (9.99, 999, 999),
    ("9.99", 999, 999),
    (0, 0, 0),
    (0.005, 0, 0),
    ("", None, 0),
    (None, None, 0),
    ("abc", None, 0),
    (True, 100, 100),
    ([], None, 0),
    ("inf", None, 0),
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
