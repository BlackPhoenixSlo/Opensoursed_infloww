from __future__ import annotations

import logging
import random

log = logging.getLogger("of-relay.automation.pools")


def int_list(raw: object) -> list[int]:
    out: list[int] = []
    if isinstance(raw, list):
        for v in raw:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
    return out


def pick_text(item: dict) -> str:
    texts = item.get("texts")
    if isinstance(texts, list):
        opts = [t.strip() for t in texts if isinstance(t, str) and t.strip()]
        if opts:
            return random.choice(opts)
    return (item.get("text") or "").strip()


def has_media_source(item: dict) -> bool:
    return bool(int_list(item.get("media_files")) or item.get("media_folder_id") is not None)


def _folder_photo_ids(client, folder_id: int) -> list[int]:
    page = client.vault_media(type="photo", list_id=int(folder_id),
                              limit=48, field="recent", sort="desc")
    items = page.get("list") or page.get("items") or []
    out: list[int] = []
    for it in items:
        full = ((it.get("files") or {}).get("full") or {})
        if full.get("url") and not full.get("drm"):
            try:
                out.append(int(it.get("id")))
            except (TypeError, ValueError):
                continue
    return out


def pick_media(item: dict, client=None) -> list[int]:
    pool = int_list(item.get("media_files"))
    folder_id = item.get("media_folder_id")
    if folder_id is not None and client is not None:
        try:
            for i in _folder_photo_ids(client, int(folder_id)):
                if i not in pool:
                    pool.append(i)
        except Exception:
            log.warning("pick_media: folder pull failed folder=%r", folder_id, exc_info=True)
    if not pool:
        return []
    try:
        count = int(item.get("media_count") or 1)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, len(pool)))
    return random.sample(pool, count)
