#!/usr/bin/env python3
"""OnlyFans Statistics figures per Creator per UTC day (roadmap W5 5.5; service/of_stats_daily.py), and the
Creator reports' columns per_model reads off them and off the ledger (spenders).

OF is faked: a real OFClient without a session whose `get_json` records every GET and answers from
service/tests/fixtures/of_statistics_reads.json (the relay's recorded shapes), so the job's reads go through the
client's own methods and params. No network.

  the fetch          three GETs, read only: Reach's profile stats, the Subscriptions chart by=new and by=renew,
                     over the last 7 complete UTC days; each chart's points stored per day
  the shape check    a series not one point per consecutive day (another shape, a weekly bucket) is not stored
  the upsert         a re-fetch overwrites its series and leaves the roster columns alone
  the roster         the latest complete crawl's active and renew-on counts land on its UTC day; an unknown status
                     leaves renew_on NULL
  the loop's pass    only OnlyFans Creators with a live session; once a day; a failure waits, at most 3 tries a
                     day, counted on the row; a dead session is flagged and skipped
  the window         a sum only when every day through yesterday is stored; the new subscriber conversion when
                     both its series are; renew on at the last day
  per_model          the spender columns from the ledger, the OF columns from the stored days

Run: ./venv/bin/python service/tests/test_of_stats_daily.py   (exit 0 = green)
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import text  # noqa: E402

import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402
import client_pool  # noqa: E402
import of_client  # noqa: E402
import of_stats_daily as osd  # noqa: E402
import stats  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, SubscriberSnapshot, Transaction  # noqa: E402

API = of_client.API_BASE
FIX = json.loads((Path(__file__).parent / "fixtures" / "of_statistics_reads.json").read_text())
A1, A2, A3, A4 = "7300001", "7300002", "7300003", "7300004"
NOW = datetime(2026, 10, 3, 12, 0)  # yesterday = 2026-10-02, the fixture's last chart day


def _series(days: dict[str, int]) -> list[dict]:
    return [{"date": f"{d}T00:00:00+00:00", "count": n} for d, n in sorted(days.items())]


def _fake(replies: dict[str, dict] | None = None):
    """An OFClient whose GETs are recorded and answered from the fixture (or `replies`, keyed by path, then
    `path?by=`)."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.sent = []

    def get_json(path, params=None):
        c.sent.append((path[len(API):], dict(params or {})))
        key = path[len(API):]
        by = (params or {}).get("by")
        for k in (f"{key}?by={by}", key):
            if replies and k in replies:
                return copy.deepcopy(replies[k])
        return copy.deepcopy(FIX[key])
    c.get_json = get_json
    return c


EARN_FILTER = {f"filter[{c}_{m}]": f"{c}_{m}" for c in (*osd.EARNINGS, osd.TOTAL) for m in ("count", "amount")}


async def _never_due(aid, *, now=None):
    return False


def _sql(stmt: str, **params):
    async def go():
        async with get_session() as s:
            res = await s.execute(text(stmt), params)
            out = res.all() if res.returns_rows else None
            await s.commit()
            return out
    return asyncio.run(go())


def _rows(aid: str) -> dict[str, tuple]:
    return {r[0]: tuple(r[1:]) for r in _sql(
        "SELECT day, visitors, new_subs, renewals, active_fans, renew_on FROM of_stats_daily "
        "WHERE account_id = :a ORDER BY day", a=aid)}


async def _seed() -> None:
    async with get_session() as s:
        for aid in (A1, A2, A3, A4):
            s.add(Account(id=aid, nickname=f"stats_{aid}"))
        await s.commit()


asyncio.run(_seed())


def case_the_fetch_reads_three_charts_and_stores_each_day():
    c = _fake()
    n = asyncio.run(osd.snapshot(A1, c, now=NOW, pause_s=0))
    rng = {"startDate": "2026-09-26 00:00:00", "endDate": "2026-10-02 23:59:59"}
    assert c.sent == [("/users/me/profile/stats", {**rng, "limit": 10}),
                      ("/subscriptions/subscribers/chart", {**rng, "by": "new"}),
                      ("/subscriptions/subscribers/chart", {**rng, "by": "renew"}),
                      ("/earnings/chart", {**rng, "withTotal": "true", **EARN_FILTER})], c.sent
    # The fixture: visitors 0 on 10-01 and 3 on 10-02; subscribes 0 on 10-01 (both tabs answer it).
    assert n == 2, n
    assert _rows(A1) == {"2026-10-01": (0, 0, 0, None, None), "2026-10-02": (3, None, None, None, None)}, _rows(A1)


def case_a_series_not_one_point_per_day_is_not_stored():
    weekly = {"subscribes": _series({"2026-09-21": 4, "2026-09-28": 5}), "earnings": [], "subscribers": 9}
    c = _fake({"/subscriptions/subscribers/chart?by=new": weekly,
               "/users/me/profile/stats": {"chart": {"visitors": "n/a"}}})
    got = osd.fetch_blocking(c, datetime(2026, 9, 26).date(), datetime(2026, 10, 2).date(), pause_s=0)
    assert set(got) == {"renewals"}, got
    assert osd._points([{"date": "2026-10-01T00:00:00+00:00", "count": 1.5}], NOW.date(), NOW.date()) is None
    assert osd._points([{"date": "2026-10-01T00:00:00+00:00", "count": -1}], NOW.date(), NOW.date()) is None
    assert osd._points([{"day": "2026-10-01", "count": 1}], NOW.date(), NOW.date()) is None


def case_a_refetch_overwrites_its_series_and_keeps_the_roster_columns():
    _sql("UPDATE of_stats_daily SET active_fans = 40, renew_on = 10 WHERE account_id = :a AND day = '2026-10-02'",
         a=A1)
    week = {f"2026-09-{d}": d for d in range(26, 31)} | {"2026-10-01": 1, "2026-10-02": 2, "2026-10-03": 99}
    c = _fake({"/users/me/profile/stats": {"chart": {"visitors": _series(week)}},
               "/subscriptions/subscribers/chart?by=new": {"subscribes": _series({d: 1 for d in week})},
               "/subscriptions/subscribers/chart?by=renew": {"subscribes": _series({d: 2 for d in week})}})
    assert asyncio.run(osd.snapshot(A1, c, now=NOW, pause_s=0)) == 7, "today (10-03) is never stored"
    rows = _rows(A1)
    assert "2026-10-03" not in rows, rows
    assert rows["2026-10-02"] == (2, 1, 2, 40, 10), rows["2026-10-02"]
    assert rows["2026-09-26"] == (26, 1, 2, None, None), rows["2026-09-26"]


def case_the_roster_lands_on_its_crawls_day():
    early, late = datetime(2026, 10, 2, 9, 0), datetime(2026, 10, 2, 23, 40)

    async def seed():
        async with get_session() as s:
            # An older crawl listed a fan who has since lapsed: not active at the latest one.
            s.add(SubscriberSnapshot(account_id=A2, fan_id=1, renew_on=True, seen_at=early))
            for fid, on in ((2, True), (3, True), (4, False)):
                s.add(SubscriberSnapshot(account_id=A2, fan_id=fid, renew_on=on, seen_at=late))
            await s.commit()
    asyncio.run(seed())
    assert asyncio.run(osd.sample_roster(A2, now=NOW)) is True
    assert _rows(A2) == {"2026-10-02": (None, None, None, 3, 2)}, _rows(A2)
    _sql("UPDATE subscriber_snapshot SET renew_on = NULL WHERE account_id = :a AND fan_id = 4", a=A2)
    asyncio.run(osd.sample_roster(A2, now=NOW))
    assert _rows(A2)["2026-10-02"] == (None, None, None, 3, None), "an unknown status is no count"
    assert asyncio.run(osd.sample_roster(A3, now=NOW)) is False, "no crawl, no row"
    assert _rows(A3) == {}


def case_the_pass_fetches_only_live_onlyfans_creators_a_few_times_a_day_at_most():
    metas = [{"id": A1, "has_session": True}, {"id": A2, "has_session": True},
             {"id": A3, "has_session": False}, {"id": A4, "has_session": True},
             {"id": "7300009", "has_session": True}]
    platforms = {"7300009": "fansly"}
    built: list[str] = []
    fail: dict[str, Exception | None] = {"with": RuntimeError("proxy down")}

    def get(aid):
        built.append(aid)
        if aid == A2 and fail["with"] is not None:
            raise fail["with"]
        return _fake()

    def tick(at):
        return asyncio.run(osd.tick(now=at, pause_s=0))
    saved = (account_registry.list_accounts, account_registry.get_platform, client_pool.get, osd.earnings_due)
    osd.earnings_due = _never_due  # the earnings history walk has its own case
    account_registry.list_accounts = lambda: metas
    account_registry.get_platform = lambda aid: platforms.get(aid, "onlyfans")
    client_pool.get = get
    asyncio.run(account_health.mark_session_dead(A4, "wrong_user"))
    try:
        assert tick(NOW) == {} and built == [A2], built  # A1 already holds yesterday; A2 fails
        assert not asyncio.run(account_health.is_session_dead(A2)), "a proxy blip is no dead session"
        fail["with"] = None
        tick(NOW + timedelta(hours=5))
        assert built == [A2], "a failure waits; counted on the row, so a restart waits too"
        assert tick(NOW + timedelta(hours=6)) == {A2: 2} and built == [A2, A2], built
        tick(NOW + timedelta(hours=11))
        assert built == [A2, A2], "yesterday stored: not due again today"

        # The next day both are due. The fixture has no point for it, so A1's fetch stores nothing for
        # yesterday either: both are capped.
        built.clear()
        fail["with"] = RuntimeError("proxy down")
        day2 = datetime(2026, 10, 4)
        assert set(tick(day2)) == {A1}, "A2 fails again"
        for h in (6, 12, 18):
            tick(day2 + timedelta(hours=h))
        assert built == [A1, A2] * 3, ("three tries a day at most", built)

        built.clear()
        fail["with"] = FileNotFoundError(f"Account {A2} has no captured session")
        day3 = datetime(2026, 10, 5)
        tick(day3)
        assert asyncio.run(account_health.is_session_dead(A2)), "a dead session is flagged"
        tick(day3 + timedelta(hours=7))
        assert built.count(A2) == 1, ("a dead session is not fetched again", built)
        assert A4 not in built
    finally:
        account_registry.list_accounts, account_registry.get_platform, client_pool.get, osd.earnings_due = saved
        for aid in (A2, A4):
            asyncio.run(account_health.clear_session_dead(aid))


def case_window_days_name_the_reports_calendar_days():
    utc = osd.window_days(datetime(2026, 10, 13), datetime(2026, 10, 19, 23, 59, 59, 999_999))
    ny = osd.window_days(datetime(2026, 10, 13, 4), datetime(2026, 10, 20, 3, 59, 59, 999_000))
    tokyo = osd.window_days(datetime(2026, 10, 12, 15), datetime(2026, 10, 19, 14, 59, 59, 999_000))
    want = (datetime(2026, 10, 13).date(), datetime(2026, 10, 19).date())
    assert utc == ny == tokyo == want, (utc, ny, tokyo)


def case_the_window_sums_only_whole_coverage():
    _sql("DELETE FROM of_stats_daily")
    for d in range(1, 8):
        _sql("INSERT INTO of_stats_daily (account_id, day, visitors, new_subs, renewals) "
             "VALUES (:a, :d, 10, 2, :r)", a=A1, d=f"2026-10-0{d}", r=None if d == 3 else 1)
    _sql("UPDATE of_stats_daily SET active_fans = 50, renew_on = 20 WHERE day = '2026-10-07'")
    now = datetime(2026, 10, 8, 6)

    def fig(lo, hi, aids=None):
        return asyncio.run(osd.window_figures(aids, datetime(2026, 10, lo), datetime(2026, 10, hi, 23, 59, 59),
                                              now=now)).get(A1)
    assert fig(1, 7) == {"of_visitors": 70, "of_new_sub_conversion_pct": 20.0,
                         "of_renew_on": 20, "of_renew_on_pct": 40.0}, fig(1, 7)
    assert fig(4, 7)["of_renewals"] == 4, "a window without the missing day sums"
    assert fig(4, 8)["of_visitors"] == 40, "today is cut off: the window runs through yesterday"
    assert "of_renew_on" not in fig(4, 6), "renew on is the window's last day's"
    _sql("UPDATE of_stats_daily SET new_subs = NULL WHERE day = '2026-10-05'")
    assert "of_new_sub_conversion_pct" not in fig(4, 7), "no conversion without every day's new subscribers"
    assert asyncio.run(osd.window_figures(None, datetime(2026, 9, 30), datetime(2026, 10, 7, 23, 59, 59),
                                          now=now))[A1].get("of_visitors") is None, "a day before the first stored"
    assert fig(1, 7, [A2]) is None, "scoped to the Creators asked"


def case_per_model_carries_the_spender_and_of_columns():
    async def seed():
        async with get_session() as s:
            at = datetime(2026, 10, 5, 12)
            for fan, kind, cents in ((1, "ppv_message", 1000), (1, "tip", 500), (2, "tip_post", 300),
                                     (3, "subscription", 999), (3, "rebill", 999)):
                s.add(Transaction(account_id=A1, fan_id=fan, kind=kind, amount_cents=cents, occurred_at=at,
                                  status="cleared", currency="USD", source="ledger"))
            s.add(Transaction(account_id=A1, fan_id=4, kind="tip", amount_cents=7000, occurred_at=at,
                              status="chargedback", currency="USD", source="ledger"))
            await s.commit()
    asyncio.run(seed())
    pm = asyncio.run(stats.per_model(from_="2026-10-01", to="2026-10-07", account_id=None, engagement=False))
    row = {m["account_id"]: m for m in pm["per_model"]}
    a1, a3 = row[A1], row[A3]
    # Fans 1 and 2 bought or tipped; fan 3 only subscribed; fan 4's tip was charged back.
    assert (a1["spenders_count"], a1["avg_spend_per_spender_cents"], a1["avg_spend_per_transaction_cents"]) \
        == (2, 900, 600), a1
    assert (a3["spenders_count"], a3["avg_spend_per_spender_cents"]) == (0, None), a3
    assert a1["of_visitors"] == 70 and a1["of_new_sub_conversion_pct"] is None and a1["of_renewals"] is None, a1
    assert a1["of_renew_on"] == 20 and a1["of_renew_on_pct"] == 40.0, a1
    assert a3["of_visitors"] is None and a3["of_renew_on"] is None and a3["of_new_sub_conversion_pct"] is None, a3


def _chart(cats: dict[str, dict[str, float]], counts: dict | None = None, gross: dict | None = None,
           total: bool = True) -> dict:
    """An /earnings/chart reply as OF answers Statements' filters: per category (under OF's reply key, messages as
    `chat_messages`) its daily net amounts (dollars), counts, net total and gross, and OF's `total` of them."""
    out = {}
    for c, days in cats.items():
        tot = sum(days.values())
        out[osd.REPLY_KEY.get(c, c)] = {
            "chartAmount": [{"date": f"{d}T00:00:00+00:00", "count": v} for d, v in sorted(days.items())],
            "chartCount": [{"date": f"{d}T00:00:00+00:00", "count": (counts or {}).get(c, {}).get(d, 0)}
                           for d in sorted(days)],
            "total": tot, "gross": (gross or {}).get(c, round(tot / 0.8, 2)), "delta": 0}
    if total:
        days = sorted({d for v in cats.values() for d in v})
        out["total"] = {"chartAmount": [{"date": f"{d}T00:00:00+00:00", "count": sum(v.get(d, 0) for v in cats.values())}
                                        for d in days],
                        "total": sum(sum(v.values()) for v in cats.values()), "gross": 0, "delta": 0}
    return out


def case_the_earnings_chart_is_read_per_day_and_category():
    d1, d2 = datetime(2026, 10, 1).date(), datetime(2026, 10, 2).date()
    reply = _chart({"tips": {"2026-10-01": 8, "2026-10-02": 12.8}, "messages": {"2026-10-02": 100}},
                   counts={"tips": {"2026-10-01": 2, "2026-10-02": 3}}, gross={"tips": 26.0, "messages": 125})
    assert "chat_messages" in reply and "messages" not in reply
    got = osd._earnings(reply, d1, d2)
    # tips: 20.80 net over 26.00 gross, so each day's gross is 1.25x its net; messages charted 10-02 only;
    # subscribes, post and stream are not in the reply: zero.
    assert got["2026-10-01"]["tips"] == (800, 1000, 2), got
    assert got["2026-10-02"]["tips"] == (1280, 1600, 3), got
    assert got["2026-10-01"]["messages"] == (0, 0, 0) and got["2026-10-02"]["messages"] == (10000, 12500, 0), got
    assert got["2026-10-02"]["subscribes"] == (0, 0, 0), got
    assert set(got["2026-10-02"]) == {*osd.EARNINGS, osd.TOTAL} and got["2026-10-02"][osd.TOTAL][0] == 11280, got
    # The recorded reply to the job's own filters (2026-10-25's shape): a $14 PPV message is $11.20 net, not $0.
    rec = osd._earnings(FIX["/earnings/chart?filter=statements"], d1, d2)
    assert rec["2026-10-01"]["messages"] == (1120, 1400, 1), rec
    assert rec["2026-10-02"]["tips"] == (800, 1000, 2) and rec["2026-10-02"]["subscribes"] == (400, 500, 1), rec
    assert osd._earnings(_chart({"tips": {"2026-09-21": 1, "2026-09-28": 2}}), d1, d2) is None, "a weekly bucket"
    assert osd._earnings([], d1, d2) is None, "OF's [] (no filter) is no chart"
    assert osd._earnings({}, d1, d2) is None, "no total: nothing to check the categories against, not a known $0"
    assert osd._earnings(_chart({"tips": {"2026-10-01": 8}}, total=False), d1, d1) is None, "no total"
    # The bug of 2026-10-25: money under a key not read (messages answered as `chat_messages`, read as `messages`)
    # does not add up to OF's total, so the days are not stored as $0.
    wrong_key = _chart({"tips": {"2026-10-01": 8}, "messages": {"2026-10-01": 11.2}})
    wrong_key["unread_messages"] = wrong_key.pop("chat_messages")
    assert osd._earnings(wrong_key, d1, d1) is None, "a category we do not read"
    # OF cuts its days at UTC midnight; a point cut at another zone's midnight would not line up with ours.
    pacific = _chart({"tips": {"2026-10-01": 8}})
    for b in pacific.values():
        for pt in b["chartAmount"]:
            pt["date"] = "2026-10-01T00:00:00-07:00"
    assert osd._earnings(pacific, d1, d1) is None, "a day cut at UTC-7"
    assert osd._earnings({"foo": 1}, d1, d2) is None, "no Statements category among other keys"
    assert osd._earnings({"tips": {"chartAmount": "n/a"}, "total": {"chartAmount": []}}, d1, d2) is None
    no_gross = _chart({"tips": {"2026-10-01": 8}}, gross={"tips": 0})
    assert osd._earnings(no_gross, d1, d1)["2026-10-01"]["tips"] == (800, 1000, 0), "no gross: net / 0.8"
    negative = osd._earnings(_chart({"tips": {"2026-10-01": -3.5}, "messages": {"2026-10-01": 2}}), d1, d1)
    assert negative["2026-10-01"][osd.TOTAL][0] == -150, "a chargeback day adds up too"


def case_days_stored_before_the_total_check_are_read_again():
    """Rows written by the reader of before 2026-10-25 (no `total`, PPV messages at $0) are not OF's days: the
    reports read the ledger for them, the job asks OF again and overwrites them, with no manual data fix."""
    saved = osd._EARNINGS_HISTORY_DAYS
    osd._EARNINGS_HISTORY_DAYS = 3
    now = datetime(2026, 10, 3, 6)
    try:
        _sql("DELETE FROM of_earnings_daily")
        old = {d: {c: (0, 0, 0) for c in osd.EARNINGS} for d in ("2026-09-30", "2026-10-01", "2026-10-02")}
        asyncio.run(osd._upsert_earnings(A4, old, now))
        assert asyncio.run(osd.earnings_due(A4, now=now)), "a day without OF's total is due"
        cells, _ = asyncio.run(osd.earnings_window([A4], datetime(2026, 9, 30), datetime(2026, 10, 2, 23, 59, 59),
                                                   now=now))
        assert cells == {}, "and is not read as OF's $0"
        c = _fake({"/earnings/chart": _chart({"messages": {"2026-10-01": 11.2}, "tips": {"2026-10-02": 4}})})
        assert asyncio.run(osd.backfill_earnings(A4, c, now=now, pause_s=0)) == 3 and len(c.sent) == 1
        got = _sql("SELECT day, net_cents FROM of_earnings_daily WHERE account_id = :a AND category = 'messages' "
                   "ORDER BY day", a=A4)
        assert got == [("2026-09-30", 0), ("2026-10-01", 1120), ("2026-10-02", 0)], got
        assert not asyncio.run(osd.earnings_due(A4, now=now))
    finally:
        osd._EARNINGS_HISTORY_DAYS = saved
        _sql("DELETE FROM of_earnings_daily")


def case_the_earnings_history_fills_its_newest_missing_days_back_to_the_horizon():
    saved = osd._EARNINGS_HISTORY_DAYS
    osd._EARNINGS_HISTORY_DAYS = 75
    now = datetime(2026, 10, 3, 6)  # yesterday 10-02: the history is 07-20 .. 10-02
    try:
        _sql("DELETE FROM of_earnings_daily")
        asyncio.run(osd._upsert_earnings(A4, {d: {"tips": (100, 125, 1), osd.TOTAL: (100, 125, 1)}
                                              for d in ("2026-10-01", "2026-10-02")}, now))
        assert asyncio.run(osd.earnings_due(A4, now=now))
        c = _fake({"/earnings/chart": _chart({"tips": {"2026-09-01": 5}})})
        assert asyncio.run(osd.backfill_earnings(A4, c, now=now, pause_s=0, chunks=2)) == 60
        sent = [(p["startDate"], p["endDate"]) for _, p in c.sent]
        assert sent == [("2026-09-01 00:00:00", "2026-09-30 23:59:59"),
                        ("2026-08-02 00:00:00", "2026-08-31 23:59:59")], sent
        c.sent.clear()
        assert asyncio.run(osd.backfill_earnings(A4, c, now=now, pause_s=0)) == 13
        assert [p["startDate"][:10] + ".." + p["endDate"][:10] for _, p in c.sent] == ["2026-07-20..2026-08-01"]
        assert not asyncio.run(osd.earnings_due(A4, now=now)), "every day of the history is stored"
        got = _sql("SELECT net_cents, gross_cents FROM of_earnings_daily WHERE account_id = :a AND day = '2026-09-01' "
                   "AND category = 'tips'", a=A4)
        assert got == [(500, 625)], got
        _sql("DELETE FROM of_earnings_daily WHERE account_id = :a AND day < '2026-08-10'", a=A4)
        bad = _fake({"/earnings/chart": []})
        assert asyncio.run(osd.backfill_earnings(A4, bad, now=now, pause_s=0)) == 0 and len(bad.sent) == 1, \
            "a reply in another shape stores nothing and waits for the next tick"
    finally:
        osd._EARNINGS_HISTORY_DAYS = saved
        _sql("DELETE FROM of_earnings_daily")


def _of_days(aid: str, days: dict[str, dict[str, tuple[int, int, int]]]) -> None:
    """Store OF's days as the job does: every category, and their total."""
    def total(cats):
        return tuple(sum(v[i] for v in cats.values()) for i in range(3))
    asyncio.run(osd._upsert_earnings(aid, {d: {**{c: cats.get(c, (0, 0, 0)) for c in osd.EARNINGS}, osd.TOTAL: total(cats)}
                                           for d, cats in days.items()}, datetime(2026, 10, 1)))


def case_the_reports_read_the_larger_of_of_and_the_ledger_per_day():
    A5 = "7300005"

    async def seed():
        async with get_session() as s:
            s.add(Account(id=A5, nickname="added 09-12", created_at=datetime(2026, 9, 12, 15)))
            await s.flush()
            for day, kind, gross, net in ((11, "tip", 1000, 800), (12, "ppv_message", 2000, 1600),
                                          (13, "subscription", 500, 400)):
                s.add(Transaction(account_id=A5, fan_id=day, kind=kind, amount_cents=gross, net_cents=net,
                                  fee_cents=gross - net, occurred_at=datetime(2026, 9, day, 12), status="cleared",
                                  currency="USD", source="ledger"))
            await s.commit()
    asyncio.run(seed())
    # OF's own days: 09-10 and 09-11 (the ledger's 09-11 tip is in OF's tips: max, not a sum); 09-12 and 09-13
    # are not read yet.
    _of_days(A5, {"2026-09-10": {"tips": (5000, 6250, 4)}, "2026-09-11": {"tips": (3000, 3750, 2)}})

    def rev(lo, hi, **kw):
        kw = {"account_id": A5, "include_net": True, "by_kind": False, "status": "tracked",
              "from_": lo, "to": hi, **kw}
        return asyncio.run(stats.revenue(**kw))
    by_kind = rev("2026-09-10", "2026-09-13", group_by="kind")
    kinds = {r["kind"]: (r["total_cents"], r["net_cents"], r["count"], r["fee_cents"]) for r in by_kind["rows"]}
    assert kinds == {"tip": (10000, 8000, 6, 2000), "ppv_message": (2000, 1600, 1, 400),
                     "subscription": (500, 400, 1, 100)}, kinds
    assert by_kind["history_missing_days"] == 0, by_kind
    by_day = rev("2026-09-10", "2026-09-13", group_by="day", by_kind=True)
    days = {r["day"]: (r["total_cents"], r["net_cents"], [k["kind"] for k in r["by_kind"]]) for r in by_day["rows"]}
    assert days == {"2026-09-10": (6250, 5000, ["tip"]), "2026-09-11": (3750, 3000, ["tip"]),
                    "2026-09-12": (2000, 1600, ["ppv_message"]), "2026-09-13": (500, 400, ["subscription"])}, days
    # 09-08 and 09-09: before A5 was added, no OF figure: unknown, so a growth against them is "-".
    assert rev("2026-09-08", "2026-09-11", group_by="kind")["history_missing_days"] == 2
    assert rev("2026-09-12", "2026-09-13", group_by="kind")["history_missing_days"] == 0, "after it was added"
    assert "history_missing_days" not in rev("2026-09-10", "2026-09-13", group_by="kind", status="reversed")
    hours = rev("2026-09-11", "2026-09-11", group_by="hour")["rows"]
    assert [(r["day"], r["total_cents"]) for r in hours] == [("2026-09-11T12:00", 1000)], "hours stay the ledger's"

    pm = asyncio.run(stats.per_model(from_="2026-09-10", to="2026-09-13", account_id=A5, engagement=False))
    (row,) = pm["per_model"]
    assert (row["total_revenue_cents"], row["total_net_revenue_cents"]) == (12500, 10000), row
    rk = row["revenue_by_kind"]
    assert (rk["tip"], rk["ppv"], rk["subscription"]) == (10000, 2000, 500), rk

    # Today is never OF's: the window runs through yesterday.
    _of_days(A5, {"2026-09-20": {"tips": (100, 125, 1)}, "2026-09-21": {"tips": (100, 125, 1)}})
    cells, _ = asyncio.run(osd.earnings_window([A5], datetime(2026, 9, 20), datetime(2026, 9, 21, 23, 59, 59),
                                               now=datetime(2026, 9, 21, 18)))
    assert set(cells) == {(A5, "2026-09-20")}, cells
    # The answer is kept until the job writes again, and a write is read at once.
    again, _ = asyncio.run(osd.earnings_window([A5], datetime(2026, 9, 20), datetime(2026, 9, 21, 23, 59, 59),
                                               now=datetime(2026, 9, 21, 18)))
    assert again is cells, "a repeated window is the kept answer"
    _of_days(A5, {"2026-09-20": {"tips": (900, 1125, 3)}})
    fresh, _ = asyncio.run(osd.earnings_window([A5], datetime(2026, 9, 20), datetime(2026, 9, 21, 23, 59, 59),
                                               now=datetime(2026, 9, 21, 18)))
    assert [c["net_cents"] for c in fresh[(A5, "2026-09-20")]] == [900], fresh
    # A write elsewhere (another window's days) keeps this window's answer; askers at once share one read.
    _of_days(A5, {"2026-08-01": {"tips": (100, 125, 1)}})
    kept, _ = asyncio.run(osd.earnings_window([A5], datetime(2026, 9, 20), datetime(2026, 9, 21, 23, 59, 59),
                                              now=datetime(2026, 9, 21, 18)))
    assert kept is fresh, "a write outside the window keeps it"
    reads, real = [], osd._read_window

    async def counted(*a):
        reads.append(a)
        await asyncio.sleep(0.01)
        return await real(*a)

    async def crowd():
        return await asyncio.gather(*(osd.earnings_window([A5], datetime(2026, 9, 1), datetime(2026, 9, 5),
                                                          now=datetime(2026, 9, 21, 18)) for _ in range(20)))
    osd._read_window = counted
    try:
        got = asyncio.run(crowd())
    finally:
        osd._read_window = real
    assert len(reads) == 1 and all(g[0] is got[0][0] for g in got), len(reads)


def case_an_of_zero_day_never_erases_a_sale_the_ledger_holds():
    """max(OF, ledger) per Creator, UTC day and category: OF's $0 (or a chargeback day's negative) keeps the
    ledger's sale; OF's larger figure adds only what the ledger lacks."""
    A6 = "7300006"

    async def seed():
        async with get_session() as s:
            s.add(Account(id=A6, nickname="max", created_at=datetime(2026, 8, 1)))
            await s.flush()
            for fan, kind, gross, at, status in ((1, "ppv_message", 1400, datetime(2026, 8, 21, 19, 0, 3), "pending"),
                                                 (2, "tip", 1000, datetime(2026, 8, 22, 9), "cleared"),
                                                 (3, "tip", 500, datetime(2026, 8, 23, 9), "cleared")):
                s.add(Transaction(account_id=A6, fan_id=fan, kind=kind, amount_cents=gross, net_cents=gross * 8 // 10,
                                  fee_cents=gross // 5, occurred_at=at, status=status, currency="USD", source="ledger"))
            await s.commit()
    asyncio.run(seed())
    # 08-21: OF $0 (the prod case: the $14 PPV message read as $0); 08-22: OF's tips a chargeback day (-$3);
    # 08-23: OF has $20 of tips where the ledger caught $5.
    _of_days(A6, {"2026-08-21": {}, "2026-08-22": {"tips": (-300, -375, 0)}, "2026-08-23": {"tips": (1600, 2000, 3)}})

    def rev(**kw):
        return asyncio.run(stats.revenue(**{"account_id": A6, "include_net": True, "by_kind": False,
                                            "status": "tracked", "from_": "2026-08-21", "to": "2026-08-23", **kw}))
    days = {r["day"]: (r["total_cents"], r["net_cents"], r["count"]) for r in rev(group_by="day")["rows"]}
    assert days == {"2026-08-21": (1400, 1120, 1), "2026-08-22": (1000, 800, 1), "2026-08-23": (2000, 1600, 3)}, days
    kinds = {r["kind"]: (r["total_cents"], r["net_cents"]) for r in rev(group_by="kind")["rows"]}
    assert kinds == {"ppv_message": (1400, 1120), "tip": (3000, 2400)}, kinds
    pm = asyncio.run(stats.per_model(from_="2026-08-21", to="2026-08-23", account_id=A6, engagement=False))
    (row,) = pm["per_model"]
    assert (row["total_revenue_cents"], row["total_net_revenue_cents"]) == (4400, 3520), row
    assert (row["revenue_by_kind"]["ppv"], row["revenue_by_kind"]["tip"]) == (1400, 3000), row


def case_a_sale_near_midnight_in_another_zone_is_counted_once_on_its_local_day():
    """OF cuts days at UTC midnight (its points are stamped 00:00+00:00; a sale at 19:00 UTC charts on that UTC
    day, measured 2026-10-25), the report at the Agency's zone. A sale at 23:30 in UTC-7 (06:30 UTC the next day)
    is in OF's next UTC day: the report shows it once, on its local day, not again on OF's."""
    A7 = "7300007"

    async def seed():
        async with get_session() as s:
            s.add(Account(id=A7, nickname="pacific", created_at=datetime(2026, 7, 1)))
            await s.flush()
            s.add(Transaction(account_id=A7, fan_id=1, kind="ppv_message", amount_cents=2500, net_cents=2000,
                              fee_cents=500, occurred_at=datetime(2026, 7, 15, 6, 30), status="cleared",
                              currency="USD", source="ledger"))
            await s.commit()
    asyncio.run(seed())
    _of_days(A7, {"2026-07-14": {}, "2026-07-15": {"messages": (2000, 2500, 1)}})
    real = stats._report_prefs

    async def pacific(_aid):
        return ZoneInfo("America/Los_Angeles"), "monday"
    stats._report_prefs = pacific
    try:
        got = asyncio.run(stats.revenue(account_id=A7, include_net=True, by_kind=False, status="tracked",
                                        from_="2026-07-14", to="2026-07-15", group_by="day"))
        days = {r["day"]: (r["total_cents"], r["count"]) for r in got["rows"]}
        assert days == {"2026-07-14": (2500, 1)}, days
        pm = asyncio.run(stats.per_model(from_="2026-07-14", to="2026-07-15", account_id=A7, engagement=False))
        assert pm["per_model"][0]["total_revenue_cents"] == 2500, pm["per_model"][0]
    finally:
        stats._report_prefs = real


_harness.run()
