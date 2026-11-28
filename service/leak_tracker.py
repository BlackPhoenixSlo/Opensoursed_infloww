from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import account_health
import runtime_switches
from agency_context import AgencyContext, agency_context
from automations._knobs import test_mode
from db.engine import get_session
from db.models import LeakTrackerTenant, LeakWatch, LeakWatchTombstone
from permissions import leak_page_granted, leak_writer, removal_offer_viewer
from send_ops import cells
from settings_schema import applied_blob
from tenant_keys import NON_LLM_PROVIDERS, TRACKER_PROVIDER as PROVIDER, get_key, set_keys

log = logging.getLogger("of-relay.leak_tracker")

FLAG = "leak_tracker"
KEY_SHAPE = re.compile(r"ltk_[A-Za-z0-9]{32,}")
TIMEOUT = httpx.Timeout(10.0, connect=3.0)
INLINE_TIMEOUT = httpx.Timeout(15.0, connect=3.0)
NOT_BOUND = "Connect the removal service again before deleting"
USER_DELETE_PENDING = "Leak watch deletes are still pending at the removal service; try again later"
USER_DELETE_PENDING_OFF = ("Leak watch deletes are still pending at the removal service and the Leak tracker is "
                           "switched off on this server; switch it back on so they can finish, then try again")
SYNC_EVERY_S = 3600
SYNC_FIRST_AFTER_S = 60
TOMBSTONES_EVERY_S = 600
TOMBSTONES_FIRST_AFTER_S = 60

_invalid: set[str] = set()
_copies: dict[tuple[str, str], tuple[Any, str]] = {}
_wake = asyncio.Event()


@dataclass(frozen=True)
class Me:
    tenant_id: str
    brand: str | None


@dataclass(frozen=True)
class Copy:
    body: Any
    stale: bool
    fetched_at: str


@dataclass(frozen=True)
class Gates:
    ctx: AgencyContext
    key: str
    can_write: bool
    offer_viewer: bool


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def tracker_url() -> str | None:
    raw = (os.environ.get("LEAK_TRACKER_URL") or "").strip()
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
    except ValueError:
        return None
    if not host:
        return None
    if parts.scheme == "https" or (parts.scheme == "http" and test_mode() and _loopback(host)):
        return raw.rstrip("/")
    return None


# The Front door cannot route /admin/leaks, so cell mode keeps the tracker off whatever its env says.
def deployment_on() -> bool:
    return not cells() and tracker_url() is not None and runtime_switches.on("LEAK_TRACKER_ENABLED")


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not Found")


def page_on(ctx: AgencyContext, flags: dict[str, Any], roles: dict[str, Any]) -> bool:
    return deployment_on() and flags.get(FLAG) is True and leak_page_granted(ctx, roles)


async def require_gates(request: Request, *, need_key: bool) -> Gates:
    gates = getattr(request.state, "leak_tracker_gates", None)
    if gates is None:
        gates = request.state.leak_tracker_gates = await _resolve_gates(request)
    if need_key and not gates.key:
        raise not_found()
    return gates


async def _resolve_gates(request: Request) -> Gates:
    if not deployment_on():
        raise not_found()
    try:
        ctx = await agency_context(
            account_id=request.headers.get("x-account-id") or request.query_params.get("account_id") or None)
    except HTTPException:
        raise not_found() from None
    async with get_session() as s:
        flags: dict[str, Any] = await applied_blob(s, ctx.agency_user_id, "flags")
        roles: dict[str, Any] = await applied_blob(s, ctx.agency_user_id, "roles")
    if not page_on(ctx, flags, roles):
        raise not_found()
    key = await get_key(ctx.agency_user_id, PROVIDER)
    return Gates(ctx=ctx, key=key, can_write=leak_writer(ctx, roles), offer_viewer=removal_offer_viewer(ctx, roles))


class Unreachable(Exception):
    pass


class Down(Unreachable):
    pass


class KeyRefused(Exception):
    pass


class ContractError(Exception):
    pass


class Gone(Exception):
    pass


def watch_acknowledged(r: httpx.Response, watch_id: str) -> bool:
    if r.status_code != 200:
        return False
    try:
        ack = r.json()
    except ValueError:
        return False
    return isinstance(ack, dict) and ack.get("watch_id") == watch_id


def gone(r: httpx.Response) -> bool:
    if r.status_code != 410:
        return False
    try:
        body = r.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("error") == "watch_deleted"


def key_invalid(agency_user_id: str) -> bool:
    return agency_user_id in _invalid


async def _invalidate_key(agency_user_id: str, key: str) -> None:
    if await get_key(agency_user_id, PROVIDER) == key:
        _invalid.add(agency_user_id)
        drop_copies(agency_user_id)


def forget_invalid(agency_user_id: str) -> None:
    _invalid.discard(agency_user_id)


async def call(agency_user_id: str | None, key: str, method: str, path: str, json: Any = None, *,
               timeout: httpx.Timeout = TIMEOUT) -> httpx.Response:
    base = tracker_url()
    if base is None:
        raise Unreachable()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as c:
            r = await asyncio.wait_for(
                c.request(method, base + path, headers={"Authorization": f"Bearer {key}"}, json=json),
                timeout=timeout.read,
            )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise Down() from None
    except (httpx.HTTPError, TimeoutError):
        raise Unreachable() from None
    if r.status_code == 401:
        if agency_user_id:
            await _invalidate_key(agency_user_id, key)
        raise KeyRefused()
    if r.status_code in (502, 503, 504):
        raise Down()
    if r.status_code >= 500:
        raise Unreachable()
    return r


async def open_stream(agency_user_id: str, key: str, path: str,
                      byte_range: str | None) -> tuple[httpx.AsyncClient, httpx.Response]:
    base = tracker_url()
    if base is None:
        raise Unreachable()
    client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    req = client.build_request("GET", base + path, headers={
        "Authorization": f"Bearer {key}", "Accept-Encoding": "identity", **({"Range": byte_range} if byte_range else {})})
    for name in ("user-agent", "accept"):
        req.headers.pop(name, None)
    try:
        r = await asyncio.wait_for(client.send(req, stream=True), timeout=TIMEOUT.read)
    except BaseException as e:
        await client.aclose()
        if isinstance(e, (httpx.HTTPError, TimeoutError)):
            raise Unreachable() from None
        raise
    if r.status_code == 401:
        await r.aclose()
        await client.aclose()
        await _invalidate_key(agency_user_id, key)
        raise KeyRefused()
    return client, r


async def read(agency_user_id: str, key: str, path: str, parse: Callable[[Any], Any], *,
               keep: bool = True) -> Copy | None:
    try:
        if key_invalid(agency_user_id):
            raise KeyRefused()
        r = await call(agency_user_id, key, "GET", path)
        if r.status_code == 429:
            raise Unreachable()
    except Unreachable:
        hit = _copies.get((agency_user_id, path)) if keep else None
        return Copy(hit[0], True, hit[1]) if hit else None
    if gone(r):
        raise Gone()
    try:
        body = r.json()
    except ValueError:
        raise ContractError() from None
    if r.status_code != 200:
        raise ContractError()
    body = parse(body)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if keep:
        _copies[(agency_user_id, path)] = (body, fetched_at)
    return Copy(body, False, fetched_at)


def drop_copies(agency_user_id: str) -> None:
    for k in [k for k in _copies if k[0] == agency_user_id]:
        del _copies[k]


def drop_watch_copies(agency_user_id: str, watch_id: str) -> None:
    for k, (body, at) in list(_copies.items()):
        if k[0] != agency_user_id:
            continue
        if watch_id in k[1]:
            del _copies[k]
        elif isinstance(body, dict) and watch_id in body:
            _copies[k] = ({w: c for w, c in body.items() if w != watch_id}, at)


async def forget_watch(agency_user_id: str, watch_id: str) -> None:
    async with get_session() as s:
        await s.execute(delete(LeakWatch).where(LeakWatch.watch_id == watch_id))
    drop_watch_copies(agency_user_id, watch_id)


async def me(agency_user_id: str | None, key: str) -> Me:
    r = await call(agency_user_id, key, "GET", "/v1/me")
    try:
        body = r.json()
    except ValueError:
        body = None
    if r.status_code != 200 or not isinstance(body, dict) or not isinstance(body.get("tenant_id"), str) \
            or not body["tenant_id"]:
        raise Unreachable()
    brand = body.get("brand")
    return Me(tenant_id=body["tenant_id"], brand=brand if isinstance(brand, str) and brand else None)


async def bind_tenant(agency_user_id: str, tenant_id: str) -> str | None:
    async with get_session() as s:
        await s.execute(sqlite_insert(LeakTrackerTenant).values(
            agency_user_id=agency_user_id, tenant_id=tenant_id, bound_at=datetime.utcnow(),
        ).on_conflict_do_nothing(index_elements=[LeakTrackerTenant.agency_user_id]))
    return await bound_tenant(agency_user_id)


async def bound_tenant(agency_user_id: str) -> str | None:
    async with get_session() as s:
        return await s.scalar(select(LeakTrackerTenant.tenant_id).where(
            LeakTrackerTenant.agency_user_id == agency_user_id))


async def store_key(agency_user_id: str, key: str) -> None:
    await set_keys(agency_user_id, {PROVIDER: key}, known=NON_LLM_PROVIDERS)
    forget_invalid(agency_user_id)
    drop_copies(agency_user_id)


def jobs_on() -> bool:
    return not cells() and tracker_url() is not None


def paused(on: bool, flag: bool, deactivated: bool) -> bool:
    return not on or not flag or deactivated


def watch_body(account_id: str, paused: bool, *, platform: str, username: str, verified: bool, display_name: str,
               aliases_json: str | None, instagram: str | None, x: str | None) -> dict[str, Any]:
    return {"account_id": account_id, "platform": platform, "username": username, "verified": verified,
            "display_name": display_name, "aliases": json.loads(aliases_json or "[]"), "instagram": instagram, "x": x,
            "paused": paused}


_save_locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()


def watch_lock(agency: str, account_id: str) -> asyncio.Lock:
    return _save_locks.setdefault((agency, account_id), asyncio.Lock())


def watch_synced(w: LeakWatch) -> bool:
    return w.synced_at is not None and w.synced_at >= w.updated_at


async def sync_watches(now: datetime | None = None) -> None:
    if not deployment_on():
        return
    now = now or datetime.utcnow()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    off = await account_health.deactivated_ids()
    by_agency: dict[str, list[LeakWatch]] = defaultdict(list)
    async with get_session() as s:
        for w in (await s.execute(select(LeakWatch).order_by(LeakWatch.id))).scalars():
            by_agency[w.agency_user_id].append(w)
    for agency, watches in by_agency.items():
        key = await get_key(agency, PROVIDER)
        if not key or key_invalid(agency):
            continue
        async with get_session() as s:
            flag = (await applied_blob(s, agency, "flags")).get(FLAG) is True
        for w in watches:
            bit = paused(w.on, flag, w.account_id in off)
            if watch_synced(w) and w.synced_paused == bit and w.synced_at >= day:
                continue
            current = (LeakWatch.watch_id == w.watch_id, LeakWatch.updated_at == w.updated_at)
            async with watch_lock(agency, w.account_id):
                async with get_session() as s:
                    if await s.scalar(select(LeakWatch.id).where(*current)) is None:
                        continue
                body = watch_body(w.account_id, bit, platform=w.platform, username=w.username, verified=w.verified,
                                  display_name=w.display_name, aliases_json=w.aliases_json,
                                  instagram=w.instagram, x=w.x)
                try:
                    r = await call(agency, key, "PUT", f"/v1/watches/{w.watch_id}", json=body)
                except Down:
                    return
                except Unreachable:
                    log.warning("leak watch sync: %s failed on the service side", w.watch_id)
                    continue
                except KeyRefused:
                    break
                if gone(r):
                    await forget_watch(agency, w.watch_id)
                    continue
                if r.status_code == 429:
                    break
                if not watch_acknowledged(r, w.watch_id):
                    log.warning("leak watch sync: %s received no matching acknowledgement (HTTP %d)", w.watch_id, r.status_code)
                    continue
                at = max(now, w.updated_at)
                async with get_session() as s:
                    await s.execute(update(LeakWatch).where(*current)
                                    .values(updated_at=at, synced_at=at, synced_paused=bit))


async def drop_watches(*, account_id: str | None = None, agency_user_id: str | None = None) -> None:
    if account_id is None and agency_user_id is None:
        raise ValueError("drop_watches needs an account or an Agency")
    q = select(LeakWatch, LeakTrackerTenant.tenant_id).outerjoin(
        LeakTrackerTenant, LeakTrackerTenant.agency_user_id == LeakWatch.agency_user_id)
    if account_id is not None:
        q = q.where(LeakWatch.account_id == account_id)
    if agency_user_id is not None:
        q = q.where(LeakWatch.agency_user_id == agency_user_id)
    now = datetime.utcnow()
    async with get_session() as s:
        hits = (await s.execute(q)).all()
        if not hits:
            return
        if any(tenant is None for _, tenant in hits):
            raise HTTPException(status_code=409, detail=NOT_BOUND)
        await s.execute(sqlite_insert(LeakWatchTombstone).values([
            {"watch_id": w.watch_id, "agency_user_id": w.agency_user_id, "account_id": w.account_id,
             "tenant_id": tenant, "requested_at": now} for w, tenant in hits
        ]).on_conflict_do_nothing(index_elements=[LeakWatchTombstone.watch_id]))
        await s.execute(delete(LeakWatch).where(LeakWatch.watch_id.in_([w.watch_id for w, _ in hits])))
    for w, _ in hits:
        drop_watch_copies(w.agency_user_id, w.watch_id)
    _wake.set()


async def pending(agency_user_id: str) -> bool:
    async with get_session() as s:
        return await s.scalar(select(LeakWatchTombstone.watch_id).where(
            LeakWatchTombstone.agency_user_id == agency_user_id).limit(1)) is not None


async def _missed(watch_id: str, error: str, *, attempted: bool = True) -> None:
    t = LeakWatchTombstone.__table__
    async with get_session() as s:
        await s.execute(update(t).where(t.c.watch_id == watch_id).values(
            last_error=error, **({"attempts": t.c.attempts + 1} if attempted else {})))


async def land_tombstones(agency_user_id: str | None = None, *, inline: bool = False) -> None:
    if not jobs_on():
        return
    by_agency: dict[str, list[LeakWatchTombstone]] = defaultdict(list)
    q = select(LeakWatchTombstone).order_by(LeakWatchTombstone.created_at, LeakWatchTombstone.watch_id)
    if agency_user_id is not None:
        q = q.where(LeakWatchTombstone.agency_user_id == agency_user_id)
    async with get_session() as s:
        for t in (await s.execute(q)).scalars():
            by_agency[t.agency_user_id].append(t)
    for agency, stones in by_agency.items():
        key = await get_key(agency, PROVIDER)
        if not key or key_invalid(agency):
            continue
        tenant = await bound_tenant(agency)
        for t in stones:
            if t.tenant_id != tenant:
                await _missed(t.watch_id, "tenant_mismatch", attempted=False)
                if inline:
                    return
                continue
            at = t.requested_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                r = await call(agency, key, "DELETE", f"/v1/watches/{t.watch_id}?requested_at={at}",
                               timeout=INLINE_TIMEOUT if inline else TIMEOUT)
            except Down:
                await _missed(t.watch_id, "unreachable")
                return
            except Unreachable:
                await _missed(t.watch_id, "service_error")
                if inline:
                    return
                continue
            except KeyRefused:
                await _missed(t.watch_id, "key_invalid")
                break
            if 200 <= r.status_code < 300:
                async with get_session() as s:
                    await s.execute(delete(LeakWatchTombstone).where(LeakWatchTombstone.watch_id == t.watch_id))
                continue
            await _missed(t.watch_id, f"http_{r.status_code}")
            if inline or r.status_code == 429:
                break


async def before_user_delete(agency_user_id: str) -> None:
    await drop_watches(agency_user_id=agency_user_id)
    await land_tombstones(agency_user_id, inline=True)
    if await pending(agency_user_id):
        raise HTTPException(status_code=409, detail=USER_DELETE_PENDING if jobs_on() else USER_DELETE_PENDING_OFF)


async def tombstone_loop() -> None:
    delay = TOMBSTONES_FIRST_AFTER_S
    while True:
        try:
            await asyncio.wait_for(_wake.wait(), delay)
        except TimeoutError:
            pass
        _wake.clear()
        delay = TOMBSTONES_EVERY_S
        try:
            await land_tombstones()
        except Exception:
            log.warning("leak watch tombstones cycle failed", exc_info=True)
