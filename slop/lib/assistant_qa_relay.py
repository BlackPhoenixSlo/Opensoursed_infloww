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
    m = re.search(r"^Question: (.*)$", user, re.M)
    return m.group(1).strip() if m else ""


def _answer(system: str, user: str) -> str | None:
    if not system.startswith(SYSTEM_HEAD):
        return None
    _base._fake_calls["deepseek:help_assistant"] += 1
    q = question_of(user).lower()
    return REVENUE_ANSWER if q == REVENUE_Q.lower() else HOWTO_ANSWER if q == HOWTO_Q.lower() else OTHER_ANSWER


try:
    import automation_relay as _base
except ImportError:
    _base = None
else:
    _base.ANSWERS.insert(0, ("help_assistant", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
