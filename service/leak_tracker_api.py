from __future__ import annotations

import asyncio
import logging
import re
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import unquote, urlencode, urlsplit

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

import agency_scope
import leak_removal
import leak_tracker
import platforms
import relay_host
import runtime_switches
from agency_context import AgencyContext
from audit_log import credential_write
from auth import require_actor_account_ids
from chatters import current_actor
from db.engine import get_session
from db.models import Account, LeakWatch
from db.of_writer import snapshot_session
from leak_tracker import HANDLE, NAME_MAX
from secrets_store import mask

log = logging.getLogger("of-relay.leak_tracker_api")

NOT_ACCEPTED = "Key not accepted"
OTHER_TENANT = "Key belongs to another tracker account"
UNREACHABLE = "The removal service is not reachable; nothing was saved"
WRITERS_ONLY = "Only the owner or an Admin can change Leak tracking"
HANDLE_TAKEN = "Another Creator in this agency already uses that handle"
ACCOUNT_TAKEN = "The removal service already tracks this Creator under another watch"
CREATOR_CAP = "The removal service's Creator limit is reached"
WAITLIST = "The removal service is full right now; try again later"
ALREADY_TRACKED = "This Creator was just tracked by another save; reload to see it"
KEY_INVALID = {"error": "key_invalid", "message": "Key no longer valid"}
UNREADABLE = "The removal service gave an answer the CRM cannot read"
NOT_REACHABLE = "The removal service is not reachable"
PENDING = ("A Leak watch delete is still pending at the removal service and needs a valid key to finish. "
           "Replace the key instead of clearing it, or try again later")
WATCH_DELETED = "The removal service already deleted this watch; save again to track this Creator anew"
TRACKING_OFF = "Tracking is off for this Creator"
REFRESHED = "Refreshed recently"
TRY_SHORTLY = "Try again shortly"

INSTAGRAM = re.compile(r"[A-Za-z0-9_.]{1,30}")
X_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
ALIASES_MAX = 5
ALIAS_MIN = 4
CLOSED = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
# HANDLE, NAME_MAX (from leak_tracker) and INSTAGRAM through BANNED_ALIASES mirror the same limits in app/components/leaks/leakIdentityForm.ts.
BANNED_ALIASES = frozenset({
    *(p.key for p in platforms.ALL), "leak", "leaks", "leaked", "nude", "nudes", "naked", "free", "porn", "sexy", "model",
    "official", "babe", "baby", "video", "videos", "photo", "photos", "pics", "content", "premium", "vip",
})


async def _base_gate(request: Request) -> None:
    try:
        await leak_tracker.require_gates(request, need_key=False)
    except HTTPException as exc:
        exc.headers = dict(CLOSED)
        raise


router = APIRouter(prefix="/admin/leaks", tags=["leak-tracker"], dependencies=[Depends(_base_gate)])


def owns(path: str) -> bool:
    return path.startswith(router.prefix + "/")


def hidden() -> JSONResponse:
    return _closed(404)


@router.get("/setup")
async def get_setup(request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=False)
    agency = g.ctx.agency_user_id
    return {**await _setup_state(agency, g.key, g.instance, g.ctx.is_owner),
            "is_owner": g.ctx.is_owner, "can_write": g.can_write, "previews": previews_on()}


async def _setup_state(agency: str, key: str, instance: bool, is_owner: bool, *,
                       verified: leak_tracker.Me | None = None) -> dict[str, Any]:
    out = {"key": "missing", "masked": None, "brand": None, "source": None}
    if not key:
        return out
    out["source"] = "instance" if instance else "own"
    out["masked"] = mask(key) if is_owner and not instance else None
    if leak_tracker.key_invalid(agency):
        return {**out, "key": "invalid"}
    try:
        return {**out, "key": "set", "brand": (verified or await leak_tracker.me(agency, key)).brand}
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
        await leak_tracker.store_key(agency, "", pending_message=PENDING)
        stored, instance = await leak_tracker.agency_key(agency)
        return await _setup_state(agency, stored, instance, True)
    if key == leak_tracker.instance_key():
        raise HTTPException(status_code=400, detail=NOT_ACCEPTED)
    if not leak_tracker.KEY_SHAPE.fullmatch(key):
        raise HTTPException(status_code=422, detail=NOT_ACCEPTED)
    try:
        me = await leak_tracker.me(None, key)
    except leak_tracker.KeyRefused:
        raise HTTPException(status_code=422, detail=NOT_ACCEPTED) from None
    except leak_tracker.Unreachable:
        raise HTTPException(status_code=503, detail=UNREACHABLE) from None
    claim = await leak_tracker.claim_tenant(agency, me.tenant_id, key)
    if claim == "other_tenant":
        raise HTTPException(status_code=422, detail=OTHER_TENANT)
    return await _setup_state(agency, key, False, True, verified=me)


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


async def _agency_watches(agency: str, account_ids: dict[str, str], *, session: AsyncSession | None = None) -> list[LeakWatch]:
    async with (get_session() if session is None else nullcontext(session)) as s:
        return list((await s.scalars(select(LeakWatch).where(
            LeakWatch.agency_user_id == agency, LeakWatch.account_id.in_(account_ids)))).all())


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


REFUSAL_HTTP: dict[leak_tracker.RefusalKind, tuple[int, Any]] = {
    "not_found": (404, "Not Found"),
    "key_invalid": (409, KEY_INVALID),
    "creator_cap": (409, CREATOR_CAP),
    "waitlist": (409, WAITLIST),
    "identity": (422, "The removal service refused the identity"),
    "unbound": (503, UNREACHABLE),
    "handle_taken": (409, HANDLE_TAKEN),
    "account_taken": (409, ACCOUNT_TAKEN),
    "watch_deleted": (409, WATCH_DELETED),
    "watch_changed": (409, "Tracking changed while saving. Reload and try again."),
    "exists": (409, ALREADY_TRACKED),
    "watch_paused": (409, TRACKING_OFF),
}


def _http(e: leak_tracker.Refused) -> HTTPException:
    status, detail = REFUSAL_HTTP[e.kind]
    if e.kind == "creator_cap" and e.detail is not None:
        detail = f"{detail} ({e.detail})"
    if e.kind == "identity" and e.detail:
        detail = f"The removal service refused the {e.detail}"
    return HTTPException(status_code=status, detail=detail)


SERVICE_FIELDS = ("seeded", "paused", "paused_since", "last_checked_at", "next_check_at", "next_refresh_at", "counts")
UNKNOWN = {"seeded": False, "paused": False, "paused_since": None, "last_checked_at": None, "next_check_at": None,
           "next_refresh_at": None, "counts": None, "this_week": None}


COUNTS = ("live", "cached", "gone", "listed", "not_checked", "found_on_first_scan", "came_back_30d")


def _shaped(c: dict[str, Any]) -> bool:
    counts = c.get("counts")
    return (isinstance(c.get("seeded"), bool) and isinstance(c.get("paused"), bool)
            and all(c.get(k) is None or isinstance(c.get(k), str)
                    for k in ("paused_since", "last_checked_at", "next_check_at", "next_refresh_at"))
            and (counts is None or isinstance(counts, dict) and all(type(counts.get(k)) is int for k in COUNTS)))


DAY_STATES = frozenset({"pending", "complete", "partial", "coverage_reduced", "paused"})
DAY_COUNTS = ("new", "first_scan", "came_back", "gone")


def _this_week(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict) or not isinstance(x.get("since"), str) or not isinstance(x.get("state"), str) \
            or x["state"] not in DAY_STATES \
            or not all(type(x.get(k)) is int for k in DAY_COUNTS):
        return None
    return {"since": x["since"], "state": x["state"], **{k: x[k] for k in DAY_COUNTS}}


def _by_watch(body: Any) -> dict[str, dict[str, Any]]:
    creators = body.get("creators") if isinstance(body, dict) else None
    if not isinstance(creators, list) or any(
            not isinstance(c, dict) or not isinstance(c.get("watch_id"), str) or not _shaped(c) for c in creators):
        raise leak_tracker.ContractError()
    return {c["watch_id"]: c for c in creators}


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
    watches = {w.account_id: w for w in await _agency_watches(g.ctx.agency_user_id, names)}
    if not leak_tracker.key_invalid(g.ctx.agency_user_id) and leak_tracker.ensure_wanted(g.ctx.agency_user_id):
        relay_host.spawn_bg(leak_tracker.ensure_each([g.ctx.agency_user_id]), "leak-auto-track")
    copy = await _read(g, "/v1/creators", _by_watch) if watches else None
    service = copy.body if copy else {}
    rows = []
    for aid, name in names.items():
        if (w := watches.get(aid)) is None:
            continue
        c = service.get(w.watch_id)
        rows.append({"account_id": aid, "name": name, "platform": w.platform, "username": w.username,
                     "display_name": w.display_name, "on": w.on, "synced": leak_tracker.watch_synced(w),
                     "reachable": copy is not None,
                     **({**{k: c.get(k) for k in SERVICE_FIELDS}, "this_week": _this_week(c.get("this_week"))} if c else UNKNOWN)})
    untracked = [{"account_id": aid, "name": name} for aid, name in names.items() if aid not in watches]
    return {"rows": rows, "untracked": untracked, "stale": bool(copy and copy.stale),
            "fetched_at": copy.fetched_at if copy else None}


PAGE = 100
STRIP = 12
CURSOR_MAX = 512
PILLS = frozenset({"live", "cached", "gone", "listed", "not_checked"})
LEAK_TEXT = ("leak_id", "leak_site", "kind", "title", "first_seen_at")
LEAK_WHEN = ("last_up_at", "last_probe_at", "origin_status")
NO_LEAKS = {"leaks": [], "next_cursor": None, "stale": False, "fetched_at": None}
PENDING_LEAKS = {**NO_LEAKS, "leaks": None}
NO_DETAIL = {"lanes": None, "this_week": None, "next_refresh_at": None, "last_checked_at": None, "removal": None, "offer": None}


def _cursor_ok(cursor: str | None) -> None:
    if cursor is not None and not 0 < len(cursor) <= CURSOR_MAX:
        raise _invalid("cursor")


def _query(watch_ids: list[str], cursor: str | None, preview: bool = False, limit: int | None = None) -> str:
    return urlencode([*(("watch_id", w) for w in watch_ids), *((("preview_only", 1),) if preview else ()),
                      ("limit", limit or PAGE), *((("cursor", cursor),) if cursor else ())])


def _event(e: Any) -> dict[str, Any] | None:
    if not isinstance(e, dict) or not isinstance(e.get("at"), str) or not isinstance(e.get("type"), str) \
            or not isinstance(e.get("data"), dict):
        return None
    return {"at": e["at"], "type": e["type"], "data": e["data"]}


def _leak(x: Any, extra: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(x, dict):
        return None
    url = x.get("url")
    try:
        scheme = urlsplit(url).scheme if isinstance(url, str) else None
    except ValueError:
        return None
    if scheme not in ("http", "https") \
            or not all(isinstance(x.get(k), str) for k in LEAK_TEXT + extra) \
            or not all(x.get(k) is None or isinstance(x.get(k), str) for k in LEAK_WHEN) \
            or not isinstance(x.get("pill"), str) or x["pill"] not in PILLS or not isinstance(x.get("came_back"), bool) \
            or not isinstance(x.get("found_on_first_scan"), bool):
        return None
    sources = x.get("sources")
    out = {k: x[k] for k in LEAK_TEXT + extra}
    out.update({k: x.get(k) for k in LEAK_WHEN})
    out.update(url=url, pill=x["pill"], came_back=x["came_back"], found_on_first_scan=x["found_on_first_scan"],
               sources=[s for s in sources if isinstance(s, str)] if isinstance(sources, list) else [])
    return out


def previews_on() -> bool:
    return runtime_switches.on("LEAK_TRACKER_PREVIEWS")


VERTICALS = frozenset({"images", "videos"})


def _preview(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict) or x.get("vertical") not in VERTICALS or not isinstance(x.get("seen_at"), str):
        return None
    return {"vertical": x["vertical"], "seen_at": x["seen_at"]}


def _shown(page: dict[str, Any]) -> dict[str, Any]:
    if page["leaks"] is None or previews_on():
        return page
    return {**page, "leaks": [{**x, "preview": None} for x in page["leaks"]]}


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
        leak["preview"] = _preview(x.get("preview"))
        out.append(leak)
    if leaks and not out:
        raise leak_tracker.ContractError()
    return {"leaks": out, "next_cursor": cursor}


def _all_page(body: Any) -> dict[str, Any]:
    return _page(body, ("watch_id",), False)


def _drill_page(body: Any) -> dict[str, Any]:
    return _page(body, (), True)


LANES = ("origin_probe", "mega_lookup", "listing_recheck", "google_full", "registry_crawl")
LANE_STATES = frozenset({"ok", "waiting", "reduced", "failed", "never", "paused"})
LANE_TEXT = ("reason", "last_success_at", "last_attempt_at", "next_attempt_on")


def _lane(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict) or x.get("lane") not in LANES or x.get("cadence") not in ("daily", "weekly") \
            or not isinstance(x.get("state"), str) or x["state"] not in LANE_STATES \
            or not all(x.get(k) is None or isinstance(x.get(k), str) for k in LANE_TEXT):
        return None
    trimmed = x.get("trimmed")
    return {"lane": x["lane"], "cadence": x["cadence"], "state": x["state"], **{k: x.get(k) for k in LANE_TEXT},
            "trimmed": [{"field": t["field"], "value": t["value"]} for t in trimmed
                        if isinstance(t, dict) and isinstance(t.get("field"), str) and isinstance(t.get("value"), str)]
            if isinstance(trimmed, list) else []}


def _ints(x: Any, keys: tuple[str, ...]) -> dict[str, int] | None:
    if not isinstance(x, dict) or not all(type(x.get(k)) is int for k in keys):
        return None
    return {k: x[k] for k in keys}


def _text(x: Any) -> str | None:
    return x if isinstance(x, str) else None


def _detail_of(body: Any) -> dict[str, Any]:
    lanes = body.get("lanes") if isinstance(body, dict) else None
    if not isinstance(lanes, list):
        raise leak_tracker.ContractError()
    return {"lanes": [lane for lane in map(_lane, lanes) if lane], "this_week": _this_week(body.get("this_week")),
            "next_refresh_at": _text(body.get("next_refresh_at")),
            "service_status": _text(body.get("service_status")),
            "removal": _ints(body.get("removal"), leak_removal.TRACK_COUNTS),
            "offer_counts": _ints(body.get("offer_counts"), leak_removal.OFFER_COUNTS),
            "first_daily_at": _text(body.get("first_daily_at")), "last_checked_at": _text(body.get("last_checked_at")),
            "preview_leak": _preview_leak(body.get("preview_leak"))}


def _preview_leak(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict) or not all(isinstance(x.get(k), str) for k in LEAK_TEXT) or x.get("pill") not in PILLS:
        return None
    return {**{k: x[k] for k in LEAK_TEXT}, "pill": x["pill"], "preview": None}


def _me_of(body: Any) -> dict[str, str | None]:
    if not isinstance(body, dict):
        raise leak_tracker.ContractError()
    return {k: _text(body.get(k)) for k in ("brand", "contact_url", "notices_updated_at")}


def _popup_me(body: Any) -> dict[str, Any]:
    return {**_me_of(body), "video": leak_removal.video_of(body.get("video"))}


async def _read_or_none(g: leak_tracker.Gates, path: str, parse: Callable[[Any], Any]) -> leak_tracker.Copy | None:
    try:
        return await leak_tracker.read(g.ctx.agency_user_id, g.key, path, parse)
    except leak_tracker.KeyRefused:
        raise HTTPException(status_code=409, detail=KEY_INVALID) from None
    except leak_tracker.ContractError:
        return None


def _removal(g: leak_tracker.Gates, row: LeakWatch, detail: dict[str, Any], me: dict[str, Any], *,
             detail_stale: bool) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    area = leak_removal.removal_view(detail.get("service_status"), me.get("notices_updated_at"), now)
    area["stale"] = area["stale"] or detail_stale
    counts = detail.get("removal") if area["view"] in leak_removal.TRACK_VIEWS and not area["stale"] else None
    snoozed = row.offer_snoozed_until is not None and row.offer_snoozed_until > now.replace(tzinfo=None)
    offer = leak_removal.removal_offer(area["view"], owner_or_admin=g.offer_viewer, first_daily_at=detail.get("first_daily_at"),
                                       snoozed=snoozed, brand=me.get("brand"), contact_url=me.get("contact_url"),
                                       counts=detail.get("offer_counts"))
    until = row.offer_snoozed_until.isoformat() + "Z" if snoozed and g.offer_viewer else None
    return {"removal": {**area, "notices_updated_at": me.get("notices_updated_at"), "counts": counts,
                        "offer_snoozed_until": until}, "offer": offer}


async def _leaks(g: leak_tracker.Gates, path: str, parse: Callable[[Any], Any], cursor: str | None) -> dict[str, Any]:
    copy = await _read(g, path, parse, keep=cursor is None)
    if copy is not None:
        return {**copy.body, "stale": copy.stale, "fetched_at": copy.fetched_at}
    if cursor is not None:
        raise HTTPException(status_code=503, detail=NOT_REACHABLE)
    return PENDING_LEAKS


@router.get("/all")
async def get_all(request: Request, cursor: str | None = None, preview: bool = False) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if preview and not previews_on():
        raise leak_tracker.not_found()
    if preview and cursor is not None:
        raise _invalid("cursor")
    _cursor_ok(cursor)
    names = await _creators(g.ctx)
    agency = g.ctx.agency_user_id
    async with snapshot_session() as s:
        watches = await _agency_watches(agency, names, session=s)
        accounts = {w.watch_id: w.account_id for w in watches if w.synced_at is not None}
        if not accounts:
            return PENDING_LEAKS if watches else NO_LEAKS
        if (credential := await leak_tracker.verified_key(agency, session=s)) is None or credential[0] != g.key:
            raise HTTPException(status_code=503, detail="Reconnect the removal service to read these Leaks")
    if preview:
        page = {**await _leaks(g, f"/v1/leaks?{_query(sorted(accounts), None, preview=True, limit=STRIP)}", _all_page, None), "next_cursor": None}
    else:
        page = await _leaks(g, f"/v1/leaks?{_query(sorted(accounts), cursor)}", _all_page, cursor)
    if page["leaks"] is not None:
        page["leaks"] = [{**{k: v for k, v in x.items() if k != "watch_id"}, "account_id": accounts[x["watch_id"]]}
                         for x in page["leaks"] if x["watch_id"] in accounts]
    return _shown(page)


@router.get("/watches/{account_id}")
async def get_watch(account_id: str, request: Request, cursor: str | None = None,
                    preview: bool = False) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx) or (preview and not previews_on()):
        raise leak_tracker.not_found()
    _cursor_ok(cursor)
    row = await leak_tracker.watch(g.ctx.agency_user_id, account_id)
    if row is not None:
        path = f"/v1/leaks?{_query([row.watch_id], cursor, preview=True)}" if preview \
            else f"/v1/creators/{row.watch_id}/leaks?{_query([], cursor)}"
        page, detail, me, extra = PENDING_LEAKS, None, None, NO_DETAIL
        try:
            if row.synced_at is not None and cursor is None and not preview:
                page, detail, me = await asyncio.gather(_leaks(g, path, _drill_page, None),
                                                        _read_or_none(g, f"/v1/creators/{row.watch_id}", _detail_of),
                                                        _read_or_none(g, "/v1/me", _me_of))
                d = detail.body if detail else {}
                extra = {"lanes": d.get("lanes"), "this_week": d.get("this_week"), "next_refresh_at": d.get("next_refresh_at"),
                         "last_checked_at": d.get("last_checked_at"),
                         **_removal(g, row, d, me.body if me else {}, detail_stale=bool(detail and detail.stale))}
            elif row.synced_at is not None:
                page = await _leaks(g, path, _drill_page, cursor)
        except leak_tracker.Gone:
            await leak_tracker.forget_watch(g.ctx.agency_user_id, row.watch_id)
        else:
            return {"tracked": True, "identity": leak_tracker.identity_out(row), "suggested": None,
                    "synced": leak_tracker.watch_synced(row), **extra, **_shown(page),
                    "stale": page["stale"] or bool(detail and detail.stale)}
    live = await leak_tracker.live(account_id, platforms.for_account(account_id).key)
    suggested = {**live, "verified": True} if live else {"username": "", "display_name": "", "verified": False}
    return {"tracked": False, "identity": None, "suggested": suggested, "synced": False, **NO_DETAIL, **NO_LEAKS}


@router.get("/watches/{account_id}/offer")
async def get_offer(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if not g.offer_viewer or account_id not in await _creators(g.ctx):
        raise leak_tracker.not_found()
    row = await leak_tracker.watch(g.ctx.agency_user_id, account_id)
    if row is None or row.synced_at is None:
        raise leak_tracker.not_found()
    try:
        detail, me, page = await asyncio.gather(
            _read(g, f"/v1/creators/{row.watch_id}", _detail_of, keep=False),
            _read(g, "/v1/me", _popup_me, keep=False),
            _read(g, f"/v1/creators/{row.watch_id}/leaks?{_query([], None)}", _drill_page, keep=False))
    except leak_tracker.Gone:
        await leak_tracker.forget_watch(g.ctx.agency_user_id, row.watch_id)
        raise leak_tracker.not_found() from None
    if detail is None or me is None or page is None:
        raise HTTPException(status_code=503, detail=NOT_REACHABLE)
    offer = _removal(g, row, detail.body, me.body, detail_stale=detail.stale)["offer"]
    if offer is None:
        raise leak_tracker.not_found()
    return {"offer": offer, "preview_leak": detail.body["preview_leak"], "video": me.body["video"],
            "scenes": leak_removal.overlay_scenes(page.body["leaks"]), "last_checked_at": detail.body["last_checked_at"]}


STREAMS_MAX = 3
STREAM_FOR_S = 300
CHUNK = 64 * 1024
PASSED = ("content-range", "accept-ranges", "content-length")
_streams: dict[str, int] = {}


class _StreamLease:
    def __init__(self, agency: str | None, counts: dict[str, int]) -> None:
        self.agency = agency
        self.counts = counts
        self.client: httpx.AsyncClient | None = None
        self.upstream: httpx.Response | None = None
        if agency is not None:
            counts[agency] = counts.get(agency, 0) + 1

    async def aclose(self) -> None:
        agency, self.agency = self.agency, None
        client, self.client = self.client, None
        upstream, self.upstream = self.upstream, None
        if agency is not None:
            if self.counts[agency] == 1:
                del self.counts[agency]
            else:
                self.counts[agency] -= 1
        with anyio.CancelScope(shield=True):
            try:
                if upstream is not None:
                    await upstream.aclose()
            finally:
                if client is not None:
                    await client.aclose()


class _HeldStream(StreamingResponse):
    def __init__(self, lease: _StreamLease, upstream: httpx.Response, cap: int, ctype: str,
                 passed: tuple[str, ...], for_s: float) -> None:
        self._lease = lease
        self._for_s = for_s

        async def body():
            sent = 0
            async for chunk in upstream.aiter_bytes(CHUNK):
                sent += len(chunk)
                if sent > cap:
                    break
                yield chunk

        kept = {k: v for k in passed if (v := upstream.headers.get(k))}
        super().__init__(body(), status_code=upstream.status_code, media_type=ctype, headers={**kept, **CLOSED})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            with anyio.move_on_after(self._for_s):
                await super().__call__(scope, receive, send)
        finally:
            await self._lease.aclose()


def _closed(status: int, headers: dict[str, str] | None = None) -> Response:
    return JSONResponse(status_code=status, content={"detail": HTTPStatus(status).phrase},
                        headers={**CLOSED, **(headers or {})})


def _type_and_size(upstream: httpx.Response, cap: int) -> tuple[str, bool]:
    size = upstream.headers.get("content-length")
    return ((upstream.headers.get("content-type") or "").split(";")[0].strip().lower(),
            size is None or (size.isdigit() and int(size) <= cap))


@router.get("/offer-video/{part}")
async def get_offer_video(part: str, request: Request) -> Response:
    try:
        g = await leak_tracker.require_gates(request, need_key=True)
    except HTTPException as e:
        return _closed(e.status_code)
    agency = g.ctx.agency_user_id
    if part not in leak_removal.VIDEO_PARTS or not g.offer_viewer or leak_tracker.key_invalid(agency):
        return _closed(404)
    ctype, cap = leak_removal.VIDEO_PARTS[part]
    try:
        byte_range = leak_removal.one_range(request.headers.getlist("range")) if part == "video" else None
    except ValueError:
        return _closed(416)
    if part == "video" and _streams.get(agency, 0) >= STREAMS_MAX:
        return _closed(429)
    lease = _StreamLease(agency if part == "video" else None, _streams)
    response = None
    try:
        try:
            lease.client, upstream = await leak_tracker.open_stream(agency, g.key, f"/v1/offer-video/{part}", byte_range)
            lease.upstream = upstream
        except leak_tracker.KeyRefused:
            return _closed(404)
        except leak_tracker.Unreachable:
            return _closed(503)
        got, size_ok = _type_and_size(upstream, cap)
        if upstream.status_code == 416:
            rng = upstream.headers.get("content-range")
            return _closed(416, {"Content-Range": rng} if rng else None)
        if upstream.status_code not in (200, 206) or got != ctype or not size_ok:
            return _closed(404)
        response = _HeldStream(lease, upstream, cap, ctype, PASSED, STREAM_FOR_S)
        return response
    finally:
        if response is None:
            await lease.aclose()


THUMB_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
THUMB_MAX = 3 * 1024 * 1024
THUMB_FOR_S = 30
THUMBS_MAX = 6
LEAK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_thumbs: dict[str, int] = {}


@router.get("/watches/{account_id}/leaks/{leak_id}/thumb")
async def get_thumb(account_id: str, leak_id: str, request: Request) -> Response:
    try:
        g = await leak_tracker.require_gates(request, need_key=True)
    except HTTPException:
        return _closed(404)
    agency = g.ctx.agency_user_id
    if not previews_on() or leak_tracker.key_invalid(agency) or not LEAK_ID.fullmatch(leak_id) \
            or account_id not in await _creators(g.ctx):
        return _closed(404)
    row = await leak_tracker.watch(agency, account_id)
    if row is None or row.synced_at is None:
        return _closed(404)
    if _thumbs.get(agency, 0) >= THUMBS_MAX:
        return _closed(429)
    lease = _StreamLease(agency, _thumbs)
    response = None
    try:
        try:
            lease.client, upstream = await leak_tracker.open_stream(
                agency, g.key, f"/v1/creators/{row.watch_id}/leaks/{leak_id}/thumb", None)
            lease.upstream = upstream
        except (leak_tracker.KeyRefused, leak_tracker.Unreachable) as e:
            log.info("leak thumb refused: %s", "key" if isinstance(e, leak_tracker.KeyRefused) else "unreachable")
            return _closed(404)
        status = upstream.status_code
        ctype, size_ok = _type_and_size(upstream, THUMB_MAX)
        if status == 410:
            try:
                await upstream.aread()
            except httpx.HTTPError:
                log.info("leak thumb refused: 410 body unreadable")
                return _closed(404)
            if leak_tracker.gone(upstream):
                await leak_tracker.forget_watch(agency, row.watch_id)
                log.info("leak thumb refused: watch gone")
                return _closed(404)
        if status != 200 or ctype not in THUMB_TYPES or not size_ok:
            log.info("leak thumb refused: %s", status if status != 200 else "type or size")
            return _closed(429 if status == 429 else 404)
        response = _HeldStream(lease, upstream, THUMB_MAX, ctype, ("content-length",), THUMB_FOR_S)
        return response
    finally:
        if response is None:
            await lease.aclose()


@router.put("/watches/{account_id}")
async def put_watch(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise leak_tracker.not_found()
    if not g.can_write:
        raise HTTPException(status_code=403, detail=WRITERS_ONLY)
    try:
        body = await request.json()
    except ValueError:
        body = None
    ident = _identity(body)
    actor = current_actor()
    if actor is None:
        raise HTTPException(status_code=401, detail="sign in required")
    agency = g.ctx.agency_user_id
    try:
        synced = await leak_tracker.save_watch(agency, g.key, account_id, ident, verified=body.get("verified") is True,
                                               consent_by=f"{actor.kind}:{actor.id}:{actor.username}")
    except leak_tracker.Refused as e:
        raise _http(e) from None
    return {"synced": synced}


@router.post("/watches/{account_id}/tracking")
async def post_tracking(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise leak_tracker.not_found()
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
            raise leak_tracker.not_found()
        row.on = on
        row.updated_at = datetime.utcnow()
    return {"on": on}


@router.post("/watches/{account_id}/refresh")
async def post_refresh(account_id: str, request: Request) -> Any:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise leak_tracker.not_found()
    if not g.can_write:
        raise HTTPException(status_code=403, detail=WRITERS_ONLY)
    agency = g.ctx.agency_user_id
    row = await leak_tracker.watch(agency, account_id)
    if row is None:
        raise leak_tracker.not_found()
    if not row.on:
        raise HTTPException(status_code=409, detail=TRACKING_OFF)
    try:
        queued = await leak_tracker.refresh(agency, g.key, row.watch_id)
    except leak_tracker.Gone:
        await leak_tracker.forget_watch(agency, row.watch_id)
        raise leak_tracker.not_found() from None
    except leak_tracker.Unreachable:
        raise HTTPException(status_code=503, detail=NOT_REACHABLE) from None
    except leak_tracker.ContractError:
        raise HTTPException(status_code=502, detail=UNREADABLE) from None
    except leak_tracker.Cooldown as c:
        next_refresh_at = c.next_refresh_at
        if next_refresh_at is None and c.retry_after_s is not None:
            next_refresh_at = (datetime.now(timezone.utc) + timedelta(seconds=min(c.retry_after_s, 2**31))).isoformat()
        return JSONResponse(status_code=429,
                            headers={"Retry-After": str(c.retry_after_s)} if c.retry_after_s is not None else None,
                            content={"detail": REFRESHED if c.next_refresh_at else TRY_SHORTLY,
                                     "kind": "refresh_cooldown" if c.next_refresh_at else "rate_limited",
                                     "next_refresh_at": next_refresh_at})
    except leak_tracker.Refused as e:
        raise _http(e) from None
    leak_tracker.drop_copies(agency)
    return queued


@router.post("/watches/{account_id}/offer-snooze")
async def post_offer_snooze(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise leak_tracker.not_found()
    if not g.offer_viewer:
        raise HTTPException(status_code=403, detail="Only the owner or an Admin can hide the Removal offer")
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("snoozed") is not True:
        raise _invalid("snoozed")
    until = datetime.utcnow().replace(microsecond=0) + leak_removal.SNOOZE_FOR
    async with get_session() as s:
        row = await s.scalar(select(LeakWatch).where(LeakWatch.agency_user_id == g.ctx.agency_user_id,
                                                     LeakWatch.account_id == account_id))
        if row is None:
            raise leak_tracker.not_found()
        row.offer_snoozed_until = until
    return {"offer_snoozed_until": until.isoformat() + "Z"}


@router.delete("/watches/{account_id}")
async def delete_watch(account_id: str, request: Request) -> dict[str, Any]:
    g = await leak_tracker.require_gates(request, need_key=True)
    if account_id not in await _creators(g.ctx):
        raise leak_tracker.not_found()
    if not g.can_write:
        raise HTTPException(status_code=403, detail=WRITERS_ONLY)
    agency = g.ctx.agency_user_id
    await leak_tracker.untrack(agency, account_id)
    return {"tracked": False}
