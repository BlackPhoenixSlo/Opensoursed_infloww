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
