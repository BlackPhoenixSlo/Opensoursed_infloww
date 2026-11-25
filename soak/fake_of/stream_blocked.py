from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_STATE = "_soak_stream_blocked"


def blocked(fake) -> list[dict[str, Any]]:
    return fake.__dict__.setdefault(_STATE, [])


def _fan(fake, name: str):
    for f in fake.world.fans:
        if name == f.username or name == f"u{f.id}":
            return f
    return None


async def _list(fake, req: Request, ok) -> Response:
    p = req.query_params
    off, lim, q = int(p.get("offset") or 0), int(p.get("limit") or 10), (p.get("query") or "").lower()
    rows = [r for r in blocked(fake) if not q or q in r["username"].lower() or q in r["name"].lower()]
    return ok(req, {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)})


async def _block(fake, req: Request, ok, name: str) -> Response:
    f = _fan(fake, name)
    if f is None:
        fake._log(req, 404, True)
        return JSONResponse({"error": {"code": 0, "message": "User not found"}}, status_code=404)
    rows = blocked(fake)
    if not any(r["id"] == f.id for r in rows):
        rows.insert(0, {"id": f.id, "name": f.name, "username": f.username, "avatar": None, "isActive": True})
    fake._log(req, 200, True)
    return JSONResponse({"success": True})


async def _unblock(fake, req: Request, ok, uid: str) -> Response:
    rows = blocked(fake)
    hit = next((r for r in rows if str(r["id"]) == uid), None)
    if hit is None:
        fake._log(req, 404, True)
        return JSONResponse({"error": {"code": 0, "message": "Not found"}}, status_code=404)
    rows.remove(hit)
    fake._log(req, 200, True)
    return JSONResponse({"success": True})


ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/streams/users/blocked"), _list),
    ("DELETE", re.compile(r"/api2/v2/streams/users/(\d+)/block"), _unblock),
    ("POST", re.compile(r"/api2/v2/streams/users/([A-Za-z0-9._-]{1,24})/block"), _block),
]
