from __future__ import annotations

VERDICTS = {
    "fansly": {"customs_watch": {"owed": "gated:platform_lacks:tip_ledger"}},
    "onlyfans": {"customs_watch": {"owed": "same"}},
}

PAYLOADS = {"customs_watch": {"owed": {}}}

SAME_EFFECTS = {"onlyfans": {"customs_watch": {"owed": ("table:fans",)}}}

SEEDS: dict = {}
