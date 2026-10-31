"""Pure coercers for OF payload values (dollars → cents, HTML bodies, JSON
list columns). Stdlib only — no service imports, so any module can use it.
Tables: tests/test_of_coerce.py.

The two cents flavours differ only in the fallback: `cents_or_none` keeps
"absent" distinct (tx-ingest net/fee/vat columns), `cents_or_zero` folds it
into 0 (message prices, tips, promo/earnings dollar amounts)."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

_HTML_TAG = re.compile(r"<[^>]+>")


def cents_or_none(v: Any) -> int | None:
    """OF dollars (9.99 or "9.99") → 999. None/"" or non-numeric → None.
    `int(round(float(v) * 100))` sidesteps the 9.99 → 998 float trap."""
    if v is None or v == "":
        return None
    try:
        return int(round(float(v) * 100))
    except Exception:
        return None


def cents_or_zero(v: Any) -> int:
    """`cents_or_none`, with every fallback → 0."""
    return cents_or_none(v) or 0


def strip_tags(s: str | None) -> str:
    """Cheap tag strip for previews/descriptions (OF wraps bodies in <p>…</p>);
    full sanitization happens client-side when the body is rendered."""
    if not s:
        return ""
    if "<" not in s:
        return s.strip()
    return _HTML_TAG.sub("", s).strip()


def json_list(raw: str | None, coerce: Callable[[Any], Any] | None = None) -> list[Any]:
    """A JSON-list text column → list; empty/bad/non-list → []. `coerce` maps
    each item (fans.tags passes `str`)."""
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(v, list):
        return []
    return [coerce(x) for x in v] if coerce else v
