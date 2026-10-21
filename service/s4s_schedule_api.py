"""service/s4s_schedule_api.py — the S4S schedule, slot cancel, and the
opt-out cascade that `s4s_api.put_profile` runs.

  GET  /admin/s4s/schedule?from&to
       → [{id, slot_at, status, display_status, reason, partner, own, remove_at,
           partner_issue}]
       The caller's own Creators' S4S slots with `from` <= `slot_at` < `to`
       (ISO-8601 instants, at most 42 days apart), by `slot_at`. `partner` and `own` are the projection
       snapshots the request stored at send, never a live read of the other
       Agency (ADR-0011); no account id appears. `partner_issue` is the
       paired slot's tamper reason (`TAMPER_REASONS`, ADR-0015) or null.
  POST /admin/s4s/slots/{id}/cancel
       → the slot, canceled (`owner_canceled`). Only the caller's own slot,
       while it is `scheduled`; the partner's slot is never written.

docs/spec/phase-03-share-for-share.md (Contracts, Lifecycle, Display
status). The same owner-only check order as the other S4S routers: 401 (no
session) → 403 (a Chatter) → 404 (a slot the caller's Agency does not post,
the partner's paired slot included, or no such slot) → 422 (a missing or
malformed `from`/`to`) → 409 (a slot that is no longer `scheduled`).
Registered in server.py with the same lazy-expiry dependency as `s4s_api`
and `s4s_requests_api`.

ASSUMPTION: the range is parsed by `shifts_api._parse_range` itself, so a
bad range is 422 there as on GET /admin/shifts, not the 400 the spec gives
a malformed body. Rung 3 (the same `from`/`to` query, the same parser;
clock_api imports shifts_api's helpers the same way). Overturned by the
spec giving query errors 400.

Display status is derived on read and writes nothing. A `scheduled` slot
whose partner has opted out, or has no Agency left, reads "Canceled" /
`partner_opted_out`; the partner's own Agency never writes it (its `s4s_post` run cancels it at
`slot_at`, service/automations/s4s_post.py).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select, update

from db.engine import get_session
from db.models import Action, Post, S4SProfile, S4SRequest, S4SSlot, ScheduledJob
from employees import AgencyContext
from s4s_common import _owner_context
from s4s_requests_api import OPEN, _audit, _linked, _own_ids, _wire
from shifts_api import _parse_range


router = APIRouter(prefix="/admin/s4s", tags=["s4s"])

WILL_POST = "Will be posted shortly"
IN_PROGRESS = "In progress"
COMPLETED = "Completed"
CANCELED = "Canceled"
FAILED = "Failed"
# The `s4s_check` run's reasons for a posted slot whose post was changed on
# OnlyFans before its removal (Infloww `s4s0133`–`s4s0145`): the only slot
# reasons the partner's schedule is shown, as `partner_issue`.
TAMPER_REASONS = ("post_deleted", "post_archived", "post_edited")


# ── The one slot transition (slot cancel, the opt-out cascade, s4s_post) ──


async def claim_slot(s, slot: S4SSlot, src: str, values: dict[str, Any]) -> bool:
    """`src` → `values` by a status-guarded UPDATE of this one row, with no
    audit row (the `s4s_post` claim). True only when this call moved it."""
    moved = await s.execute(
        update(S4SSlot)
        .where(S4SSlot.id == slot.id, S4SSlot.status == src)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return moved.rowcount == 1


async def move_slot(s, slot: S4SSlot, src: str, values: dict[str, Any], *, action: str,
                    audit: dict[str, Any], agency_user_id: str | None, employee_id: int | None) -> bool:
    """`claim_slot`, and only when this call moved the row, one `action` row
    on the slot's own poster in the same transaction: the Agency's user id,
    the S4S row ids and `audit`, never the slot's text.

    `audit` is its own argument, never derived from `values`: the stored
    columns (datetimes among them) are not the audit row's payload. The
    caller has already proved `slot` is its own Agency's, or is the
    `s4s_post` run on the slot's own poster.
    """
    if not await claim_slot(s, slot, src, values):
        return False
    s.add(Action(
        employee_id=employee_id,
        account_id=slot.poster_account_id,
        action=action,
        target_type="s4s_slot",
        target_id=str(slot.id),
        payload_json=json.dumps({"agency_user_id": agency_user_id, "slot_id": slot.id,
                                 "request_id": slot.request_id, **audit}),
        at=datetime.utcnow(),
    ))
    return True


async def _cancel(s, ctx: AgencyContext, slot: S4SSlot, reason: str) -> bool:
    """An owner's `scheduled` → `canceled` (`reason`), audited as `s4s.slot_cancel`."""
    return await move_slot(s, slot, "scheduled", {"status": "canceled", "reason": reason}, action="s4s.slot_cancel",
                           audit={"reason": reason}, agency_user_id=ctx.agency_user_id, employee_id=ctx.employee_id)


async def opt_out_cascade(s, ctx: AgencyContext, account_id: str, now: datetime) -> None:
    """The opting-out Creator's own rows only: its pending and skipped
    requests, sent and received, become `cancelled` (`opted_out`), and its
    own `scheduled` slots after `now` become `canceled` (`opted_out`).
    Posted slots are left for their 24h removal, and the partner's paired
    slot is never written (it reads `partner_opted_out`, `_display`).

    ASSUMPTION: the cascade writes one `s4s.request_cancel` row per request
    and one `s4s.slot_cancel` row per slot, each on the opting-out Creator
    with `reason: opted_out`, beside the save's `s4s.profile_update`. Rung 3
    (`s4s_requests_api._expire_due` writes one row per request). Overturned
    by an owner wanting the one profile row to stand for the whole cascade.
    """
    requests = (await s.execute(
        select(S4SRequest.id).where(
            S4SRequest.status.in_(OPEN),
            or_(S4SRequest.from_account_id == account_id, S4SRequest.to_account_id == account_id),
        )
    )).scalars().all()
    for request_id in requests:
        done = await s.execute(
            update(S4SRequest)
            .where(S4SRequest.id == request_id, S4SRequest.status.in_(OPEN))
            .values(status="cancelled", cancel_reason="opted_out")
            .execution_options(synchronize_session=False)
        )
        if done.rowcount == 1:
            _audit(s, "s4s.request_cancel", account_id, request_id,
                   {"agency_user_id": ctx.agency_user_id, "reason": "opted_out"}, ctx.employee_id)
    slots = (await s.execute(
        select(S4SSlot).where(
            S4SSlot.poster_account_id == account_id, S4SSlot.status == "scheduled", S4SSlot.slot_at > now,
        )
    )).scalars().all()
    for slot in slots:
        await _cancel(s, ctx, slot, "opted_out")


# ── Display status ───────────────────────────────────────────────────


def _display(slot: S4SSlot, *, own_opted_in: bool, partner_live: bool,
             post_status: str | None, job_status: str | None) -> tuple[str, str | None]:
    """(display_status, reason) for one slot, per the spec's Display status.

    ASSUMPTION: a `scheduled` or `posting` slot whose `s4s_post` job the
    executor has parked as `error` reads "Failed" / `job_error`. The executor
    sets `error` once a raised job runs out of retries
    (automation_executor.py `_mark_job_failure`) and at once for a kind with
    no runner (`run_once`, e.g. an `s4s_post` plugin that failed to import);
    `s4s_post` itself raises only after writing the slot's `failed` row, so
    this covers a run that died before it could write the slot, which then
    never moves again, and "Will be posted shortly" would be untrue. Rung 4
    (a failure is never shown as pending or done, story 28). Overturned by
    `s4s_post` writing the slot's own `failed` row on every exit.
    ASSUMPTION: a `scheduled` slot of a Creator that is itself opted out
    (one whose `slot_at` had passed when the cascade ran) reads "Canceled" /
    `opted_out`, as the cascade would have written. Rung 4. Overturned with
    the cascade's future-only rule.
    ASSUMPTION: a partner with no Agency left (unlinked, or its Agency
    deleted) reads the same `partner_opted_out` as one that opted out, so a
    slot never tells one Agency about another Agency's membership: ADR-0011
    lets only the S4S projection cross, and opt-in state is in it while
    Agency membership is not. Both partners are also gone from Discovery
    alike. Rung 4 (a membership change once shown cannot be taken back).
    Overturned by an owner wanting a distinct reason for a departed partner.
    """
    if slot.status in ("scheduled", "posting") and job_status == "error":
        return FAILED, "job_error"
    if slot.status == "scheduled":
        if not partner_live:
            return CANCELED, "partner_opted_out"
        if not own_opted_in:
            return CANCELED, "opted_out"
        return WILL_POST, None
    if slot.status == "posting":
        return IN_PROGRESS, None
    if slot.status == "posted":
        return (COMPLETED if post_status == "deleted" else IN_PROGRESS), None
    if slot.status == "canceled":
        return CANCELED, slot.reason
    return FAILED, slot.reason


async def _outs(s, slots: list[S4SSlot]) -> list[dict[str, Any]]:
    """Each slot as the schedule shows it. The partner's opt-in state and
    whether it still has an Agency are read only to derive the display
    status; neither value, nor any partner account id, leaves the Relay."""
    if not slots:
        return []
    accounts = {sl.poster_account_id for sl in slots} | {sl.partner_account_id for sl in slots}
    opted = {aid for aid, on in (await s.execute(
        select(S4SProfile.account_id, S4SProfile.opted_in).where(S4SProfile.account_id.in_(accounts))
    )).all() if on}
    live = opted & await _linked(s, accounts)
    requests = {r.id: r for r in (await s.execute(
        select(S4SRequest).where(S4SRequest.id.in_({sl.request_id for sl in slots}))
    )).scalars().all()}
    post_ids = {sl.post_id for sl in slots if sl.post_id is not None}
    posts = dict((await s.execute(select(Post.id, Post.status).where(Post.id.in_(post_ids)))).all()) if post_ids else {}
    job_ids = {sl.job_id for sl in slots if sl.job_id is not None}
    jobs = dict((await s.execute(
        select(ScheduledJob.id, ScheduledJob.status).where(ScheduledJob.id.in_(job_ids))
    )).all()) if job_ids else {}
    # The paired slot (the partner posting this Creator's caption) shows only
    # a tamper reason, so a partner who changed its post is visible here.
    issues = {(sl.request_id, sl.poster_account_id): sl.reason for sl in (await s.execute(
        select(S4SSlot).where(S4SSlot.request_id.in_(set(requests)), S4SSlot.status == "failed",
                              S4SSlot.reason.in_(TAMPER_REASONS))
    )).scalars().all()}
    out = []
    for sl in slots:
        r = requests[sl.request_id]
        mine_sent = r.from_account_id == sl.poster_account_id
        own_proj = json.loads(r.from_projection_json if mine_sent else r.to_projection_json)
        partner_proj = json.loads(r.to_projection_json if mine_sent else r.from_projection_json)
        display, reason = _display(
            sl, own_opted_in=sl.poster_account_id in opted, partner_live=sl.partner_account_id in live,
            post_status=posts.get(sl.post_id), job_status=jobs.get(sl.job_id),
        )
        out.append({
            "id": sl.id, "slot_at": _wire(sl.slot_at), "status": sl.status, "display_status": display,
            "reason": reason, "partner": partner_proj, "own": own_proj, "remove_at": _wire(sl.remove_at),
            "partner_issue": issues.get((sl.request_id, sl.partner_account_id)),
        })
    return out


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/schedule")
async def get_schedule(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
) -> list[dict[str, Any]]:
    """The caller's own Creators' slots with `from` <= `slot_at` < `to`, by
    `slot_at`. The app sends its local month's first and next-first
    instants, as the Shift schedule sends its local week (app/lib/shifts.ts
    `shiftWeekPath`), so every slot lands on its own local day.

    ASSUMPTION: each item also carries `own`, the request's stored snapshot
    of the caller's posting Creator, beside the spec's keys, so an owner
    with several Creators sees which one posts. Rung 3 (Requests rows show
    both stored snapshots, `s4s_requests_api._out`). Overturned by the
    spec's key set being made exact.
    """
    # Parsed in the handler, after the session checks, as shifts_api does.
    ctx = await _owner_context()
    start, end = _parse_range(from_, to)
    async with get_session() as s:
        ids = await _own_ids(s, ctx.agency_user_id)
        slots = list((await s.execute(
            select(S4SSlot)
            .where(S4SSlot.poster_account_id.in_(ids), S4SSlot.slot_at >= start, S4SSlot.slot_at < end)
            .order_by(S4SSlot.slot_at, S4SSlot.id)
        )).scalars().all())
        return await _outs(s, slots)


# The id is a string parsed in the handler: a typed path parameter would let
# FastAPI answer 422 before the 401/403 session checks run.
@router.post("/slots/{slot_id}/cancel")
async def cancel_own_slot(slot_id: str) -> dict[str, Any]:
    """Cancel one of the caller's own Creators' slots while it is
    `scheduled`. Its paired partner slot is left as it is.

    ASSUMPTION: the partner's paired slot is 404 to the caller, like a slot
    of no party, because the route cancels only the caller's own slot. Rung
    3 (`s4s_requests_api._transition` answers the wrong party 404).
    Overturned if the partner side should get 403.
    ASSUMPTION: an owner's cancel stores reason `owner_canceled`, and any
    `scheduled` slot may be cancelled, even one whose time has just passed
    (the guarded UPDATE loses to the `s4s_post` claim, ticket 19). Rung 6
    for the name, rung 4 for the time. Overturned by Infloww's wording or a
    future-only rule.
    """
    ctx = await _owner_context()
    try:
        sid = int(slot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="slot not found") from None
    async with get_session() as s:
        slot = await s.get(S4SSlot, sid)
        if slot is None or slot.poster_account_id not in await _own_ids(s, ctx.agency_user_id):
            raise HTTPException(status_code=404, detail="slot not found")
        if not await _cancel(s, ctx, slot, "owner_canceled"):
            raise HTTPException(status_code=409, detail="this slot is no longer scheduled")
        await s.refresh(slot)
        (out,) = await _outs(s, [slot])
        return out
