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
