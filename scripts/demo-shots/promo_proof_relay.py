import ast
import asyncio
import os
import runpy
import sys
import urllib.parse
from pathlib import Path

import uvicorn

HERE = Path(__file__).resolve().parent
_stats = {"received": 0, "processed": 0}


def _guard_curl_cffi() -> None:
    from curl_cffi import requests as cffi
    real = cffi.Session.request

    def guarded(self, method, url, *a, **k):
        if urllib.parse.urlsplit(str(url)).hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ConnectionRefusedError(f"proof: off-host curl_cffi refused: {url}")
        return real(self, method, url, *a, **k)

    cffi.Session.request = guarded


def _real_supervisor():
    import automation_executor as ax
    tree = ast.parse(Path(ax.__file__).read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "automation_supervisor")
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), ax.__file__, "exec"), ax.__dict__, ns)
    return ns["automation_supervisor"]


def _wire(app) -> None:
    from fastapi import HTTPException, Request

    import automation_executor as ax
    import employees
    import event_transcoder
    import events
    import server

    if hasattr(employees, "_AUDIT_SKIP_PREFIXES"):
        employees._AUDIT_SKIP_PREFIXES = (*employees._AUDIT_SKIP_PREFIXES, "/__proof/")
    _guard_curl_cffi()
    inner = event_transcoder.transcode

    async def counted(event):
        try:
            return await inner(event)
        finally:
            _stats["processed"] += 1

    event_transcoder.transcode = counted
    app.on_event("startup")(events.start_persist_worker)
    supervisor = _real_supervisor()

    async def start_supervisor() -> None:
        server._automation_exec_task = asyncio.create_task(supervisor(), name="automation-exec")

    app.on_event("startup")(start_supervisor)

    def _loopback(request: Request) -> None:
        if (request.client.host if request.client else "") not in ("127.0.0.1", "::1"):
            raise HTTPException(status_code=403, detail="proof hooks are loopback-only")

    async def of_ws_frame(request: Request) -> dict:
        _loopback(request)
        body = await request.json()
        frame = dict(body["frame"])
        frame["__account_id"] = str(body["account_id"])
        frame["__account_name"] = str(body["account_id"])
        _stats["received"] += 1
        await server._broadcast_event(frame)
        return {"ok": True}

    async def wake(request: Request) -> dict:
        _loopback(request)
        ax.wake_supervisor()
        return {"ok": True}

    async def idle(request: Request) -> dict:
        _loopback(request)
        return {"inflight": len(ax._inflight_tasks), "poked": sorted(map(list, ax._poked)), **_stats}

    async def env(request: Request) -> dict:
        _loopback(request)
        body = await request.json()
        for k, v in (body.get("set") or {}).items():
            os.environ[k] = str(v)
        for k in body.get("unset") or ():
            os.environ.pop(k, None)
        return {"ok": True}

    app.add_api_route("/__proof/of-ws-frame", of_ws_frame, methods=["POST"])
    app.add_api_route("/__proof/wake", wake, methods=["POST"])
    app.add_api_route("/__proof/idle", idle, methods=["GET"])
    app.add_api_route("/__proof/env", env, methods=["POST"])


def main() -> None:
    real_run = uvicorn.run

    def run(app, **kw):
        _wire(app)
        return real_run(app, **kw)

    uvicorn.run = run
    sys.argv = [str(HERE / "relay_guarded.py")]
    runpy.run_path(str(HERE / "relay_guarded.py"), run_name="__main__")


if __name__ == "__main__":
    main()
