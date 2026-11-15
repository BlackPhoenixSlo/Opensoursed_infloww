"""automations/_reserved_scripts.py — the reserved script-name rule.

A script id of `PREFIX` then ASCII digits only names a generated script: no
user script may take that name, and the Scripts page's import, copy and
overview leave such rows out. NULL, `PREFIX` alone, `PREFIX` + a non-digit
(`...x`) or digits then more (`...1-intro`) are not reserved.

  - `is_reserved_name(name)`: the rule in Python.
  - `is_reserved(column)`: the same rule as SQL (SQLite GLOB).
"""
from __future__ import annotations

from typing import Any

PREFIX = "FM"
# SQLite GLOBs: a reserved id is the prefix, a digit, then digits only.
GLOB = f"{PREFIX}[0-9]*"
NOT_GLOB = f"{PREFIX}*[^0-9]*"


def is_reserved_name(name: str) -> bool:
    """`name` is a reserved script id (the prefix and ASCII digits only)."""
    digits = name.removeprefix(PREFIX)
    return name != digits and digits.isascii() and digits.isdigit()


def is_reserved(column: Any) -> Any:
    """SQL: `column` holds a reserved script id (NULL is not one)."""
    return (column.is_not(None) & column.op("GLOB")(GLOB)
            & ~column.op("GLOB")(NOT_GLOB))
