#!/usr/bin/env python3
"""`/ws/events` is gone: it streamed every account's OF events with no auth, and
nothing in app/ or desktop/ used it. The browser app reads `/events` (SSE).

  case_ws_events_is_not_routed
  case_sse_events_is_still_routed

Run: ./venv/bin/python service/tests/test_ws_events_removed.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import server  # noqa: E402


def _paths():
    return {getattr(r, "path", None) for r in server.app.routes}


def case_ws_events_is_not_routed():
    assert "/ws/events" not in _paths(), "unauthenticated /ws/events is routed again"


def case_sse_events_is_still_routed():
    assert "/events" in _paths(), "/events (SSE) missing"


_harness.run()
