#!/usr/bin/env python3
"""OnlyFans' Statistics replies read per UTC day (service/of_stats_parse.py): pure tables, no DB, no client.

  points     Reach / Subscriptions charts as {day: count}: one point per consecutive day with a whole count, the
             days in [first, last] kept (so today, after `last`, is never stored)
  earnings   /earnings/chart as {day: {category: (net, gross, sales)}} in cents, plus OF's total: every category
             under OF's reply key, gross from the period's gross/net, the days adding up to OF's total

Rows start from the recorded replies (service/tests/fixtures/of_statistics_reads.json); None = not stored.

Run: ./venv/bin/python service/tests/test_of_stats_parse.py   (exit 0 = green)
"""
import _harness  # noqa: F401 — first, as in every service test (paths)

import copy  # noqa: E402
import json  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import of_stats_parse as p  # noqa: E402

FIX = json.loads((Path(__file__).parent / "fixtures" / "of_statistics_reads.json").read_text())
D1, D2, D3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)
Z = "T00:00:00+00:00"


def pts(days: dict[str, object]) -> list[dict]:
    """A chart series, one point per day in day order (dict order ignored)."""
    return [{"date": f"{d}{Z}", "count": n} for d, n in sorted(days.items())]


def chart(cats: dict[str, dict[str, float]], counts: dict | None = None, gross: dict | None = None,
           total: bool = True) -> dict:
    """An /earnings/chart reply as OF answers Statements' filters: per category (under OF's reply key) its daily net
    amounts (dollars), counts, net total and gross, and OF's `total` of them."""
    out = {}
    for c, days in cats.items():
        tot = sum(days.values())
        out[p.REPLY_KEY.get(c, c)] = {
            "chartAmount": pts(days),
            "chartCount": pts({d: (counts or {}).get(c, {}).get(d, 0) for d in sorted(days)}),
            "total": tot, "gross": (gross or {}).get(c, round(tot / 0.8, 2)), "delta": 0}
    if total:
        days = sorted({d for v in cats.values() for d in v})
        out[p.TOTAL] = {"chartAmount": pts({d: sum(v.get(d, 0) for v in cats.values()) for d in days}),
                        "total": sum(sum(v.values()) for v in cats.values()), "gross": 0, "delta": 0}
    return out


def _edit(reply: dict, fn) -> dict:
    out = copy.deepcopy(reply)
    fn(out)
    return out


# ── points ──────────────────────────────────────────────────────────────

POINTS = [  # (why, series, first, last, expected)
    ("Reach's recorded visitors", FIX["/users/me/profile/stats"]["chart"]["visitors"], D1, D2,
     {"2026-10-01": 0, "2026-10-02": 3}),
    ("Subscriptions' recorded subscribes", FIX["/subscriptions/subscribers/chart"]["subscribes"], D1, D2,
     {"2026-10-01": 0}),
    ("Z suffix read as UTC", [{"date": "2026-10-01T00:00:00Z", "count": 2}], D1, D1, {"2026-10-01": 2}),
    ("a whole float count", pts({"2026-10-01": 2.0}), D1, D1, {"2026-10-01": 2}),
    ("days outside [first, last] dropped; today (after last) never stored",
     pts({"2026-09-30": 5, "2026-10-01": 1, "2026-10-02": 2, "2026-10-03": 99}), D1, D2,
     {"2026-10-01": 1, "2026-10-02": 2}),
    ("empty series: no days", [], D1, D2, {}),
    ("weekly buckets", pts({"2026-09-21": 4, "2026-09-28": 5}), D1, D2, None),
    ("non-consecutive days", pts({"2026-10-01": 1, "2026-10-03": 1}), D1, D3, None),
    ("fractional count", pts({"2026-10-01": 1.5}), D1, D1, None),
    ("negative count", pts({"2026-10-01": -1}), D1, D1, None),
    ("bool count", pts({"2026-10-01": True}), D1, D1, None),
    ("string count", pts({"2026-10-01": "3"}), D1, D1, None),
    ("no date key", [{"day": "2026-10-01", "count": 1}], D1, D1, None),
    ("no count key", [{"date": f"2026-10-01{Z}"}], D1, D1, None),
    ("unparsable date", [{"date": "yesterday", "count": 1}], D1, D1, None),
    ("not a list", "n/a", D1, D1, None),
    ("None (a reply without the series)", None, D1, D1, None),
]


def case_points_table():
    for why, series, first, last, want in POINTS:
        got = p.points(series, first, last)
        assert got == want, (why, got)


# ── earnings ────────────────────────────────────────────────────────────

REC = FIX["/earnings/chart?filter=statements"]
TWO_DAYS = chart({"tips": {"2026-10-01": 8, "2026-10-02": 12.8}, "messages": {"2026-10-02": 100}},
                  counts={"tips": {"2026-10-01": 2, "2026-10-02": 3}}, gross={"tips": 26.0, "messages": 125})


def _pacific(reply: dict) -> None:
    for b in reply.values():
        for pt in b["chartAmount"]:
            pt["date"] = "2026-10-01T00:00:00-07:00"


def _noon(reply: dict) -> None:
    for b in reply.values():
        for pt in b["chartAmount"]:
            pt["date"] = "2026-10-01T12:00:00+00:00"


def _off_by(cents: int):
    def fn(reply: dict) -> None:
        reply["tips"]["chartAmount"][0]["count"] += cents / 100
    return fn


def _rekey(old: str, new: str):
    def fn(reply: dict) -> None:
        reply[new] = reply.pop(old)
    return fn


def _set_amount(cat: str, value: object):
    def fn(reply: dict) -> None:
        reply[cat]["chartAmount"][0]["count"] = value
    return fn


def _set_gross(cat: str, value: object):
    def fn(reply: dict) -> None:
        reply[cat]["gross"] = value
    return fn


EARNINGS = [  # (why, reply, first, last, {day: {category: (net, gross, sales)}} picked from the result | None)
    ("recorded: a $14 PPV message under chat_messages is $11.20 net, not $0", REC, D1, D2,
     {"2026-10-01": {"messages": (1120, 1400, 1), p.TOTAL: (1120, 1400, 1)},
      "2026-10-02": {"tips": (800, 1000, 2), "subscribes": (400, 500, 1), "messages": (0, 0, 0)}}),
    ("gross per day at the category's gross/net (tips 26.00/20.80 = 1.25x); a day with no point is zero",
     TWO_DAYS, D1, D2,
     {"2026-10-01": {"tips": (800, 1000, 2), "messages": (0, 0, 0)},
      "2026-10-02": {"tips": (1280, 1600, 3), "messages": (10000, 12500, 0), "subscribes": (0, 0, 0),
                     p.TOTAL: (11280, 14100, 0)}}),
    ("gross = net / 0.8 when OF's gross total is 0", chart({"tips": {"2026-10-01": 8}}, gross={"tips": 0}), D1, D1,
     {"2026-10-01": {"tips": (800, 1000, 0)}}),
    ("a chargeback day: negative amount kept, adds up", chart({"tips": {"2026-10-01": -3.5},
                                                                "messages": {"2026-10-01": 2}}), D1, D1,
     {"2026-10-01": {"tips": (-350, -438, 0), "messages": (200, 250, 0), p.TOTAL: (-150, -188, 0)}}),
    ("days outside [first, last] dropped; today (after last) never stored",
     chart({"tips": {"2026-09-30": 1, "2026-10-01": 2, "2026-10-02": 3, "2026-10-03": 4}}), D1, D2,
     {"2026-10-01": {"tips": (200, 250, 0)}, "2026-10-02": {"tips": (300, 375, 0)}}),
    ("off by 1 cent: within the check", _edit(chart({"tips": {"2026-10-01": 8}}), _off_by(1)), D1, D1,
     {"2026-10-01": {"tips": (801, 1001, 0), p.TOTAL: (800, 1001, 0)}}),
    ("off by len(EARNINGS) cents: the check's edge, kept",
     _edit(chart({"tips": {"2026-10-01": 8}}), _off_by(len(p.EARNINGS))), D1, D1,
     {"2026-10-01": {"tips": (805, 1006, 0), p.TOTAL: (800, 1006, 0)}}),
    ("off by more than a cent per category",
     _edit(chart({"tips": {"2026-10-01": 8}}), _off_by(len(p.EARNINGS) + 1)), D1, D1, None),
    ("weekly buckets", chart({"tips": {"2026-09-21": 1, "2026-09-28": 2}}), D1, D2, None),
    ("non-consecutive days", chart({"tips": {"2026-10-01": 1, "2026-10-03": 2}}), D1, D3, None),
    ("a point at UTC-7 midnight", _edit(chart({"tips": {"2026-10-01": 8}}), _pacific), D1, D1, None),
    ("a point at UTC noon", _edit(chart({"tips": {"2026-10-01": 8}}), _noon), D1, D1, None),
    ("no total: nothing to check against", chart({"tips": {"2026-10-01": 8}}, total=False), D1, D1, None),
    ("money under an unknown key (messages as `unread_messages`)",
     _edit(chart({"tips": {"2026-10-01": 8}, "messages": {"2026-10-01": 11.2}}),
           _rekey("chat_messages", "unread_messages")), D1, D1, None),
    ("messages under its filter name, not chat_messages",
     _edit(chart({"tips": {"2026-10-01": 8}, "messages": {"2026-10-01": 11.2}}),
           _rekey("chat_messages", "messages")), D1, D1, None),
    ("a bool amount", _edit(chart({"tips": {"2026-10-01": 8}}),
                            _set_amount("tips", True)), D1, D1, None),
    ("a category not a dict", {"tips": "n/a", p.TOTAL: {"chartAmount": []}}, D1, D1, None),
    ("chartAmount not a list", {"tips": {"chartAmount": "n/a"}, p.TOTAL: {"chartAmount": []}}, D1, D2, None),
    ("a gross not a number", _edit(chart({"tips": {"2026-10-01": 8}}),
                                   _set_gross("tips", "n/a")), D1, D1, None),
    ("OF's [] (no filter) is no chart", [], D1, D2, None),
    ("{}: no total, not a known $0", {}, D1, D2, None),
    ("no Statements category among other keys", {"foo": 1}, D1, D2, None),
]


def case_earnings_table():
    for why, reply, first, last, want in EARNINGS:
        got = p.earnings(reply, first, last)
        if want is None:
            assert got is None, (why, got)
            continue
        assert got is not None, why
        every = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
        assert list(got) == every, (why, list(got))
        for day, cats in want.items():
            assert set(got[day]) == {*p.EARNINGS, p.TOTAL}, (why, day, got[day])
            picked = {c: got[day][c] for c in cats}
            assert picked == cats, (why, day, picked)


def case_earnings_reads_every_category_and_the_total():
    """The filters fetch_earnings_blocking sends name EARNINGS and TOTAL; the recorded reply answers each."""
    for c in (*p.EARNINGS, p.TOTAL):
        assert p.REPLY_KEY.get(c, c) in REC, c
    assert set(p.EARNINGS_KIND) == set(p.EARNINGS)


if __name__ == "__main__":  # test_of_stats_daily imports its reply builders
    _harness.run()
