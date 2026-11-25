#!/usr/bin/env python3
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
