from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any, Callable
from urllib.parse import unquote, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

import account_health
import account_page
import agency_scope
import leak_tracker
import platforms
from agency_context import AgencyContext
from audit_log import credential_write
from auth import require_actor_account_ids
from chatters import current_actor
from db.engine import get_session
from db.models import Account, LeakWatch
from secrets_store import mask

router = APIRouter(prefix="/admin/leaks", tags=["leak-tracker"])

NOT_ACCEPTED = "Key not accepted"
OTHER_TENANT = "Key belongs to another tracker account"
UNREACHABLE = "The removal service is not reachable; nothing was saved"
WRITERS_ONLY = "Only the owner or an Admin can change Leak tracking"
CONSENT = "Consent is required to track this Creator"
HANDLE_TAKEN = "Another Creator in this agency already uses that handle"
ACCOUNT_TAKEN = "The removal service already tracks this Creator under another watch"
CREATOR_CAP = "The removal service's Creator limit is reached"
KEY_INVALID = {"error": "key_invalid", "message": "Key no longer valid"}
UNREADABLE = "The removal service gave an answer the CRM cannot read"
NOT_REACHABLE = "The removal service is not reachable"
PENDING = ("A Leak watch delete is still pending at the removal service and needs a valid key to finish. "
           "Replace the key instead of clearing it, or try again later")
WATCH_DELETED = "The removal service already deleted this watch; save again to track this Creator anew"

HANDLE = re.compile(r"[A-Za-z0-9_.-]{2,64}")
INSTAGRAM = re.compile(r"[A-Za-z0-9_.]{1,30}")
X_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
ALIASES_MAX = 5
ALIAS_MIN = 4
NAME_MAX = 64
# HANDLE through BANNED_ALIASES mirror the same limits in app/components/leaks/leakIdentityForm.ts.
BANNED_ALIASES = frozenset({
    *(p.key for p in platforms.ALL), "leak", "leaks", "leaked", "nude", "nudes", "naked", "free", "porn", "sexy", "model",
    "official", "babe", "baby", "video", "videos", "photo", "photos", "pics", "content", "premium", "vip",
})


def owns(path: str) -> bool:
    return path.startswith(router.prefix + "/")


def hidden() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@router.get("/setup")
async def get_setup(request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=False)
    agency = g.ctx.agency_user_id
    out = {"key": "missing", "masked": None, "is_owner": g.ctx.is_owner, "can_write": g.can_write, "brand": None}
    if not g.key:
        return out
    out["masked"] = mask(g.key) if g.ctx.is_owner else None
    if leak_tracker.key_invalid(agency):
        return {**out, "key": "invalid"}
    try:
        return {**out, "key": "set", "brand": (await leak_tracker.me(agency, g.key)).brand}
    except leak_tracker.KeyRefused:
        return {**out, "key": "invalid"}
    except leak_tracker.Unreachable:
        return {**out, "key": "set"}


@router.put("/key", dependencies=[Depends(credential_write)])
async def put_key(request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=False)
    if not g.ctx.is_owner:
        raise HTTPException(status_code=403, detail="Only the agency owner can connect the removal service")
    try:
        body = await request.json()
    except ValueError:
        body = None
    raw = body.get("key") if isinstance(body, dict) else None
    if not isinstance(raw, str) or len(raw) > 256:
        raise HTTPException(status_code=422, detail=NOT_ACCEPTED)
    agency = g.ctx.agency_user_id
    key = raw.strip()
    if not key:
        if await leak_tracker.pending(agency):
            raise HTTPException(status_code=409, detail=PENDING)
        await leak_tracker.store_key(agency, "")
        return {"key": "missing", "masked": None, "brand": None}
    if not leak_tracker.KEY_SHAPE.fullmatch(key):
        raise HTTPException(status_code=422, detail=NOT_ACCEPTED)
    try:
        me = await leak_tracker.me(None, key)
    except leak_tracker.KeyRefused:
        raise HTTPException(status_code=422, detail=NOT_ACCEPTED) from None
    except leak_tracker.Unreachable:
        raise HTTPException(status_code=503, detail=UNREACHABLE) from None
    if await leak_tracker.bind_tenant(agency, me.tenant_id) != me.tenant_id:
        raise HTTPException(status_code=422, detail=OTHER_TENANT)
    await leak_tracker.store_key(agency, key)
    return {"key": "set", "masked": mask(key), "brand": me.brand}


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not Found")


def _invalid(field: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"Invalid {field}")


async def _creators(ctx: AgencyContext) -> dict[str, str]:
    seen = require_actor_account_ids()
    async with get_session() as s:
        own = await agency_scope.agency_account_ids(s, ctx.agency_user_id)
        ids = own if seen is None else own & seen
        rows = (await s.execute(select(Account.id, Account.nickname).where(Account.id.in_(ids))
                                .order_by(Account.nickname, Account.id))).all()
    return {aid: nick or aid for aid, nick in rows}


async def _watch(agency: str, account_id: str) -> LeakWatch | None:
    async with get_session() as s:
        return await s.scalar(select(LeakWatch).where(LeakWatch.agency_user_id == agency,
                                                      LeakWatch.account_id == account_id))


async def _live(account_id: str, platform: str) -> dict[str, str] | None:
    if platform != "onlyfans":
        return None
    me = await account_page.of_me(account_id)
    username = me.get("username") if me else None
    if not isinstance(username, str) or not username:
        return None
    name = me.get("name")
    return {"username": username, "display_name": name[:NAME_MAX] if isinstance(name, str) else ""}


def _optional(value: Any, shape: re.Pattern[str], field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(field)
    value = value.strip()
    if value and not shape.fullmatch(value):
        raise _invalid(field)
    return value or None


def _alias_norm(alias: str) -> str:
    return re.sub(r"[_.\-]", "", unquote(alias).lower())


def _identity(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise _invalid("identity")
    username = body.get("username")
    if not isinstance(username, str) or not HANDLE.fullmatch(username.strip()):
        raise _invalid("username")
    username = username.strip().lower()
    display = body.get("display_name") or ""
    if not isinstance(display, str) or len(display.strip()) > NAME_MAX:
        raise _invalid("display_name")
    raw = body.get("aliases") or []
    if not isinstance(raw, list) or len(raw) > ALIASES_MAX:
        raise _invalid("aliases")
    taken, aliases = {_alias_norm(username)}, []
    for alias in raw:
        alias = alias.strip() if isinstance(alias, str) else ""
        norm = _alias_norm(alias)
        if not ALIAS_MIN <= len(alias) <= 64 or len(norm) < ALIAS_MIN or alias.lower() in BANNED_ALIASES or norm in taken:
            raise _invalid("aliases")
        taken.add(norm)
        aliases.append(alias)
    return {"username": username, "display_name": display.strip(), "aliases": aliases,
            "instagram": _optional(body.get("instagram"), INSTAGRAM, "instagram"),
            "x": _optional(body.get("x"), X_HANDLE, "x")}


def _identity_out(row: LeakWatch) -> dict[str, Any]:
    return {"platform": row.platform, "username": row.username, "verified": row.verified,
            "display_name": row.display_name, "aliases": json.loads(row.aliases_json or "[]"),
            "instagram": row.instagram, "x": row.x, "on": row.on}


def _refusal(r: Any) -> HTTPException | None:
    try:
        body = r.json()
    except ValueError:
        body = None
    body = body if isinstance(body, dict) else {}
    if r.status_code == 409 and body.get("error") == "account_taken":
        return HTTPException(status_code=409, detail=ACCOUNT_TAKEN)
    if r.status_code == 409 and body.get("error") == "creator_cap":
        cap = body.get("creators_max")
        return HTTPException(status_code=409, detail=f"{CREATOR_CAP} ({cap})" if isinstance(cap, int) else CREATOR_CAP)
    if r.status_code == 422:
        field = body.get("field")
        return HTTPException(status_code=422, detail=f"The removal service refused the {field}"
                             if isinstance(field, str) and field else "The removal service refused the identity")
    return None


async def _push(agency: str, key: str, watch_id: str, body: dict[str, Any]) -> bool:
    if leak_tracker.key_invalid(agency):
        return False
    try:
        r = await leak_tracker.call(agency, key, "PUT", f"/v1/watches/{watch_id}", json=body)
    except (leak_tracker.Unreachable, leak_tracker.KeyRefused):
        return False
    if r.status_code == 200:
        return True
    if leak_tracker.gone(r):
        raise leak_tracker.Gone()
    if refused := _refusal(r):
        raise refused
    return False


SERVICE_FIELDS = ("seeded", "paused", "paused_since", "last_checked_at", "next_check_at", "counts")
UNKNOWN = {"seeded": False, "paused": False, "paused_since": None, "last_checked_at": None, "next_check_at": None,
           "counts": None, "today": None}


COUNTS = ("live", "cached", "gone", "listed", "not_checked", "new_today", "found_on_first_scan", "came_back_30d")


def _shaped(c: dict[str, Any]) -> bool:
    counts = c.get("counts")
    return (isinstance(c.get("seeded"), bool) and isinstance(c.get("paused"), bool)
            and all(c.get(k) is None or isinstance(c.get(k), str)
                    for k in ("paused_since", "last_checked_at", "next_check_at"))
            and (counts is None or isinstance(counts, dict) and all(type(counts.get(k)) is int for k in COUNTS)))


DAY_STATES = frozenset({"pending", "complete", "partial", "coverage_reduced", "paused"})
DAY_COUNTS = ("new", "first_scan", "came_back", "gone")


def _today(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict) or not isinstance(x.get("day"), str) or x.get("state") not in DAY_STATES \
            or not all(type(x.get(k)) is int for k in DAY_COUNTS):
        return None
    return {"day": x["day"], "state": x["state"], **{k: x[k] for k in DAY_COUNTS}}


def _by_watch(body: Any) -> dict[str, dict[str, Any]]:
    creators = body.get("creators") if isinstance(body, dict) else None
    if not isinstance(creators, list):
        raise leak_tracker.ContractError()
    return {c["watch_id"]: c for c in creators
            if isinstance(c, dict) and isinstance(c.get("watch_id"), str) and _shaped(c)}


async def _read(g: leak_tracker.Gates, path: str, parse: Callable[[Any], Any], *,
                keep: bool = True) -> leak_tracker.Copy | None:
    try:
        return await leak_tracker.read(g.ctx.agency_user_id, g.key, path, parse, keep=keep)
    except leak_tracker.KeyRefused:
        raise HTTPException(status_code=409, detail=KEY_INVALID) from None
    except leak_tracker.ContractError:
        raise HTTPException(status_code=502, detail=UNREADABLE) from None


@router.get("/roster")
async def get_roster(request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    names = await _creators(g.ctx)
    async with get_session() as s:
        watches = {w.account_id: w for w in (await s.execute(select(LeakWatch).where(
            LeakWatch.agency_user_id == g.ctx.agency_user_id, LeakWatch.account_id.in_(names)))).scalars()}
    copy = await _read(g, "/v1/creators", _by_watch) if watches else None
    service = copy.body if copy else {}
    rows = []
    for aid, name in names.items():
        if (w := watches.get(aid)) is None:
            continue
        c = service.get(w.watch_id)
        rows.append({"account_id": aid, "name": name, "platform": w.platform, "username": w.username,
                     "display_name": w.display_name, "on": w.on, "synced": w.synced_at is not None,
                     "reachable": copy is not None,
                     **({**{k: c.get(k) for k in SERVICE_FIELDS}, "today": _today(c.get("today"))} if c else UNKNOWN)})
    untracked = [{"account_id": aid, "name": name} for aid, name in names.items() if aid not in watches]
    return {"rows": rows, "untracked": untracked, "stale": bool(copy and copy.stale),
            "fetched_at": copy.fetched_at if copy else None}


PAGE = 100
CURSOR_MAX = 512
PILLS = frozenset({"live", "cached", "gone", "listed", "not_checked"})
LEAK_TEXT = ("leak_id", "leak_site", "kind", "title", "first_seen_at")
LEAK_WHEN = ("last_up_at", "last_probe_at", "origin_status")
NO_LEAKS = {"leaks": [], "next_cursor": None, "stale": False, "fetched_at": None}
NO_DETAIL = {"lanes": None, "today": None}


def _cursor_ok(cursor: str | None) -> None:
    if cursor is not None and not 0 < len(cursor) <= CURSOR_MAX:
        raise _invalid("cursor")


def _query(watch_ids: list[str], cursor: str | None) -> str:
    return urlencode([*(("watch_id", w) for w in watch_ids), ("limit", PAGE), *((("cursor", cursor),) if cursor else ())])


def _event(e: Any) -> dict[str, Any] | None:
    if not isinstance(e, dict) or not isinstance(e.get("at"), str) or not isinstance(e.get("type"), str) \
            or not isinstance(e.get("data"), dict):
        return None
    return {"at": e["at"], "type": e["type"], "data": e["data"]}


def _leak(x: Any, extra: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(x, dict):
        return None
    url = x.get("url")
    if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https") \
            or not all(isinstance(x.get(k), str) for k in LEAK_TEXT + extra) \
            or not all(x.get(k) is None or isinstance(x.get(k), str) for k in LEAK_WHEN) \
            or x.get("pill") not in PILLS or not isinstance(x.get("came_back"), bool) \
            or not isinstance(x.get("found_on_first_scan"), bool):
        return None
    sources = x.get("sources")
    out = {k: x[k] for k in LEAK_TEXT + extra}
    out.update({k: x.get(k) for k in LEAK_WHEN})
    out.update(url=url, pill=x["pill"], came_back=x["came_back"], found_on_first_scan=x["found_on_first_scan"],
               sources=[s for s in sources if isinstance(s, str)] if isinstance(sources, list) else [])
    return out


def _page(body: Any, extra: tuple[str, ...], events: bool) -> dict[str, Any]:
    leaks = body.get("leaks") if isinstance(body, dict) else None
    cursor = body.get("next_cursor") if isinstance(body, dict) else None
    if not isinstance(leaks, list) or not (cursor is None or isinstance(cursor, str)):
        raise leak_tracker.ContractError()
    out = []
    for x in leaks:
        if (leak := _leak(x, extra)) is None:
            continue
        if events:
            raw = x.get("events")
            leak["events"] = [e for e in map(_event, raw) if e] if isinstance(raw, list) else []
        out.append(leak)
    return {"leaks": out, "next_cursor": cursor}


def _all_page(body: Any) -> dict[str, Any]:
    return _page(body, ("watch_id",), False)


def _drill_page(body: Any) -> dict[str, Any]:
    return _page(body, (), True)


LANES = ("origin_probe", "mega_lookup", "listing_recheck", "google_fresh", "google_full", "registry_crawl")
LANE_STATES = frozenset({"ok", "waiting", "reduced", "failed", "never", "paused"})
LANE_TEXT = ("reason", "last_success_at", "last_attempt_at", "next_attempt_on")


def _lane(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict) or x.get("lane") not in LANES or x.get("cadence") not in ("daily", "weekly") \
            or x.get("state") not in LANE_STATES or not all(x.get(k) is None or isinstance(x.get(k), str) for k in LANE_TEXT):
        return None
    trimmed = x.get("trimmed")
    return {"lane": x["lane"], "cadence": x["cadence"], "state": x["state"], **{k: x.get(k) for k in LANE_TEXT},
            "trimmed": [{"field": t["field"], "value": t["value"]} for t in trimmed
                        if isinstance(t, dict) and isinstance(t.get("field"), str) and isinstance(t.get("value"), str)]
            if isinstance(trimmed, list) else []}


def _detail_of(body: Any) -> dict[str, Any]:
    lanes = body.get("lanes") if isinstance(body, dict) else None
    if not isinstance(lanes, list):
        raise leak_tracker.ContractError()
    return {"lanes": [lane for lane in map(_lane, lanes) if lane], "today": _today(body.get("today"))}


async def _detail(g: leak_tracker.Gates, watch_id: str) -> leak_tracker.Copy | None:
    try:
        return await leak_tracker.read(g.ctx.agency_user_id, g.key, f"/v1/creators/{watch_id}", _detail_of)
    except leak_tracker.KeyRefused:
        raise HTTPException(status_code=409, detail=KEY_INVALID) from None
    except leak_tracker.ContractError:
        return None


async def _leaks(g: leak_tracker.Gates, path: str, parse: Callable[[Any], Any], cursor: str | None) -> dict[str, Any]:
    copy = await _read(g, path, parse, keep=cursor is None)
    if copy is not None:
        return {**copy.body, "stale": copy.stale, "fetched_at": copy.fetched_at}
    if cursor is not None:
        raise HTTPException(status_code=503, detail=NOT_REACHABLE)
    return {**NO_LEAKS, "leaks": None}


@router.get("/all")
async def get_all(request: Request, cursor: str | None = None) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    _cursor_ok(cursor)
    names = await _creators(g.ctx)
    async with get_session() as s:
        accounts = dict((await s.execute(select(LeakWatch.watch_id, LeakWatch.account_id).where(
            LeakWatch.agency_user_id == g.ctx.agency_user_id, LeakWatch.account_id.in_(names)))).all())
    if not accounts:
        return NO_LEAKS
    page = await _leaks(g, f"/v1/leaks?{_query(sorted(accounts), cursor)}", _all_page, cursor)
    if page["leaks"] is not None:
        page["leaks"] = [{**{k: v for k, v in x.items() if k != "watch_id"}, "account_id": accounts[x["watch_id"]]}
                         for x in page["leaks"] if x["watch_id"] in accounts]
    return page


@router.get("/watches/{account_id}")
async def get_watch(account_id: str, request: Request, cursor: str | None = None) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise _not_found()
    _cursor_ok(cursor)
    row = await _watch(g.ctx.agency_user_id, account_id)
    if row is not None:
        path = f"/v1/creators/{row.watch_id}/leaks?{_query([], cursor)}"
        page, detail = NO_LEAKS, None
        try:
            if row.synced_at is not None and cursor is None:
                page, detail = await asyncio.gather(_leaks(g, path, _drill_page, None), _detail(g, row.watch_id))
            elif row.synced_at is not None:
                page = await _leaks(g, path, _drill_page, cursor)
        except leak_tracker.Gone:
            await leak_tracker.forget_watch(g.ctx.agency_user_id, row.watch_id)
        else:
            return {"tracked": True, "identity": _identity_out(row), "suggested": None,
                    "synced": row.synced_at is not None, **(detail.body if detail else NO_DETAIL), **page,
                    "stale": page["stale"] or bool(detail and detail.stale)}
    live = await _live(account_id, platforms.for_account(account_id).key)
    suggested = {**live, "verified": True} if live else {"username": "", "display_name": "", "verified": False}
    return {"tracked": False, "identity": None, "suggested": suggested, "synced": False, **NO_DETAIL, **NO_LEAKS}


@router.put("/watches/{account_id}")
async def put_watch(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise _not_found()
    if not g.can_write:
        raise HTTPException(status_code=403, detail=WRITERS_ONLY)
    try:
        body = await request.json()
    except ValueError:
        body = None
    ident = _identity(body)
    agency = g.ctx.agency_user_id
    platform = platforms.for_account(account_id).key
    row = await _watch(agency, account_id)
    if row is None and body.get("consent") is not True:
        raise HTTPException(status_code=422, detail=CONSENT)
    async with get_session() as s:
        clash = await s.scalar(select(LeakWatch.id).where(
            LeakWatch.agency_user_id == agency, LeakWatch.platform == platform,
            LeakWatch.username == ident["username"], LeakWatch.account_id != account_id))
    if clash is not None:
        raise HTTPException(status_code=409, detail=HANDLE_TAKEN)
    kept = row is not None and row.verified and row.username == ident["username"]
    live = await _live(account_id, platform) if body.get("verified") is True and not kept else None
    verified = body.get("verified") is True and (kept or (live is not None and live["username"].lower() == ident["username"]))
    values = {"platform": platform, "username": ident["username"], "verified": verified,
              "display_name": ident["display_name"], "aliases_json": json.dumps(ident["aliases"]),
              "instagram": ident["instagram"], "x": ident["x"]}
    now = datetime.utcnow()
    if row is None:
        actor = current_actor()
        if actor is None:
            raise HTTPException(status_code=401, detail="sign in required")
        watch_id, on = str(uuid.uuid4()), True
        try:
            async with get_session() as s:
                s.add(LeakWatch(agency_user_id=agency, account_id=account_id, watch_id=watch_id, on=on,
                                consent_at=now, consent_by=f"{actor.kind}:{actor.id}:{actor.username}",
                                created_at=now, updated_at=now, **values))
        except IntegrityError:
            raise HTTPException(status_code=409, detail=HANDLE_TAKEN) from None
    else:
        watch_id, on = row.watch_id, row.on
    paused = leak_tracker.paused(on, True, await account_health.is_deactivated(account_id))
    push = leak_tracker.watch_body(account_id, paused, **values)
    try:
        pushed = await _push(agency, g.key, watch_id, push)
    except leak_tracker.Gone:
        await leak_tracker.forget_watch(agency, watch_id)
        raise HTTPException(status_code=409, detail=WATCH_DELETED) from None
    except HTTPException:
        if row is None:
            async with get_session() as s:
                await s.execute(delete(LeakWatch).where(LeakWatch.watch_id == watch_id))
        raise
    async with get_session() as s:
        live_row = await s.scalar(select(LeakWatch).where(LeakWatch.watch_id == watch_id))
        if live_row is not None:
            for k, v in values.items():
                setattr(live_row, k, v)
            live_row.updated_at = now
            live_row.synced_at = now if pushed else None
            live_row.synced_paused = paused if pushed else live_row.synced_paused
    return {"synced": pushed}


@router.post("/watches/{account_id}/tracking")
async def post_tracking(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise _not_found()
    if not g.can_write:
        raise HTTPException(status_code=403, detail=WRITERS_ONLY)
    try:
        body = await request.json()
    except ValueError:
        body = None
    on = body.get("on") if isinstance(body, dict) else None
    if not isinstance(on, bool):
        raise _invalid("on")
    async with get_session() as s:
        row = await s.scalar(select(LeakWatch).where(LeakWatch.agency_user_id == g.ctx.agency_user_id,
                                                     LeakWatch.account_id == account_id))
        if row is None:
            raise _not_found()
        row.on = on
        row.updated_at = datetime.utcnow()
    return {"on": on}


@router.delete("/watches/{account_id}")
async def delete_watch(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise _not_found()
    if not g.can_write:
        raise HTTPException(status_code=403, detail=WRITERS_ONLY)
    await leak_tracker.drop_watches(account_id=account_id, agency_user_id=g.ctx.agency_user_id)
    return {"tracked": False}
