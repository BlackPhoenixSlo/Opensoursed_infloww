from __future__ import annotations

import json
from collections.abc import Mapping, Set
from typing import Any


def parse_folder_ids(raw: str | None) -> list[int]:
    try:
        ids = json.loads(raw or "[]")
        ids = [int(x) for x in ids if x is not None]
    except (ValueError, TypeError):
        ids = []
    return ids


def next_folder_ids(ids: list[int], media_id: int,
                    live_by_list: Mapping[int, Set[int]]) -> list[int]:
    out = list(ids)
    for lid, live in live_by_list.items():
        has, should = lid in out, int(media_id) in live
        if has == should:
            continue
        if should:
            out.append(lid)
        else:
            out = [x for x in out if x != lid]
    return out


def too_many(requested: list[int], max_n: int) -> dict[str, Any] | None:
    if len(requested) > max_n:
        return {"error": "too_many", "max": max_n, "got": len(requested)}
    return None


def parse_threshold(raw: Any, default: int, top: int) -> int:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(f"bad threshold: {raw!r}")
    return max(0, min(top, int(raw)))


def hide_selection(
    requested: list[int], clusters: list[dict[str, Any]], allow_sent: bool,
) -> tuple[list[int], dict[str, list[int]]]:
    # The ORIGINAL of a set is never hidden; a dupe with sends is refused unless allow_sent.
    originals = {c["original"]["media_id"] for c in clusters}
    dupes = {d["media_id"]: d for c in clusters for d in c["dupes"]}
    approved: list[int] = []
    refused: dict[str, list[int]] = {"is_original": [], "not_a_duplicate": [],
                                     "has_sends": []}
    for mid in requested:
        if mid in originals:
            refused["is_original"].append(mid)
        elif mid not in dupes:
            refused["not_a_duplicate"].append(mid)
        elif dupes[mid]["send_count"] > 0 and not allow_sent:
            refused["has_sends"].append(mid)
        else:
            approved.append(mid)
    return approved, refused


def chunks(ids: list[int], n: int) -> list[list[int]]:
    return [ids[i:i + n] for i in range(0, len(ids), n)]
