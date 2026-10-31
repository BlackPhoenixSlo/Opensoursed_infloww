#!/usr/bin/env python3
"""
isotime — table tests over the shared ISO parser and writers:

  case_parse_iso_table:  Z / +00:00 / any offset → naive UTC (converted, not dropped);
                         naive taken as UTC; outer spaces ignored; "", None, non-str and
                         garbage → None. BEHAVIOUR CHANGE (W15): vault_mirror.parse_iso
                         used to drop an offset, so `+02:00` landed 2h late there.
  case_iso_z_table:      naive UTC → "...Z"; None passes through.
  case_iso_plain_table:  naive → bare isoformat (no zone); None passes through.

Run: ./venv/bin/python service/tests/test_isotime.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from datetime import datetime  # noqa: E402

from isotime import iso_plain, iso_z, parse_iso  # noqa: E402

T = datetime(2026, 10, 31, 9, 5, 7)
TU = datetime(2026, 10, 31, 9, 5, 7, 120000)


def case_parse_iso_table():
    bad = []
    for raw, want in [
        ("2026-10-31T09:05:07Z", T),
        ("2026-10-31T09:05:07+00:00", T),
        # CHANGED row: 11:05 at +02:00 is 09:05 UTC — 2h earlier than vault_mirror's old
        # offset-dropping copy gave (11:05).
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
    assert not bad, bad  # every wrong row, not just the first


def case_iso_z_table():
    for dt, want in [(T, "2026-10-31T09:05:07Z"), (TU, "2026-10-31T09:05:07.120000Z"), (None, None)]:
        assert iso_z(dt) == want, (dt, iso_z(dt))


def case_iso_plain_table():
    for dt, want in [(T, "2026-10-31T09:05:07"), (TU, "2026-10-31T09:05:07.120000"), (None, None)]:
        assert iso_plain(dt) == want, (dt, iso_plain(dt))


_harness.run()
