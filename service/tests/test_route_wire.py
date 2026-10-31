#!/usr/bin/env python3
"""
route_wire — table tests over the shared wire-time and path-id helpers:

  case_parse_utc_table:     Z and +02:00 → naive UTC; naive, garbage, empty, None,
                            non-str → 422 with the field-named detail texts.
  case_parse_utc_status:    status=400 refuses with 400, same texts.
  case_wire_table:          naive UTC → "...Z"; None passes through.
  case_own_row_or_404:      a Shift in the temp DB: own id (str) found; non-int,
                            missing and another owner's → 404 "<what> not found".

Run: ./venv/bin/python service/tests/test_route_wire.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB)

_harness.bootstrap()

from datetime import datetime  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Shift  # noqa: E402
from route_wire import own_row_or_404, parse_utc, wire  # noqa: E402

IDS = fx.seed_two_agencies()


def _refusal(fn, *args, **kw) -> tuple[int, object]:
    try:
        fn(*args, **kw)
    except HTTPException as exc:
        return exc.status_code, exc.detail
    raise AssertionError(f"no refusal for {args}")


def case_parse_utc_table():
    ok = [
        ("2026-10-31T12:00:00Z", datetime(2026, 10, 31, 12)),
        ("2026-10-31T12:00:00+02:00", datetime(2026, 10, 31, 10)),
        ("2026-10-31T01:30:00-05:00", datetime(2026, 10, 31, 6, 30)),
        ("2026-10-31T12:00:00.250000+00:00", datetime(2026, 10, 31, 12, 0, 0, 250000)),
    ]
    for raw, want in ok:
        got = parse_utc(raw, "start_utc")
        assert got == want and got.tzinfo is None, (raw, got)
    bad = [
        ("2026-10-31T12:00:00", "start_utc: the time needs a zone (end it with Z)"),
        ("not a time", "start_utc: not an ISO-8601 time"),
        ("", "start_utc: an ISO-8601 UTC time is required"),
        (None, "start_utc: an ISO-8601 UTC time is required"),
        (1730376000, "start_utc: an ISO-8601 UTC time is required"),
    ]
    for raw, detail in bad:
        assert _refusal(parse_utc, raw, "start_utc") == (422, detail), raw


def case_parse_utc_status():
    assert _refusal(parse_utc, "2026-10-31T12:00:00", "from", status=400) == (
        400, "from: the time needs a zone (end it with Z)")
    assert _refusal(parse_utc, "garbage", "to", 400) == (400, "to: not an ISO-8601 time")
    assert parse_utc("2026-10-31T12:00:00Z", "from", status=400) == datetime(2026, 10, 31, 12)


def case_wire_table():
    assert wire(datetime(2026, 10, 31, 12)) == "2026-10-31T12:00:00Z"
    assert wire(datetime(2026, 10, 31, 12, 0, 0, 5)) == "2026-10-31T12:00:00.000005Z"
    assert wire(None) is None
    assert parse_utc(wire(datetime(2026, 1, 2, 3, 4, 5)), "x") == datetime(2026, 1, 2, 3, 4, 5)


async def case_own_row_or_404():
    owner = IDS["agency_a_owner"]
    async with get_session() as s:
        sh = Shift(agency_user_id=owner, start_utc=datetime(2026, 11, 2, 9), end_utc=datetime(2026, 11, 2, 17),
                   tz="UTC", status="scheduled", created_by=f"owner:{owner}",
                   created_at=datetime(2026, 10, 31), updated_at=datetime(2026, 10, 31))
        s.add(sh)
        await s.flush()
        sid = sh.id
    async with get_session() as s:
        got = await own_row_or_404(s, Shift, str(sid), "shift", "agency_user_id", owner)
        assert got.id == sid
        cases = [
            ("abc", owner),                            # not an id
            (str(sid + 1000), owner),                  # missing
            (str(sid), IDS["agency_b_owner"]),         # another owner's
        ]
        for raw, who in cases:
            try:
                await own_row_or_404(s, Shift, raw, "shift", "agency_user_id", who)
            except HTTPException as exc:
                assert (exc.status_code, exc.detail) == (404, "shift not found"), (raw, exc.detail)
            else:
                raise AssertionError(f"no 404 for {raw} as {who}")


_harness.run()
