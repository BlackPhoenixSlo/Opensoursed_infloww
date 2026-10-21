"""service/automations/s4s_check.py — the S4S tamper check: before a posted
slot's 24h removal, read its post on the poster's own account and end the
slot `failed` if the post was deleted, archived or edited (Infloww's failure
reasons `s4s0133`–`s4s0145`; ADR-0015).

`s4s_post` queues one `s4s_check` job per posted slot on the poster's
account, 30 minutes before Auto Post's `delete_at`, payload `{"slot_id"}`.
This run makes one read-only OnlyFans call, `get_post(of_post_id)`, with the
poster's own session, and no write: the unsend job still removes the post
on time whatever this finds. It does nothing to a slot that is not `posted`,
that another account's job names, or whose post our own unsend already
removed (`posts.status` `deleted`). Otherwise:

  - OF answers 404 or 410 (`post_is_gone`), or the post reads `isDeleted` → `post_deleted`;
  - the post reads `isArchived` → `post_archived`;
  - its text differs from what OF returned when the post was created (Auto
    Post's `posts.raw_json`, else the slot's text as posted, `_advertised`), or its media count
    from the files the slot sent (its request's snapshot, `slot_media_ids`)
    → `post_edited`;

and the slot moves `posted` → `failed` with that reason (`move_slot`,
audited as `s4s.slot_tamper`). Any other error is inconclusive: the slot is
left as it is and the run reports it.

ASSUMPTION: one check shortly before removal is enough: a deleted or edited
post stays so, and a post archived and restored within the 24h is missed.
Rung 4 (one read per slot). Overturned by an owner wanting the post polled.
ASSUMPTION: "edited" compares OF's own `rawText` (else `text`) with tags
stripped and whitespace collapsed, against the same field of the create
response, and counts media against what was sent, not the create response
(which may list fewer while upload claims still convert). Rung 5 (no live
capture of an edited post). Overturned by a live capture showing OF rewrites
untouched posts.

Self-registers via `@register("s4s_check")` on import.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re

import automation_executor as ax
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


def tamper_reason(now: dict | None, then: dict, sent_text: str, sent_media: int) -> str | None:
    """The reason `now` (None: OF says it is gone) is not the post that was
    sent, or None. Text is compared with the create response `then`, else
    `sent_text`; the media count with `sent_media`, when `now` lists media."""
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
        sent_media = len(slot_media_ids(req, slot)) if req is not None else 0
        of_post_id, sent_text = slot.of_post_id, _advertised(slot.text)

    client = await asyncio.to_thread(ax._make_client, str(account_id))
    try:
        now = await asyncio.to_thread(client.get_post, of_post_id)
    except OFAPIError as e:
        if not post_is_gone(e):
            log.warning("s4s_check: slot %s read failed, inconclusive", slot_id, exc_info=True)
            return {"status": "error", "reason": "inconclusive", "slot_id": slot_id}
        now = None
    reason = tamper_reason(now, then if isinstance(then, dict) else {}, sent_text, sent_media)
    if reason is None:
        return {"status": "ok", "slot_id": slot_id, "tamper": None}

    agency = await _agency(str(account_id))
    async with get_session() as s:
        moved = await move_slot(s, slot, "posted", {"status": "failed", "reason": reason}, action="s4s.slot_tamper",
                                audit={"actor": "system", "reason": reason}, agency_user_id=agency, employee_id=None)
    return {"status": "ok", "slot_id": slot_id, "tamper": reason, "moved": moved}
