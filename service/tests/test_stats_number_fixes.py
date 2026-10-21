#!/usr/bin/env python3
"""The wrong numbers roadmap Safety S4, S5, S6 and S8 name, the batch revenue read (W2 2.8), and Employee
reports' rollup read (W2 2.1, 2.2).

  S4   Messages sent (Creator reports and Employee reports) counts an Employee's own sends only: no message of
       a mass message (`mass_run_id`), none an automation sent (`automation_kind`), none stamped with the
       Automation sentinel Employee, no inbound one.
  S5   Active subs is counted as of the window's end, not now: a fan whose subscription ended after the window
       counts, one who subscribed after it does not.
  S6   New subs counts the fans whose subscription began in the window, free and trial ones too: those leave no
       sale, so OF's own roster (`subscriber_snapshot.subscribe_at`) supplies them, each fan once.
  S8   A day bucket follows the report zone's offset at each sale's hour, so the days either side of a
       daylight-saving change each keep their own sales; a zone whose offset is not a whole hour is cut by
       the minute.
  2.8  `/admin/stats/revenue?account_id=a,b` answers the sum of the two single reads in one call, and one id
       outside the caller's Creators is 403.
  2.1  Employee reports sum the hourly rollup (`credited_sales(grouped=True)`); its figures equal the per-sale
       read's under every Sales Settings rule.

Each case was red before its fix (S4 counted 6 sends, S5 counted the fans active today, S6 missed the free
sub, S8 put the 23:30 EST sale on the next day, 2.8 refused the comma list 403). Seeded straight
into the temp DB; no network.

Run: ./venv/bin/python service/tests/test_stats_number_fixes.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import datetime  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
from _clock_fixtures import IDS, employee as _employee  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, Fan, SubscriberSnapshot, Transaction, UserAccount  # noqa: E402
from sales_attribution import credited_sales  # noqa: E402

ENGINE = sa.create_engine(os.environ["CHATTERLY_DB_URL"])  # no FK pragma: a mass_run_id needs no mass run
OWNER_A = fx.login_owner("agency_a_owner")


def _creator(aid: str) -> str:
    async def _seed():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=f"nf_creator_{aid[-2:]}", color="#aaaaaa"))
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


def _sentinel() -> int:
    async def _seed():
        async with get_session() as s:
            row = Employee(display_name="Automation", is_active=False)
            s.add(row)
            await s.flush()
            return row.id
    return asyncio.run(_seed())


_mid = iter(range(60_000_001, 60_100_000))


def _message(aid: str, fan: int, sender: int | None, at: datetime, direction: str = "out",
             mass_run_id: int | None = None, automation_kind: str | None = None) -> int:
    mid = next(_mid)
    with ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO messages (account_id, fan_id, message_id, direction, sender_name, body, media_ids, "
            "media_count, price_cents, is_tip, is_unsent, is_promise, sent_by_employee_id, mass_run_id, "
            "automation_kind, created_at, ingested_at) VALUES (:a, :f, :m, :d, '', 'x', '[]', 0, 0, 0, 0, 0, "
            ":e, :r, :k, :c, :c)"),
            {"a": aid, "f": fan, "m": mid, "d": direction, "e": sender, "r": mass_run_id, "k": automation_kind,
             "c": at.strftime("%Y-%m-%d %H:%M:%S.%f")})
    return mid


def _sale(aid: str, kind: str, cents: int, at: datetime, fan: int | None = 1, message_id: int | None = None,
          status: str = "cleared", manual: int | None = None) -> None:
    _add(Transaction(account_id=aid, fan_id=fan, kind=kind, message_id=message_id, amount_cents=cents,
                     occurred_at=at, status=status, currency="USD", source="ledger", attributed_employee_id=manual))


def _get(path: str, status: int = 200) -> dict:
    r = OWNER_A.get(path)
    assert r.status_code == status, f"{path}: {r.status_code} {r.text}"
    return r.json() if status == 200 else {}


def _model(body: dict, aid: str) -> dict:
    return next(m for m in body["per_model"] if m["account_id"] == aid)


C1, C2, C3 = _creator("5100001"), _creator("5100002"), _creator("5100003")
E1, E2 = _employee("nf_emp_1"), _employee("nf_emp_2")
AUTO = _sentinel()


def case_s4_messages_sent_counts_only_an_employees_own_sends():
    at = datetime(2026, 2, 10, 12, 0)
    _message(C1, 1, E1, at)
    _message(C1, 2, E1, at)
    _message(C1, 3, E1, at, mass_run_id=777)                      # one recipient of a mass message
    _message(C1, 4, E1, at, automation_kind="welcome_new_sub")    # an automation's send credited to E1
    _message(C1, 5, AUTO, at)                                     # the Automation sentinel's
    _message(C1, 6, None, at, direction="in")
    _message(C1, 7, E2, at)
    window = "from=2026-02-10&to=2026-02-10"
    assert _model(_get(f"/admin/stats/per-model?{window}"), C1)["messages_sent"] == 3
    sent = {e["employee_id"]: e["messages_sent"] for e in _get(f"/admin/stats/per-employee?{window}")["employees"]}
    assert (sent.get(E1), sent.get(E2), sent.get(AUTO, 0)) == (2, 1, 0), sent


def case_s5_active_subs_are_counted_as_of_the_windows_end():
    _add(Fan(account_id=C2, fan_id=1, subscribed_at=datetime(2026, 1, 1), subscription_expires_at=datetime(2026, 3, 20)),
         Fan(account_id=C2, fan_id=2, subscribed_at=datetime(2026, 3, 25), subscription_expires_at=datetime(2099, 1, 1)),
         Fan(account_id=C2, fan_id=3, subscription_expires_at=datetime(2099, 1, 1)),
         Fan(account_id=C2, fan_id=4, subscribed_at=datetime(2026, 2, 1), subscription_expires_at=datetime(2026, 3, 31)),
         Fan(account_id=C2, fan_id=5, subscribed_at=datetime(2026, 1, 1), subscription_expires_at=datetime(2026, 3, 1)))
    body = _get("/admin/stats/per-model?from=2026-03-01&to=2026-03-15")
    assert body["active_subs_source"] == "subscription_expires_at", body["active_subs_source"]
    # Fans 1 and 4 were subscribed on 15 March; 2 had not subscribed yet; 5 had lapsed; 3 has no start date.
    assert _model(body, C2)["active_subs_count"] == 3, _model(body, C2)


def case_s6_new_subs_count_free_and_trial_subscribers_once_each():
    in_window = datetime(2026, 4, 10, 9, 0)
    _sale(C3, "subscription", 999, in_window, fan=1)
    _sale(C3, "subscription", 999, in_window, fan=8, status="refunded")
    _add(SubscriberSnapshot(account_id=C3, fan_id=1, subscribe_at=in_window, seen_at=in_window),   # the paid one
         SubscriberSnapshot(account_id=C3, fan_id=2, subscribe_at=datetime(2026, 4, 12), seen_at=in_window),  # free
         SubscriberSnapshot(account_id=C3, fan_id=3, subscribe_at=datetime(2026, 3, 1), seen_at=in_window),   # before
         SubscriberSnapshot(account_id=C3, fan_id=4, subscribe_at=None, seen_at=in_window))
    assert _model(_get("/admin/stats/per-model?from=2026-04-01&to=2026-04-30"), C3)["new_subs_count"] == 2


def case_2_8_one_revenue_call_sums_several_creators_and_refuses_a_foreign_one():
    _sale(C1, "tip", 300, datetime(2026, 5, 2, 10, 0))
    _sale(C1, "ppv_message", 700, datetime(2026, 5, 3, 10, 0))
    _sale(C2, "tip", 1100, datetime(2026, 5, 3, 11, 30), status="pending")
    _sale(C2, "tip", 5000, datetime(2026, 5, 3, 12, 0), status="refunded")
    window = "from=2026-05-01&to=2026-05-31"
    for mode in ("group_by=day&by_kind=true&include_net=true", "group_by=kind"):
        one = _get(f"/admin/stats/revenue?{window}&{mode}&account_id={C1},{C2}")["rows"]
        totals: Counter = Counter()
        for aid in (C1, C2):
            for r in _get(f"/admin/stats/revenue?{window}&{mode}&account_id={aid}")["rows"]:
                totals[r["day"] or r["kind"]] += r["total_cents"]
        assert {r["day"] or r["kind"]: r["total_cents"] for r in one} == dict(totals), (mode, one, totals)
    assert sum(r["total_cents"] for r in _get(f"/admin/stats/revenue?{window}&account_id={C1},{C2}")["rows"]) == 2100
    _get(f"/admin/stats/revenue?{window}&account_id={C1},{IDS['creator_b']}", status=403)


def case_employee_reports_from_the_rollup_equal_the_per_sale_read_under_every_rule():
    m1 = _message(C1, 21, E1, datetime(2026, 6, 1, 8, 0), automation_kind="welcome")
    m2 = _message(C2, 22, E2, datetime(2026, 6, 1, 8, 0))
    _message(C1, 23, E2, datetime(2026, 6, 2, 7, 0))
    _sale(C1, "ppv_message", 1001, datetime(2026, 6, 1, 9, 0, 5), fan=21, message_id=m1)
    _sale(C2, "ppv_message", 2003, datetime(2026, 6, 1, 9, 30), fan=22, message_id=m2)
    _sale(C1, "tip", 333, datetime(2026, 6, 2, 9, 15), fan=23, message_id=None)
    _sale(C1, "tip_post", 77, datetime(2026, 6, 2, 9, 59, 59), fan=24)
    _sale(C2, "custom", 450, datetime(2026, 6, 3, 0, 0), fan=25, manual=E1, status="pending")
    _sale(C2, "subscription", 1200, datetime(2026, 6, 3, 1, 0), fan=26)
    _sale(C2, "rebill", 1200, datetime(2026, 6, 3, 1, 0), fan=27, manual=E2)
    start, end = datetime(2026, 6, 1, 0, 30), datetime(2026, 6, 3, 0, 59, 59)  # partial hours at both edges

    def sums(grouped: bool) -> dict:
        sales, _ = asyncio.run(credited_sales([C1, C2], start, end, grouped=grouped))
        out: Counter = Counter()
        for c in sales:
            out[(c.employee_id, c.account_id, c.kind, "cents")] += c.amount_cents
            out[(c.employee_id, c.account_id, c.kind, "sales")] += c.sales
        return dict(out)

    blobs = ({"attribution": {"messages": "converters", "posts_tips": "converters"}},
             {"exclude_welcome": True, "exclude_of_fee": True,
              "attribution": {"messages": "sender", "posts_tips": "converters", "subscriptions_chatter_opt_in": True}},
             {})
    # Sales Settings are versioned (roadmap W6 6.4): each blob is saved from the start, so it credits every sale
    # in the window; then a second version from mid-window splits it, which credits sale by sale.
    def save(blob: dict, since: str = "1970-01-01T00:00:00Z") -> None:
        r = OWNER_A.put("/admin/settings/sales", json=blob, params={"effective_from": since})
        assert r.status_code == 200, r.text

    try:
        alone = []
        for blob in blobs:
            save(blob)
            assert sums(True) == sums(False), (blob, sums(True), sums(False))
            alone.append(sums(False))
        assert sums(True), "the window holds sales"
        save(blobs[0])
        save(blobs[1], "2026-06-02T00:00:00Z")
        split = sums(False)
        assert sums(True) == split, (sums(True), split)
        assert split not in alone[:2], "the split window reads both versions, not one"
    finally:
        fx.store_blob(IDS["agency_a_owner"], "sales", {})


def case_s8_day_buckets_follow_the_zones_offset_at_each_hour():
    # New York springs forward on 2026-03-08 at 07:00 UTC (EST -5 -> EDT -4).
    _sale(C1, "tip", 1, datetime(2026, 3, 8, 4, 30))    # 2026-03-07 23:30 EST
    _sale(C1, "tip", 10, datetime(2026, 3, 9, 3, 30))   # 2026-03-08 23:30 EDT
    _sale(C1, "tip", 100, datetime(2026, 3, 9, 4, 30))  # 2026-03-09 00:30 EDT
    # Kolkata is UTC+5:30: 18:20 UTC is 23:50 that day, 18:40 UTC is 00:10 the next.
    _sale(C1, "tip", 1000, datetime(2026, 3, 20, 18, 20))
    _sale(C1, "tip", 10000, datetime(2026, 3, 20, 18, 40))

    def days(zone: str, window: str) -> dict:
        assert OWNER_A.put("/admin/settings/preferences", json={"report_tz": zone}).status_code == 200
        rows = _get(f"/admin/stats/revenue?account_id={C1}&{window}&group_by=day&by_kind=true")["rows"]
        assert all(sum(k["total_cents"] for k in r["by_kind"]) == r["total_cents"] for r in rows), rows
        return {r["day"]: r["total_cents"] for r in rows}

    try:
        assert days("America/New_York", "from=2026-03-07&to=2026-03-09") == \
            {"2026-03-07": 1, "2026-03-08": 10, "2026-03-09": 100}
        assert days("Asia/Kolkata", "from=2026-03-20&to=2026-03-21") == {"2026-03-20": 1000, "2026-03-21": 10000}
    finally:
        OWNER_A.put("/admin/settings/preferences", json={})


_harness.run()
