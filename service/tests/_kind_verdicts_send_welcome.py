from __future__ import annotations

import json
from datetime import datetime

from _kind_verdict_seeds import FAN

VERDICTS = {
    "fansly": {"send_welcome": {"run": "same", "follow": "same", "toggle": "gated:platform_lacks:my_settings",
                                "paid": "gated:platform_lacks:tagged_users"}},
    "onlyfans": {"send_welcome": {"run": "same", "follow": "same", "toggle": "same", "paid": "same"}},
}

_WELCOME = {"message": ["welcome babe"], "with_image": False}
PAYLOADS = {"send_welcome": {"run": _WELCOME, "follow": _WELCOME, "toggle": {**_WELCOME, "after_of_welcome": True},
                             "paid": {**_WELCOME, "media_ids": [901], "price_cents": 1000}}}

SAME_EFFECTS = {
    "fansly": {"send_welcome": dict.fromkeys(("run", "follow"), (
        "POST /account/900000000000000002/followers", "POST /message", "table:chats", "table:fans", "table:follow_log",
        "table:follow_ping_state", "table:messages", "table:welcome_sent"))},
    "onlyfans": {"send_welcome": dict.fromkeys(("run", "follow", "paid"), (
        "follow_user", "send_message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state",
        "table:messages", "table:welcome_sent")) | {"toggle": (
        "follow_user", "table:follow_log", "table:follow_ping_state", "table:welcome_sent")}},
}


def _notified(code: int, nid: str, metadata: str | None):
    def shape(fake) -> None:
        fake.notifications.insert(0, {
            "id": nid, "accountId": fake.account_id, "type": code, "correlationId": "900000000000000502",
            "correlationGroupId": FAN, "acknowledgedAt": 0, "createdAt": int(datetime.utcnow().timestamp()),
            "metadata": metadata})
    return shape


SEEDS: dict = {}

FAKE_STATE = {
    ("send_welcome", "run"): _notified(15016, "900000000000000802", json.dumps({"subscriptionStreak": 0})),
    ("send_welcome", "follow"): _notified(3003, "900000000000000803", None),
    ("send_welcome", "toggle"): _notified(3003, "900000000000000804", None),
    ("send_welcome", "paid"): _notified(15016, "900000000000000805", json.dumps({"subscriptionStreak": 0})),
}
