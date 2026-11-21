"""Streaming > Blocked users surface of the fake OnlyFans (Phase 3 ticket 73: Block a username's fake-mode proof), one
state for its read and both writes.

Mounted from app.py beside the settings surface (after automations' gate rows, so its fault knobs still apply):
  GET    /streams/users/blocked              {list, hasMore}; `limit`/`offset`/`query` honoured (service/of_reads.py
                                             `stream_blocked_users`)
  POST   /streams/users/{username}/block     no body (of_sends `block_stream_viewer`): a world fan by its username, or
                                             by OF's default handle `u<id>`; an unknown name 404s
  DELETE /streams/users/{id}/block           removes the row (of_sends `unblock_stream_viewer`)

The shapes are the capture record's (.scratch/ofm-not-yet/captures/settings--streaming-block-username.json): the read
`{list: user[], hasMore}`, each write `{success: true}`. The list starts empty; every write is logged and applied before
the response, so the next read reflects it. Rows are world fans (synthetic, soak/world.py), never a real one.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_STATE = "_soak_stream_blocked"


def blocked(fake) -> list[dict[str, Any]]:
    return fake.__dict__.setdefault(_STATE, [])


def _fan(fake, name: str):
    """The world fan `name` names: its username, or OF's default `u<id>` handle."""
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
