#!/usr/bin/env python3
"""OF Manager queue row actions: publish now, delete, pin.

"Post now" / "Message now" is OF's PUT /api2/v2/schedules/{id}/publish with no
body, keyed by the schedule item's own id (module 409363 `V9`). Delete goes to
the entity: DELETE /posts/{id} for a post, DELETE /messages/queue/{id} for a
message; pin is the POST toggle. Plain-assert, OF faked (no request leaves the
process).

  case_publish_route_is_registered
  case_publish_route_calls_the_client
  case_client_publish_is_a_bodyless_put
  case_delete_post_and_cancel_message_paths
  case_of_error_is_502

Run: ./venv/bin/python service/tests/test_queue_actions.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from fastapi import HTTPException  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402


def _client():
    """An OFClient whose every request is recorded instead of sent."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = "4242"
    c.sent = []
    c.request_json = lambda method, path, **kw: c.sent.append((method, path, kw)) or {"success": True}
    return c


class _Fake:
    def __init__(self, fail=False):
        self.calls: list[int] = []
        self.fail = fail

    def publish_schedule(self, schedule_id):
        self.calls.append(schedule_id)
        if self.fail:
            class R:
                status_code = 400
                text = '{"error":{"message":"Media is not ready"}}'
            raise of_client.OFAPIError("400", response=R())
        return {"success": True}


def _with(fake, fn):
    orig = server._get_client
    server._get_client = lambda: fake
    try:
        return fn()
    finally:
        server._get_client = orig


def case_publish_route_is_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("PUT", "/api/of/v2/schedules/{schedule_id}/publish") in routes, "publish route missing"
    assert ("DELETE", "/api/of/v2/posts/{post_id}") in routes
    assert ("DELETE", "/api/of/v2/messages/queue/{queue_id}") in routes
    assert ("POST", "/api/of/v2/posts/{post_id}/pin") in routes


def case_publish_route_calls_the_client():
    fake = _Fake()
    assert _with(fake, lambda: server.of_publish_schedule(901)) == {"success": True}
    assert fake.calls == [901], fake.calls


def case_client_publish_is_a_bodyless_put():
    c = _client()
    assert c.publish_schedule(901) == {"success": True}
    assert c.sent == [("PUT", f"{of_client.API_BASE}/schedules/901/publish", {})], c.sent


def case_delete_post_and_cancel_message_paths():
    c = _client()
    c.delete_post(11)
    c.cancel_scheduled(22)
    c.pin_post(11)
    assert c.sent == [
        ("DELETE", f"{of_client.API_BASE}/posts/11", {}),
        ("DELETE", f"{of_client.API_BASE}/messages/queue/22", {}),
        ("POST", f"{of_client.API_BASE}/posts/11/pin", {"params": {"format": "status"}}),
    ], c.sent


def case_of_error_is_502():
    try:
        _with(_Fake(fail=True), lambda: server.of_publish_schedule(901))
    except HTTPException as e:
        assert e.status_code == 502, e.status_code
        assert "Media is not ready" in e.detail["upstream_body"], e.detail
    else:
        raise AssertionError("expected a 502")


_harness.run()
