from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

import automation_executor as ax
from automation_registry import register
from automations import auto_posts
from db.engine import get_session
from db.models import Post, S4SProfile, S4SSlot
from s4s_api import live_posting
from s4s_media import MediaMissing, fetch_to, prune, slot_vault_ids
from s4s_requests_api import _linked
from s4s_schedule_api import claim_slot, move_slot
from tenant_keys import owners_of

log = logging.getLogger("of-relay.automation.s4s_post")

HOURS_TO_LIVE = 24
MISSED_AFTER = timedelta(hours=24)
DONE = ("posted", "canceled", "failed")
CHECK_BEFORE_REMOVAL = timedelta(minutes=30)


async def _copy(account_id: str, partner_id: str, vault_ids: list[int]) -> list | str:
    client = await asyncio.to_thread(ax._make_client, account_id)
    out: list = []
    with tempfile.TemporaryDirectory(prefix="s4s_") as tmp:
        for vid in vault_ids:
            try:
                p = await asyncio.to_thread(fetch_to, partner_id, vid, Path(tmp))
            except MediaMissing:
                log.warning("s4s_post: vault item %s of account=%s is gone", vid, partner_id)
                return "media_missing"
            except Exception:  # noqa: BLE001 — the slot ends `media_fetch_failed`; the error is logged
                log.warning("s4s_post: vault item %s of account=%s could not be read", vid, partner_id, exc_info=True)
                return "media_fetch_failed"
            try:
                up = await ax.of_write_paced(account_id, lambda p=p: client.upload_media(p),
                                             send_purpose="not_fan_dm")
            except Exception:  # noqa: BLE001 — the slot ends `upload_failed`; the error is logged, not stored
                log.warning("s4s_post: upload of %s failed for account=%s", p.name, account_id, exc_info=True)
                return "upload_failed"
            finally:
                p.unlink(missing_ok=True)
            if not up.get("ready"):
                log.warning("s4s_post: upload of %s not ready for account=%s: %s", p.name, account_id,
                            up.get("note"))
                return "upload_failed"
            out.extend(up["send_with"])
    return out


async def _prune() -> None:
    try:
        await prune()
    except Exception:  # noqa: BLE001 — a cleanup failure never changes a slot's outcome
        log.warning("s4s_post: S4S media prune failed", exc_info=True)


AD_TAG = "#advertisement"


def _advertised(text: str) -> str:
    body = text.rstrip()
    return body if body.endswith(AD_TAG) else f"{body}\n{AD_TAG}"


async def _agency(account_id: str) -> str | None:
    return next(iter(await owners_of(account_id)), None)


async def _cancel_reason(s, slot: S4SSlot, now: datetime) -> str | None:
    if not live_posting():
        return "live posting off"
    ids = {slot.poster_account_id, slot.partner_account_id}
    opted = set((await s.execute(
        select(S4SProfile.account_id).where(S4SProfile.account_id.in_(ids), S4SProfile.opted_in.is_(True))
    )).scalars().all())
    linked = await _linked(s, ids)
    if slot.poster_account_id not in opted:
        return "opted_out"
    if slot.poster_account_id not in linked:
        return "no_agency"
    if slot.partner_account_id not in opted or slot.partner_account_id not in linked:
        return "partner_opted_out"
    if now - slot.slot_at >= MISSED_AFTER:
        return "missed"
    return None


def _when(iso: str) -> datetime:
    return datetime.fromisoformat(iso.rstrip("Z"))


async def _fail(slot: S4SSlot, reason: str, agency: str | None) -> None:
    async with get_session() as s:
        await move_slot(s, slot, "posting", {"status": "failed", "reason": reason[:500]}, action="s4s.slot_fail",
                        audit={"actor": "system", "reason": reason[:500]}, agency_user_id=agency, employee_id=None)


@register("s4s_post")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Post one S4S slot, or end it with a reason. Returns a stats dict."""
    try:
        return await _run(account_id, payload, run_id=run_id)
    finally:
        await _prune()


async def _run(account_id: str, payload: dict, *, run_id: int) -> dict:
    try:
        slot_id = int((payload or {}).get("slot_id"))
    except (TypeError, ValueError):
        return {"status": "skipped", "reason": "no_slot_id"}
    now = datetime.utcnow()
    async with get_session() as s:
        slot = await s.get(S4SSlot, slot_id)
        if slot is None:
            return {"status": "skipped", "reason": "no_slot", "slot_id": slot_id}
        if slot.poster_account_id != str(account_id):
            log.warning("s4s_post: slot %s belongs to another poster than account=%s", slot_id, account_id)
            return {"status": "skipped", "reason": "not_the_poster", "slot_id": slot_id}
        if slot.status in DONE:
            return {"status": "skipped", "reason": slot.status, "slot_id": slot_id}
        agency = await _agency(str(account_id))
        if slot.status == "posting":
            await move_slot(s, slot, "posting", {"status": "failed", "reason": "interrupted_mid_post"},
                            action="s4s.slot_fail", audit={"actor": "system", "reason": "interrupted_mid_post"},
                            agency_user_id=agency, employee_id=None)
            return {"status": "skipped", "reason": "interrupted_mid_post", "slot_id": slot_id}
        reason = await _cancel_reason(s, slot, now)
        if reason is not None:
            await move_slot(s, slot, "scheduled", {"status": "canceled", "reason": reason}, action="s4s.slot_cancel",
                            audit={"actor": "system", "reason": reason}, agency_user_id=agency, employee_id=None)
            return {"status": "skipped", "reason": reason, "slot_id": slot_id}
        try:
            vault_ids = await slot_vault_ids(s, slot)
        except MediaMissing:
            await move_slot(s, slot, "scheduled", {"status": "failed", "reason": "media_missing"},
                            action="s4s.slot_fail", audit={"actor": "system", "reason": "media_missing"},
                            agency_user_id=agency, employee_id=None)
            return {"status": "error", "reason": "media_missing", "slot_id": slot_id}
        # Once claimed, a crash leaves `posting`, never a second post.
        if not await claim_slot(s, slot, "scheduled", {"status": "posting"}):
            return {"status": "skipped", "reason": "claimed_elsewhere", "slot_id": slot_id}
        text = _advertised(slot.text)

    item: dict = {"text": text, "hours_to_live": HOURS_TO_LIVE}
    if vault_ids:
        claims = await _copy(str(account_id), slot.partner_account_id, vault_ids)
        if isinstance(claims, str):
            await _fail(slot, claims, agency)
            return {"status": "error", "reason": claims, "slot_id": slot_id}
        item["media_claims"] = claims
    try:
        res = await auto_posts.run(str(account_id), {"posts": [item]}, run_id=run_id)
    except Exception as e:
        await _fail(slot, repr(e), agency)
        raise
    if res["status"] != "ok":
        reason = str(res.get("reason") or res["status"])
        await _fail(slot, reason, agency)
        return {"status": "error", "reason": reason, "slot_id": slot_id}

    post_id, of_post_id = int(res["local_post_id"]), res["of_post_id"]
    async with get_session() as s:
        posted_at = (await s.get(Post, post_id)).posted_at
        moved = await move_slot(
            s, slot, "posting",
            {"status": "posted", "post_id": post_id, "of_post_id": of_post_id, "posted_at": posted_at,
             "remove_at": _when(res["delete_at"])},
            action="s4s.slot_post", audit={"actor": "system", "post_id": post_id, "of_post_id": of_post_id},
            agency_user_id=agency, employee_id=None,
        )
    if not moved:
        log.warning("s4s_post: slot %s left `posting` during its post (post_id=%s)", slot_id, post_id)
        return {"status": "error", "reason": "slot_left_posting", "slot_id": slot_id, "post_id": post_id}
    await ax.enqueue_job(str(account_id), "s4s_check", payload={"slot_id": slot_id},
                         run_at=_when(res["delete_at"]) - CHECK_BEFORE_REMOVAL)
    return {"status": "ok", "slot_id": slot_id, "post_id": post_id, "of_post_id": of_post_id,
            "remove_at": res["delete_at"]}
