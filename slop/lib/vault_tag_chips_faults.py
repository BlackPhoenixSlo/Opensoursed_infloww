"""Vault Pro's tag chips and "Save as folder": check names and break-it-once faults, for
scenarios/2026-11-11-vault-tag-chips.py. lib/faults.py merges `register(Fault)`.
"""
from __future__ import annotations

FACETS = "tag_facets_counts"
FILTER = "tag_filter_and_three_sources"
CHIPS_DESK = "tag_chips_desktop"
CHIPS_PHONE = "tag_chips_phone_fit"
SAVED = "tag_folder_saved_from_ui"
PUBLISHED = "tag_folder_published"
MEMBERS = "tag_folder_members_exact"
NO_5XX = "tag_chips_no_5xx"


def _ignore_ai_tags() -> None:
    """The tag filter matches the tags column and primary_folder only, not `ai_fields_json.tags` (the describe
    model's raw list): every item tagged by the describe pass alone drops out of the grid and its saved folder."""
    import vault_tags as vt
    from sqlalchemy import case, func, literal, select

    from db.models import VaultItem

    if not hasattr(vt, "tag_match") or not hasattr(vt, "_valid"):
        raise RuntimeError("slop fault: vault_tags.tag_match/_valid is gone; update lib/vault_tag_chips_faults.py")

    def no_ai(tag: str):
        col = func.json_each(vt._valid(VaultItem.tags, "[]")).table_valued("value")
        in_col = select(literal(1)).select_from(col).where(func.lower(func.trim(col.c.value)) == tag).exists()
        ai = case((func.json_valid(VaultItem.ai_fields_json), VaultItem.ai_fields_json), else_=literal("{}"))
        folder = func.lower(func.trim(func.json_extract(ai, "$.primary_folder"))) == tag
        return in_col | folder

    vt.tag_match = no_ai


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-11-vault-tag-chips --break (the scenario's FAULT), server.
        "tag-filter-ignores-ai-tags": Fault(_ignore_ai_tags, (FILTER, SAVED, PUBLISHED, MEMBERS)),
    }
