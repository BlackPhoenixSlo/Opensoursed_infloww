#!/usr/bin/env python3
from __future__ import annotations

import _harness

from datetime import datetime  # noqa: E402

from isotime import iso_plain, iso_z, parse_iso  # noqa: E402

T = datetime(2026, 10, 31, 9, 5, 7)
TU = datetime(2026, 10, 31, 9, 5, 7, 120000)


def case_parse_iso_table():
    bad = []
    for raw, want in [
        ("2026-10-31T09:05:07Z", T),
        ("2026-10-31T09:05:07+00:00", T),
        ("2026-10-31T11:05:07+02:00", T),
        ("2026-10-31T03:35:07-05:30", T),
        ("2026-10-31T09:05:07", T),
        ("  2026-10-31T09:05:07Z \n", T),
        ("2026-10-31T09:05:07.120Z", TU),
        ("", None),
        ("   ", None),
        (None, None),
        (123, None),
        ("garbage", None),
    ]:
        got = parse_iso(raw)
        if got != want or (got is not None and got.tzinfo is not None):
            bad.append((raw, got))
    assert not bad, bad


def case_iso_z_table():
    for dt, want in [(T, "2026-10-31T09:05:07Z"), (TU, "2026-10-31T09:05:07.120000Z"), (None, None)]:
        assert iso_z(dt) == want, (dt, iso_z(dt))


def case_iso_plain_table():
    for dt, want in [(T, "2026-10-31T09:05:07"), (TU, "2026-10-31T09:05:07.120000"), (None, None)]:
        assert iso_plain(dt) == want, (dt, iso_plain(dt))


_harness.run()
