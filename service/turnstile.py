from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

import of_origin

log = logging.getLogger("of-relay.turnstile")

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_S = 5.0
MAX_TOKEN = 2048


def keys() -> tuple[str, str] | None:
    site = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    return (site, secret) if site and secret else None


def available() -> bool:
    return keys() is not None


_verify_http: tuple[Any, httpx.AsyncClient] | None = None


def _client() -> httpx.AsyncClient:
    global _verify_http
    loop = asyncio.get_running_loop()
    if _verify_http is None or _verify_http[0] is not loop or _verify_http[1].is_closed:
        _verify_http = (loop, httpx.AsyncClient(timeout=TIMEOUT_S, limits=httpx.Limits(max_connections=32)))
    return _verify_http[1]


def verify_url() -> str:
    raw = os.environ.get("TURNSTILE_VERIFY_URL", "").strip()
    if not raw:
        return VERIFY_URL
    if of_origin.loopback_url(raw) is None:
        log.warning("TURNSTILE_VERIFY_URL ignored: not a loopback http(s) URL")
        return VERIFY_URL
    return raw


# Past this a verify answers None (caller 503, page shows Retry) instead of queueing behind the client's connections.
MAX_INFLIGHT = 32
_inflight = 0


async def passes(secret: str, token: str, remoteip: str | None) -> bool | None:
    global _inflight
    if _inflight >= MAX_INFLIGHT:
        log.warning("turnstile siteverify: %d calls out, refusing", _inflight)
        return None
    data = {"secret": secret, "response": token}
    if remoteip:
        data["remoteip"] = remoteip
    _inflight += 1
    try:
        r = await _client().post(verify_url(), data=data)
        if r.status_code != 200:
            log.warning("turnstile siteverify answered %s", r.status_code)
            return None
        answer = r.json()
        if answer.get("success"):
            return True
        if "internal-error" in (answer.get("error-codes") or []):
            log.warning("turnstile siteverify internal-error")
            return None
        return False
    except (httpx.HTTPError, ValueError, AttributeError):
        log.warning("turnstile siteverify unreachable", exc_info=True)
        return None
    finally:
        _inflight -= 1


async def check(token: str | None, remoteip: str | None) -> bool | None:
    k = keys()
    token = (token or "").strip()
    if k is None or not token or len(token) > MAX_TOKEN:
        return False
    return await passes(k[1], token, remoteip)
