#!/usr/bin/env python3
"""Response gzip (backend 1.5) and the SQLite pragmas (backend 1.20).

  • A JSON body ≥ 1 KiB leaves the relay gzip-encoded when the client accepts
    it; a small one does not; an SSE stream and a media type never are (SSE
    must flush frame by frame through the compressor), including every type
    /img can stream through from the CDN (any image/*, video, octet-streams).
  • Every pooled SQLite connection opens with mmap_size and temp_store=MEMORY;
    init_db leaves planner stats behind (sqlite_stat1); `db.engine.optimize()`
    runs clean with analysis_limit set.

Run:  ./venv/bin/python service/tests/test_gzip_and_pragmas.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from fastapi.responses import JSONResponse, Response, StreamingResponse  # noqa: E402
from sqlalchemy import text  # noqa: E402

from db.engine import engine as db_async_engine, optimize as db_optimize  # noqa: E402

client = _harness.make_client()

import server  # noqa: E402  — already imported by make_client


def _probe_routes() -> None:
    """Throwaway routes under a public prefix so the probe needs no login."""
    async def _big():
        return JSONResponse({"rows": [{"id": i, "text": "hello there"} for i in range(200)]})

    async def _small():
        return JSONResponse({"ok": True})

    async def _sse():
        async def _gen():
            for i in range(3):
                yield f"event: ping\ndata: {'x' * 600}{i}\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream")

    async def _img():
        return Response(b"\x89PNG" + b"\0" * 4096, media_type="image/png")

    async def _media_stream(ct: str):
        # Shaped like /img: chunks streamed with the CDN's Content-Type as-is.
        async def _gen():
            for _ in range(4):
                yield b"\0" * 2048
        return StreamingResponse(_gen(), media_type=ct)

    for path, fn in (("big", _big), ("small", _small), ("sse", _sse), ("img", _img),
                     ("stream", _media_stream)):
        server.app.add_api_route(f"/healthz/gzprobe/{path}", fn, methods=["GET"])


_probe_routes()
GZ = {"Accept-Encoding": "gzip"}


def case_gzip_middleware_registered():
    mw = [m for m in server.app.user_middleware if m.cls.__name__ == "GZipMiddleware"]
    assert len(mw) == 1, server.app.user_middleware
    assert server.app.user_middleware[-1].cls.__name__ == "GZipMiddleware", \
        "gzip must be the innermost layer (outer http hooks re-chunk bodies)"
    opts = mw[0].kwargs
    assert opts["minimum_size"] == 1024, opts
    assert "text/event-stream" in opts["exclude_content_types"], opts


def case_big_json_is_gzipped():
    r = client.get("/healthz/gzprobe/big", headers=GZ)
    if r.status_code in (401, 403):
        raise AssertionError(f"probe route not public: {r.status_code}")
    assert r.status_code == 200, r.status_code
    assert r.headers.get("content-encoding") == "gzip", dict(r.headers)
    assert len(r.json()["rows"]) == 200  # TestClient decodes transparently


def case_small_json_and_no_accept_stay_plain():
    r = client.get("/healthz/gzprobe/small", headers=GZ)
    assert r.headers.get("content-encoding") is None, dict(r.headers)
    r = client.get("/healthz/gzprobe/big", headers={"Accept-Encoding": "identity"})
    assert r.headers.get("content-encoding") is None, dict(r.headers)


def case_sse_and_media_never_gzipped():
    r = client.get("/healthz/gzprobe/sse", headers=GZ)
    assert r.headers.get("content-encoding") is None, dict(r.headers)
    assert r.text.count("event: ping") == 3
    r = client.get("/healthz/gzprobe/img", headers=GZ)
    assert r.headers.get("content-encoding") is None, dict(r.headers)


def case_img_style_streams_never_gzipped():
    for ct in ("image/jpeg", "image/heic", "image/svg+xml", "video/mp4", "audio/mpeg",
               "application/octet-stream", "binary/octet-stream"):
        r = client.get("/healthz/gzprobe/stream", params={"ct": ct}, headers=GZ)
        assert r.status_code == 200, (ct, r.status_code)
        assert r.headers.get("content-encoding") is None, (ct, dict(r.headers))
        assert len(r.content) == 8192, (ct, len(r.content))
    r = client.get("/healthz/gzprobe/stream", params={"ct": "application/json"}, headers=GZ)
    assert r.headers.get("content-encoding") == "gzip", "the exclusions must stay narrow"


async def case_sqlite_pragmas_on_connect():
    async with db_async_engine.connect() as conn:
        temp_store = (await conn.execute(text("PRAGMA temp_store"))).scalar()
        mmap = (await conn.execute(text("PRAGMA mmap_size"))).scalar()
    assert temp_store == 2, f"temp_store={temp_store} (2 = MEMORY)"
    assert mmap == 268435456, f"mmap_size={mmap}"
    await db_optimize()  # must run clean on a live DB


async def case_init_db_optimizes_once_not_per_connection():
    import inspect

    from db.engine import _set_sqlite_pragmas, init_db
    src = inspect.getsource(init_db)
    listener = inspect.getsource(_set_sqlite_pragmas)
    assert "optimize" not in listener, "optimize must not run on every pooled connect"
    assert "analysis_limit" in src and "PRAGMA optimize=0x10002" in src
    await init_db()
    async with db_async_engine.connect() as conn:
        n = (await conn.execute(text(
            "SELECT count(*) FROM sqlite_master WHERE name='sqlite_stat1'"))).scalar()
    assert n == 1, "init_db left no planner statistics"


def case_optimize_runs_on_its_own_loop():
    import inspect
    assert "optimize" not in inspect.getsource(server._audit_retention_sweep)
    assert server._DB_OPTIMIZE_INTERVAL_S == 6 * 60 * 60


_harness.run()
