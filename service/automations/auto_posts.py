from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta

import account_page
import automation_executor as ax
import send_tripwire
from automation_registry import register
from automations._pools import has_media_source, pick_media, pick_text
from db.engine import get_session
from db.models import Post

log = logging.getLogger("of-relay.automation.auto_posts")


def _int_list(raw: object) -> list[int]:
    out: list[int] = []
    if isinstance(raw, list):
        for v in raw:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
    return out


def _pos_float(raw: object) -> float | None:
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return None


def _to_cents(price: object) -> int:
    try:
        return int(round(float(price) * 100))
    except (TypeError, ValueError):
        return 0


@register("auto_posts")
# Not fan-scoped and no LLM spend, so no fan lease or account_spend_lock.
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Post the first item of the queue, schedule its auto-delete, and drip the
    rest. Returns a stats dict (lands in `automation_runs.stats_json`)."""
    payload = payload or {}
    posts = payload.get("posts") or []
    if not isinstance(posts, list) or not posts:
        return {"status": "skipped", "reason": "no_posts"}

    if payload.get("dry_run"):
        plan = [
            {
                "text": (pick_text(p))[:80] if isinstance(p, dict) else "",
                "text_variants": (len(p.get("texts")) if isinstance(p, dict) and isinstance(p.get("texts"), list) else 1),
                "price": (p.get("price") or 0) if isinstance(p, dict) else 0,
                "media_pool": len(_int_list(p.get("media_files"))) if isinstance(p, dict) else 0,
                "media_folder_id": (p.get("media_folder_id") if isinstance(p, dict) else None),
                "media_count": (p.get("media_count") or 1) if isinstance(p, dict) else 1,
                "preview_pool": len(_int_list(p.get("preview_media_files"))) if isinstance(p, dict) else 0,
                "preview_media_folder_id": (p.get("preview_media_folder_id") if isinstance(p, dict) else None),
                "preview_media_count": (p.get("preview_media_count") or 1) if isinstance(p, dict) else 1,
                "hours_to_live": _pos_float(p.get("hours_to_live")) if isinstance(p, dict) else None,
                "delay_minutes": (_pos_float(p.get("delay_minutes")) or 0) if isinstance(p, dict) else 0,
            }
            for p in posts
        ]
        paid_page = await account_page.is_paid_page(account_id)
        for p in plan:
            p["skipped_reason"] = (account_page.PAID_PAGE_SKIP
                                   if paid_page and (p.get("price") or 0) > 0 else None)
        return {
            "dry_run": True, "posts": len(posts), "plan": plan, "posted": 0,
            "paid_page": paid_page,
            "resend_after_hours": _pos_float(payload.get("resend_after_hours")),
            "resend_count": int(payload.get("resend_count") or 0),
        }

    send_tripwire.check("create_post")
    spec = posts[0] if isinstance(posts[0], dict) else {}
    rest = posts[1:]

    resend_after = _pos_float(payload.get("resend_after_hours"))
    resend_count = int(payload.get("resend_count") or 0)
    original_posts = payload.get("_original_posts")
    if original_posts is None and resend_count > 0:
        original_posts = posts
    cycle = {
        "resend_after_hours": resend_after,
        "resend_count": resend_count,
        "_original_posts": original_posts,
    }

    text = pick_text(spec)
    price = spec.get("price") or 0
    hours_to_live = _pos_float(spec.get("hours_to_live"))

    if not text and not has_media_source(spec):
        log.warning("auto_posts: empty post (no text, no media) — skipping item")
        remaining = await _drip_rest(account_id, rest, None, cycle)
        return {"status": "skipped", "reason": "empty_post", "remaining": remaining}

    # A paid-subscription page has no paid-post lane: drop the priced item, never re-price to 0 (would give the locked set away).
    if price and price > 0 and await account_page.is_paid_page(account_id):
        log.info("auto_posts: account=%s is a paid-subscription page — dropping the "
                 "priced item (no paid-post lane on OF)", account_id)
        remaining = await _drip_rest(account_id, rest, None, cycle)
        return {"status": "skipped", "reason": account_page.PAID_PAGE_SKIP,
                "remaining": remaining}

    employee_id: int | None = None
    try:
        from employees import get_automation_employee_id
        employee_id = await get_automation_employee_id()
    except Exception:
        log.debug("automation employee lookup failed; post attribution NULL", exc_info=True)

    client = await asyncio.to_thread(ax._make_client, account_id)
    media_files = await asyncio.to_thread(pick_media, spec, client)
    if not text and not media_files:
        log.warning("auto_posts: media pool resolved empty + no text — skipping item")
        remaining = await _drip_rest(account_id, rest, employee_id, cycle)
        return {"status": "skipped", "reason": "empty_after_resolve", "remaining": remaining}

    # preview ids are added to media_files so previews is always a subset (OF unlocks only those).
    previews: list[int] = []
    if price and price > 0:
        preview_spec = {
            "media_files": spec.get("preview_media_files"),
            "media_folder_id": spec.get("preview_media_folder_id"),
            "media_count": spec.get("preview_media_count"),
        }
        if has_media_source(preview_spec):
            preview_files = await asyncio.to_thread(pick_media, preview_spec, client)
            for pid in preview_files:
                if pid not in media_files:
                    media_files.append(pid)
            previews = [p for p in preview_files if p in media_files]

    # Same shuffled list goes to create_post and the posts row so OF and our record never diverge.
    if len(media_files) > 1:
        random.shuffle(media_files)

    claims = spec.get("media_claims") if isinstance(spec.get("media_claims"), list) else []
    media_files = media_files + claims

    # OF rejects a priced text-only post.
    if price and price > 0 and not media_files:
        log.warning("auto_posts: paid post resolved to no media — skipping item")
        remaining = await _drip_rest(account_id, rest, employee_id, cycle)
        return {"status": "skipped", "reason": "paid_no_media", "remaining": remaining}

    # Spaced after the account's previous OF write so drips never crowd OF's 10s window.
    result = await ax.of_write_paced(
        account_id,
        lambda: client.create_post(
            text=text, media_files=media_files, price=price, previews=previews,
        ),
        send_purpose="not_fan_dm",
    )
    of_post_id = result.get("id") if isinstance(result, dict) else None
    if of_post_id is None:
        log.warning("auto_posts: create_post returned no id (result=%r)", result)
        remaining = await _drip_rest(account_id, rest, employee_id, cycle)
        return {"status": "error", "reason": "no_post_id", "remaining": remaining}
    of_post_id = int(of_post_id)

    now = datetime.utcnow()

    async with get_session() as s:
        row = Post(
            account_id=str(account_id),
            of_post_id=of_post_id,
            status="posted",
            text=text,
            # OF /posts price is dollars; stored as cents.
            price_cents=_to_cents(price),
            # A convert claim has no id until OF mints one: read the ids back.
            media_ids=json.dumps(ax._media_ids(result.get("media")) if claims else media_files),
            posted_at=now,
            created_by_employee_id=employee_id,
            raw_json=json.dumps(result, default=str)[:20000],
        )
        s.add(row)
        await s.flush()
        local_post_id = int(row.id)

    delete_job_id: int | None = None
    delete_at_iso: str | None = None
    if hours_to_live:
        delete_at = now + timedelta(hours=hours_to_live)
        delete_job_id = await ax.enqueue_job(
            account_id, "unsend_messages",
            payload={"targets": [{"post_id": of_post_id, "local_post_id": local_post_id}]},
            run_at=delete_at,
            created_by_employee_id=employee_id,
        )
        delete_at_iso = delete_at.isoformat() + "Z"

    remaining = await _drip_rest(account_id, rest, employee_id, cycle)

    resend_job_id: int | None = None
    resend_at_iso: str | None = None
    if remaining == 0 and resend_count > 0 and resend_after and original_posts:
        resend_at = now + timedelta(hours=resend_after)
        # Drip + resend ride enqueue_followup so switching the rule off ends the list; the auto-delete deliberately does not.
        resend_job_id = await ax.enqueue_followup(
            account_id, "auto_posts",
            payload={
                "posts": original_posts,
                "resend_after_hours": resend_after,
                "resend_count": resend_count - 1,
                "_original_posts": original_posts,
            },
            run_at=resend_at,
            created_by_employee_id=employee_id,
        )
        resend_at_iso = resend_at.isoformat() + "Z"

    return {
        "status": "ok",
        "posted": 1,
        "of_post_id": of_post_id,
        "local_post_id": local_post_id,
        "delete_job_id": delete_job_id,
        "delete_at": delete_at_iso,
        "remaining": remaining,
        "resend_job_id": resend_job_id,
        "resend_at": resend_at_iso,
        "resends_left": max(resend_count - 1, 0) if resend_count > 0 else 0,
    }


async def _drip_rest(
    account_id: str, rest: list, employee_id: int | None, cycle: dict | None = None
) -> int:
    if not rest:
        return 0
    head = rest[0] if isinstance(rest[0], dict) else {}
    delay_min = _pos_float(head.get("delay_minutes")) or 0
    run_at = datetime.utcnow() + timedelta(minutes=delay_min)
    drip_payload: dict = {"posts": rest}
    if cycle and cycle.get("resend_count", 0) > 0 and cycle.get("resend_after_hours"):
        drip_payload["resend_after_hours"] = cycle["resend_after_hours"]
        drip_payload["resend_count"] = cycle["resend_count"]
        drip_payload["_original_posts"] = cycle["_original_posts"]
    job_id = await ax.enqueue_followup(
        account_id, "auto_posts",
        payload=drip_payload,
        run_at=run_at,
        created_by_employee_id=employee_id,
    )
    return len(rest) if job_id is not None else 0
