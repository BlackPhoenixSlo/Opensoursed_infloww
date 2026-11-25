from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import platforms
import runtime_switches
from auth import get_request_token, get_request_user
from chatters import get_request_chatter

log = logging.getLogger("of-relay.live-window")

router = APIRouter()

SWITCH = "OF_LIVE_WINDOW_ENABLED"
RATE_MAX = 6
RATE_WINDOW_S = 60.0
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_OF_DOMAIN = "onlyfans.com"

_reads: dict[str, deque[float]] = defaultdict(deque)


_require_on = runtime_switches.require_switch(SWITCH)


def is_cloudflare_cookie(name: str) -> bool:
    return name.lower().startswith(("__cf", "_cf", "cf_"))


def _of_domain(domain: str) -> bool:
    bare = (domain or "").lstrip(".").lower()
    return bare == _OF_DOMAIN or bare.endswith("." + _OF_DOMAIN)


def session_cookies(jar, *, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    out: list[dict] = []
    for c in jar:
        if not _of_domain(c.domain) or is_cloudflare_cookie(c.name):
            continue
        if c.expires is not None and c.expires <= now:
            continue
        bare = c.domain.lstrip(".")
        out.append({
            "name": c.name,
            "value": c.value or "",
            "domain": "." + bare if c.domain_specified else bare,
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": c.has_nonstandard_attr("HttpOnly"),
            "expires": c.expires,
        })
    return out


def _owner() -> tuple[str, frozenset[str]]:
    user = get_request_user()
    if user is not None:
        return f"user:{user.id}", user.account_ids
    if get_request_chatter() is not None:
        raise HTTPException(status_code=403, detail="Go live in the app is for owners only")
    raise HTTPException(status_code=401, detail="sign in required")


def _rate_ok(key: str) -> bool:
    now = time.monotonic()
    q = _reads[key]
    while q and now - q[0] >= RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_MAX:
        return False
    q.append(now)
    return True


def _client_for(account_id: str):
    import server
    return server._load_client(account_id)


@router.get("/api/of/live-window")
async def live_window_probe():
    _require_on()
    # Go live hands out the session: owner-only, chatters get 403.
    _owner()
    return JSONResponse({"enabled": True}, headers=_NO_STORE)


@router.post("/api/of/live-window/session")
async def live_window_session(request: Request):
    _require_on()
    key, allowed = _owner()
    if get_request_token() is not None:
        raise HTTPException(status_code=403, detail="Go live needs a signed-in person, not an access token")
    aid = (request.headers.get("x-account-id") or "").strip()
    if not aid.isdigit():
        raise HTTPException(status_code=400, detail="X-Account-Id required")
    if aid not in allowed:
        raise HTTPException(status_code=403, detail="not your account")
    if not _rate_ok(key):
        raise HTTPException(status_code=429, detail="too many Go live opens, wait a minute",
                            headers={"Retry-After": str(int(RATE_WINDOW_S))})
    if platforms.for_account(aid) is not platforms.ONLYFANS:
        raise HTTPException(status_code=409, detail="Go live is for OnlyFans Creators")
    try:
        client = _client_for(aid)
    except HTTPException as e:
        if e.status_code == 503 and isinstance(e.detail, dict) and e.detail.get("error") == "no_session":
            log.info("live_window_session account=%s principal=%s session=none", aid, key)
            return JSONResponse({"session": None}, headers=_NO_STORE)
        raise
    cookies = session_cookies(client.http.cookies.jar)
    x_bc = getattr(client, "x_bc", "") or ""
    if not x_bc or not any(c["name"] == "sess" for c in cookies):
        raise HTTPException(status_code=503, detail="this Creator has no usable OnlyFans session")
    log.info("live_window_session account=%s principal=%s cookies=%d", aid, key, len(cookies))
    return JSONResponse({"session": {"cookies": cookies, "x_bc": x_bc}}, headers=_NO_STORE)
