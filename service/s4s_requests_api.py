"""service/s4s_requests_api.py — S4S requests: send, answer, cancel, expire.

  POST /admin/s4s/requests  {from_account_id, to_profile_id, slot_at}
       → 201 the request (box "sent"). `from_account_id` is one of the
       caller's own Creators; the partner is named by S4S profile id only.
  GET  /admin/s4s/requests/proposal?from_account_id&to_profile_id
       → {slot_at} 06:00 UTC on the first day from tomorrow with room under
       both Daily limits, or null.
  GET  /admin/s4s/requests?box=received|sent
       → [{id, box, status, slot_at, from, to, from_media, to_media,
           created_at, answered_at}]
       `from` and `to` are the projection snapshots stored at send, never a
       live read of the other Agency (ADR-0011); `from_media` / `to_media`
       the S4S media `{id, media_type}` on each Primary post at send (ADR-0015, readable by
       either party at GET /admin/s4s/media/{id}). A skipped request is absent
       from the receiver's box and reads `pending` in the sender's.
  POST /admin/s4s/requests/{id}/accept|skip|decline  the receiver only.
  POST /admin/s4s/requests/{id}/cancel               the sender only.

docs/spec/phase-03-share-for-share.md (Contracts, Lifecycle). The same
owner-only check order as `s4s_api`: 401 (no session) → 403 (a Chatter, or a
`from_account_id` outside the caller's Agency) → 404 (a request the caller
is not that party to, a profile id that is not a listed partner, or a
partner blocked either way, `s4s_blocks`) → 400 (a malformed body, or a
request to the sender's own Creator) → 409 (the sender's 51st request of
the UTC day, a past `slot_at`, a missing Primary post, an opted-out party, a
full Daily limit, an open request between the same pair in the same
direction, a block at Accept, or a request that is no longer pending).

Every transition is a status-guarded UPDATE whose zero row count answers
409, so of two racing answers exactly one wins. Accept runs its guarded
update, then re-checks both opt-ins and Daily limits, then inserts the two
S4S slots and queues one `s4s_post` job per slot on its poster's account at
`slot_at` through the executor's `enqueue_job(session=...)`, all in one
transaction: a failure anywhere leaves the request pending with no slot and
no job. A
request whose `slot_at` has passed is expired lazily before every S4S
handler runs (`expire_callers_requests`, a dependency of both S4S routers
in server.py, like the Auto clock-out sweep of the /admin/shifts routers).
Each send, answer, cancel and expiry appends one `actions` row.

When a queued job falls due, the supervisor dispatches it
(automation_executor.py `_due_job_pairs`) to the `s4s_post` automation
(service/automations/s4s_post.py), which posts the slot on its poster's own
account through Auto Post unless `S4S_LIVE_POSTING` is set off (it defaults
on), and otherwise ends it with a reason.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from auth import get_request_user
from automation_executor import enqueue_job
from db.engine import get_session
from db.models import Action, S4SBlock, S4SPost, S4SProfile, S4SRequest, S4SSlot, UserAccount
from s4s_common import _json_object, _owner_context
from s4s_media import snapshot


router = APIRouter(prefix="/admin/s4s", tags=["s4s"])

OPEN = ("pending", "skipped")
# Infloww's limit (`s4s0096`): requests one Creator sends per UTC day.
MAX_SENT_PER_DAY = 50
_SEND_FIELDS = ("from_account_id", "to_profile_id", "slot_at")
_ANSWERS = {"accept": "accepted", "skip": "skipped", "decline": "declined"}


def _wire(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat() + "Z"


async def _own_ids(s, agency_user_id: str) -> set[str]:
    """The Agency's Creators: its `user_accounts` rows, as `list_profiles`
    lists them (a Master owns only its own links)."""
    return set((await s.execute(
        select(UserAccount.account_id).where(UserAccount.user_id == agency_user_id)
    )).scalars().all())


def _audit(s, action: str, account_id: str, request_id: int, payload: dict[str, Any],
           employee_id: int | None = None) -> None:
    """One `actions` row in the transition's own transaction: the S4S row
    ids and who acted, never a caption or fan data."""
    s.add(Action(
        employee_id=employee_id,
        account_id=account_id,
        action=action,
        target_type="s4s_request",
        target_id=str(request_id),
        payload_json=json.dumps({**payload, "request_id": request_id}),
        at=datetime.utcnow(),
    ))


# ── Lazy expiry ──────────────────────────────────────────────────────


async def expire_callers_requests() -> None:
    """Expire the open requests of the signed-in owner's Creators whose
    `slot_at` has passed. Nothing for a signed-out or Chatter request: both
    are refused by every S4S route.

    ASSUMPTION: the sweep covers only requests the caller's Agency is a
    party to, as the Auto clock-out sweep covers only the caller's Agencies
    (rung 3, `clock_api._sweep_callers_agencies`); a request nobody reads
    stays `pending` in the table until a party's next S4S call, which is
    the first moment anyone could see or answer it. Overturned if a report
    must read expiry straight from the table.
    """
    user = get_request_user()
    if user is None:
        return
    async with get_session() as s:
        ids = await _own_ids(s, user.id)
        if ids:
            await _expire_due(s, ids, datetime.utcnow())


async def _expire_due(s, account_ids: set[str], now: datetime) -> None:
    """Each due open request goes to `expired` by a guarded UPDATE, and only
    the UPDATE that changed it writes its `s4s.request_expire` row.

    ASSUMPTION: an expiry writes one audit row, on the sender's Creator,
    with `actor: system` and no `agency_user_id`, because no Agency acted
    (rung 3: `clock.auto_out` rows carry `actor: system`). Overturned by an
    owner wanting one row per party.
    """
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


# ── Send ─────────────────────────────────────────────────────────────


def _parse_utc(value: Any) -> datetime:
    """An ISO-8601 time with a zone → naive UTC (shifts_api's rule, with
    this router's 400 for a malformed body)."""
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=400, detail="slot_at: an ISO-8601 UTC time is required")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="slot_at: not an ISO-8601 time") from None
    if dt.tzinfo is None:
        raise HTTPException(status_code=400, detail="slot_at: the time needs a zone (end it with Z)")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_send(body: dict[str, Any]) -> tuple[str, int, datetime]:
    """ASSUMPTION: a key outside the three is 400, as for the profile body.
    Rung 3 (`s4s_api._parse_profile_body`). Overturned with that one."""
    unknown = set(body) - set(_SEND_FIELDS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown field(s): {', '.join(sorted(unknown))}")
    from_id = body.get("from_account_id")
    if not isinstance(from_id, str) or not from_id:
        raise HTTPException(status_code=400, detail="from_account_id: one of your Creators is required")
    to_pid = body.get("to_profile_id")
    if isinstance(to_pid, bool) or not isinstance(to_pid, int):
        raise HTTPException(status_code=400, detail="to_profile_id: the partner's S4S profile id is required")
    return from_id, to_pid, _parse_utc(body.get("slot_at"))


async def _primary_caption(s, account_id: str) -> str | None:
    return (await s.execute(
        select(S4SPost.caption).where(S4SPost.account_id == account_id, S4SPost.is_primary.is_(True))
    )).scalar_one_or_none()


async def _linked(s, ids) -> set[str]:
    """The accounts in `ids` that still have an Agency (a `user_accounts` row)."""
    return set((await s.execute(
        select(UserAccount.account_id).where(UserAccount.account_id.in_(ids))
    )).scalars().all())


async def _in_agency(s, account_id: str) -> bool:
    return account_id in await _linked(s, {account_id})


async def blocked_between(s, a: str, b: str) -> bool:
    """Has an Agency of either Creator blocked the other one (`s4s_blocks`)?

    ASSUMPTION: a block by any Agency linked to a Creator counts, so a
    Creator two Agencies share is kept apart from whomever either blocked.
    Rung 4 (refusing is the cheaper direction). Overturned by an owner
    wanting a co-owner's block to bind only that co-owner's sends.
    """
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
    """Requests the Creator sent on `now`'s UTC day, whatever became of them."""
    start = datetime(now.year, now.month, now.day)
    return (await s.execute(
        select(func.count()).select_from(S4SRequest).where(
            S4SRequest.from_account_id == account_id, S4SRequest.created_at >= start,
            S4SRequest.created_at < start + timedelta(days=1),
        )
    )).scalar_one()


def _projection(p: S4SProfile, caption: str) -> dict[str, Any]:
    """The S4S projection (ADR-0011), the Discovery card's keys less the
    viewer-relative `own_agency`: what a request stores at send."""
    return {
        "profile_id": p.id, "display_name": p.display_name, "username": p.username,
        "avatar_url": p.avatar_url, "primary_caption": caption, "daily_limit": p.daily_limit,
        "opted_in": bool(p.opted_in),
    }


async def _booked(s, account_id: str, slot_at: datetime) -> int:
    """The Creator's slots that are not canceled on `slot_at`'s UTC day.

    The spec's rule, Lifecycle: "The Daily limit counts a poster's slots
    that are not canceled and fall on the same UTC day as `slot_at`" — so
    open requests do not count; they are re-checked at Accept.
    """
    start = datetime(slot_at.year, slot_at.month, slot_at.day)
    return len((await s.execute(
        select(S4SSlot.id).where(
            S4SSlot.poster_account_id == account_id, S4SSlot.status != "canceled",
            S4SSlot.slot_at >= start, S4SSlot.slot_at < start + timedelta(days=1),
        )
    )).all())


async def _limit_full(s, p: S4SProfile, slot_at: datetime) -> bool:
    return await _booked(s, p.account_id, slot_at) >= p.daily_limit


def _other(r: S4SRequest, box: str) -> str:
    """The account id of the party `box` does not hold: the sender for the
    Received box, the receiver for the Sent box."""
    return r.from_account_id if box == "received" else r.to_account_id


def _out(r: S4SRequest, box: str, partner_in_agency: bool) -> dict[str, Any]:
    """The request as `box` sees it: the sender reads a skip as `pending`,
    and an open request whose other party has left every Agency, or lost its
    Agency, reads `cancelled` (story 31; derived, the row is not written).

    ASSUMPTION: a departed party's open request reads `cancelled`, the one
    request status that says nobody will act on it, while answered and
    expired requests keep their status as history. Rung 5 (the request keys
    carry no reason). Overturned by a request reason field in the contract.
    """
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
    """The partner profile `from_id` may send to: 404 for one Discovery would
    not list (missing, hidden, no Agency left, or blocked either way — a block
    reads as a partner that is not there, as Discovery hides it too), 400 for
    the sender's own Creator."""
    to_p = await s.get(S4SProfile, to_pid)
    if to_p is None or not to_p.discovery_visible or not await _in_agency(s, to_p.account_id):
        raise HTTPException(status_code=404, detail="partner not found")
    if to_p.account_id == from_id:
        raise HTTPException(status_code=400, detail="a Creator cannot send an S4S request to itself")
    if await blocked_between(s, from_id, to_p.account_id):
        raise HTTPException(status_code=404, detail="partner not found")
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
    async with get_session() as s:
        to_p = await _partner(s, from_id, to_pid)
        if await _sent_today(s, from_id, now) >= MAX_SENT_PER_DAY:
            raise HTTPException(status_code=409,
                                detail=f"a Creator sends at most {MAX_SENT_PER_DAY} S4S requests a day (UTC)")
        from_p = (await s.execute(
            select(S4SProfile).where(S4SProfile.account_id == from_id)
        )).scalar_one_or_none()
        if from_p is None or not from_p.opted_in or not to_p.opted_in:
            raise HTTPException(status_code=409, detail="both Creators must be opted in to Share for Share")
        from_caption = await _primary_caption(s, from_id)
        to_caption = await _primary_caption(s, to_p.account_id)
        if from_caption is None or to_caption is None:
            raise HTTPException(status_code=409, detail="both Creators need a Primary post")
        if slot_at <= now:
            raise HTTPException(status_code=409, detail="the proposed time has passed")
        open_pair = (await s.execute(
            select(S4SRequest.id).where(
                S4SRequest.from_account_id == from_id, S4SRequest.to_account_id == to_p.account_id,
                S4SRequest.status.in_(OPEN),
            ).limit(1)
        )).first()
        if open_pair is not None:
            raise HTTPException(status_code=409, detail="an open request to this partner already exists")
        for p in (from_p, to_p):
            if await _limit_full(s, p, slot_at):
                raise HTTPException(status_code=409, detail="a Daily limit is full on that day")
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
            # A concurrent send for the same pair took the open slot first.
            raise HTTPException(status_code=409, detail="an open request to this partner already exists") from None
        _audit(s, "s4s.request_send", from_id, row.id, {"agency_user_id": ctx.agency_user_id}, ctx.employee_id)
        # The partner passed `_in_agency` above, in this transaction.
        return _out(row, "sent", True)


# ── Proposed time ────────────────────────────────────────────────────

# How many UTC days ahead the proposal looks before giving up (`slot_at: null`).
PROPOSAL_DAYS = 60
# The proposal's time of day, UTC.
PROPOSAL_HOUR = 6


@router.get("/requests/proposal")
async def propose_time(from_account_id: str | None = None, to_profile_id: str | None = None) -> dict[str, Any]:
    """06:00 UTC on the first day from tomorrow on (never today) on which both
    Creators' Daily limits have room, as `{slot_at}` (null when none within
    PROPOSAL_DAYS, or the sender is not opted in). The same `_limit_full`
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


# ── Boxes ────────────────────────────────────────────────────────────


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


# ── Answer, cancel ───────────────────────────────────────────────────


def _mention(caption: str, username: str) -> str:
    """The partner's caption plus an @mention of the partner.

    ASSUMPTION: the mention goes on its own line after the caption. Rung 6
    (the spec fixes "caption plus @mention", not the joint). Overturned by
    Infloww evidence of where the mention sits.
    """
    return f"{caption}\n@{username}"


async def _book(s, r: S4SRequest, employee_id: int | None) -> list[S4SSlot]:
    """Accept's re-checks, its two slots and their two `s4s_post` jobs, inside
    the accept transaction: an HTTPException here rolls back the guarded
    update too, and a slot never exists without its job."""
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
    """Move one request the caller is the right party to.

    ASSUMPTION: the sender answering, or the receiver cancelling, is 404
    like a non-party, because each route exists for one party only. Rung 5
    (the spec's "for the receiver only" / "for the sender only" with 404
    for a request the caller is not a party to). Overturned if the wrong
    party should get 403.
    ASSUMPTION: Skip leaves `answered_at` null, so nothing in the sender's
    Sent tab tells a skip from a pending request. Rung 4. Overturned if the
    receiver's history needs the skip time (the audit row has it).
    """
    ctx = await _owner_context()
    try:
        request_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="request not found") from None
    receiver = verb in _ANSWERS
    now = datetime.utcnow()
    async with get_session() as s:
        r = await s.get(S4SRequest, request_id)
        party = None if r is None else (r.to_account_id if receiver else r.from_account_id)
        if party is None or party not in await _own_ids(s, ctx.agency_user_id):
            raise HTTPException(status_code=404, detail="request not found")
        values: dict[str, Any] = {"status": _ANSWERS.get(verb, "cancelled")}
        if verb in ("accept", "decline"):
            values["answered_at"] = now
        moved = await s.execute(
            update(S4SRequest)
            .where(S4SRequest.id == request_id, S4SRequest.status.in_(("pending",) if receiver else OPEN),
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
        action = "s4s.request_cancel" if verb == "cancel" else f"s4s.request_{verb}"
        _audit(s, action, party, r.id, payload, ctx.employee_id)
        box = "received" if receiver else "sent"
        return _out(r, box, await _in_agency(s, _other(r, box)))


# The ids are strings parsed in the handler: a typed path parameter would let
# FastAPI answer 422 before the 401/403 session checks run.
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
