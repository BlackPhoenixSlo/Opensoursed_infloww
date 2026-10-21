#!/usr/bin/env python3
"""OF Manager reads for Notifications' Tags tab and the Streaming dashboard.

GET /api/of/v2/release-forms/mentions -> OF's GET /api2/v2/release-forms/mentions
(the Tags tab), GET /api/of/v2/users/{id}/streams -> OF's GET
/api2/v2/users/{id}/streams (Past live streams). Query as OF's own client sends
it; an OF rejection surfaces as the usual structured 502. Plain-assert, OF faked.

  case_routes_are_registered
  case_mentions_route_passes_paging
  case_streams_route_passes_user_and_paging
  case_client_mentions_query
  case_client_streams_query
  case_of_error_is_502

Run: ./venv/bin/python service/tests/test_of_manager_notifications_streams.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from fastapi import HTTPException  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402


class _Fake:
    def __init__(self, fail=False):
        self.calls: list[tuple] = []
        self.fail = fail

    def _maybe_fail(self):
        if self.fail:
            class R:
                status_code = 400
                text = '{"error":{"message":"Bad request"}}'
            raise of_client.OFAPIError("400", response=R())

    def release_form_mentions(self, **kw):
        self.calls.append(("mentions", kw))
        self._maybe_fail()
        return {"list": [{"id": 1, "type": "tags"}], "hasMore": False}

    def user_streams(self, user_id, **kw):
        self.calls.append(("streams", user_id, kw))
        self._maybe_fail()
        return {"list": [{"id": 9, "viewsCount": 3}], "hasMore": False}


def _with(fake, fn):
    orig = server._get_client, server._resolve_account_id
    server._get_client = lambda: fake
    server._resolve_account_id = lambda _req=None: "acct-notif"
    try:
        return fn()
    finally:
        server._get_client, server._resolve_account_id = orig


def _client():
    c = of_client.OFClient.__new__(of_client.OFClient)
    sent = []
    c.get_json = lambda path, **kw: sent.append((path, kw)) or {"list": []}
    return c, sent


def case_routes_are_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("GET", "/api/of/v2/release-forms/mentions") in routes, "mentions route missing"
    assert ("GET", "/api/of/v2/users/{user_id}/streams") in routes, "streams route missing"


def case_mentions_route_passes_paging():
    fake = _Fake()
    out = _with(fake, lambda: server.of_release_form_mentions(limit=20, offset=0))
    assert fake.calls == [("mentions", {"limit": 20, "offset": 0})], fake.calls
    assert out["list"][0]["id"] == 1, out


def case_streams_route_passes_user_and_paging():
    fake = _Fake()
    out = _with(fake, lambda: server.of_user_streams("42", limit=8, offset=8))
    assert fake.calls == [("streams", "42", {"limit": 8, "offset": 8})], fake.calls
    assert out["list"][0]["viewsCount"] == 3, out


def case_client_mentions_query():
    c, sent = _client()
    c.release_form_mentions(limit=20)
    assert sent == [(f"{of_client.API_BASE}/release-forms/mentions",
                     {"params": {"limit": 20, "offset": 0, "skip_users": "all", "format": "infinite"}})], sent


def case_client_streams_query():
    c, sent = _client()
    c.user_streams(42)
    assert sent == [(f"{of_client.API_BASE}/users/42/streams",
                     {"params": {"limit": 8, "offset": 0, "skip_users": "all"}})], sent


def case_of_error_is_502():
    for call in (lambda: server.of_release_form_mentions(limit=10, offset=0),
                 lambda: server.of_user_streams("42", limit=8, offset=0)):
        try:
            _with(_Fake(fail=True), call)
        except HTTPException as e:
            assert e.status_code == 502, e.status_code
            assert e.detail["upstream_status"] == 400, e.detail
        else:
            raise AssertionError("expected a 502")


_harness.run()
