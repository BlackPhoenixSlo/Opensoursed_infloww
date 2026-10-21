#!/usr/bin/env python3
"""POST /api/of/v2/streams — schedule a stream (OF Manager's schedule form).

The body passes through to OF's POST /api2/v2/streams exactly as OF's own
create form sends it ({description, scheduledDate, isShowTips}); an OF
rejection surfaces as the usual structured 502. Plain-assert, OF faked.

  case_route_is_registered
  case_body_passes_through
  case_client_posts_to_streams
  case_of_error_is_502

Run: ./venv/bin/python service/tests/test_schedule_stream.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from fastapi import HTTPException  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402

BODY = {"description": "Synthetic stream", "scheduledDate": "2026-10-20T18:30:00+02:00", "isShowTips": True}


class _Fake:
    def __init__(self, fail=False):
        self.calls: list[dict] = []
        self.fail = fail

    def schedule_stream(self, **fields):
        self.calls.append(fields)
        if self.fail:
            class R:
                status_code = 400
                text = '{"error":{"message":"Date is in the past"}}'
            raise of_client.OFAPIError("400", response=R())
        return {"id": 77, **fields}


def _with(fake, fn):
    orig = server._get_client, server._resolve_account_id
    server._get_client = lambda: fake
    server._resolve_account_id = lambda _req=None: "acct-stream"
    try:
        return fn()
    finally:
        server._get_client, server._resolve_account_id = orig


def case_route_is_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    assert ("POST", "/api/of/v2/streams") in routes, "POST /api/of/v2/streams missing"


def case_body_passes_through():
    fake = _Fake()
    out = _with(fake, lambda: server.of_schedule_stream(dict(BODY)))
    assert fake.calls == [BODY], fake.calls
    assert out["id"] == 77, out


def case_client_posts_to_streams():
    c = of_client.OFClient.__new__(of_client.OFClient)
    sent = []
    c.request_json = lambda method, path, **kw: sent.append((method, path, kw)) or {"id": 1}
    assert c.schedule_stream(**BODY) == {"id": 1}
    assert sent == [("POST", f"{of_client.API_BASE}/streams", {"json_body": BODY})], sent


def case_of_error_is_502():
    try:
        _with(_Fake(fail=True), lambda: server.of_schedule_stream(dict(BODY)))
    except HTTPException as e:
        assert e.status_code == 502, e.status_code
        assert e.detail["upstream_status"] == 400, e.detail
        assert "Date is in the past" in e.detail["upstream_body"], e.detail
    else:
        raise AssertionError("expected a 502")


_harness.run()
