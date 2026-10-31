#!/usr/bin/env python3
"""Fan reports (roadmap W5 5.6): `/admin/stats/fan-report` over a window, per Creator.

  top     each fan's window spend split into tips / PPV / subscriptions, pending counted, a refund not, ranked
          by the asked metric; net is OF's net, else 80% of gross (net_or_80); the fan's name and his roster
          subscription start ride along.
  csv     `format=csv` streams the whole ranking (`limit` aside) with FAN_REPORT_FIELDS as the header, under the
          shared CSV cap.
  traffic the window's spend by the trial link or promotion each spender claimed (his earliest claim by OF's
          subscribe_at, else first sighting), named by the trial mirror and the promotion's campaign (through
          link_meta.campaign_id); the rest as no link.
  growth  new fans per report-zone day (a subscription sale or the roster's subscribe_at, each fan once) and
          renewed fans (a rebill).
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
    Account, Fan, LinkClaimer, LinkMeta, PromoCampaign, SubscriberSnapshot, Transaction, TrialLinkMirror,
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


C1, C2, C3, C4 = _creator("5600001"), _creator("5600002"), _creator("5600003"), _creator("5600004")
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


def case_another_agencys_creator_is_refused():
    _get(f"/admin/stats/fan-report?account_id={IDS['creator_b']}", status=403)


_harness.run()
