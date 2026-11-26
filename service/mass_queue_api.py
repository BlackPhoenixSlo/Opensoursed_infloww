from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

import mass_queue_decide
import send_ops
from automations.send_mass_decide import audience_filter_json, echoed_of
from relay_host import (
    get_client as _get_client,
    proxy as _proxy,
    resolve_account_id as _resolve_account_id,
)

from side_effect_gate import refuse_if_platform_lacks

log = logging.getLogger("of-relay")

router = APIRouter()

# Send key held 10 min after a possible OF POST so a retry/twin of an unclear send is a 409; in memory, a restart forgets it.
_MAY_HAVE_SENT_S = 600.0
_send_keys: dict[tuple[str, str], float | None] = {}


def _send_key(account_id: str, body: BaseModel) -> tuple[str, str]:
    return str(account_id), hashlib.sha256(body.model_dump_json().encode()).hexdigest()


def _reserve_send(key: tuple[str, str]) -> None:
    now = time.monotonic()
    for k in [k for k, t in _send_keys.items() if t is not None and now - t >= _MAY_HAVE_SENT_S]:
        del _send_keys[k]
    if key in _send_keys:
        raise HTTPException(409, "This exact mass message is being sent, or may already have "
                                 "gone out: OF did not answer the last try. Check OF's sent "
                                 "mass messages before sending it again.")
    _send_keys[key] = None


@contextlib.asynccontextmanager
async def _exclude_list_held(account_id: str, excluded_users: list[int]):
    from audiences import broadcast_lock, ensure_exclude_list
    async with broadcast_lock(account_id):
        yield await ensure_exclude_list(account_id, excluded_users, client=_get_client())


async def _open_mass_run(
    request: Request,
    *,
    user_lists: list,
    included_users: list[int],
    excluded_users: list[int],
    excluded_user_lists: list | None = None,
    funnel_id: int | None = None,
    online_only: bool = False,
    filters: dict | None = None,
    auto_exclude: int | None = None,
) -> tuple[str, int | None, int | None]:
    account_id = _resolve_account_id(request)
    from employees import resolve_outbound_employee_id
    employee_id = await resolve_outbound_employee_id(request, account_id)

    audience_filter = audience_filter_json(
        user_lists=user_lists, included_users=included_users,
        excluded_users=excluded_users, excluded_user_lists=excluded_user_lists,
        online=online_only, filters=filters, auto_exclude=auto_exclude)
    mass_run_id: int | None = None
    try:
        from db.engine import get_session
        from db.models import MASS_RUN_RUNNING, MassRun
        async with get_session() as s:
            run = MassRun(
                account_id=str(account_id),
                funnel_id=int(funnel_id) if funnel_id is not None else None,
                started_by_employee_id=employee_id,
                audience_filter=audience_filter,
                recipient_count=len(included_users),
                status=MASS_RUN_RUNNING,
            )
            s.add(run)
            await s.flush()
            mass_run_id = int(run.id)
    except Exception:
        log.exception("mass_runs mint failed (account=%s)", account_id)
    return account_id, employee_id, mass_run_id


async def _close_mass_run(
    *,
    account_id: str,
    employee_id: int | None,
    mass_run_id: int | None,
    text: str,
    price: float,
    result: Any,
    recipient_ids: list[int] | None = None,
    scheduled: bool = False,
) -> None:
    if mass_run_id is None:
        return
    from attribution import (
        reconcile_mass_placeholder,
        write_mass_optimistic_rows,
        write_outbound_attribution,
    )
    from event_transcoder import _parse_iso, _to_cents

    created_at = (
        (_parse_iso(result.get("createdAt")) if isinstance(result, dict) else None)
        or datetime.utcnow()
    )
    price_cents = _to_cents(price)

    per_fan_ids = echoed_of(result)

    echoed_fans: set[int] = set()
    for fan_id, msg_id in per_fan_ids:
        echoed_fans.add(fan_id)
        try:
            await write_outbound_attribution(
                account_id=account_id,
                fan_id=fan_id,
                message_id=msg_id,
                sent_by_employee_id=employee_id,
                body=text or "",
                price_cents=price_cents,
                created_at=created_at,
                mass_run_id=mass_run_id,
            )
            await reconcile_mass_placeholder(
                account_id=account_id, fan_id=fan_id, mass_run_id=mass_run_id,
            )
        except Exception:
            log.exception(
                "mass attribution write failed (account=%s run=%s fan=%s)",
                account_id, mass_run_id, fan_id,
            )

    pending = mass_queue_decide.pending_placeholders(recipient_ids, echoed_fans)
    if pending:
        await write_mass_optimistic_rows(
            account_id=account_id,
            fan_ids=pending,
            mass_run_id=mass_run_id,
            sent_by_employee_id=employee_id,
            body=text or "",
            price_cents=price_cents,
            created_at=created_at,
        )

    queue_id = result.get("id") if isinstance(result, dict) else None
    try:
        from db.engine import get_session
        from db.models import MASS_RUN_OK, MassRun
        async with get_session() as s:
            mr = await s.get(MassRun, mass_run_id)
            if mr is not None:
                mr.status = MASS_RUN_OK
                mr.completed_at = datetime.utcnow()
                if queue_id is not None:
                    mr.queue_id = int(queue_id)
                if not scheduled:
                    # Scheduled send leaves both NULL: not sent yet, a future sent_at would put a line on the thread.
                    mr.body = text or ""
                    mr.sent_at = created_at
    except Exception:
        log.exception("mass run close failed (account=%s run=%s)", account_id, mass_run_id)


class _MassScheduleBody(BaseModel):
    text: str
    scheduled_date: str | None = Field(
        None, description="ISO 8601 (e.g. 2026-06-01T18:00:00+00:00); omit to send now",
    )
    save_for_later: bool = False
    user_ids: list[int] = Field(default_factory=list)
    user_lists: list[str] = Field(default_factory=list, description="List ids or built-in names like 'fans'")
    excluded_users: list[int] = Field(default_factory=list)
    excluded_user_lists: list[str] = Field(default_factory=list, description="List ids/names to exclude from the audience")
    price: float = Field(0, ge=0)
    locked_text: bool = False
    media_files: list[int | dict] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    tagged_users: list[int] = Field(default_factory=list)
    giphy_id: str | None = Field(
        None,
        description="Giphy GIF id forwarded to OF as top-level `giphyId`.",
    )
    online_only: bool = False
    filters: dict | None = None
    recent_chat_hours: float | None = Field(
        None, gt=0, description="Target fans chatted with in the last N hours (from local DB)",
    )
    recent_chat_limit: int | None = Field(
        None, gt=0, description="Cap the recent-chat audience to the N most-recent fans",
    )
    exclude_replied_hours: float | None = Field(
        None, gt=0, description="Exclude fans we replied to (outbound) in the last N hours",
    )
    exclude_inbound_hours: float | None = Field(
        None, gt=0, description="Exclude fans who messaged us (inbound) in the last N hours",
    )
    unread_limit: int | None = Field(
        None, gt=0, le=1000, description="Target up to N fans with unread messages",
    )
    unsend_after_hours: float | None = Field(
        None, gt=0, le=8760, description="Auto-unsend the broadcast N hours after it sends",
    )
    funnel_id: int | None = Field(
        None, gt=0, description="mass_message_funnels.id to walk repliers through",
    )
    min_total_spent: float | None = Field(None, gt=0, description="Only fans who spent at least $N")
    min_tipped: float | None = Field(None, gt=0, description="Only fans who tipped at least $N")
    subscribed_over_days: float | None = Field(None, gt=0, description="Only fans subscribed N+ days")
    expired_over_days: float | None = Field(None, gt=0, description="Only fans expired N+ days ago")
    require_recipients: bool = Field(
        False, description="422 (nothing sent) when no list and no fan id is left after the guards",
    )

    def is_later(self) -> bool:
        return bool(self.scheduled_date or self.save_for_later)

    def has_thresholds(self) -> bool:
        return bool(self.min_total_spent or self.min_tipped
                    or self.subscribed_over_days or self.expired_over_days)


@router.post("/api/of/v2/messages/queue")
async def of_send_or_schedule_mass(
    request: Request,
    body: _MassScheduleBody = Body(...),
):
    """POST /messages/queue — broadcasts a mass message to many fans.
    With `scheduled_date` it's a scheduled send; without, it's immediate.
    `user_ids` for explicit fans OR `user_lists` for list-based audience.

    Attribution: mint a `mass_runs` row up front, then walk the
    OF response for per-fan ids and write attribution rows. This is the
    path the Next UI broadcast composer actually hits."""
    aid = _resolve_account_id(request)
    if body.is_later():
        refuse_if_platform_lacks(aid, "schedule_mass_message", "scheduled mass message")
    else:
        refuse_if_platform_lacks(aid, "send_mass_message", "mass message")
    claim = None
    if anchor := send_ops.anchor(request):
        import accounts
        platform, kind = accounts.get_platform(aid), "manual_mass_schedule" if body.is_later() else "manual_mass_send"
        claim = send_ops.begin(platform, aid, send_ops.op_id(platform, aid, kind, "mass", anchor,
                                                             send_ops.part(request.headers)),
                               kind, "mass", send_ops.digest(body.model_dump()))
        if isinstance(claim, send_ops.Sent):
            return claim.result
    key = _send_key(aid, body)
    try:
        _reserve_send(key)
    except HTTPException:
        if claim is not None:
            claim.abort()
        raise
    try:
        result = await _send_or_schedule_mass(request, body, key, claim)
    except BaseException as e:
        if _send_keys.get(key, 0.0) is None:
            del _send_keys[key]
        if claim is not None and isinstance(e, Exception):
            claim.abort()
        raise
    _send_keys.pop(key, None)
    if claim is not None:
        claim.done(result)
    return result


async def _send_or_schedule_mass(request: Request, body: _MassScheduleBody,
                                 _key: tuple[str, str], claim: send_ops.Claim | None = None):
    _asked_ids = len(dict.fromkeys(body.user_ids))
    _thresholds = body.has_thresholds()
    _online_now = bool(body.online_only or (body.filters or {}).get("online"))
    _refusal = mass_queue_decide.threshold_refusal(
        body.scheduled_date, body.save_for_later, _thresholds, _online_now,
        body.expired_over_days)
    if _refusal is not None:
        raise HTTPException(422, _refusal)
    from audiences import (MASSDMEXCLUDE_LIST, THRESHOLD_IDS_MAX,
                           AudienceUnknown, resolve_mass_audience)
    _aid = _resolve_account_id(request)
    # Even plain blasts need MASSDMEXCLUDE and dedup against explicit recipients in pending local send jobs.
    try:
        resolved = await resolve_mass_audience(
            _aid,
            included_users=body.user_ids,
            excluded_users=body.excluded_users,
            recent_chat_hours=body.recent_chat_hours,
            recent_chat_limit=body.recent_chat_limit,
            exclude_replied_hours=body.exclude_replied_hours,
            exclude_inbound_hours=body.exclude_inbound_hours,
            exclude_funnel_responders=body.funnel_id,
            unread_limit=body.unread_limit,
            exclude_list_name=MASSDMEXCLUDE_LIST,
            min_spent_cents=round(body.min_total_spent * 100) if body.min_total_spent else None,
            min_tips_cents=round(body.min_tipped * 100) if body.min_tipped else None,
            subscribed_over_days=body.subscribed_over_days,
            expired_over_days=body.expired_over_days,
            online_now=_thresholds and _online_now,
            user_lists=body.user_lists if _thresholds else None,
            excluded_user_lists=body.excluded_user_lists if _thresholds else None,
            client=_get_client() if (body.unread_limit or _thresholds) else None,
        )
    except AudienceUnknown as e:
        raise HTTPException(422, str(e))
    body.user_ids = resolved["included_users"]
    body.excluded_users = resolved["excluded_users"]
    if _thresholds:
        # OF unions userLists with userIds: a list left in would re-add every fan below the bar.
        _refusal = mass_queue_decide.threshold_count_refusal(
            len(body.user_ids), THRESHOLD_IDS_MAX)
        if _refusal is not None:
            raise HTTPException(422, _refusal)
        body.user_lists = []
        body.online_only = False
        body.filters = None
    _skipped_answered = resolved.get("skipped_funnel_responders") or []
    _answered_total = int(resolved.get("funnel_responders_total") or 0)
    # Excluded ids must leave user_ids: of_client subtracts them from wire userIds, else recipient_count and optimistic rows are phantom.
    body.user_ids = mass_queue_decide.strip_excluded(body.user_ids, body.excluded_users)
    _listed_out = 0
    if (not _thresholds and body.user_ids and body.excluded_user_lists
            and not (body.user_lists or body.online_only or body.filters)):
        from audiences import drop_exclude_list_members
        _kept = len(set(body.user_ids))
        try:
            body.user_ids = await drop_exclude_list_members(
                _get_client(), body.user_ids, body.excluded_user_lists)
        except AudienceUnknown as e:
            raise HTTPException(422, str(e))
        _listed_out = _kept - len(set(body.user_ids))
    # What OF does with an empty audience is unknown: fail closed with 422.
    if (not (body.user_ids or body.user_lists or body.online_only or body.filters)
            or (body.require_recipients and not body.user_lists and not body.user_ids)):
        raise HTTPException(422, mass_queue_decide.nobody_left_refusal(_asked_ids, _listed_out))
    # OF has no excludedUsers field (silently dropped): mirror ids into the Auto_Exclude list, synced under broadcast_lock held through the POST.
    _later = body.is_later()
    _held = (_exclude_list_held(_aid, body.excluded_users) if mass_queue_decide.needs_exclude_list(
        body.excluded_users, body.user_lists, body.online_only, body.filters) else contextlib.nullcontext())
    async with _held as auto_lid:
        if auto_lid is not None and auto_lid not in (body.excluded_user_lists or []):
            body.excluded_user_lists = [*(body.excluded_user_lists or []), auto_lid]
        account_id, employee_id, mass_run_id = await _open_mass_run(
            request,
            user_lists=body.user_lists,
            included_users=body.user_ids,
            excluded_users=body.excluded_users,
            excluded_user_lists=body.excluded_user_lists,
            funnel_id=body.funnel_id,
            online_only=body.online_only,
            filters=body.filters,
            auto_exclude=auto_lid,
        )
        client = _get_client()
        # OF 400s a broadcast within ~10s of another ("Please allow 10 seconds"): retry once only on that refusal, nothing was created.
        from automation_executor import of_write_with_retry
        shared = dict(
            text=body.text,
            user_lists=body.user_lists,
            excluded_users=body.excluded_users,
            excluded_user_lists=body.excluded_user_lists,
            price=body.price,
            locked_text=body.locked_text,
            media_files=body.media_files,
            previews=body.previews,
            tagged_users=body.tagged_users,
            giphy_id=body.giphy_id,
            filters=body.filters,
            online_only=body.online_only,
        )
        if _later:
            post, extra = client.schedule_mass_message, dict(
                scheduled_date=body.scheduled_date,
                save_for_later=body.save_for_later and not body.scheduled_date,
                user_ids=body.user_ids)
        else:
            post, extra = client.send_mass_message, dict(included_users=body.user_ids)
        _send_keys[_key] = time.monotonic()
        try:
            def wire():
                return of_write_with_retry(lambda: _proxy(lambda: post(**shared, **extra), client=client))
            result = await (claim.awire(wire) if claim is not None else wire())
        except Exception as e:
            from automations.send_mass_message import close_run_if_unsent
            from of_write import _may_have_sent
            await close_run_if_unsent(mass_run_id, e)
            if not _may_have_sent(e):
                _send_keys.pop(_key, None)
            raise
    # Best-effort: a funnel send without the reply-walker sends the opener and never checks replies; must not block the broadcast.
    if body.funnel_id and mass_run_id is not None:
        try:
            from funnels_api import ensure_funnel_walker
            await ensure_funnel_walker(account_id)
        except Exception:
            log.exception("funnel walker ensure failed (account=%s) — enable "
                          "Reply-walking in My Automations > Auto Funnel", account_id)
    if not _later:
        await _close_mass_run(
            account_id=account_id,
            employee_id=employee_id,
            mass_run_id=mass_run_id,
            text=body.text,
            price=body.price,
            result=result,
            recipient_ids=body.user_ids,
            scheduled=False,
        )
        queue_id = result.get("id") if isinstance(result, dict) else None
        if body.unsend_after_hours and queue_id:
            from automation_executor import enqueue_job
            run_at = datetime.utcnow() + timedelta(hours=body.unsend_after_hours)
            job_id = await enqueue_job(
                account_id, "unsend_messages",
                payload={"targets": [{"queue_id": int(queue_id),
                                      "mass_run_id": mass_run_id}]},
                run_at=run_at,
                created_by_employee_id=employee_id,
            )
            if isinstance(result, dict):
                result["_auto_unsend_at"] = run_at.isoformat() + "Z"
                result["_auto_unsend_job_id"] = job_id
    if mass_run_id is not None and isinstance(result, dict):
        result.setdefault("_mass_run_id", mass_run_id)
    if isinstance(result, dict) and (_answered_total or _skipped_answered):
        result["_skipped_already_answered"] = _answered_total or len(_skipped_answered)
        result["_skipped_already_answered_ids"] = _skipped_answered
    if isinstance(result, dict) and _asked_ids:
        result["_user_ids_kept"] = {"asked": _asked_ids, "kept": len(set(body.user_ids))}
    return result

class _EditQueuedMessageBody(BaseModel):
    """PUT /api/of/v2/messages/queue/{id}: a queued mass message saved in
    place. A schedule (`scheduled_date`) or `save_for_later` is required, so
    an edit can never send the message at once (that is Message now)."""
    text: str
    scheduled_date: str | None = None
    save_for_later: bool = False
    user_ids: list[int] = Field(default_factory=list)
    user_lists: list[str] = Field(default_factory=list)
    excluded_user_lists: list[str] = Field(default_factory=list)
    price: float = Field(0, ge=0)
    locked_text: bool = False
    media_files: list[int | dict] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    tagged_users: list[int] = Field(default_factory=list)


@router.post("/api/of/v2/messages/queue/later")
async def of_save_mass_for_later(request: Request, body: _MassScheduleBody = Body(...)):
    """A mass message saved for later (OF's Save for later: queued with no
    date). POST /messages/queue with `save_for_later` does the same; this route
    is what OF Manager calls, so a relay that predates `save_for_later` answers
    405 instead of ignoring the field and sending the message at once."""
    body.save_for_later = True
    body.scheduled_date = None
    return await of_send_or_schedule_mass(request, body)


@router.get("/api/of/v2/messages/queue/{queue_id:int}")
def of_queued_message(queue_id: int):
    """One queued mass message (scheduled or saved for later), as OF's Edit
    message loads it: GET /messages/queue/{id}?format=scheduled."""
    return _proxy(lambda: _get_client().queued_message(queue_id))


@router.put("/api/of/v2/messages/queue/{queue_id:int}")
def of_edit_queued_message(queue_id: int, body: _EditQueuedMessageBody = Body(...)):
    """Save a queued mass message in place (OF Manager's Edit message, from the
    Queue): OF's PUT /messages/queue/{id}. A new `scheduled_date` reschedules."""
    if not body.scheduled_date and not body.save_for_later:
        raise HTTPException(422, "an edited queued message needs scheduled_date or save_for_later")
    return _proxy(lambda: _get_client().edit_queued_message(
        queue_id, text=body.text, scheduled_date=body.scheduled_date,
        save_for_later=body.save_for_later and not body.scheduled_date,
        user_ids=body.user_ids, user_lists=body.user_lists,
        excluded_user_lists=body.excluded_user_lists, price=body.price,
        locked_text=body.locked_text, media_files=body.media_files,
        previews=body.previews, tagged_users=body.tagged_users,
    ))


@router.delete("/api/of/v2/messages/queue/{queue_id}")
async def of_cancel_scheduled(request: Request, queue_id: int):
    """Cancel a previously scheduled message or unsend a mass broadcast.

    Both code paths share OF's wire endpoint:
      • scheduled (future) → cancel before it fires
      • mass broadcast (past) → unsend from EVERY recipient (no window)

    On success we flip `is_canceled=True` in the local mass-broadcast
    cache so the Settings → Mass messages list reflects the new state
    without waiting for the next refresh.

    On a Fansly Creator this is ALSO the scheduled-POST cancel: the Fansly
    shim's `cancel_scheduled` is Fansly's `POST /post/scheduled/{id}/cancel`,
    so `queue_id` is a post id from `GET /api/of/v2/schedules` (the Fansly
    Manager's Scheduled Posts page, roadmap 8.1). The bookkeeping below then
    finds nothing to mark. Locked by test_fansly_cancel_scheduled_route.py."""
    import mass_broadcast_cache as cache
    resp = await asyncio.to_thread(_proxy, lambda: _get_client().cancel_scheduled(queue_id))
    try:
        account_id = _resolve_account_id(request)
    except Exception as e:
        log.warning("cancel bookkeeping skipped, account unresolved: %s", e)
        return resp

    try:
        await cache.mark_canceled(account_id, queue_id)
    except Exception as e:
        log.warning("mass_broadcast_cache mark_canceled failed: %s", e)
    try:
        from audiences import close_funnel_discovery_for_queue
        await close_funnel_discovery_for_queue(account_id, queue_id=queue_id)
    except Exception as e:
        log.warning("close_funnel_discovery failed queue_id=%s: %s", queue_id, e)
    try:
        # Mirror rows left live would re-seed as empty bubbles on each recipient's next chat open; purchasers and funnel follow-ups are spared.
        from messages import mark_queue_unsent
        await mark_queue_unsent(account_id, queue_id)
    except Exception as e:
        log.warning("queue unsend mirror flip failed queue_id=%s: %s", queue_id, e)
    return resp
