#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401  — MUST be first: binds a throwaway temp DB

import importlib
import math
import os

import of_pacing  # noqa: E402
import transaction_ingest as tx  # noqa: E402
from tx_ingest_admin_api import _tx_ingest_tier  # noqa: E402

_ENV = "INGEST_TICK_INTERVAL_S"
_FLEET, _PAGES = 50, 10


def _fleet_cycle_s() -> float:
    waves = math.ceil(_FLEET / tx._REFRESH_CONCURRENCY)
    return waves * _PAGES * (of_pacing.PAGE_GAP_S + of_pacing.JITTER_S)


def _reloaded(value):
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
    assert _tx_ingest_tier(worst + 10, "ok", 0) == "green", (
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
    assert _tx_ingest_tier((tx._MAX_TICK_INTERVAL_S + _fleet_cycle_s()) / 60, "ok", 0) == "green"


def _knob(env: str, attr: str, value):
    old = os.environ.get(env)
    try:
        if value is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = value
        return getattr(importlib.reload(tx), attr)
    finally:
        if old is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = old
        importlib.reload(tx)


def case_recent_window_and_full_every_clamps():
    table = [
        ("INGEST_RECENT_WINDOW_H", "_RECENT_WINDOW_H",
         ((None, 24.0), ("36", 36.0), ("12", 12.0), ("1", 12.0), ("6", 12.0), ("168", 168.0),
          ("500", 168.0), ("-3", 12.0), ("garbage", 24.0), ("", 24.0), ("inf", 24.0), ("nan", 24.0))),
        ("INGEST_FULL_EVERY_S", "_FULL_EVERY_S",
         ((None, 7200.0), ("3600", 3600.0), ("60", 900.0), ("900", 900.0), ("86400", 86400.0),
          ("1e9", 86400.0), ("garbage", 7200.0), ("-inf", 7200.0))),
    ]
    for env, attr, rows in table:
        for value, want in rows:
            assert _knob(env, attr, value) == want, (env, value, want)


def case_stale_inflight_below_the_tick():
    for v in ("60", "300", "900", "1500"):
        tick, stale = _reloaded(v)
        assert stale < tick and stale <= 900.0, (v, tick, stale)


_harness.run()
