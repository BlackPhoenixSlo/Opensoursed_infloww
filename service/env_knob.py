from __future__ import annotations

import logging
import math
import os

log = logging.getLogger("of-relay.env_knob")


def env_float(name: str, default: float, lo: float = -math.inf) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = float(raw)
    except ValueError:
        v = math.nan
    # Malformed, non-finite or under lo falls back to default with a warning: an operator typo must not take the relay down at import.
    if not math.isfinite(v) or v < lo:
        log.warning("env_knob_bad_value name=%s value=%r — using default %g", name, raw, default)
        return default
    return v
