from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from soak.fake_of import links, render

_STATE = "_soak_trials"
TRIALS: list[dict[str, Any]] = [
    {"id": 6202, "trialLinkName": "Mid trial", "subscribeDays": 7, "subscribeCounts": 10, "claimCounts": 4,
     "clicksCounts": 30, "createdAt": "2026-03-01T00:00:00+00:00", "expiredAt": None, "isFinished": False},
    {"id": 6203, "trialLinkName": "Zeta trial", "subscribeDays": 30, "subscribeCounts": 5, "claimCounts": 1,
     "clicksCounts": 2, "createdAt": "2026-01-01T00:00:00+00:00", "expiredAt": None, "isFinished": False},
    {"id": 6201, "trialLinkName": "Alpha trial", "subscribeDays": 1, "subscribeCounts": 20, "claimCounts": 9,
     "clicksCounts": 11, "createdAt": "2026-02-01T00:00:00+00:00", "expiredAt": None, "isFinished": False},
]
TRIAL_KEYS = {"create_date": "createdAt", "expire_date": "expiredAt", "subscribe_counts": "subscribeCounts",
              "subscribe_days": "subscribeDays", "claims_count": "claimCounts", "clicks_count": "clicksCounts"}


def trials(fake) -> list[dict[str, Any]]:
    st = fake.__dict__.get(_STATE)
    if st is None:
        rows = [*render.fixture("settings-trials.json"), *TRIALS]
        st = fake.__dict__[_STATE] = copy.deepcopy(sorted(rows, key=lambda t: t["createdAt"], reverse=True))
    return st


async def _list(fake, req: Request, ok) -> Response:
    p = req.query_params
    off, lim = int(p.get("offset") or 0), int(p.get("limit") or 3)
    rows = links.sort_rows(req, trials(fake), TRIAL_KEYS)
    page = rows[off:off + lim]
    return ok(req, {"list": page, "hasMore": off + lim < len(rows)} if "pagination" in p else page)


async def _create(fake, req: Request, ok) -> Response:
    raw = await req.body()
    body = json.loads(raw) if raw else {}
    rows = trials(fake)
    new_id = max((int(t["id"]) for t in rows), default=6200) + 1
    now = datetime.now(timezone.utc).replace(microsecond=0)
    days = int(body.get("expireDays") or 0)
    link = {"id": new_id, "trialLinkName": str(body.get("trialLinkName") or ""),
            "url": f"https://onlyfans.com/synthmodel/trial/soak{new_id}",
            "subscribeDays": int(body.get("subscribeDays") or 0), "subscribeCounts": int(body.get("subscribeCounts") or 0),
            "claimCounts": 0, "clicksCounts": 0,
            "expiredAt": (now + timedelta(days=days)).isoformat() if days else None,
            "createdAt": now.isoformat(), "isFinished": False}
    if rows and "user" in rows[0]:
        link["user"] = copy.deepcopy(rows[0]["user"])
    rows.insert(0, link)
    fake._log(req, 200, True, body)
    return JSONResponse(link)


async def _delete(fake, req: Request, ok, tid: str) -> Response:
    rows = trials(fake)
    hit = next((t for t in rows if str(t["id"]) == tid), None)
    if hit is None:
        fake._log(req, 404, True)
        return JSONResponse({"error": {"code": 0, "message": "Not found"}}, status_code=404)
    rows.remove(hit)
    fake._log(req, 200, True)
    return JSONResponse({"success": True})


ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/trials"), _list),
    ("POST", re.compile(r"/api2/v2/trials"), _create),
    ("DELETE", re.compile(r"/api2/v2/trials/(\d+)"), _delete),
]
