"""automations/full_ai_config.py — Full AI Chat's settings JSON (spec 03a › Contracts › Config v1).

Pure (constant imports only). The stored blob (`account_ai_config.full_ai_config_json`) is {checkpoint, previous, draft, rev}:
the checkpoint drives Shadow and later live, the draft only the Test chat's right window.

  DEFAULTS          Config v1 with every field at its default
  merged(stored)    {checkpoint, previous, draft, rev}; an empty store gives DEFAULTS on both
                    sides, and a stored side missing a later key takes it from DEFAULTS
  turn_bound_s(cfg) one Turn's deadline: Router Jev + info Jev + extract + every Writer
  style_layers(cfg) the side's five human-texting layers (`style`), read off the old `text_style` too
  validate(cfg)     field errors ("<key or page label>: <why>"); a missing key is its default, an unknown one
                    an error (so no secret ever lands in the JSON)
  put_draft(stored, draft, rev) / save(stored, rev) / rollback(stored, rev)
                    the next stored blob, rev + 1; `StaleRev` on a rev mismatch, `Invalid` on
                    field errors, nothing to save, or nothing to roll back to

`style` holds the five layers the reply chain reads (`full_ai_writers.style_flags`). `text_style` is the
pre-layers master key, still accepted on a write (Do mode's prompt names it): girl = every layer on, formal =
all off; it wins over `style` and is never stored (`side` turns it into `style`), so an old stored side reads
exactly as before.

Save makes the draft the checkpoint and keeps the old one as `previous`; roll back swaps the two
(twice = identity) and leaves the draft as it is.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from automations.welcome_chatter_for_info import _EXTRACT_FIELDS
from llm_models import MODELS

# The fields wcfi's extract fills, the Test chat's get-to-know set by default.
INFO_FIELDS: tuple[str, ...] = _EXTRACT_FIELDS

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "reply_speed": "0-2m",
    # The human-texting layers (all on = the old `text_style: "girl"`): texting = the texting-style prompt
    # block and bubbles, nonnative = the u/ur rewrite, spacing = a space before ?/!, typos = thumb typos +
    # `*fix`, painful = the painful-texting prompt block.
    "style": {"texting": True, "nonnative": True, "spacing": True, "typos": True, "painful": True},
    "gifs": False,
    "sell_on": False,           # settable since 03b; off by default
    "sext_on": True,
    # Test Mode only: the Jev-run sext scene (scene questions, saved scene state, scene Writer
    # prompt, content level, price Jev; owner 2026-11-14). JSON-only switch (10-control limit).
    "sext_scene": True,
    # Test Mode only: get-to-know asks led into, not asked straight (lead-in lines, few-shots, a
    # beat of her own, the info Jev's lead wording; owner 2026-11-14). JSON-only switch.
    "lead_in": True,
    "folders": {"include": [], "exclude": []},   # 03b: Content folders, empty include = all
    "draft_questions": False,   # 03b: DRAFT Router questions count (test Mode only, ticket 47)
    "writers": ["euryale-v2.3", "hermes-4-405b", "glm-5.3-flash", "deepseek-v4-flash"],
    "writer_timeout_s": 25,
    "floor_on": True,
    "info_fields": list(INFO_FIELDS),
    "info_questions": "pick",   # pick: info Jev picks one | list: wcfi's whole still-need list
    "reply_by_webhook": True,   # D59 defaults on; read by 04a's live sender
    "typing_sign": True,
    "typing_notification": True,
    "caption_writer": "chat",   # PPV caption: "chat" = the chat Writer's last bubble; "caption" = its own call
    # Test Mode only: a sell ask nothing in the vault matches sells the nearest piece (same subject,
    # then same format, then anything) instead of no PPV. "off" = no_match as before; "plain" = the
    # caption as today; "note" = the Writer also plays his ask out as a story from what the piece shows (NEW-140).
    # JSON-only switch (10-control limit).
    "sell_nearest": "note",
    "describe_fan_photos": False,   # read his photo (inbound_describe, DeepInfra); JSON-only switch
}


REPLY_SPEEDS: tuple[str, ...] = ("0-2m", "0-15-60")     # full_ai_test._SPEEDS draws them
TEXT_STYLES: tuple[str, ...] = ("girl", "formal")      # the legacy `text_style` alias's values
STYLE_LAYERS: tuple[str, ...] = tuple(DEFAULTS["style"])
LEGACY_KEYS: tuple[str, ...] = ("text_style",)         # accepted on a write, never stored
INFO_QUESTIONS: tuple[str, ...] = ("pick", "list")
CAPTION_WRITERS: tuple[str, ...] = ("chat", "caption")    # full_ai_caption
SELL_NEAREST: tuple[str, ...] = ("off", "plain", "note")   # full_ai_sell.pick(nearest=)
MAX_WRITERS = 4
WRITER_TIMEOUT_S = (5, 60)
# The Writer hosts (D54, D60): a Writer is a known model on one of them.
WRITER_PROVIDERS: frozenset[str] = frozenset({"nanogpt", "openrouter", "zai", "deepseek"})
# A folder ref (03b): an internal vault folder `vf:<vault_folders.id>` or an OF list `of:<id>`.
FOLDER_REF = re.compile(r"(vf|of):[0-9]+")
_FOLDER_KEYS = ("include", "exclude")
_BOOLS = ("gifs", "sext_on", "sext_scene", "lead_in", "sell_on", "draft_questions", "floor_on", "reply_by_webhook", "typing_sign", "typing_notification",
          "describe_fan_photos")


class StaleRev(Exception):
    """The write's `rev` is not the stored one: someone stored meanwhile (`rev` = the stored)."""

    def __init__(self, rev: int):
        super().__init__(rev)
        self.rev = rev


class Invalid(Exception):
    """The write is refused with field errors."""

    def __init__(self, errors: list[str]):
        super().__init__(errors)
        self.errors = errors


def _writers_error(ws: Any) -> str | None:
    if not isinstance(ws, list) or not all(isinstance(w, str) for w in ws):
        return "must be a list of model ids"
    if not 1 <= len(ws) <= MAX_WRITERS:
        return f"needs 1 to {MAX_WRITERS} Writers"
    if len(set(ws)) != len(ws):
        return "a Writer is listed twice"
    for w in ws:
        if w not in MODELS:
            return f"unknown model {w!r}"
        if MODELS[w].provider not in WRITER_PROVIDERS:
            return f"{w!r} runs on {MODELS[w].provider}, not a Writer provider ({', '.join(sorted(WRITER_PROVIDERS))})"
    return None


def _folders_error(fs: Any) -> str | None:
    """`folders: {include, exclude}`, both lists of refs. Exclude is JSON-only (03b: no
    control); exclude wins at read time (`full_ai_sell.in_folders`)."""
    if not isinstance(fs, dict):
        return "must be an object {include, exclude}"
    if set(fs) != set(_FOLDER_KEYS):
        return f"want exactly include and exclude, got {sorted(fs)}"
    for k in _FOLDER_KEYS:
        refs = fs[k]
        if not isinstance(refs, list):
            return f"{k} must be a list of folder refs"
        for ref in refs:
            if not isinstance(ref, str) or not FOLDER_REF.fullmatch(ref):
                return f"bad ref {ref!r} in {k} (want vf:<id> or of:<id>)"
    return None


def style_layers(cfg: dict) -> dict[str, bool]:
    """The side's five layers. A valid `text_style` wins (girl = all on, formal = all off), else
    `style`; a side with neither is all off, as the old `text_style != "girl"` read."""
    ts, st = cfg.get("text_style"), cfg.get("style")
    if ts in TEXT_STYLES or not isinstance(st, dict):
        return dict.fromkeys(STYLE_LAYERS, ts == "girl")
    return {k: st.get(k) is True for k in STYLE_LAYERS}


def _style_error(st: Any) -> str | None:
    if not isinstance(st, dict) or set(st) != set(STYLE_LAYERS) or not all(isinstance(v, bool) for v in st.values()):
        return f"want exactly {', '.join(STYLE_LAYERS)}, each true or false"
    return None


def validate(cfg: Any) -> list[str]:
    """Field errors of one side's config, [] when it is valid (spec 03a › Contracts › Config v1)."""
    if not isinstance(cfg, dict):
        return ["config: must be an object"]
    errs = [f"{k}: unknown key" for k in cfg if k not in DEFAULTS and k not in LEGACY_KEYS]
    c = {**DEFAULTS, **cfg}

    def bad(key: str, why: str) -> None:
        errs.append(f"{key}: {why}")

    if c["version"] != 1 or isinstance(c["version"], bool):
        bad("version", "must be 1")
    if c["reply_speed"] not in REPLY_SPEEDS:
        bad("reply_speed", f"must be one of {', '.join(REPLY_SPEEDS)}")
    if "text_style" in c and c["text_style"] not in TEXT_STYLES:
        # The page's switch label, never the wire value (`assistant_full_ai.LABELS`).
        bad("Human style", "must be on or off")
    if (why := _style_error(c["style"])) is not None:
        bad("style", why)
    if c["caption_writer"] not in CAPTION_WRITERS:
        bad("caption_writer", f"must be one of {', '.join(CAPTION_WRITERS)}")
    if c["sell_nearest"] not in SELL_NEAREST:
        bad("sell_nearest", f"must be one of {', '.join(SELL_NEAREST)}")
    for k in _BOOLS:
        if not isinstance(c[k], bool):
            bad(k, "must be true or false")
    if (why := _writers_error(c["writers"])) is not None:
        bad("writers", why)
    t, (lo, hi) = c["writer_timeout_s"], WRITER_TIMEOUT_S
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not lo <= t <= hi:
        bad("writer_timeout_s", f"must be a number of seconds from {lo} to {hi}")
    f = c["info_fields"]
    if (not isinstance(f, list) or len(set(map(str, f))) != len(f)
            or not all(isinstance(x, str) and x in INFO_FIELDS for x in f)):
        bad("info_fields", f"must be distinct fields of {', '.join(INFO_FIELDS)}")
    if c["info_questions"] not in INFO_QUESTIONS:
        bad("info_questions", f"must be one of {', '.join(INFO_QUESTIONS)}")
    if (why := _folders_error(c["folders"])) is not None:
        bad("folders", why)
    return errs


def side(cfg: dict | None) -> dict[str, Any]:
    """One side filled from DEFAULTS, a valid `text_style` turned into `style` (the stored shape)."""
    c = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(cfg or {})}
    if c.get("text_style") in TEXT_STYLES:
        c["style"] = style_layers(c)
        del c["text_style"]
    return c


def merged(stored: dict | None) -> dict[str, Any]:
    """The stored blob with each side filled from DEFAULTS. `previous` stays None until a save."""
    stored = stored or {}
    checkpoint = side(stored.get("checkpoint"))
    return {
        "checkpoint": checkpoint,
        "previous": side(stored["previous"]) if stored.get("previous") else None,
        "draft": side(stored["draft"]) if stored.get("draft") else copy.deepcopy(checkpoint),
        "rev": int(stored.get("rev") or 0),
    }


def _check(cur: dict, rev: int) -> None:
    if rev != cur["rev"]:
        raise StaleRev(cur["rev"])


def put_draft(stored: dict | None, draft: Any, rev: int) -> dict[str, Any]:
    """`draft` (filled from DEFAULTS) as the stored draft. A stale rev answers before field
    errors: the owner reloads first."""
    cur = merged(stored)
    _check(cur, rev)
    if errs := validate(draft):
        raise Invalid(errs)
    return {**cur, "draft": side(draft), "rev": rev + 1}


def save(stored: dict | None, rev: int) -> dict[str, Any]:
    """The draft becomes the checkpoint; the old checkpoint is kept as `previous`."""
    cur = merged(stored)
    _check(cur, rev)
    if errs := validate(cur["draft"]):
        raise Invalid(errs)
    if cur["draft"] == cur["checkpoint"]:
        # A no-op save would overwrite `previous` with the checkpoint itself.
        raise Invalid(["draft: same as the checkpoint, nothing to save"])
    return {"checkpoint": cur["draft"], "previous": cur["checkpoint"],
            "draft": copy.deepcopy(cur["draft"]), "rev": rev + 1}


def put_checkpoint(stored: dict | None, cfg: Any, rev: int) -> dict[str, Any]:
    """`cfg` (filled from DEFAULTS) as the checkpoint, typed straight in (the page's checkpoint JSON);
    the old checkpoint is kept as `previous`, so Roll back undoes it. The draft stays."""
    cur = merged(stored)
    _check(cur, rev)
    if errs := validate(cfg):
        raise Invalid(errs)
    new = side(cfg)
    if new == cur["checkpoint"]:
        raise Invalid(["checkpoint: unchanged, nothing to store"])
    return {**cur, "checkpoint": new, "previous": cur["checkpoint"], "rev": rev + 1}


def rollback(stored: dict | None, rev: int) -> dict[str, Any]:
    """Swap the checkpoint and `previous` (a second roll back undoes it); the draft stays."""
    cur = merged(stored)
    _check(cur, rev)
    if cur["previous"] is None:
        raise Invalid(["previous: nothing to roll back to"])
    return {**cur, "checkpoint": cur["previous"], "previous": cur["checkpoint"], "rev": rev + 1}


# Router Jev 10 s (`_router_jev.TIMEOUT_S`, retries included) + info Jev 10 s.
_JEV_STAGES_S = 20


def turn_bound_s(cfg: dict) -> float:
    """One Turn's bound (spec 03a › Contracts › One Turn bound): the two Jev stages, then the
    extract and each Writer at `writer_timeout_s`. Defaults: 20 + 5 x 25 = 145 s."""
    return _JEV_STAGES_S + (1 + len(cfg["writers"])) * cfg["writer_timeout_s"]
