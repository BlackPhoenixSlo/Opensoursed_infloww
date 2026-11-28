#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fansly"))

from fansly_client import FanslySession  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402

import server  # noqa: E402
import mass_queue_api  # noqa: E402
import mass_broadcast_cache  # noqa: E402
import accounts  # noqa: E402

# A snowflake above 2^53: the id must reach Fansly digit for digit.
POST = "900546198725955584"


def _shim():
    c = FanslyShimClient(FanslySession({
        "accountId": "700237824869654528", "token": "t", "check_key": "k", "device_id": "d",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }))
    c.calls = []

    def fake(method, path, *, params=None, json_body=None, **_kw):
        c.calls.append((method, path, json_body))
        if path == "/post/scheduled":
            return {"scheduledPosts": [{"postId": POST, "status": 1, "postTemplate": {},
                                        "scheduledFor": 1788894787000}]}
        return {"success": True}

    c._request = fake
    return c


def _with(client, fn):
    orig = server._get_client
    server._get_client = lambda: client
    try:
        return fn()
    finally:
        server._get_client = orig


def case_cancel_route_reaches_the_fansly_post_lane_cancel():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("DELETE", "/api/of/v2/messages/queue/{queue_id}") in routes
    c = _shim()
    aid = "700237824869654528"
    with (patch.object(mass_queue_api, "_resolve_account_id", return_value=aid),
          patch.object(accounts, "get_platform", return_value="fansly"),
          patch.object(mass_broadcast_cache, "mark_canceled", new_callable=AsyncMock) as mark):
        resp = _with(c, lambda: asyncio.run(mass_queue_api.of_cancel_scheduled(None, int(POST))))
        mark.assert_not_awaited()
    assert resp == {"success": True}, resp
    assert c.calls == [("GET", "/post/scheduled", None), ("POST", f"/post/scheduled/{POST}/cancel", None)], c.calls


def case_schedules_route_answers_the_shim_queue_items():
    c = _shim()
    resp = _with(c, lambda: server.of_schedules(publish_date=None, publish_date_end=None,
                                                time_zone="UTC", limit=50))
    assert [i["id"] for i in resp["list"]] == [POST], resp
    assert c.calls == [("GET", "/post/scheduled", None)], c.calls


_harness.run()
