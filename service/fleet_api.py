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
    if _SECRET and len(_SECRET) < _MIN_SECRET:
        log.warning("fleet whois disabled: FLEET_SECRET < 32 chars")
    return len(_SECRET) >= _MIN_SECRET


def secret_ok(given: str | None) -> bool:
    return len(_SECRET) >= _MIN_SECRET and bool(given) and hmac.compare_digest(given.encode(), _SECRET.encode())


@router.get(PATH)
async def whois(
    x_fleet_secret: Annotated[str | None, Header()] = None,
    x_fleet_username: Annotated[str, Header()] = "",
) -> JSONResponse:
    """`{exists}` for an owner's or a chatter's username; 403 without the secret."""
    if not secret_ok(x_fleet_secret):
        return JSONResponse({"detail": "forbidden"}, status_code=403, headers=_NO_STORE)
    # Username rides in a header, not `?username=`: query strings reach the access log and every shard sees every sign-in attempt (a password typed into the name field would leak). Never log it or take a sign-in throttle token.
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
