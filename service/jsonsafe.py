from __future__ import annotations

import json
from typing import Any

PAYLOAD_CAP = 64 * 1024


# bool("false") is True: would turn a money-sending flag on from a raw-JSON edit or key=value stamp
def truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("", "false", "0", "no", "off", "null")
    return bool(v)


# Over the cap store a stub, not a slice: a byte-offset cut is unparseable JSON (261 bad raw_json rows were exactly 65536 bytes)
def dump_capped(payload: Any, *, limit: int = PAYLOAD_CAP) -> str:
    try:
        text = json.dumps(payload, default=str)
    except Exception:
        return json.dumps({"_dropped": "unserializable"})
    if len(text) <= limit:
        return text
    return json.dumps({"_dropped": "oversize", "_bytes": len(text)})


def load_json(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        val = json.loads(raw)
    # Bare on purpose: json.loads raises RecursionError (not ValueError) on deep nesting, and callers must fail open
    except Exception:
        return fallback
    return val if val is not None else fallback


def load_dict(raw: Any) -> dict:
    val = load_json(raw, {})
    return val if isinstance(val, dict) else {}
