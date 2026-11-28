from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Literal
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import account_health
import account_page
import agency_scope
import platforms
import runtime_switches
from agency_context import AgencyContext, agency_context
from automations._knobs import test_mode
from db.engine import get_session
from db.of_writer import immediate_session
from db.models import (
    LeakTrackerTenant, LeakWatch, LeakWatchAutoSkip, LeakWatchOptOut, LeakWatchTombstone, UserAccount,
)
from permissions import leak_page_granted, leak_writer, removal_offer_viewer
from send_ops import cells
from settings_schema import applied_blob
from tenant_keys import NON_LLM_PROVIDERS, TRACKER_PROVIDER as PROVIDER, get_key, owners_of_many, set_keys

log = logging.getLogger("of-relay.leak_tracker")

FLAG = "leak_tracker"
KEY_SHAPE = re.compile(r"ltk_[A-Za-z0-9]{32,}")
TIMEOUT = httpx.Timeout(10.0, connect=3.0)
INLINE_TIMEOUT = httpx.Timeout(15.0, connect=3.0)
INLINE_BUDGET_S = 20
NOT_BOUND = "Connect the removal service again before deleting"
USER_DELETE_PENDING = "Leak watch deletes are still pending at the removal service; try again later"
USER_DELETE_PENDING_OFF = ("Leak watch deletes are still pending at the removal service and the Leak tracker is "
                           "switched off on this server; switch it back on so they can finish, then try again")
SYNC_EVERY_S = 3600
SYNC_FIRST_AFTER_S = 60
TOMBSTONES_EVERY_S = 600
TOMBSTONES_FIRST_AFTER_S = 60
AUTO_CONSENT = "auto:owner-default"
ENSURE_BATCH = 10
ENSURE_GAP_S = 60.0
AUTO_RETRY = timedelta(days=1)
TENANT_RETRY_MIN_S, TENANT_RETRY_MAX_S = 30.0, 1800.0
HANDLE = re.compile(r"[A-Za-z0-9_.-]{2,64}")
NAME_MAX = 64

_invalid: set[str] = set()
_copies: dict[tuple[str, str], tuple[Any, str]] = {}
_wake = asyncio.Event()
_tenants: dict[str, str] = {}
_tenant_misses: dict[str, tuple[float, float]] = {}
_capped: dict[str, datetime] = {}
_ensure_asked: dict[str, float] = {}


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
    instance: bool


RefusalKind = Literal["not_found", "key_invalid", "handle_taken", "account_taken", "creator_cap", "waitlist", "identity",
                      "watch_deleted", "unbound", "exists", "watch_paused"]


class Refused(Exception):
    def __init__(self, kind: RefusalKind, detail: Any = None) -> None:
        super().__init__(kind)
        self.kind: RefusalKind = kind
        self.detail = detail


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


def tracker_on(flags: dict[str, Any]) -> bool:
    return flags.get(FLAG) is not False


def page_on(ctx: AgencyContext, flags: dict[str, Any], roles: dict[str, Any]) -> bool:
    return deployment_on() and tracker_on(flags) and leak_page_granted(ctx, roles)


def instance_key() -> str:
    raw = (os.environ.get("LEAK_TRACKER_KEY") or "").strip()
    return raw if KEY_SHAPE.fullmatch(raw) else ""


async def instance_tenant() -> str | None:
    key = instance_key()
    if not key:
        return None
    if key in _tenants:
        return _tenants[key]
    retry_at, wait = _tenant_misses.get(key, (0.0, 0.0))
    now = time.monotonic()
    if now < retry_at:
        return None
    try:
        _tenants[key] = (await me(None, key)).tenant_id
    except (Unreachable, KeyRefused):
        wait = min(max(wait * 2, TENANT_RETRY_MIN_S), TENANT_RETRY_MAX_S)
        _tenant_misses[key] = (now + wait, wait)
        return None
    _tenant_misses.pop(key, None)
    return _tenants[key]


async def agency_key(agency_user_id: str, *, session: AsyncSession | None = None) -> tuple[str, bool]:
    own = await get_key(agency_user_id, PROVIDER, session=session)
    if own:
        return own, False
    inst = await _fallback_key(agency_user_id, session=session)
    return inst, bool(inst)


async def _fallback_key(agency_user_id: str, *, session: AsyncSession | None = None) -> str:
    inst = instance_key()
    if not inst:
        return ""
    held = await binding(agency_user_id, session=session)
    return inst if held is None or held[1] else ""


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
    key, instance = await agency_key(ctx.agency_user_id)
    return Gates(ctx=ctx, key=key, can_write=leak_writer(ctx, roles), offer_viewer=removal_offer_viewer(ctx, roles),
                 instance=instance)


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
    if (await agency_key(agency_user_id))[0] == key:
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


async def opt_out(agency_user_id: str, account_id: str) -> None:
    async with get_session() as s:
        await s.execute(sqlite_insert(LeakWatchOptOut).values(
            agency_user_id=agency_user_id, account_id=account_id, created_at=datetime.utcnow(),
        ).on_conflict_do_nothing())


async def forget_watch(agency_user_id: str, watch_id: str) -> None:
    async with get_session() as s:
        account_id = await s.scalar(select(LeakWatch.account_id).where(LeakWatch.watch_id == watch_id))
        await s.execute(delete(LeakWatch).where(LeakWatch.watch_id == watch_id))
    if account_id is not None:
        await opt_out(agency_user_id, account_id)
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


async def bind_tenant(agency_user_id: str, tenant_id: str, *, via_instance: bool = False) -> tuple[str, bool] | None:
    async with get_session() as s:
        await s.execute(sqlite_insert(LeakTrackerTenant).values(
            agency_user_id=agency_user_id, tenant_id=tenant_id, bound_at=datetime.utcnow(), via_instance=via_instance,
        ).on_conflict_do_nothing(index_elements=[LeakTrackerTenant.agency_user_id]))
    return await binding(agency_user_id)


async def bind_instance(agency_user_id: str) -> bool:
    tenant = await instance_tenant()
    if tenant is None:
        return False
    held = await bind_tenant(agency_user_id, tenant, via_instance=True)
    return held is not None and held[0] == tenant


async def rebind(agency_user_id: str, tenant_id: str) -> None:
    held = await binding(agency_user_id)
    stones = held is not None and not held[1]
    if held is not None and held[1]:
        inst = await instance_tenant()
        if inst is None:
            raise Unreachable()
        stones = held[0] == inst
    now = datetime.utcnow()
    async with get_session() as s:
        rows = list((await s.scalars(select(LeakWatch).where(LeakWatch.agency_user_id == agency_user_id))).all())
        if rows and stones:
            await s.execute(sqlite_insert(LeakWatchTombstone).values([
                {"watch_id": w.watch_id, "agency_user_id": agency_user_id, "account_id": w.account_id,
                 "tenant_id": held[0], "requested_at": now} for w in rows
            ]).on_conflict_do_nothing(index_elements=[LeakWatchTombstone.watch_id]))
        for w in rows:
            w.watch_id, w.synced_at, w.synced_paused, w.updated_at = str(uuid.uuid4()), None, None, now
        await s.execute(update(LeakTrackerTenant).where(LeakTrackerTenant.agency_user_id == agency_user_id)
                        .values(tenant_id=tenant_id, bound_at=now, via_instance=False))
    drop_copies(agency_user_id)
    _wake.set()


async def bound_tenant(agency_user_id: str) -> str | None:
    held = await binding(agency_user_id)
    return held[0] if held else None


async def binding(agency_user_id: str, *, session: AsyncSession | None = None) -> tuple[str, bool] | None:
    async with (get_session() if session is None else nullcontext(session)) as s:
        row = (await s.execute(select(LeakTrackerTenant.tenant_id, LeakTrackerTenant.via_instance).where(
            LeakTrackerTenant.agency_user_id == agency_user_id))).first()
    return (row[0], bool(row[1])) if row else None


async def store_key(agency_user_id: str, key: str, *, pending_message: str | None = None) -> None:
    if not key and pending_message is not None:
        async with immediate_session() as s:
            if await has_stones(s, agency_user_id):
                raise HTTPException(status_code=409, detail=pending_message)
            if (await get_key(agency_user_id, PROVIDER, session=s)
                    and not await _fallback_key(agency_user_id, session=s)
                    and await has_watches(s, agency_user_id)):
                raise HTTPException(status_code=409, detail="Stop tracking every Creator before disconnecting")
            await set_keys(agency_user_id, {PROVIDER: key}, known=NON_LLM_PROVIDERS, session=s)
    else:
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
        key, _ = await agency_key(agency)
        if not key or key_invalid(agency):
            continue
        async with get_session() as s:
            flag = tracker_on(await applied_blob(s, agency, "flags"))
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
                if not deployment_on():
                    return
                try:
                    r = await call(agency, key, "PUT", f"/v1/watches/{w.watch_id}", json=body)
                except Down:
                    break
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


async def has_watches(s: AsyncSession, agency: str) -> bool:
    return await s.scalar(select(LeakWatch.id).where(LeakWatch.agency_user_id == agency).limit(1)) is not None


async def has_stones(s: AsyncSession, agency: str) -> bool:
    return await s.scalar(select(LeakWatchTombstone.watch_id).where(
        LeakWatchTombstone.agency_user_id == agency).limit(1)) is not None


async def pending(agency_user_id: str) -> bool:
    async with get_session() as s:
        return await has_stones(s, agency_user_id)


def user_delete_pending() -> HTTPException:
    return HTTPException(status_code=409, detail=USER_DELETE_PENDING if jobs_on() else USER_DELETE_PENDING_OFF)


async def _missed(watch_id: str, error: str, *, attempted: bool = True) -> None:
    t = LeakWatchTombstone.__table__
    async with get_session() as s:
        await s.execute(update(t).where(t.c.watch_id == watch_id).values(
            last_error=error, **({"attempts": t.c.attempts + 1} if attempted else {})))


async def land_tombstones(agency_user_id: str | None = None, *, timeout: httpx.Timeout = TIMEOUT) -> None:
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
        key, _ = await agency_key(agency)
        if not key or key_invalid(agency):
            continue
        tenant = await bound_tenant(agency)
        inst = instance_key() if any(t.tenant_id != tenant for t in stones) else ""
        inst_tenant = await instance_tenant() if inst else None
        for t in stones:
            use, who = _stone_key(t.tenant_id, tenant, key, agency, inst, inst_tenant)
            if not use:
                await _missed(t.watch_id, "tenant_mismatch", attempted=False)
                continue
            at = t.requested_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                r = await call(who, use, "DELETE", f"/v1/watches/{t.watch_id}?requested_at={at}",
                               timeout=timeout)
            except Down:
                await _missed(t.watch_id, "unreachable")
                break
            except Unreachable:
                await _missed(t.watch_id, "service_error")
                continue
            except KeyRefused:
                await _missed(t.watch_id, "key_invalid")
                break
            if 200 <= r.status_code < 300:
                async with get_session() as s:
                    await s.execute(delete(LeakWatchTombstone).where(LeakWatchTombstone.watch_id == t.watch_id))
                continue
            await _missed(t.watch_id, f"http_{r.status_code}")
            if r.status_code == 429:
                break


def _stone_key(stone_tenant: str, tenant: str | None, key: str, agency: str, inst: str,
               inst_tenant: str | None) -> tuple[str, str | None]:
    if stone_tenant == tenant:
        return key, agency
    if inst and stone_tenant == inst_tenant:
        return inst, None
    return "", None


async def before_user_delete(agency_user_id: str) -> None:
    await drop_watches(agency_user_id=agency_user_id)
    try:
        async with asyncio.timeout(INLINE_BUDGET_S):
            await land_tombstones(agency_user_id, timeout=INLINE_TIMEOUT)
    except TimeoutError:
        pass
    async with get_session() as s:
        if await has_stones(s, agency_user_id):
            raise user_delete_pending()


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


async def live(account_id: str, platform: str) -> dict[str, str] | None:
    if platform != "onlyfans":
        return None
    seen = await account_page.of_me(account_id)
    username = seen.get("username") if seen else None
    if not isinstance(username, str) or not username:
        return None
    name = seen.get("name")
    return {"username": username, "display_name": name[:NAME_MAX] if isinstance(name, str) else ""}


def auto_identity(seen: dict[str, str] | None) -> dict[str, Any] | None:
    if seen is None or not HANDLE.fullmatch(seen["username"].strip()):
        return None
    return {"username": seen["username"].strip().lower(), "display_name": seen["display_name"].strip(), "aliases": [],
            "instagram": None, "x": None}


def identity_out(row: LeakWatch) -> dict[str, Any]:
    return {"platform": row.platform, "username": row.username, "verified": row.verified,
            "display_name": row.display_name, "aliases": json.loads(row.aliases_json or "[]"),
            "instagram": row.instagram, "x": row.x, "on": row.on}


async def watch(agency: str, account_id: str) -> LeakWatch | None:
    async with get_session() as s:
        return await s.scalar(select(LeakWatch).where(LeakWatch.agency_user_id == agency,
                                                      LeakWatch.account_id == account_id))


async def handle_taken(agency: str, platform: str, account_id: str, username: str) -> bool:
    async with get_session() as s:
        return await s.scalar(select(LeakWatch.id).where(
            LeakWatch.agency_user_id == agency, LeakWatch.platform == platform,
            LeakWatch.username == username, LeakWatch.account_id != account_id)) is not None


def _body(r: httpx.Response) -> dict[str, Any] | None:
    try:
        body = r.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def refusal(r: httpx.Response) -> Refused | None:
    body = _body(r) or {}
    if r.status_code == 409 and body.get("error") == "account_taken":
        return Refused("account_taken")
    if r.status_code == 409 and body.get("error") == "creator_cap":
        cap = body.get("creators_max")
        return Refused("creator_cap", cap if isinstance(cap, int) else None)
    if r.status_code == 409 and body.get("error") == "waitlist":
        return Refused("waitlist")
    if r.status_code == 422:
        field = body.get("field")
        return Refused("identity", field if isinstance(field, str) and field else None)
    return None


class Cooldown(Exception):
    def __init__(self, next_refresh_at: str | None, retry_after_s: int | None) -> None:
        super().__init__("cooldown")
        self.next_refresh_at = next_refresh_at
        self.retry_after_s = retry_after_s


def _retry_after(r: httpx.Response, body: dict[str, Any]) -> int | None:
    s = body.get("retry_after_s")
    if type(s) is int and s >= 0:
        return s
    raw = r.headers.get("retry-after", "")
    return int(raw) if raw.isdigit() else None


async def refresh(agency: str, key: str, watch_id: str) -> dict[str, str]:
    if key_invalid(agency):
        raise Refused("key_invalid")
    try:
        r = await call(agency, key, "POST", f"/v1/watches/{watch_id}/refresh")
    except KeyRefused:
        raise Refused("key_invalid") from None
    if gone(r):
        raise Gone()
    body = _body(r)
    if r.status_code == 202:
        if body is None or not isinstance(body.get("queued_at"), str) or not isinstance(body.get("next_refresh_at"), str):
            raise ContractError()
        return {"queued_at": body["queued_at"], "next_refresh_at": body["next_refresh_at"]}
    body = body or {}
    if r.status_code == 429 and body.get("error") == "refresh_cooldown":
        at = body.get("next_refresh_at")
        raise Cooldown(at if isinstance(at, str) else None, _retry_after(r, body))
    if r.status_code == 429:
        raise Cooldown(None, _retry_after(r, body))
    if r.status_code == 409 and body.get("error") == "watch_paused":
        raise Refused("watch_paused")
    if r.status_code == 409 and body.get("error") == "waitlist":
        raise Refused("waitlist")
    if r.status_code == 404:
        raise Refused("not_found")
    raise ContractError()


async def push(agency: str, key: str, watch_id: str, body: dict[str, Any]) -> bool:
    try:
        r = await call(agency, key, "PUT", f"/v1/watches/{watch_id}", json=body)
    except (Unreachable, KeyRefused):
        return False
    if r.status_code == 200:
        return watch_acknowledged(r, watch_id)
    if gone(r):
        raise Gone()
    if refused := refusal(r):
        raise refused
    return False


async def save_watch(agency: str, key: str, account_id: str, ident: dict[str, Any], *, verified: bool,
                     consent_by: str) -> bool:
    if key_invalid(agency):
        raise Refused("key_invalid")
    platform = platforms.for_account(account_id).key
    row = await watch(agency, account_id)
    now = datetime.utcnow()
    current = identity_out(row) if row is not None else None
    changed = current is None or any(current[field] != value for field, value in ident.items())
    consent = {"consent_at": now, "consent_by": consent_by} if changed else {}
    if await handle_taken(agency, platform, account_id, ident["username"]):
        raise Refused("handle_taken")
    kept = row is not None and row.verified and row.username == ident["username"]
    seen = await live(account_id, platform) if verified and not kept else None
    verified = verified and (kept or (seen is not None and seen["username"].lower() == ident["username"]))
    values = {"platform": platform, "username": ident["username"], "verified": verified,
              "display_name": ident["display_name"], "aliases_json": json.dumps(ident["aliases"]),
              "instagram": ident["instagram"], "x": ident["x"]}
    if row is None and await bound_tenant(agency) is None and not await bind_instance(agency):
        raise Refused("unbound")
    if row is None:
        watch_id, on = str(uuid.uuid4()), True
        try:
            async with immediate_session() as s:
                usable, _ = await agency_key(agency, session=s)
                if not usable or account_id not in await agency_scope.agency_account_ids(s, agency):
                    raise Refused("not_found")
                s.add(LeakWatch(
                    agency_user_id=agency, account_id=account_id, watch_id=watch_id, on=on,
                    created_at=now, updated_at=now, **consent, **values,
                ))
        except IntegrityError:
            if await handle_taken(agency, platform, account_id, ident["username"]):
                raise Refused("handle_taken") from None
            if await watch(agency, account_id) is not None:
                raise Refused("exists") from None
            raise
    else:
        watch_id, on = row.watch_id, row.on
    bit = paused(on, True, await account_health.is_deactivated(account_id))
    try:
        pushed = await push(agency, key, watch_id, watch_body(account_id, bit, **values))
    except Gone:
        await forget_watch(agency, watch_id)
        raise Refused("watch_deleted") from None
    except Refused:
        if row is None:
            async with get_session() as s:
                await s.execute(delete(LeakWatch).where(LeakWatch.watch_id == watch_id))
        raise
    async with get_session() as s:
        live_row = await s.scalar(select(LeakWatch).where(LeakWatch.watch_id == watch_id))
        if live_row is not None:
            for k, v in {**values, **consent}.items():
                setattr(live_row, k, v)
            live_row.updated_at = now
            if pushed:
                live_row.synced_at = now
                live_row.synced_paused = bit
            if row is None:
                await s.execute(delete(LeakWatchOptOut).where(LeakWatchOptOut.agency_user_id == agency,
                                                              LeakWatchOptOut.account_id == account_id))
    return pushed


async def _auto_blocked(agency: str, ids: set[str], now: datetime) -> set[str]:
    found: set[str] = set()
    async with get_session() as s:
        for t, extra in ((LeakWatch, ()), (LeakWatchOptOut, ()), (LeakWatchTombstone, ()),
                         (LeakWatchAutoSkip, (LeakWatchAutoSkip.retry_after > now,))):
            found |= set((await s.scalars(select(t.account_id).where(
                t.agency_user_id == agency, t.account_id.in_(ids), *extra))).all())
    return found


async def _skip_auto(agency: str, account_id: str, reason: str, now: datetime) -> None:
    async with get_session() as s:
        await s.execute(sqlite_insert(LeakWatchAutoSkip).values(
            agency_user_id=agency, account_id=account_id, reason=reason, retry_after=now + AUTO_RETRY,
        ).on_conflict_do_update(index_elements=[LeakWatchAutoSkip.agency_user_id, LeakWatchAutoSkip.account_id],
                                set_={"reason": reason, "retry_after": now + AUTO_RETRY}))


def capped(key: str, now: datetime) -> bool:
    return _capped.get(key, datetime.min) > now


async def ensure_watches(agency: str, key: str, account_ids: Iterable[str], now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    ids = set(account_ids)
    ids -= await _auto_blocked(agency, ids, now)
    owners = await owners_of_many(ids)
    off = await account_health.deactivated_ids()
    todo = sorted(aid for aid, who in owners.items()
                  if aid not in off and platforms.for_account(aid).key == "onlyfans" and agency in who)
    made = 0
    for aid in todo[:ENSURE_BATCH]:
        ident = auto_identity(await live(aid, "onlyfans"))
        if ident is None:
            await _skip_auto(agency, aid, "no_identity", now)
            continue
        async with watch_lock(agency, aid):
            if await _auto_blocked(agency, {aid}, now):
                continue
            try:
                synced = await save_watch(agency, key, aid, ident, verified=True, consent_by=AUTO_CONSENT)
            except Refused as e:
                if e.kind in ("creator_cap", "waitlist"):
                    _capped[key] = now + AUTO_RETRY
                    return made
                if e.kind in ("key_invalid", "unbound"):
                    return made
                if e.kind not in ("exists", "not_found"):
                    await _skip_auto(agency, aid, e.kind, now)
                continue
        made += 1
        if not synced:
            break
    return made


_agency_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


async def ensure_agency(agency: str, now: datetime | None = None) -> int:
    if not deployment_on():
        return 0
    now = now or datetime.utcnow()
    lock = _agency_locks.setdefault(agency, asyncio.Lock())
    if lock.locked():
        return 0
    async with lock:
        async with get_session() as s:
            if not tracker_on(await applied_blob(s, agency, "flags")):
                return 0
            ids = await agency_scope.agency_account_ids(s, agency)
        key, _ = await agency_key(agency)
        if not key or key_invalid(agency) or capped(key, now):
            return 0
        return await ensure_watches(agency, key, ids, now)


async def ensure_each(agencies: Iterable[str], now: datetime | None = None) -> None:
    for agency in agencies:
        try:
            await ensure_agency(agency, now)
        except Exception:
            log.warning("leak auto-track failed for Agency %s", agency, exc_info=True)


async def ensure_all(now: datetime | None = None) -> None:
    if not deployment_on():
        return
    async with get_session() as s:
        agencies = sorted(set((await s.scalars(select(UserAccount.user_id).distinct())).all()))
    await ensure_each(agencies, now)


def ensure_wanted(agency: str) -> bool:
    now = time.monotonic()
    if agency in _ensure_asked and now - _ensure_asked[agency] < ENSURE_GAP_S:
        return False
    _ensure_asked[agency] = now
    return True


async def sync_all() -> None:
    try:
        await ensure_all()
    except Exception:
        log.warning("leak auto-track cycle failed", exc_info=True)
    await sync_watches()
