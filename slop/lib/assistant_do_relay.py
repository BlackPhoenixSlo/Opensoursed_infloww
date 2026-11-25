from __future__ import annotations

import json
import os
import re
from pathlib import Path

SYSTEM_HEAD = "You turn a request into the fields of ONE form in this product."
PHRASE = ("make a auto mass to fans every hour and delete to everyone exclude mass-exclude list, pick the sfw "
          "folder or one that is close has no nude photos and insert 10 captions I will add the rest later")
RULE_NAME = "Hourly SFW mass"
PROMPTS = "assistant-do-prompts.jsonl"
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
    m = re.search(r"<request>\n(.*)\n</request>", user, re.S)
    return m.group(1).strip() if m else ""


def _answer(system: str, user: str) -> str | None:
    if not system.startswith(SYSTEM_HEAD):
        return None
    _base._fake_calls["deepseek:help_assistant_do"] += 1
    req = request_of(user)
    text = json.dumps(INTENT if req == PHRASE else EDIT_INTENT if req == EDIT_PHRASE else NO_FLOW, ensure_ascii=False)
    # one write(2) on an O_APPEND fd: whole lines, whatever thread wrote next
    fd = os.open(Path(os.environ.get("DEMO_SHOTS_TMP", "")) / PROMPTS, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps({"system": system, "user": user, "completion": text}, ensure_ascii=False)
                      + "\n").encode())
    finally:
        os.close(fd)
    return text


try:
    import automation_relay as _base
except ImportError:
    _base = None
else:
    _base.ANSWERS.insert(0, ("help_assistant_do", _answer))


def wire(_app, _loopback, _relay) -> None:
    """Nothing to wire: the answer joined ANSWERS at import."""
