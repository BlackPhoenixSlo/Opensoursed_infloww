from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from agency_scope import agency_account_ids
from auth import get_request_user
from automation_executor import enqueue_job
from db.engine import get_session
from db.models import Action, S4SBlock, S4SPost, S4SProfile, S4SRequest, S4SSlot, UserAccount
from db.of_writer import immediate_session
from route_wire import parse_utc, wire as _wire
from s4s_common import (OPEN, VERBS, Refuse, _json_object, _owner_context, daily_full, next_status,
                        partner_refusal, request_refusal)
from s4s_media import snapshot


router = APIRouter(prefix="/admin/s4s", tags=["s4s"])

_SEND_FIELDS = ("from_account_id", "to_profile_id", "slot_at")


_own_ids = agency_account_ids


def _audit(s, action: str, account_id: str, request_id: int, payload: dict[str, Any],
           employee_id: int | None = None) -> None:
    s.add(Action(
        employee_id=employee_id,
        account_id=account_id,
        action=action,
        target_type="s4s_request",
        target_id=str(request_id),
        payload_json=json.dumps({**payload, "request_id": request_id}),
        at=datetime.utcnow(),
    ))




async def expire_callers_requests() -> None:
    user = get_request_user()
    if user is None:
        return
    async with get_session() as s:
        ids = await _own_ids(s, user.id)
        if ids:
            await _expire_due(s, ids, datetime.utcnow())


async def _expire_due(s, account_ids: set[str], now: datetime) -> None:
    due = (await s.execute(
        select(S4SRequest.id, S4SRequest.from_account_id).where(
            S4SRequest.status.in_(OPEN), S4SRequest.slot_at <= now,
            or_(S4SRequest.from_account_id.in_(account_ids), S4SRequest.to_account_id.in_(account_ids)),
        )
    )).all()
    for request_id, from_account_id in due:
        done = await s.execute(
            update(S4SRequest)
            .where(S4SRequest.id == request_id, S4SRequest.status.in_(OPEN), S4SRequest.slot_at <= now)
            .values(status="expired")
            .execution_options(synchronize_session=False)
        )
        if done.rowcount == 1:
            _audit(s, "s4s.request_expire", from_account_id, request_id, {"actor": "system"})




def _parse_send(body: dict[str, Any]) -> tuple[str, int, datetime]:
    unknown = set(body) - set(_SEND_FIELDS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown field(s): {', '.join(sorted(unknown))}")
    from_id = body.get("from_account_id")
    if not isinstance(from_id, str) or not from_id:
        raise HTTPException(status_code=400, detail="from_account_id: one of your Creators is required")
    to_pid = body.get("to_profile_id")
    if isinstance(to_pid, bool) or not isinstance(to_pid, int):
        raise HTTPException(status_code=400, detail="to_profile_id: the partner's S4S profile id is required")
    return from_id, to_pid, parse_utc(body.get("slot_at"), "slot_at", status=400)


async def _primary_caption(s, account_id: str) -> str | None:
    return (await s.execute(
        select(S4SPost.caption).where(S4SPost.account_id == account_id, S4SPost.is_primary.is_(True))
    )).scalar_one_or_none()


async def _linked(s, ids) -> set[str]:
    return set((await s.execute(
        select(UserAccount.account_id).where(UserAccount.account_id.in_(ids))
    )).scalars().all())


async def _in_agency(s, account_id: str) -> bool:
    return account_id in await _linked(s, {account_id})


async def blocked_between(s, a: str, b: str) -> bool:
    owners_a = select(UserAccount.user_id).where(UserAccount.account_id == a)
    owners_b = select(UserAccount.user_id).where(UserAccount.account_id == b)
    hit = (await s.execute(
        select(S4SBlock.id).where(or_(
            and_(S4SBlock.account_id == b, S4SBlock.agency_user_id.in_(owners_a)),
            and_(S4SBlock.account_id == a, S4SBlock.agency_user_id.in_(owners_b)),
        )).limit(1)
    )).first()
    return hit is not None


async def _sent_today(s, account_id: str, now: datetime) -> int:
    start = datetime(now.year, now.month, now.day)
    return (await s.execute(
        select(func.count()).select_from(S4SRequest).where(
            S4SRequest.from_account_id == account_id, S4SRequest.created_at >= start,
            S4SRequest.created_at < start + timedelta(days=1),
        )
    )).scalar_one()


def _projection(p: S4SProfile, caption: str) -> dict[str, Any]:
    return {
        "profile_id": p.id, "display_name": p.display_name, "username": p.username,
        "avatar_url": p.avatar_url, "primary_caption": caption, "daily_limit": p.daily_limit,
        "opted_in": bool(p.opted_in),
    }


async def _booked(s, account_id: str, slot_at: datetime) -> int:
    start = datetime(slot_at.year, slot_at.month, slot_at.day)
    return len((await s.execute(
        select(S4SSlot.id).where(
            S4SSlot.poster_account_id == account_id, S4SSlot.status != "canceled",
            S4SSlot.slot_at >= start, S4SSlot.slot_at < start + timedelta(days=1),
        )
    )).all())


async def _limit_full(s, p: S4SProfile, slot_at: datetime) -> bool:
    return daily_full(await _booked(s, p.account_id, slot_at), p.daily_limit)


def _other(r: S4SRequest, box: str) -> str:
    return r.from_account_id if box == "received" else r.to_account_id


def _out(r: S4SRequest, box: str, partner_in_agency: bool) -> dict[str, Any]:
    status = "pending" if box == "sent" and r.status == "skipped" else r.status
    if r.status in OPEN and not partner_in_agency:
        status = "cancelled"
    return {
        "id": r.id, "box": box, "status": status, "slot_at": _wire(r.slot_at),
        "from": json.loads(r.from_projection_json), "to": json.loads(r.to_projection_json),
        "from_media": json.loads(r.from_media_json or "[]"), "to_media": json.loads(r.to_media_json or "[]"),
        "created_at": _wire(r.created_at), "answered_at": _wire(r.answered_at),
    }


async def _partner(s, from_id: str, to_pid: int) -> S4SProfile:
    to_p = await s.get(S4SProfile, to_pid)
    if to_p is None or not to_p.discovery_visible or not await _in_agency(s, to_p.account_id):
        raise HTTPException(status_code=404, detail="partner not found")
    refusal = partner_refusal(from_id, to_p.account_id, await blocked_between(s, from_id, to_p.account_id))
    if refusal is not None:
        raise HTTPException(status_code=refusal.status, detail=refusal.detail)
    return to_p


@router.post("/requests", status_code=201)
async def send_request(request: Request) -> dict[str, Any]:
    """Send an S4S request from one of the caller's own Creators to a listed
    partner for one `slot_at`, fixing both Primary captions and both
    projections now.

    ASSUMPTION: a partner profile that Discovery would not list — hidden
    from Discovery, or whose Creator left every Agency — is 404 like one
    that does not exist, while an opted-out one is the spec's 409. Rung 4
    (refusing now is cheaper than undoing a request the partner never made
    findable). Overturned if an owner wants to request a hidden partner it
    already knows.
    """
    await _owner_context()
    from_id, to_pid, slot_at = _parse_send(await _json_object(request))
    ctx = await _owner_context(from_id)
    now = datetime.utcnow()
    # BEGIN IMMEDIATE: the per-day count and its INSERT run alone (deferred: 12 concurrent sends stored 53).
    async with immediate_session() as s:
        to_p = await _partner(s, from_id, to_pid)
        from_p = (await s.execute(
            select(S4SProfile).where(S4SProfile.account_id == from_id)
        )).scalar_one_or_none()
        from_caption = await _primary_caption(s, from_id)
        to_caption = await _primary_caption(s, to_p.account_id)
        open_pair = (await s.execute(
            select(S4SRequest.id).where(
                S4SRequest.from_account_id == from_id, S4SRequest.to_account_id == to_p.account_id,
                S4SRequest.status.in_(OPEN),
            ).limit(1)
        )).first()
        sent_today = await _sent_today(s, from_id, now)
        booked_from = await _booked(s, from_id, slot_at)
        booked_to = await _booked(s, to_p.account_id, slot_at)
        refusal = request_refusal(
            from_p=from_p, to_p=to_p, sent_today=sent_today,
            primaries=from_caption is not None and to_caption is not None, slot_at=slot_at, now=now,
            open_pair=open_pair is not None, booked_from=booked_from, booked_to=booked_to,
        )
        if refusal is not None:
            raise HTTPException(status_code=refusal.status, detail=refusal.detail)
        assert from_p is not None and from_caption is not None and to_caption is not None
        row = S4SRequest(
            from_account_id=from_id, to_account_id=to_p.account_id, slot_at=slot_at,
            from_caption=from_caption, to_caption=to_caption,
            from_projection_json=json.dumps(_projection(from_p, from_caption)),
            to_projection_json=json.dumps(_projection(to_p, to_caption)),
            from_media_json=json.dumps(await snapshot(s, from_id)),
            to_media_json=json.dumps(await snapshot(s, to_p.account_id)),
            status="pending", created_at=now,
        )
        s.add(row)
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="an open request to this partner already exists") from None
        _audit(s, "s4s.request_send", from_id, row.id, {"agency_user_id": ctx.agency_user_id}, ctx.employee_id)
        return _out(row, "sent", True)



PROPOSAL_DAYS = 60
PROPOSAL_HOUR = 6


@router.get("/requests/proposal")
async def propose_time(from_account_id: str | None = None, to_profile_id: str | None = None) -> dict[str, Any]:
    """06:00 UTC on the first day from tomorrow on (never today) on which both
    Creators' Daily limits have room, as `{slot_at}` (null when none within
    PROPOSAL_DAYS, or the sender is not opted in). The same `daily_full`
    rule Send and Accept apply, so the proposal is not refused for a full day.

    Only the instant is answered: of the partner's schedule it says no more
    than "this day has room", which a Send refusal says already (ADR-0011).
    The same 401 → 403 → 404 → 400 order as Send.
    """
    await _owner_context()
    if not from_account_id:
        raise HTTPException(status_code=400, detail="from_account_id: one of your Creators is required")
    await _owner_context(from_account_id)
    try:
        to_pid = int(to_profile_id or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="to_profile_id: the partner's S4S profile id is required") from None
    now = datetime.utcnow()
    async with get_session() as s:
        to_p = await _partner(s, from_account_id, to_pid)
        from_p = (await s.execute(
            select(S4SProfile).where(S4SProfile.account_id == from_account_id)
        )).scalar_one_or_none()
        if from_p is None or not from_p.opted_in:
            return {"slot_at": None}
        tomorrow = datetime(now.year, now.month, now.day, PROPOSAL_HOUR) + timedelta(days=1)
        for n in range(PROPOSAL_DAYS):
            at = tomorrow + timedelta(days=n)
            if not await _limit_full(s, from_p, at) and not await _limit_full(s, to_p, at):
                return {"slot_at": _wire(at)}
        return {"slot_at": None}




@router.get("/requests")
async def list_requests(box: str | None = None) -> list[dict[str, Any]]:
    """The caller's Received or Sent requests, newest first.

    ASSUMPTION: each box lists every status, history included, newest sent
    first. Rung 5 (the spec's Sent tab "showing each request's status").
    Overturned by Infloww evidence of a pending-only Received tab.
    """
    ctx = await _owner_context()
    if box not in ("received", "sent"):
        raise HTTPException(status_code=400, detail="box must be received or sent")
    async with get_session() as s:
        ids = await _own_ids(s, ctx.agency_user_id)
        mine = S4SRequest.to_account_id if box == "received" else S4SRequest.from_account_id
        stmt = select(S4SRequest).where(mine.in_(ids)).order_by(S4SRequest.created_at.desc(), S4SRequest.id.desc())
        if box == "received":
            stmt = stmt.where(S4SRequest.status != "skipped")
        found = (await s.execute(stmt)).scalars().all()
        linked = await _linked(s, {_other(r, box) for r in found})
        return [_out(r, box, _other(r, box) in linked) for r in found]




def _mention(caption: str, username: str) -> str:
    return f"{caption}\n@{username}"


async def _book(s, r: S4SRequest, employee_id: int | None) -> list[S4SSlot]:
    profiles = {p.account_id: p for p in (await s.execute(
        select(S4SProfile).where(S4SProfile.account_id.in_([r.from_account_id, r.to_account_id]))
    )).scalars().all()}
    both = [profiles.get(r.from_account_id), profiles.get(r.to_account_id)]
    if not all(p is not None and p.opted_in for p in both):
        raise HTTPException(status_code=409, detail="both Creators must still be opted in to Share for Share")
    if not all([await _in_agency(s, r.from_account_id), await _in_agency(s, r.to_account_id)]):
        raise HTTPException(status_code=409, detail="both Creators must still belong to an Agency")
    if await blocked_between(s, r.from_account_id, r.to_account_id):
        raise HTTPException(status_code=409, detail="one of these Creators is blocked")
    for p in both:
        if await _limit_full(s, p, r.slot_at):
            raise HTTPException(status_code=409, detail="a Daily limit is full on that day")
    from_proj, to_proj = json.loads(r.from_projection_json), json.loads(r.to_projection_json)
    slots = [
        S4SSlot(request_id=r.id, poster_account_id=r.to_account_id, partner_account_id=r.from_account_id,
                text=_mention(r.from_caption, from_proj["username"]), slot_at=r.slot_at, status="scheduled"),
        S4SSlot(request_id=r.id, poster_account_id=r.from_account_id, partner_account_id=r.to_account_id,
                text=_mention(r.to_caption, to_proj["username"]), slot_at=r.slot_at, status="scheduled"),
    ]
    s.add_all(slots)
    await s.flush()
    for sl in slots:
        sl.job_id = await enqueue_job(sl.poster_account_id, "s4s_post", payload={"slot_id": sl.id},
                                      run_at=sl.slot_at, created_by_employee_id=employee_id, session=s)
    await s.flush()
    return slots


async def _transition(raw_id: str, verb: str) -> dict[str, Any]:
    ctx = await _owner_context()
    try:
        request_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="request not found") from None
    box, movable, _ = VERBS[verb]
    now = datetime.utcnow()
    async with get_session() as s:
        r = await s.get(S4SRequest, request_id)
        party = None if r is None else (r.to_account_id if box == "received" else r.from_account_id)
        held = box if party is not None and party in await _own_ids(s, ctx.agency_user_id) else None
        new = next_status(None if r is None else r.status, verb, held)
        if isinstance(new, Refuse):
            raise HTTPException(status_code=new.status, detail=new.detail)
        assert r is not None and party is not None
        values: dict[str, Any] = {"status": new}
        if verb in ("accept", "decline"):
            values["answered_at"] = now
        # The guard again: of two racing moves exactly one changes the row.
        moved = await s.execute(
            update(S4SRequest)
            .where(S4SRequest.id == request_id, S4SRequest.status.in_(movable),
                   S4SRequest.slot_at > now)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if moved.rowcount != 1:
            raise HTTPException(status_code=409, detail="this request is no longer pending")
        await s.refresh(r)
        payload: dict[str, Any] = {"agency_user_id": ctx.agency_user_id}
        if verb == "accept":
            payload["slot_ids"] = [sl.id for sl in await _book(s, r, ctx.employee_id)]
        _audit(s, f"s4s.request_{verb}", party, r.id, payload, ctx.employee_id)
        return _out(r, box, await _in_agency(s, _other(r, box)))


# Ids are strings parsed in the handler: a typed path param would 422 before the 401/403 checks.
@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: str) -> dict[str, Any]:
    return await _transition(request_id, "accept")


@router.post("/requests/{request_id}/skip")
async def skip_request(request_id: str) -> dict[str, Any]:
    return await _transition(request_id, "skip")


@router.post("/requests/{request_id}/decline")
async def decline_request(request_id: str) -> dict[str, Any]:
    return await _transition(request_id, "decline")


@router.post("/requests/{request_id}/cancel")
async def cancel_request(request_id: str) -> dict[str, Any]:
    return await _transition(request_id, "cancel")
