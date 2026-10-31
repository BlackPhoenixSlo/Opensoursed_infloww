"""style_config_json realism-flag keys + loaders."""
from __future__ import annotations

import json

from automation_registry import LEGACY_KINDS
from db.engine import get_session
from db.models import AccountAiConfig

from . import _voice


# The automations carrying the "human texting style" package (see _prompt_rules).
STYLE_AUTOMATIONS = ("welcome_chatter_for_info", "autoreply")

# The engines that actually CALL _persona.verify_self_consistency. Deliberately
# NOT STYLE_AUTOMATIONS: the style layers (_prompt_rules) are prompt-level and every engine
# applies them, but the pre-send check is a code path an engine either has or does
# not. Keying its flags off the wider tuple minted consistency flags for engines
# without the call (e.g. `consistency_autoreply`) — settable, persisted, and read
# by nothing, which is the same shape as the hot-lead trinity flag deleted in dc2c3b8.
#
# Widen this ONLY in the commit that adds the call, never ahead of it. The
# invariant is asserted by test_consistency_check.case_no_inert_flags.
CONSISTENCY_AUTOMATIONS = ("welcome_chatter_for_info",)


# ── Realism-flag default policy (TRI-STATE) ───────────────────────────
# An EXPLICIT stored value (True OR False) is ALWAYS honoured verbatim; only an
# ABSENT key consults this per-automation map. Auto-reply defaults ON (the owner's
# ask: its human style, typos, non-native and space-before-'?' layers all ship
# enabled, and are surfaced on the Auto-reply page). welcome_chatter_for_info is
# absent → OFF, so an absent key there means "run the current prompt + 2-bubble
# cap byte-for-byte". An explicit stored False still wins on every key.
_STYLE_DEFAULT_ON: dict[str, bool] = {"autoreply": True}

# Panic switch: STYLE_FORCE_OFF (env, to anything non-empty, or its Settings → System
# override) forces EVERY realism flag False across every account and automation,
# regardless of stored config — a kill switch for the whole realism stack if the
# default-on rollout misbehaves in prod. Read through runtime_switches, every call.
_STYLE_FORCE_OFF_ENV = "STYLE_FORCE_OFF"


def _style_force_off() -> bool:
    import runtime_switches
    return runtime_switches.on(_STYLE_FORCE_OFF_ENV)


def _style_default(automation: str) -> bool:
    """The absent-key default for one automation (see _STYLE_DEFAULT_ON)."""
    return _STYLE_DEFAULT_ON.get(automation, False)


def _parse_style_config(raw) -> dict:
    """Parse a style_config_json blob to a dict, tolerating NULL / garbage → {}.

    Legacy keys: a blob written before a kind rename (automation_registry.
    LEGACY_KINDS) still keys that automation's flags by the old name
    ('of_ai_chat', 'typos_of_ai_chat', …). Normalized here — the one parse
    chokepoint every flag reader goes through — so a stale blob keeps its
    meaning; an explicit new-name key wins over a leftover legacy one. The
    block no-ops (and can go) once LEGACY_KINDS empties."""
    if not raw:
        return {}
    try:
        stored = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(stored, dict):
        return {}
    for legacy, live in LEGACY_KINDS.items():
        for old_key in [k for k in stored
                        if k == legacy or k.endswith("_" + legacy)]:
            new_key = old_key[: -len(legacy)] + live
            legacy_val = stored.pop(old_key)
            stored.setdefault(new_key, legacy_val)
    return stored


async def _load_json_col(account_id: str, col: str) -> dict:
    """ONE fetch + tolerant parse of a JSON-blob column on account_ai_config —
    absent row / NULL / parse error / non-dict → {}. Every per-account config
    loader goes through here instead of re-cloning the fetch/parse block."""
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    return _parse_style_config(getattr(cfg, col, None) if cfg else None)


async def _load_style_json(account_id: str) -> dict:
    """The style_config_json blob — the overwhelmingly common case, named."""
    return await _load_json_col(account_id, "style_config_json")


def _resolve_style_flag(stored: dict, automation: str, key: str) -> bool:
    """One realism flag, applying the tri-state default: an EXPLICIT stored value
    under `key` (True or False) wins verbatim; an ABSENT key falls back to the per-
    automation default (_STYLE_DEFAULT_ON). `key` is the storage key (which differs
    from `automation` for the typos_/nonnative_ layers) while the DEFAULT is keyed by
    the automation."""
    if key in stored:
        return bool(stored.get(key))
    return _style_default(automation)


async def load_style_flags(account_id: str) -> dict[str, bool]:
    """Read account_ai_config.style_config_json → {automation: bool} for the
    humanizer / multi-bubble layer. TRI-STATE default (see policy note above): an
    explicit stored True/False wins; an ABSENT key → _STYLE_DEFAULT_ON. Absent row /
    NULL json / parse error → the same absent-key defaults. STYLE_FORCE_OFF forces
    every flag False regardless."""
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    stored = await _load_style_json(account_id)
    # the humanizer flag is stored under the bare automation name (the typos_/
    # nonnative_ layers use a prefixed key — see their own loaders).
    return {k: _resolve_style_flag(stored, k, k) for k in STYLE_AUTOMATIONS}


async def load_painful_texting_flag(account_id: str) -> bool:
    """Account-wide toggle for the PAINFUL_TEXTING framing block (brevity + emotion
    economy) injected at the top of the conversational prompts. Reads the
    'painful_texting' key of account_ai_config.style_config_json. DEFAULT ON
    (absent/NULL/parse-error → True) so it stays live where it's already shipping;
    set the key to false to A/B it off per account. STYLE_FORCE_OFF forces it off."""
    if _style_force_off():
        return False
    val = (await _load_style_json(account_id)).get(PAINFUL_TEXTING_KEY)
    return True if val is None else bool(val)


async def load_voice_blocks(account_id: str) -> "_voice.VoiceBlocks":
    """The account's resolved voice bundle, one row read.

    Engines call exactly this and read every voice-varying block off the result,
    so no engine can render one block in the male lane and another in the female.

    Absent row → the default lane."""
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    return _voice.blocks(getattr(cfg, "voice", None) if cfg else None)


async def load_cat_stickers_flag(account_id: str) -> bool:
    """Account-wide toggle for the cat-sticker reaction pack (a chat engine may
    end a reply with a cat gif, occasionally sending JUST the gif — see
    automations/cat_stickers.py). Reads the 'cat_stickers' key of
    account_ai_config.style_config_json. DEFAULT ON (absent/NULL/parse-error →
    True); an explicit stored False opts the account out. STYLE_FORCE_OFF kills
    it with the rest of the realism stack."""
    if _style_force_off():
        return False
    val = (await _load_style_json(account_id)).get(CAT_STICKERS_KEY)
    return True if val is None else bool(val)


async def load_strip_emojis(account_id: str) -> bool:
    """Read account_ai_config.style_config_json → the account-wide 'strip_emojis'
    bool. Absent/NULL/parse-error → False (the safe default: emojis kept, current
    behavior unchanged). When True, senders strip emojis at the send chokepoint."""
    return bool((await _load_style_json(account_id)).get("strip_emojis"))


def typo_flag_key(automation: str) -> str:
    """style_config_json key for the per-automation typo toggle (separate from the
    humanizer flag so typos can be ticked on independently)."""
    return f"typos_{automation}"


STYLE_TYPO_KEYS = tuple(typo_flag_key(k) for k in STYLE_AUTOMATIONS)


async def load_typo_flags(account_id: str) -> dict[str, bool]:
    """Read account_ai_config.style_config_json → {automation: bool} for the
    thumb-typo injector, keyed by STYLE_AUTOMATIONS (reads the 'typos_<automation>'
    keys). TRI-STATE default (see policy note above load_style_flags): an explicit
    'typos_<automation>' True/False wins; an ABSENT key → _STYLE_DEFAULT_ON.
    STYLE_FORCE_OFF forces every flag False."""
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    stored = await _load_style_json(account_id)
    return {k: _resolve_style_flag(stored, k, typo_flag_key(k)) for k in STYLE_AUTOMATIONS}


def nonnative_flag_key(automation: str) -> str:
    """style_config_json key for the per-automation non-native toggle."""
    return f"nonnative_{automation}"


STYLE_NONNATIVE_KEYS = tuple(nonnative_flag_key(k) for k in STYLE_AUTOMATIONS)


def spacing_flag_key(automation: str) -> str:
    """style_config_json key for the space-before-'?' habit.

    Its OWN key rather than riding `nonnative_<automation>`: the non-native layer
    is a whole register (vocabulary, word order, the odd article), while this is a
    single visible punctuation artifact — "you like it ?" — that an operator may
    well want off while keeping the rest. Same tri-state default as the layer it came from, so ticking nothing
    changes nothing."""
    return f"nonnative_spacing_{automation}"


async def load_spacing_flags(account_id: str) -> dict[str, bool]:
    """Read account_ai_config.style_config_json → {automation: bool} for the
    space-before-'?' habit. TRI-STATE, same rule as load_nonnative_flags: explicit
    True/False wins, ABSENT → _STYLE_DEFAULT_ON. STYLE_FORCE_OFF forces all False.

    Read INDEPENDENTLY of the non-native flag, but the caller applies it only when
    the non-native layer is on — the spacing is part of that register, so it can be
    narrowed, never widened past its parent."""
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    stored = _parse_style_config(getattr(cfg, "style_config_json", None) if cfg else None)
    return {k: _resolve_style_flag(stored, k, spacing_flag_key(k)) for k in STYLE_AUTOMATIONS}


def consistency_flag_key(automation: str) -> str:
    """style_config_json key for the PHASE 2 pre-send consistency check, mirroring
    typo_flag_key / nonnative_flag_key."""
    return f"consistency_{automation}"


STYLE_CONSISTENCY_KEYS = tuple(consistency_flag_key(k) for k in CONSISTENCY_AUTOMATIONS)


async def load_consistency_flags(account_id: str) -> dict[str, bool]:
    """Read account_ai_config.style_config_json → {automation: bool} for the
    pre-send consistency check (the 'consistency_<automation>' keys).

    Keyed off CONSISTENCY_AUTOMATIONS, not STYLE_AUTOMATIONS: only an engine that
    calls verify_self_consistency may have a flag, so an operator can never enable
    a check that nothing performs.

    OFF unless EXPLICITLY enabled — note this does NOT use _resolve_style_flag,
    whose per-automation default map could one day carry a default-ON entry.
    Unlike the humanizer and the typo layers, which are free, this one costs a
    second LLM call on the replies it fires for: it is opted into per account,
    never assumed. Ship it off, enable on the accounts with real payers, measure.
    STYLE_FORCE_OFF still forces False."""
    if _style_force_off():
        return {k: False for k in CONSISTENCY_AUTOMATIONS}
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    stored = _parse_style_config(getattr(cfg, "style_config_json", None) if cfg else None)
    return {k: bool(stored.get(consistency_flag_key(k), False))
            for k in CONSISTENCY_AUTOMATIONS}


async def load_nonnative_flags(account_id: str) -> dict[str, bool]:
    """Read account_ai_config.style_config_json → {automation: bool} for the
    non-native layer (the 'nonnative_<automation>' keys). TRI-STATE default (see
    policy note above load_style_flags): an explicit 'nonnative_<automation>'
    True/False wins; an ABSENT key → _STYLE_DEFAULT_ON. STYLE_FORCE_OFF forces every flag False."""
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    stored = await _load_style_json(account_id)
    return {k: _resolve_style_flag(stored, k, nonnative_flag_key(k)) for k in STYLE_AUTOMATIONS}


# ── "Fact-grounding" personalization layer (Auto Convo / welcome_chatter_for_info) ──
# When on, welcome_chatter_for_info's reply prompt is fed gen_info's rich profile — the short_bio +
# bullet notes — plus a "work in ONE specific detail" nudge. Makes a bubble land as "she remembers me" instead of
# generic. DEFAULT ON: a fan with no profile on file yet is unaffected (the block only
# appears when there's something to reference), so turning it on can never blank or
# break a reply.
# NOT the teases: those reach the model only through `_openers.need_block`, which
# paces them and marks them used. This layer once carried them too, as a menu — see
# ONE CHANNEL in _openers.py for why one metered door beats two unmetered ones.
FACTGROUND_KEY = "factground_welcome_chatter_for_info"
# Account-wide toggle key (style_config_json) for the PAINFUL_TEXTING framing block.
PAINFUL_TEXTING_KEY = "painful_texting"
# Account-wide toggle key (style_config_json) for the cat-sticker reaction pack.
CAT_STICKERS_KEY = "cat_stickers"
# Cat-sticker rate knobs (style_config_json, account-wide, NUMERIC not bool —
# the style API persists these through its numeric lane). Percents are 0-100
# in storage/UI; the loader hands the roll 0-1 weights.
CAT_STICKER_SKIP_PCT_KEY = "cat_sticker_skip_pct"  # % of replies that hide the pack
CAT_STICKER_SOLO_PCT_KEY = "cat_sticker_solo_pct"  # % nudged to a gif-ONLY reply
CAT_STICKER_GAP_MIN_KEY = "cat_sticker_gap_min"    # per-fan minutes between stickers
# The cat-sticker READER lives with the feature (cat_stickers.load_cat_sticker_config);
# the keys stay here beside every other style_config_json key the API validates.


async def load_factground_flag(account_id: str) -> bool:
    """Read account_ai_config.style_config_json → the 'factground_welcome_chatter_for_info' bool for
    Auto Convo's rich-profile personalization. Absent/parse-error → True (default
    ON); only an EXPLICIT stored False turns it off.

    ⚠️ NOT "NULL → True", which this docstring used to claim: `.get(KEY, True)`
    finds a stored null and `bool(None)` is False, the same shape as the rule-
    payload defect `bool_knob` exists for. It is left in the family's own
    spelling instead of being converted alone — but it is NOT unreachable, which
    is what this note used to say. `style_config_api._persist` writes
    `{k: bool(v) …}`, so the style-config API cannot produce a null; a row from
    the retired settings IMPORT path (verbatim, no coercion) can. See the ⚠️ SCOPE note above `bool_knob` (_knobs.py)."""
    return bool((await _load_style_json(account_id)).get(FACTGROUND_KEY, True))
