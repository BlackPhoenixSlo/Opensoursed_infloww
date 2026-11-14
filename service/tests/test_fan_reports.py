#!/usr/bin/env python3
"""Fan reports (roadmap W5 5.6): `/admin/stats/fan-report` over a window, per Creator.

  top     each fan's window spend split into tips / PPV / subscriptions, pending counted, a refund not, ranked
          by the asked metric; net is OF's net, else 80% of gross (net_or_80); the fan's name and his roster
          subscription start ride along.
  csv     `format=csv` streams the whole ranking (`limit` aside) with FAN_REPORT_FIELDS as the header, under the
          shared CSV cap.
  traffic the window's spend by the trial link or promotion each spender claimed (his earliest claim by OF's
          subscribe_at, else first sighting, then id), named by the trial mirror and the promotion's campaign (through
          link_meta.campaign_id); the rest as no link.
  growth  new fans per report-zone day (a subscription sale or the roster's subscribe_at, each fan once) and
          renewed fans (a rebill), each per Creator and day raised to OF's own stored count when larger.
  scope   another Agency's Creator is 403.

Seeded straight into the temp DB; no network.

Run: ./venv/bin/python service/tests/test_fan_reports.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import csv  # noqa: E402
import io  # noqa: E402
from datetime import datetime  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import csv_export  # noqa: E402
from _clock_fixtures import IDS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Fan, LinkClaimer, LinkMeta, OfStatsDaily, PromoCampaign, SubscriberSnapshot, Transaction, TrialLinkMirror,
    UserAccount,
)
from stats_fans import FAN_REPORT_FIELDS  # noqa: E402

OWNER_A = fx.login_owner("agency_a_owner")


def _creator(aid: str) -> str:
    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"fr_creator_{aid[-2:]}", color="#aaaaaa"))
        async with get_session() as s:
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))
    (account_registry.ACCOUNTS_DIR / aid).mkdir()
    asyncio.run(_seed())
    return aid


def _add(*rows) -> None:
    async def _seed():
        async with get_session() as s:
            s.add_all(rows)
    asyncio.run(_seed())


def _sale(aid: str, fan: int, kind: str, cents: int, at: datetime, status: str = "cleared",
          net: int | None = None) -> None:
    _add(Transaction(account_id=aid, fan_id=fan, kind=kind, amount_cents=cents, net_cents=net, occurred_at=at,
                     status=status, currency="USD", source="ledger"))


def _get(path: str, status: int = 200):
    r = OWNER_A.get(path)
    assert r.status_code == status, f"{path}: {r.status_code} {r.text}"
    return r


C1, C2, C3, C4, C5 = (_creator("5600001"), _creator("5600002"), _creator("5600003"), _creator("5600004"),
                      _creator("5600005"))
C6 = _creator("5600016")
MARCH = "from=2026-03-01&to=2026-03-31"


def case_top_fans_split_spend_by_kind_and_rank_by_the_asked_metric():
    at = datetime(2026, 3, 10, 12, 0)
    _add(Fan(account_id=C1, fan_id=1, of_display_name="Whale", of_username="whale1"),
         SubscriberSnapshot(account_id=C1, fan_id=1, subscribe_at=datetime(2026, 1, 5), seen_at=at))
    _sale(C1, 1, "ppv_message", 5000, at, net=4000)
    _sale(C1, 1, "subscription", 1000, at, net=800)
    _sale(C1, 1, "tip", 500, at, status="pending")                 # pending counts; no net yet: 80%
    _sale(C1, 1, "tip", 9999, at, status="refunded")               # a refund does not
    _sale(C1, 1, "tip", 7777, datetime(2026, 4, 2))                # outside the window
    _sale(C1, 2, "tip", 3000, at)
    _sale(C1, 2, "custom", 100, at)                                # total only
    _sale(C2, 3, "tip", 99_000, at)                                # another Creator

    body = _get(f"/admin/stats/fan-report?account_id={C1}&{MARCH}").json()
    top = body["top_fans"]
    assert [f["fan_id"] for f in top] == [1, 2], top
    assert top[0] == {"account_id": C1, "fan_id": 1, "fan_name": "Whale", "username": "whale1",
                      "total_cents": 6500, "net_or_80_cents": 5200, "tips_cents": 500, "ppv_cents": 5000,
                      "subs_cents": 1000, "subscribed_at": "2026-01-05T00:00:00"}, top[0]
    assert (top[1]["total_cents"], top[1]["tips_cents"], top[1]["subscribed_at"]) == (3100, 3000, None), top[1]

    tips = _get(f"/admin/stats/fan-report?account_id={C1}&{MARCH}&sort=tips&limit=1").json()["top_fans"]
    assert [f["fan_id"] for f in tips] == [2], tips


def case_csv_streams_the_whole_ranking_under_the_shared_cap():
    path = f"/admin/stats/fan-report?account_id={C1}&{MARCH}&sort=tips&limit=1&format=csv"
    r = _get(path)
    assert r.headers["content-type"].startswith("text/csv"), r.headers
    assert "top-fans_2026-03-01_to_2026-03-31.csv" in r.headers["content-disposition"], r.headers
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == list(FAN_REPORT_FIELDS), rows[0]
    assert [(row[1], row[6]) for row in rows[1:]] == [("2", "3000"), ("1", "500")], rows

    real, csv_export.CSV_MAX_ROWS = csv_export.CSV_MAX_ROWS, 1
    try:
        rows = list(csv.reader(io.StringIO(_get(path).text)))
    finally:
        csv_export.CSV_MAX_ROWS = real
    assert [row[0] for row in rows[1:]] == [C1, csv_export.TRUNCATED_LINE], rows


def case_traffic_groups_spend_by_each_fans_earliest_claimed_link():
    at = datetime(2026, 3, 12, 9, 0)
    seen = datetime(2026, 3, 1)
    feb = datetime(2026, 2, 1)
    _add(TrialLinkMirror(account_id=C3, of_trial_id=71, name="Reddit trial"),
         PromoCampaign(id=900, account_id=C3, of_promo_id=82, name="Spring promo"),
         LinkMeta(account_id=C3, kind="trial", of_id=71, source="Reddit"),
         LinkMeta(account_id=C3, kind="promo", of_id=81, campaign_id=900))   # an earlier OF id of the re-armed promo
    _add(LinkClaimer(account_id=C3, kind="trial", of_id=71, fan_id=10, first_seen_at=seen),
         LinkClaimer(account_id=C3, kind="trial", of_id=71, fan_id=14, first_seen_at=seen))
    # Recorded after the trial claim, but OF dates fan 10's promo subscription earlier: the promo is his first.
    _add(LinkClaimer(account_id=C3, kind="promo", of_id=81, fan_id=10, first_seen_at=seen, subscribe_at=feb),
         LinkClaimer(account_id=C3, kind="promo", of_id=81, fan_id=11, first_seen_at=seen),
         LinkClaimer(account_id=C3, kind="promo", of_id=81, fan_id=13, first_seen_at=seen))  # spent nothing
    _sale(C3, 10, "tip", 1000, at)
    _sale(C3, 10, "ppv_message", 500, at)
    _sale(C3, 11, "tip", 200, at)
    _sale(C3, 14, "tip", 300, at)
    _sale(C3, 12, "tip", 50, at)

    traffic = _get(f"/admin/stats/fan-report?account_id={C3}&{MARCH}").json()["traffic"]
    assert traffic == [
        {"account_id": C3, "kind": "promo", "of_id": 81, "name": "Spring promo", "source": None,
         "fans": 2, "total_cents": 1700},
        {"account_id": C3, "kind": "trial", "of_id": 71, "name": "Reddit trial", "source": "Reddit",
         "fans": 1, "total_cents": 300},
        {"account_id": C3, "kind": None, "of_id": None, "name": None, "source": None,
         "fans": 1, "total_cents": 50},
    ], traffic


def case_traffic_earliest_claim_ties_break_on_id():
    # Fan 20's three claims, in insert (id) order: by coalesce(subscribe_at, first_seen_at), the first
    # two tie on Mar 2, so the lower id (the trial) takes his spend.
    _add(LinkClaimer(account_id=C5, kind="trial", of_id=72, fan_id=20, first_seen_at=datetime(2026, 3, 2)),
         LinkClaimer(account_id=C5, kind="promo", of_id=83, fan_id=20, subscribe_at=datetime(2026, 3, 2),
                     first_seen_at=datetime(2026, 3, 1)),
         LinkClaimer(account_id=C5, kind="trial", of_id=73, fan_id=20, first_seen_at=datetime(2026, 3, 3)))
    _sale(C5, 20, "tip", 1000, datetime(2026, 3, 12, 9, 0))

    traffic = _get(f"/admin/stats/fan-report?account_id={C5}&{MARCH}").json()["traffic"]
    assert [(t["kind"], t["of_id"], t["fans"], t["total_cents"]) for t in traffic] == [("trial", 72, 1, 1000)], traffic


def case_growth_counts_new_and_renewed_fans_per_report_zone_day():
    seen = datetime(2026, 3, 20)
    _sale(C4, 1, "subscription", 1000, datetime(2026, 3, 5, 10, 0))
    _add(SubscriberSnapshot(account_id=C4, fan_id=1, subscribe_at=datetime(2026, 3, 5, 10, 0), seen_at=seen),
         SubscriberSnapshot(account_id=C4, fan_id=2, subscribe_at=datetime(2026, 3, 5, 11, 0), seen_at=seen),
         SubscriberSnapshot(account_id=C4, fan_id=3, subscribe_at=datetime(2026, 3, 7, 3, 0), seen_at=seen))
    _sale(C4, 4, "rebill", 1000, datetime(2026, 3, 6, 12, 0))
    _sale(C4, 4, "rebill", 1000, datetime(2026, 3, 6, 13, 0))       # the same fan twice that day
    _sale(C4, 5, "rebill", 1000, datetime(2026, 3, 6, 14, 0), status="chargedback")
    window = f"account_id={C4}&from=2026-03-01&to=2026-03-10"

    growth = _get(f"/admin/stats/fan-report?{window}").json()["growth"]
    assert growth == [{"day": "2026-03-05", "new_fans": 2, "renewed_fans": 0},
                      {"day": "2026-03-06", "new_fans": 0, "renewed_fans": 1},
                      {"day": "2026-03-07", "new_fans": 1, "renewed_fans": 0}], growth

    # New York: fan 3's 03:00 UTC start is 22:00 on the 6th.
    assert OWNER_A.put("/admin/settings/preferences", json={"report_tz": "America/New_York"}).status_code == 200
    try:
        growth = _get(f"/admin/stats/fan-report?{window}").json()["growth"]
        assert [(g["day"], g["new_fans"], g["renewed_fans"]) for g in growth] == \
            [("2026-03-05", 2, 0), ("2026-03-06", 1, 1)], growth
    finally:
        OWNER_A.put("/admin/settings/preferences", json={})


def case_growth_takes_ofs_daily_counts_when_larger():
    # A free Creator: OF counts 155 new subs on the 12th and we saw one; no sale, no roster otherwise.
    _add(SubscriberSnapshot(account_id=C6, fan_id=1, subscribe_at=datetime(2026, 3, 12, 10, 0),
                            seen_at=datetime(2026, 3, 20)),
         SubscriberSnapshot(account_id=C6, fan_id=2, subscribe_at=datetime(2026, 3, 13, 10, 0),
                            seen_at=datetime(2026, 3, 20)),
         OfStatsDaily(account_id=C6, day="2026-03-12", new_subs=155, renewals=3),
         OfStatsDaily(account_id=C6, day="2026-03-13", new_subs=0, renewals=None),
         OfStatsDaily(account_id=C6, day="2026-03-14", visitors=40),          # no subscriber reading: no row
         OfStatsDaily(account_id=C6, day="2026-04-02", new_subs=9))           # outside the window
    growth = _get(f"/admin/stats/fan-report?account_id={C6}&from=2026-03-01&to=2026-03-31").json()["growth"]
    assert growth == [{"day": "2026-03-12", "new_fans": 155, "renewed_fans": 3},
                      {"day": "2026-03-13", "new_fans": 1, "renewed_fans": 0}], growth


def case_another_agencys_creator_is_refused():
    _get(f"/admin/stats/fan-report?account_id={IDS['creator_b']}", status=403)



def case_json_spend_materialized_once_with_two_reads_and_indexed_claims():
    # A real request must do one aggregation, not two independently executed queries.
    # This fails on the old runtime even though its figures are correct.
    import sqlite3
    import sys
    from sqlalchemy import event
    engine = sys.modules["db.engine"].engine.sync_engine
    calls = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if "net_or_80_cents" in statement and "transactions" in statement:
            calls.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        body = _get(f"/admin/stats/fan-report?account_id={C1}&{MARCH}&limit=1").json()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(body["top_fans"]) == 1
    assert sum(t["fans"] for t in body["traffic"]) == 2, body
    assert len(calls) == 1, f"spend executed {len(calls)} times, expected one shared statement"
    sql, params = calls[0]
    with sqlite3.connect(f"file:{_harness.DB_PATH}?mode=ro", uri=True) as con:
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, params)]
    assert sum("MATERIALIZE fan_spend" in p for p in plan) == 1, plan
    assert sum(p.startswith(("SCAN fan_spend", "SEARCH fan_spend")) for p in plan) == 2, plan
    assert any("ix_link_claimers_account_fan" in p for p in plan), plan
    assert "FROM (SELECT" in sql and "LIMIT" in sql.split("UNION ALL")[0], sql
    assert "ORDER BY fan_report_rows.branch" in sql, sql
    # CSV must retain its independent streaming query, without materialization or UNION.
    calls.clear()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        _get(f"/admin/stats/fan-report?account_id={C1}&{MARCH}&format=csv")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(calls) == 1 and "MATERIALIZED" not in calls[0][0] and "UNION ALL" not in calls[0][0], calls


def case_signed_zero_net_and_cutoff_ties_preserve_membership_and_order():
    a, b = _creator("5600006"), _creator("5600007")
    at = datetime(2026, 3, 10)
    _sale(a, 1, "tip", 101, at)
    _sale(a, 1, "custom", -101, at)  # signed floor: 80 + (-81), total zero still a spender
    _sale(a, 2, "tip", 1000, at, net=0)
    _sale(a, 3, "ppv_message", 500, at)
    _sale(b, 3, "ppv_message", 500, at)  # every existing ordering key ties across accounts
    _sale(a, 4, "subscription", 500, at)
    _sale(a, 5, "rebill", -3, at)
    _sale(a, 11, "custom", -1, at, status="pending")
    for fan, status in enumerate(("refunded", "chargedback", "refund_pending", "failed"), 20):
        _sale(a, fan, "tip", 999999, at, status=status)
    _sale(a, 30, "tip", 999999, datetime(2026, 4, 1))
    q = f"/admin/stats/fan-report?account_id={a},{b}&{MARCH}"
    expected = {(a, 1): (0, -1, 101, 0, 0), (a, 2): (1000, 0, 1000, 0, 0),
                (a, 3): (500, 400, 0, 500, 0), (b, 3): (500, 400, 0, 500, 0),
                (a, 4): (500, 400, 0, 0, 500), (a, 5): (-3, -3, 0, 0, -3),
                (a, 11): (-1, -1, 0, 0, 0)}
    fields = ("total_cents", "net_or_80_cents", "tips_cents", "ppv_cents", "subs_cents")
    for sort, col in (("total", 0), ("tips", 2), ("ppv", 3), ("subs", 4)):
        ordered_keys = sorted((-v[col], -v[0], k[1]) for k, v in expected.items())
        for limit in (1, 2, 3, 100, 5000):
            body = _get(q + f"&sort={sort}&limit={limit}").json()
            rows = body["top_fans"]
            assert len(rows) == min(limit, len(expected)), rows
            keys = [(r["account_id"], r["fan_id"]) for r in rows]
            assert len(keys) == len(set(keys)), rows
            assert all(tuple(r[f] for f in fields) == expected[k] for k, r in zip(keys, rows)), rows
            assert [(-r[fields[col]], -r["total_cents"], r["fan_id"]) for r in rows] == ordered_keys[:limit], rows
            # Existing order deliberately leaves account ties unspecified, including cutoff ties.
            assert sum(t["fans"] for t in body["traffic"]) == len(expected), body
            assert sum(t["total_cents"] for t in body["traffic"]) == sum(v[0] for v in expected.values()), body
            assert [t["total_cents"] for t in body["traffic"]] == sorted(
                [t["total_cents"] for t in body["traffic"]], reverse=True), body
        rows = list(csv.DictReader(io.StringIO(_get(q + f"&sort={sort}&format=csv&limit=1").text)))
        assert len(rows) == len(expected), rows
        assert {(r["account_id"], int(r["fan_id"])): tuple(int(r[f]) for f in fields) for r in rows} == expected
    empty = _get(f"/admin/stats/fan-report?account_id={a},{b}&from=2027-01-01&to=2027-01-02").json()
    assert empty == {"top_fans": [], "traffic": [], "growth": []}, empty


_harness.run()
