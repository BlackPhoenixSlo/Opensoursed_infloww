"""service/tracking_links_api.py — Tracking / UTM redirects and owner CRUD.

Fully internal (no OnlyFans dependency). An operator mints a named link with a
short `slug`; the PUBLIC endpoint `GET /t/{slug}` records one click and 302s to
the `target_url`. Per-link analytics = clicks over time (subscriber / revenue
attribution is unavailable: a TrackingClick has no fan-joinable identity and
the fan never lands on OnlyFans from here).

A link may ask for a "Bot check before redirect" (`bot_check`, Cloudflare
Turnstile, needs TURNSTILE_SITE_KEY + TURNSTILE_SECRET_KEY): GET /t/{slug} then
answers a blank page holding only the widget (the target is nowhere in it) and
the click counts once POST /t/{slug}/verify passes Cloudflare's siteverify.
Keys unset → the feature is off and a gated link is a plain 302 (a fan is never
stranded on a check that cannot pass).

Routes:
  Public (share-token exempt in server.py):
    GET  /t/{slug}                                record click → 302 target_url
                                                  (bot_check: Turnstile page, no click)
    POST /t/{slug}/verify {token, ref}            siteverify → record click → {url}

  Owner-gated (/admin/*):
    GET    /admin/tracking-links?account_id=      list links (+ click_count)
    POST   /admin/tracking-links                  create (auto or custom slug)
    PATCH  /admin/tracking-links/{link_id}        {bot_check}
    DELETE /admin/tracking-links/{link_id}        delete (cascades clicks)
  Click stats (summary, per-link analytics): tracking_stats.py, which also owns the
  bounded raw click reads.
"""
from __future__ import annotations

import html
import json
import logging
import re
import secrets
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

import client_addr
import tracking_stats
import click_classify
import token_bucket
import turnstile
from auth import assert_account_owned
from db.engine import get_session
from db.models import TrackingClick, TrackingLink

log = logging.getLogger("of-relay.tracking_links_api")

router = APIRouter()

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_SLUG = 48


def _slugify(text: str) -> str:
    base = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return base[:_MAX_SLUG] or "link"


# "javascript:", "data:", "mailto:" … — a scheme with no "//" after it. A host
# with a port ("ofl.ink:8080/x") is not one: digits follow its colon.
_BARE_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:(?!\d)", re.I)


def _normalize_target(url: Any) -> str | None:
    """The http(s) URL to store, or None. No scheme → https:// is prepended
    (`ofl.ink/nora` → `https://ofl.ink/nora`); any other scheme is
    refused, and so is a host with no dot. The one check: the app sends the
    target as typed and shows this route's 422."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or len(url) > 2000 or any(c.isspace() for c in url):
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif "://" not in url:
        if _BARE_SCHEME_RE.match(url):
            return None
        url = "https://" + url
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        parts.port  # noqa: B018 — raises on a malformed port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or "." not in host.strip("."):
        return None
    return url if len(url) <= 2000 else None


# ── Cloudflare Turnstile ("Bot check before redirect") ────────────────
# The keys, the siteverify client and its in-flight cap live in turnstile.py
# (the bio app gates its Reveal with the same); the names below are this
# module's own seams (tests patch _turnstile_passes here).
TURNSTILE_VERIFY_URL = turnstile.VERIFY_URL
_MAX_TOKEN = turnstile.MAX_TOKEN
_turnstile_keys = turnstile.keys
bot_check_available = turnstile.available
_verify_url = turnstile.verify_url
_turnstile_passes = turnstile.passes


# Per-client verify budget (client_addr: the trusted hop's address, an IPv6
# client by its /64): VERIFY_CAPACITY at once, refilling one per VERIFY_REFILL_S.
# Sized for many fans behind one carrier NAT address on a gated link in a click
# burst (each check plus its Retries), which must not see 429; a script posting
# garbage tokens is held to ~30 a minute per address (plus _VERIFY_MAX_INFLIGHT
# overall) and gets 429 before the link lookup and Cloudflare's siteverify. The
# plain GET is not throttled (a burst of real clicks from one NAT must all land).
VERIFY_CAPACITY = 30
VERIFY_REFILL_S = 2.0
_verify_buckets = token_bucket.Buckets(max_keys=10_000)
_clock = time.monotonic


def _verify_wait(request: Request) -> int | None:
    """Take one verify token for this client: None, or the seconds until one is
    back when its budget is spent."""
    key = token_bucket.bucket_key(client_addr.client_address(request))
    return _verify_buckets.take(key, VERIFY_CAPACITY, VERIFY_REFILL_S, _clock())


# The page a gated link answers: dark, blank, the widget alone. It must never
# hold the target URL (a bot reading the HTML would skip the check).
_GATE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>&#8203;</title>
<style nonce="{nonce}">html,body{{margin:0;height:100%;background:#0b0b0f;color:#9a9aa5;
font:14px system-ui,sans-serif}}body{{display:flex;align-items:center;justify-content:center}}
#m{{display:flex;flex-direction:column;align-items:center;gap:12px}}#r{{display:none}}
button{{background:#1d1d25;color:#e5e5ea;border:1px solid #33333d;border-radius:8px;padding:6px 14px;
cursor:pointer}}</style>
<script nonce="{nonce}">
function okTs(t){{fetch(location.pathname.replace(/[/]+$/,"")+"/verify",{{method:"POST",
headers:{{"content-type":"application/json"}},body:JSON.stringify({{token:t,ref:{ref}}})}})
.then(function(r){{return r.ok?r.json():Promise.reject(r.status)}})
.then(function(j){{location.replace(j.url)}}).catch(failTs)}}
function failTs(){{document.getElementById("r").style.display="block"}}
function retryTs(){{document.getElementById("r").style.display="none";
if(window.turnstile)turnstile.reset("#w")}}
document.addEventListener("DOMContentLoaded",function(){{
document.getElementById("rb").addEventListener("click",retryTs)}})
</script>
<script nonce="{nonce}" src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</head><body><div id="m">
<div id="w" class="cf-turnstile" data-sitekey="{site_key}" data-theme="dark" data-appearance="interaction-only"
 data-callback="okTs" data-error-callback="failTs" data-expired-callback="retryTs"></div>
<div id="r"><button id="rb" type="button">Retry</button></div>
</div></body></html>
"""


def _gate_page(site_key: str, ref: str) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    body = _GATE_PAGE.format(nonce=nonce, site_key=html.escape(site_key, quote=True), ref=json.dumps(ref))
    return HTMLResponse(body, headers={
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        "Referrer-Policy": "no-referrer",
        # Turnstile's own CSP needs: script + frame from challenges.cloudflare.com.
        "Content-Security-Policy": (
            f"default-src 'none'; script-src 'nonce-{nonce}' https://challenges.cloudflare.com; "
            f"style-src 'nonce-{nonce}'; frame-src https://challenges.cloudflare.com; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'"),
    })


def _serialize(row: TrackingLink) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "name": row.name,
        "slug": row.slug,
        "target_url": row.target_url,
        "click_count": row.click_count,
        "bot_check": bool(row.bot_check),
        "path": f"/t/{row.slug}",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── Public redirect (NO auth — a fan clicks this) ─────────────────────

async def _record_click(link_id: int, slug: str, request: Request, *, gate_ref: str | None = None,
                        verified: bool = False) -> None:
    """Best-effort click row and count in one transaction; labels may fail independently."""
    addr = None
    referer = request.headers.get("referer") or None
    try:
        addr, country = client_addr.edge(request)
        cls = click_classify.classify(request.headers.get("user-agent"), referer)
        if gate_ref is not None:
            # Forgeable by the fan; it affects only analytics labels, never access or redirect.
            cls = cls._replace(ref=gate_ref if gate_ref in click_classify.REF_FAMILIES else "")
    except Exception as e:
        log.warning("tracking click classify failed slug=%s: %r", slug, e)
        country = None
        cls = click_classify.ClickClass(None, None)
    try:
        async with get_session() as s2:
            s2.add(TrackingClick(
                tracking_link_id=link_id, clicked_at=tracking_stats.utcnow().replace(tzinfo=None),
                referer=referer, user_agent=request.headers.get("user-agent"), ip=str(addr) if request.client else None,
                country=country, in_app=cls.in_app, ref=cls.ref, verified=verified,
            ))
            await s2.execute(update(TrackingLink).where(TrackingLink.id == link_id)
                             .values(click_count=TrackingLink.click_count + 1))
    except Exception:
        log.warning("tracking click record failed slug=%s", slug, exc_info=True)


async def _lookup(slug: str) -> tuple[int, str, bool]:
    async with get_session() as s:
        row = (await s.execute(
            select(TrackingLink).where(TrackingLink.slug == slug)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "unknown link")
        return row.id, row.target_url, bool(row.bot_check)


@router.get("/t/{slug}")
async def follow_tracking_link(slug: str, request: Request):
    """Record a click and 302 to the target. An unknown slug 404s; a known slug
    ALWAYS redirects — or, with bot_check on and Turnstile keys set, answers the
    check page (no click yet; POST /t/{slug}/verify counts it).

    The click write is deliberately kept OUT of the lookup's transaction. It
    used to share it, and the try/except around it could not deliver on
    "best-effort": `s.execute(update(...))` triggers autoflush, so the INSERT is
    what raises, the swallow leaves the transaction poisoned, and the auto-commit
    in get_session.__aexit__ — which is OUTSIDE the try — then raises
    PendingRollbackError. The fan got `Internal Server Error` instead of their
    redirect, and the click wasn't recorded either. Any write failure did it:
    disk-full, corruption, a constraint, or simply another writer holding
    SQLite's write lock past busy_timeout.

    This is the one URL a real fan touches — it goes in the creator's bio — so
    resolve the target, leave the session, and only then attempt the write.
    """
    link_id, target, gated = await _lookup(slug)
    keys = _turnstile_keys()
    gate = bool(gated and keys)
    if gate:
        try:
            ref = click_classify.ref_family(request.headers.get("referer"))
        except Exception as e:
            log.warning("tracking gate referer classify failed slug=%s: %r", slug, e)
            ref = ""
        return _gate_page(keys[0], ref)
    await _record_click(link_id, slug, request)
    # 302 so the browser doesn't cache the hop (each click must re-record).
    return RedirectResponse(url=target, status_code=302)


class _VerifyBody(BaseModel):
    token: str = ""
    ref: str = ""


@router.post("/t/{slug}/verify")
async def verify_tracking_link(slug: str, request: Request, body: _VerifyBody = Body(...)):
    """The gate page's widget callback: Cloudflare's siteverify on the token, then
    the click and the target. A link that is not gated (or keys unset) passes as
    its GET would. Fail → 403 (rejected) / 503 (Cloudflare unreachable): the page
    shows Retry. A client past its verify budget gets 429 + Retry-After first."""
    wait = _verify_wait(request)
    if wait is not None:
        log.info("tracking verify throttled slug=%s retry_after=%ss", slug, wait)
        return JSONResponse({"detail": "too many checks, retry shortly"}, status_code=429,
                            headers={"Cache-Control": "no-store", "Retry-After": str(wait)})
    link_id, target, gated = await _lookup(slug)
    keys = _turnstile_keys()
    gate = bool(gated and keys)
    if gate:
        token = (body.token or "").strip()
        ok = False
        if token and len(token) <= _MAX_TOKEN:
            ip = str(client_addr.client_address(request)) if request.client else None
            ok = await _turnstile_passes(keys[1], token, ip)
        if not ok:
            log.info("tracking bot check failed slug=%s verdict=%s", slug, ok)
            return JSONResponse({"detail": "bot check failed"}, status_code=503 if ok is None else 403,
                                headers={"Cache-Control": "no-store"})
    await _record_click(link_id, slug, request, gate_ref=body.ref if gate else None, verified=gate)
    return JSONResponse({"url": target}, headers={"Cache-Control": "no-store"})


# ── Owner-gated CRUD ──────────────────────────────────────────────────

@router.get("/admin/tracking-links")
async def list_tracking_links(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        rows = (await s.execute(
            select(TrackingLink).where(TrackingLink.account_id == account_id)
            .order_by(TrackingLink.created_at.desc())
        )).scalars().all()
    return {"links": [_serialize(r) for r in rows], "bot_check_available": bot_check_available()}


class _CreateBody(BaseModel):
    account_id: str
    name: str
    target_url: str
    slug: str | None = None
    bot_check: bool = False


@router.post("/admin/tracking-links")
async def create_tracking_link(body: _CreateBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    target = _normalize_target(body.target_url)
    if target is None:
        # Shown as is under the Create form (RedirectLinksPanel): the only check of the target.
        raise HTTPException(422, "Target must be a web address, e.g. ofl.ink/name.")
    base = _slugify(body.slug) if body.slug else _slugify(name)
    now = datetime.utcnow()

    # slug is globally unique → retry a few times with a random suffix on clash.
    # The try/except MUST sit OUTSIDE the `async with`: on a UNIQUE collision the
    # flush raises IntegrityError, get_session.__aexit__ rolls back + re-raises,
    # and we catch it here. Catching it INSIDE the block instead would let the
    # context manager's success-path auto-commit run on a dead transaction →
    # PendingRollbackError → 500 (and the retry would never fire).
    last_err: Exception | None = None
    for attempt in range(6):
        slug = base if (attempt == 0 and body.slug) else f"{base}-{secrets.token_hex(3)}"
        try:
            async with get_session() as s:
                row = TrackingLink(account_id=body.account_id, name=name, slug=slug,
                                   target_url=target, click_count=0, bot_check=body.bot_check,
                                   created_at=now)
                s.add(row)
                await s.flush()
                out = _serialize(row)
            log.info("tracking_link_created id=%s account=%s slug=%s",
                     out["id"], body.account_id, slug)
            return out
        except IntegrityError as e:  # UNIQUE(slug) collision → retry with a new suffix
            last_err = e
            continue
    raise HTTPException(409, f"could not allocate a unique slug: {repr(last_err)[:120]}")


class _PatchBody(BaseModel):
    bot_check: bool


@router.patch("/admin/tracking-links/{link_id}")
async def patch_tracking_link(link_id: int, body: _PatchBody = Body(...)) -> dict[str, Any]:
    async with get_session() as s:
        row = await s.get(TrackingLink, link_id)
        if row is None:
            raise HTTPException(404, "tracking link not found")
        assert_account_owned(row.account_id)
        row.bot_check = body.bot_check
        await s.flush()
        out = _serialize(row)
    log.info("tracking_link_patched id=%s bot_check=%s", link_id, body.bot_check)
    return out


@router.delete("/admin/tracking-links/{link_id}")
async def delete_tracking_link(link_id: int) -> dict[str, Any]:
    async with get_session() as s:
        row = await s.get(TrackingLink, link_id)
        if row is None:
            raise HTTPException(404, "tracking link not found")
        assert_account_owned(row.account_id)
        await s.delete(row)  # clicks cascade (FK ondelete=CASCADE)
    log.info("tracking_link_deleted id=%s", link_id)
    return {"deleted": link_id}
