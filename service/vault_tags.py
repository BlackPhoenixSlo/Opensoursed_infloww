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

FACET_LIMIT = 30
MAX_TAGS = 8
_TAG_MAX_LEN = 80
# a bigger result is a filter mistake; its later publish would push that many items to OnlyFans
FOLDER_MAX_ITEMS = 5_000


def parse_tags(raw: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    for t in raw or []:
        v = "" if t is None else str(t).strip().lower()[:_TAG_MAX_LEN]
        if v and v not in out:
            out.append(v)
    return out[:MAX_TAGS]


def default_folder_name(tags: list[str]) -> str:
    return " + ".join(tags)[:120]


# a tag folder must never take an existing name: the pack picker finds its rung folders by name
def unique_name(name: str, used: set[str]) -> str:
    out, n = name, 1
    while out in used:
        n += 1
        out = f"{name[:115]} {n}"
    return out


# json_each raises on malformed JSON text
def _valid(col, empty: str):
    return case((func.json_valid(col), col), else_=literal(empty))


def tag_match(tag: str):
    col = func.json_each(_valid(VaultItem.tags, "[]")).table_valued("value")
    ai = func.json_each(_valid(VaultItem.ai_fields_json, "{}"), "$.tags").table_valued("value")
    in_col = select(literal(1)).select_from(col).where(func.lower(func.trim(col.c.value)) == tag).exists()
    in_ai = select(literal(1)).select_from(ai).where(func.lower(func.trim(ai.c.value)) == tag).exists()
    folder = func.lower(func.trim(func.json_extract(_valid(VaultItem.ai_fields_json, "{}"), "$.primary_folder"))) == tag
    raw = func.lower(func.coalesce(VaultItem.tags, "") + func.coalesce(VaultItem.ai_fields_json, ""))
    # prefilter: SQLite ANDs left to right, so most rows never reach json_each
    pre = func.instr(raw, tag) > 0
    # json.dumps stores non-ASCII escaped ("caf\u00e9"): match that spelling too
    esc = json.dumps(tag)[1:-1]
    if esc != tag:
        pre = pre | (func.instr(raw, esc) > 0)
    return pre & (in_col | in_ai | folder)


def tags_where(tags: list[str]) -> list:
    return [tag_match(t) for t in tags]


def facet_rows_stmt(where: list):
    ai = _valid(VaultItem.ai_fields_json, "{}")
    return select(VaultItem.tags, func.json_extract(ai, "$.tags"), func.json_extract(ai, "$.primary_folder")).where(*where)


def _as_list(raw: Any) -> list:
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
    counts: Counter[str] = Counter()
    for col, ai_tags, folder in rows:
        mine = {str(t).strip().lower() for t in [*_as_list(col), *_as_list(ai_tags), folder]
                if isinstance(t, str)}
        mine.discard("")
        counts.update(mine)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
