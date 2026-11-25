#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

from datetime import datetime  # noqa: E402

from automations.rhythm import (  # noqa: E402
    DEFAULT_SLEEP, in_sleep_window, tz_hours_for, tz_offset_for,
)

_SLEEP_FROM_H = int(DEFAULT_SLEEP[0].split(":")[0])
_WAKE_H = int(DEFAULT_SLEEP[1].split(":")[0])


def case_timezone_resolver_is_dst_correct():
    assert tz_offset_for("America/New_York", None, datetime(2026, 7, 13, 12)) == -240
    assert tz_offset_for("America/New_York", None, datetime(2026, 1, 13, 12)) == -300
    assert tz_offset_for("Not/AZone", -5, datetime(2026, 7, 13, 12)) == -300
    assert tz_offset_for("Not/AZone", None, datetime(2026, 7, 13, 12)) is None


def case_no_timezone_falls_back_to_utc_offset():
    assert tz_offset_for(None, -5) == -300
    assert tz_offset_for(None, 8) == 480
    # 0 means unanswered, not UTC: defaulting to UTC would put a US creator to sleep at her peak.
    assert tz_offset_for(None, 0) is None
    assert tz_offset_for(None, None) is None
    assert tz_offset_for("", 0) is None


def case_tz_hours_for_is_the_one_hours_accessor():
    jan = datetime(2026, 1, 13, 12)
    jul = datetime(2026, 7, 13, 12)
    assert tz_hours_for(None, -4) == -4.0
    assert tz_hours_for("America/Los_Angeles", -4, jul) == -4.0
    assert tz_hours_for("America/New_York", None, jul) == -4.0
    assert tz_hours_for("America/New_York", None, jan) == -5.0
    assert tz_hours_for("America/New_York", 0, jul) == -4.0
    assert tz_hours_for("Asia/Kolkata", None, jul) == 5.5
    assert tz_hours_for(None, None) == 0.0
    assert tz_hours_for(None, 0) == 0.0
    assert tz_offset_for(None, 0) is None


def case_house_night_is_four_hours_on_her_own_clock():
    assert DEFAULT_SLEEP == ("02:00", "06:00"), DEFAULT_SLEEP
    start_h, end_h = _SLEEP_FROM_H, _WAKE_H
    assert (end_h - start_h) % 24 == 4, DEFAULT_SLEEP
    loc = lambda h: datetime(2026, 7, 13, h, 0)
    assert in_sleep_window(loc(3), DEFAULT_SLEEP) is True
    assert in_sleep_window(loc(12), DEFAULT_SLEEP) is False
    assert in_sleep_window(loc(22), DEFAULT_SLEEP) is False
    assert in_sleep_window(loc(8), DEFAULT_SLEEP) is False
    assert in_sleep_window(loc(23), ("22:00", "06:00")) is True
    assert in_sleep_window(loc(7), ("22:00", "06:00")) is False


_harness.run(
    case_timezone_resolver_is_dst_correct,
    case_no_timezone_falls_back_to_utc_offset,
    case_tz_hours_for_is_the_one_hours_accessor,
    case_house_night_is_four_hours_on_her_own_clock,
)
