#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import of_client  # noqa: E402
import server  # noqa: E402
import of_stats_api  # noqa: E402  # after server: its routes load with it


def _client():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.sent = []
    c.get_json = lambda path, params=None: c.sent.append((path, params)) or {"ok": 1}
    return c


def _via_route(fn, *args, **kw):
    c = _client()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        out = getattr(fn, "__wrapped__", fn)(*args, **kw)
    finally:
        server._get_client = orig
    return out, c.sent


def case_balances_is_a_bare_get():
    out, sent = _via_route(server.of_payout_balances)
    assert out == {"ok": 1}, out
    assert sent == [(f"{of_client.API_BASE}/payouts/balances", None)], sent


def case_earning_stats_path():
    _, sent = _via_route(server.of_earning_stats, by="day", startDate=None, endDate=None)
    assert sent == [(f"{of_client.API_BASE}/payouts/stats", {"by": "day"})], sent


def case_earning_stats_range_reaches_of_as_start_date_and_end_date():
# OF ignores start/end (all-time answer): only startDate/endDate scope the period
    _, sent = _via_route(server.of_earning_stats, by="day", startDate="2026-10-01", endDate="2026-10-31")
    assert sent == [(f"{of_client.API_BASE}/payouts/stats",
                     {"by": "day", "startDate": "2026-10-01", "endDate": "2026-10-31"})], sent


def case_referral_balance_is_a_bare_get():
    _, sent = _via_route(of_stats_api.of_referrals_balance)
    assert sent == [(f"{of_client.API_BASE}/payments/referrals/balance", None)], sent


def case_chargebacks_ratio_sends_the_date_range():
    _, sent = _via_route(of_stats_api.of_chargebacks_ratio, start="2026-09-16 00:00:00", end="2026-10-16 23:59:59")
    assert sent == [(f"{of_client.API_BASE}/payouts/chargebacks/ratio",
                     {"startDate": "2026-09-16 00:00:00", "endDate": "2026-10-16 23:59:59"})], sent


def case_chargebacks_ratio_defaults_to_30_days():
    from datetime import datetime
    _, sent = _via_route(of_stats_api.of_chargebacks_ratio, start=None, end=None)
    (path, params), = sent
    assert path == f"{of_client.API_BASE}/payouts/chargebacks/ratio", path
    fmt = "%Y-%m-%d %H:%M:%S"
    span = datetime.strptime(params["endDate"], fmt) - datetime.strptime(params["startDate"], fmt)
    assert span.days == 30, params


def case_mirror_read_routes_are_registered_as_gets():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for path in ("/api/of/v2/payouts/balances", "/api/of/v2/payouts/stats",
                 "/api/of/v2/payments/referrals/balance", "/api/of/v2/payouts/chargebacks/ratio"):
        assert ("GET", path) in routes, path


_harness.run()
