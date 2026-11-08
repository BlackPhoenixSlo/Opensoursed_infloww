"""service/screens_api.py — one relay call per screen (the owner's "bundle them per screen").

A phone ~250 ms from the host paid one round trip per Creator per read: the Dashboard's cold
open was 57 relay calls in 3 dependent steps (Applied settings and the accounts list, then per
Creator `users/me`, `subscriptions/count/all`, `subscriptions/subscribers/chart`), Messages
Pro's All scope 2 per Creator (`users/notifications/count`, `/chats` page 0). These routes
answer a screen's whole first paint in one call:

  GET /admin/screens/dashboard?from=&to=&accounts=&deadline_ms=&focus=
  GET /admin/screens/inbox?cursor=&accounts=&deadline_ms=&focus=
      {answers: [{accountId, read, body, refreshing?} | {accountId, read, status, detail}], asOf}

One envelope for every screen (chat_screen_api.py's too): an answer per read, `read` the field the client
names (settings, accounts, perModel, profile, subscriberCounts, newFans, notificationCounts, chats),
`accountId` the X-Account-Id the per-Creator call would send (null for an unscoped read).

One source of truth: every value is the exact body its own route answers (`settings` =
GET /admin/settings/applied, `accounts` = GET /admin/accounts (an owner session only: a chatter's
list is /chatter/me/accounts, which the bundle never answers), `perModel` = GET /admin/stats/per-model, `profile` = GET
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
bundle; the real bounds are process-wide: single-flight per key, account lanes) and the bundle answers at
`deadline_ms` (default 2000) with what is done. A read still running answers a 504 `bundle_deadline`; it is
never cancelled (it may hold relay_cache's single-flight lock; finishing warms the cache the
client's background refresh then hits) and is kept referenced until done. A read still
queued at the deadline runs on too (reported late): no Creator is skipped on every cold load. The two reads with no server cache of their own
(subscriber counts, subscribers chart) are cached here, 60 s, single-flight (relay_cache: a background
read waits for its Creator's background lane before its thread), so 200 Dashboards cost OF one read per
Creator, not 200.

Serve-stale (the Dashboard's OF reads, `STALE_READS`): a read whose last value for this principal, Creator and query
is under STALE_MAX_S old answers with it at once, after its gate (never a value the gate would refuse now), and runs
behind the answer through the same path (`_shared`: single-flight, its priority, lanes, caches), its value the next
last one. Such an answer carries `refreshing: true`; the client's one
follow-up (`accounts=`, which never serves a last value) brings the new value. Bounded (STALE_ENTRIES, oldest out),
in memory only, keyed by the principal: never another session's.

An error answer: the status and detail the per-Creator route would have answered (403 role / not yours, 404, 409, 502 OF, 503 no session, 504). The client
maps an errored read to what its hook shows on a failed fetch today (profile and counts null,
the bell 0, the Creator's chats dropped) and keeps its own copy only on `bundle_deadline`. `accounts=`
naming a Creator outside the screen: `{accountId, read: "*", status: 404}`, nothing read.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence
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
SHARE_S = 1.0              # a finished read's result reused by identical reads (`_shared`)
CACHE_TTL_S = 60.0         # its two caches (counts, chart); the client keeps them 30 min
CHATS_PAGE = 25            # useChatList's PAGE_SIZE = the roster badge's window (_ROSTER_SCAN_MAX)
PER_MODEL_CARD = "/#card-per-model"
STALE_READS = ("profile", "subscriberCounts", "newFans")   # served from the last value, re-read behind (docstring)
STALE_MAX_S = 30 * 60.0    # the cards' own staleTime (hooks/useStats.ts): older is read before answering
STALE_ENTRIES = 4096       # last values kept, process-wide (13 Creators x 3 reads x ~100 principals)
_SHARED: dict[tuple, asyncio.Future] = {}   # identical reads in flight (`_shared`)
_INFLIGHT: set[asyncio.Task] = set()   # reads past their bundle's deadline, kept alive until done
_LAST: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()   # (`_read_key`) -> (epoch s, the read's last value)


@dataclass
class Read:
    name: str                 # the bundle field: profile, subscriberCounts, newFans, notificationCounts, chats
    aid: str | None           # the Creator (X-Account-Id); None for an All-scope read
    path: str                 # the per-Creator route it stands for
    query: dict[str, Any]
    call: Callable[[], Awaitable[Any]]
    reuse: bool = False       # may answer from its last value (STALE_READS, not a follow-up)


@dataclass
class _Done:
    read: Read
    value: Any = None
    status: int | None = None     # None = ok
    detail: Any = None
    refreshing: bool = False      # the last value, the read running behind it


_PASSED = object()


async def _passed(_request) -> object:
    return _PASSED


def _inner_request(outer: Request, path: str, query: dict[str, Any], aid: str | None,
                   focus: str | None) -> StarletteRequest:
    """A Request for the per-Creator route itself, as the browser would have sent it. Priority: the
    caller's for the Creator it has open (`focus`) and for unscoped reads; every other Creator's
    read is background (its lane's background cap: a tap on that Creator never waits behind the
    bundle, and no Creator but the open one reads as user-active to of_pacing / the vault collector)."""
    headers = [(b"x-account-id", aid.encode())] if aid else []
    pri = outer.headers.get("x-priority")
    if aid and aid != focus:
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


async def _serve(outer: Request, read: Read, sem: asyncio.Semaphore, focus: str | None) -> _Done:
    async with sem:
        srv = relay_host.live_server()
        inner = _inner_request(outer, read.path, read.query, read.aid, focus)
        token = srv._request_ctx.set(inner)
        try:
            refused = await _gate(inner)
            if refused is not None:
                return _Done(read, status=refused[0], detail=refused[1])
            last = _LAST.get(_read_key(read)) if read.reuse else None
            if last is not None and time.time() - last[0] <= STALE_MAX_S:
                _keep(asyncio.ensure_future(_shared(read, inner)))   # behind the answer, this Request's context
                return _Done(read, value=last[1], refreshing=True)
            return _Done(read, value=await _shared(read, inner))
        except HTTPException as e:
            return _Done(read, status=e.status_code, detail=e.detail)
        except Exception:  # noqa: BLE001  one Creator's bug must not sink the screen
            log.exception("screen read failed read=%s account=%s", read.name, read.aid)
            return _Done(read, status=500, detail="internal error")
        finally:
            srv._request_ctx.reset(token)


def _principal() -> tuple:
    u, c = auth.get_request_user(), chatters.get_request_chatter()
    return (u.id if u else None, c.id if c else None)


def _read_key(read: Read) -> tuple:
    return (_principal(), read.name, read.aid, tuple(sorted((k, str(v)) for k, v in read.query.items())))


def _remember(key: tuple, value: Any) -> None:
    _LAST[key] = (time.time(), value)
    _LAST.move_to_end(key)
    while len(_LAST) > STALE_ENTRIES:
        _LAST.popitem(last=False)


async def _shared(read: Read, inner: StarletteRequest) -> Any:
    """Identical reads run once per SHARE_S: same principal, read, Creator, query and priority
    (190 owner phones opening Messages Pro in the same second cost what one does: list_chats
    annotates its page with 3 DB reads per call, cache hit or not; Per-model stats aggregate the
    ledger). Each caller has passed its own gate first; a success is reused for SHARE_S after it
    finishes (on top of list_chats' own 10 min cache), an error never."""
    key = (*_read_key(read), inner.headers.get("x-priority"))
    task = _SHARED.get(key)
    if task is None:
        task = asyncio.ensure_future(read.call())   # copies this context: the inner Request in _request_ctx
        _SHARED[key] = task

        def _forget(t: asyncio.Future, k: tuple = key) -> None:
            drop = lambda: _SHARED.pop(k, None) if _SHARED.get(k) is t else None  # noqa: E731
            if t.cancelled() or t.exception() is not None:
                drop()                                   # an error is never served to the next caller
            else:
                if read.name in STALE_READS:
                    _remember(k[:-1], t.result())
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


async def _run(outer: Request, reads: list[Read], until: float,
               focus: str | None) -> tuple[list[_Done], list[Read]]:
    """Every read at once (BUNDLE_READS in flight); what is done by `until` (monotonic),
    and the reads not done then: running or still queued, all left to finish (referenced), so the
    next bundle finds every Creator warm, never the same tail skipped on each cold load."""
    if not reads:
        return [], []
    sem = asyncio.Semaphore(BUNDLE_READS)
    tasks = {asyncio.create_task(_serve(outer, r, sem, focus), name=f"screen-{r.name}-{r.aid}"): r
             for r in reads}
    done, pending = await asyncio.wait(tasks, timeout=max(0.0, until - time.monotonic()))
    for t in pending:
        _keep(t)
    return [t.result() for t in done], [tasks[t] for t in pending]


async def _cached(namespace: str, aid: str, key: tuple, fn: Callable[[], Any]) -> Any:
    """`fn` (a sync route function) through relay_cache: single-flight, CACHE_TTL_S, errors never
    cached; its thread taken after the Creator's background lane admits it (relay_coalesce.admission)."""
    return await relay_cache.get_or_fetch(namespace, aid, key, CACHE_TTL_S, fn)


def _body(aid: str | None, name: str, value: Any) -> dict:
    """A read's answer with its value (the route's body)."""
    return {"accountId": aid, "read": name, "body": value}


def _error(aid: str | None, name: str, status: int, detail: Any) -> dict:
    """A read's answer with its error (the route's status and detail)."""
    return {"accountId": aid, "read": name, "status": status, "detail": detail}


async def _accounts() -> tuple[Any, list[dict]]:
    """The principal's own accounts read, its exact body (useAccounts' two sources), and the answers it puts in the
    envelope: GET /admin/accounts' body as `accounts`; for a chatter-only session GET /chatter/me/accounts, no
    answer (its list is another route's)."""
    if auth.get_request_user() is None and chatters.get_request_chatter() is not None:
        return jsonable_encoder(await chatters.me_accounts()), []
    acc = await accounts_admin_api.admin_accounts_list(Response())
    return acc, [_body(None, "accounts", acc)]


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
    return keep, [_error(a, "*", 404, "not on this screen") for a in asked if a not in ids]


def _answer(d: _Done) -> dict:
    if d.status is not None:
        return _error(d.read.aid, d.read.name, d.status, d.detail)
    out = _body(d.read.aid, d.read.name, d.value)
    return {**out, "refreshing": True} if d.refreshing else out


def _late(r: Read) -> dict:
    return _error(r.aid, r.name, 504, {"upstream_status": "bundle_deadline"})


def deadline_at(deadline_ms: int) -> float:
    """The monotonic time a bundle asked now with `deadline_ms` answers at."""
    return time.monotonic() + min(max(deadline_ms, 0), DEADLINE_MAX_MS) / 1000


async def run_screen(request: Request, response: Response, reads: list[Read], until: float, focus: str | None,
                     head: Sequence[dict] = ()) -> dict[str, Any]:
    """`reads` at once (`_run`), as the screen envelope: `head` (the answers the handler read itself), then an
    answer per read in `reads`' order (a late one: 504 `bundle_deadline`). Principal-specific: no-store."""
    response.headers["Cache-Control"] = "no-store"
    done, late = await _run(request, reads, until, focus)
    by = {id(d.read): _answer(d) for d in done}
    by.update({id(r): _late(r) for r in late})
    return {"answers": [*head, *(by[id(r)] for r in reads)], "asOf": int(time.time() * 1000)}


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
    until = deadline_at(deadline_ms)
    srv = relay_host.live_server()
    settings = await settings_api.get_applied(_inner_request(request, "/admin/settings/applied", {}, None, focus))
    acc, head = await _accounts()
    ids, refused = _narrow(_dashboard_ids(acc), accounts)
    # A role hiding the Per-model KPIs card: the Dashboard draws no card, so nothing is read for it
    # (another page may still grant those routes; this screen shows nothing of them).
    card = PER_MODEL_CARD not in ((settings.get("permissions") or {}).get("denied_cards") or ())
    reads: list[Read] = []
    if card and accounts is None:
        reads.append(Read("perModel", None, "/admin/stats/per-model", {"from": from_, "to": to},
                          lambda: stats_per_model.per_model(from_=from_, to=to, account_id=None, engagement=False)))
    reuse = accounts is None   # a follow-up (`accounts=`) is the client's refresh: never a last value
    for aid in ids:
        reads.append(Read("profile", aid, "/api/of/v2/users/me", {}, lambda: srv.users_me(), reuse))
        if card:
            reads.append(Read("subscriberCounts", aid, "/api/of/v2/subscriptions/count/all", {},
                              lambda aid=aid: _cached("screen_sub_counts", aid, (),
                                                      srv.of_subscription_counts_all), reuse))
            reads.append(Read("newFans", aid, "/api/of/v2/subscriptions/subscribers/chart",
                              {"start": from_, "end": to},
                              lambda aid=aid: _cached("screen_subs_chart", aid, (from_, to, None),
                                                      lambda: srv.of_subscribers_chart(start=from_, end=to,
                                                                                       by=None)), reuse))
    head = [_body(None, "settings", settings), *head, *refused]
    return await run_screen(request, response, reads, until, focus, head)


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
    until = deadline_at(deadline_ms)
    srv = relay_host.live_server()
    acc, head = await _accounts()
    ids, refused = _narrow(_inbox_ids(acc), accounts)
    reads: list[Read] = []
    for aid in ids:
        reads.append(Read("notificationCounts", aid, "/api/of/v2/users/notifications/count", {},
                          lambda: srv.of_notifications_count(refresh=False)))
        reads.append(Read("chats", aid, "/api/of/v2/chats", {"limit": CHATS_PAGE, "offset": cursor, "order": "recent"},
                          lambda: srv.list_chats(limit=CHATS_PAGE, offset=cursor, order="recent", filter=None,
                                                 list_id=None, query=None, search=None, refresh=False)))
    return await run_screen(request, response, reads, until, focus, [*head, *refused])
