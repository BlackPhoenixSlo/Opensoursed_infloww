"""The help bot's "Do it for me" part of the slop relay (lib/relay.py loads it;
scenarios/2026-11-11-assistant-do-auto-mass.py). Its DeepSeek answer joins lib/automation_relay.py's
ANSWERS at import (purpose `help_assistant_do`, so the fake's 503 body names it). Nothing to wire.

POST /admin/assistant/draft asks DeepSeek (purpose `help_assistant_do`, JSON mode) to turn the
user's words into the Auto mass form's intent. That one prompt is faked at DeepSeek's wire, on
automation_relay's loopback fake: a chat completion whose system text opens with SYSTEM_HEAD gets,
after automation_relay.DEEPSEEK_LATENCY_S, INTENT (what a model reads off PHRASE: hourly, delete
after, everyone, exclude the mass-exclude list, folder want "sfw", 10 generated CAPTIONS) when the
user block's <request> is PHRASE, EDIT_INTENT (mass_edit, spec D11: scope all, every rule, unsend off) when
it is EDIT_PHRASE, else the schema's {"flow": null, ...}. The product then resolves
everything itself (lists, folders off `vault_items`, names, unsend hours) — the fake decides none
of that. Counted as `deepseek:help_assistant_do` at GET /__slop/fake/calls. With SLOP_LIVE=1 the
fake is not installed. Each draft prompt it answers is one line of `$DEMO_SHOTS_TMP/PROMPTS`
({system, user, completion}: the exact messages the product sent and the text the fake returned;
the scenario's `video=1` prices them). The chat completion's `usage` is automation_relay's fixed,
synthetic one.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SYSTEM_HEAD = "You turn a request into the fields of ONE form in this product."
PHRASE = ("make a auto mass to fans every hour and delete to everyone exclude mass-exclude list, pick the sfw "
          "folder or one that is close has no nude photos and insert 10 captions I will add the rest later")
RULE_NAME = "Hourly SFW mass"
PROMPTS = "assistant-do-prompts.jsonl"   # under $DEMO_SHOTS_TMP (the stack's tmp)
CAPTIONS = ["Thinking about you right now 😘", "Guess what I'm wearing today…",
            "Just woke up and you were my first thought ☀️", "Bored and looking for someone fun to talk to 💭",
            "New pics, who wants to see? 👀", "I've got a little surprise for you…", "Miss me? I missed you 💕",
            "Can't stop smiling today, wanna know why?", "Come say hi, I'm in the mood to chat 😊",
            "Sending you a little something to brighten your day ✨"]
INTENT = {"flow": "mass_premade", "name": RULE_NAME, "every": {"value": 1, "unit": "hours"},
          "delete_after": True, "unsend_after_hours": None, "online_only": False,
          "audience": {"include": ["everyone"], "exclude": ["mass-exclude"]},
          "folder": {"want": "sfw", "name": None},
          "captions": {"count": 10, "provided": [], "generated": CAPTIONS},
          "keep_skip_recent": True,
          "assumptions": ['"Delete to everyone" read as: unsend each mass for everyone once the next one is due.'],
          "unresolved": []}
# mass_edit (spec D11): the owner's own words, 2026-11-12. Which rules, the clamp and the per-rule diffs are
# the product's (assistant_edit), not the fake's.
EDIT_PHRASE = "please turn off auto mass unsend for every model"
EDIT_INTENT = {"flow": "mass_edit",
               "edit": {"scope": "all", "match": None,
                        "changes": {"unsend_after_hours": 0, "online_only": None, "every": None,
                                    "exclude_last_chat_hours": None, "price": None, "media_count": None,
                                    "disable_rule": False}},
               "assumptions": [], "unresolved": []}
NO_FLOW = {"flow": None, "name": None, "every": None, "delete_after": False, "unsend_after_hours": None,
           "online_only": None, "audience": {"include": [], "exclude": []}, "folder": {"want": "none", "name": None},
           "captions": {"count": 0, "provided": [], "generated": []}, "keep_skip_recent": True,
           "assumptions": [], "unresolved": []}


def request_of(user: str) -> str:
    """The user's words out of the draft's user block (between <request> and </request>)."""
    m = re.search(r"<request>\n(.*)\n</request>", user, re.S)
    return m.group(1).strip() if m else ""


def _answer(system: str, user: str) -> str | None:
    """The fake DeepSeek's text for the draft's prompt (module docstring); None for any other."""
    if not system.startswith(SYSTEM_HEAD):
        return None
    _base._fake_calls["deepseek:help_assistant_do"] += 1
    req = request_of(user)
    text = json.dumps(INTENT if req == PHRASE else EDIT_INTENT if req == EDIT_PHRASE else NO_FLOW, ensure_ascii=False)
    fd = os.open(Path(os.environ.get("DEMO_SHOTS_TMP", "")) / PROMPTS, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:   # one write(2) on an O_APPEND fd: whole lines, whatever thread wrote next
        os.write(fd, (json.dumps({"system": system, "user": user, "completion": text}, ensure_ascii=False)
                      + "\n").encode())
    finally:
        os.close(fd)
    return text


try:   # relay side only: the harness imports this module for its constants above
    import automation_relay as _base
except ImportError:
    _base = None
else:
    _base.ANSWERS.insert(0, ("help_assistant_do", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
