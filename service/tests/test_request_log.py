#!/usr/bin/env python3
"""request_log.RequestLog: one `req id=… path=<template> status=… ms=…` line per
request on the relay's real middleware stack, X-Request-Id echoed (incoming one
honoured, cleaned), health probes skipped, CHATTERLY_SLOW_REQ_MS flips the line
to WARNING, SSE is `stream=1` and never warns, an unhandled error is a 500 line
and its /admin/errors row carries the request id.

Run: ./venv/bin/python service/tests/test_request_log.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

from fastapi import Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.responses import StreamingResponse  # noqa: E402

import _agency_fixtures as fx  # noqa: E402

CLIENT = _harness.make_client()
import server  # noqa: E402

IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")


@server.app.get("/__reqlog/{account_id}/echo")
def _echo(account_id: str, request: Request):
    return {"rid": request.state.request_id}


@server.app.get("/__reqlog_slow")
def _slow():
    time.sleep(0.02)
    return {"ok": True}


@server.app.get("/__reqlog_sse")
async def _sse():
    async def frames():
        yield b"data: one\n\n"
    return StreamingResponse(frames(), media_type="text/event-stream")


@server.app.get("/__reqlog_boom")
def _boom():
    raise RuntimeError("reqlog-boom")


class _Tap(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[tuple[int, str]] = []

    def emit(self, record):
        msg = record.getMessage()
        if msg.startswith("req id="):
            self.lines.append((record.levelno, msg))


def _logged(client, path, **kw):
    """(response, [(level, line)]) for one request."""
    tap = _Tap()
    logging.getLogger("of-relay").addHandler(tap)
    try:
        r = client.get(path, **kw)
    finally:
        logging.getLogger("of-relay").removeHandler(tap)
    return r, tap.lines


def case_one_line_with_id_template_status_ms_and_state():
    r, lines = _logged(CLIENT, "/__reqlog/12345678/echo")
    assert r.status_code == 200, r.text
    rid = r.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{10}", rid), rid
    assert r.json()["rid"] == rid, "request.state.request_id is the echoed id"
    assert len(lines) == 1, lines
    level, line = lines[0]
    assert level == logging.INFO, lines
    assert re.fullmatch(rf"req id={rid} method=GET path=/__reqlog/{{account_id}}/echo "
                        r"status=200 ms=\d+\.\d acct=12345678", line), line


def case_incoming_id_honoured_and_cleaned():
    r, lines = _logged(CLIENT, "/__reqlog/1/echo", headers={"X-Request-Id": "abc123"})
    assert r.headers["x-request-id"] == "abc123", r.headers
    assert lines[0][1].startswith("req id=abc123 "), lines
    r, lines = _logged(CLIENT, "/__reqlog/1/echo", headers={"X-Request-Id": "a b;c=" + "x" * 99})
    assert r.headers["x-request-id"] == "abc" + "x" * 61, r.headers


def case_signed_in_owner_is_user():
    r, lines = _logged(OWNER_A, "/__reqlog/1/echo")
    assert r.status_code == 200, r.text
    assert f" user={IDS['agency_a_owner']}" in lines[0][1], lines


def case_health_probes_not_logged():
    for path in ("/livez", "/health"):
        r, lines = _logged(CLIENT, path)
        assert lines == [], (path, lines)
        assert "x-request-id" not in r.headers, (path, r.headers)


def case_slow_threshold_flips_to_warning():
    os.environ["CHATTERLY_SLOW_REQ_MS"] = "1"
    try:
        _r, lines = _logged(CLIENT, "/__reqlog_slow")
        _r, sse = _logged(CLIENT, "/__reqlog_sse")
    finally:
        os.environ.pop("CHATTERLY_SLOW_REQ_MS")
    assert lines[0][0] == logging.WARNING, lines
    assert sse[0][0] == logging.INFO and sse[0][1].endswith(" stream=1"), sse
    _r, lines = _logged(CLIENT, "/__reqlog_slow")
    assert lines[0][0] == logging.INFO, lines


def case_404_gets_a_line_and_the_header():
    r, lines = _logged(CLIENT, "/no/such/route")
    assert r.status_code == 404, r.status_code
    assert r.headers.get("x-request-id"), r.headers
    assert " path=/no/such/route status=404 " in lines[0][1], lines


def case_unhandled_error_logs_500_and_reraises():
    client = TestClient(server.app, raise_server_exceptions=False)
    r, lines = _logged(client, "/__reqlog_boom")
    assert r.status_code == 500, r.status_code
    assert " path=/__reqlog_boom status=500 " in lines[0][1], lines
    rid = lines[0][1].split()[1].removeprefix("id=")
    errs = OWNER_A.get("/admin/errors").json()
    mine = [e for e in errs["list"] if "reqlog-boom" in (e.get("message") or "")]
    assert mine and mine[0]["context"] == {"request_id": rid}, (rid, mine)


_harness.run()
