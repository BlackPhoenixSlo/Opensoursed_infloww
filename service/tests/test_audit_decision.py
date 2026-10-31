#!/usr/bin/env python3
"""
audit_log.audit_decision — table tests over which finished request the audit
middleware logs to `actions`, and under which `actions.action`:

  case_table:        normal writes, the app's BACKGROUND_WRITES (audited like
                     any write), each skip prefix, reads, non-2xx answers.
  case_skip_seam:    the middleware's prefixes are read through employees,
                     where slop/lib/relay.py extends them.
  case_reexports:    employees still exports what its importers use.

Run: ./venv/bin/python service/tests/test_audit_decision.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import audit_log  # noqa: E402
from audit_log import _AUDIT_SKIP_PREFIXES, BACKGROUND_WRITES, audit_decision, audited  # noqa: E402

# (method, path, status) -> action or None
TABLE = [
    ("POST", "/admin/employees", 200, "POST /admin/employees"),
    ("PATCH", "/admin/employees/7", 204, "PATCH /admin/employees/7"),
    ("PUT", "/admin/employees/7/setup", 299, "PUT /admin/employees/7/setup"),
    ("DELETE", "/admin/employees/7", 200, "DELETE /admin/employees/7"),
    ("POST", "/api/of/v2/chats/1/messages", 201, "POST /api/of/v2/chats/1/messages"),
    ("POST", "/admin/perflog/flush", 200, "POST /admin/perflog/flush"),
    ("POST", "/admin/errors", 200, "POST /admin/errors"),
    ("GET", "/admin/employees", 200, None),
    ("HEAD", "/admin/employees", 200, None),
    ("OPTIONS", "/admin/employees", 200, None),
    ("post", "/admin/employees", 200, None),
    ("POST", "/admin/employees", 199, None),
    ("POST", "/admin/employees", 300, None),
    ("POST", "/admin/employees", 400, None),
    ("POST", "/admin/employees", 403, None),
    ("POST", "/admin/employees", 500, None),
    ("POST", "/", 200, "POST /"),
    ("POST", "/healthz", 200, None),            # prefix match, not segment
    ("POST", "/admin/auditor", 200, None),
    ("POST", "/admin/login/start", 200, None),  # body carries the OF password
    ("POST", "/admin/shifts/clock-heartbeat", 200, None),
    ("POST", "/admin/shifts/clock-in", 200, "POST /admin/shifts/clock-in"),
    ("POST", "/__slop/of-ws-frame", 200, "POST /__slop/of-ws-frame"),  # default prefixes only
]


def case_table():
    bad = []
    rows = list(TABLE)
    rows += [(m, p + "x", 200, f"{m} {p}x") for m, p in BACKGROUND_WRITES]
    rows += [(m, p, 200, None) for p in _AUDIT_SKIP_PREFIXES for m in ("POST", "PATCH", "PUT", "DELETE")]
    for method, path, status, want in rows:
        got = audit_decision(method, path, status, should_audit=audited(method, path, _AUDIT_SKIP_PREFIXES))
        if got != want:
            bad.append(f"{method} {path} {status}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)
    assert not audited("POST", "/__slop/of-ws-frame", (*_AUDIT_SKIP_PREFIXES, "/__slop/"))


def case_skip_seam():
    import asyncio
    import employees
    from starlette.requests import Request
    from starlette.responses import Response

    seen = []
    saved = employees._AUDIT_SKIP_PREFIXES, audit_log._write_action
    async def _write(**kw):
        seen.append(kw["action"])
    audit_log._write_action = _write
    employees._AUDIT_SKIP_PREFIXES = (*employees._AUDIT_SKIP_PREFIXES, "/__slop/")

    async def call(path: str, status: int) -> None:
        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}
        req = Request({"type": "http", "method": "POST", "path": path, "headers": [],
                       "query_string": b""}, receive)
        async def nxt(_r):
            return Response(status_code=status)
        await audit_log.audit_middleware(req, nxt)

    try:
        asyncio.run(call("/__slop/of-ws-frame", 200))
        asyncio.run(call("/admin/x/y", 500))
        asyncio.run(call("/admin/x/y", 200))
        assert seen == ["POST /admin/x/y"], seen
    finally:
        employees._AUDIT_SKIP_PREFIXES, audit_log._write_action = saved


def case_reexports():
    import agency_context
    import employees
    assert employees.audit_middleware is audit_log.audit_middleware
    assert employees.BACKGROUND_WRITES is audit_log.BACKGROUND_WRITES
    assert employees.audit_action is audit_log.audit_action
    assert employees._AUDIT_SKIP_PREFIXES is audit_log._AUDIT_SKIP_PREFIXES
    assert employees._safe_snapshot is audit_log._safe_snapshot
    assert employees.AgencyContext is agency_context.AgencyContext
    assert employees.owner_context is agency_context.owner_context
    assert employees.agency_context is agency_context.agency_context
    assert employees.agency_contexts is agency_context.agency_contexts
    assert employees._chatter_agency_for_creator is agency_context._chatter_agency_for_creator  # clock_api


if __name__ == "__main__":
    _harness.run()
