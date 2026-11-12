"""JavaScript value semantics for imported geo JSON."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# ── JS value semantics (geo rules hold arbitrary JSON) ────────────────

def js_truthy(v: Any) -> bool:
    if v is None or v is False:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True  # every object and array, empty ones included


def _js_num(f: float) -> str:
    """JS Number::toString for a double."""
    if f != f:
        return "NaN"
    if f in (float("inf"), float("-inf")):
        return "Infinity" if f > 0 else "-Infinity"
    if f == 0:
        return "0"
    sign = "-" if f < 0 else ""
    _, digs, exp = Decimal(repr(abs(f))).as_tuple()
    d = "".join(map(str, digs)).rstrip("0")
    exp += len(digs) - len(d)
    k = len(d)
    n = exp + k
    if k <= n <= 21:
        body = d + "0" * (n - k)
    elif 0 < n <= 21:
        body = d[:n] + "." + d[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * -n + d
    else:
        e = n - 1
        body = d[0] + ("." + d[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + body


def js_str(v: Any) -> str:
    if isinstance(v, str):
        return v
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        try:
            return _js_num(float(v))  # JSON.parse reads every number as a double
        except OverflowError:
            return "Infinity" if v > 0 else "-Infinity"
    if isinstance(v, float):
        return _js_num(v)
    if isinstance(v, dict):
        return "[object Object]"
    if isinstance(v, list):
        return ",".join("" if x is None else js_str(x) for x in v)
    return str(v)


_INDEX_KEY = re.compile(r"0|[1-9][0-9]*")


def _own(o: Any, k: Any) -> Any:
    """destination.js `own`: `k` truthy and an own key of `o`, else undefined (None)."""
    if not js_truthy(k) or not isinstance(k, str):
        return None
    if isinstance(o, dict):
        return o.get(k)
    if isinstance(o, list):
        if k == "length":
            return len(o)
        if _INDEX_KEY.fullmatch(k) and int(k) < len(o):
            return o[int(k)]
    return None


def geo_tracking_code(geo: Any, country: str, region: str) -> Any:
    """destination.js:13-22."""
    if not isinstance(geo, (dict, list)):
        return None
    rule = _own(geo, country)
    if js_truthy(rule):
        if isinstance(rule, (dict, list)):
            for v in (_own(rule, region), _own(rule, "default")):
                if js_truthy(v):
                    return v
            return None
        return rule
    v = _own(geo, "default")
    return v if js_truthy(v) else None


