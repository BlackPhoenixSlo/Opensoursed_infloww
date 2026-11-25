from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from soak.fake_of import render


async def _users(fake, req: Request, ok) -> Response:
    p = req.query_params
    q = (p.get("query") or "").strip().lower()
    off, lim = int(p.get("offset") or 0), int(p.get("limit") or 10)
    fans = [f for f in fake.world.fans if q and (q in f.username.lower() or q in f.name.lower())]
    return ok(req, [render.user(fake.world, f.id, "se") for f in fans[off:off + lim]])


async def _posts(fake, req: Request, ok) -> Response:
    if "query" in req.query_params:
        return ok(req, {"list": [], "hasMore": False})
    fake._log(req, 404, False)
    return JSONResponse({"error": {"code": 0, "message": "Not found (soak fake: unmodelled)"}}, status_code=404)


ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/users"), _users),
    ("GET", re.compile(r"/api2/v2/posts"), _posts),
]
