"""Owner admin API for bio pages, mounted on the relay (never on the bio app: bio_pages/app.py does not import this).

Every handler starts with `owner_context` (no session 401, chatter 403, owner → its Agency); every query carries
`owner_user_id`, links go through their owned profile. A foreign or unknown id is 404 (employee_groups precedent);
a malformed path id is 404 before any query. Bodies: JSON objects checked by the pure `decide.check_profile` /
`decide.check_link` (422 `{"detail": {"field", "msg"}}`). Every write under `/{pid}` answers the whole page `P`
(`_page`; link create adds the new link as `link`) and bumps the profile's `updated_at`; that bump is each write
transaction's first statement, so the SQLite write lock is taken before any read (no read-then-write upgrade) and it
doubles as the ownership check.

Uploads: multipart `file`, 20 MB cap, decoded and re-encoded to WebP off the event loop (bio_pages/images.py, at most
two at a time); a new random file name per upload (the bio app serves files immutable). Files are written before the
row points at them and the old file is unlinked after commit; a crash in between leaves an orphan file, never a row
without its file. Logs: fixed `bio admin: ` lines with ids only, never a destination or geo value.

Create with a Creator: an empty display name takes the Creator's OnlyFans name, and the page starts with one
"OnlyFans" link straight to https://onlyfans.com/<username> (never through /t/: that would break /c<code> tracking).
Both read the Creator's cached `users_me` (the app's own `of-me` read fills it), so at most one OnlyFans call.
Vault avatar: `POST /{pid}/avatar/vault {media_id}` takes a photo of the page's Creator through vault_stills (disk,
mirror url, then a by-id re-sign; the account's own egress, never a client url) and encodes it like an upload;
`POST /{pid}/links/{lid}/background/vault` the same for a link's background, `/{pid}/background(/vault)` for the
page's backdrop (BACKGROUND_SIDE). Setting a Creator later (PATCH) adds the
"OnlyFans" link first when the page has no onlyfans.com link yet.
Audit: link create, the vault picks (the Toolbox write tools' routes) and the page background upload name the
page's stored Creator for the audit row (`_audit_as`), whatever X-Account-Id / ?account_id= the caller sent.

Env: BIO_PUBLIC_URL (the public base, e.g. https://ofl.ink; unset → `<request origin>/p`, the origin read from
X-Forwarded-Host/Proto when a proxy set them), BIO_SHORT_URL (optional short base whose `/<username>` redirects to
the page, e.g. https://ofl.ink/s; the editor's `short_url`, unset → null), BIO_HEALTH_URL (the bio service's /internal/healthz, probed for
`serving`; unset → false), BIO_SERVER_IP (the box's public IPv4 a custom domain's A record must name; unset → custom
domains can't be set or checked, only removed) and BIO_SERVER_IPV6 (optional: the one AAAA a custom domain may have).

Custom domain (`PUT /{pid}/domain {domain}`, `DELETE /{pid}/domain`, `POST /{pid}/domain/check`): one per page (a
new one replaces it, the same one keeps its row and token), at most domains.MAX_PER_OWNER per account, never this
service's own hosts. Several pages may hold the same `pending` domain (nobody can squat one); only one row per domain
may be `pending_cert` / `live` (checked under the write lock, and the live index). The check reads DNS and probes
HTTPS outside any transaction (bio_pages/domains.py), at most once per page every CHECK_GAP_S. Sentences, records and the
check's `{status, problems}` are ofl.ink v2's (~/oflinkv2/app/server.js, the domain-check route), plus `pending_cert`.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import time
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.datastructures import UploadFile

from audit_log import AUDIT_ACCOUNT
from bio_pages import decide, domains, files, images
from bio_pages.assets import PUBLIC
from db.engine import get_session
from db.models import BioCustomDomain, BioDaily, BioLink, BioProfile, BioSpareDomain, VaultItem
from employees import json_object, owner_context

log = logging.getLogger("of-relay.bio-admin")
_REQUEST_BASE: contextvars.ContextVar[str | None] = contextvars.ContextVar("bio_request_base", default=None)
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::\d{1,5})?")
OF_IDENTITY_TIMEOUT_S = 8.0


def request_base(request: Request) -> str | None:
    """`<origin>/p` of this request: X-Forwarded-Host/Proto (first hop) when a proxy set them, else the Host."""
    h = request.headers
    host = ((h.get("x-forwarded-host") or "").split(",")[0].strip() or h.get("host") or "").lower()
    proto = ((h.get("x-forwarded-proto") or "").split(",")[0].strip() or request.url.scheme).lower()
    if proto not in ("http", "https") or not _HOST.fullmatch(host):
        return None
    return f"{proto}://{host}/p"


async def _capture_base(request: Request) -> None:
    _REQUEST_BASE.set(request_base(request))


router = APIRouter(prefix="/admin/bio-pages", tags=["bio-pages"], dependencies=[Depends(_capture_base)])

_OWNER_ONLY = "bio pages are owner-only"
MAX_UPLOAD = 20 * 1024 * 1024
FORM_OVERHEAD = 64 * 1024
FILE_PREFIX = "/admin/bio-pages/files"
_ENCODE = asyncio.Semaphore(2)
_PRIVATE_IMM = "private, max-age=31536000, immutable"
_serving_cache: tuple[float, bool] = (0.0, False)
_serving_lock = asyncio.Lock()


# ── helpers ──────────────────────────────────────────────────────────

async def _owner() -> str:
    return (await owner_context(None, _OWNER_ONLY)).agency_user_id


def _id_or_404(value: str, rx=decide.RECORD_ID) -> str:
    if not rx.fullmatch(value):
        raise HTTPException(404, "no such bio page")
    return value


def _check(result):
    if isinstance(result, decide.Invalid):
        raise HTTPException(422, {"field": result.field, "msg": result.msg})
    return result


async def _check_account(body: dict) -> None:
    if body.get("account_id") is not None:
        await owner_context(body["account_id"], _OWNER_ONLY)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def public_base() -> str | None:
    """BIO_PUBLIC_URL, else this request's `<origin>/p` (the app host serves bio pages under /p)."""
    return (os.environ.get("BIO_PUBLIC_URL") or "").rstrip("/") or _REQUEST_BASE.get()


def _public_url(username: str, domain: dict | None) -> str | None:
    if domain and domain["status"] == "live":
        return f"https://{domain['domain']}/"
    base = public_base()
    return f"{base}/{username}" if base else None


def _short_url(username: str) -> str | None:
    base = (os.environ.get("BIO_SHORT_URL") or "").rstrip("/")
    return f"{base}/{username}" if base else None


def _file_url(collection: str, rid: str, name: str) -> str:
    return f"{FILE_PREFIX}/{collection}/{rid}/{name}" if name else ""


async def serving() -> bool:
    """Whether the bio service answers its health check (BIO_HEALTH_URL), cached 30 s."""
    global _serving_cache
    url = os.environ.get("BIO_HEALTH_URL")
    if not url:
        return False
    at, ok = _serving_cache
    if time.monotonic() - at < 30:
        return ok
    async with _serving_lock:
        at, ok = _serving_cache
        if time.monotonic() - at < 30:
            return ok
        try:
            async with httpx.AsyncClient(timeout=1.0, trust_env=False) as cl:
                ok = (await cl.get(url)).status_code == 200
        except Exception:  # noqa: BLE001 — malformed health URL also means not serving
            ok = False
        _serving_cache = (time.monotonic(), ok)
        return ok


def _own_profile(owner: str, pid: str):
    return (BioProfile.id == pid, BioProfile.owner_user_id == owner)


def _own_link(owner: str, lid: str, pid: str | None = None):
    predicates = (BioLink.id == lid, BioLink.profile_id.in_(select(BioProfile.id).where(
        BioProfile.owner_user_id == owner)))
    return predicates + ((BioLink.profile_id == pid,) if pid is not None else ())


def _db_unavailable(exc: DBAPIError) -> HTTPException:
    log.error("bio admin: database write failed: error=%s", type(exc).__name__)
    return HTTPException(503, "try again")


def _safe_write(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except DBAPIError as exc:
            raise _db_unavailable(exc) from None
        except files.WriteFailed:
            log.error("bio admin: file write failed")
            raise HTTPException(503, "try again") from None
    return wrapped


async def _lock_own(s, owner: str, pid: str) -> None:
    """Bump the profile's updated_at as the write's first statement (takes the write lock); 404 unless owned."""
    r = await s.execute(update(BioProfile).where(*_own_profile(owner, pid))
                        .values(updated_at=_now()))
    if r.rowcount == 0:
        raise HTTPException(404, "no such bio page")


def _link_out(lk: BioLink) -> dict[str, Any]:
    try:
        geo = json.loads(lk.geo) if lk.geo is not None else None
    except ValueError:
        geo = None
    return {"id": lk.id, "link_id": lk.link_id, "title": lk.title, "destination": lk.destination,
            "icon": lk.icon, "icon_stock": decide.icon_stock(lk.icon), "icon_url": _file_url("links", lk.id, lk.icon),
            "background_image": lk.background_image,
            "background_url": _file_url("links", lk.id, lk.background_image),
            "is_adult": bool(lk.is_adult), "mode": lk.mode, "tracking": bool(lk.tracking),
            "default_tracking_code": lk.default_tracking_code, "geo": geo, "sort_order": lk.sort_order,
            "updated_at": _iso(lk.updated_at)}


async def _page(s, owner: str, pid: str) -> dict[str, Any]:
    """`P`: the profile and its links in the public order `(sort_order, id)`; 404 unless owned."""
    p = (await s.execute(select(BioProfile).where(*_own_profile(owner, pid)))
         ).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "no such bio page")
    dom = (await s.execute(select(BioCustomDomain.domain, BioCustomDomain.status, BioCustomDomain.token,
                                  BioCustomDomain.checked)
                           .where(BioCustomDomain.profile_id == pid))).first()
    domain = {"domain": dom.domain, "status": dom.status, "checked": _iso(dom.checked),
              "records": domains.records_for(dom.domain, dom.token, domains.server_ip(), domains.server_ipv6())
              } if dom else None
    links = (await s.execute(select(BioLink).where(BioLink.profile_id == pid)
                             .order_by(BioLink.sort_order, BioLink.id))).scalars().all()
    return {"profile": {"id": p.id, "username": p.username, "display_name": p.display_name, "bio": p.bio,
                        "avatar": p.avatar, "avatar_url": _file_url("profiles", p.id, p.avatar),
                        "background_url": _file_url("profiles", p.id, p.background_image),
                        "account_id": p.account_id, "mode": p.mode, "verified": bool(p.verified),
                        "custom_domain": domain, "public_url": _public_url(p.username, domain),
                        "short_url": _short_url(p.username), "home_url": _public_url(p.username, None),
                        "domain_server_ip": domains.server_ip(),
                        "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at)},
            "links": [_link_out(lk) for lk in links]}


async def _answer(owner: str, pid: str) -> dict[str, Any]:
    async with get_session() as s:
        return await _page(s, owner, pid)


def _audit_as(request: Request, page: dict[str, Any]) -> dict[str, Any]:
    """The audit row names the page's stored Creator, never the caller's X-Account-Id (audit_log.AUDIT_ACCOUNT)."""
    setattr(request.state, AUDIT_ACCOUNT, page["profile"]["account_id"])
    return page


def _stock_data(stem: str) -> bytes:
    try:
        return (PUBLIC / "images" / f"{stem}.webp").read_bytes()
    except OSError:
        log.error("bio admin: file read failed")
        raise HTTPException(503, "try again") from None


# ── list / create / static ───────────────────────────────────────────

@router.get("")
async def list_pages() -> dict[str, Any]:
    owner = await _owner()
    since = (datetime.now(timezone.utc).date() - timedelta(days=29)).isoformat()
    async with get_session() as s:
        rows = (await s.execute(
            select(BioProfile, func.count(BioLink.id))
            .outerjoin(BioLink, BioLink.profile_id == BioProfile.id)
            .where(BioProfile.owner_user_id == owner)
            .group_by(BioProfile.id).order_by(BioProfile.updated_at.desc(), BioProfile.id))).all()
        ids = [p.id for p, _ in rows]
        stats = {pid: (v, c) for pid, v, c in (await s.execute(
            select(BioDaily.profile_id, func.sum(BioDaily.views), func.sum(BioDaily.clicks))
            .where(BioDaily.profile_id.in_(ids), BioDaily.day >= since)
            .group_by(BioDaily.profile_id))).all()} if ids else {}
        doms = {pid: {"domain": d, "status": st} for pid, d, st in (await s.execute(
            select(BioCustomDomain.profile_id, BioCustomDomain.domain, BioCustomDomain.status)
            .where(BioCustomDomain.profile_id.in_(ids)))).all()} if ids else {}
    out = []
    for p, n in rows:
        dom = doms.get(p.id)
        v, c = stats.get(p.id, (0, 0))
        out.append({"id": p.id, "username": p.username, "display_name": p.display_name,
                    "avatar_url": _file_url("profiles", p.id, p.avatar),
                    "background_url": _file_url("profiles", p.id, p.background_image), "account_id": p.account_id,
                    "mode": p.mode, "verified": bool(p.verified), "link_count": n, "custom_domain": dom,
                    "public_url": _public_url(p.username, dom), "views_30d": int(v or 0), "clicks_30d": int(c or 0),
                    "updated_at": _iso(p.updated_at)})
    return {"serving": await serving(), "public_base": public_base(), "profiles": out}


async def _of_me(account_id: str) -> dict[str, Any] | None:
    """The Creator's OnlyFans `/users/me` through the `GET /api/of/v2/users/me` route's own cache entry (namespace,
    key and TTL as server.py's `users_me`, s4s_api's precedent); None when it cannot be read."""
    import automation_executor as ax
    import relay_cache
    try:
        me = await asyncio.wait_for(relay_cache.get_or_fetch(
            "users_me", account_id, ("users_me",), 60, lambda: ax._make_client(account_id).me(),
        ), OF_IDENTITY_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — no session, proxy refusal, timeout: create goes on without it
        log.info("bio admin: OnlyFans profile unreadable: account=%s", account_id)
        return None
    return me if isinstance(me, dict) else None


def _of_username(me: dict | None) -> str:
    u = str((me or {}).get("username") or "").strip()
    return u if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", u) else ""


def _of_link(lid: str, pid: str, of_user: str, icon: str, sort_order: int, now: datetime) -> BioLink:
    """The Creator's "OnlyFans" link; tracking on: Reveal appends the visitor's /c<code>."""
    return BioLink(id=lid, profile_id=pid, link_id=files.new_id(12), title="OnlyFans",
                   destination=f"https://onlyfans.com/{of_user}", icon=icon, tracking=True,
                   sort_order=sort_order, created_at=now, updated_at=now)


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


@router.post("", status_code=201)
@_safe_write
async def create_page(request: Request) -> dict[str, Any]:
    owner = await _owner()
    raw = await json_object(request, 422)
    fill = _blank(raw.get("display_name"))
    # every other field is refused before the Creator's profile is read
    body = _check(decide.check_profile({**raw, "display_name": "-"} if fill else raw, create=True))
    await _check_account(body)
    me = await _of_me(body["account_id"]) if body.get("account_id") else None
    of_user = _of_username(me)
    if fill:
        name = str((me or {}).get("name") or "").strip() or of_user
        body = _check(decide.check_profile({**raw, "display_name": name[:decide.MAX_DISPLAY_NAME]}, create=True))
    pid, lid = files.new_id(15), files.new_id(15)
    icon = _file_name("onlyicon") if of_user else ""
    data = await asyncio.to_thread(_stock_data, "onlyicon") if of_user else None
    try:
        async with files.staged("links", lid, icon, data):
            async with get_session() as s:
                now = _now()
                s.add(BioProfile(id=pid, owner_user_id=owner, created_at=now, updated_at=now, **body))
                if of_user:  # flushed after the profile (its FK)
                    await s.flush()
                    s.add(_of_link(lid, pid, of_user, icon, 0, now))
                await s.flush()
                return await _page(s, owner, pid)
    except IntegrityError:
        async with get_session() as s:
            taken = (await s.execute(select(BioProfile.id).where(BioProfile.username == body["username"]))).first()
        if taken:
            raise HTTPException(409, {"field": "username", "msg": "That username is taken."}) from None
        raise HTTPException(409, "Creator or page id is no longer available.") from None


@router.get("/stock/{name}")
async def stock_icon(name: str) -> Response:
    await _owner()
    stem = name.removesuffix(".webp")
    if name != f"{stem}.webp" or stem not in decide.STOCK_ICONS:
        raise HTTPException(404, "no such icon")
    return FileResponse(PUBLIC / "images" / name, media_type="image/webp", headers={"cache-control": _PRIVATE_IMM})


@router.get("/files/{collection}/{rid}/{filename}")
async def owner_file(collection: str, rid: str, filename: str) -> Response:
    owner = await _owner()
    _id_or_404(rid)
    builders = {"profiles": lambda: select(BioProfile.id).where(*_own_profile(owner, rid)),
                "links": lambda: select(BioLink.id)
                .where(*_own_link(owner, rid))}
    if collection not in builders:
        raise HTTPException(404, "no such file")
    q = builders[collection]()
    async with get_session() as s:
        if (await s.execute(q)).first() is None:
            raise HTTPException(404, "no such file")
    path = files.safe_path(files.files_dir(), collection, rid, filename)
    if path is None:
        raise HTTPException(404, "no such file")
    return FileResponse(path, media_type="image/webp", headers={"cache-control": _PRIVATE_IMM})


# ── one page ─────────────────────────────────────────────────────────

@router.get("/{pid}")
async def get_page(pid: str) -> dict[str, Any]:
    owner = await _owner()
    return await _answer(owner, _id_or_404(pid))


@router.patch("/{pid}")
@_safe_write
async def patch_page(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    body = _check(decide.check_profile(await json_object(request, 422), create=False))
    await _check_account(body)
    # A Creator set after create gets the same first "OnlyFans" link, unless the page already links to OnlyFans.
    of_user = _of_username(await _of_me(body["account_id"])) if body.get("account_id") else ""
    lid = files.new_id(15)
    icon = _file_name("onlyicon") if of_user else ""
    data = await asyncio.to_thread(_stock_data, "onlyicon") if of_user else None
    added = False
    async with files.staged("links", lid, icon, data):
        async with get_session() as s:
            await _lock_own(s, owner, pid)
            if body:
                await s.execute(update(BioProfile).where(BioProfile.id == pid).values(**body))
            if of_user:
                n, low, has_of = (await s.execute(select(
                    func.count(), func.min(BioLink.sort_order),
                    func.sum(case((or_(*(BioLink.destination.ilike(f"{sch}{h}onlyfans.com%")
                                          for sch in ("https://", "http://") for h in ("", "www."))), 1), else_=0)),
                ).where(BioLink.profile_id == pid))).one()
                if not has_of and n < decide.MAX_LINKS:
                    s.add(_of_link(lid, pid, of_user, icon, (low if low is not None else 1) - 1, _now()))
                    await s.flush()
                    added = True
                    log.info("bio admin: OnlyFans link added: page=%s account=%s", pid, body["account_id"])
            page = await _page(s, owner, pid)
    if data is not None and not added:  # staged for nothing: no link points at it
        await files.discard("links", lid)
    return page


@router.delete("/{pid}", status_code=204)
@_safe_write
async def delete_page(pid: str) -> Response:
    owner = await _owner()
    _id_or_404(pid)
    async with get_session() as s:
        await _lock_own(s, owner, pid)
        link_ids = (await s.execute(select(BioLink.id).where(BioLink.profile_id == pid))).scalars().all()
        await s.execute(delete(BioProfile).where(*_own_profile(owner, pid)))
    await files.discard("profiles", pid)
    for lid in link_ids:
        await files.discard("links", lid)
    return Response(status_code=204)


# ── custom domain ────────────────────────────────────────────────────

CHECK_GAP_S = 10
_VERIFIED = ("pending_cert", "live")
_DOMAINS_OFF = domains.OFF_MSG


async def _own_hosts(s) -> set[str]:
    """This box's own hosts (public/short bases, the request's host, BIO_PRIMARY_HOSTS, the spare domains): never a
    custom domain, nor anything under one."""
    hosts = {domains.host_of(os.environ.get(k)) for k in ("BIO_PUBLIC_URL", "BIO_SHORT_URL")}
    hosts.add(domains.host_of(_REQUEST_BASE.get()))
    hosts |= set(decide.parse_primary_hosts(os.environ.get("BIO_PRIMARY_HOSTS")))
    hosts |= set((await s.execute(select(BioSpareDomain.domain))).scalars())
    return {h for h in hosts if h}


def _own_msg(domain: str) -> str:
    return f"{domain} is one of ofl.ink's own addresses. Use a domain you own."


def _in_use(domain: str) -> str:
    return f"Another Profile already uses {domain}."


def _example(username: str) -> str:
    """v2's exampleOf: the username as a .com (underscores are not allowed in a hostname)."""
    return f"{username.replace('_', '') or 'yourname'}.com"


async def _taken(s, domain: str, pid: str) -> bool:
    """Another page's row holds `domain` past `pending`."""
    return (await s.execute(select(BioCustomDomain.id).where(
        BioCustomDomain.domain == domain, BioCustomDomain.profile_id != pid,
        BioCustomDomain.status.in_(_VERIFIED)))).first() is not None


@router.put("/{pid}/domain")
@_safe_write
async def set_domain(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    raw = (await json_object(request, 422)).get("domain")
    domain = domains.normalize(raw) if isinstance(raw, str) else ""
    if not domain:
        raise HTTPException(422, {"field": "domain", "msg": "Enter a domain."})
    if domains.server_ip() is None:
        raise HTTPException(409, _DOMAINS_OFF)
    async with get_session() as s:
        await _lock_own(s, owner, pid)
        if not domains.valid(domain):
            username = (await s.execute(select(BioProfile.username).where(BioProfile.id == pid))).scalar_one()
            raise HTTPException(422, {"field": "domain", "msg": f"Enter the domain alone, like {_example(username)}: "
                                                                "no https://, no slash, no spaces."})
        if domains.own_host(domain, await _own_hosts(s)):
            raise HTTPException(422, {"field": "domain", "msg": _own_msg(domain)})
        cur = (await s.execute(select(BioCustomDomain).where(BioCustomDomain.profile_id == pid))).scalar_one_or_none()
        if cur is not None and cur.domain == domain:
            return await _page(s, owner, pid)  # same domain: its row, token and status stay
        if await _taken(s, domain, pid):
            raise HTTPException(409, {"field": "domain", "msg": _in_use(domain)})
        n = (await s.execute(select(func.count()).select_from(BioCustomDomain).join(
            BioProfile, BioProfile.id == BioCustomDomain.profile_id).where(
            BioProfile.owner_user_id == owner, BioCustomDomain.profile_id != pid))).scalar_one()
        if n >= domains.MAX_PER_OWNER:
            raise HTTPException(409, f"An account holds at most {domains.MAX_PER_OWNER} custom domains.")
        if cur is not None:
            await s.execute(delete(BioCustomDomain).where(BioCustomDomain.id == cur.id))
        s.add(BioCustomDomain(id=files.new_id(15), profile_id=pid, domain=domain, status="pending",
                              token=files.new_id(32)))  # v2's token form: 32 lowercase letters or digits
        await s.flush()
        log.info("bio admin: custom domain set: page=%s", pid)
        return await _page(s, owner, pid)


@router.delete("/{pid}/domain")
@_safe_write
async def remove_domain(pid: str) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    async with get_session() as s:
        await _lock_own(s, owner, pid)
        await s.execute(delete(BioCustomDomain).where(BioCustomDomain.profile_id == pid))
        log.info("bio admin: custom domain removed: page=%s", pid)
        return await _page(s, owner, pid)


@router.post("/{pid}/domain/check")
@_safe_write
async def check_domain(pid: str) -> dict[str, Any]:
    """DNS, then the HTTPS probe; the row's next status is written only if it is still the row that was checked."""
    owner = await _owner()
    _id_or_404(pid)
    async with get_session() as s:
        cur = (await s.execute(select(BioCustomDomain.id, BioCustomDomain.domain, BioCustomDomain.token,
                                      BioCustomDomain.status, BioCustomDomain.checked)
                               .join(BioProfile, BioProfile.id == BioCustomDomain.profile_id)
                               .where(*_own_profile(owner, pid)))).first()
        if cur is None:
            if (await s.execute(select(BioProfile.id).where(*_own_profile(owner, pid)))).first() is None:
                raise HTTPException(404, "no such bio page")
            raise HTTPException(409, "This page has no custom domain.")
        own = cur.status != "live" and domains.own_host(cur.domain, await _own_hosts(s))
    ip = domains.server_ip()
    if ip is None and cur.status != "live":
        raise HTTPException(409, _DOMAINS_OFF)
    if cur.status != "live" and cur.checked and (_now() - cur.checked).total_seconds() < CHECK_GAP_S:
        raise HTTPException(429, "Too many checks. Wait a few seconds, then try again.")
    if own:  # a spare domain added since it was saved
        status, problems = "pending", [_own_msg(cur.domain)]
    else:
        status, problems = await domains.check(cur.domain, cur.token, cur.status, ip or "", domains.server_ipv6())
    async with get_session() as s:
        await _lock_own(s, owner, pid)
        if (await s.execute(select(BioCustomDomain.id).where(BioCustomDomain.id == cur.id))).first() is None:
            raise HTTPException(409, "The custom domain changed: reload.")
        if status in _VERIFIED and status != cur.status and await _taken(s, cur.domain, pid):
            status, problems = "pending", [_in_use(cur.domain)]  # v2: the live write's clash is a problem
        try:
            await s.execute(update(BioCustomDomain).where(BioCustomDomain.id == cur.id)
                            .values(status=status, checked=_now()))
            await s.flush()
        except IntegrityError:
            raise HTTPException(409, {"field": "domain", "msg": _in_use(cur.domain)}) from None
        if status != cur.status:
            log.info("bio admin: custom domain %s → %s: page=%s", cur.status, status, pid)
        return {**await _page(s, owner, pid), "check": {"status": status, "problems": problems}}


# ── uploads ──────────────────────────────────────────────────────────

async def _read_upload(request: Request) -> bytes:
    """The form's `file` part: 411 without a size, 413 past 20 MB."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared <= 0:
        raise HTTPException(411, "send the image as a form upload with a content-length")
    if declared > MAX_UPLOAD + FORM_OVERHEAD:
        raise HTTPException(413, "The image is larger than 20 MB.")
    form = await request.form(max_files=1, max_fields=2)
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(422, {"field": "file", "msg": "Pick an image."})
        data = await file.read(MAX_UPLOAD + 1)
    finally:
        await form.close()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The image is larger than 20 MB.")
    return data


async def _encode(request: Request, side: int) -> bytes:
    raw = await _read_upload(request)
    async with _ENCODE:
        try:
            return await asyncio.to_thread(images.encode, raw, side)
        except images.Refused as e:
            raise HTTPException(e.status, e.msg) from None


async def _owned_link(s, owner: str, pid: str, lid: str) -> BioLink:
    lk = (await s.execute(select(BioLink)
                          .where(*_own_link(owner, lid, pid)))
          ).scalar_one_or_none()
    if lk is None:
        raise HTTPException(404, "no such link")
    return lk


def _file_name(stem: str | None) -> str:
    return f"{stem}_{files.new_id(10)}.webp" if stem else ""


async def _set_file(owner: str, pid: str, model, col, collection: str, rid: str, stem: str,
                    data: bytes | None, values: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """Point a row at a new file, then drop the old file after commit."""
    name = _file_name(stem) if data is not None else ""
    async with files.staged(collection, rid, name, data):
        async with get_session() as s:
            await _lock_own(s, owner, pid)
            if model is BioLink:
                await _owned_link(s, owner, pid, rid)
            old = (await s.execute(select(col).where(model.id == rid))).scalar_one()
            patch = {col.key: name, **(values or {})}
            if model is BioLink:
                patch["updated_at"] = _now()
            await s.execute(update(model).where(model.id == rid).values(**patch))
            page = await _page(s, owner, pid)
    if old and old != name:
        await files.discard(collection, rid, old)
    return page


async def _require(owner: str, pid: str, lid: str | None = None) -> None:
    """Ownership before an upload body is read (the write re-checks it)."""
    async with get_session() as s:
        if lid is None:
            if (await s.execute(select(BioProfile.id).where(*_own_profile(owner, pid)))).first() is None:
                raise HTTPException(404, "no such bio page")
        else:
            await _owned_link(s, owner, pid, lid)


@router.post("/{pid}/avatar")
@_safe_write
async def upload_avatar(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    await _require(owner, pid)
    return await _set_file(owner, pid, BioProfile, BioProfile.avatar, "profiles", pid, "avatar",
                           await _encode(request, images.AVATAR_SIDE))


async def _vault_still(account_id: str, media_id: int) -> bytes:
    """A vault photo's bytes via vault_stills (disk, mirror url, by-id re-sign; the account's egress). Photos only:
    a mirror row of another kind is refused, and a re-signed media that is not a photo yields no url."""
    import vault_frames
    import vault_stills
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is not None and item.kind != "photo":
        raise HTTPException(415, "Pick a photo, not a video.")
    def pick(m: dict) -> str | None:
        return vault_frames.pick_image(m) if m.get("type", "photo") == "photo" else None
    still = await vault_stills.bytes_for(account_id, media_id, vault_stills.image_path(account_id, media_id), pick)
    if still.data is not None:
        return still.data
    if still.reason == "no_variant":
        raise HTTPException(415, "Pick a photo, not a video.")
    if still.reason == "gone":
        raise HTTPException(404, "That vault item is gone.")
    raise HTTPException(502, "Couldn't fetch that photo from OnlyFans. Try again.")


async def _vault_image(owner: str, pid: str, request: Request, side: int) -> tuple[str, int, bytes]:
    """A photo of the page's Creator's vault, encoded at `side`: (account, media id, WebP bytes)."""
    async with get_session() as s:
        aid = (await s.execute(select(BioProfile.account_id).where(*_own_profile(owner, pid)))).first()
    if aid is None:
        raise HTTPException(404, "no such bio page")
    body = await json_object(request, 422)
    mid = body.get("media_id")
    if not isinstance(mid, int) or isinstance(mid, bool) or mid <= 0:
        raise HTTPException(422, {"field": "media_id", "msg": "Pick a photo from the vault."})
    if body.get("type") not in (None, "photo"):
        raise HTTPException(415, "Pick a photo, not a video.")
    if not aid[0]:
        raise HTTPException(409, "Connect a Creator to pick from its vault.")
    await owner_context(aid[0], _OWNER_ONLY)
    raw = await _vault_still(aid[0], mid)
    async with _ENCODE:
        try:
            return aid[0], mid, await asyncio.to_thread(images.encode, raw, side)
        except images.Refused as e:
            raise HTTPException(e.status, e.msg) from None


@router.post("/{pid}/avatar/vault")
@_safe_write
async def avatar_from_vault(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    aid, mid, data = await _vault_image(owner, pid, request, images.AVATAR_SIDE)
    log.info("bio admin: avatar from vault: page=%s account=%s media=%s", pid, aid, mid)
    return _audit_as(request, await _set_file(owner, pid, BioProfile, BioProfile.avatar, "profiles", pid, "avatar",
                                              data))


@router.delete("/{pid}/avatar")
@_safe_write
async def remove_avatar(pid: str) -> dict[str, Any]:
    owner = await _owner()
    return await _set_file(owner, _id_or_404(pid), BioProfile, BioProfile.avatar, "profiles", pid, "avatar", None)


@router.post("/{pid}/background")
@_safe_write
async def upload_page_background(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    await _require(owner, pid)
    return _audit_as(request, await _set_file(owner, pid, BioProfile, BioProfile.background_image, "profiles", pid,
                                              "background", await _encode(request, images.BACKGROUND_SIDE)))


@router.post("/{pid}/background/vault")
@_safe_write
async def page_background_from_vault(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    aid, mid, data = await _vault_image(owner, pid, request, images.BACKGROUND_SIDE)
    log.info("bio admin: background from vault: page=%s account=%s media=%s", pid, aid, mid)
    return _audit_as(request, await _set_file(owner, pid, BioProfile, BioProfile.background_image, "profiles", pid,
                                              "background", data))


@router.delete("/{pid}/background")
@_safe_write
async def remove_page_background(pid: str) -> dict[str, Any]:
    owner = await _owner()
    return await _set_file(owner, _id_or_404(pid), BioProfile, BioProfile.background_image, "profiles", pid,
                           "background", None)


# ── links ────────────────────────────────────────────────────────────

@router.post("/{pid}/links", status_code=201)
@_safe_write
async def create_link(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    body = _check(decide.check_link(await json_object(request, 422), create=True))
    stem = body.pop("icon", None)
    lid, link_id = files.new_id(15), files.new_id(12)
    icon = _file_name(stem)
    data = await asyncio.to_thread(_stock_data, stem) if stem else None
    async with files.staged("links", lid, icon, data):
        try:
            async with get_session() as s:
                await _lock_own(s, owner, pid)
                n, top = (await s.execute(select(func.count(), func.max(BioLink.sort_order))
                                          .where(BioLink.profile_id == pid))).one()
                if n >= decide.MAX_LINKS:
                    raise HTTPException(409, f"A bio page holds at most {decide.MAX_LINKS} links.")
                now = _now()
                s.add(BioLink(id=lid, profile_id=pid, link_id=link_id, icon=icon,
                              sort_order=(top if top is not None else -1) + 1, created_at=now, updated_at=now,
                              **body))
                await s.flush()
                page = await _page(s, owner, pid)
                return _audit_as(request, {**page, "link": next(lk for lk in page["links"] if lk["id"] == lid)})
        except IntegrityError:
            raise HTTPException(409, "Creator or link id is no longer available.") from None


@router.put("/{pid}/links/order")
@_safe_write
async def reorder_links(pid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    ids = (await json_object(request, 422)).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise HTTPException(422, {"field": "ids", "msg": "ids must be a list of link ids"})
    async with get_session() as s:
        await _lock_own(s, owner, pid)
        have = set((await s.execute(select(BioLink.id).where(BioLink.profile_id == pid))).scalars())
        if len(ids) != len(have) or set(ids) != have:
            raise HTTPException(409, "the links changed: reload")
        await _write_order(s, pid, ids)
        return await _page(s, owner, pid)


async def _write_order(s, pid: str, ids: list[str]) -> None:
    now = _now()
    for i, lid in enumerate(ids):
        await s.execute(update(BioLink).where(BioLink.id == lid, BioLink.profile_id == pid)
                        .values(sort_order=i, updated_at=now))


@router.patch("/{pid}/links/{lid}")
@_safe_write
async def patch_link(pid: str, lid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    _id_or_404(lid)
    body = _check(decide.check_link(await json_object(request, 422), create=False))
    if "icon" in body:
        await _require(owner, pid, lid)  # before a file lands in the link's dir
        stem = body.pop("icon")
        data = await asyncio.to_thread(_stock_data, stem) if stem else None
        return await _set_file(owner, pid, BioLink, BioLink.icon, "links", lid, stem, data, body)
    async with get_session() as s:
        await _lock_own(s, owner, pid)
        await _owned_link(s, owner, pid, lid)
        if body:
            await s.execute(update(BioLink).where(BioLink.id == lid).values(updated_at=_now(), **body))
        return await _page(s, owner, pid)


@router.delete("/{pid}/links/{lid}")
@_safe_write
async def delete_link(pid: str, lid: str) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    _id_or_404(lid)
    async with get_session() as s:
        await _lock_own(s, owner, pid)
        r = await s.execute(delete(BioLink).where(BioLink.id == lid, BioLink.profile_id == pid))
        if r.rowcount == 0:
            raise HTTPException(404, "no such link")
        page = await _page(s, owner, pid)
    await files.discard("links", lid)
    return page


@router.post("/{pid}/links/{lid}/background")
@_safe_write
async def upload_background(pid: str, lid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    _id_or_404(lid)
    await _require(owner, pid, lid)
    return await _set_file(owner, pid, BioLink, BioLink.background_image, "links", lid, "backgroundImage",
                           await _encode(request, images.BACKGROUND_SIDE))


@router.post("/{pid}/links/{lid}/background/vault")
@_safe_write
async def background_from_vault(pid: str, lid: str, request: Request) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    _id_or_404(lid)
    await _require(owner, pid, lid)
    aid, mid, data = await _vault_image(owner, pid, request, images.BACKGROUND_SIDE)
    log.info("bio admin: background from vault: page=%s link=%s account=%s media=%s", pid, lid, aid, mid)
    return _audit_as(request, await _set_file(owner, pid, BioLink, BioLink.background_image, "links", lid,
                                              "backgroundImage", data))


@router.delete("/{pid}/links/{lid}/background")
@_safe_write
async def remove_background(pid: str, lid: str) -> dict[str, Any]:
    owner = await _owner()
    _id_or_404(pid)
    return await _set_file(owner, pid, BioLink, BioLink.background_image, "links", _id_or_404(lid),
                           "backgroundImage", None)
