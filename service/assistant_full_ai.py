from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from automations import full_ai_config

_LABEL_OVERRIDES: dict[str, str] = {
    "style": "Human style", "text_style": "Human style",
    "sext_scene": "Sext scene",
    "writer_timeout_s": "Writer timeout (s)", "writer_timeouts": "Writer timeouts per model (s)",
    "writer_retries": "Writer retries", "floor_on": "Reply checks", "info_fields": "Facts to learn",
    "chat_tease_prices": "Chat tease prices", "info_wide": "Wider hobbies",
    "catchup_minutes": "Catch-up passes (min)",
}
LABELS: dict[str, str] = {
    **{k: ref["page"] for k, ref in full_ai_config.REFERENCE.items() if ref["page"]}, **_LABEL_OVERRIDES,
}


# The blob's own fields: only the page's Save / Roll back / PUT move them, never a patch. The audience keys (`fans`,
# `top_spend_cents`) have their own write (`PUT /admin/full-ai/config/audience`); a draft PUT carries the stored ones
# over, so a patch of them would apply as nothing: refused here instead.
LOCKED_KEYS: tuple[str, ...] = ("version", "checkpoint", "previous", "rev", *full_ai_config.AUDIENCE_KEYS)
# The draft fields `DEFAULTS` holds.
CONFIG_KEYS: tuple[str, ...] = tuple(k for k in full_ai_config.DEFAULTS if k not in LOCKED_KEYS)


def label(key: str) -> str:
    return LABELS.get(key, key)


class ConfigPatch(BaseModel):
    """The model's patch: top-level draft keys → whole new values."""
    model_config = ConfigDict(extra="ignore")
    set: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class Proposal:
    rev: int
    before: dict[str, Any]
    after: dict[str, Any]
    diffs: list[dict[str, Any]]


@dataclass(frozen=True)
class Refusal:
    error: str
    text: str


def diffs(before: dict, after: dict) -> list[dict[str, Any]]:
    return [{"field": k, "label": label(k), "before": before.get(k), "after": v}
            for k, v in after.items() if before.get(k) != v]


def refusal_text(errors: list[str]) -> str:
    return "I can't make that change: " + "; ".join(errors) + "."


def propose(cur: dict, patch: ConfigPatch) -> Proposal | Refusal:
    base = cur["draft"]
    if bad := [f"{k}: locked" for k in patch.set if k in LOCKED_KEYS]:
        return Refusal("invalid_patch", refusal_text(bad))
    # `side` below drops a retired key, so name it here or the answer would be a false "already set"
    if bad := full_ai_config.retired_errors(patch.set):
        return Refusal("invalid_patch", refusal_text(bad))
    after = {**base, **patch.set}
    # a folders value without `exclude` keeps the stored one
    f = patch.set.get("folders")
    if isinstance(f, dict) and "exclude" not in f and isinstance(base.get("folders"), dict) \
            and "exclude" in base["folders"]:
        after["folders"] = {**f, "exclude": base["folders"]["exclude"]}
    after = full_ai_config.side(after)
    if after == base:
        return Refusal("no_change", "That's already how the draft is set — nothing to change.")
    if errs := full_ai_config.validate(after):
        return Refusal("invalid_patch", refusal_text(errs))
    return Proposal(rev=cur["rev"], before=base, after=after, diffs=diffs(base, after))


def draft_line(cur: dict) -> str:
    return "Full AI draft: " + json.dumps(cur["draft"], ensure_ascii=False, sort_keys=True)



_FIXED = ("reply", "speed", "slow", "fast", "gif", "style", "formal", "girl", "sext", "writer", "timeout",
          "question", "info", "learn", "check", "floor", "sell", "folder", "setting", "config", "json")
_STOP = frozenset({"his", "the", "and", "min", "minutes"})


def writer_short_names() -> list[str]:
    return sorted({re.match(r"[a-z]+", m).group(0) for m in full_ai_config.WRITER_MODELS
                   if re.match(r"[a-z]+", m)})


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", s.lower()) if len(w) >= 3 and w not in _STOP]


def config_vocab() -> list[str]:
    keys = CONFIG_KEYS
    out = set(_FIXED) | set(writer_short_names())
    for k in keys:
        out.update(_words(k))
    for k in set(keys) | set(LABELS):
        out.update(_words(label(k)))
    for f in full_ai_config.INFO_FIELDS:
        out.update(_words(f))
    return sorted(out)


def _stem(w: str) -> str:
    head = re.escape(w[:-1]) + "(?:y|ies)" if w.endswith("y") else re.escape(w)
    return head + r"(?:s|es|er|ers|ing|ed)?"


def build_config_word() -> re.Pattern[str]:
    alts = [re.escape(k) for k in CONFIG_KEYS + full_ai_config.LEGACY_KEYS] + [_stem(w) for w in config_vocab()] + [r"full\s*ai"]
    return re.compile(r"\b(?:" + "|".join(sorted(alts, key=len, reverse=True)) + r")\b", re.I)


CONFIG_WORD = build_config_word()
