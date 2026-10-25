"""GET /auth/fleet/whois: does this shard hold a login with this username?

A fleet runs one Relay per shard (one Agency each). The front shard's
/site-auth (app/app/site-auth/route.ts) asks every shard this before it
signs anyone in, so the password goes only to the shard that holds the login
(.scratch/fleet-sharding/DESIGN.md §3, §10.1). The answer is one bool for a
username; no password, no ids.

Mounted only when FLEET_SECRET is at least 32 characters (server.py), so a
single-box install answers 404 as before. Every call must carry the secret in
`X-Fleet-Secret`. It sits under /auth/, so the share gate and the app's and
Caddy's /auth/* routes already let it through. It never takes a sign-in
throttle token and never logs the username.

The username rides in the `X-Fleet-Username` header (percent-encoded), not in
`?username=`: every request URL, query included, goes to uvicorn's access log
and /tmp/of-api.log (server.py `_api_access_log`), and the front asks every
shard about every sign-in, so a query would put each typed name (or a password
typed into the name field) in every shard's logs.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select

import auth
from db.engine import get_session
from db.models import Chatter, User

PATH = "/auth/fleet/whois"
_MIN_SECRET = 32
_NO_STORE = {"Cache-Control": "no-store"}
_SECRET = os.environ.get("FLEET_SECRET", "")

log = logging.getLogger(__name__)
router = APIRouter()


def enabled() -> bool:
    """True when FLEET_SECRET is long enough to mount the route."""
    if _SECRET and len(_SECRET) < _MIN_SECRET:
        log.warning("fleet whois disabled: FLEET_SECRET < 32 chars")
    return len(_SECRET) >= _MIN_SECRET


@router.get(PATH)
async def whois(
    x_fleet_secret: Annotated[str | None, Header()] = None,
    x_fleet_username: Annotated[str, Header()] = "",
) -> JSONResponse:
    """`{exists}` for an owner's or a chatter's username; 403 without the secret."""
    given = (x_fleet_secret or "").encode("utf-8")
    if not x_fleet_secret or not hmac.compare_digest(given, _SECRET.encode("utf-8")):
        return JSONResponse({"detail": "forbidden"}, status_code=403, headers=_NO_STORE)
    username = unquote(x_fleet_username)
    if len(username) > 64:
        return JSONResponse({"detail": "username too long"}, status_code=422, headers=_NO_STORE)
    u = auth._normalize_username(username)
    found = False
    if u:
        async with get_session() as s:
            for model in (User, Chatter):
                if await s.scalar(select(model.id).where(model.username == u).limit(1)) is not None:
                    found = True
                    break
    return JSONResponse({"exists": found}, headers=_NO_STORE)
