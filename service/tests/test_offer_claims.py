#!/usr/bin/env python3
"""Growth's Details reads: who claimed an offer, with OF's per-fan spend (app/components/growth/OfferClaimers.tsx).

A user-supplied HAR of OF's own free trial link claimers list (2026-10-18) pins the trial read:

  GET /api2/v2/subscriptions/subscribers?limit=10&offset=0&format=infinite&filter[trial_id]=<id>
  GET ...same with offset=10                     -> {list: [user], hasMore}

Each user carries subscribedOnData {totalSumm, subscribesSumm, postsSumm, messagesSumm, streamsSumm, tipsSumm},
which the relay must hand through untouched: the page sums it. The promotion (filter[promoId]) and tracking link
(/campaigns/{id}/claimers) reads are OF's bundle read statically, not in the HAR.

Plain-assert, OF faked (no request leaves the process); synthetic ids and amounts.

Run: ./venv/bin/python service/tests/test_offer_claims.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import of_client  # noqa: E402
import server  # noqa: E402
import of_stats_api  # noqa: E402  # after server: its routes load with it

SUBSCRIBERS = f"{of_client.API_BASE}/subscriptions/subscribers"
FAN = {"id": 70000001, "name": "Synth Fan A", "username": "synthfana",
       "subscribedOnData": {"totalSumm": 67.19, "subscribesSumm": 0, "postsSumm": 48, "messagesSumm": 19.19,
                            "streamsSumm": 0, "tipsSumm": 0}}
PAGE = {"list": [FAN], "hasMore": True}


def _client(reply=None):
    """An OFClient whose every GET is recorded instead of sent."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.sent = []
    c.get_json = lambda path, params=None: c.sent.append((path, params)) or (reply if reply is not None else {"ok": 1})
    return c


def _via_route(fn, *args, reply=None, **kw):
    """Call a relay route with OF faked; return (body, [(path, params)])."""
    c = _client(reply)
    orig = server._get_client
    server._get_client = lambda: c
    try:
        out = fn(*args, **kw)
    finally:
        server._get_client = orig
    return out, c.sent


def case_trial_claims_reach_of_as_captured():
    _, sent = _via_route(of_stats_api.of_trial_claims, trial_id=4242, limit=10, offset=0)
    assert sent == [(SUBSCRIBERS, {"limit": 10, "offset": 0, "format": "infinite", "filter[trial_id]": 4242})], sent
    # The HAR's own query order.
    assert list(sent[0][1]) == ["limit", "offset", "format", "filter[trial_id]"], list(sent[0][1])


def case_trial_claims_next_page_is_offset_10():
    _, sent = _via_route(of_stats_api.of_trial_claims, trial_id=4242, limit=10, offset=10)
    assert sent[0][1]["offset"] == 10 and sent[0][1]["limit"] == 10, sent


def case_fans_spend_passes_through_untouched():
    out, _ = _via_route(of_stats_api.of_trial_claims, trial_id=4242, limit=10, offset=0, reply=PAGE)
    assert out == PAGE, out
    d = out["list"][0]["subscribedOnData"]
    parts = ("subscribesSumm", "postsSumm", "messagesSumm", "streamsSumm", "tipsSumm")
    assert abs(d["totalSumm"] - sum(d[k] for k in parts)) < 0.005, d


def case_promotion_claims_filter_by_promo_id():
    _, sent = _via_route(of_stats_api.of_promotion_claims, promo_id=501, limit=10, offset=0)
    assert sent == [(SUBSCRIBERS, {"limit": 10, "offset": 0, "format": "infinite", "filter[promoId]": 501})], sent


def case_campaign_claimers_page_as_ofs_modal():
    _, first = _via_route(of_stats_api.of_campaign_claimers, campaign_id=7, limit=10, offset=0, query=None)
    _, nxt = _via_route(of_stats_api.of_campaign_claimers, campaign_id=7, limit=10, offset=10, query=None)
    path = f"{of_client.API_BASE}/campaigns/7/claimers"
    assert first == [(path, {"more": "false", "limit": 10, "offset": 0})], first
    assert nxt == [(path, {"more": "true", "limit": 10, "offset": 10})], nxt


def case_unknown_offer_kind_is_refused():
    c = _client()
    try:
        c.offer_claims(1, "campaign")
    except ValueError:
        pass
    else:
        raise AssertionError("offer_claims took a kind it has no filter for")
    assert c.sent == [], c.sent


_harness.run(
    case_trial_claims_reach_of_as_captured,
    case_trial_claims_next_page_is_offset_10,
    case_fans_spend_passes_through_untouched,
    case_promotion_claims_filter_by_promo_id,
    case_campaign_claimers_page_as_ofs_modal,
    case_unknown_offer_kind_is_refused,
)
