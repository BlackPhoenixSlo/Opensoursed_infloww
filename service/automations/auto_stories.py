from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import automation_executor as ax
import media_cotag
from automation_registry import register
from ._common import bool_knob
from automations._pools import has_media_source, pick_media

log = logging.getLogger("of-relay.automation.auto_stories")

# The vault dupe is hash-findable only after OF finishes transcoding the upload.
_HIDE_DELAY_MINUTES = 15


def _pos_float(raw: object) -> float | None:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        return float(raw)
    return None


def _pos_int(raw: object, default: int) -> int:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 1:
        return int(raw)
    return default


# create_story rejects a bare vault id: resolve to the full-res non-DRM CDN url, skip urlless/DRM items.
def _photo_url(client, media_id: int) -> str | None:
    try:
        it = client.vault_media_by_id(int(media_id))
    except Exception:
        log.warning("auto_stories: vault_media_by_id failed id=%r", media_id, exc_info=True)
        return None
    full = ((it.get("files") or {}).get("full") or {}) if isinstance(it, dict) else {}
    url = full.get("url")
    if url and not full.get("drm"):
        return url
    return None


@register("auto_stories")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Post `per_run` random stories from a media POOL, scheduling each delete.

    The pool mirrors auto_posts: explicit `media_files` ids ∪ a vault folder,
    with `media_count` (falls back to `per_run`) sampled per fire. The legacy
    single-folder shape (`folder_id`) still works — it maps onto the pool's
    `media_folder_id`."""
    payload = payload or {}

    folder_id = payload.get("media_folder_id")
    if folder_id is None:
        folder_id = payload.get("folder_id")
    try:
        folder_id = int(folder_id) if folder_id is not None else None
    except (TypeError, ValueError):
        folder_id = None

    per_run = _pos_int(payload.get("per_run"), 1)
    count = _pos_int(payload.get("media_count"), 0) or per_run
    hours_to_live = _pos_float(payload.get("hours_to_live"))
    watermark_text = payload.get("watermark_text") or None
    remove_dupe = bool_knob(payload, "remove_vault_dupe", True)

    pool_spec = {
        "media_files": payload.get("media_files"),
        "media_folder_id": folder_id,
        "media_count": count,
    }
    if not has_media_source(pool_spec):
        return {"status": "skipped", "reason": "no_media_source"}

    client = await asyncio.to_thread(ax._make_client, account_id)

    picked_ids = await asyncio.to_thread(pick_media, pool_spec, client)
    resolved: list[tuple[int, str]] = []
    for mid in picked_ids:
        url = await asyncio.to_thread(_photo_url, client, mid)
        if url:
            resolved.append((mid, url))
    if not resolved:
        return {"status": "skipped", "reason": "no_usable_photos",
                "folder_id": folder_id}

    if payload.get("dry_run"):
        return {
            "dry_run": True, "folder_id": folder_id,
            "would_post": [mid for mid, _ in resolved],
            "remove_vault_dupe": remove_dupe,
            "posted": 0,
        }

    employee_id = None
    try:
        from employees import get_automation_employee_id
        employee_id = await get_automation_employee_id()
    except Exception:
        log.debug("automation employee lookup failed; attribution NULL", exc_info=True)

    posted: list[dict] = []
    failed = 0
    now = datetime.utcnow()
    for mid, url in resolved:
        # of_client can't auto-tag a story (OF re-uploads, no vault id in the body), so the release-form mention is decided here.
        mention = media_cotag.story_mention(account_id, [mid])
        try:
            result = await asyncio.to_thread(
                lambda u=url, mn=mention: client.post_story_from_url(
                    u, watermark_text=watermark_text, mention=mn,
                    return_upload=remove_dupe)
            )
        except Exception as e:  # noqa: BLE001 — one bad pick shouldn't strand the rest
            failed += 1
            log.warning("auto_stories: post failed vault=%s: %s", mid, e)
            continue
        if remove_dupe and isinstance(result, dict) and "story" in result:
            story = result.get("story")
            upload = result.get("upload") or {}
        else:
            story, upload = result, {}
        story_id = story.get("id") if isinstance(story, dict) else None
        entry = {"vault_id": mid, "story_id": story_id}

        hide_tgt = None
        if remove_dupe and upload.get("md5") and upload.get("size"):
            hide_tgt = {"hide_upload": {
                "md5": upload["md5"],
                "size": int(upload["size"]),
                # the source id is excluded so the original is never hidden.
                "exclude_ids": [int(mid)],
            }}

        if story_id and hours_to_live:
            delete_at = now + timedelta(hours=hours_to_live)
            targets: list[dict] = [{"story_id": int(story_id)}]
            if hide_tgt:
                targets.append(hide_tgt)
            entry["delete_job_id"] = await ax.enqueue_job(
                account_id, "unsend_messages",
                payload={"targets": targets},
                run_at=delete_at,
                created_by_employee_id=employee_id,
            )
            entry["delete_at"] = delete_at.isoformat() + "Z"
        elif hide_tgt:
            hide_at = now + timedelta(minutes=_HIDE_DELAY_MINUTES)
            entry["hide_job_id"] = await ax.enqueue_job(
                account_id, "unsend_messages",
                payload={"targets": [hide_tgt]},
                run_at=hide_at,
                created_by_employee_id=employee_id,
            )
            entry["hide_at"] = hide_at.isoformat() + "Z"
        posted.append(entry)

    return {
        "status": "ok" if posted else "error",
        "folder_id": folder_id,
        "posted": len(posted),
        "failed": failed,
        "stories": posted,
        "hours_to_live": hours_to_live,
    }
