from __future__ import annotations

import contextlib
from datetime import timedelta
from unittest.mock import patch

from _kind_verdict_seeds import OFStandIn, _fan, _out, _rows, threadless

VERDICTS = {
    "fansly": {"send_followup": {"run": "same", "no_group": "same"}},
    "onlyfans": {"send_followup": {"run": "same", "no_group": "same"}},
}

PAYLOADS = {"send_followup": {"run": {"with_image": False}, "no_group": {"with_image": False}}}

_TABLES = ("table:chats", "table:fans", "table:followup_state", "table:messages")
SAME_EFFECTS = {
    "fansly": {"send_followup": {"run": ("POST /message", *_TABLES),
                                 "no_group": ("POST /group", "POST /message", *_TABLES)}},
    "onlyfans": {"send_followup": dict.fromkeys(("run", "no_group"), ("send_message", *_TABLES))},
}

_PAYING = _rows(_fan(lifetime_spend_cents=500), _out(timedelta(hours=30)))
SEEDS = {("send_followup", "run"): _PAYING, ("send_followup", "no_group"): _PAYING}

FAKE_STATE = {("send_followup", "no_group"): threadless}


@contextlib.contextmanager
def _no_chat(_aid):
    def no_chats(stand_in, *, offset=0, **_kw):
        stand_in.calls.append("list_chats")
        return {"list": [], "hasMore": False}

    def no_messages(stand_in, chat_id, **_kw):
        stand_in.calls.append("get_messages")
        return {"list": [], "hasMore": False}
    with patch.object(OFStandIn, "list_chats", no_chats), patch.object(OFStandIn, "get_messages", no_messages):
        yield


WORLDS = {("send_followup", "no_group"): _no_chat}
