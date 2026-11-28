from __future__ import annotations

import json

from _kind_verdict_seeds import CHAT_RULES, SPEND_RULE, TAG_RULE, _lists
from db.engine import get_session
from db.models import Fan, SmartList

VERDICTS = {
    "fansly": {
        "smart_list_sync": {"sync": "gated:platform_lacks:tip_ledger",
                            "stale": "gated:platform_lacks:delete_list",
                            "chat": "same",
                            "money": "gated:platform_lacks:tip_ledger",
                            "renewal": "gated:platform_lacks:renewal_state",
                            "sub_start": "gated:platform_lacks:subscribers:paid_start",
                            "mixed": "gated:platform_lacks:tip_ledger",
                            "money_tombstone": "gated:platform_lacks:tip_ledger",
                            "tombstone": "gated:platform_lacks:delete_list"},
    },
    "onlyfans": {
        "smart_list_sync": {"sync": "same", "stale": "same", "chat": "same", "money": "same", "renewal": "same",
                            "sub_start": "same", "mixed": "same", "money_tombstone": "same", "tombstone": "same"},
    },
}

PAYLOADS = {"smart_list_sync": dict.fromkeys(VERDICTS["onlyfans"]["smart_list_sync"], {})}

_SYNCED = ("add_users_to_lists", "create_list", "table:smart_lists")
_CREATED = ("create_list", "table:smart_lists", "table:subscriber_crawl", "table:subscriber_snapshot")

SAME_EFFECTS = {
    "fansly": {"smart_list_sync": {"chat": ("POST /lists", "POST /lists/commands", "table:smart_lists")}},
    "onlyfans": {
        "smart_list_sync": {"sync": _SYNCED,
                            "stale": ("add_users_to_lists", "create_list", "delete_list", "table:smart_lists"),
                            "chat": _SYNCED,
                            "money": _SYNCED,
                            "renewal": _CREATED,
                            "sub_start": _CREATED,
                            "mixed": _SYNCED,
                            "money_tombstone": _SYNCED,
                            "tombstone": ("delete_list", "table:smart_lists")},
    },
}

PARTIAL_RUNS = {
    "fansly": {"smart_list_sync": {"mixed": ("POST /lists", "POST /lists/commands", "table:smart_lists"),
                                   "stale": ("POST /lists", "POST /lists/commands", "table:smart_lists"),
                                   "money_tombstone": ("table:smart_lists",)}},
}

MARKER_ALLOWLIST = {
    "smart_list_sync": {"delete_list": "a granted tombstone deletes only a Complete, Proof-fan-only list"},
}


async def _seed_active_list(aid: str, _platform: str) -> None:
    async with get_session() as s:
        s.add_all([Fan(account_id=aid, fan_id=f, lifetime_spend_cents=20000) for f in (1, 2)])
        s.add(SmartList(account_id=aid, name="Whales", is_active=True,
                        rules_json=json.dumps({"rules": [SPEND_RULE]})))


SEEDS = {
    ("smart_list_sync", "sync"): _seed_active_list,
    ("smart_list_sync", "stale"): _lists(("Chatty", CHAT_RULES, {"sync_state": "syncing"}),
                                         ("Gone (deleting #1)", CHAT_RULES,
                                          {"is_active": False, "sync_state": "deleting", "of_list_id": 703})),
    ("smart_list_sync", "chat"): _lists(("Chatty", CHAT_RULES, {})),
    ("smart_list_sync", "money"): _lists(("Whales", (SPEND_RULE,), {})),
    ("smart_list_sync", "renewal"): _lists(("Renewing", ({"field": "renew", "op": "==", "value": "on"},), {})),
    ("smart_list_sync", "sub_start"): _lists(
        ("Old subs", ({"field": "sub_start", "op": "more_than", "value": 30},), {})),
    ("smart_list_sync", "mixed"): _lists(("Chatty", CHAT_RULES, {}), ("Whales", (TAG_RULE, SPEND_RULE), {})),
    ("smart_list_sync", "money_tombstone"): _lists(("Whales", (SPEND_RULE,), {}), (
        "Gone (deleting #2)", CHAT_RULES, {"is_active": False, "sync_state": "deleting"})),
    ("smart_list_sync", "tombstone"): _lists(
        ("Gone (deleting #3)", CHAT_RULES, {"is_active": False, "sync_state": "deleting", "of_list_id": 704})),
}
