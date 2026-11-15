"""
One float knob from the environment, the parse the purchases poll (purchase_poll_decide), the View lease
(view_lease) and the ledger ingest (transaction_ingest) share. No imports of the relay: any module may read its
knobs through it at import time.

Unset or blank -> `default`, quietly. Malformed, non-finite (inf, nan) or under `lo` -> `default`, with one
warning naming the knob: an operator typo must not take the relay down at import, nor pass for a value.
A ceiling or a clamp is the caller's (transaction_ingest._clamped_env).
"""
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
    if not math.isfinite(v) or v < lo:
        log.warning("env_knob_bad_value name=%s value=%r — using default %g", name, raw, default)
        return default
    return v
