#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import stats_window as sw  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
EOD = dict(hour=23, minute=59, second=59, microsecond=999_999)


def case_parse_bound_table():
    rows = [
        (None, "from", None, None, None),
        ("", "to", None, None, None),
        ("2026-05-22", "from", None, None, datetime(2026, 5, 22)),
        ("2026-05-22", "to", None, None, datetime(2026, 5, 22, **EOD)),
        ("2026-05-22T12:00:00Z", "from", None, None, datetime(2026, 5, 22, 12)),
        ("2026-05-22T12:00:00Z", "to", None, None, datetime(2026, 5, 22, 12)),
        ("2026-05-22T23:59:59.999-07:00", "to", None, None, datetime(2026, 5, 23, 6, 59, 59, 999_000)),
        ("2026-05-22T12:00:00+05:30", "from", None, None, datetime(2026, 5, 22, 6, 30)),
        ("2026-05-22", "to", None, 420, datetime(2026, 5, 23, 6, 59, 59, 999_999)),
        ("2026-05-22", "from", None, -120, datetime(2026, 5, 21, 22)),
        ("2026-05-22T12:00:00", "from", None, 60, datetime(2026, 5, 22, 12)),
        ("2026-05-22", "from", None, 840, datetime(2026, 5, 22, 14)),
        ("2026-05-22", "from", None, -840, datetime(2026, 5, 21, 10)),
        ("2026-05-22", "from", None, 841, datetime(2026, 5, 22)),
        ("2026-05-22", "from", None, -841, datetime(2026, 5, 22)),
        ("2026-05-22", "from", NEW_YORK, 420, datetime(2026, 5, 22, 4)),
        ("2026-10-24", "from", BERLIN, None, datetime(2026, 10, 23, 22)),
        ("2026-10-26", "from", BERLIN, None, datetime(2026, 10, 25, 23)),
        ("2026-10-25", "to", BERLIN, None, datetime(2026, 10, 25, 22, 59, 59, 999_999)),
        ("2026-03-07", "from", NEW_YORK, None, datetime(2026, 3, 7, 5)),
        ("2026-03-09", "from", NEW_YORK, None, datetime(2026, 3, 9, 4)),
        ("2026-03-08", "to", NEW_YORK, None, datetime(2026, 3, 9, 3, 59, 59, 999_999)),
        ("2026-10-25T12:00:00Z", "from", BERLIN, None, datetime(2026, 10, 25, 12)),
    ]
    bad = []
    for s, field, zone, off, want in rows:
        got = sw.parse_bound(s, field, zone, off)
        if got != want:
            bad.append((s, field, zone, off, got, want))
    assert not bad, bad
    for s in ("nope", "2026-13-01", "2026-05-22T25:00"):
        try:
            sw.parse_bound(s, "from")
        except HTTPException as e:
            assert e.status_code == 400 and e.detail.startswith("invalid from:"), (s, e.detail)
        else:
            raise AssertionError(f"{s!r} parsed")


def case_parse_date_reads_the_offset_header():
    def req(raw):
        return SimpleNamespace(headers={} if raw is None else {"x-timezone-offset-minutes": raw})
    assert sw.parse_date("2026-05-22", field="to", request=req("420")) == datetime(2026, 5, 23, 6, 59, 59, 999_999)
    assert sw.parse_date("2026-05-22", field="from", request=req("abc")) == datetime(2026, 5, 22)
    assert sw.parse_date("2026-05-22", field="from", request=req(None)) == datetime(2026, 5, 22)
    assert sw.parse_date("2026-05-22", field="from", request=req("420"), zone=BERLIN) == datetime(2026, 5, 21, 22)
    assert sw.parse_date("2026-05-22", field="from") == datetime(2026, 5, 22)


def case_bucket_allowed_table():
    rules = {
        "hour": {1: True, 2: True, 3: False, 13: False, 400: False},
        "day": {1: True, 2: True, 13: True, 14: True, 31: True, 32: False, 62: False, 366: False},
        "week": {2: False, 13: False, 14: True, 31: True, 32: True, 62: True, 63: True, 365: True, 366: False},
        "month": {2: False, 13: False, 14: False, 31: False, 32: False, 62: False, 63: True, 365: True, 366: True},
    }
    bad = [(b, n, got, want) for b, table in rules.items() for n, want in table.items()
           if (got := sw.bucket_allowed(b, n)) != want]
    assert not bad, bad


def case_range_days_table():
    start = datetime(2026, 1, 1)
    last_ms = timedelta(milliseconds=1)
    bad = [(n, got) for n in (1, 2, 3, 13, 14, 31, 32, 62, 63, 365, 366)
           if (got := sw.range_days(start, start + timedelta(days=n) - last_ms)) != n]
    assert not bad, bad
    assert sw.range_days(datetime(2026, 10, 24, 22), datetime(2026, 10, 25, 23) - last_ms) == 1
    assert sw.range_days(datetime(2026, 3, 8, 5), datetime(2026, 3, 9, 4) - last_ms) == 1
    assert sw.range_days(datetime(2026, 9, 30, 22), datetime(2026, 10, 31, 23) - last_ms) == 31


def case_bucket_edges_across_dst():
    d = datetime
    rows = [
        (("day", d(2026, 10, 23, 22), d(2026, 10, 26, 22), BERLIN),
         [d(2026, 10, 23, 22), d(2026, 10, 24, 22), d(2026, 10, 25, 23)]),
        (("week", d(2026, 10, 23, 22), d(2026, 10, 27), BERLIN),
         [d(2026, 10, 18, 22), d(2026, 10, 25, 23)]),
        (("hour", d(2026, 10, 24, 23, 30), d(2026, 10, 25, 2), BERLIN),
         [d(2026, 10, 24, 23), d(2026, 10, 25, 0), d(2026, 10, 25, 1), d(2026, 10, 25, 2)]),
        (("day", d(2026, 3, 7, 5), d(2026, 3, 9, 4, 30), NEW_YORK),
         [d(2026, 3, 7, 5), d(2026, 3, 8, 5), d(2026, 3, 9, 4)]),
        (("week", d(2026, 3, 9, 4), d(2026, 3, 16), NEW_YORK, "sunday"),
         [d(2026, 3, 8, 5), d(2026, 3, 15, 4)]),
        (("hour", d(2026, 3, 8, 6, 30), d(2026, 3, 8, 8), NEW_YORK),
         [d(2026, 3, 8, 6), d(2026, 3, 8, 7), d(2026, 3, 8, 8)]),
        (("month", d(2026, 2, 15), d(2026, 4, 1, 4), NEW_YORK),
         [d(2026, 2, 1, 5), d(2026, 3, 1, 5), d(2026, 4, 1, 4)]),
    ]
    bad = [(args, got, want) for args, want in rows if (got := sw.bucket_edges(*args)) != want]
    assert not bad, bad


_harness.run()
