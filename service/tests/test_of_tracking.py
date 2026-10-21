#!/usr/bin/env python3
"""OnlyFans-native tracking links (/campaigns). OF is faked — no network.

Locks the contract verified LIVE on 2026-07-23 (Ava):
  • The share URL is built as onlyfans.com/<username>/c<campaignCode> — the API
    never returns a URL; OF's own Copy-link builds exactly this, so
    url_verified rides as True.
  • CREATE body field is `name` (sending `campaignName` 400s "Name is
    required"), while the LIST response spells it `campaignName`. The fake
    enforces that asymmetry so a regression to campaignName fails here.
  • create -> list -> delete round-trips; a deleted campaign stays in the list
    with is_deleted:true and its counts (OF keeps it behind with_deleted=1;
    the UI shows it as Infloww's "Deactivated").
  • countTransitions = clicks, countSubscribers = subs (the whole point).
  • /campaigns pages ({list, hasMore}); the list reads every page.

  case_url_is_built_from_username_and_code
  case_create_uses_name_field_not_campaignname
  case_create_list_delete_round_trip
  case_stats_map_clicks_and_subs
  case_of_unavailable_is_not_a_500
  case_list_pages_through_has_more
  case_deleted_rows_come_back_flagged_with_counts
  case_earnings_sum_claimers_spend_per_link
  case_earnings_exclude_refunds_and_pre_created_and_post_end
  case_earnings_net_vs_gross_and_kind_buckets
  case_fan_claimed_by_two_links_splits_spend_by_time
  case_claimers_page_and_cache_until_subs_move
  case_claimers_error_marks_only_that_link
  case_earnings_of_down_is_unavailable_not_500
  case_fans_endpoint_details_rows
  case_link_without_created_at_has_no_earnings
  case_net_missing_is_counted_not_imputed
  case_bad_later_campaigns_page_is_unavailable_not_partial

Run: ./venv/bin/python service/tests/test_of_tracking.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

import automation_executor as ax  # noqa: E402
import of_tracking_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Transaction  # noqa: E402

_client = _harness.make_client()

_AID = "of_track_acct"  # assert_account_owned is a no-op for unauthed test calls


class FakeOF:
    """OF /campaigns + /users/me, live-accurate."""

    def __init__(self, username="testcreator", page_cap=10):
        self._username = username
        self._page_cap = page_cap        # OF answers at most this many per page
        self.calls: list[dict] = []
        self.claimers: dict[int, list[int]] = {}   # campaign id -> fan ids
        self.claimer_calls: list[tuple[int, int, int]] = []
        self.claimers_fail: set[int] = set()
        self._code = 4
        self.store: dict[int, dict] = {}
        self._next_id = 3_600_000

    def me(self):
        return {"id": 999, "username": self._username}

    def seed(self, *, name, clicks=0, subs=0, created_at=None, fans=None):
        self._code += 1
        cid = self._next_id
        self._next_id += 1
        if fans is not None:
            self.claimers[cid] = list(fans)
            subs = subs or len(fans)
        self.store[cid] = {"id": cid, "campaignCode": self._code, "campaignName": name,
                           "countTransitions": clicks, "countSubscribers": subs,
                           "createdAt": created_at, "endDate": None, "isDeleted": False}
        return cid

    def campaign_claimers(self, campaign_id, *, limit=10, offset=0, query=None):
        # OF's user-list shape: {list:[user], hasMore}, no money, capped per page.
        self.claimer_calls.append((campaign_id, limit, offset))
        if campaign_id in self.claimers_fail:
            raise RuntimeError("429 Too Many Requests")
        ids = self.claimers.get(campaign_id, [])
        n = min(limit, self._page_cap)
        page = ids[offset:offset + n]
        return {"list": [{"id": i, "name": f"Fan {i}", "username": f"u{i}"} for i in page],
                "hasMore": offset + len(page) < len(ids), "marker": 1792340782}

    def tracking_links(self, *, limit=None, offset=0, with_deleted=False):
        # OF's paged shape, campaignName spelling; deleted ones only on request.
        self.calls.append({"limit": limit, "offset": offset, "with_deleted": with_deleted})
        rows = [c for c in self.store.values() if with_deleted or not c["isDeleted"]]
        n = min(limit or self._page_cap, self._page_cap)
        page = rows[offset:offset + n]
        return {"list": page, "hasMore": offset + len(page) < len(rows)}

    def create_tracking_link(self, *, name, code=None):
        # NOTE: the `name` vs `campaignName` JSON-body bug lives INSIDE the real
        # of_client.create_tracking_link, which this fake replaces wholesale — so
        # that specific bug is covered by the LIVE round-trip, not this test.
        # Here we only assert the route hands the value through intact.
        if not name:
            raise RuntimeError('400 {"error":{"message":"Name is required"}}')
        self._code += 1
        cid = self._next_id
        self._next_id += 1
        item = {"id": cid, "campaignCode": self._code, "campaignName": name,
                "countTransitions": 0, "countSubscribers": 0,
                "createdAt": None, "endDate": None, "isDeleted": False}
        self.store[cid] = item
        return item

    def delete_tracking_link(self, campaign_id):
        # OF keeps a deleted campaign, its counts and an endDate, behind with_deleted=1.
        c = self.store.get(int(campaign_id))
        if c:
            c.update(isDeleted=True, endDate="2026-10-18 12:00:00")
        return {"success": True}


def _use(fake):
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    _fresh()
    return fake


def _fresh():
    """Forget every cache: claimers, recent failures and the per-account memo."""
    of_tracking_api._CLAIMERS_CACHE.clear()
    of_tracking_api._CLAIMERS_FAILED.clear()
    of_tracking_api._COMPUTED.clear()


of_tracking_api._CLAIMERS_PAGE_SLEEP_S = 0


# ── Earnings: a fresh Creator per case so ledgers never mix ──

_n_acct = 0


def _acct() -> str:
    global _n_acct
    _n_acct += 1
    aid = f"of_track_earn_{_n_acct}"

    async def go():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=aid))
    asyncio.run(go())
    return aid


def _tx(aid, fan, kind, cents, when, *, net=None, status="cleared"):
    async def go():
        async with get_session() as s:
            s.add(Transaction(account_id=aid, fan_id=fan, kind=kind, amount_cents=cents,
                              net_cents=net if net is not None else cents * 8 // 10,
                              occurred_at=datetime.fromisoformat(when), status=status,
                              currency="USD", source="ledger"))
    asyncio.run(go())


def _earnings(aid):
    r = _client.get(f"/admin/of-tracking-links/earnings?account_id={aid}")
    assert r.status_code == 200, r.text
    d = r.json()
    return d, {l["id"]: l for l in d["links"]}


def _list():
    r = _client.get(f"/admin/of-tracking-links?account_id={_AID}")
    assert r.status_code == 200, r.text
    return r.json()


def case_url_is_built_from_username_and_code():
    f = _use(FakeOF(username="peerava"))
    f.seed(name="IG main")           # gets code 5
    d = _list()
    assert d["username"] == "peerava", d
    # OF's own Copy-link builds onlyfans.com/<username>/c<campaignCode> (statistics-reach-campaigns.js copyLink).
    assert d["url_verified"] is True, d
    row = d["links"][0]
    assert row["url"] == f"https://onlyfans.com/peerava/c{row['code']}", row


def case_create_uses_name_field_not_campaignname():
    _use(FakeOF())
    r = _client.post("/admin/of-tracking-links", json={"account_id": _AID, "name": "Reddit"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Reddit", body
    assert body["url"] and body["url"].endswith(f"/c{body['code']}"), body
    # empty name is rejected before touching OF
    bad = _client.post("/admin/of-tracking-links", json={"account_id": _AID, "name": "  "})
    assert bad.status_code == 422, bad.text


def case_create_list_delete_round_trip():
    _use(FakeOF())
    made = _client.post("/admin/of-tracking-links",
                        json={"account_id": _AID, "name": "TikTok"}).json()
    cid = made["id"]
    assert cid is not None, made
    assert "TikTok" in {l["name"] for l in _list()["links"]}

    d = _client.delete(f"/admin/of-tracking-links/{cid}?account_id={_AID}")
    assert d.status_code == 200 and d.json()["deleted"] == cid, d.text
    row = next(l for l in _list()["links"] if l["name"] == "TikTok")
    assert row["is_deleted"] is True, row


def case_stats_map_clicks_and_subs():
    f = _use(FakeOF())
    f.seed(name="shoutout", clicks=42, subs=7)
    row = next(l for l in _list()["links"] if l["name"] == "shoutout")
    assert row["clicks"] == 42 and row["subscribers"] == 7, row


def case_of_unavailable_is_not_a_500():
    class Boom:
        def me(self): raise RuntimeError("no session")
        def tracking_links(self, **_kw): raise RuntimeError("no session")
    ax._make_client = lambda account_id: Boom()  # type: ignore[attr-defined]
    d = _list()
    assert d["of_available"] is False and d["links"] == [], d


def case_list_pages_through_has_more():
    # OF caps each page (10 here); 23 links must all come back, none twice.
    f = _use(FakeOF(page_cap=10))
    for i in range(23):
        f.seed(name=f"L{i}", clicks=i)
    links = _list()["links"]
    assert [l["name"] for l in links] == [f"L{i}" for i in range(23)], [l["name"] for l in links]
    assert [c["offset"] for c in f.calls] == [0, 10, 20], f.calls
    assert all(c["with_deleted"] and c["limit"] for c in f.calls), f.calls


def case_deleted_rows_come_back_flagged_with_counts():
    f = _use(FakeOF())
    live = f.seed(name="live", clicks=5, subs=1)
    gone = f.seed(name="gone", clicks=9, subs=2)
    f.store[gone].update(isDeleted=True, endDate="2026-09-21 03:01:31")
    by = {l["id"]: l for l in _list()["links"]}
    assert by[live]["is_deleted"] is False, by
    assert by[gone]["is_deleted"] is True and by[gone]["clicks"] == 9 and by[gone]["subscribers"] == 2, by
    assert by[gone]["end_date"] == "2026-09-21 03:01:31", by



def case_earnings_sum_claimers_spend_per_link():
    aid = _acct()
    f = _use(FakeOF())
    a = f.seed(name="IG", clicks=10, created_at="2026-09-01T00:00:00+00:00", fans=[1, 2])
    b = f.seed(name="TikTok", clicks=5, created_at="2026-09-02T00:00:00+00:00", fans=[3])
    z = f.seed(name="empty", clicks=3, created_at="2026-09-03T00:00:00+00:00")
    _tx(aid, 1, "ppv_message", 1000, "2026-09-10T10:00:00")
    _tx(aid, 2, "tip", 500, "2026-09-11T10:00:00")
    _tx(aid, 3, "ppv_post", 700, "2026-09-12T10:00:00")
    _tx(aid, 99, "tip", 9999, "2026-09-12T10:00:00")   # not a claimer of any link
    d, by = _earnings(aid)
    assert d["available"] is True, d
    assert by[a]["earnings_cents"] == 1500 and by[a]["fans_who_spent"] == 2 and by[a]["fans_counted"] == 2, by[a]
    assert by[b]["earnings_cents"] == 700 and by[b]["fans_who_spent"] == 1, by[b]
    assert by[z]["earnings_cents"] == 0 and by[z]["fans_who_spent"] == 0, by[z]
    # zero subscribers costs no claimers call
    assert z not in {c[0] for c in f.claimer_calls}, f.claimer_calls


def case_earnings_exclude_refunds_and_pre_created_and_post_end():
    aid = _acct()
    f = _use(FakeOF())
    a = f.seed(name="IG", created_at="2026-09-05T12:00:00+00:00", fans=[1])
    f.store[a].update(isDeleted=True, endDate="2026-09-20 00:00:00")
    _tx(aid, 1, "tip", 100, "2026-09-05T11:59:59")                       # before the link existed
    _tx(aid, 1, "tip", 200, "2026-09-06T00:00:00")                       # counted
    _tx(aid, 1, "tip", 400, "2026-09-07T00:00:00", status="refunded")
    _tx(aid, 1, "tip", 800, "2026-09-07T00:00:00", status="chargedback")
    _tx(aid, 1, "tip", 1600, "2026-09-07T00:00:00", status="failed")
    _tx(aid, 1, "tip", 3200, "2026-09-08T00:00:00", status="pending")    # pending is revenue (stats.py)
    _tx(aid, 1, "tip", 6400, "2026-09-21T00:00:00")                      # after it was deactivated
    _d, by = _earnings(aid)
    assert by[a]["earnings_cents"] == 3400, by[a]


def case_earnings_net_vs_gross_and_kind_buckets():
    aid = _acct()
    f = _use(FakeOF())
    a = f.seed(name="IG", created_at="2026-09-01T00:00:00+00:00", fans=[1, 2])
    _tx(aid, 1, "subscription", 1000, "2026-09-02T00:00:00", net=800)
    _tx(aid, 1, "rebill", 1000, "2026-10-02T00:00:00", net=800)
    _tx(aid, 1, "ppv_message", 2000, "2026-09-03T00:00:00", net=1600)
    _tx(aid, 1, "ppv_post", 300, "2026-09-03T00:00:00", net=240)
    _tx(aid, 1, "ppv_stream", 400, "2026-09-03T00:00:00", net=320)
    _tx(aid, 1, "tip_post", 500, "2026-09-03T00:00:00", net=400)
    _tx(aid, 2, "subscription", 1000, "2026-09-02T00:00:00", net=777)   # subs only: not a "fan who spent"
    _d, by = _earnings(aid)
    assert by[a]["earnings_cents"] == 6200 and by[a]["earnings_net_cents"] == 4937, by[a]
    assert by[a]["fans_who_spent"] == 1, by[a]
    fans = {r["fan_id"]: r for r in _client.get(
        f"/admin/of-tracking-links/{a}/fans?account_id={aid}").json()["fans"]}
    one = fans[1]
    assert (one["subs_cents"], one["messages_cents"], one["posts_cents"], one["streams_cents"], one["tips_cents"]) \
        == (2000, 2000, 300, 400, 500), one
    assert one["subs_net_cents"] == 1600 and one["total_net_cents"] == 4160, one
    assert one["total_cents"] == 5200 and one["other_cents"] == 0, one


def case_fan_claimed_by_two_links_splits_spend_by_time():
    # Fan 1 came via A (Aug 1) and B (Sep 1, deactivated Oct 1). Each tx goes to the newest claiming link open at its
    # time: Aug 15 is before B existed -> A; Sep 15 -> B; Oct 15 is after B ended -> back to A. Fan 2: A only.
    aid = _acct()
    f = _use(FakeOF())
    a = f.seed(name="A", created_at="2026-08-01T00:00:00+00:00", fans=[1, 2])
    b = f.seed(name="B", created_at="2026-09-01T00:00:00+00:00", fans=[1])
    f.store[b].update(isDeleted=True, endDate="2026-10-01 00:00:00")
    _tx(aid, 1, "tip", 500, "2026-08-15T00:00:00")
    _tx(aid, 1, "tip", 1000, "2026-09-15T00:00:00")
    _tx(aid, 1, "tip", 2000, "2026-10-15T00:00:00")
    _tx(aid, 2, "tip", 300, "2026-09-15T00:00:00")
    _d, by = _earnings(aid)
    assert by[a]["earnings_cents"] == 2800 and by[a]["fans_counted"] == 2, by[a]
    assert by[b]["earnings_cents"] == 1000 and by[b]["fans_counted"] == 1, by[b]

    def rows(cid):
        return {r["fan_id"]: r for r in _client.get(
            f"/admin/of-tracking-links/{cid}/fans?account_id={aid}").json()["fans"]}
    ra, rb = rows(a), rows(b)
    assert ra[1]["total_cents"] == 2500 and ra[1]["also_claimed_by"] == [b], ra[1]
    assert ra[2]["total_cents"] == 300 and ra[2]["also_claimed_by"] == [], ra[2]
    assert rb[1]["total_cents"] == 1000 and rb[1]["also_claimed_by"] == [a], rb[1]
    # Details rows add up to each link's Earnings.
    assert sum(r["total_cents"] for r in ra.values()) == by[a]["earnings_cents"]
    assert sum(r["total_cents"] for r in rb.values()) == by[b]["earnings_cents"]


def case_claimers_page_and_cache_until_subs_move():
    aid = _acct()
    f = _use(FakeOF(page_cap=10))
    a = f.seed(name="big", created_at="2026-09-01T00:00:00+00:00", fans=list(range(1, 24)))
    for fid in range(1, 24):
        _tx(aid, fid, "tip", 100, "2026-09-02T00:00:00")
    _d, by = _earnings(aid)
    assert by[a]["fans_counted"] == 23 and by[a]["earnings_cents"] == 2300, by[a]
    assert [c[2] for c in f.claimer_calls] == [0, 10, 20], f.claimer_calls
    list_calls = len(f.calls)
    _earnings(aid)
    assert len(f.claimer_calls) == 3, "a second read within the TTL must come from cache"
    assert len(f.calls) == list_calls, "within the memo's TTL /campaigns is not re-read either"
    of_tracking_api._COMPUTED.clear()   # the 60 s memo lapses
    _earnings(aid)
    assert len(f.claimer_calls) == 3 and len(f.calls) > list_calls, "claimers still cached past the memo"
    of_tracking_api._COMPUTED.clear()
    f.claimers[a].append(24)
    f.store[a]["countSubscribers"] = 24
    _tx(aid, 24, "tip", 100, "2026-09-02T00:00:00")
    _d, by = _earnings(aid)
    assert by[a]["fans_counted"] == 24 and len(f.claimer_calls) == 6, (by[a], f.claimer_calls)


def case_claimers_error_marks_only_that_link():
    aid = _acct()
    f = _use(FakeOF())
    ok = f.seed(name="ok", created_at="2026-09-01T00:00:00+00:00", fans=[1])
    bad = f.seed(name="bad", created_at="2026-09-01T00:00:00+00:00", fans=[2])
    f.claimers_fail.add(bad)
    _tx(aid, 1, "tip", 100, "2026-09-02T00:00:00")
    d, by = _earnings(aid)
    assert d["available"] is True and by[ok]["earnings_cents"] == 100, by
    assert by[bad]["earnings_cents"] is None and by[bad]["fans_who_spent"] is None, by[bad]
    r = _client.get(f"/admin/of-tracking-links/{bad}/fans?account_id={aid}")
    assert r.status_code == 502, r.text
    # The failure is remembered: past the memo, OF is not asked about that link again for a while.
    calls = [c for c in f.claimer_calls if c[0] == bad]
    of_tracking_api._COMPUTED.clear()
    _d, by = _earnings(aid)
    assert by[bad]["earnings_cents"] is None and [c for c in f.claimer_calls if c[0] == bad] == calls, f.claimer_calls


def case_earnings_of_down_is_unavailable_not_500():
    class Boom:
        def me(self): raise RuntimeError("no session")
        def tracking_links(self, **_kw): raise RuntimeError("no session")
    ax._make_client = lambda account_id: Boom()  # type: ignore[attr-defined]
    d, _by = _earnings(_acct())
    assert d == {"available": False, "links": []}, d


def case_fans_endpoint_details_rows():
    aid = _acct()
    f = _use(FakeOF())
    a = f.seed(name="IG", created_at="2026-09-01T00:00:00+00:00", fans=[1, 2, 3])
    _tx(aid, 2, "tip", 900, "2026-09-02T00:00:00")
    _tx(aid, 3, "ppv_message", 400, "2026-09-02T00:00:00")
    r = _client.get(f"/admin/of-tracking-links/{a}/fans?account_id={aid}")
    assert r.status_code == 200, r.text
    rows = r.json()["fans"]
    assert [x["fan_id"] for x in rows] == [2, 3, 1], rows          # most spent first; a $0 fan still listed
    assert rows[0]["name"] == "Fan 2" and rows[0]["username"] == "u2", rows[0]
    # The honest window: the link was created Sep 1, but the ledger only starts Sep 2.
    assert r.json()["counted_from"] == "2026-09-02T00:00:00Z", r.json()["counted_from"]
    assert _client.get(f"/admin/of-tracking-links/424242/fans?account_id={aid}").status_code == 404


def case_link_without_created_at_has_no_earnings():
    aid = _acct()
    f = _use(FakeOF())
    a = f.seed(name="undated", created_at=None, fans=[1])
    _tx(aid, 1, "tip", 100, "2026-09-02T00:00:00")
    _d, by = _earnings(aid)
    assert by[a]["earnings_cents"] is None, by[a]       # "—", never all-time spend
    assert not f.claimer_calls, f.claimer_calls


def case_net_missing_is_counted_not_imputed():
    aid = _acct()
    f = _use(FakeOF())
    a = f.seed(name="IG", created_at="2026-09-01T00:00:00+00:00", fans=[1])
    _tx(aid, 1, "tip", 1000, "2026-09-02T00:00:00", net=800)

    async def go():
        async with get_session() as s:
            s.add(Transaction(account_id=aid, fan_id=1, kind="tip", amount_cents=500, net_cents=None,
                              occurred_at=datetime.fromisoformat("2026-09-03T00:00:00"), status="cleared",
                              currency="USD", source="ws"))
    asyncio.run(go())
    _d, by = _earnings(aid)
    assert by[a]["earnings_cents"] == 1500 and by[a]["earnings_net_cents"] == 800, by[a]
    assert by[a]["net_missing_count"] == 1, by[a]


def case_bad_later_campaigns_page_is_unavailable_not_partial():
    f = _use(FakeOF(page_cap=10))
    for i in range(15):
        f.seed(name=f"L{i}")
    real = f.tracking_links

    def flaky(*, limit=None, offset=0, with_deleted=False):
        return {"error": "rate limited"} if offset else real(limit=limit, offset=offset, with_deleted=with_deleted)
    f.tracking_links = flaky
    d = _list()
    assert d["of_available"] is False and d["links"] == [], d


_harness.run(
    case_url_is_built_from_username_and_code,
    case_create_uses_name_field_not_campaignname,
    case_create_list_delete_round_trip,
    case_stats_map_clicks_and_subs,
    case_of_unavailable_is_not_a_500,
    case_list_pages_through_has_more,
    case_deleted_rows_come_back_flagged_with_counts,
    case_earnings_sum_claimers_spend_per_link,
    case_earnings_exclude_refunds_and_pre_created_and_post_end,
    case_earnings_net_vs_gross_and_kind_buckets,
    case_fan_claimed_by_two_links_splits_spend_by_time,
    case_claimers_page_and_cache_until_subs_move,
    case_claimers_error_marks_only_that_link,
    case_earnings_of_down_is_unavailable_not_500,
    case_fans_endpoint_details_rows,
    case_link_without_created_at_has_no_earnings,
    case_net_missing_is_counted_not_imputed,
    case_bad_later_campaigns_page_is_unavailable_not_partial,
)
