from __future__ import annotations

import contextlib
import json
from datetime import timedelta
from unittest.mock import patch

import of_ws
from automations import autoreply, send_welcome, welcome_chatter_for_info
from db.models import SensitiveWord, User, UserAccount, UserLlmKey
from fansly_ws import FanslyWebSocket
from of_sends import SendsMixin
from _kind_verdict_seeds import AUDIENCE_LIST, FAN, OFStandIn, _ai, _fan, _in, _rows, fan_ids, llm_says

FOLDER = "900000000000000704"

VERDICTS = {
    "fansly": {"autoreply": {"run": "same", "folder": "gated:platform_lacks:list_users_in:incomplete",
                             "gone_folder": "gated:platform_lacks:list_users_in:unknown_list", "leak": "same"}},
    "onlyfans": {"autoreply": {"run": "same", "folder": "same", "gone_folder": "same", "leak": "same"}},
}

PAYLOADS = {"autoreply": {"run": {}, "folder": {}, "gone_folder": {}, "leak": {}}}

SAME_EFFECTS = {
    "fansly": {"autoreply": {"run": ("POST /message×2", "table:autoreply_state", "table:chats", "table:fans",
                                     "table:messages"),
                             "leak": ("POST /message", "table:autoreply_state", "table:chats", "table:fans",
                                      "table:messages")}},
    "onlyfans": {"autoreply": {**dict.fromkeys(("run", "folder", "gone_folder"), (
        "send_message×2", "table:autoreply_state", "table:chats", "table:fans", "table:messages")),
        "leak": ("send_message", "table:autoreply_state", "table:chats", "table:fans", "table:messages")}},
}


def _folder_config(aid: str, platform: str):
    lid = int(FOLDER) if platform == "fansly" else AUDIENCE_LIST
    return _ai(autoreply_config_json=json.dumps({"enabled": True, "list_ids": [lid]}))(aid, platform)


def _full_folder(fake) -> None:
    fake.lists[FOLDER] = {"accountId": fake.account_id, "type": 1, "label": "Folder", "id": FOLDER}
    fake.members[FOLDER] = [str(m) for m in fan_ids(int(FAN), 50)]


LEAK_REPLY = "add me on snapchat babe, im bella_x"
_ON = _ai(autoreply_config_json=json.dumps({"enabled": True}))

BANNED = _rows(_ON, _fan(), _in(timedelta(hours=1)),
               lambda aid, _p: User(id=f"u{aid}", username=f"u{aid}", password="x"),
               lambda aid, _p: UserAccount(user_id=f"u{aid}", account_id=aid),
               lambda aid, _p: UserLlmKey(user_id=f"u{aid}", provider="deepseek", api_key="kind-verdicts-key"),
               lambda aid, _p: SensitiveWord(agency_user_id=f"u{aid}", word="more", word_key="more"))

SEEDS = {
    ("autoreply", "run"): _rows(_ON, _fan(), _in(timedelta(hours=1))),
    ("autoreply", "leak"): _rows(_ON, _fan(), _in(timedelta(hours=1))),
    ("autoreply", "folder"): _rows(_folder_config, _fan(), _in(timedelta(hours=1))),
    ("autoreply", "gone_folder"): _rows(_folder_config, _fan(), _in(timedelta(hours=1))),
}

FAKE_STATE = {("autoreply", "folder"): _full_folder}

WORLDS = {("autoreply", "leak"): llm_says(LEAK_REPLY)}


class WireOF(OFStandIn, SendsMixin):
    def __init__(self, aid: str) -> None:
        super().__init__(aid)
        self.wire: list[tuple] = []

    def send_message(self, chat_id, text, **kw):
        _chat, path, body, _retry = SendsMixin.prepare_message(self, chat_id, text, **kw)
        self.wire.append(("POST", path, body))
        return super().send_message(chat_id, text, **kw)


class _Frames:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))


@contextlib.contextmanager
def typing_on(aid: str, platform: str, fake):
    if platform == "fansly":
        ws = FanslyWebSocket(fake.client(), clock=lambda: 0.0)
    else:
        ws = of_ws.OFWebSocket(lambda: fake, account_id=aid)
        ws._live_ws = _Frames()

    async def wpm(_aid):
        return 6000.0

    async def shown(_aid):
        return True
    of_ws.register_pump(aid, ws)
    try:
        with contextlib.ExitStack() as stack:
            for sender in (autoreply, send_welcome, welcome_chatter_for_info):
                stack.enter_context(patch.object(sender, "load_typing_wpm", wpm))
                stack.enter_context(patch.object(sender, "load_typing_indicator", shown))
            yield [] if platform == "fansly" else ws._live_ws.sent
    finally:
        of_ws.unregister_pump(aid, ws)
