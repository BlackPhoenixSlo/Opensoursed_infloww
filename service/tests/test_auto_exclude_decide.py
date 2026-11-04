#!/usr/bin/env python3
"""
auto_exclude_decide — table tests over the pure rules of an Auto_Exclude past
the 20k backstop. No DB, no OF.

  case_next_batch_table:   adds (guard − members) before removes (members −
                           guard), ascending, at most n; `skip` leaves an id out
                           of both; None when in sync.
  case_refresh_due_table:  due once REFRESH_EVERY_S passed since the last
                           attempt; the module global read at call time.

Run: ./venv/bin/python service/tests/test_auto_exclude_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import auto_exclude_decide as aed  # noqa: E402
from auto_exclude_decide import Mirror, next_batch, refresh_due  # noqa: E402


def _table(rows, fn) -> None:
    bad = []
    for rid, args, want in rows:
        got = fn(*args)
        if got != want:
            bad.append(f"{rid}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_next_batch_table():
    _table([
        ("adds first, ascending, at most n", ({1, 2, 3, 10, 11}, {3, 4, 5, 6, 10}, 2, set()), ("add", [4, 5])),
        ("no adds left: removes", ({1, 2, 3, 10, 11}, {3, 10}, 2, set()), ("remove", [1, 2])),
        ("in sync: None", ({1, 2}, frozenset({1, 2}), 50, set()), None),
        ("skip drops a refused add", ({1, 2}, {1, 2, 3}, 50, {3}), None),
        ("skip drops a failed remove, the rest go", ({1, 2, 9}, {2}, 50, {9}), ("remove", [1])),
        ("empty members: all adds", (set(), {2, 1}, 5, set()), ("add", [1, 2])),
    ], next_batch)


def case_refresh_due_table():
    m = Mirror(list_id=50, members={1}, refreshed_at=1_000.0)
    every = aed.REFRESH_EVERY_S
    _table([
        ("just refreshed", (m, 1_000.0 + every - 1), False),
        ("REFRESH_EVERY_S since the last attempt", (m, 1_000.0 + every), True),
    ], refresh_due)
    old = aed.REFRESH_EVERY_S
    try:
        aed.REFRESH_EVERY_S = 3.0          # a patched module global reaches it
        assert refresh_due(m, 1_003.0) and not refresh_due(m, 1_002.0)
    finally:
        aed.REFRESH_EVERY_S = old


_harness.run(
    case_next_batch_table,
    case_refresh_due_table,
)
