from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
from attribution import write_outbound_attribution
from automation_registry import register
from db.engine import get_session
from db.models import Fan, Message, NudgeState
from job_queue import current_job_id
from side_effect_gate import live_check_fan
from ._common import bool_knob, send_dropping_bad_media
from .nudge_online import KIND, _compose_messages, _gate_skip_reason, _load_nudge_config

log = logging.getLogger("of-relay.automation.nudge_online_fire")


async def _get_state(account_id: str, fan_id: int) -> NudgeState | None:
    async with get_session() as s:
        return await s.get(NudgeState, (str(account_id), int(fan_id)))


async def _clear_pending(account_id: str, fan_id: int, *, job_id: int | None = None) -> None:
    only = () if job_id is None else (NudgeState.pending_job_id == job_id,)
    async with get_session() as s:
        await s.execute(
            update(NudgeState)
            .where(NudgeState.account_id == str(account_id),
                   NudgeState.fan_id == int(fan_id), *only)
            .values(pending_job_id=None, updated_at=datetime.utcnow())
        )


async def _fan_obj(account_id: str, fan_id: int) -> dict:
    async with get_session() as s:
        fan = await s.get(Fan, (str(account_id), int(fan_id)))
    return {
        "id": int(fan_id),
        "name": getattr(fan, "of_display_name", None) if fan else None,
        "username": getattr(fan, "of_username", None) if fan else None,
    }


async def _bump_after_send(
    account_id: str, fan_id: int, idx: int, slot: str, now: datetime,
) -> None:
    async with get_session() as s:
        st = await s.get(NudgeState, (str(account_id), int(fan_id)))
        last_in = (await s.execute(select(func.max(Message.created_at)).where(
            Message.account_id == str(account_id), Message.fan_id == int(fan_id),
            Message.direction == "in"))).scalar_one_or_none()
        prev_nudge = st.last_nudged_at if st else None
        replied = last_in is not None and (prev_nudge is None or last_in > prev_nudge)
        base_streak = 0 if replied else (st.no_reply_streak if st else 0)
        new_count = (st.nudge_count if st else 0) + 1
        new_streak = base_streak + 1
        common = {
            "last_nudged_at": now,
            "last_variation_idx": int(idx),
            "last_slot": str(slot),
            "pending_job_id": None,
            "nudge_count": new_count,
            "no_reply_streak": new_streak,
            "updated_at": now,
        }
        await s.execute(
            sqlite_insert(NudgeState)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    last_seen_online_at=now, **common)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"], set_=common)
        )


@register("nudge_online_fire")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    try:
        fan_id = int(payload.get("fan_id"))
    except (TypeError, ValueError):
        return {"sent": 0, "skipped": "bad_fan_id"}
    with_image = bool_knob(payload, "with_image", True)

    cfg = await _load_nudge_config(account_id)
    now = datetime.utcnow()

    if not cfg.get("enabled", True):
        await _clear_pending(account_id, fan_id)
        return {"sent": 0, "skipped": "disabled"}

    if reason := live_check_fan(account_id, KIND, fan_id):
        if (job_id := current_job_id()) is not None:
            await _clear_pending(account_id, fan_id, job_id=job_id)
        return {"sent": 0, "reason": reason}

    # A fire queued before the rule went OFF must not send.
    if (not payload.get("test_force")
            and await ax.enabled_rule_id(account_id, "nudge_online") is None):
        await _clear_pending(account_id, fan_id)
        return {"sent": 0, "skipped": "rule_disabled"}

    st = await _get_state(account_id, fan_id)
    recent = timedelta(minutes=cfg.get("online_recent_minutes", 5))
    if (st is None or st.last_seen_online_at is None
            or (now - st.last_seen_online_at) > recent):
        await _clear_pending(account_id, fan_id)
        return {"sent": 0, "skipped": "offline"}

    if not payload.get("test_force"):
        reason = await _gate_skip_reason(account_id, fan_id, cfg, now, at_fire=True)
        if reason:
            await _clear_pending(account_id, fan_id)
            return {"sent": 0, "skipped": reason}
        import audience_include as _audiences
        allowed, why = await _audiences.check_at_fire(
            account_id, fan_id, kind="nudge_online_fire", payload=payload)
        if not allowed:
            await _clear_pending(account_id, fan_id)
            return {"sent": 0, "skipped": f"audience:{why}"}

    if not await ax.acquire_fan_lease(account_id, fan_id, "nudge_online_fire"):
        await _clear_pending(account_id, fan_id)
        return {"sent": 0, "skipped": "locked"}

    idx = 0
    slot = ""
    sent = 0
    images = 0
    try:
        fan_obj = await _fan_obj(account_id, fan_id)
        msgs, slot = await _compose_messages(account_id, fan_id, cfg, fan_obj, st)
        if not msgs:
            await _clear_pending(account_id, fan_id)
            return {"sent": 0, "skipped": "empty"}
        client = await asyncio.to_thread(ax._make_client, account_id)
        for m in msgs:
            text, media = m["text"], m["media"]
            # This sender clears its latch and never retries, so a refused attachment must still deliver the text.
            outcome = await send_dropping_bad_media(client, fan_id, text, media,
                                                    log=log, send_purpose="gated")
            result = outcome.result
            msg_id = result.get("id") if isinstance(result, dict) else None
            if msg_id:
                await write_outbound_attribution(
                    account_id=account_id,
                    fan_id=int(fan_id),
                    message_id=int(msg_id),
                    sent_by_employee_id=None,
                    automation_kind="nudge_online",
                    body=str(result.get("text") or text),
                    price_cents=0,
                    created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
                    emit_live=True,
                )
            sent += 1
            if outcome.media_landed:
                images += 1
            idx = m.get("idx", idx)
        await _bump_after_send(account_id, fan_id, idx, slot, now)
    except Exception as e:
        await _clear_pending(account_id, fan_id)
        log.warning("nudge_fire_failed account=%s fan=%s", account_id, fan_id, exc_info=True)
        # Latch cleared above; never re-raise: a sender re-run risks a double message.
        return {"sent": 0, "skipped": "error", "error": repr(e)[:200]}
    finally:
        await ax.release_fan_lease(account_id, fan_id)

    return {
        "sent": sent,
        "fan_id": fan_id,
        "slot": slot,
        "variation_idx": idx,
        "image_attached": images,
    }
