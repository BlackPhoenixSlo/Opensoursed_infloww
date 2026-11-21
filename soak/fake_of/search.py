"""The right column's "Search users or posts" reads of the fake OnlyFans (ofm-not-yet ticket 84: the schedule form's
search read proofs' fake run), read only.

Mounted from app.py:

  GET /api2/v2/users   the users search (of_reads.py `search_users`: `{limit, offset, query, view: "se"}`): the world's
                       fans whose username or name holds `query` (any case), as a bare list of users in the `se` view
  GET /api2/v2/posts   the posts search (`search_posts`: `{limit, query, skip_users, format}`): the fake has no feed
                       posts, so `{"list": [], "hasMore": false}`; with no `query` (the own posts list, `list_posts`)
                       unmodelled, answered 404 and counted as app.py answers any unmodelled request

ASSUMPTION: matching by a plain substring of username or name stands in for OnlyFans's own search ranking (inferred,
D29: no capture of how OF matches); overturned by a capture of its answer, which then replaces this filter.
"""
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
