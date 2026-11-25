#!/usr/bin/env python3
from __future__ import annotations

import _harness

import importlib  # noqa: E402
import logging  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402

import env_knob  # noqa: E402

KEY = "X_ENV_KNOB_TEST"


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _set(raw):
    if raw is None:
        os.environ.pop(KEY, None)
    else:
        os.environ[KEY] = raw


def case_table():
    grab = _Grab()
    env_knob.log.addHandler(grab)
    try:
        for raw, lo, want, warns in [
            (None, -math.inf, 30.0, False),
            ("", -math.inf, 30.0, False),
            ("  ", 5.0, 30.0, False),
            ("abc", -math.inf, 30.0, True),
            ("nan", -math.inf, 30.0, True),
            ("inf", -math.inf, 30.0, True),
            ("-inf", -math.inf, 30.0, True),
            ("2", 5.0, 30.0, True),
            ("5", 5.0, 5.0, False),
            ("45.5", 5.0, 45.5, False),
            ("0", -math.inf, 0.0, False),
            ("-3", -math.inf, -3.0, False),
        ]:
            grab.lines.clear()
            _set(raw)
            got = env_knob.env_float(KEY, 30.0, lo)
            assert got == want, (raw, lo, got, want)
            assert bool(grab.lines) == warns, (raw, grab.lines)
            if warns:
                assert len(grab.lines) == 1 and f"name={KEY}" in grab.lines[0], grab.lines
    finally:
        env_knob.log.removeHandler(grab)
        _set(None)


def case_view_lease_ttl():
    import view_lease
    old = os.environ.get("VIEW_LEASE_TTL_S")
    try:
        for raw, want in (("0", 60.0), ("-5", 60.0), ("0.5", 0.5), ("90", 90.0), (None, 60.0)):
            if raw is None:
                os.environ.pop("VIEW_LEASE_TTL_S", None)
            else:
                os.environ["VIEW_LEASE_TTL_S"] = raw
            assert importlib.reload(view_lease).TTL_S == want, (raw, view_lease.TTL_S)
    finally:
        if old is None:
            os.environ.pop("VIEW_LEASE_TTL_S", None)
        else:
            os.environ["VIEW_LEASE_TTL_S"] = old
        importlib.reload(view_lease)


_harness.run()
