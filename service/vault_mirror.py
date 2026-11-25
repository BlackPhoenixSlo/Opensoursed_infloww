from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, literal, select, true
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.models import VaultItem
from isotime import parse_iso

log = logging.getLogger("of-relay.vault_mirror")


def in_of_folders(folder_ids):
    je = func.json_each(func.coalesce(VaultItem.of_folder_ids, "[]")).table_valued("value")
    return select(literal(1)).select_from(je).where(je.c.value.in_(list(folder_ids))).exists()


def visible_to(allowed):
    return true() if allowed is None else in_of_folders(allowed)


def has_still(kind: str | None) -> bool:
    return (kind or "") != "audio"


def thumb_of(files: dict | None) -> str | None:
    if not isinstance(files, dict):
        return None
    for k in ("thumb", "squarePreview", "preview", "full"):
        f = files.get(k)
        if isinstance(f, dict) and f.get("url"):
            return f["url"]
    return None


def compact_list_states(m: dict) -> dict:
    ls = m.get("listStates")
    if not isinstance(ls, list):
        return m
    kept = [x for x in ls if isinstance(x, dict) and x.get("hasMedia")]
    return m if len(kept) == len(ls) else {**m, "listStates": kept}


def row_values(account_id: str, m: dict,
               run_id: int | None = None) -> dict[str, Any] | None:
    mid = m.get("id")
    if mid is None:
        return None
    files = m.get("files") if isinstance(m.get("files"), dict) else {}
    kind = m.get("type") or "photo"
    dur = m.get("duration")
    now = datetime.utcnow()
    # listStates[].hasMedia is the per-item "in that list" flag (Posts.hasMedia aligns with top-level hasPosts).
    of_folders = [
        ls.get("id") for ls in (m.get("listStates") or [])
        if isinstance(ls, dict) and ls.get("type") == "custom" and ls.get("hasMedia") and ls.get("id")
    ]
    return {
        "account_id": account_id,
        "media_id": int(mid),
        "kind": str(kind),
        "duration_seconds": int(dur) if isinstance(dur, (int, float)) and dur else None,
        "width": m.get("width") if isinstance(m.get("width"), int) else None,
        "height": m.get("height") if isinstance(m.get("height"), int) else None,
        "thumb_url": thumb_of(files),
        "full_url": (files.get("full") or {}).get("url") if isinstance(files.get("full"), dict) else None,
        "raw_json": json.dumps(compact_list_states(m), ensure_ascii=False, default=str),
        "created_at": parse_iso(m.get("createdAt")) or now,
        "updated_at_of": m.get("updatedAt") if isinstance(m.get("updatedAt"), str) else None,
        "updated_at": now,
        "of_folder_ids": json.dumps(of_folders),
        # OF just handed us this media, so it is not removed; an operator's hide is not undone (stamped only after OF hid it, and OF has no unhide).
        "removed_at": None,
        # On conflict we DON'T overwrite it (preserve describe output).
        "search_text": str(kind).lower(),
        "tags": "[]",
        **({"last_seen_run_id": run_id} if run_id is not None else {}),
    }


# ONE list for the collect sweep and vault_stills re-sign so raw_json and its derived columns move together; AI/operator fields are deliberately absent.
MIRROR_REFRESH_FIELDS = (
    "kind", "duration_seconds", "width", "height", "thumb_url", "full_url",
    "raw_json", "updated_at_of", "updated_at", "of_folder_ids",
    # Seeing the media again is the evidence it is not gone: this lifts the soft-delete.
    "removed_at",
)


def upsert_stmt(vals: dict[str, Any]):
    refresh = MIRROR_REFRESH_FIELDS + (
        ("last_seen_run_id",) if "last_seen_run_id" in vals else ())
    return (
        sqlite_insert(VaultItem)
        .values(**vals)
        .on_conflict_do_update(index_elements=["account_id", "media_id"],
                               set_={k: vals[k] for k in refresh})
    )
