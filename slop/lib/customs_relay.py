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
    if not system.startswith(BRIEF_OPENER):
        return None
    _base._fake_calls["deepseek:customs_brief"] += 1
    return json.dumps(_brief(user))


_base.ANSWERS.insert(0, ("customs_brief", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
