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
import platforms
import relay_cache
import relay_host
import settings_api
import side_effect_gate
import stats_per_model

log = logging.getLogger("of-relay.screens")
router = APIRouter()

DEADLINE_MS = 2000
DEADLINE_MAX_MS = 30000
BUNDLE_READS = 160
SHARE_S = 1.0
CACHE_TTL_S = 60.0
CHATS_PAGE = 25
PER_MODEL_CARD = "/#card-per-model"
STALE_READS = ("profile", "subscriberCounts", "newFans")
STALE_MAX_S = 30 * 60.0
STALE_ENTRIES = 4096
_SHARED: dict[tuple, asyncio.Future] = {}
_INFLIGHT: set[asyncio.Task] = set()
_LAST: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()


@dataclass
class Read:
    name: str
    aid: str | None
    path: str
    query: dict[str, Any]
    # Call the route function with every argument explicit: a FastAPI Query(...) default is a truthy FieldInfo when called directly.
    call: Callable[[], Awaitable[Any]]
    reuse: bool = False
    needs: tuple[str, str] | None = None


@dataclass
class _Done:
    read: Read
    value: Any = None
    status: int | None = None
    detail: Any = None
    refreshing: bool = False


_PASSED = object()


async def _passed(_request) -> object:
    return _PASSED


def _inner_request(outer: Request, path: str, query: dict[str, Any], aid: str | None,
                   focus: str | None) -> StarletteRequest:
    headers = [(b"x-account-id", aid.encode())] if aid else []
    pri = outer.headers.get("x-priority")
    if aid and aid != focus:
        pri = "background"
    if pri:
        headers.append((b"x-priority", pri.encode()))
    if caller := outer.headers.get("x-list-caller"):
        headers.append((b"x-list-caller", caller.encode()))
    q = {k: v for k, v in query.items() if v is not None}
    scope = {k: v for k, v in outer.scope.items() if k in ("app", "server", "client", "scheme", "root_path",
                                                             "http_version", "state")}
    scope.update(type="http", method="GET", path=path, raw_path=path.encode(),
                 query_string=urlencode(q).encode(), headers=headers)
    return StarletteRequest(scope)


async def _gate(inner: StarletteRequest) -> tuple[int, Any] | None:
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
            if read.needs and read.aid:
                side_effect_gate.refuse_if_platform_lacks(read.aid, *read.needs)
            last = _LAST.get(_read_key(read)) if read.reuse else None
            if last is not None and time.time() - last[0] <= STALE_MAX_S:
                _keep(asyncio.ensure_future(_shared(read, inner)))
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
    return (_principal(), read.name, read.aid, read.path, tuple(sorted((k, str(v)) for k, v in read.query.items())))


def _remember(key: tuple, value: Any) -> None:
    _LAST[key] = (time.time(), value)
    _LAST.move_to_end(key)
    while len(_LAST) > STALE_ENTRIES:
        _LAST.popitem(last=False)


async def _shared(read: Read, inner: StarletteRequest) -> Any:
    key = (*_read_key(read), inner.headers.get("x-priority"))
    task = _SHARED.get(key)
    if task is None:
        task = asyncio.ensure_future(read.call())
        _SHARED[key] = task

        def _forget(t: asyncio.Future, k: tuple = key) -> None:
            drop = lambda: _SHARED.pop(k, None) if _SHARED.get(k) is t else None  # noqa: E731
            if t.cancelled() or t.exception() is not None:
                drop()
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
            t.exception()
    task.add_done_callback(_drop)


async def _run(outer: Request, reads: list[Read], until: float,
               focus: str | None) -> tuple[list[_Done], list[Read]]:
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
    return await relay_cache.get_or_fetch(namespace, aid, key, CACHE_TTL_S, fn)


def _body(aid: str | None, name: str, value: Any) -> dict:
    return {"accountId": aid, "read": name, "body": value}


def _error(aid: str | None, name: str, status: int, detail: Any) -> dict:
    return {"accountId": aid, "read": name, "status": status, "detail": detail}


async def _accounts() -> tuple[Any, list[dict]]:
    if auth.get_request_user() is None and chatters.get_request_chatter() is not None:
        return jsonable_encoder(await chatters.me_accounts()), []
    acc = await accounts_admin_api.admin_accounts_list(Response())
    return acc, [_body(None, "accounts", acc)]


def _rows(accounts: Any) -> list[dict]:
    rows = accounts if isinstance(accounts, list) else (accounts or {}).get("accounts") or []
    out = []
    for a in rows:
        if a.get("role") == "watcher":
            continue
        out.append({**a, "id": a.get("id") or a.get("account_id"),
                    "has_session": a.get("has_session", True), "is_active": a.get("is_active", True)})
    return out


def _dashboard_ids(accounts: Any) -> list[str]:
    return [a["id"] for a in _rows(accounts)
            if not a.get("session_dead_at") and a["has_session"] and a["is_active"]]


def _inbox_ids(accounts: Any) -> list[str]:
    return [a["id"] for a in _rows(accounts)
            if a["has_session"] and a["is_active"] and platforms.get(a.get("platform")) is platforms.ONLYFANS]


def _narrow(ids: list[str], wanted: str | None) -> tuple[list[str], list[dict]]:
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
    return time.monotonic() + min(max(deadline_ms, 0), DEADLINE_MAX_MS) / 1000


async def run_screen(request: Request, response: Response, reads: list[Read], until: float, focus: str | None,
                     head: Sequence[dict] = ()) -> dict[str, Any]:
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
    focus: str | None = Query(None, max_length=40),
) -> dict[str, Any]:
    """The Dashboard's first paint in one call (module docstring)."""
    until = deadline_at(deadline_ms)
    srv = relay_host.live_server()
    settings = await settings_api.get_applied(_inner_request(request, "/admin/settings/applied", {}, None, focus))
    acc, head = await _accounts()
    ids, refused = _narrow(_dashboard_ids(acc), accounts)
    card = PER_MODEL_CARD not in ((settings.get("permissions") or {}).get("denied_cards") or ())
    reads: list[Read] = []
    if card and accounts is None:
        reads.append(Read("perModel", None, "/admin/stats/per-model", {"from": from_, "to": to},
                          lambda: stats_per_model.per_model(from_=from_, to=to, account_id=None, engagement=False)))
    reuse = accounts is None
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
                                                                                       by=None)), reuse,
                              needs=("subscribers_chart", "subscribers chart")))
    head = [_body(None, "settings", settings), *head, *refused]
    return await run_screen(request, response, reads, until, focus, head)


@router.get("/admin/screens/inbox")
async def inbox_screen(
    request: Request,
    response: Response,
    cursor: int = Query(0, ge=0, le=100_000),
    accounts: str | None = Query(None, max_length=4000),
    deadline_ms: int = Query(DEADLINE_MS, ge=0, le=DEADLINE_MAX_MS),
    focus: str | None = Query(None, max_length=40),
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
