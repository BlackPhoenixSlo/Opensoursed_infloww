"""service/of_live_window.py: the Creator's OnlyFans session for the desktop
Go live window (ticket 127, D28).

Go live is OnlyFans's own /my/streaming page in a desktop window. The desktop's
main process seeds that window's in-memory partition from here: the auth cookies
(never Cloudflare's own) and x_bc, which OF's page keeps as localStorage
bcTokenSha (a cookie copy without it killed the session in the D26 spike).

- `GET  /api/of/live-window`: the switch probe the app reads (404 when off).
- `POST /api/of/live-window/session`: the session for the Creator in
  X-Account-Id, only for a signed-in owner (or the Master) of that Creator;
  every chatter is refused (403), whatever their role grants, as for the
  owner-only consent PUT (of_consent_api). Answers `{"session": {cookies,
  x_bc}}`, or `{"session": null}` only when the Creator has no captured session
  file (`no_session`), the one case the desktop opens OF's login page for; a
  broken session stays a 503 the desktop refuses.
  POST + `Cache-Control: no-store` so no cache or proxy keeps it; rate limited
  per owner; the log line and the audit row (audit_log, an empty body) name
  the Creator and the owner, never a value. The desktop never writes back.

Both answer 404 while the `OF_LIVE_WINDOW_ENABLED` switch (runtime_switches,
default off) is off, so the web and desktop Go live stay Not available.

ASSUMPTION: the cookies come from the pooled client's jar (the one the relay
sends with, so the freshest copy), not the session file. Overturned by: the jar
holding cookies the file does not, in a way OF rejects from a second client.
ASSUMPTION: an owner access token (`Bearer ifw_…`, scripts and MCP) is refused:
the session is for a person at a desktop, who signs in with a cookie.
Overturned by: an owner asking for Go live from a token client.
ASSUMPTION: chatters are refused outright (rung 4: a Creator's session is a
full account takeover; the Go live page also gates the harmless schedule form,
and with role enforcement off every chatter holds every page). Overturned by:
the owner wanting chatters to go live, via an OPT_IN_PAGES opt-in.
ASSUMPTION: a loaded client whose jar lacks `sess` or x_bc is a broken session
(503, refused), not "no session" (login page). Overturned by: the owner wanting
the login page for a logged-out session too.
ASSUMPTION: 6 reads per operator per minute (one open is one read). Overturned
by: an operator opening more Creators than that in a minute.
ASSUMPTION (ticket 127, guess): two IPs on one OF session at once (the relay's
proxy and the operator's desktop) are not flagged by OF; ADR-0030 unobserved.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import accounts as account_registry
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

# principal key -> monotonic times of its recent reads. One relay process per DB.
_reads: dict[str, deque[float]] = defaultdict(deque)


_require_on = runtime_switches.require_switch(SWITCH)


def is_cloudflare_cookie(name: str) -> bool:
    return name.lower().startswith(("__cf", "_cf", "cf_"))


def _of_domain(domain: str) -> bool:
    bare = (domain or "").lstrip(".").lower()
    return bare == _OF_DOMAIN or bare.endswith("." + _OF_DOMAIN)


def session_cookies(jar, *, now: float | None = None) -> list[dict]:
    """The jar's OnlyFans cookies a browser may carry: OF domain only, unexpired,
    Cloudflare's dropped. Domain cookies keep a leading dot; host-only ones none."""
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
    """The signed-in owner's (or the Master's) rate key and Creators: 401 when
    nobody is signed in, 403 for every chatter."""
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
    # Lazy: server imports this module at boot.
    import server
    return server._load_client(account_id)


@router.get("/api/of/live-window")
async def live_window_probe():
    _require_on()
    # Unlike /api/of/ofm-writes (any signed-in role; its writes are role-checked per route), this probe is owner-only:
    # Go live hands out the session, so chatters get 403 and their web Start stays today's disabled control.
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
    if account_registry.get_platform(aid) == "fansly":
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
