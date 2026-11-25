from __future__ import annotations

import json

import automation_relay as _base

OPTIONS = ["hey you, what are you up to tonight", "missed u today, how was ur day", "u still awake? thinking of u"]


def _answer(system: str, _user: str) -> str | None:
    import copilot_api

    if f"Answer ONLY with JSON {copilot_api._SHAPE}" not in system:
        return None
    _base._fake_calls["deepseek:copilot"] += 1
    return json.dumps({"suggestions": OPTIONS})


_base.ANSWERS.insert(0, ("copilot", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
