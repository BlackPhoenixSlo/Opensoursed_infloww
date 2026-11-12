"""service/turnstile.py — Cloudflare Turnstile siteverify, shared by the relay's
custom redirect links (tracking_links_api) and the standalone bio app
(bio_pages.app), which imports nothing else of the relay's.

Keys: TURNSTILE_SITE_KEY + TURNSTILE_SECRET_KEY, read per call so a key set
later (or a test) takes effect without a restart. Both unset = no bot check
anywhere: a gated link behaves as an ungated one (a fan is never stranded on a
check that cannot pass).
"""
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
MAX_TOKEN = 2048  # Turnstile's documented token ceiling


def keys() -> tuple[str, str] | None:
    """(site key, secret), or None when either is unset."""
    site = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    return (site, secret) if site and secret else None


def available() -> bool:
    return keys() is not None


# One client per event loop, kept: a new AsyncClient per verify builds an SSL
# context each time, which under a click burst ate the event loop (measured in
# slop tracking-links-clicks, medium/200: /t/ p95 25 -> 276 ms).
_verify_http: tuple[Any, httpx.AsyncClient] | None = None


def _client() -> httpx.AsyncClient:
    global _verify_http
    loop = asyncio.get_running_loop()
    if _verify_http is None or _verify_http[0] is not loop or _verify_http[1].is_closed:
        _verify_http = (loop, httpx.AsyncClient(timeout=TIMEOUT_S, limits=httpx.Limits(max_connections=32)))
    return _verify_http[1]


def verify_url() -> str:
    """Cloudflare's siteverify, or TURNSTILE_VERIFY_URL (env, a test double) when
    that is an http(s) URL on loopback: the secret is posted there, so any
    other host is ignored (of_origin.loopback_url, ADR 0024's OF_API_ORIGIN rule)."""
    raw = os.environ.get("TURNSTILE_VERIFY_URL", "").strip()
    if not raw:
        return VERIFY_URL
    if of_origin.loopback_url(raw) is None:
        log.warning("TURNSTILE_VERIFY_URL ignored: not a loopback http(s) URL")
        return VERIFY_URL
    return raw


# Outstanding siteverify calls, all clients together: past this a verify answers
# None (the caller's 503, the page shows Retry) instead of queueing behind the
# client's connections.
MAX_INFLIGHT = 32
_inflight = 0


async def passes(secret: str, token: str, remoteip: str | None) -> bool | None:
    """True/False = Cloudflare's verdict; None = Cloudflare unreachable, busy on
    its side (non-200, `internal-error`), garbled, or too many calls out."""
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
    """A gate's verdict on `token` with the keys set (callers check keys() first):
    an empty or oversized token is False without a call to Cloudflare."""
    k = keys()
    token = (token or "").strip()
    if k is None or not token or len(token) > MAX_TOKEN:
        return False
    return await passes(k[1], token, remoteip)
