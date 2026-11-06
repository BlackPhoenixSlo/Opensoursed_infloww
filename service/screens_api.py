"""service/screens_api.py — one relay call per screen (the owner's "bundle them per screen").

A phone ~250 ms from the host paid one round trip per Creator per read: the Dashboard's cold
open was 57 relay calls in 3 dependent steps (Applied settings and the accounts list, then per
Creator `users/me`, `subscriptions/count/all`, `subscriptions/subscribers/chart`), Messages
Pro's All scope 2 per Creator (`users/notifications/count`, `/chats` page 0). These routes
answer a screen's whole first paint in one call:

  GET /admin/screens/dashboard?from=&to=&accounts=&deadline_ms=
      {settings, accounts, perModel, creators: [{id, profile, subscriberCounts, newFans, asOf, stale}],
       errors, asOf}
  GET /admin/screens/inbox?cursor=&accounts=&deadline_ms=
      {accounts, notificationCounts: {aid: body}, chats: {aid: body}, nextCursorByAccount: {aid: int|null},
       stale: [aid], errors, asOf}

One source of truth: every value is the exact body its own route answers (`settings` =
GET /admin/settings/applied, `accounts` = GET /admin/accounts or, chatter-only, GET
/chatter/me/accounts, `perModel` = GET /admin/stats/per-model, `profile` = GET
/api/of/v2/users/me, ...), produced by calling that route's function with EVERY argument
explicit (a FastAPI `Query(...)` default is a truthy object when called directly). The
client seeds the same query keys with the same transforms its hooks run.

Authorization is the per-Creator path's, not a copy: each inner read gets a real Request for
its own route (`X-Account-Id`, the caller's `X-Priority`), runs the role hook
(`permissions.role_enforcement_middleware`: chatter role pages, hidden Dashboard cards) and
`server._resolve_account_id` (404 unknown, 403 not the principal's) BEFORE any cache is
read, and is served with that Request in `server._request_ctx`, so the route's own
resolver, `_proxy` (per-account lanes, error mapping, session-dead) and caches run as for
the browser's call. The Creators read are the principal's own accounts list, filtered by the
client's predicates (`_dashboard_ids`, `_inbox_ids`); `accounts=` only narrows that set.

Never the slowest Creator: every read starts at once (at most `BUNDLE_READS` in flight per
bundle; the real bounds are process-wide: single-flight per key, `_FETCH_SLOTS`, account lanes) and the bundle answers at `deadline_ms` (default 2000) with what is done. A read
still running is that Creator's `stale` plus a 504 `bundle_deadline` error, value null; it is
never cancelled (it may hold relay_cache's single-flight lock; finishing warms the cache the
client's background refresh then hits) and is kept referenced until done. A read still
queued at the deadline runs on too (reported late): no Creator is skipped on every cold load. The two reads with no server cache of their own
(subscriber counts, subscribers chart) are cached here, 60 s, single-flight, their upstream
dispatch capped process-wide (`_FETCH_SLOTS`), so 200 Dashboards cost OF one read per
Creator, not 200.

Errors: `[{accountId, read, status, detail}]`, the status and detail the per-Creator route
would have answered (403 role / not yours, 404, 409, 502 OF, 503 no session, 504). The client
maps an errored read to what its hook shows on a failed fetch today (profile and counts null,
the bell 0, the Creator's chats dropped) and keeps its own copy only on `bundle_deadline`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from starlette.requests import Request as StarletteRequest

import accounts_admin_api
import auth
import chatters
import permissions
import relay_cache
import relay_host
import settings_api
import stats_per_model

log = logging.getLogger("of-relay.screens")
router = APIRouter()

DEADLINE_MS = 2000
DEADLINE_MAX_MS = 30000
BUNDLE_READS = 160         # inner reads in flight per bundle: a 50-Creator screen all at once, as the
                           # browser's per-Creator fan-out was (32 left 5 waves of 400 ms past the deadline)
FETCH_SLOTS = 64           # this module's own upstream dispatches in flight, process-wide
SHARE_S = 1.0              # a finished read's result reused by identical reads (`_shared`)
CACHE_TTL_S = 60.0         # its two caches (counts, chart); the client keeps them 30 min
CHATS_PAGE = 25            # useChatList's PAGE_SIZE = the roster badge's window (_ROSTER_SCAN_MAX)
PER_MODEL_CARD = "/#card-per-model"
_FETCH_SLOTS = asyncio.Semaphore(FETCH_SLOTS)
_SHARED: dict[tuple, asyncio.Future] = {}   # identical reads in flight (`_shared`)
_INFLIGHT: set[asyncio.Task] = set()   # reads past their bundle's deadline, kept alive until done


@dataclass
class _Read:
    name: str                 # the bundle field: profile, subscriberCounts, newFans, notificationCounts, chats
    aid: str | None           # the Creator (X-Account-Id); None for an All-scope read
    path: str                 # the per-Creator route it stands for
    query: dict[str, Any]
    call: Callable[[], Awaitable[Any]]


@dataclass
class _Done:
    read: _Read
    value: Any = None
    status: int | None = None     # None = ok
    detail: Any = None
    at: float = 0.0               # epoch s it finished


_PASSED = object()


async def _passed(_request) -> object:
    return _PASSED


def _inner_request(outer: Request, path: str, query: dict[str, Any], aid: str | None) -> StarletteRequest:
    """A Request for the per-Creator route itself, as the browser would have sent it. Priority: the
    caller's for the Creator it has open (`focus=`) and for unscoped reads; every other Creator's
    read is background (its lane's background cap: a tap on that Creator never waits behind the
    bundle, and no Creator but the open one reads as user-active to of_pacing / the vault collector)."""
    headers = [(b"x-account-id", aid.encode())] if aid else []
    pri = outer.headers.get("x-priority")
    if aid and aid != outer.query_params.get("focus"):
        pri = "background"
    if pri:
        headers.append((b"x-priority", pri.encode()))
    q = {k: v for k, v in query.items() if v is not None}
    scope = {k: v for k, v in outer.scope.items() if k in ("app", "server", "client", "scheme", "root_path",
                                                             "http_version", "state")}
    scope.update(type="http", method="GET", path=path, raw_path=path.encode(),
                 query_string=urlencode(q).encode(), headers=headers)
    return StarletteRequest(scope)


async def _gate(inner: StarletteRequest) -> tuple[int, Any] | None:
    """The refusal the per-Creator call would get before its handler (or its own cache) runs:
    the role hook, then the ownership resolver. None = allowed."""
    resp = await permissions.role_enforcement_middleware(inner, _passed)
    if resp is not _PASSED:
        try:
            detail = json.loads(resp.body).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        return resp.status_code, detail
    if inner.headers.get("x-account-id"):
        try:
            relay_host.live_server()._resolve_account_id(inner)
        except HTTPException as e:
            return e.status_code, e.detail
    return None


async def _serve(outer: Request, read: _Read, sem: asyncio.Semaphore) -> _Done:
    async with sem:
        srv = relay_host.live_server()
        inner = _inner_request(outer, read.path, read.query, read.aid)
        token = srv._request_ctx.set(inner)
        try:
            refused = await _gate(inner)
            if refused is not None:
                return _Done(read, status=refused[0], detail=refused[1], at=time.time())
            return _Done(read, value=await _shared(read, inner), at=time.time())
        except HTTPException as e:
            return _Done(read, status=e.status_code, detail=e.detail, at=time.time())
        except Exception:  # noqa: BLE001  one Creator's bug must not sink the screen
            log.exception("screen read failed read=%s account=%s", read.name, read.aid)
            return _Done(read, status=500, detail="internal error", at=time.time())
        finally:
            srv._request_ctx.reset(token)


def _principal() -> tuple:
    u, c = auth.get_request_user(), chatters.get_request_chatter()
    return (u.id if u else None, c.id if c else None)


async def _shared(read: _Read, inner: StarletteRequest) -> Any:
    """Identical reads run once per SHARE_S: same principal, read, Creator, query and priority
    (190 owner phones opening Messages Pro in the same second cost what one does: list_chats
    annotates its page with 3 DB reads per call, cache hit or not; Per-model stats aggregate the
    ledger). Each caller has passed its own gate first; a success is reused for SHARE_S after it
    finishes (on top of list_chats' own 10 min cache), an error never."""
    key = (_principal(), read.name, read.aid, tuple(sorted((k, str(v)) for k, v in read.query.items())),
           inner.headers.get("x-priority"))
    task = _SHARED.get(key)
    if task is None:
        task = asyncio.ensure_future(read.call())   # copies this context: the inner Request in _request_ctx
        _SHARED[key] = task

        def _forget(t: asyncio.Future, k: tuple = key) -> None:
            drop = lambda: _SHARED.pop(k, None) if _SHARED.get(k) is t else None  # noqa: E731
            if t.cancelled() or t.exception() is not None:
                drop()                                   # an error is never served to the next caller
            else:
                asyncio.get_running_loop().call_later(SHARE_S, drop)
        task.add_done_callback(_forget)
    return await asyncio.shield(task)


def _keep(task: asyncio.Task) -> None:
    _INFLIGHT.add(task)

    def _drop(t: asyncio.Task) -> None:
        _INFLIGHT.discard(t)
        if not t.cancelled():
            t.exception()   # retrieved: never "exception was never retrieved"
    task.add_done_callback(_drop)


async def _run(outer: Request, reads: list[_Read], deadline_at: float) -> tuple[list[_Done], list[_Read]]:
    """Every read at once (BUNDLE_READS in flight); what is done by `deadline_at` (monotonic),
    and the reads not done then: running or still queued, all left to finish (referenced), so the
    next bundle finds every Creator warm, never the same tail skipped on each cold load."""
    if not reads:
        return [], []
    sem = asyncio.Semaphore(BUNDLE_READS)
    tasks = {asyncio.create_task(_serve(outer, r, sem), name=f"screen-{r.name}-{r.aid}"): r
             for r in reads}
    done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline_at - time.monotonic()))
    for t in pending:
        _keep(t)
    return [t.result() for t in done], [tasks[t] for t in pending]


async def _cached(namespace: str, aid: str, key: tuple, fn: Callable[[], Any]) -> Any:
    """`fn` (a sync route function) through relay_cache: single-flight, CACHE_TTL_S, errors
    never cached, its thread dispatch under the process-wide cap."""
    async def fetch() -> Any:
        async with _FETCH_SLOTS:
            return await asyncio.to_thread(fn)
    return await relay_cache.get_or_fetch(namespace, aid, key, CACHE_TTL_S, fetch)


async def _accounts() -> Any:
    """The principal's own accounts read, its exact body: GET /admin/accounts, or for a
    chatter-only session GET /chatter/me/accounts (useAccounts' two sources)."""
    if auth.get_request_user() is None and chatters.get_request_chatter() is not None:
        return jsonable_encoder(await chatters.me_accounts())
    return await accounts_admin_api.admin_accounts_list(Response())


def _rows(accounts: Any) -> list[dict]:
    """The Creator rows of either accounts body, `id` and the client's defaults made total
    (a chatter row has no `has_session`: useAccounts assumes true; watchers are never Creators)."""
    rows = accounts if isinstance(accounts, list) else (accounts or {}).get("accounts") or []
    out = []
    for a in rows:
        if a.get("role") == "watcher":
            continue
        out.append({**a, "id": a.get("id") or a.get("account_id"),
                    "has_session": a.get("has_session", True), "is_active": a.get("is_active", True)})
    return out


def _dashboard_ids(accounts: Any) -> list[str]:
    """The Creators whose Per-model card reads OF (PerModelKpiGrid's ofReadState:
    sessionConnectivity is null: no dead session, a session, active)."""
    return [a["id"] for a in _rows(accounts)
            if not a.get("session_dead_at") and a["has_session"] and a["is_active"]]


def _inbox_ids(accounts: Any) -> list[str]:
    """The Creators the All Models Fan List fans out to (usePlatformAccounts on OnlyFans:
    a session, active, not Fansly; a dead session still counts)."""
    return [a["id"] for a in _rows(accounts)
            if a["has_session"] and a["is_active"] and a.get("platform") != "fansly"]


def _narrow(ids: list[str], wanted: str | None) -> tuple[list[str], list[dict]]:
    """`accounts=` narrows the screen's set; an id outside it is an error, nothing read."""
    if not wanted:
        return ids, []
    asked = list(dict.fromkeys(x for x in wanted.split(",") if x))
    keep = [a for a in asked if a in ids]
    return keep, [{"accountId": a, "read": "*", "status": 404, "detail": "not on this screen"}
                  for a in asked if a not in ids]


def _error(d: _Done) -> dict:
    return {"accountId": d.read.aid, "read": d.read.name, "status": d.status, "detail": d.detail}


def _late(r: _Read) -> dict:
    return {"accountId": r.aid, "read": r.name, "status": 504, "detail": {"upstream_status": "bundle_deadline"}}


def _deadline(started: float, deadline_ms: int) -> float:
    return started + min(max(deadline_ms, 0), DEADLINE_MAX_MS) / 1000


def _per_creator(ids: list[str], done: list[_Done], late: list[_Read], fields: tuple[str, ...]) -> list[dict]:
    by = {(d.read.aid, d.read.name): d for d in done}
    late_ids = {r.aid for r in late}
    out = []
    for aid in ids:
        row: dict[str, Any] = {"id": aid}
        ats = []
        for f in fields:
            d = by.get((aid, f))
            row[f] = d.value if d is not None and d.status is None else None
            if d is not None:
                ats.append(d.at)
        row["asOf"] = int(max(ats) * 1000) if ats else None
        row["stale"] = aid in late_ids
        out.append(row)
    return out


@router.get("/admin/screens/dashboard")
async def dashboard_screen(
    request: Request,
    response: Response,
    from_: str | None = Query(None, alias="from", max_length=40),
    to: str | None = Query(None, max_length=40),
    accounts: str | None = Query(None, max_length=4000),
    deadline_ms: int = Query(DEADLINE_MS, ge=0, le=DEADLINE_MAX_MS),
    focus: str | None = Query(None, max_length=40),  # the Creator the user has open: keeps the caller's priority
) -> dict[str, Any]:
    """The Dashboard's first paint in one call (module docstring)."""
    started = time.monotonic()
    response.headers["Cache-Control"] = "no-store"   # principal-specific, as /admin/accounts
    srv = relay_host.live_server()
    settings = await settings_api.get_applied(_inner_request(request, "/admin/settings/applied", {}, None))
    acc = await _accounts()
    ids, errors = _narrow(_dashboard_ids(acc), accounts)
    # A role hiding the Per-model KPIs card: the Dashboard draws no card, so nothing is read for it
    # (another page may still grant those routes; this screen shows nothing of them).
    card = PER_MODEL_CARD not in ((settings.get("permissions") or {}).get("denied_cards") or ())
    reads: list[_Read] = []
    if card and accounts is None:
        reads.append(_Read("perModel", None, "/admin/stats/per-model", {"from": from_, "to": to},
                           lambda: stats_per_model.per_model(from_=from_, to=to, account_id=None, engagement=False)))
    for aid in ids:
        reads.append(_Read("profile", aid, "/api/of/v2/users/me", {}, lambda: srv.users_me()))
        if card:
            reads.append(_Read("subscriberCounts", aid, "/api/of/v2/subscriptions/count/all", {},
                               lambda aid=aid: _cached("screen_sub_counts", aid, (),
                                                       srv.of_subscription_counts_all)))
            reads.append(_Read("newFans", aid, "/api/of/v2/subscriptions/subscribers/chart",
                               {"start": from_, "end": to},
                               lambda aid=aid: _cached("screen_subs_chart", aid, (from_, to, None),
                                                       lambda: srv.of_subscribers_chart(start=from_, end=to,
                                                                                        by=None))))
    done, late = await _run(request, reads, _deadline(started, deadline_ms))
    errors += [_error(d) for d in done if d.status is not None and d.read.aid is not None]
    errors += [_late(r) for r in late if r.aid is not None]
    pm = next((d for d in done if d.read.name == "perModel"), None)
    if pm is not None and pm.status is not None:
        errors.append(_error(pm))
    if any(r.name == "perModel" for r in late):
        errors.append(_late(next(r for r in late if r.name == "perModel")))
    fields = ("profile", "subscriberCounts", "newFans") if card else ("profile",)
    return {
        "settings": settings,
        "accounts": acc,
        "perModel": pm.value if pm is not None and pm.status is None else None,
        "creators": _per_creator(ids, done, late, fields),
        "errors": errors,
        "asOf": int(time.time() * 1000),
    }


@router.get("/admin/screens/inbox")
async def inbox_screen(
    request: Request,
    response: Response,
    cursor: int = Query(0, ge=0, le=100_000),
    accounts: str | None = Query(None, max_length=4000),
    deadline_ms: int = Query(DEADLINE_MS, ge=0, le=DEADLINE_MAX_MS),
    focus: str | None = Query(None, max_length=40),  # the Creator the user has open: keeps the caller's priority
) -> dict[str, Any]:
    """Messages Pro's All Models first paint in one call (module docstring). `cursor` is the
    unified list's offset, the same for every Creator (useChatList: allPages.length * 25)."""
    started = time.monotonic()
    response.headers["Cache-Control"] = "no-store"
    srv = relay_host.live_server()
    acc = await _accounts()
    ids, errors = _narrow(_inbox_ids(acc), accounts)
    chats_q = {"limit": CHATS_PAGE, "offset": cursor, "order": "recent"}
    reads: list[_Read] = []
    for aid in ids:
        reads.append(_Read("notificationCounts", aid, "/api/of/v2/users/notifications/count", {},
                           lambda: srv.of_notifications_count(refresh=False)))
        reads.append(_Read("chats", aid, "/api/of/v2/chats", chats_q,
                           lambda: srv.list_chats(limit=CHATS_PAGE, offset=cursor, order="recent", filter=None,
                                                  list_id=None, query=None, search=None, refresh=False)))
    done, late = await _run(request, reads, _deadline(started, deadline_ms))
    ok = {(d.read.aid, d.read.name): d.value for d in done if d.status is None}
    chats = {aid: ok[aid, "chats"] for aid in ids if (aid, "chats") in ok}
    return {
        "accounts": acc,
        "notificationCounts": {aid: ok[aid, "notificationCounts"] for aid in ids
                               if (aid, "notificationCounts") in ok},
        "chats": chats,
        # A Creator absent here has no page yet (late or failed: see errors), never "exhausted".
        "nextCursorByAccount": {aid: (cursor + CHATS_PAGE if (page or {}).get("hasMore") else None)
                                for aid, page in chats.items()},
        "stale": sorted({r.aid for r in late}),
        "errors": errors + [_error(d) for d in done if d.status is not None] + [_late(r) for r in late],
        "asOf": int(time.time() * 1000),
    }
