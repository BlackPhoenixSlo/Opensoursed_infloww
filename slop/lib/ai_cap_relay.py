"""The daily AI spend limit flow's part of the slop relay (lib/relay.py loads it). Its DeepSeek answer joins
lib/automation_relay.py's ANSWERS at import (purpose `copilot`, so the fake's 503 body names it). Nothing is read or
re-pointed at `wire`. Used by scenarios/2026-11-11-ai-daily-cap.py.

`POST /admin/copilot/{account}/{fan}/suggest` asks DeepSeek (`deepseek-v4-flash`, purpose `copilot`) for three reply
options as JSON. That one prompt is faked at DeepSeek's wire, on automation_relay's loopback fake
(`llm_providers.PROVIDERS["deepseek"]` re-pointed there; `llm_client.chat` with its key lookup, cap reservation,
grok_calls row and cost math is the product's): a chat completion whose system text asks for copilot_api's JSON shape
gets, after automation_relay.DEEPSEEK_LATENCY_S, three fixed short options. Counted as `deepseek:copilot` at GET
/__slop/fake/calls. With SLOP_LIVE=1 the fake is not installed.
"""
from __future__ import annotations

import json

import automation_relay as _base

OPTIONS = ["hey you, what are you up to tonight", "missed u today, how was ur day", "u still awake? thinking of u"]


def _answer(system: str, _user: str) -> str | None:
    """The fake DeepSeek's text for Copilot's prompt (module docstring); None for any other."""
    import copilot_api

    if f"Answer ONLY with JSON {copilot_api._SHAPE}" not in system:
        return None
    _base._fake_calls["deepseek:copilot"] += 1
    return json.dumps({"suggestions": OPTIONS})


_base.ANSWERS.insert(0, ("copilot", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
