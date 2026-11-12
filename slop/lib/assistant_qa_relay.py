"""The help bot's Q&A part of the slop relay (lib/relay.py loads it; scenarios/2026-11-12-assistant-siri-box.py).
Its DeepSeek answer joins lib/automation_relay.py's ANSWERS at import (purpose `help_assistant`, so the fake's
503 body names it). Nothing to wire.

POST /admin/assistant/ask asks DeepSeek (purpose `help_assistant`) with the manual as its system prompt (opens
with SYSTEM_HEAD) and a user block whose `Question: ` line is the asker's words. The fake answers, after
automation_relay.DEEPSEEK_LATENCY_S: REVENUE_ANSWER for REVENUE_Q (a D12 data marker beside a figure the model
was told never to write, PLANTED, in the same sentence: the client strip's prey), HOWTO_ANSWER for HOWTO_Q, else
OTHER_ANSWER. Counted as `deepseek:help_assistant` at GET /__slop/fake/calls.
"""
from __future__ import annotations

import re

SYSTEM_HEAD = "You are the help assistant for this platform."
REVENUE_Q = "how much did I make today"
HOWTO_Q = "how do I open settings?"
PLANTED = "999"
REVENUE_ANSWER = f"You made ${PLANTED} today from {PLANTED} sales: [[data:revenue|today|this]]\n\nThe card reads it live."
HOWTO_ANSWER = "Click **Settings** at the bottom of the sidebar."
OTHER_ANSWER = "I can only help with this product."


def question_of(user: str) -> str:
    """The asker's words out of the ask's user block (its `Question: ` line)."""
    m = re.search(r"^Question: (.*)$", user, re.M)
    return m.group(1).strip() if m else ""


def _answer(system: str, user: str) -> str | None:
    """The fake DeepSeek's text for a help-bot Q&A prompt (module docstring); None for any other."""
    if not system.startswith(SYSTEM_HEAD):
        return None
    _base._fake_calls["deepseek:help_assistant"] += 1
    q = question_of(user).lower()
    return REVENUE_ANSWER if q == REVENUE_Q.lower() else HOWTO_ANSWER if q == HOWTO_Q.lower() else OTHER_ANSWER


try:   # relay side only: the harness imports this module for its constants above
    import automation_relay as _base
except ImportError:
    _base = None
else:
    _base.ANSWERS.insert(0, ("help_assistant", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
