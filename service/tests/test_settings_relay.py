#!/usr/bin/env python3
"""OF Manager Settings: the relay routes its pages use and the OF requests they send.

Read from OF's web bundle (build 202610091632), never observed live:
- the subscription bundles: create POST /subscriptions/bundles {discount, duration}, edit
  PUT /subscriptions/bundles/{id} {discount, duration, id}, delete DELETE /subscriptions/bundles/{id}
  (app.js module 112995, bundles/saveBundle and deleteBundle);
- the free trial link's "Create link": POST /trials {trialLinkName, subscribeDays, subscribeCounts, expireDays}
  (ModalTrial saveForm; expireDays 0 = no expiration);
- QR code's scan count: GET /users/me/profile/views/qr;
- Streaming > Blocked users, read-only: GET /streams/users/blocked?limit=10[&offset][&query];
- Account > Login sessions, read-only: GET /sessions (settings-sessions.js); no route ends a session.
Plain-assert, OF faked (no request leaves the process).

Run: ./venv/bin/python service/tests/test_settings_relay.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

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


def _client():
    """An OFClient whose every request is recorded instead of sent."""
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
    # The app's trialBody for OF's defaults (TRIAL_DEFAULTS: 10 claims, 7 days' validity, a 7-day trial), a leading-space name.
    body = server._TrialLinkBody(name="  Spring", subscribe_counts=10, expire_days=7, subscribe_days=7)
    method, path, sent, _ = _route(server.of_create_trial_link, body)
    assert (method, path) == ("POST", f"{API}/trials"), (method, path)
    assert sent == {"trialLinkName": "Spring", "subscribeDays": 7, "subscribeCounts": 10, "expireDays": 7}, sent
    # "No expiration" is 0, still sent; an older caller with no expire_days sends none.
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


def case_qr_views():
    assert _route(of_stats_api.of_my_qr_views)[:2] == ("GET", f"{API}/users/me/profile/views/qr")


def case_stream_blocked_users_params():
    _, path, _, params = _route(of_stats_api.of_stream_blocked_users, limit=10, offset=0, query="")
    assert path == f"{API}/streams/users/blocked" and params == {"limit": 10}, (path, params)
    _, _, _, params = _route(of_stats_api.of_stream_blocked_users, limit=10, offset=20, query="fan")
    assert params == {"limit": 10, "offset": 20, "query": "fan"}, params


def case_sessions_read_only():
    assert _route(of_stats_api.of_sessions)[:2] == ("GET", f"{API}/sessions")


def case_routes_registered():
    paths = {(m, r.path) for r in server.app.routes if hasattr(r, "methods") for m in (r.methods or [])}
    for want in [("PUT", "/api/of/v2/subscriptions/bundles/{bundle_id}"), ("GET", "/api/of/v2/users/me/profile/views/qr"),
                 ("GET", "/api/of/v2/streams/users/blocked"), ("GET", "/api/of/v2/sessions")]:
        assert want in paths, want
    # No write route for the stream block list: blocking and unblocking stay on OnlyFans.
    assert not any(p.startswith("/api/of/v2/streams/users/") and m != "GET" for m, p in paths), "a stream block write route"
    # No route ends a login session: "Close all sessions" stays on OnlyFans.
    assert not any(p.startswith("/api/of/v2/sessions") and m not in ("GET", "HEAD") for m, p in paths), "a session write route"


_harness.run()
