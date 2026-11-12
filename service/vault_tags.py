"""service/vault_tags.py — the Vault Pro grid's tag chips: the SQL behind them.

A tag is matched in three places, because three writers put one there:
  * `VaultItem.tags`                  the column (JSON list, `normalize_tags`: lower-cased; carries
                                      operator edits and import hashtags);
  * `ai_fields_json.tags`             the describe model's raw list (case as the model wrote it);
  * `ai_fields_json.primary_folder`   the describe taxonomy's one folder word ("feet", "lingerie").
An item carries a tag when any of the three holds it, compared lower-case and trimmed. Selected
tags combine with AND.

Exact element matches through SQLite's json_each, never a LIKE on the JSON text ("feet" must not
match "feet_soles"); an `instr` on the raw text runs first as a cheap prefilter, so the JSON is
parsed only for rows that contain the word at all. Malformed JSON is skipped (`json_valid`), never
an error: json_each raises on it and one bad row would 500 the grid.

Used by `vault_ai_api`: the items listing's `tags` filter, `/tag-facets`, `/folders/from-tags`.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from typing import Any

from sqlalchemy import case, func, literal, select

from db.models import VaultItem

# Chips a facet read returns; the row shows the busiest first.
FACET_LIMIT = 30
# Tags one filter may AND together (each is a correlated EXISTS per row).
MAX_TAGS = 8
_TAG_MAX_LEN = 80
# Items one "Save as folder" may hold (also the app's `TAG_FOLDER_MAX`): a bigger result is a filter mistake,
# and its later publish would push that many items to OnlyFans.
FOLDER_MAX_ITEMS = 5_000


def parse_tags(raw: Iterable[Any] | None) -> list[str]:
    """The request's tags: trimmed, lower-cased, deduped in order, empties dropped, at most MAX_TAGS."""
    out: list[str] = []
    for t in raw or []:
        v = "" if t is None else str(t).strip().lower()[:_TAG_MAX_LEN]
        if v and v not in out:
            out.append(v)
    return out[:MAX_TAGS]


def default_folder_name(tags: list[str]) -> str:
    """The save-as-folder name before the operator edits it: the tags joined."""
    return " + ".join(tags)[:120]


def unique_name(name: str, used: set[str]) -> str:
    """`name`, or `name 2`, `name 3`… — the first no live folder of this Creator has. A tag folder
    never lands on an existing name: the pack picker finds its rung folders by name and would take it over."""
    out, n = name, 1
    while out in used:
        n += 1
        out = f"{name[:115]} {n}"
    return out


def _valid(col, empty: str):
    """`col` when it is well-formed JSON, else `empty` (json_each raises on malformed text)."""
    return case((func.json_valid(col), col), else_=literal(empty))


def tag_match(tag: str):
    """SQL: this VaultItem row carries `tag` (lower-case, trimmed) in any of the three sources."""
    col = func.json_each(_valid(VaultItem.tags, "[]")).table_valued("value")
    ai = func.json_each(_valid(VaultItem.ai_fields_json, "{}"), "$.tags").table_valued("value")
    in_col = select(literal(1)).select_from(col).where(func.lower(func.trim(col.c.value)) == tag).exists()
    in_ai = select(literal(1)).select_from(ai).where(func.lower(func.trim(ai.c.value)) == tag).exists()
    folder = func.lower(func.trim(func.json_extract(_valid(VaultItem.ai_fields_json, "{}"), "$.primary_folder"))) == tag
    raw = func.lower(func.coalesce(VaultItem.tags, "") + func.coalesce(VaultItem.ai_fields_json, ""))
    # Prefilter first: SQLite evaluates AND left to right, so most rows never reach json_each.
    return (func.instr(raw, tag) > 0) & (in_col | in_ai | folder)


def tags_where(tags: list[str]) -> list:
    """One `tag_match` per tag (AND); empty list = no tag filter."""
    return [tag_match(t) for t in tags]


def facet_rows_stmt(where: list):
    """SELECT (tags column, ai tags, ai primary_folder) for the rows matching `where`: three small values
    per row, the ai ones extracted in SQL so the ~1 KB ai_fields_json never leaves SQLite. `count_facets`
    folds them. (Measured on 12k items: a pure-SQL UNION + GROUP BY took ~140-180 ms, mostly the UNION's
    per-item dedup; this pull + the Python fold ~45 ms.)"""
    ai = _valid(VaultItem.ai_fields_json, "{}")
    return select(VaultItem.tags, func.json_extract(ai, "$.tags"), func.json_extract(ai, "$.primary_folder")).where(*where)


def _as_list(raw: Any) -> list:
    """A stored tag list (JSON text) as a list; a bare string (a non-array `$.tags`) as one tag; junk → []."""
    if raw is None:
        return []
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return [raw] if isinstance(raw, str) else []
    if isinstance(v, list):
        return v
    return [v] if isinstance(v, str) else []


def count_facets(rows: Iterable[tuple[Any, Any, Any]], limit: int = FACET_LIMIT) -> list[tuple[str, int]]:
    """(tag, items) for the `limit` busiest tags over `facet_rows_stmt` rows: each item counted once per
    tag however many of its three sources hold it; busiest first, then by name. Non-string elements skipped."""
    counts: Counter[str] = Counter()
    for col, ai_tags, folder in rows:
        mine = {str(t).strip().lower() for t in [*_as_list(col), *_as_list(ai_tags), folder]
                if isinstance(t, str)}
        mine.discard("")
        counts.update(mine)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
