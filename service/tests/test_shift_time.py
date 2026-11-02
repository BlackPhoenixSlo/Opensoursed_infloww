#!/usr/bin/env python3
"""shift_time: the Shift schedule's pure time rules (service/shift_time.py) as tables. No DB, no
relay, no clock (live_shifts / creator_spans build or run queries: covered via test_shifts_api.py,
test_timesheet_api.py).

Pins: repeat_days is a bare json.loads of a truthy column (None / "" -> None; no shape check, junk
JSON raises, "{}" / "5" come back as-is; shifts_api validates on write). cancelled_dates parses and
sorts ISO dates, None / "" -> []; a bad date or junk JSON raises (nothing is dropped).
shift_occurrences takes naive-UTC lo/hi and keeps an occurrence iff start < hi and end > lo
(starting at lo in, ending at lo out, starting at hi out); a one-off is just its stored span and
ignores cancelled_dates; a series repeats the start's local wall time in `tz` on every ticked ISO
weekday plus the start's own weekday, so its UTC length shrinks / grows by the DST hour it spans
(Europe/Berlin 2026-03-29, 2026-10-25); a spring-gap wall start lands after the gap, so UTC length
= wall length - 1 h and a shift of <= 1 h collapses or inverts (BUG pinned as-is); a fall-back
one lands on its first instant; overnight shifts cross midnight; repeat_until is inclusive; a
cancelled local date (the first one too) has none; a non-empty "[]" column still repeats weekly;
aware lo/hi raise TypeError. _merged joins overlapping or touching spans in start order.
minutes_up rounds up whole minutes after dropping sub-ms noise.

Runs under pytest (parametrized tables) or as a script (the repo's convention, no pytest needed):
    ./venv/bin/python service/tests/test_shift_time.py
"""
from __future__ import annotations

import _harness  # noqa: F401 -- MUST be first: shift_time imports db.models (temp DB bound; never used)

from datetime import date, datetime  # noqa: E402
from json import JSONDecodeError  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from shift_time import _merged, cancelled_dates, minutes_up, repeat_days, shift_occurrences  # noqa: E402

try:
    import pytest
    table = pytest.mark.parametrize
except ImportError:  # script mode: the runner below calls each row
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark

BER = "Europe/Berlin"   # CET +1 / CEST +2; 2026 DST starts 03-29 02:00, ends 10-25 03:00


def _call(fn, *a):
    """fn(*a), or the exception class it raised (rows assert raises as a value)."""
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        return type(e)


def u(s: str) -> datetime:
    """Naive UTC, the fn's own convention: "2026-03-28 00:00" (a "+00:00" suffix makes it aware)."""
    return datetime.fromisoformat(s)


def shift(start: str, end: str, days: str | None = None, until: date | None = None,
          cancelled: str | None = None, tz: str = BER) -> SimpleNamespace:
    """Exactly the attrs shift_occurrences reads."""
    return SimpleNamespace(start_utc=u(start), end_utc=u(end), tz=tz, repeat_days=days,
                           repeat_until=until, cancelled_dates=cancelled)


def spans(*pairs: tuple[str, str]) -> list[tuple[datetime, datetime]]:
    return [(u(a), u(b)) for a, b in pairs]


# --- repeat_days ---------------------------------------------------------------------------------

@table("raw, want", [
    (None, None),
    ("", None),
    ("[0,6]", [0, 6]),          # not ISO-checked here
    ("[1,3]", [1, 3]),
    ("[]", []),
    ("{}", {}),                 # no shape check: a dict comes back
    ("5", 5),                   # ... and a bare int
    ("abc", JSONDecodeError),   # junk raises
    ("[1,", JSONDecodeError),
])
def test_repeat_days(raw, want):
    assert _call(repeat_days, raw) == want


# --- cancelled_dates -----------------------------------------------------------------------------

@table("raw, want", [
    (None, []),
    ("", []),
    ("[]", []),
    ('["2026-03-29"]', [date(2026, 3, 29)]),
    ('["2026-10-25", "2026-03-29", "2026-05-01"]',
     [date(2026, 3, 29), date(2026, 5, 1), date(2026, 10, 25)]),     # sorted
    ('["20260329"]', [date(2026, 3, 29)]),                             # py3.11+ basic ISO accepted
    ('["2026-02-30"]', ValueError),         # bad date raises, not dropped
    ('["nope"]', ValueError),
    ('["2026-03-29", "x"]', ValueError),    # one bad date sinks the list
    ("abc", JSONDecodeError),
    ("[5]", TypeError),                     # non-str entry
])
def test_cancelled_dates(raw, want):
    assert _call(cancelled_dates, raw) == want


# --- shift_occurrences ---------------------------------------------------------------------------

# One-off 10:00-12:00Z, no repeat: kept iff start < hi and end > lo.
ONE = ("2026-05-04 10:00", "2026-05-04 12:00")

# Sat 2026-03-28 wall 01:00-05:00 CET, daily: 03-29 spans the spring jump.
SPRING = shift("2026-03-28 00:00", "2026-03-28 04:00", "[1,2,3,4,5,6,7]")
# Sat 2026-10-24 wall 01:00-05:00 CEST, daily: 10-25 spans the fall-back.
FALL = shift("2026-10-23 23:00", "2026-10-24 03:00", "[1,2,3,4,5,6,7]")
# Fri 2026-03-27 wall 09:00-17:00 CET, Mon+Fri: wall start kept across the switch.
DAY = shift("2026-03-27 08:00", "2026-03-27 16:00", "[1]")
# Sat 2026-03-28 wall 02:30-03:30 CET, Sun only: 03-29 02:30 is in the gap.
GAP = shift("2026-03-28 01:30", "2026-03-28 02:30", "[7]")
# Sat 2026-03-28 wall 02:30-03:00 CET, Sun only: a 30 min shift starting in the gap.
GAP_SHORT = shift("2026-03-28 01:30", "2026-03-28 02:00", "[7]")
# Sat 2026-10-24 wall 02:30-03:00 CEST, Sun only: 10-25 02:30 happens twice.
DUP = shift("2026-10-24 00:30", "2026-10-24 01:00", "[7]")
# Mon 2026-05-04 wall 22:00-06:00 CEST (20:00Z-04:00Z), Mon+Tue: crosses midnight.
NIGHT = shift("2026-05-04 20:00", "2026-05-05 04:00", "[1,2]")
# Wed 2026-05-06 09:00-10:00 CEST, ticked Mon only: Wednesdays still repeat.
WED = shift("2026-05-06 07:00", "2026-05-06 08:00", "[1]")


@table("sh, lo, hi, want", [
    # one-off: window edges
    (shift(*ONE), "2026-05-04 00:00", "2026-05-05 00:00", spans(ONE)),          # inside
    (shift(*ONE), "2026-05-05 00:00", "2026-05-06 00:00", []),                  # outside
    (shift(*ONE), "2026-05-04 10:00", "2026-05-04 11:00", spans(ONE)),          # starts at lo: in
    (shift(*ONE), "2026-05-04 12:00", "2026-05-04 13:00", []),                  # ends at lo: out
    (shift(*ONE), "2026-05-04 09:00", "2026-05-04 10:00", []),                  # starts at hi: out
    (shift(*ONE), "2026-05-04 11:59", "2026-05-04 12:01", spans(ONE)),          # partial overlap
    (shift(*ONE, cancelled='["2026-05-04"]'), "2026-05-04 00:00", "2026-05-05 00:00", spans(ONE)),  # one-off ignores cancelled
    # DST start: 03-29 is 1 h shorter in UTC, wall 01:00 kept on both sides
    (SPRING, "2026-03-28 00:00", "2026-03-30 23:00", spans(
        ("2026-03-28 00:00", "2026-03-28 04:00"),       # 4 h, the stored first
        ("2026-03-29 00:00", "2026-03-29 03:00"),       # 01:00 CET -> 05:00 CEST: 3 h
        ("2026-03-29 23:00", "2026-03-30 03:00"))),     # 4 h, both CEST; 03-31's starts at hi: out
    # DST end: 10-25 is 1 h longer in UTC
    (FALL, "2026-10-23 00:00", "2026-10-26 12:00", spans(
        ("2026-10-23 23:00", "2026-10-24 03:00"),       # 4 h
        ("2026-10-24 23:00", "2026-10-25 04:00"),       # 01:00 CEST -> 05:00 CET: 5 h
        ("2026-10-26 00:00", "2026-10-26 04:00"))),     # 4 h, both CET
    # wall 09:00 kept: 08:00Z in CET, 07:00Z in CEST
    (DAY, "2026-03-27 00:00", "2026-04-04 00:00", spans(
        ("2026-03-27 08:00", "2026-03-27 16:00"),       # Fri, CET
        ("2026-03-30 07:00", "2026-03-30 15:00"),       # Mon, CEST
        ("2026-04-03 07:00", "2026-04-03 15:00"))),     # Fri, CEST
    # spring gap: wall 02:30 on 03-29 lands after the gap (fold=0 -> CET offset -> 03:30 CEST), but
    # its end wall 03:30 is that same instant, so the 1 h shift collapses to 0 min (still returned).
    # BUG: see PR -- wall-clock length lost; intent reads 01:30Z-02:30Z (03:30-04:30 CEST).
    (GAP, "2026-03-29 00:00", "2026-03-30 00:00", spans(("2026-03-29 01:30", "2026-03-29 01:30"))),
    # spring gap, < 1 h: wall 02:30-03:00 -> start 01:30Z (03:30 CEST), end 01:00Z (03:00 CEST).
    # BUG: see PR -- end before start (inverted pair, still returned); intent 01:30Z-02:00Z.
    (GAP_SHORT, "2026-03-29 00:00", "2026-03-30 00:00", spans(("2026-03-29 01:30", "2026-03-29 01:00"))),
    # fall-back repeat: wall 02:30 on 10-25 takes its first instant (CEST)
    (DUP, "2026-10-25 00:00", "2026-10-26 00:00", spans(("2026-10-25 00:30", "2026-10-25 02:00"))),
    # overnight across midnight; Tue 05-05 repeats, Wed 05-06 not ticked
    (NIGHT, "2026-05-04 00:00", "2026-05-08 00:00", spans(
        ("2026-05-04 20:00", "2026-05-05 04:00"),
        ("2026-05-05 20:00", "2026-05-06 04:00"))),
    # a window opening mid-occurrence still sees the one that started the day before
    (NIGHT, "2026-05-12 02:00", "2026-05-12 03:00", spans(("2026-05-11 20:00", "2026-05-12 04:00"))),
    # window ends exactly at the next occurrence's start: excluded
    (NIGHT, "2026-05-05 04:00", "2026-05-05 20:00", []),
    # window begins exactly at an occurrence's end: excluded; at its start: included
    (NIGHT, "2026-05-06 04:00", "2026-05-06 05:00", []),
    (NIGHT, "2026-05-05 20:00", "2026-05-05 20:01", spans(("2026-05-05 20:00", "2026-05-06 04:00"))),
    # repeat_until inclusive: ends Tue 05-12, so Mon 05-11 + Tue 05-12 in, Mon 05-18 out
    (shift("2026-05-04 20:00", "2026-05-05 04:00", "[1,2]", until=date(2026, 5, 12)),
     "2026-05-10 00:00", "2026-05-20 00:00", spans(
        ("2026-05-11 20:00", "2026-05-12 04:00"),
        ("2026-05-12 20:00", "2026-05-13 04:00"))),
    # repeat_until before the window: nothing
    (shift("2026-05-04 20:00", "2026-05-05 04:00", "[1,2]", until=date(2026, 5, 5)),
     "2026-05-10 00:00", "2026-05-20 00:00", []),
    # cancelled local date skipped (Tue 05-05 is a 22:00 local start, 20:00Z)
    (shift("2026-05-04 20:00", "2026-05-05 04:00", "[1,2]", cancelled='["2026-05-05"]'),
     "2026-05-04 00:00", "2026-05-08 00:00", spans(("2026-05-04 20:00", "2026-05-05 04:00"))),
    # cancelled first date: the stored span itself is gone
    (shift("2026-05-04 20:00", "2026-05-05 04:00", "[1,2]", cancelled='["2026-05-04"]'),
     "2026-05-04 00:00", "2026-05-08 00:00", spans(("2026-05-05 20:00", "2026-05-06 04:00"))),
    # start's own weekday repeats though only Mon is ticked
    (WED, "2026-05-06 00:00", "2026-05-14 00:00", spans(
        ("2026-05-06 07:00", "2026-05-06 08:00"),
        ("2026-05-11 07:00", "2026-05-11 08:00"),
        ("2026-05-13 07:00", "2026-05-13 08:00"))),
    # "[]" is truthy: weekly on the start's weekday
    (shift("2026-05-06 07:00", "2026-05-06 08:00", "[]"), "2026-05-06 00:00", "2026-05-21 00:00", spans(
        ("2026-05-06 07:00", "2026-05-06 08:00"),
        ("2026-05-13 07:00", "2026-05-13 08:00"),
        ("2026-05-20 07:00", "2026-05-20 08:00"))),
    # window before the series' first date: nothing
    (WED, "2026-05-01 00:00", "2026-05-06 00:00", []),
    # UTC tz: local date == UTC date
    (shift("2026-05-04 10:00", "2026-05-04 12:00", "[3]", tz="UTC"), "2026-05-05 00:00", "2026-05-12 00:00",
     spans(("2026-05-06 10:00", "2026-05-06 12:00"), ("2026-05-11 10:00", "2026-05-11 12:00"))),
    # naive UTC in: an aware lo/hi can't be compared to the naive stored spans
    (shift(*ONE), "2026-05-04 00:00+00:00", "2026-05-06 00:00+00:00", TypeError),
    (NIGHT, "2026-05-04 00:00+00:00", "2026-05-06 00:00+00:00", TypeError),
])
def test_shift_occurrences(sh, lo, hi, want):
    assert _call(shift_occurrences, sh, u(lo), u(hi)) == want


# --- _merged -------------------------------------------------------------------------------------

@table("given, want", [
    ([], []),
    ([("2026-05-04 10:00", "2026-05-04 12:00")], [("2026-05-04 10:00", "2026-05-04 12:00")]),
    ([("2026-05-04 10:00", "2026-05-04 12:00"), ("2026-05-04 11:00", "2026-05-04 13:00")],   # overlapping
     [("2026-05-04 10:00", "2026-05-04 13:00")]),
    ([("2026-05-04 10:00", "2026-05-04 12:00"), ("2026-05-04 12:00", "2026-05-04 13:00")],   # touching
     [("2026-05-04 10:00", "2026-05-04 13:00")]),
    ([("2026-05-04 10:00", "2026-05-04 11:00"), ("2026-05-04 12:00", "2026-05-04 13:00")],   # disjoint
     [("2026-05-04 10:00", "2026-05-04 11:00"), ("2026-05-04 12:00", "2026-05-04 13:00")]),
    ([("2026-05-04 12:00", "2026-05-04 13:00"), ("2026-05-04 10:00", "2026-05-04 11:00"),    # unsorted
      ("2026-05-04 10:30", "2026-05-04 12:00")],
     [("2026-05-04 10:00", "2026-05-04 13:00")]),
    ([("2026-05-04 10:00", "2026-05-04 14:00"), ("2026-05-04 11:00", "2026-05-04 12:00")],   # nested
     [("2026-05-04 10:00", "2026-05-04 14:00")]),
    ([("2026-05-04 10:00", "2026-05-04 12:00"), ("2026-05-04 10:00", "2026-05-04 12:00")],   # duplicate
     [("2026-05-04 10:00", "2026-05-04 12:00")]),
])
def test_merged(given, want):
    src = spans(*given)
    before = list(src)
    assert _merged(src) == spans(*want)
    assert src == before        # input untouched


# --- minutes_up ----------------------------------------------------------------------------------

@table("seconds, want", [
    (0, 0),
    (0.1, 1),
    (59.9, 1),
    (60, 1),
    (60.0004, 1),       # sub-ms float noise dropped
    (60.001, 2),
    (61, 2),
    (3600, 60),
    (-30, 0),           # ceil(-0.5)
    (-61, -1),          # negative rounds toward zero
])
def test_minutes_up(seconds, want):
    assert minutes_up(seconds) == want


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
