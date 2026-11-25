#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

# Request shapes read from OF's web bundle (build 202610091632), never observed live.
_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402
import of_stats_api  # noqa: E402  # after server: its routes load with it
from pydantic import ValidationError  # noqa: E402

API = of_client.API_BASE
FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "app", "lib", "__fixtures__", "of")


def _fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def _capture(name):
    with open(os.path.join(os.path.dirname(__file__), "..", "..", ".scratch", "ofm-not-yet", "captures", name)) as f:
        return json.load(f)


def _client():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"id": 1}
    c.get_json = lambda path, **kw: c.sent.append(("GET", path, kw)) or {}
    return c


def _route(fn, *args, **kwargs):
    c = _client()
    orig = server._get_client
    server._get_client = lambda: c
    try:
        fn(*args, **kwargs)
    finally:
        server._get_client = orig
    (method, path, kw), = c.sent
    return method, path, kw.get("json_body"), kw.get("params")


def case_bundle_create_edit_delete_are_ofs_calls():
    fx = _fixture("settings-bundles.json")
    sent = _route(server.of_create_bundle, server._BundleBody(**fx["create"]["relay"]["body"]))
    assert sent[:3] == ("POST", f"{API}{fx['create']['of']['path']}", fx["create"]["of"]["body"]), sent
    sent = _route(server.of_edit_bundle, fx["edit"]["id"], server._BundleEditBody(**fx["edit"]["relay"]["body"]))
    assert sent[:3] == ("PUT", f"{API}{fx['edit']['of']['path']}", fx["edit"]["of"]["body"]), sent
    sent = _route(server.of_delete_bundle, fx["delete"]["id"])
    assert sent[:2] == ("DELETE", f"{API}{fx['delete']['of']['path']}"), sent


def case_bundle_edit_needs_discount_and_duration():
    for bad in ({"discount": 10}, {"duration": 3}, {"discount": 101, "duration": 3}, {"discount": 10, "duration": 0}):
        try:
            server._BundleEditBody(**bad)
        except ValidationError:
            continue
        raise AssertionError(f"accepted {bad}")


def case_trial_link_create_sends_ofs_expire_days():
    body = server._TrialLinkBody(name="  Spring", subscribe_counts=10, expire_days=7, subscribe_days=7)
    method, path, sent, _ = _route(server.of_create_trial_link, body)
    assert (method, path) == ("POST", f"{API}/trials"), (method, path)
    assert sent == {"trialLinkName": "Spring", "subscribeDays": 7, "subscribeCounts": 10, "expireDays": 7}, sent
    _, _, sent, _ = _route(server.of_create_trial_link, server._TrialLinkBody(name="", subscribe_counts=0, expire_days=0, subscribe_days=30))
    assert sent == {"trialLinkName": "", "subscribeDays": 30, "subscribeCounts": 0, "expireDays": 0}, sent
    _, _, sent, _ = _route(server.of_create_trial_link, server._TrialLinkBody(name="x"))
    assert "expireDays" not in sent, sent
    for bad in ({"expire_days": 31}, {"expire_days": -1}, {"subscribe_days": 0}):
        try:
            server._TrialLinkBody(**bad)
        except ValidationError:
            continue
        raise AssertionError(f"accepted {bad}")


def case_tracking_links_sort_is_ofs_field_and_sort():
    assert _route(server.of_tracking_links, field=None, sort=None)[1:] == (f"{API}/campaigns", None, None)
    for field in sorted(server._CAMPAIGN_SORT_FIELDS):
        for sort in ("asc", "desc"):
            _, path, _, params = _route(server.of_tracking_links, field=field, sort=sort)
            assert path == f"{API}/campaigns" and params == {"limit": 100, "offset": 0, "pagination": 1, "field": field, "sort": sort}, params
    assert server._CAMPAIGN_SORT_FIELDS == {"created_date", "name", "subscribers_counts", "clicks_count", "shared"}
    for field, sort in (("bogus", "asc"), ("name", None), (None, "desc"), ("created", "desc")):
        c = _client()
        orig = server._get_client
        server._get_client = lambda: c
        try:
            server.of_tracking_links(field=field, sort=sort)
        except server.HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"accepted {field!r} {sort!r}")
        finally:
            server._get_client = orig
        assert c.sent == [], c.sent


def case_tracking_links_shared_with_you_and_share_are_ofs_calls():
    base = {"limit": 100, "offset": 0, "pagination": 1, "with_deleted": 1, "sorting_deleted": 1, "stats": "true"}
    sent = _route(server.of_tracking_links_shared_with_me, field=None, sort=None, limit=100, offset=0)
    assert sent == ("GET", f"{API}/campaigns/share-access", None, base), sent
    sent = _route(server.of_tracking_links_shared_with_me, field="shared", sort="asc", limit=10, offset=20)
    assert sent[3] == {**base, "limit": 10, "offset": 20, "field": "shared", "sort": "asc"}, sent
    for field, sort in (("bogus", "asc"), ("name", None), (None, "desc")):
        c = _client()
        orig = server._get_client
        server._get_client = lambda: c
        try:
            server.of_tracking_links_shared_with_me(field=field, sort=sort, limit=100, offset=0)
        except server.HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"accepted {field!r} {sort!r}")
        finally:
            server._get_client = orig
        assert c.sent == [], c.sent
    fx = _fixture("settings-tracking-share-body.json")
    body = server._ShareCampaignBody(**fx["relay"])
    for fn, want in ((server.of_share_campaign_stats, fx["of"]), (server.of_unshare_campaign_stats, fx["undo"])):
        assert _route(fn, body)[:3] == (want["method"], f"{API}{want['path']}", want["body"]), (fn, want)
    for bad in ({"campaignId": 0, "userId": 1}, {"campaignId": 1}, {"campaign_id": 1, "user_id": 1}):
        try:
            server._ShareCampaignBody(**bad)
        except ValidationError:
            continue
        raise AssertionError(f"accepted {bad}")
    order = [(m, r.path) for r in server.app.routes if hasattr(r, "methods") for m in (r.methods or [])]
    assert order.index(("DELETE", "/api/of/v2/campaigns/share-access")) < order.index(("DELETE", "/api/of/v2/campaigns/{campaign_id}"))

_BLOCK_COUNTRIES, _BLOCK_IPS = ("/api/of/v2/users/me/settings/security/blocked-countries",
                                "/api/of/v2/users/me/settings/security/blocked-ips")


def case_block_by_country_and_ip_send_ofs_security_put_and_drop_the_settings_cache():
    assert _route(server.of_countries) == ("GET", f"{API}/countries", None, {"all": 1})
    dropped = []
    orig, orig_aid = server.relay_cache.invalidate, server._current_aid
    server.relay_cache.invalidate = lambda name, aid, *a, **kw: dropped.append((name, aid))
    server._current_aid = lambda: "acct-66"
    try:
        for fn, body in ((server.of_block_countries, {"blockedCountries": ["AQ"], "blockedStates": [12]}),
                         (server.of_block_countries, {"blockedCountries": [], "blockedStates": []}),
                         (server.of_block_ips, {"blockedIps": ["192.0.2.1", "2001:db8::/32"]}),
                         (server.of_block_ips, {"blockedIps": []})):
            assert _route(fn, dict(body)) == ("PUT", f"{API}/users/me/settings/security", body, None), (fn, body)
    finally:
        server.relay_cache.invalidate, server._current_aid = orig, orig_aid
    assert dropped == [("my_settings", "acct-66")] * 4, dropped
    for fn, bad in ((server.of_block_countries, {"blockedCountries": ["AQ"], "blockedStates": [], "blockedIps": []}),
                    (server.of_block_countries, {"blockedCountries": ["AQ"]}),
                    (server.of_block_countries, {"blockedCountries": "AQ", "blockedStates": []}),
                    (server.of_block_countries, {"blockedCountries": ["AQ"], "blockedStates": ["12"]}),
                    (server.of_block_countries, {"blockedCountries": ["AQ"], "blockedStates": [True]}),
                    (server.of_block_ips, {"blockedIps": ["192.0.2.1"], "isPrivate": True}),
                    (server.of_block_ips, {"blockedIps": [1]}),
                    (server.of_block_ips, {"hasWatermarkPhoto": True}),
                    (server.of_block_ips, {})):
        c = _client()
        orig = server._get_client
        server._get_client = lambda: c
        try:
            fn(bad)
        except server.HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"{fn.__name__} accepted {bad}")
        finally:
            server._get_client = orig
        assert c.sent == [], c.sent
    for bad in ({"blockedIps": ["192.0.2.1"]}, {"blockedCountries": ["AQ"], "blockedStates": []}):
        try:
            server.of_put_security_settings(bad)
        except server.HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"the general security PUT accepted {bad}")
    paths = {(m, r.path) for r in server.app.routes if hasattr(r, "methods") for m in (r.methods or [])}
    assert {("PUT", _BLOCK_COUNTRIES), ("PUT", _BLOCK_IPS), ("GET", "/api/of/v2/countries")} <= paths


def case_qr_views():
    assert _route(of_stats_api.of_my_qr_views)[:2] == ("GET", f"{API}/users/me/profile/views/qr")


def case_stream_blocked_users_params():
    _, path, _, params = _route(of_stats_api.of_stream_blocked_users, limit=10, offset=0, query="")
    assert path == f"{API}/streams/users/blocked" and params == {"limit": 10}, (path, params)
    _, _, _, params = _route(of_stats_api.of_stream_blocked_users, limit=10, offset=20, query="fan")
    assert params == {"limit": 10, "offset": 20, "query": "fan"}, params


def case_stream_block_and_unblock_are_ofs_calls_without_a_body():
    assert _route(server.of_block_stream_viewer, "oi_synthetic.fan-1", None) == (
        "POST", f"{API}/streams/users/oi_synthetic.fan-1/block", None, None)
    assert _route(server.of_unblock_stream_viewer, 7) == ("DELETE", f"{API}/streams/users/7/block", None, None)


def case_stream_block_and_unblock_match_the_capture_record():
    rec = _capture("settings--streaming-block-username.json")
    want = {q["role"]: q for q in rec["requests"]}
    assert want["write"]["body"] == {} and want["undo"]["body"] == {}, rec
    got = _route(server.of_block_stream_viewer, "soakfan1", None)
    assert got == (want["write"]["method"], API.replace("/api2/v2", "") + want["write"]["path"].replace(
        "{username}", "soakfan1"), None, None), got
    got = _route(server.of_unblock_stream_viewer, 7)
    assert got == (want["undo"]["method"], API.replace("/api2/v2", "") + want["undo"]["path"].replace(
        "{userId}", "7"), None, None), got


def case_sessions_read_only():
    assert _route(of_stats_api.of_sessions)[:2] == ("GET", f"{API}/sessions")


def case_routes_registered():
    paths = {(m, r.path) for r in server.app.routes if hasattr(r, "methods") for m in (r.methods or [])}
    for want in [("PUT", "/api/of/v2/subscriptions/bundles/{bundle_id}"), ("GET", "/api/of/v2/users/me/profile/views/qr"),
                 ("GET", "/api/of/v2/streams/users/blocked"), ("GET", "/api/of/v2/sessions")]:
        assert want in paths, want
    assert {(m, p) for m, p in paths if p.startswith("/api/of/v2/streams/users/") and m not in ("GET", "HEAD")} == {
        ("POST", "/api/of/v2/streams/users/{username}/block"), ("DELETE", "/api/of/v2/streams/users/{user_id}/block")}, \
        "a stream block write route"
    assert not any(p.startswith("/api/of/v2/sessions") and m not in ("GET", "HEAD") and (m, p) != ("DELETE", "/api/of/v2/sessions")
                   for m, p in paths), "a session write route"


_harness.run()
