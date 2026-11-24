"""Loopback fixture shim: Bombadil's browser origin, in front of the demo-shots `next dev`.

capture.py answers OnlyFans reads in its Playwright router; Bombadil drives its own Chrome,
so the same answers are served here at HTTP level instead (same Fixtures, same dataset):
  /api/*, /admin/* reads fixtures.py knows   -> fixture JSON (unmatched /api/* -> {} as capture.py)
  /img?u=<asset>, /__assets/<file>           -> scripts/demo-shots/assets
  POST /__ui-explore/reauth                 -> log in the seeded demo owner
  /auth/me, /chatter/me                      -> forwarded, created_at nulled (no trial nag, as capture.py)
  /admin/vault-ai/{image,thumb,poster}       -> the dataset's vault image (relay would fetch from OF)
  everything else (pages, HMR websocket, SSE) -> forwarded to next dev
The demo asset origin (https://demo-assets.invalid) is rewritten to /__assets in JSON bodies so
the browser never resolves it. Runs under demo-shots net_guard: loopback only.

    env UI_EXPLORE_NEXT=http://127.0.0.1:<next> UI_EXPLORE_PORT=<port> UI_EXPLORE_OUT=<dir> DEMO_SHOTS_TMP=<tmp>
"""
from __future__ import annotations

import asyncio
import json
import os
import runpy
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "demo-shots"
os.environ.setdefault("DEMO_SHOTS_PROCESS", "ui-explore-shim")
runpy.run_path(str(SHOTS / "net_guard.py"))
sys.path.insert(0, str(SHOTS))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.background import BackgroundTask  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import Response, StreamingResponse  # noqa: E402
from starlette.routing import Route, WebSocketRoute  # noqa: E402
from starlette.websockets import WebSocket, WebSocketDisconnect  # noqa: E402

import dataset  # noqa: E402
from fixtures import AssetRef, Fixtures  # noqa: E402
from seed_session import PASSWORD  # noqa: E402

NEXT = os.environ["UI_EXPLORE_NEXT"].rstrip("/")
PORT = int(os.environ["UI_EXPLORE_PORT"])
SELF = f"http://127.0.0.1:{PORT}"
OUT = Path(os.environ["UI_EXPLORE_OUT"])
ASSETS = SHOTS / "assets"
ASSET_ORIGIN = dataset.ASSET_ORIGIN
LOCAL_ASSETS = f"{SELF}/__assets"
RELAY_PREFIXES = ("/admin", "/api", "/auth", "/chatter", "/img", "/events", "/ws", "/health")
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "content-length",
       "proxy-authenticate", "proxy-authorization", "host", "accept-encoding"}

FX = Fixtures(dataset.build())
client = httpx.AsyncClient(timeout=httpx.Timeout(120, read=None), follow_redirects=False)
unmatched: set[str] = set()


def relay_bound(p: str) -> bool:
    return any(p == x or p.startswith(x + "/") for x in RELAY_PREFIXES)


def local(text: str) -> str:
    return text.replace(ASSET_ORIGIN, LOCAL_ASSETS)


def asset(url: str) -> Response:
    for origin in (ASSET_ORIGIN, LOCAL_ASSETS, "/__assets"):
        if url.startswith(origin + "/"):
            f = (ASSETS / url[len(origin) + 1:].split("?")[0]).resolve()
            if f.is_file() and ASSETS in f.parents:
                return Response(f.read_bytes(), media_type="image/jpeg", headers={"cache-control": "max-age=3600"})
    return Response(status_code=404)


def out_headers(res: httpx.Response, drop_length: bool) -> list[tuple[bytes, bytes]]:
    keep = []
    for k, v in res.headers.multi_items():
        lk = k.lower()
        if lk in HOP and not (lk == "content-length" and not drop_length):
            continue
        if lk == "location":
            v = v.replace(NEXT, SELF)
        keep.append((lk.encode("latin-1"), v.encode("latin-1")))
    return keep


async def static_chunk(up: httpx.Request) -> Response:
    """next dev (webpack) rewrites chunks in place when it compiles a route on demand; a chunk read
    meanwhile ends short ("peer closed connection without sending complete message body") and the
    page dies on a SyntaxError / ChunkLoadError no production build can produce. Buffer and retry."""
    for attempt in range(5):
        try:
            res = await client.send(up)
            break
        except httpx.RemoteProtocolError:
            if attempt == 4:
                raise
            await asyncio.sleep(1)
    r = Response(res.content, status_code=res.status_code)
    r.raw_headers = out_headers(res, True) + [(b"content-length", str(len(res.content)).encode())]
    return r


async def forward(req: Request, mutate=None, *, path: str | None = None, body: bytes | None = None) -> Response:
    url = NEXT + (path or req.url.path) + (f"?{req.url.query}" if req.url.query else "")
    headers = [(k, v) for k, v in req.headers.items() if k.lower() not in HOP]
    headers.append(("accept-encoding", "identity"))
    if body is None:
        body = await req.body()
    up = client.build_request(req.method, url, headers=headers, content=body or None)
    if req.url.path.startswith("/_next/static/"):
        return await static_chunk(up)
    res = await client.send(up, stream=True)
    ctype = res.headers.get("content-type", "")
    if "json" in ctype or mutate:
        raw = await res.aread()
        await res.aclose()
        text = raw.decode("utf-8", "replace")
        if mutate:
            text = mutate(text)
        r = Response(local(text).encode(), status_code=res.status_code)
        r.raw_headers = out_headers(res, True) + [(b"content-length", str(len(r.body)).encode())]
        return r
    r = StreamingResponse(res.aiter_raw(), status_code=res.status_code, background=BackgroundTask(res.aclose))
    r.raw_headers = out_headers(res, False)
    return r


# The relay renders these from OnlyFans with the account's session; the seeded session files are
# stubs (no OF login), so the relay 500s on them. Serve the dataset's vault image instead.
VAULT_STILLS = ("/admin/vault-ai/image", "/admin/vault-ai/thumb", "/admin/vault-ai/poster")


def vault_file(media_id: str) -> str:
    vault = FX.d.vault
    hit = next((v for v in vault if str(v["id"]) == media_id), None)
    return (hit or vault[int(media_id) % len(vault) if media_id.isdigit() else 0])["file"]


def no_created_at(text: str) -> str:
    try:
        body = json.loads(text)
    except ValueError:
        return text
    if isinstance(body, dict):
        body["created_at"] = None
    return json.dumps(body)


async def http(req: Request) -> Response:
    p = req.url.path
    if p.startswith("/__assets/"):
        return asset(p)
    if p == "/__ui-explore/reauth" and req.method == "POST":
        if req.headers.get("origin") != SELF or req.headers.get("content-type") != "application/json":
            return Response(status_code=403)
        owner = {"username": dataset.OWNER_USERNAME, "password": PASSWORD}
        return await forward(req, path="/auth/login", body=json.dumps(owner).encode())
    if not relay_bound(p):
        return await forward(req)
    q = parse_qs(req.url.query)
    if p == "/img" or p.startswith("/img/"):
        return asset((q.get("u") or [""])[0])
    if p in ("/auth/me", "/chatter/me"):
        return await forward(req, no_created_at)
    if p == "/events" or p.startswith("/ws"):
        return await forward(req)
    if p in VAULT_STILLS:
        return asset(f"/__assets/{vault_file((q.get('media_id') or ['0'])[0])}")
    body = FX.answer(req.method, p, q, req.headers.get("x-account-id"))
    if isinstance(body, AssetRef):
        return asset(body)
    if body is not None:
        return Response(local(json.dumps(body)), media_type="application/json")
    if p.startswith("/api/"):
        key = f"{req.method} {p}"
        if key not in unmatched:
            unmatched.add(key)
            with open(OUT / "shim-unmatched.txt", "a") as f:
                f.write(key + "\n")
        return Response("{}", media_type="application/json")
    return await forward(req)


# next dev (webpack) broadcasts this to every open page when it compiles a route on demand; a page
# still hydrating then throws "Router action dispatched before initialization" (dev-only race, no
# source edits happen during a run). Dropped so it never reads as a product exception.
HMR_DROP = '"type":"serverComponentChanges"'


async def ws(sock: WebSocket) -> None:
    path = sock.url.path + (f"?{sock.url.query}" if sock.url.query else "")
    target = "ws" + NEXT[len("http"):] + path
    try:
        up = await websockets.connect(target, open_timeout=30, max_size=None,
                                      additional_headers={"origin": NEXT})
    except Exception:
        await sock.close(code=1011)
        return
    await sock.accept()

    async def down():
        async for m in up:
            if isinstance(m, str) and HMR_DROP in m and path.startswith("/_next/webpack-hmr"):
                continue
            await (sock.send_bytes(m) if isinstance(m, bytes) else sock.send_text(m))

    async def upstream():
        while True:
            m = await sock.receive()
            if m["type"] == "websocket.disconnect":
                return
            await up.send(m.get("bytes") or m.get("text") or "")

    tasks = [asyncio.create_task(down()), asyncio.create_task(upstream())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await up.close()
        try:
            await sock.close()
        except Exception:
            pass


METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
app = Starlette(routes=[Route("/{path:path}", http, methods=METHODS), WebSocketRoute("/{path:path}", ws)])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, loop="asyncio", log_level="warning")
