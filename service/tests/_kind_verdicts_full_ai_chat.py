from __future__ import annotations

import contextlib
import json
import os
from unittest.mock import patch

from _kind_verdict_seeds import _jev_answers, _seed_live_turn
from automations import full_ai_test
from automations.full_ai_config import DEFAULTS
from automations.full_ai_sell import Pick
from db.engine import get_session
from db.models import AccountAiConfig

VERDICTS = {
    "fansly": {"full_ai_chat": {"shadow": "same", "live": "same", "ppv": "gated:platform_lacks:tagged_users",
                                "preview_ppv": "gated:platform_lacks:message_price"}},
    "onlyfans": {"full_ai_chat": {"shadow": "same", "live": "same", "ppv": "same", "preview_ppv": "same"}},
}

PAYLOADS = {"full_ai_chat": {"shadow": {}, "live": {}, "ppv": {}, "preview_ppv": {}}}

_OF_LIVE = ("mark_chat_read", "send_message×2", "table:ai_decisions", "table:chats", "table:fans", "table:messages")
_OF_PPV = (*_OF_LIVE, "table:vault_sends")

SAME_EFFECTS = {
    "fansly": {"full_ai_chat": {"shadow": ("table:ai_decisions",),
                                "live": ("POST /message/ack", "POST /message×2", "table:ai_decisions", "table:chats",
                                         "table:fans", "table:messages")}},
    "onlyfans": {"full_ai_chat": {"shadow": ("table:ai_decisions",), "live": _OF_LIVE, "ppv": _OF_PPV,
                                  "preview_ppv": _OF_PPV}},
}

DECLARED_WRITES = {"fansly": {"full_ai_chat": dict.fromkeys(("ppv", "preview_ppv"), {
    "table:ai_decisions": "the stood-down Turn's no_send row, as every stood-down Turn records"})}}

TYPED = {"typing_sign": True, "typing_notification": True, "typo_pct": 100}
_PICKS = {"ppv": Pick(ref=711, media=(711, 712), previews=(701,), price_cents=1500, list_cents=1500,
                      subject="any", format="photo", lane="paid", facts={}),
          "preview_ppv": Pick(ref=711, media=(711,), previews=(711,), price_cents=1500, list_cents=1500,
                              subject="any", format="photo", lane="paid", facts={})}


async def _typed_live_turn(aid: str, platform: str) -> dict:
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, full_ai_config_json=json.dumps({"checkpoint": {**DEFAULTS, **TYPED}})))
    return await _seed_live_turn(aid, platform)


def _offered(branch: str, **env: str):
    @contextlib.contextmanager
    def world(aid):
        real = full_ai_test.send

        def send(row, parts, pick=None, **kw):
            return real(row, parts, pick or _PICKS[branch], **kw)
        with _jev_answers(aid), patch.object(full_ai_test, "send", send), patch.dict(os.environ, env):
            yield
    return world


SEEDS = {("full_ai_chat", "ppv"): _typed_live_turn, ("full_ai_chat", "preview_ppv"): _typed_live_turn}

WORLDS = {("full_ai_chat", "ppv"): _offered("ppv"),
          ("full_ai_chat", "preview_ppv"): _offered("preview_ppv", OF_COTAG_ENABLED="0")}
