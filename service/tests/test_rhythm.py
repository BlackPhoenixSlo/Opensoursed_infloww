#!/usr/bin/env python3
"""
`automations/rhythm.py` — the creator's clock (`tz_offset_for` / `tz_hours_for`)
and the house sleep window. Pure: no DB read, no OF call. (`_harness` is still
imported FIRST: `automations` pulls in `_common` → `db.engine`, and an unbound
CHATTERLY_DB_URL falls back to the PROD sqlite file.)

Cases:
  case_timezone_resolver_is_dst_correct:
      tz_offset_for("America/New_York") is DST-correct; a garbage zone falls back
      to the legacy hours column and never raises.
  case_no_timezone_falls_back_to_utc_offset:
      tz_offset_for(None, -5) == -300; tz_offset_for(None, 0) is None — no
      timezone ⇒ no clock rather than a UTC default.
  case_tz_hours_for_is_the_one_hours_accessor:
      the hours accessor, with no-clock collapsing to 0.0.
  case_house_night_is_four_hours_on_her_own_clock:
      DEFAULT_SLEEP is 02:00-06:00, and in_sleep_window handles the midnight wrap.

Run: ./venv/bin/python service/tests/test_rhythm.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime  # noqa: E402

from automations.rhythm import (  # noqa: E402
    DEFAULT_SLEEP, in_sleep_window, tz_hours_for, tz_offset_for,
)

_SLEEP_FROM_H = int(DEFAULT_SLEEP[0].split(":")[0])
_WAKE_H = int(DEFAULT_SLEEP[1].split(":")[0])


def case_timezone_resolver_is_dst_correct():
    # The IANA resolver is DST-correct (EDT in July, EST in January).
    assert tz_offset_for("America/New_York", None, datetime(2026, 7, 13, 12)) == -240
    assert tz_offset_for("America/New_York", None, datetime(2026, 1, 13, 12)) == -300
    # A garbage timezone falls back to the legacy hours column, never raises.
    assert tz_offset_for("Not/AZone", -5, datetime(2026, 7, 13, 12)) == -300
    assert tz_offset_for("Not/AZone", None, datetime(2026, 7, 13, 12)) is None


def case_no_timezone_falls_back_to_utc_offset():
    assert tz_offset_for(None, -5) == -300           # legacy HOURS column → minutes
    assert tz_offset_for(None, 8) == 480
    # 0 is not "UTC", it is "unanswered" — the clock stays OFF rather than
    # defaulting to UTC and silently putting a US creator to sleep at her peak.
    assert tz_offset_for(None, 0) is None
    assert tz_offset_for(None, None) is None
    assert tz_offset_for("", 0) is None


def case_tz_hours_for_is_the_one_hours_accessor():
    """`tz_hours_for` exists so the minutes→hours conversion AND the no-clock
    default are decided ONCE. Four senders used to spell out
    `off_min / 60.0 if off_min is not None else (cfg.utc_offset or 0)` themselves,
    which is four independent chances to weigh the two clock columns differently —
    and one of them did, which is how a preview and a real send disagreed by 3h.

    Note the deliberate split from `tz_offset_for`: this collapses "no clock" to
    0.0 (UTC), which is what a welcome line has always done. Engines that must be
    able to say NOTHING about the time — the chat prompt clock, the sleep window —
    keep using `tz_offset_for` and its None."""
    jan = datetime(2026, 1, 13, 12)
    jul = datetime(2026, 7, 13, 12)
    # The fixed offset is the clock, zone or no zone beside it.
    assert tz_hours_for(None, -4) == -4.0
    assert tz_hours_for("America/Los_Angeles", -4, jul) == -4.0
    # Offset-less accounts fall back to the zone, still DST-correct.
    assert tz_hours_for("America/New_York", None, jul) == -4.0
    assert tz_hours_for("America/New_York", None, jan) == -5.0
    assert tz_hours_for("America/New_York", 0, jul) == -4.0     # 0 == unanswered
    # Half-hour zones survive as fractions — _model_hour takes floats.
    assert tz_hours_for("Asia/Kolkata", None, jul) == 5.5
    # No clock at all → UTC, NOT None. That is the whole difference from
    # tz_offset_for, and it is why this is a separate function and not a wrapper.
    assert tz_hours_for(None, None) == 0.0
    assert tz_hours_for(None, 0) == 0.0
    assert tz_offset_for(None, 0) is None


def case_house_night_is_four_hours_on_her_own_clock():
    """Operator ruling 2026-08-04: 02:00-06:00. Asserted as a WINDOW (start, end and
    length), because the constant moving is exactly the change that quietly puts a
    creator to sleep through hours she used to earn in."""
    assert DEFAULT_SLEEP == ("02:00", "06:00"), DEFAULT_SLEEP
    start_h, end_h = _SLEEP_FROM_H, _WAKE_H
    assert (end_h - start_h) % 24 == 4, DEFAULT_SLEEP
    # It IS a night, on the creator's clock — asleep at 03:00 local, awake at noon
    # and at 22:00.
    loc = lambda h: datetime(2026, 7, 13, h, 0)
    assert in_sleep_window(loc(3), DEFAULT_SLEEP) is True
    assert in_sleep_window(loc(12), DEFAULT_SLEEP) is False
    assert in_sleep_window(loc(22), DEFAULT_SLEEP) is False
    # …and the hours the old 03:00-10:00 window swallowed are now working hours.
    assert in_sleep_window(loc(8), DEFAULT_SLEEP) is False
    # A window that wraps midnight is handled too.
    assert in_sleep_window(loc(23), ("22:00", "06:00")) is True
    assert in_sleep_window(loc(7), ("22:00", "06:00")) is False


_harness.run(
    case_timezone_resolver_is_dst_correct,
    case_no_timezone_falls_back_to_utc_offset,
    case_tz_hours_for_is_the_one_hours_accessor,
    case_house_night_is_four_hours_on_her_own_clock,
)
