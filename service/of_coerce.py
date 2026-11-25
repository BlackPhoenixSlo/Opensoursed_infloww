from __future__ import annotations

import json
import re
from typing import Any, Callable

_HTML_TAG = re.compile(r"<[^>]+>")


def cents_or_none(v: Any) -> int | None:
    # int(round(float(v) * 100)) sidesteps the 9.99 -> 998 float trap.
    if v is None or v == "":
        return None
    try:
        return int(round(float(v) * 100))
    except Exception:
        return None


def cents_or_zero(v: Any) -> int:
    return cents_or_none(v) or 0


def strip_tags(s: str | None) -> str:
    if not s:
        return ""
    if "<" not in s:
        return s.strip()
    return _HTML_TAG.sub("", s).strip()


def json_list(raw: str | None, coerce: Callable[[Any], Any] | None = None) -> list[Any]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(v, list):
        return []
    return [coerce(x) for x in v] if coerce else v
