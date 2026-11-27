from __future__ import annotations

import json

from _kind_verdict_seeds import AUDIENCE_LIST, _payload_id
from db.models import PriorityMassRun

VERDICTS = {
    "fansly": {
        "priority_mass": {"list": "gated:platform_lacks:priority_mass",
                          "fans": "gated:platform_lacks:priority_mass",
                          "following": "gated:platform_lacks:following"},
    },
    "onlyfans": {
        "priority_mass": {"list": "same", "fans": "same", "following": "same"},
    },
}

PAYLOADS = {"priority_mass": {"list": {}, "fans": {}, "following": {}}}

_SENT = ("job:priority_mass", "send_message", "table:chats", "table:fans", "table:messages",
         "table:priority_mass_recipients", "table:priority_mass_runs")

SAME_EFFECTS = {"onlyfans": {"priority_mass": dict.fromkeys(("list", "fans", "following"), _SENT)}}


def priority_run(*lists, **kw):
    return _payload_id("run_id", lambda aid, _p: PriorityMassRun(
        account_id=aid, text="priority hey", audience_json=json.dumps({"user_lists": list(lists)}), **kw))


SEEDS = {
    ("priority_mass", "list"): priority_run(AUDIENCE_LIST),
    ("priority_mass", "fans"): priority_run("fans"),
    ("priority_mass", "following"): priority_run("following"),
}
