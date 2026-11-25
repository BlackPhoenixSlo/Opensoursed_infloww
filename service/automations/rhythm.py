from __future__ import annotations

import logging
from datetime import datetime, time

log = logging.getLogger("of-relay.automation.rhythm")

# Longer inline holds would outlive the 900s fan lease.
INLINE_MAX_S = 120

# Measured prod model calls 1.5-2.8 s (max 10.6 s); a miss is that fan's provider error, retried next run.
MODEL_WAIT_S = 30
MODEL_TRIES = 2

# Owner ruling: 4 h night; "always awake" reads as a bot, and a shorter night fails cheaply.
DEFAULT_SLEEP = ("02:00", "06:00")


def tz_offset_for(timezone: str | None, utc_offset: int | None,
                  utc_now: datetime | None = None) -> int | None:
    # utc_offset (the dropdown the operator sees) wins over the IANA zone; None keeps the clock off, never defaulted to UTC.
    if utc_offset:
        return int(utc_offset) * 60
    if timezone:
        try:
            from datetime import timezone as _tz
            from zoneinfo import ZoneInfo
            # Stored datetimes are naive UTC; without stamping UTC, astimezone() reads them as server-local time.
            ref = (utc_now or datetime.utcnow()).replace(tzinfo=_tz.utc)
            off = ref.astimezone(ZoneInfo(timezone)).utcoffset()
            if off is not None:
                return int(off.total_seconds() // 60)
        except Exception:
            log.warning("bad timezone %r — and no utc_offset to fall back to", timezone)
    return None


def tz_hours_for(timezone: str | None, utc_offset: int | None,
                 utc_now: datetime | None = None) -> float:
    off_min = tz_offset_for(timezone, utc_offset, utc_now)
    return off_min / 60.0 if off_min is not None else 0.0


def _parse_hhmm(s: str) -> time:
    h, _, m = str(s).partition(":")
    return time(int(h) % 24, int(m or 0) % 60)


def in_sleep_window(local_dt: datetime, window: tuple[str, str]) -> bool:
    start, end = _parse_hhmm(window[0]), _parse_hhmm(window[1])
    t = local_dt.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end
