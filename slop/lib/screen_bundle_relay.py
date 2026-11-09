"""Relay hooks for screen-bundle and inline-boot scenarios.

The HTML's inline boot (app/lib/inlineBoot.server.ts) seen from the relay, outermost hook (no product code):

      GET  /__slop/server-reads   the reads the Next server sent for a document's HTML (Node's fetch: user agent
           `node` / `undici*`; the browser's own calls through the rewrites keep its user agent), each
           {path (+query), status, t0, t1} in wall-clock seconds, since this relay's start.
      POST /__slop/screens-404 {on}  every /admin/screens/* answers 404 (the per-Creator path), for the browser and
           the Next server alike: a page route would only reach the browser's calls.
      The Next server's /admin/screens/* read for a browser with the no-bundles cookie (actors/ui.py:
      its page route 404s the bundles) answers 404 too.
      POST /__slop/server-wire {path, mode}  the Next server's reads of `path` (exact) meet what a scenario's page
           route does to the browser's: mode 403 (a blocking proxy's HTML 403) or "hold" (a relay that never
           answers: held until the mode changes, then forwarded on release or answered 403 on switch; after
           HOLD_MAX_S it answers 504 (the server's own INLINE_TIMEOUT_MS normally gives up first); null lifts it.
           The proxy and the silent relay a scenario stands in for
           sit in front of the relay, on the leg the browser's rewrites and the server's reads both take (RELAY_URL).
"""
from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import Request
from starlette.responses import HTMLResponse, JSONResponse
if __package__:
    from .screen_bundle import CHAT_SCREEN_PATH, NO_BUNDLES_COOKIE
else:
    from screen_bundle import CHAT_SCREEN_PATH, NO_BUNDLES_COOKIE

HOLD_MAX_S = 10.0


def wire(app, _loopback, _relay) -> None:
    import server

    reads: deque[dict] = deque(maxlen=4096)
    screens_404 = {"on": False}
    server_wire: dict[str, object] = {}
    releases: dict[str, asyncio.Event] = {}

    async def held(path: str):
        deadline = time.monotonic() + HOLD_MAX_S
        while server_wire.get(path) == "hold":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"
            event = releases.setdefault(path, asyncio.Event())
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return "timeout"
        return server_wire.get(path)

    async def inline_hook(request, call_next):
        t0 = time.time()
        path = request.url.path
        ua = request.headers.get("user-agent", "")
        server_read = ua == "node" or ua.startswith("undici")
        no_bundles = server_read and f"{NO_BUNDLES_COOKIE}=1" in request.headers.get("cookie", "")
        wire = server_wire.get(path) if server_read else None
        if (screens_404["on"] or (no_bundles and path != CHAT_SCREEN_PATH)) and path.startswith("/admin/screens/"):
            resp = JSONResponse({"detail": "slop: per-Creator path"}, status_code=404)
        elif wire == 403:
            resp = HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
        elif wire == "hold":
            mode = await held(path)
            resp = (HTMLResponse("<h1>403 Forbidden</h1>", status_code=403) if mode == 403
                    else JSONResponse({"detail": "slop: held"}, status_code=504) if mode == "timeout"
                    else await call_next(request))
        else:
            resp = await call_next(request)
        if server_read:
            q = request.url.query
            reads.append({"path": path + (f"?{q}" if q else ""), "status": resp.status_code,
                          "t0": t0, "t1": time.time()})
        return resp

    server._http_hooks.add(inline_hook)

    async def server_reads(request: Request) -> dict:
        _loopback(request)
        return {"reads": list(reads)}

    async def set_screens_404(request: Request) -> dict:
        _loopback(request)
        screens_404["on"] = bool((await request.json()).get("on"))
        return dict(screens_404)

    async def set_server_wire(request: Request) -> dict:
        _loopback(request)
        body = await request.json()
        mode = body.get("mode")
        if mode not in (None, 403, "hold"):
            return JSONResponse({"detail": f"mode {mode!r}: 403, 'hold' or null"}, status_code=400)
        if mode is None:
            server_wire.pop(body["path"], None)
        else:
            server_wire[body["path"]] = mode
        if event := releases.get(body["path"]):
            event.set()
        releases[body["path"]] = asyncio.Event()
        return dict(server_wire)

    app.add_api_route("/__slop/server-reads", server_reads, methods=["GET"])
    app.add_api_route("/__slop/screens-404", set_screens_404, methods=["POST"])
    app.add_api_route("/__slop/server-wire", set_server_wire, methods=["POST"])
