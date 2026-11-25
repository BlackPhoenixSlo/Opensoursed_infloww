from __future__ import annotations

from typing import Any

PREFIX = "FM"
GLOB = f"{PREFIX}[0-9]*"
NOT_GLOB = f"{PREFIX}*[^0-9]*"


def is_reserved_name(name: str) -> bool:
    digits = name.removeprefix(PREFIX)
    return name != digits and digits.isascii() and digits.isdigit()


def is_reserved(column: Any) -> Any:
    return (column.is_not(None) & column.op("GLOB")(GLOB)
            & ~column.op("GLOB")(NOT_GLOB))
