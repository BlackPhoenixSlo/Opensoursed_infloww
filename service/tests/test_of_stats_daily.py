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
                      ("/subscriptions/subscribers/chart", {**rng, "by": "renew"})], c.sent
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
    saved = (account_registry.list_accounts, account_registry.get_platform, client_pool.get)
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
        account_registry.list_accounts, account_registry.get_platform, client_pool.get = saved
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


_harness.run()
