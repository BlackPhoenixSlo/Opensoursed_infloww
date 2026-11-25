from __future__ import annotations

import json
import re
from typing import Any

from jsonsafe import load_json


def normalize_tags(v: Any) -> list[str]:
    if isinstance(v, str):
        parts = re.split(r"[,\n]", v)
    elif isinstance(v, (list, tuple)):
        parts = [str(x) for x in v]
    else:
        parts = []
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        t = str(p).strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:12]





def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def overrides(item: Any) -> dict:
    return load_json(getattr(item, "operator_overrides_json", None), {}) or {}


def ai_fields(item: Any) -> dict:
    return load_json(getattr(item, "ai_fields_json", None), {}) or {}


def locked_fields(item: Any) -> set[str]:
    raw = load_json(getattr(item, "locked_fields_json", None), [])
    return set(raw) if isinstance(raw, (list, tuple, set)) else set()


def effective_value(item: Any, field: str, config: Any = None, *, default: Any = None) -> Any:
    ov = overrides(item)
    # Override present by KEY wins even if empty (blanking is intentional); the lock only matters at write time. Precedence: override > AI field > legacy column > default.
    if field in ov:
        return ov[field]

    ai = ai_fields(item).get(field)
    if not _is_blank(ai):
        return ai

    legacy = getattr(item, field, None)
    if not _is_blank(legacy):
        return legacy

    if isinstance(config, dict):
        cfg_default = (config.get("defaults") or {}).get(field)
        if not _is_blank(cfg_default):
            return cfg_default

    return default
