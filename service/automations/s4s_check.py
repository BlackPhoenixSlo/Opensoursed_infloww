from __future__ import annotations

import asyncio
import html
import json
import logging
import re

import automation_executor as ax
import platforms
from automation_registry import register
from automations.s4s_post import _advertised, _agency
from db.engine import get_session
from db.models import Post, S4SRequest, S4SSlot
from s4s_media import slot_media_ids
from s4s_schedule_api import TAMPER_REASONS, move_slot

DELETED, ARCHIVED, EDITED = TAMPER_REASONS

log = logging.getLogger("of-relay.automation.s4s_check")


def _text(post: dict) -> str:
    raw = post.get("rawText") or post.get("text") or ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(raw))).split())


# One check before removal: a post archived then restored within the 24h is missed.
def tamper_reason(now: dict | None, then: dict, sent_text: str, sent_media: int) -> str | None:
    if now is None or now.get("isDeleted"):
        return DELETED
    if now.get("isArchived"):
        return ARCHIVED
    baseline = _text(then) or " ".join(sent_text.split())
    if _text(now) != baseline or ("media" in now and len(now["media"] or []) != sent_media):
        return EDITED
    return None


@register("s4s_check")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Check one posted slot's post. Returns a stats dict."""
    from of_client import OFAPIError, post_is_gone

    try:
        slot_id = int((payload or {}).get("slot_id"))
    except (TypeError, ValueError):
        return {"status": "skipped", "reason": "no_slot_id"}
    async with get_session() as s:
        slot = await s.get(S4SSlot, slot_id)
        if slot is None or slot.poster_account_id != str(account_id):
            return {"status": "skipped", "reason": "not_the_poster", "slot_id": slot_id}
        if slot.status != "posted" or slot.of_post_id is None:
            return {"status": "skipped", "reason": slot.status, "slot_id": slot_id}
        post = await s.get(Post, slot.post_id) if slot.post_id is not None else None
        if post is None or post.status == "deleted":
            return {"status": "skipped", "reason": "already_removed", "slot_id": slot_id}
        try:
            then = json.loads(post.raw_json or "{}")
        except ValueError:  # Auto Post cuts raw_json at 20,000 characters
            then = {}
        req = await s.get(S4SRequest, slot.request_id)
        sent_media = len(slot_media_ids(req, slot.poster_account_id)) if req is not None else 0
        of_post_id, sent_text = slot.of_post_id, _advertised(slot.text)

    backend = platforms.for_account(str(account_id)).backend
    read_errors = (OFAPIError,) if backend is None else (OFAPIError, backend.APIError)
    client = await asyncio.to_thread(ax._make_client, str(account_id))
    try:
        now = await asyncio.to_thread(client.get_post, of_post_id)
    except read_errors as e:
        gone = isinstance(e, OFAPIError) and post_is_gone(e)
        if not gone:
            log.warning("s4s_check: slot %s read failed, inconclusive", slot_id, exc_info=True)
        now = None if gone else {}
    if now is not None and not now.get("id"):
        return {"status": "error", "reason": "inconclusive", "slot_id": slot_id}
    reason = tamper_reason(now, then if isinstance(then, dict) else {}, sent_text, sent_media)
    if reason is None:
        return {"status": "ok", "slot_id": slot_id, "tamper": None}

    agency = await _agency(str(account_id))
    async with get_session() as s:
        moved = await move_slot(s, slot, "posted", {"status": "failed", "reason": reason}, action="s4s.slot_tamper",
                                audit={"actor": "system", "reason": reason}, agency_user_id=agency, employee_id=None)
    return {"status": "ok", "slot_id": slot_id, "tamper": reason, "moved": moved}
