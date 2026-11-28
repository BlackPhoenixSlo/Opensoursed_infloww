from __future__ import annotations

import contextlib
import copy
import json
from datetime import datetime
from unittest.mock import patch

import requests
from stateful_fake import StatefulFansly

from _kind_verdict_seeds import FAN, OFStandIn

OTHER_FAN = "900000000000000003"
OTHER_PROFILE = ("ASSUMPTION: GET /account answers the second fan with the groups listing's account row "
                 "(fixtures/reads.json), no flags field; the capture has a profile for one fan only")
LOST_REPLY = "ASSUMPTION: a lost response is a transport error after Fansly stored the message"

VERDICTS = {
    "fansly": {"send_welcome": {"run": "same", "follow": "same", "both": "same", "partial": "same",
                                "toggle": "gated:platform_lacks:my_settings",
                                "paid": "gated:platform_lacks:tagged_users"}},
    "onlyfans": {"send_welcome": {"run": "same", "follow": "same", "both": "same", "partial": "same",
                                  "toggle": "same", "paid": "same"}},
}

_WELCOME = {"message": ["welcome babe"], "with_image": False}
PAYLOADS = {"send_welcome": {"run": _WELCOME, "follow": _WELCOME, "both": _WELCOME, "partial": {**_WELCOME, "limit": 1},
                             "toggle": {**_WELCOME, "after_of_welcome": True},
                             "paid": {**_WELCOME, "media_ids": [901], "price_cents": 1000}}}

_ONE_WELCOME = ("POST /account/900000000000000002/followers", "POST /message", "table:chats", "table:fans",
                "table:follow_log", "table:follow_ping_state", "table:messages", "table:welcome_sent")
SAME_EFFECTS = {
    "fansly": {"send_welcome": dict.fromkeys(("run", "follow", "both", "partial"), _ONE_WELCOME)},
    "onlyfans": {"send_welcome": dict.fromkeys(("run", "follow", "both", "partial", "paid"), (
        "follow_user", "send_message", "table:chats", "table:fans", "table:follow_log", "table:follow_ping_state",
        "table:messages", "table:welcome_sent")) | {"toggle": (
        "follow_user", "table:follow_log", "table:follow_ping_state", "table:welcome_sent")}},
}

_STREAK = json.dumps({"subscriptionStreak": 0})


def _notified(code: int, nid: str, metadata: str | None, fan: str = FAN):
    def shape(fake) -> None:
        fake.notifications.insert(0, {
            "id": nid, "accountId": fake.account_id, "type": code, "correlationId": "900000000000000502",
            "correlationGroupId": fan, "acknowledgedAt": 0, "createdAt": int(datetime.utcnow().timestamp()),
            "metadata": metadata})
    return shape


def _both(fake) -> None:
    _notified(15016, "900000000000000806", _STREAK)(fake)
    _notified(3003, "900000000000000807", None)(fake)


def _past_limit(fake) -> None:
    fake.profiles[OTHER_FAN] = copy.deepcopy(fake.accounts[OTHER_FAN])
    _notified(15016, "900000000000000808", _STREAK, OTHER_FAN)(fake)
    _notified(15016, "900000000000000809", _STREAK)(fake)


class LostReply(StatefulFansly):
    def __init__(self) -> None:
        super().__init__()
        self.lost = 1

    def request(self, *a, **kw):
        response = super().request(*a, **kw)
        if self.lost and self.calls[-1][:2] == ("POST", "/message"):
            self.lost -= 1
            raise requests.ConnectionError(LOST_REPLY)
        return response


def _of_feed(*fans: str):
    @contextlib.contextmanager
    def world(_aid):
        def notifications(stand_in, *, limit=10, offset=0, type=None, **_kw):
            stand_in.calls.append("notifications")
            rows = [{"id": f"n{i}", "type": "subscribed", "createdAt": datetime.utcnow().isoformat() + "+00:00",
                     "user": {"id": int(fan), "name": "Synth Fan"}}
                    for i, fan in enumerate(fans)] if type in (None, "subscribed") else []
            page = rows[offset:offset + limit]
            return {"list": page, "hasMore": offset + len(page) < len(rows)}
        with patch.object(OFStandIn, "notifications", notifications):
            yield
    return world


WORLDS = {("send_welcome", "both"): _of_feed(FAN, FAN), ("send_welcome", "partial"): _of_feed(FAN, OTHER_FAN)}

SEEDS: dict = {}

FAKE_STATE = {
    ("send_welcome", "run"): _notified(15016, "900000000000000802", _STREAK),
    ("send_welcome", "follow"): _notified(3003, "900000000000000803", None),
    ("send_welcome", "both"): _both,
    ("send_welcome", "partial"): _past_limit,
    ("send_welcome", "toggle"): _notified(3003, "900000000000000804", None),
    ("send_welcome", "paid"): _notified(15016, "900000000000000805", _STREAK),
}
