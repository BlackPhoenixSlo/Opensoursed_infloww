#!/usr/bin/env python3
"""test_reserved_scripts — the reserved script-name rule (`automations/_reserved_scripts`).

One table: each id, whether it is reserved. `is_reserved_name` (Python) and
`is_reserved` (SQL, run on SQLite) must both give the table's answer.

Run: ./venv/bin/python service/tests/test_reserved_scripts.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

from sqlalchemy import Column, MetaData, String, Table, create_engine, select  # noqa: E402

from automations import _reserved_scripts as reserved  # noqa: E402

P = reserved.PREFIX
TABLE: list[tuple[str, bool]] = [
    (f"{P}12", True),
    (f"{P}0", True),
    (f"{P}007", True),
    (f"{P}1234567890", True),
    (P, False),                     # the prefix alone
    ("", False),
    (f"{P}x", False),
    (f"{P}1-intro", False),         # digits, then more
    (f"{P}2024promo", False),
    (f"{P}12 ", False),             # trailing space
    (f" {P}12", False),
    (f"x{P}12", False),
    (f"{P.lower()}12", False),      # case-sensitive
    (f"{P}-12", False),
    (f"{P}1.5", False),
    (f"{P}１２", False),    # full-width digits: not ASCII
    (f"{P}٣", False),          # Arabic-Indic digit: not ASCII
    ("12", False),
]


def case_python_rule_matches_the_table():
    bad = [(name, want) for name, want in TABLE if reserved.is_reserved_name(name) is not want]
    assert not bad, bad


def case_sql_rule_matches_the_table_and_null_is_not_reserved():
    md = MetaData()
    t = Table("t", md, Column("v", String, nullable=True))
    eng = create_engine("sqlite://")
    md.create_all(eng)
    with eng.begin() as c:
        c.execute(t.insert(), [{"v": name} for name, _ in TABLE] + [{"v": None}])
        hit = set(c.execute(select(t.c.v).where(reserved.is_reserved(t.c.v))).scalars())
        miss = list(c.execute(select(t.c.v).where(~reserved.is_reserved(t.c.v))).scalars())
    assert hit == {name for name, want in TABLE if want}, hit
    # NOT(NULL-aware rule) keeps a NULL id: the copy/overview filters never drop untitled sequences.
    assert None in miss and set(miss) - {None} == {name for name, want in TABLE if not want}, miss


if __name__ == "__main__":
    _harness.run()
