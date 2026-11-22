#!/usr/bin/env python3
"""test_full_ai_owner — `full_ai_owner`'s pure tables (spec 04b › Testing Decisions).

  case_who_owns_table        one case per Stop reason; None when all clear
  case_who_owns_pairs        each adjacent pair of REASONS set together returns the earlier one (the
                             off_* trio and the human pair share one field: their order is the loader's,
                             test_full_ai_owner_io)
  case_top_spend_edges       0 never stops; equal stops; one cent under does not
  case_claims_table          true only with off None and listed; a Fan over the Top spend limit, hard
                             skipped or in a walk is still claimed
  case_pure_imports          no DB, OF client, lease or dm_rate import (AST)

Run: ./venv/bin/python service/tests/test_full_ai_owner.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import ast  # noqa: E402
import dataclasses  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from automations import full_ai_owner as fo  # noqa: E402
from automations.full_ai_owner import OwnerFacts, Stop, claims, who_owns  # noqa: E402

CLEAR = OwnerFacts(off=None, listed=True, hard_skip=False, audience_ok=True, human=None, human_at=None,
                   walk_advancing=False, spend_cents=0, top_spend_cents=100000)
# reason -> the facts change that alone raises it
RAISE = {
    "off_global": {"off": "off_global"}, "off_rule": {"off": "off_rule"}, "off_mode": {"off": "off_mode"},
    "not_listed": {"listed": False}, "hard_skip": {"hard_skip": True}, "audience": {"audience_ok": False},
    "human": {"human": "human", "human_at": datetime(2026, 11, 15, 12)},
    "human_of_app": {"human": "human_of_app", "human_at": datetime(2026, 11, 15, 12)},
    "funnel_walk": {"walk_advancing": True}, "top_spend": {"spend_cents": 100000},
}


def case_who_owns_table():
    assert who_owns(CLEAR) is None
    assert tuple(RAISE) == fo.REASONS, fo.REASONS
    for reason, change in RAISE.items():
        assert who_owns(dataclasses.replace(CLEAR, **change)) == Stop(reason), reason


def case_who_owns_pairs():
    checked = 0
    for a, b in zip(fo.REASONS, fo.REASONS[1:]):
        if set(RAISE[a]) & set(RAISE[b]):        # one field (off, human): cannot both be set
            continue
        got = who_owns(dataclasses.replace(CLEAR, **RAISE[a], **RAISE[b]))
        assert got == Stop(a), (a, b, got)
        checked += 1
    assert checked == 6, checked                  # off_mode/not_listed ... funnel_walk/top_spend
    # every reason beats everything below it, not only its neighbour
    for i, a in enumerate(fo.REASONS):
        below = {}
        for b in fo.REASONS[i + 1:]:
            if not set(RAISE[b]) & set(RAISE[a]):
                below.update(RAISE[b])
        assert who_owns(dataclasses.replace(CLEAR, **below, **RAISE[a])) == Stop(a), a


def case_top_spend_edges():
    f = lambda spend, top: who_owns(dataclasses.replace(CLEAR, spend_cents=spend, top_spend_cents=top))  # noqa: E731
    assert f(10**9, 0) is None                    # 0 = off
    assert f(0, 0) is None
    assert f(5000, 5000) == Stop("top_spend")     # equal stops
    assert f(4999, 5000) is None
    assert f(5001, 5000) == Stop("top_spend")


def case_claims_table():
    rows = [(None, True, True), (None, False, False), ("off_global", True, False), ("off_rule", True, False),
            ("off_mode", True, False), ("off_mode", False, False)]
    for off, listed, want in rows:
        assert claims(off, listed) is want, (off, listed)
    # claims reads only off + listed: a Fan Full AI stops on (spend, hard skip, walk, human) stays claimed
    for change in (RAISE["top_spend"], RAISE["hard_skip"], RAISE["funnel_walk"], RAISE["human"]):
        f = dataclasses.replace(CLEAR, **change)
        assert who_owns(f) is not None and claims(f.off, f.listed), change


_BANNED = ("db", "sqlalchemy", "of_client", "fan_lease", "dm_rate", "automation_executor", "job_queue",
           "automations._outbound", "audience_include", "runtime_switches")


def case_pure_imports():
    src = (Path(fo.__file__)).read_text()
    found = []
    for n in ast.walk(ast.parse(src)):
        mods = []
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""] + [f"{n.module}.{a.name}" for a in n.names]
        found += [m for m in mods if any(m == b or m.startswith(b + ".") for b in _BANNED)]
    assert found == [], found
    imported = {a.name.split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "dataclasses", "datetime", "of_shapes"}, imported   # of_shapes: pure parsers


if __name__ == "__main__":
    _harness.run()
