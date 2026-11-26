from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import automation_executor as ax
from automation_registry import register
from automations._pools import has_media_source, pick_media, pick_text
import platforms
from side_effect_gate import PLATFORM_LACKS_PREFIX

log = logging.getLogger("of-relay.automation.mass_premade")

_SEND_KEYS = (
    "text", "media_files", "previews", "price", "online_only", "filters",
    "included_users", "excluded_users", "user_lists", "excluded_user_lists",
    "list_ids", "exclude_list_ids", "funnel_id", "funnel_name", "funnel",
    "recent_chat_hours", "recent_chat_limit",
    "exclude_replied_hours", "exclude_inbound_hours", "exclude_last_chat_hours",
    "unread_limit",
)


def _pos_float(raw: object) -> float | None:
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return None


def _paid(raw: object) -> bool:
    try:
        return float(raw or 0) > 0
    except (TypeError, ValueError):
        return False


@register("mass_premade")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Send the first message of the queue, schedule its unsend, and re-enqueue
    for the resend / the rest of the list. Returns a stats dict."""
    payload = payload or {}
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return {"status": "skipped", "reason": "no_messages"}

    if payload.get("dry_run"):
        plan = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            plan.append({
                "text": (pick_text(m))[:80],
                "text_variants": len(m.get("texts")) if isinstance(m.get("texts"), list) else 1,
                "media_pool": len(m.get("media_files") or []),
                "media_folder_id": m.get("media_folder_id"),
                "media_count": m.get("media_count") or 1,
                "online_only": bool(m.get("online_only")),
                "included_users": list(m.get("included_users") or []),
                "excluded_users": list(m.get("excluded_users") or []),
                "user_lists": list(m.get("user_lists") or []),
                "excluded_user_lists": list(m.get("excluded_user_lists") or []),
                "list_ids": list(m.get("list_ids") or []),
                "exclude_list_ids": list(m.get("exclude_list_ids") or []),
                "exclude_replied_hours": _pos_float(m.get("exclude_replied_hours")),
                "exclude_inbound_hours": _pos_float(m.get("exclude_inbound_hours")),
                "recent_chat_hours": _pos_float(m.get("recent_chat_hours")),
                "unread_limit": int(m.get("unread_limit") or 0) or None,
                "unsend_after_hours": _pos_float(m.get("unsend_after_hours")),
                "resend_after_hours": _pos_float(m.get("resend_after_hours")),
                "resend_count": int(m.get("resend_count") or 0),
                "delay_minutes": _pos_float(m.get("delay_minutes")) or 0,
            })
        return {"dry_run": True, "messages": len(messages), "plan": plan, "sent": 0}

    if platforms.refusal_for_account(account_id, "send_mass_message"):
        return {"status": "skipped", "reason": f"{PLATFORM_LACKS_PREFIX}send_mass_message"}

    spec = messages[0] if isinstance(messages[0], dict) else {}
    rest = messages[1:]

    text = pick_text(spec)
    client = (
        await asyncio.to_thread(ax._make_client, account_id)
        if spec.get("media_folder_id") is not None else None
    )
    media = await asyncio.to_thread(pick_media, spec, client)
    # Fail closed: a priced mass with unreadable media would go out with nothing to lock.
    if not media and has_media_source(spec) and _paid(spec.get("price")):
        log.warning("mass_premade: paid mass with no media (folder=%r) — not sent, draining rest",
                    spec.get("media_folder_id"))
        remaining = await _drip_rest(account_id, rest)
        return {"status": "skipped", "reason": "paid_no_media", "remaining": remaining}

    from automations.send_mass_message import run as send_mass_run
    send_payload = {k: spec[k] for k in _SEND_KEYS if k in spec}
    send_payload["text"] = text
    send_payload["media_files"] = media
    send_payload["automation_kind"] = "mass_premade"
    if payload.get("send_anchor"):
        send_payload["send_anchor"] = payload["send_anchor"]
    res = await send_mass_run(account_id, send_payload, run_id=run_id)

    if res.get("status") not in (None, "ok"):
        log.warning("mass_premade: send not sent (%s) — draining rest", res.get("reason"))
        remaining = await _drip_rest(account_id, rest)
        return {"status": res["status"], "reason": res.get("reason"), "remaining": remaining}

    queue_id = res.get("queue_id")
    mass_run_id = res.get("mass_run_id")
    now = datetime.utcnow()

    unsend_job_id: int | None = None
    resend_job_id: int | None = None
    remaining: int | None = None
    try:
        unsend_at_iso: str | None = None
        unsend_after = _pos_float(spec.get("unsend_after_hours"))
        if unsend_after and queue_id is not None:
            unsend_at = now + timedelta(hours=unsend_after)
            # Plain enqueue_job, not enqueue_followup: a rule switched off still takes its sent mass down.
            unsend_job_id = await ax.enqueue_job(
                account_id, "unsend_messages",
                payload={"targets": [{"queue_id": int(queue_id), "mass_run_id": mass_run_id}]},
                run_at=unsend_at,
            )
            unsend_at_iso = unsend_at.isoformat() + "Z"
        elif unsend_after and queue_id is None:
            log.warning("mass_premade: unsend_after set but OF returned no queue id — no auto-unsend")

        resend_at_iso: str | None = None
        resend_count = int(spec.get("resend_count") or 0)
        resend_after = _pos_float(spec.get("resend_after_hours"))
        if resend_count > 0 and resend_after:
            resend_spec = {**spec, "resend_count": resend_count - 1}
            resend_at = now + timedelta(hours=resend_after)
            resend_job_id = await ax.enqueue_followup(
                account_id, "mass_premade",
                payload={"messages": [resend_spec]},
                run_at=resend_at,
            )
            resend_at_iso = resend_at.isoformat() + "Z"

        remaining = await _drip_rest(account_id, rest)
    # The broadcast is out: a failure from here parks the job, never resent, so unenqueued legs are lost.
    except BaseException:
        log.warning("mass_premade_followons_dropped account=%s run_id=%s mass_run=%s "
                    "unsend=%s resend=%s rest=%s (unsend %sh, resends %s, rest %d message(s); "
                    "the broadcast went out, the job parks)", account_id, run_id, mass_run_id,
                    unsend_job_id, resend_job_id, remaining,
                    spec.get("unsend_after_hours"), spec.get("resend_count") or 0, len(rest))
        raise

    return {
        "status": "ok",
        "sent": 1,
        "queue_id": queue_id,
        "mass_run_id": mass_run_id,
        "recipients": res.get("recipients"),
        "unsend_job_id": unsend_job_id,
        "unsend_at": unsend_at_iso,
        "resend_job_id": resend_job_id,
        "resend_at": resend_at_iso,
        "resends_left": max(resend_count - 1, 0) if resend_count > 0 else 0,
        "remaining": remaining,
    }


async def _drip_rest(account_id: str, rest: list) -> int:
    if not rest:
        return 0
    head = rest[0] if isinstance(rest[0], dict) else {}
    delay_min = _pos_float(head.get("delay_minutes")) or 0
    run_at = datetime.utcnow() + timedelta(minutes=delay_min)
    job_id = await ax.enqueue_followup(
        account_id, "mass_premade",
        payload={"messages": rest},
        run_at=run_at,
    )
    return len(rest) if job_id is not None else 0
