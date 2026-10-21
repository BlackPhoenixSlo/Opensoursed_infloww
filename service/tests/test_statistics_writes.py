#!/usr/bin/env python3
"""OF Manager fan writes that sit next to the retired Statistics ones and must
keep reaching OF unchanged:

  PUT  /api/of/v2/subscriptions/{id}  → OFClient.update_subscription
  POST /api/of/v2/lists/users         → OFClient.add_users_to_lists

OF is faked on the client: nothing leaves the process. Ids are synthetic.

Run: ./venv/bin/python service/tests/test_statistics_writes.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import _agency_fixtures as fx  # noqa: E402
import of_client  # noqa: E402
import server  # noqa: E402

IDS = fx.seed_two_agencies()
http = fx.login_owner("agency_a_owner")
http.headers["X-Account-Id"] = IDS["creator_a"]


def _fake():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.sent = []
    return c


def case_subscription_id_put_still_reaches_update_subscription():
    c = _fake()
    seen = []
    c.update_subscription = lambda user_id, **kw: seen.append((user_id, kw)) or {"ok": True}
    orig = server._get_client
    server._get_client = lambda: c
    try:
        r = http.put("/api/of/v2/subscriptions/123", json={"notice": "n"})
    finally:
        server._get_client = orig
    assert r.status_code == 200, r.text
    assert seen == [(123, {"notice": "n"})] and c.sent == [], (seen, c.sent)


def case_bulk_lists_users_post_is_unchanged():
    c = _fake()
    seen = []
    c.add_users_to_lists = lambda body: seen.append(body) or {"ok": True}
    orig = server._get_client
    server._get_client = lambda: c
    try:
        r = http.post("/api/of/v2/lists/users", json={"1001": [900101]})
    finally:
        server._get_client = orig
    assert r.status_code == 200 and seen == [{"1001": [900101]}], (r.status_code, seen)


_harness.run()
