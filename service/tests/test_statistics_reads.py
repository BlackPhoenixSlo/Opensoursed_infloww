#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import of_client  # noqa: E402
import server  # noqa: E402

API = of_client.API_BASE
FIX = json.loads((Path(__file__).parent / "fixtures" / "of_statistics_reads.json").read_text())
S, E = "2026-10-01 00:00:00", "2026-10-16 23:59:59"
RANGE = {"start": S, "end": E}
OF_RANGE = {"startDate": S, "endDate": E}

IDS = fx.seed_two_agencies()
http = fx.login_owner("agency_a_owner")
http.headers["X-Account-Id"] = IDS["creator_a"]


def _reply(key, params=None):
    for name in ("format", "filter[]"):
        v = (params or {}).get(name)
        v = v[0] if isinstance(v, list) else v
        if f"{key}?{name.rstrip('[]')}={v}" in FIX:
            return FIX[f"{key}?{name.rstrip('[]')}={v}"]
    return FIX[key]


def _fake():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.sent = []

    def get_json(path, params=None):
        c.sent.append((path, params))
        return _reply(path[len(API):], params)
    c.get_json = get_json
    return c


def _get(url, params=None):
    c = _fake()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        r = http.get(url, params=params)
    finally:
        server._get_client = orig
    return r.status_code, (r.json() if r.content else None), c.sent


def _one(url, params, of_path, of_params):
    status, body, sent = _get(url, params)
    assert status == 200, (url, status, body)
    assert sent == [(f"{API}{of_path}", of_params)], sent
    assert body == _reply(of_path, of_params), body
    return body



def case_earnings_chart_names_its_series():
    body = _one("/api/of/v2/earnings/chart", {**RANGE, "filter": "tips_count,tips_amount"},
                "/earnings/chart",
                {**OF_RANGE, "withTotal": "true",
                 "filter[tips_count]": "tips_count", "filter[tips_amount]": "tips_amount"})
    assert set(body) == {"tips"} and set(body["tips"]) == {"chartCount", "chartAmount", "total", "gross", "delta"}


def case_earnings_chart_monthly_total_is_alone():
    status, _, sent = _get("/api/of/v2/earnings/chart", {"monthlyTotal": 1})
    assert status == 200 and sent == [(f"{API}/earnings/chart", {"monthlyTotal": 1})], sent


def case_earnings_chart_rejects_junk_filter():
    status, _, sent = _get("/api/of/v2/earnings/chart", {"filter": "tips]&x=[1"})
    assert status == 422 and sent == [], (status, sent)


def case_earnings_chart_without_filter_is_unchanged():
    status, _, sent = _get("/api/of/v2/earnings/chart", RANGE)
    assert status == 200 and sent == [(f"{API}/earnings/chart", {**OF_RANGE, "withTotal": "true"})], sent


def case_posts_chart_by_adds_the_chip_series():
    _one("/api/of/v2/posts/chart", {**RANGE, "by": "views"}, "/posts/chart",
         {**OF_RANGE, "withTotal": "true", "filter[views]": "views", "filter[posts]": "posts"})



def case_chargebacks_list():
    body = _one("/api/of/v2/payouts/chargebacks", {**RANGE, "offset": 10, "marker": "1791000000"},
                "/payouts/chargebacks",
                {"limit": 10, "offset": 10, "marker": "1791000000", **OF_RANGE})
    assert body["list"][0]["payment"]["net"] == 4
    assert set(body) == {"list", "marker"}, body


def case_referred_creators_and_users():
    _one("/api/of/v2/users/me/referrals", {**RANGE, "onlyPerformers": 1}, "/users/me/referrals",
         {**OF_RANGE, "offset": 0, "onlyPerformers": 1})
    _one("/api/of/v2/users/me/referrals", RANGE, "/users/me/referrals",
         {**OF_RANGE, "offset": 0, "onlyPerformers": 0})



def case_top_highlights():
    keys = {"message": {"purchases"}, "stream": {"purchases", "tips", "views", "likes", "comments"},
            "story": {"tips", "views", "likes", "comments"},
            "fan": {"total", "subscriptions", "tips", "messages", "streams"}}
    for kind, want in keys.items():
        body = _one(f"/api/of/v2/users/me/stats/top/{kind}", RANGE, f"/users/me/stats/top/{kind}", OF_RANGE)
        assert set(body) == want, (kind, body)


def case_top_unknown_kind_is_404_and_post_keeps_its_route():
    status, _, sent = _get("/api/of/v2/users/me/stats/top/secret", RANGE)
    assert status == 404 and sent == [], (status, sent)
    c = _fake()
    c.get_json = lambda path, params=None: c.sent.append((path, params)) or {}
    orig = server._get_client
    server._get_client = lambda: c
    try:
        assert http.get("/api/of/v2/users/me/stats/top/post", params=RANGE).status_code == 200
    finally:
        server._get_client = orig
    assert c.sent[0][1].get("skip_users") == "all", c.sent


def case_streaks():
    row = {"id", "startDate", "endDate", "isActive", "postsCount", "daysCount", "streamsDuration",
           "storiesCount", "chatsCount", "frozenDays"}
    body = _one("/api/of/v2/streaks", RANGE, "/streaks", OF_RANGE)
    assert set(body) == {"list", "hasMore"} and set(body["list"][0]) == row, body
    assert set(_one("/api/of/v2/streaks/top", None, "/streaks/top", None)) == row
    body = _one("/api/of/v2/users/me/stats/today-activity", None, "/users/me/stats/today-activity", None)
    assert set(body) == {"stories", "posts", "chats", "streams"}, body



def case_direct_messages_and_search():
    q = {"startDate": S, "endDate": E, "limit": 10, "offset": 10, "query": "synthetic"}
    _one("/api/of/v2/users/me/stats/messages/direct", q, "/users/me/stats/messages/direct",
         {"startDate": S, "endDate": E, "limit": 10, "offset": 10, "query": "synthetic"})


def case_mass_messages_search_passes_query():
    q = {"startDate": S, "endDate": E, "limit": 50, "query": "synthetic"}
    _one("/api/of/v2/users/me/stats/messages/group", q, "/users/me/stats/messages/group",
         {"startDate": S, "endDate": E, "limit": 50, "offset": 0, "query": "synthetic"})
    status, _, sent = _get("/api/of/v2/users/me/stats/messages/group", {"startDate": S, "endDate": E})
    assert status == 200 and sent == [(f"{API}/users/me/stats/messages/group",
                                       {"startDate": S, "endDate": E, "limit": 50, "offset": 0})], sent


def case_messages_chart_per_tab():
    body = _one("/api/of/v2/messages/queue/chart", {**RANGE, "type": "direct"}, "/messages/queue/chart",
         {**OF_RANGE, "withTotal": "true",
          "filter[direct_messages]": "direct_messages",
          "filter[direct_messages_purchases]": "direct_messages_purchases"})
    for key in ("direct_messages", "direct_messages_purchases"):
        assert set(body[key]) == {"chart", "total", "delta"}, body


def case_mass_message_buyers():
    _one("/api/of/v2/messages/queue/buyers", {"queue_id": 56001}, "/messages/queue/56001/buyers",
         {"limit": 10, "offset": 0, "skip_users_dups": 1})
    _one("/api/of/v2/messages/queue/buyers",
         {"queue_id": 56001, "skip_users": "all", "offset": 10, "marker": "m1"},
         "/messages/queue/56001/buyers", {"limit": 10, "offset": 10, "skip_users": "all", "marker": "m1"})
    status, _, sent = _get("/api/of/v2/messages/queue/buyers")
    assert status == 422 and sent == [], status


def case_streams_and_stories_lists():
    _one("/api/of/v2/streams/top", {**RANGE, "by": "tips"}, "/streams/top",
         {**OF_RANGE, "limit": 10, "offset": 0, "by": "tips"})
    _one("/api/of/v2/stories/top", {**RANGE, "by": "views", "offset": 4}, "/stories/top",
         {**OF_RANGE, "by": "views", "offset": 4, "limit": 4})
    status, _, sent = _get("/api/of/v2/stories/top", {"by": "purchases"})
    assert status == 422 and sent == [], status



def case_subscribers_all_renews_new():
    for by in ("total", "renew", "new"):
        _one("/api/of/v2/subscriptions/subscribers/latest", {**RANGE, "by": by},
             "/subscriptions/subscribers/latest", {**OF_RANGE, "by": by, "offset": 0})
    _one("/api/of/v2/subscriptions/subscribers/chart", {**RANGE, "by": "renew"},
         "/subscriptions/subscribers/chart", {**OF_RANGE, "by": "renew"})


def case_top_fans_by_every_tab():
    for by in ("total", "subscribes", "tips", "messages", "post", "streams"):
        body = _one("/api/of/v2/subscriptions/subscribers/top", {**RANGE, "by": by, "offset": 10},
                    "/subscriptions/subscribers/top", {**OF_RANGE, "by": by, "offset": 10})
    assert body["users"][0]["subscribedOnData"]["tipsSumm"] == 7
    status, _, _ = _get("/api/of/v2/subscriptions/subscribers/top", {"by": "everything"})
    assert status == 422, status


def case_fans_activity_table_and_hours():
    body = {}
    for fmt in ("table", "hours"):
        body[fmt] = _one("/api/of/v2/fans-activity/list", {**RANGE, "format": fmt, "timeZone": "Europe/Ljubljana"},
                         "/fans-activity/list", {"format": fmt, **OF_RANGE, "timeZone": "Europe/Ljubljana"})
    table = body["table"]["data"]
    assert list(table) == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] and len(table["Fri"]) == 24
    assert set(table["Fri"]["21"]) == {"ratio"}
    assert len(body["hours"]["data"]) == 24 and set(body["hours"]["data"][0]) == {"ratio"}



def case_reach_promotions_trials_tracking_links():
    _one("/api/of/v2/promotions/stats", RANGE, "/promotions", {"offset": 0, **OF_RANGE, "limit": 10})
    _one("/api/of/v2/trials/stats", {**RANGE, "offset": 10}, "/trials/stats",
         {"offset": 10, **OF_RANGE, "limit": 10})
    _one("/api/of/v2/campaigns/stats", RANGE, "/campaigns",
         {"limit": 10, "offset": 0, "pagination": 1, **OF_RANGE,
          "with_deleted": 1, "sorting_deleted": 0, "stats": "true"})
    _one("/api/of/v2/campaigns/stats", {**RANGE, "field": "countSubscribers", "sort": "desc", "offset": 10},
         "/campaigns", {"limit": 10, "offset": 10, "pagination": 1, "field": "countSubscribers", **OF_RANGE,
                        "with_deleted": 1, "sorting_deleted": 0, "stats": "true", "sort": "desc"})


def case_plain_promotions_and_campaigns_are_main_s_routes():
    _, _, sent = _get("/api/of/v2/promotions")
    assert sent == [(f"{API}/promotions", {"offset": 0, "limit": 100})], sent
    _, _, sent = _get("/api/of/v2/campaigns")
    assert sent == [(f"{API}/campaigns", None)], sent


def case_every_statistics_route_is_a_get():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for path in ("/api/of/v2/payouts/chargebacks", "/api/of/v2/users/me/stats/top/{kind}",
                 "/api/of/v2/streaks", "/api/of/v2/streaks/top", "/api/of/v2/users/me/stats/today-activity",
                 "/api/of/v2/users/me/stats/messages/direct", "/api/of/v2/messages/queue/chart",
                 "/api/of/v2/messages/queue/buyers", "/api/of/v2/promotions/stats",
                 "/api/of/v2/campaigns/stats", "/api/of/v2/subscriptions/subscribers/latest",
                 "/api/of/v2/subscriptions/subscribers/top", "/api/of/v2/fans-activity/list",
                 "/api/of/v2/streams/top", "/api/of/v2/stories/top", "/api/of/v2/trials/stats",
                 "/api/of/v2/users/me/referrals", "/api/of/v2/payouts/chart",
                 "/api/of/v2/payouts/referrals/chart", "/api/of/v2/payouts/chargebacks/chart",
                 "/api/of/v2/promotions/chart", "/api/of/v2/trials/chart", "/api/of/v2/campaigns/chart",
                 "/api/of/v2/stories/chart", "/api/of/v2/streams/chart", "/api/of/v2/streams/viewers",
                 "/api/of/v2/stories/viewers", "/api/of/v2/payouts/download-approved-invoice",
                 "/api/of/v2/posts/stats", "/api/of/v2/posts/buyers",
                 "/api/of/v2/posts/tips", "/api/of/v2/posts/likes",
                 "/api/of/v2/promotions/claims", "/api/of/v2/trials/claims",
                 "/api/of/v2/campaigns/claimers"):
        assert ("GET", path) in routes, path
        assert not {("POST", path), ("PATCH", path), ("PUT", path), ("DELETE", path)} & routes, path



def case_transactions_pages_the_statistics_way():
    q = {"limit": 10, "type": "tips", "startDate": S, "marker": "1792195199", "tipsSource": "post_all"}
    body = _one("/api/of/v2/payouts/transactions", q, "/payouts/transactions",
                {"limit": 10, "offset": 0, "type": "tips", "startDate": S, "marker": "1792195199",
                 "tipsSource": "post_all"})
    assert body["nextMarker"] == 1791000001
    status, _, sent = _get("/api/of/v2/payouts/transactions", {"limit": 20})
    assert status == 200 and sent == [(f"{API}/payouts/transactions", {"limit": 20, "offset": 0})], sent
    status, _, sent = _get("/api/of/v2/payouts/transactions", {"tipsSource": "everywhere"})
    assert status == 422 and sent == [], status


def case_posts_top_offset_and_every_posts_chart_metric():
    _one("/api/of/v2/posts/top", {**RANGE, "by": "likes", "offset": 10}, "/posts/top",
         {**OF_RANGE, "by": "likes", "limit": 10, "offset": 10})
    status, _, sent = _get("/api/of/v2/posts/top", RANGE)
    assert sent == [(f"{API}/posts/top", {**OF_RANGE, "by": "purchases", "limit": 10})], sent
    for by in ("purchases", "tips", "views", "likes", "comments"):
        body = _one("/api/of/v2/posts/chart", {**RANGE, "by": by}, "/posts/chart",
                    {**OF_RANGE, "withTotal": "true", f"filter[{by}]": by, "filter[posts]": "posts"})
        assert body[by]["chart"], by


def case_profile_stats_by_filter_and_limit():
    body = _one("/api/of/v2/users/me/profile/stats", {**RANGE, "by": "guests", "limit": 50, "filter": "topCountries"},
                "/users/me/profile/stats", {**OF_RANGE, "limit": 50, "by": "guests", "filter[]": ["topCountries"]})
    countries = body["topCountries"]
    assert isinstance(countries["totals"]["guests"], str) and isinstance(countries["rows"][0]["viewsCount"]["guests"], int)
    _one("/api/of/v2/users/me/profile/stats", {**RANGE, "by": "users", "limit": 0, "filter": "chart"},
         "/users/me/profile/stats", {**OF_RANGE, "limit": 0, "by": "users", "filter[]": ["chart"]})
    status, _, sent = _get("/api/of/v2/users/me/profile/stats", {**RANGE, "limit": 3})
    assert sent == [(f"{API}/users/me/profile/stats", {**OF_RANGE, "limit": 3})], sent
    for bad in ({"filter": "everything"}, {"by": "bots"}, {"limit": 51}):
        status, _, sent = _get("/api/of/v2/users/me/profile/stats", bad)
        assert status == 422 and sent == [], (bad, status)


def case_statements_amount_count_charts():
    amount_count = {"withChart": "true", "filter[chartAmount]": "chartAmount", "filter[chartCount]": "chartCount"}
    _one("/api/of/v2/payouts/chart", RANGE, "/payouts/chart", {**OF_RANGE, "withTotal": "true", **amount_count})
    _one("/api/of/v2/payouts/referrals/chart", RANGE, "/payouts/referrals/chart",
         {**OF_RANGE, "withTotal": 1, **amount_count})
    body = _one("/api/of/v2/payouts/chargebacks/chart", RANGE, "/payouts/chargebacks/chart",
                {**OF_RANGE, "withTotal": "true", **amount_count})
    assert set(body) == {"total", "delta", "chartAmount", "chartCount"}, body


def case_reach_and_engagement_charts():
    for path in ("/promotions/chart", "/trials/chart"):
        body = _one(f"/api/of/v2{path}", RANGE, path, {**OF_RANGE, "stats": 1})
        assert set(body) == {"claims", "offers"} and set(body["claims"]) == {"chart", "total", "delta"}, body
    body = _one("/api/of/v2/campaigns/chart", RANGE, "/campaigns/chart",
                {"filter[clicks]": "clicks", "filter[claims]": "claims", **OF_RANGE})
    assert isinstance(body["clicks"], list) and isinstance(body["claims"], list) and "total" in body, body
    _one("/api/of/v2/stories/chart", {**RANGE, "by": "views"}, "/stories/chart",
         {**OF_RANGE, "withTotal": "true", "filter[views]": "views", "filter[stories]": "stories"})
    _one("/api/of/v2/streams/chart", {**RANGE, "by": "purchases"}, "/streams/chart",
         {**OF_RANGE, "withTotal": "true", "filter[purchases]": "purchases", "filter[duration]": "duration"})


def case_stream_and_story_viewer_lists():
    _one("/api/of/v2/streams/viewers", {"stream_id": 57001}, "/streams/57001/viewers",
         {"withFinishedViewers": "true", "onlyCurrentStreamTips": "true", "limit": 10, "offset": 0})
    _one("/api/of/v2/streams/viewers", {"stream_id": 57001, "tips_only": 1, "limit": 8, "offset": 8},
         "/streams/57001/viewers", {"withFinishedViewers": "true", "onlyCurrentStreamTips": "true",
                                    "onlyWithTips": "true", "limit": 8, "offset": 8})
    _one("/api/of/v2/stories/viewers", {"story_id": 58001}, "/stories/58001/viewers", {"limit": 10, "offset": 0})
    _one("/api/of/v2/stories/viewers", {"story_id": 58001, "tips_only": 1}, "/stories/58001/viewers",
         {"onlyWithTips": "true", "limit": 10, "offset": 0})


SIGNED = "https://cdn.example.invalid/files/invoice.pdf?Policy=SYNTHETICSECRET&Signature=SYNTHETICSIG"


class _InvoiceResponse:
    def __init__(self, status: int, body: bytes, ctype: str, disposition: str | None = None):
        self.status_code, self.ok, self.content = status, 200 <= status < 300, body
        self.headers = {"content-type": ctype}
        if disposition: self.headers["content-disposition"] = disposition
        self.url = SIGNED  # where a redirect could have landed: must never leave the relay
        self.text = body.decode("latin-1")


def _invoice(params, response):
    import logging
    c = _fake()
    c.get = lambda path, params=None: c.sent.append((path, params)) or response
    logs: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda rec: logs.append(rec.getMessage())
    root = logging.getLogger()
    root.addHandler(handler)
    orig = server._get_client
    server._get_client = lambda: c
    try:
        r = http.get("/api/of/v2/payouts/download-approved-invoice", params=params)
    finally:
        server._get_client = orig
        root.removeHandler(handler)
    return r, c.sent, logs


def case_payout_invoice_download_streams_the_file_and_never_leaks_the_url():
    pdf = b"%PDF-1.4 synthetic invoice"
    named = 'attachment; filename="Synthetic Creator 10-03-2026.pdf"'
    r, sent, logs = _invoice({"invoiceId": 4242}, _InvoiceResponse(200, pdf, "application/pdf", named))
    assert r.status_code == 200 and r.content == pdf, r.status_code
    assert sent == [(f"{API}/payouts/download-approved-invoice",
                     {"invoiceId": 4242, "app-token": of_client.APP_TOKEN, "isRefbonus": 0})], sent
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"] == named
    _, sent, _ = _invoice({"invoiceId": 4242, "isRefbonus": 1}, _InvoiceResponse(200, pdf, "application/pdf", named))
    assert sent[0][1]["isRefbonus"] == 1, sent
    for bad in (_InvoiceResponse(403, b'{"error":"' + SIGNED.encode() + b'"}', "application/json"),
                _InvoiceResponse(200, b'{"error":"' + SIGNED.encode() + b'"}', "application/json")):
        r, _, logs = _invoice({"invoiceId": 4242}, bad)
        assert r.status_code == 502 and r.json() == {"detail": {"upstream_status": bad.status_code}}, r.text
        assert any(f"upstream {bad.status_code}" in line for line in logs), logs
        for text in [r.text, *r.headers.values(), *logs]:
            assert "SYNTHETICSECRET" not in text and "cdn.example" not in text, text
    status, _, sent = _get("/api/of/v2/payouts/download-approved-invoice")
    assert status == 422 and sent == [], status



def case_per_item_stats_headers():
    body = _one("/api/of/v2/posts/stats", {"post_id": 59001}, "/posts/59001/stats", {"withChart": "true"})
    assert body["purchasedSumm"] == 10 and body["uniqueLookCount"] == 9, body
    status, body, sent = _get("/api/of/v2/posts/stats")
    assert (status, body, sent) == (200, {"supported": True}, []), (status, body, sent)
    status, _, sent = _get("/api/of/v2/posts/stats", {"post_id": 0})
    assert status == 422 and sent == [], status


def case_post_stats_is_not_read_as_a_post_id():
    c = _fake()
    c.get_post = lambda pid: c.sent.append(("get_post", pid)) or {"id": pid}
    orig = server._get_client
    server._get_client = lambda: c
    try:
        assert http.get("/api/of/v2/posts/59001").json() == {"id": 59001}
    finally:
        server._get_client = orig
    assert c.sent == [("get_post", 59001)], c.sent


def case_post_buyers_and_tippers_page_by_10():
    body = _one("/api/of/v2/posts/buyers", {"post_id": 59001}, "/posts/59001/buyers", {"limit": 10, "offset": 0})
    assert body["hasMore"] is True
    _one("/api/of/v2/posts/buyers", {"post_id": 59001, "offset": 10}, "/posts/59001/buyers",
         {"limit": 10, "offset": 10})
    _one("/api/of/v2/posts/tips", {"post_id": 59001, "offset": 20}, "/posts/59001/tips", {"limit": 10, "offset": 20})
    body = _one("/api/of/v2/posts/likes", {"post_id": 59001}, "/posts/59001/favorites", {"limit": 10, "offset": 0})
    assert set(body) == {"list", "hasMore"}, body
    _one("/api/of/v2/posts/likes", {"post_id": 59001, "offset": 10}, "/posts/59001/favorites",
         {"limit": 10, "offset": 10})
    status, _, sent = _get("/api/of/v2/posts/likes")
    assert status == 422 and sent == [], status
    status, _, sent = _get("/api/of/v2/posts/buyers")
    assert status == 422 and sent == [], status


def case_reach_claimed_and_subscriber_lists():
    claims = {"limit": 10, "offset": 0, "format": "infinite"}
    _one("/api/of/v2/promotions/claims", {"promo_id": 61001}, "/subscriptions/subscribers",
         {**claims, "filter[promoId]": 61001})
    _one("/api/of/v2/trials/claims", {"trial_id": 62001, "offset": 10}, "/subscriptions/subscribers",
         {**claims, "offset": 10, "filter[trial_id]": 62001})
    _one("/api/of/v2/campaigns/claimers", {"campaign_id": 60001}, "/campaigns/60001/claimers",
         {"more": "false", "limit": 10, "offset": 0})
    _one("/api/of/v2/campaigns/claimers", {"campaign_id": 60001, "offset": 10, "query": "synthetic"},
         "/campaigns/60001/claimers", {"more": "true", "limit": 10, "offset": 10, "query": "synthetic"})
    for url in ("/api/of/v2/promotions/claims", "/api/of/v2/trials/claims", "/api/of/v2/campaigns/claimers"):
        status, _, sent = _get(url)
        assert status == 422 and sent == [], (url, status)


def case_streak_month_switch_and_longest_streak_use_existing_routes():
    month = {"start": "2026-09-01 00:00:00", "end": "2026-09-30 23:59:59"}
    _one("/api/of/v2/streaks", month, "/streaks",
         {"startDate": month["start"], "endDate": month["end"]})
    c = _fake()
    c.get_json = lambda path, params=None: c.sent.append((path, params)) or {}
    orig = server._get_client
    server._get_client = lambda: c
    try:
        r = http.get("/api/of/v2/users/me/stats/overview", params={**month, "by": "earnings"})
    finally:
        server._get_client = orig
    assert r.status_code == 200 and c.sent == [(f"{API}/users/me/stats/overview",
                                                {"startDate": month["start"], "endDate": month["end"],
                                                 "by": "earnings"})], c.sent


def case_payout_requests_page_by_dates_and_marker():
    for route, of_path in (("/api/of/v2/payouts/requests", "/payouts/requests"),
                           ("/api/of/v2/payouts/requests/referral", "/payouts/requests/referral")):
        body = _one(route, {**RANGE, "offset": 10, "marker": "1791000003"}, of_path,
                    {"limit": 10, "offset": 10, **OF_RANGE, "marker": "1791000003"})
        assert set(body) == {"list", "marker"}, body
        _one(route, RANGE, of_path, {"limit": 10, "offset": 0, **OF_RANGE})
        _one(route, {"limit": 20, "offset": 40}, of_path, {"limit": 20, "offset": 40})
        status, _, sent = _get(route, {"marker": "x" * 65})
        assert status == 422 and sent == [], status


def case_fixture_is_synthetic():
    blob = json.dumps(FIX).replace("https://example.invalid/", "")
    assert "http" not in blob and "onlyfans.com" not in blob, "fixture must carry no real URLs"


_harness.run()
