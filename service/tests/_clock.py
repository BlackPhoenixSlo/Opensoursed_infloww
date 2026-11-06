"""tests/_clock.py — pins the wall clock for a test file.

Imported before everything else (even `_harness`: it touches no service
module), it makes `datetime.datetime` a subclass whose `utcnow()`, `now()` and
`today()` start at a fixed UTC instant and tick with the real monotonic clock,
so every `from datetime import datetime` after it (the test, the service, the
ORM's defaults) reads the same clock and no case depends on the real time of
day. The instant is `TEST_CLOCK_UTC` (ISO, naive UTC), default
2026-11-05T14:00:00; the paid stream's window edges are proven by running the
files at e.g. `TEST_CLOCK_UTC=2026-11-05T00:55:00`.
"""
from __future__ import annotations

import datetime as _dt
import os
import time

_Real = _dt.datetime
START = _Real.fromisoformat(os.environ.get("TEST_CLOCK_UTC", "2026-11-05T14:00:00"))
_T0 = time.monotonic()


class _Clock(_Real):
    @classmethod
    def utcnow(cls):
        t = START + _dt.timedelta(seconds=time.monotonic() - _T0)
        return cls(t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond)

    @classmethod
    def now(cls, tz=None):
        aware = cls.utcnow().replace(tzinfo=_dt.timezone.utc)
        if tz is not None:
            return aware.astimezone(tz)
        local = aware.astimezone()
        return cls(local.year, local.month, local.day, local.hour, local.minute,
                   local.second, local.microsecond)

    @classmethod
    def today(cls):
        return cls.now()


_dt.datetime = _Clock
