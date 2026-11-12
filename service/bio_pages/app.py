"""The public bio app (ofl.ink's pages, ported): a standalone ASGI app served by uvicorn on BIO_PORT.

One catch-all endpoint dispatches every method and path in ofl.ink v2's Hono order (server.js), on Hono's view of
the path (hono.url_path / route_path). FileResponse adds ETag, Last-Modified and Accept-Ranges headers and
supports Range (206) beyond v2's file response. It mounts nothing of the
relay's: no /admin, /auth, /t/, SSE or session middleware exists on this port. It never logs a request, a row or an
error's message: a Link holds its destination.
"""
from __future__ import annotations

import logging
from pathlib import Path
import re
import asyncio

from sqlalchemy.exc import OperationalError

from starlette.requests import Request
from starlette.responses import FileResponse, Response

from bio_pages import assets, decide, files, guard, hono, store
from bio_pages.config import BioConfig
from client_addr import client_address

log = logging.getLogger("of-relay.bio")

MR = "public, max-age=0, must-revalidate"
IMM = "public, max-age=31536000, immutable"
HTML = "text/html; charset=utf-8"
JSON = "application/json"
TYPES = {".html": HTML, ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".webp": "image/webp", ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8"}

CONFIG = BioConfig.from_env()
INDEX_HTML = decide.render_index(assets.INDEX.read_text(encoding="utf-8"), CONFIG.escape_tap)
LANDING = (assets.PUBLIC / "landing.html").read_bytes()
ASSETS = {str(p.relative_to(assets.PUBLIC)): p.read_bytes() for p in assets.PUBLIC.rglob("*") if p.is_file()}

PRIMARY = CONFIG.primary_hosts
FILES_DIR = CONFIG.files_dir
guard.configure(CONFIG.reveal_limit)

_PROFILE_FILE = re.compile(r"/api/profiles/([^/]+)")
_PING = re.compile(r"/v/([^/]+)")
_FILES = re.compile(r"/api/files/([^/]+)/([^/]+)/([^/]+)")


def _r(status: int, body: bytes = b"", headers: dict | None = None) -> Response:
    return Response(body, status_code=status, headers=headers or {})


def _json(status: int, value, cc: str | None = None) -> Response:
    return _r(status, decide.to_json(value), {"content-type": JSON, **({"cache-control": cc} if cc else {})})


def _under(prefix: str, path: str) -> bool:
    """Hono's `/x/*`, which also matches `/x`."""
    return path == prefix or path.startswith(prefix + "/")


class _Req:
    def __init__(self, request: Request):
        self.request = request
        self.method = request.method
        raw = request.scope.get("raw_path") or request.scope["path"].encode("utf-8")
        if len(raw) + len(request.scope.get("query_string", b"")) > 16 * 1024:
            raise _LongTarget
        self.url_path = hono.url_path(raw.split(b"?", 1)[0])  # some servers keep the query in raw_path
        self.path = hono.route_path(self.url_path)

    def hdr(self, name: str) -> str | None:
        vals = self.request.headers.getlist(name)
        return ", ".join(vals) if vals else None

    def query(self, key: str) -> str | None:
        vals = self.request.query_params.getlist(key)
        return vals[0] if vals else None  # Hono: first occurrence wins


async def _resolve(host: str | None) -> tuple[decide.HostKind, str | None]:
    kind, name = decide.host_kind(host, PRIMARY)
    if kind != "lookup":
        return kind, None
    return await store.resolve_host_row(name)


async def _profile_json(file: str) -> Response:
    name = decide.lookup_username(file[:-5])
    found = await store.profile_with_links(name) if name else None
    if not found:
        return _json(404, {"error": "Profile not found"}, MR)
    return _json(200, decide.public_profile(*found), MR)


async def _ping(q: _Req, username: str) -> Response:
    cc = "no-store"
    name = decide.lookup_username(username)
    if name and not guard.allow_ping(str(client_address(q.request)), name):
        return _json(429, {"error": "Too many requests"}, cc)
    profile = await store.profile_at(name) if name else None
    if not profile:
        return _json(404, {"error": "Profile not found"}, cc)
    await store.record("view", profile["id"], "", decide.event_country(q.hdr), decide.in_app(q.hdr), "")
    return _r(204, b"", {"cache-control": cc})


async def _reveal(q: _Req) -> Response:
    cc = "no-store"
    if not decide.same_origin(q.hdr):
        return _json(403, {"error": "Cross-origin request refused"}, cc)
    if not guard.allow(str(client_address(q.request))):
        return _json(429, {"error": "Too many requests"}, cc)
    location = decide.visitor_location(q.hdr)
    link_id = q.query("id")
    link = await store.link_by_link_id(link_id) if link_id and decide.LINK_ID.fullmatch(link_id) else None
    url, code = decide.reveal(link, q.query("trackingId"), location)
    if not url:
        return _json(404, {"error": "Link not found"}, cc)
    await store.record("click", link["profile_id"], link["id"], decide.event_country(q.hdr), decide.in_app(q.hdr),
                       code if link["tracking"] else "")
    return _json(200, {"realUrl": url}, cc)


def _file(collection: str, record_id: str, filename: str) -> Response:
    path = files.safe_path(FILES_DIR, collection, record_id, filename)
    if path:
        ctype = "image/webp" if filename.endswith(".webp") else "application/octet-stream"
        return FileResponse(path, media_type=ctype, headers={"cache-control": IMM})
    return _r(404)


async def _tls_ask(q: _Req) -> Response:
    cc = {"cache-control": "no-store"}
    domain = q.query("domain")
    if not domain or not decide.is_askable(domain, PRIMARY):
        return _r(400, b"", cc)
    try:
        kind, _ = await _resolve(domain)
    except Exception:  # noqa: BLE001  a DB that cannot be read is Caddy's "no" too
        return _r(503, b"", cc)
    return _r(404 if kind == "unknown" else 200, b"", cc)


def _landing(status: int) -> Response:
    return _r(status, LANDING, {"content-type": HTML, "cache-control": MR})


async def _page(q: _Req) -> Response:
    key = assets.public_key(q.path)
    if key in ASSETS:
        return _r(200, ASSETS[key],
                  {"content-type": TYPES.get(Path(key).suffix, "application/octet-stream"),
                                        "cache-control": MR})
    kind, custom = await _resolve(q.hdr("host"))
    req = decide.resolve_profile_request(kind, custom, q.url_path)
    if req is not None and req["username"] == "" and req["trackingCode"] is None:
        return _landing(200)
    page = decide.bootstrap_page(INDEX_HTML, req).encode("utf-8")
    return _r(200, page, {"content-type": HTML, "cache-control": MR})


async def _dispatch(q: _Req) -> Response:
    m, p = q.method, q.path
    get = m in ("GET", "HEAD")
    if get and (mm := _PROFILE_FILE.fullmatch(p)):
        file = hono.param(mm.group(1))
        if file.endswith(".json"):
            return await _profile_json(file)
    if m == "POST" and (mm := _PING.fullmatch(p)):
        return await _ping(q, hono.param(mm.group(1)))
    if get and p == "/.netlify/functions/reveal":
        return await _reveal(q)
    if get and (mm := _FILES.fullmatch(p)):
        return _file(*map(hono.param, mm.groups()))
    if _under("/api", p):
        return _json(404, {"error": "Not found"})
    if get and _under("/edit", p):
        return _landing(404)  # the editor moved into inflowwww (PR2); never a link to it
    if get and p == "/internal/healthz":
        return _r(200, b"", {"cache-control": "no-store"})
    if get and p == "/internal/tls-ask":
        return await _tls_ask(q)
    if get and _under("/netlify", p):
        return _landing(404)
    if get:
        return await _page(q)
    return _r(404, b"404 Not Found", {"content-type": "text/plain; charset=UTF-8"})


_last_db_warning = 0.0


def _log_db_unavailable(error_class: str) -> None:
    global _last_db_warning
    now = asyncio.get_running_loop().time()
    if now - _last_db_warning >= 10:
        log.warning("bio: request database unavailable %s", error_class)
        _last_db_warning = now


async def endpoint(request: Request) -> Response:
    try:
        q = _Req(request)
        resp = await _dispatch(q)
    except _LongTarget:
        resp = _r(431)
    except OperationalError as e:
        _log_db_unavailable(type(e).__name__)
        resp = _json(503, {"error": "Temporarily unavailable"}, "no-store")
    except Exception as e:  # noqa: BLE001  a fixed line: an error can carry a row, and a row a destination
        log.error("bio: request failed %s", type(e).__name__)
        resp = _json(500, {"error": "Internal error"}, "no-store")
    if request.method == "HEAD":
        resp.body = b""
    return resp


SHUTDOWN_DRAIN_SECONDS = 35


async def app(scope, receive, send) -> None:
    """The ASGI app: every method and path to `endpoint` (a Starlette Route would answer 405, fold slashes and decode
    `%2F` before we see the path)."""
    if scope["type"] == "lifespan":
        task = None
        stop = asyncio.Event()
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                task = asyncio.create_task(store.flush_loop(CONFIG.flush_seconds, stop))
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                stop.set()
                if task:
                    await task
                if store._flush_task:
                    await store._flush_task
                # 5s uvicorn graceful phase + 35s drain < 45s compose/Stack stop grace.
                deadline = asyncio.get_running_loop().time() + SHUTDOWN_DRAIN_SECONDS
                while not await store.flush() and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.2)
                keys, views, clicks = store.pending()
                if keys or store.capped_drops():
                    log.error("bio: shutdown counter drain lost keys=%d views=%d clicks=%d dropped=%d",
                              keys, views, clicks, store.capped_drops())
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return
    request = Request(scope, receive)
    await (await endpoint(request))(scope, receive, send)


class _LongTarget(Exception):
    pass
