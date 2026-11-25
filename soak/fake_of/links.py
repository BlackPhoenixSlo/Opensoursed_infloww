from __future__ import annotations

import copy
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CAMPAIGNS: list[dict[str, Any]] = [
    {"id": 6102, "campaignCode": 2, "campaignName": "Mid link", "countSubscribers": 3, "countTransitions": 20,
     "createdAt": "2026-03-01T00:00:00+00:00", "isDeleted": False},
    {"id": 6103, "campaignCode": 3, "campaignName": "Zeta link", "countSubscribers": 1, "countTransitions": 5,
     "createdAt": "2026-01-01T00:00:00+00:00", "isDeleted": False},
    {"id": 6101, "campaignCode": 1, "campaignName": "Alpha link", "countSubscribers": 7, "countTransitions": 9,
     "createdAt": "2026-02-01T00:00:00+00:00", "isDeleted": False},
]
PERFORMERS: list[dict[str, Any]] = [{"id": 7401, "name": "Synthetic Peer", "username": "synthpeer"}]
SHARED: list[dict[str, Any]] = [
    {"id": 7491, "campaignCode": 91, "campaignName": "Peer link", "countSubscribers": 4, "countTransitions": 12,
     "createdAt": "2026-02-15T00:00:00+00:00", "isDeleted": False,
     "user": {"id": 7402, "name": "Synthetic Owner", "username": "synthowner"}},
]
_STATE = "_soak_links"
CAMPAIGN_KEYS = {"created_date": "createdAt", "name": "campaignName", "subscribers_counts": "countSubscribers",
                 "clicks_count": "countTransitions"}



def sort_rows(req: Request, rows: list, keys: dict) -> list:
    p = req.query_params
    key, sort = keys.get(p.get("field") or ""), p.get("sort")
    if key and sort in ("asc", "desc"):
        rows = sorted(rows, key=lambda r: (r.get(key) is None, r.get(key) if r.get(key) is not None else 0),
                      reverse=sort == "desc")
    return rows


def shares(fake) -> dict[int, dict[str, Any]]:
    return fake.__dict__.setdefault(_STATE, {})


async def _campaigns(fake, req: Request, ok) -> Response:
    p = req.query_params
    rows = [{**c, "sharedWith": copy.deepcopy(shares(fake)[c["id"]])} if c["id"] in shares(fake) else c for c in CAMPAIGNS]
    rows = sort_rows(req, rows, CAMPAIGN_KEYS)
    off, lim = int(p.get("offset") or 0), int(p.get("limit") or 100)
    return ok(req, {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)})


async def _shared(fake, req: Request, ok) -> Response:
    p = req.query_params
    off, lim = int(p.get("offset") or 0), int(p.get("limit") or 10)
    rows = sort_rows(req, SHARED, CAMPAIGN_KEYS)
    return ok(req, {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)})


async def _share(fake, req: Request, ok) -> Response:
    raw = await req.body()
    body = json.loads(raw) if raw else {}
    cid, uid = body.get("campaignId"), body.get("userId")
    who = next((u for u in PERFORMERS if u["id"] == uid), None)
    if who is None or not any(c["id"] == cid for c in CAMPAIGNS):
        fake._log(req, 400, True, body)
        return JSONResponse({"error": {"code": 0, "message": "Wrong link or user"}}, status_code=400)
    if req.method == "POST":
        shares(fake)[cid] = copy.deepcopy(who)
    else:
        shares(fake).pop(cid, None)
    fake._log(req, 200, True, body)
    return JSONResponse({"success": True})


async def _performers(fake, req: Request, ok) -> Response:
    q = (req.query_params.get("query") or "").lower()
    return ok(req, [u for u in PERFORMERS if q and q in u["username"]])


ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/campaigns"), _campaigns),
    ("GET", re.compile(r"/api2/v2/campaigns/share-access"), _shared),
    ("POST", re.compile(r"/api2/v2/campaigns/share-access"), _share),
    ("DELETE", re.compile(r"/api2/v2/campaigns/share-access"), _share),
    ("GET", re.compile(r"/api2/v2/users/performers-search"), _performers),
]
