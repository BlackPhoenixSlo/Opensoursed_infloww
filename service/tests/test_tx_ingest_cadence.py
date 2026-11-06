#!/usr/bin/env python3
"""
The payouts-ledger supervisor ticks every 15 min, and that must stay green.

2026-11-06: 300 s -> 900 s. The ledger lands hours late (209/560/628 min
after occurred_at, measured) and provider_id dedup makes a re-read a no-op,
so the 5-min full 7-day re-read was ~72 OF calls/h/account of waste. The
floor this file guards: the cadence plus one fleet cycle must still read
green on the ingest health tier (scanned within 30 min), with >= 10 min to
spare — at the default and at the env knob's 1500 s ceiling.

Plain-assert standalone script (no pytest), run via:
    ./venv/bin/python service/tests/test_tx_ingest_cadence.py
Exit 0 = all pass.
"""
from __future__ import annotations

import _harness  # noqa: F401  — MUST be first: binds a throwaway temp DB

import importlib
import math
import os

import of_pacing  # noqa: E402
import transaction_ingest as tx  # noqa: E402
from tx_ingest_admin_api import _tx_ingest_tier  # noqa: E402

_ENV = "INGEST_TICK_INTERVAL_S"
_FLEET, _PAGES = 50, 10   # sized-for fleet (<= 50 Creators), ~10 ledger pages a Creator per 7 days


def _fleet_cycle_s() -> float:
    """One supervisor pass over the whole fleet: _REFRESH_CONCURRENCY Creators at once, each
    paged at of_pacing's per-Creator pace (gap + full jitter, the worst case)."""
    waves = math.ceil(_FLEET / tx._REFRESH_CONCURRENCY)
    return waves * _PAGES * (of_pacing.PAGE_GAP_S + of_pacing.JITTER_S)


def _reloaded(value):
    """transaction_ingest re-imported with INGEST_TICK_INTERVAL_S = value (None: unset);
    returns (_TICK_INTERVAL_S, _STALE_INFLIGHT_S), then restores the env and the module."""
    old = os.environ.get(_ENV)
    try:
        if value is None:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = value
        m = importlib.reload(tx)
        return m._TICK_INTERVAL_S, m._STALE_INFLIGHT_S
    finally:
        if old is None:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = old
        importlib.reload(tx)


def case_default_is_900_and_green_with_margin():
    tick, stale = _reloaded(None)
    assert tick == tx._DEFAULT_TICK_INTERVAL_S == 900.0, tick
    assert stale == 720.0, stale
    worst = (tick + _fleet_cycle_s()) / 60
    assert _tx_ingest_tier(worst + 10, "ok") == "green", (
        f"{worst:.1f} min worst-case staleness leaves < 10 min to the 30 min green ceiling")


def case_env_override_honoured():
    assert _reloaded("300") == (300.0, 240.0)
    assert _reloaded("1200.5")[0] == 1200.5
    assert _reloaded("garbage")[0] == 900.0, "a typo must degrade to the default"
    assert _reloaded("")[0] == 900.0


def case_non_finite_is_default():
    for v in ("inf", "-inf", "nan", "Infinity"):
        assert _reloaded(v)[0] == 900.0, v


def case_clamp_floor_60_and_cap_1500():
    for v, want in (("0", 60.0), ("-5", 60.0), ("59.9", 60.0), ("60", 60.0),
                    ("1500", 1500.0), ("1500.1", 1500.0), ("86400", 1500.0)):
        assert _reloaded(v)[0] == want, (v, want)
    # The ceiling itself stays green with a fleet cycle on top (no 10 min margin promised there).
    assert _tx_ingest_tier((tx._MAX_TICK_INTERVAL_S + _fleet_cycle_s()) / 60, "ok") == "green"


def case_stale_inflight_below_the_tick():
    """A crashed tick's stamp is ~one interval old at the next visit: it must read stale then."""
    for v in ("60", "300", "900", "1500"):
        tick, stale = _reloaded(v)
        assert stale < tick and stale <= 900.0, (v, tick, stale)


_harness.run()
