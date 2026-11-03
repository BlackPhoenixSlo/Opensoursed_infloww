"""The owed-customs queue's part of the slop relay (lib/relay.py loads it). Its DeepSeek answer
joins lib/automation_relay.py's ANSWERS at import (purpose `customs_brief`, so the fake's 503
body names it). No load-order dependency: nothing is read or re-pointed at `wire`.

`POST /admin/customs/brief` asks DeepSeek (`deepseek-v4-flash`, purpose `customs_brief`) for
the work order. That one prompt is faked at DeepSeek's wire, on automation_relay's loopback
fake (`llm_providers.PROVIDERS["deepseek"]` re-pointed there): a chat completion whose system
text opens with BRIEF_OPENER gets, after automation_relay.DEEPSEEK_LATENCY_S, JSON in the
brief's schema read off the transcript the product built: `summary` names the fan's first HIM
line, `his_words` are his HIM lines that mention a custom (copied whole, so `_whole_messages`
keeps them), `call_him` is the name after "call me". Any other prompt is the other ANSWERS'
or the fake's 503. Counted as `deepseek:customs_brief` at GET /__slop/fake/calls. With
SLOP_LIVE=1 the fake is not installed.
"""
from __future__ import annotations

import json
import re

import automation_relay as _base

BRIEF_OPENER = "You read one OnlyFans fan's chat with the creator and write the WORK ORDER"


def _brief(user: str) -> dict:
    him = [ln.split(":", 1)[1].strip() for ln in user.splitlines() if ln.startswith("HIM ") and ":" in ln]
    call = next((m.group(1) for ln in him for m in [re.search(r"call me (\w+)", ln)] if m), None)
    asks = [ln for ln in him if "custom" in ln.lower()] or him[:1]
    return {"summary": f"Record the voice note he asked for: {him[0]}" if him else "",
            "his_words": asks[:3], "call_him": call, "found_request": bool(him)}


def _answer(system: str, user: str) -> str | None:
    """The fake DeepSeek's text for the brief's prompt (module docstring); None for any other."""
    if not system.startswith(BRIEF_OPENER):
        return None
    _base._fake_calls["deepseek:customs_brief"] += 1
    return json.dumps(_brief(user))


_base.ANSWERS.insert(0, ("customs_brief", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
