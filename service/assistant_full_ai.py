"""assistant_full_ai — Do mode's `full_ai_config` proposal (phase 03c, D63). Pure: no DB, no LLM.

The assistant turns "reply slower" into a patch of the Creator's Full AI draft. `propose` applies the
patch to the fresh merged draft (`full_ai_turn.stored_config`) and checks the result with 03a's one
`full_ai_config.validate` (never a forked schema). The card shows `diffs`; the apply is the page's own
rev-checked `PUT /admin/full-ai/config/draft`. The assistant never touches the checkpoint.

`CONFIG_WORD` is the lexical gate `assistant_draft.vetoed` and `user_block` read, built from the
schema (keys, labels, Writer model names, info fields), so a new key or model widens it with no edit.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from automations import full_ai_config
from llm_models import MODELS

# Plan-card labels; a key with none shows its own name (`label`). text_style reads like the page's switch.
# `folders` / `draft_questions` are 03b's keys (spec 03c lists their labels).
LABELS: dict[str, str] = {
    "reply_speed": "Reply speed", "text_style": "Human style", "gifs": "GIFs",
    "sell_on": "Selling", "sext_on": "Sexting", "writers": "Writers (in order)",
    "writer_timeout_s": "Writer timeout (s)", "floor_on": "Reply checks", "info_fields": "Facts to learn",
    "folders": "Content folders", "draft_questions": "Draft questions",
}


# The blob's own fields: only the page's Save / Roll back / PUT move them, never a patch.
LOCKED_KEYS: tuple[str, ...] = ("version", "checkpoint", "previous", "rev")
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
    error: str          # invalid_patch | no_change
    text: str


def diffs(before: dict, after: dict) -> list[dict[str, Any]]:
    """One row per changed key, in `after`'s key order."""
    return [{"field": k, "label": label(k), "before": before.get(k), "after": v}
            for k, v in after.items() if before.get(k) != v]


def refusal_text(errors: list[str]) -> str:
    return "I can't make that change: " + "; ".join(errors) + "."


def propose(cur: dict, patch: ConfigPatch) -> Proposal | Refusal:
    """`cur`: the merged stored config (`full_ai_config.merged` / `full_ai_turn.stored_config`)."""
    base = cur["draft"]
    # An unknown key never equals `base`, so `validate` below refuses it, as it does the JSON box's.
    if bad := [f"{k}: locked" for k in patch.set if k in LOCKED_KEYS]:
        return Refusal("invalid_patch", refusal_text(bad))
    after = {**base, **patch.set}
    # 03b's `folders`: a value without `exclude` keeps the stored one (spec 03c › propose step 3).
    f = patch.set.get("folders")
    if isinstance(f, dict) and "exclude" not in f and isinstance(base.get("folders"), dict) \
            and "exclude" in base["folders"]:
        after["folders"] = {**f, "exclude": base["folders"]["exclude"]}
    if after == base:
        return Refusal("no_change", "That's already how the draft is set — nothing to change.")
    if errs := full_ai_config.validate(after):
        return Refusal("invalid_patch", refusal_text(errs))
    return Proposal(rev=cur["rev"], before=base, after=after, diffs=diffs(base, after))


def draft_line(cur: dict) -> str:
    """The `user_block` line: the merged stored draft, as the model patches it."""
    return "Full AI draft: " + json.dumps(cur["draft"], ensure_ascii=False, sort_keys=True)


# ── CONFIG_WORD (built from the schema) ───────────────────────────────

_FIXED = ("reply", "speed", "slow", "fast", "gif", "style", "formal", "girl", "sext", "writer", "timeout",
          "question", "info", "learn", "check", "floor", "sell", "folder", "setting", "config", "json")
_STOP = frozenset({"his", "the", "and"})      # key words that name nothing (`his_age`); < 3 letters drop too


def writer_short_names() -> list[str]:
    """Each Writer-provider model's leading word: euryale, hermes, glm, deepseek."""
    return sorted({re.match(r"[a-z]+", m).group(0) for m, v in MODELS.items()
                   if v.provider in full_ai_config.WRITER_PROVIDERS and re.match(r"[a-z]+", m)})


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
    # "reply" → replies, "slow" → slower, "gif" → gifs, "sell" → selling.
    head = re.escape(w[:-1]) + "(?:y|ies)" if w.endswith("y") else re.escape(w)
    return head + r"(?:s|es|er|ers|ing|ed)?"


def build_config_word() -> re.Pattern[str]:
    alts = [re.escape(k) for k in CONFIG_KEYS] + [_stem(w) for w in config_vocab()] + [r"full\s*ai"]
    return re.compile(r"\b(?:" + "|".join(sorted(alts, key=len, reverse=True)) + r")\b", re.I)


CONFIG_WORD = build_config_word()
