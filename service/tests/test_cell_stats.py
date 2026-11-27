#!/usr/bin/env python3

import _harness

import asyncio  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import cell_stats  # noqa: E402


def _reset():
    cell_stats._buckets.clear()
    cell_stats._spills = 0


def test_route_p95_over_the_window_and_old_minutes_drop():
    _reset()
    now = 1_000_000.0
    real = time.time
    try:
        time.time = lambda: now - 400
        cell_stats.route("GET /old", 9999)
        time.time = lambda: now - 120
        for ms in range(1, 101):
            cell_stats.route("GET /admin/chats/recent", float(ms))
        time.time = lambda: now
        cell_stats.route("GET /admin/chats/recent", 1000.0)
    finally:
        time.time = real
    snap = cell_stats.snapshot(now)
    assert "GET /old" not in snap["routes"], snap
    r = snap["routes"]["GET /admin/chats/recent"]
    assert r["n"] == 101 and r["p95_ms"] == 96.0, r
    assert snap["window_s"] == 300 and snap["pool_wait_p95_ms"] is None


def test_pool_wait_and_spills_in_window():
    _reset()

    class Pool:
        spills = 3

    slow = cell_stats.timed(lambda pool: time.sleep(0.02) or "conn")
    assert slow(Pool()) == "conn"
    snap = cell_stats.snapshot()
    assert snap["pool_waits"] == 1 and snap["pool_wait_p95_ms"] >= 15, snap
    assert snap["spills"] == 3, snap
    Pool.spills = 5
    slow(Pool())
    assert cell_stats.snapshot()["spills"] == 5


def test_instrument_wraps_once():
    class Pool:
        spills = 0

        def _do_get(self):
            return "c"

    cell_stats.instrument(Pool)
    first = Pool._do_get
    cell_stats.instrument(Pool)
    assert Pool._do_get is first and Pool()._do_get() == "c"


def test_request_log_records_matched_routes_only():
    _reset()
    import httpx
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from request_log import RequestLog

    async def chat(request):
        return JSONResponse({"ok": True})

    app = RequestLog(Starlette(routes=[Route("/api/of/v2/chats/{chat_id}/messages", chat, methods=["POST"])]))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            await c.post("/api/of/v2/chats/42/messages")
            await c.get("/nope/123")

    was = cell_stats.ENABLED
    cell_stats.ENABLED = True
    try:
        asyncio.run(go())
    finally:
        cell_stats.ENABLED = was
    routes = cell_stats.snapshot()["routes"]
    assert list(routes) == ["POST /api/of/v2/chats/{chat_id}/messages"], routes
    _reset()
    asyncio.run(go())
    assert cell_stats.snapshot()["routes"] == {}, "env unset: nothing recorded"


def test_write_is_atomic_json():
    _reset()
    cell_stats.route("GET /x", 5.0)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / cell_stats.FILE
        cell_stats.write(p)
        doc = json.loads(p.read_text())
        assert doc["routes"]["GET /x"] == {"n": 1, "p95_ms": 5.0}
        assert [x.name for x in Path(d).iterdir()] == [cell_stats.FILE]


if __name__ == "__main__":
    _harness.run()
