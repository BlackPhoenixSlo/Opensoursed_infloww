"""service/vault_of_folders_decide.py — the pure decisions of the OF-folder writes.

No DB, no IO, no OF: what `vault_of_folders` hands loaded rows to and gets a
verdict back; the shell raises the HTTP errors (`too_many` only builds the
400 detail) and does the writes.
Table-tested in tests/test_vault_of_folders_decide.py.

  membership   parse_folder_ids, next_folder_ids — an item's `of_folder_ids`
               after a read-back, both directions (gained AND dropped lists).
  dupes hide   too_many (the per-call blast-radius cap), hide_selection (keeper
               never hidden, sent copies only with allow_sent).
  batching     chunks — bounded slices for OF bodies and SQL IN(...).
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Set
from typing import Any


def parse_folder_ids(raw: str | None) -> list[int]:
    """The stored `of_folder_ids` JSON as ints; missing / bad JSON / bad ids → []."""
    try:
        ids = json.loads(raw or "[]")
        ids = [int(x) for x in ids if x is not None]
    except (ValueError, TypeError):
        ids = []
    return ids


def next_folder_ids(ids: list[int], media_id: int,
                    live_by_list: Mapping[int, Set[int]]) -> list[int]:
    """The item's folder ids once every list in `live_by_list` is believed.

    `ids` is the parsed stored list (`parse_folder_ids`); never mutated. A list
    the item is live in is appended if missing; a list it is no longer live in
    is dropped — lists not in `live_by_list` are left as they were."""
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
    """The 400 detail when one hide request asks for more than `max_n`, else None."""
    if len(requested) > max_n:
        return {"error": "too_many", "max": max_n, "got": len(requested)}
    return None


def hide_selection(
    requested: list[int], clusters: list[dict[str, Any]], allow_sent: bool,
) -> tuple[list[int], dict[str, list[int]]]:
    """Split requested ids into (approved, refused) against freshly derived clusters.

    The ORIGINAL of a set is refused (the keeper is never hidden), an id in no
    set is refused, a dupe with sends is refused unless `allow_sent`. `refused`
    always carries all three keys, in this order."""
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
    """`ids` in consecutive slices of at most `n`, order kept; [] → []."""
    return [ids[i:i + n] for i in range(0, len(ids), n)]
