from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import automation_executor as ax
import media_cotag
import platforms
import send_ops
from attribution import write_outbound_attribution
from automation_registry import register
from job_queue import send_anchor
from side_effect_gate import send_refusal

log = logging.getLogger("of-relay.automation.scheduled_send")

_KIND = "scheduled_send"


@register(_KIND)
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    fan_id = payload.get("fan_id")
    text = str(payload.get("text") or "")
    media_files = payload.get("media_files") or []
    giphy_id = payload.get("giphy_id")

    if not fan_id or (not text.strip() and not media_files and not giphy_id):
        log.info("scheduled_send empty account=%s fan=%s — skip", account_id, fan_id)
        return {"status": "skipped", "reason": "empty", "fan_id": fan_id}

    auto_tag = str(payload.get("send_purpose") or "") != "manual"
    platform = platforms.for_account(account_id)
    would_cotag = bool(platform.backend and auto_tag and media_cotag.would_cotag(account_id, media_files))
    refused = send_refusal(platform, payload, would_cotag=would_cotag)
    if refused:
        log.info("scheduled_send refused account=%s fan=%s (%s)", account_id, fan_id, refused)
        return {"status": "skipped", "reason": refused, "fan_id": fan_id}

    price = float(payload.get("price") or 0)
    locked_text = bool(payload.get("locked_text"))
    previews = payload.get("previews") or []
    tagged_users = payload.get("tagged_users") or []
    employee_id = payload.get("sent_by_employee_id")

    # Human sends are stamped "manual" and bypass the fence; anything else enqueued into this kind is re-checked at fire time.
    import audience_include as _audiences
    allowed, why = await _audiences.check_at_fire(
        account_id, fan_id, kind=_KIND, payload=payload)
    if not allowed:
        log.info("scheduled_send audience-blocked account=%s fan=%s (%s)",
                 account_id, fan_id, why)
        return {"status": "skipped", "reason": f"audience:{why}", "fan_id": fan_id}
    purpose = "gated" if auto_tag else "manual"

    client = await asyncio.to_thread(ax._make_client, account_id)
    result = await ax.of_write_paced(
        account_id,
        lambda: send_ops.automated_sync(account_id, _KIND, fan_id, send_anchor(payload), lambda: client.send_message(
            fan_id,
            text,
            price=price,
            locked_text=locked_text,
            media_files=media_files,
            previews=previews,
            tagged_users=tagged_users,
            giphy_id=giphy_id,
            # Keys on who composed, not who fired: a deferred composer send must not name a co-performer the operator never picked.
            auto_tag=auto_tag,
        ), body=payload),
        send_purpose=purpose,
        # An automation run waits for a DM-rate slot; an operator run never does.
        dm=True,
    )

    msg_id = result.get("id") if isinstance(result, dict) else None
    if msg_id:
        # local import keeps this plugin's module import cheap
        from event_transcoder import _to_cents

        await write_outbound_attribution(
            account_id=account_id,
            fan_id=int(fan_id),
            message_id=int(msg_id),
            sent_by_employee_id=employee_id,
            body=str(result.get("text") or text),
            price_cents=_to_cents(price),
            created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
            automation_kind=None,
            emit_live=True,
        )
        try:
            # No fan lease (a human send always fires), but rest the fan like a manual send so automations yield; best-effort.
            await ax.start_fan_cooldown(account_id, int(fan_id))
        except Exception:
            log.warning("scheduled_send cooldown set failed account=%s fan=%s",
                        account_id, fan_id, exc_info=True)

    log.info("scheduled_send ok account=%s fan=%s msg=%s", account_id, fan_id, msg_id)
    return {"status": "ok" if msg_id else "sent_no_id", "fan_id": fan_id, "message_id": msg_id}
