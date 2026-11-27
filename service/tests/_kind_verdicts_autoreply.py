from __future__ import annotations

import json
from datetime import timedelta

from _kind_verdict_seeds import AUDIENCE_LIST, FAN, _ai, _fan, _in, _rows, fan_ids

FOLDER = "900000000000000704"

VERDICTS = {
    "fansly": {"autoreply": {"run": "same", "folder": "gated:platform_lacks:list_users_in:incomplete",
                             "gone_folder": "gated:platform_lacks:list_users_in:unknown_list"}},
    "onlyfans": {"autoreply": {"run": "same", "folder": "same", "gone_folder": "same"}},
}

PAYLOADS = {"autoreply": {"run": {}, "folder": {}, "gone_folder": {}}}

SAME_EFFECTS = {
    "fansly": {"autoreply": {"run": ("POST /message×2", "table:autoreply_state", "table:chats", "table:fans",
                                     "table:messages")}},
    "onlyfans": {"autoreply": dict.fromkeys(("run", "folder", "gone_folder"), (
        "send_message×2", "table:autoreply_state", "table:chats", "table:fans", "table:messages"))},
}


def _folder_config(aid: str, platform: str):
    lid = int(FOLDER) if platform == "fansly" else AUDIENCE_LIST
    return _ai(autoreply_config_json=json.dumps({"enabled": True, "list_ids": [lid]}))(aid, platform)


def _full_folder(fake) -> None:
    fake.lists[FOLDER] = {"accountId": fake.account_id, "type": 1, "label": "Folder", "id": FOLDER}
    fake.members[FOLDER] = [str(m) for m in fan_ids(int(FAN), 50)]


SEEDS = {
    ("autoreply", "run"): _rows(_ai(autoreply_config_json=json.dumps({"enabled": True})),
                                _fan(), _in(timedelta(hours=1))),
    ("autoreply", "folder"): _rows(_folder_config, _fan(), _in(timedelta(hours=1))),
    ("autoreply", "gone_folder"): _rows(_folder_config, _fan(), _in(timedelta(hours=1))),
}

FAKE_STATE = {("autoreply", "folder"): _full_folder}
