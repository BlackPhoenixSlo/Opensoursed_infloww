"""Re-export shim: new code should import from the leaf modules (_knobs, _send_failure, ...)."""
from __future__ import annotations

# Explicit re-export shim: every helper lives in a leaf module below. Leaves import
# each other, never this file. Patch a module global on its LEAF, not here.
import asyncio  # noqa: F401  (test_pacing patches _common.asyncio.sleep — the global module)

from ._knobs import (  # noqa: F401
    bool_knob, coerce_ids, test_mode,
)
from ._send_failure import (  # noqa: F401
    SendOutcome, is_media_rejected_error, is_unreachable_fan_error,
    quarantine_if_undeliverable, send_dropping_bad_media, send_dropping_bad_media_sync,
    skip_unreachable_fan,
)
from ._skiplist import (  # noqa: F401
    HARD_SKIP_REASONS, LADDER_STOP_REASON, MANUAL_RESTRICT_REASON, MUTED_CREATOR_REASON,
    OF_RESTRICTED_REASON, _load_skip_ids, automation_restrict_status, classify_source,
    is_hard_skipped, load_hard_skip_ids, load_of_restricted_ids, load_promo_spam_ids,
    mark_muted_creator_skip, set_of_restricted_skip, should_skip_muted_creator,
    source_self_heal_set,
)
from ._model_pick import (  # noqa: F401
    DEFAULT_MODEL, MODEL_PURPOSES, PURPOSE_DEFAULT_MODELS, resolve_model,
)
from ._prompt_rules import (  # noqa: F401
    BIO_CONSISTENCY_GUARDRAIL, LIVE_PROOF_GUARDRAIL, NO_NARRATION_RULE,
    ONPLATFORM_GUARDRAIL, PAINFUL_TEXTING, STYLE_3LINE, STYLE_BRIEF, STYLE_HUMANIZER,
    STYLE_MAX_BUBBLES,
)
from ._textutil import (  # noqa: F401
    BOT_ACCUSED_RE, detect_bot_accusation, has_emoji, is_substantive_msg, nonempty,
    strip_emojis, strip_inverted_punct,
)
from ._style_flags import (  # noqa: F401
    CONSISTENCY_AUTOMATIONS, STYLE_AUTOMATIONS,
    CAT_STICKERS_KEY, CAT_STICKER_GAP_MIN_KEY, CAT_STICKER_SKIP_PCT_KEY,
    CAT_STICKER_SOLO_PCT_KEY, FACTGROUND_KEY, PAINFUL_TEXTING_KEY,
    STYLE_CONSISTENCY_KEYS, STYLE_NONNATIVE_KEYS, STYLE_TYPO_KEYS, _STYLE_DEFAULT_ON,
    _STYLE_FORCE_OFF_ENV, _load_style_json, _parse_style_config, _resolve_style_flag,
    _style_default, _style_force_off, consistency_flag_key, load_cat_stickers_flag,
    load_consistency_flags, load_factground_flag, load_nonnative_flags,
    load_painful_texting_flag, load_spacing_flags, load_strip_emojis, load_style_flags,
    load_typo_flags, load_voice_blocks, nonnative_flag_key, spacing_flag_key,
    typo_flag_key,
)
from ._nonnative import (  # noqa: F401
    NONNATIVE_MISSPELLINGS, NONNATIVE_OUTPUTS, NONNATIVE_PHRASES, NONNATIVE_REGISTER,
    apply_nonnative_spacing, apply_nonnative_style,
)
from ._typos import (  # noqa: F401
    _TYPO_FIX_MIN_EXCHANGES, _TYPO_FIX_STATE_KEY, _humanize_typos_impl, _slip_is_ugly,
    _typo_correction_allowed, apply_typo_throttle, humanize_typos,
)
from ._typing_hold import (  # noqa: F401
    _DEFAULT_TYPING_WPM, _TYPING_REEMIT_S, hold_with_typing, load_typing_indicator,
    load_typing_wpm, typing_delay_seconds,
)
from ._fan_notes import (  # noqa: F401
    build_facts_note, build_rich_note, facts_from_fan, push_nick_and_notes,
    rich_note_cap, substitute_placeholders, template_fan_name,
)
from ._inbound import (  # noqa: F401
    MSG_CLIP, TURN_NEUTRAL_KINDS, TurnHandoff, _REACTION_TAG, inbound_is_words,
    worded_inbound_where,
)
from ._outbound_guard import (  # noqa: F401
    _OFF_DEFLECTIONS, _RESTRICTED_RE, _double_first_vowel, apply_word_restriction,
    guard_offplatform, scan_offplatform,
)
from ._intent import (  # noqa: F401
    CONTENT_ASK_RE, ESCALATION_RE, content_payer_fans, is_content_ask, is_escalation,
    norm_text, thread_heat,
)

# The fan-NAME cluster lives in names.py now (one concern, one file). Re-exported
# here because nine modules already import it from _common — names.py is the
# canonical home; this line is the bridge, not an abstraction.
from .names import (  # noqa: F401  (re-export)
    SPEND_TIERS, build_structured_nickname, is_greetable_name, is_place_word,
    name_token, resolve_fan_name,
)

__all__ = [
    "bool_knob",
    "test_mode",
    "coerce_ids",
    "SendOutcome",
    "is_media_rejected_error",
    "is_unreachable_fan_error",
    "quarantine_if_undeliverable",
    "send_dropping_bad_media",
    "send_dropping_bad_media_sync",
    "skip_unreachable_fan",
    "HARD_SKIP_REASONS",
    "LADDER_STOP_REASON",
    "MANUAL_RESTRICT_REASON",
    "MUTED_CREATOR_REASON",
    "OF_RESTRICTED_REASON",
    "_load_skip_ids",
    "automation_restrict_status",
    "classify_source",
    "is_hard_skipped",
    "load_hard_skip_ids",
    "load_of_restricted_ids",
    "load_promo_spam_ids",
    "mark_muted_creator_skip",
    "set_of_restricted_skip",
    "should_skip_muted_creator",
    "source_self_heal_set",
    "DEFAULT_MODEL",
    "MODEL_PURPOSES",
    "PURPOSE_DEFAULT_MODELS",
    "resolve_model",
    "BIO_CONSISTENCY_GUARDRAIL",
    "LIVE_PROOF_GUARDRAIL",
    "NO_NARRATION_RULE",
    "ONPLATFORM_GUARDRAIL",
    "PAINFUL_TEXTING",
    "STYLE_3LINE",
    "STYLE_BRIEF",
    "STYLE_HUMANIZER",
    "STYLE_MAX_BUBBLES",
    "BOT_ACCUSED_RE",
    "detect_bot_accusation",
    "has_emoji",
    "is_substantive_msg",
    "nonempty",
    "strip_emojis",
    "strip_inverted_punct",
    "CONSISTENCY_AUTOMATIONS",
    "STYLE_AUTOMATIONS",
    "CAT_STICKERS_KEY",
    "CAT_STICKER_GAP_MIN_KEY",
    "CAT_STICKER_SKIP_PCT_KEY",
    "CAT_STICKER_SOLO_PCT_KEY",
    "FACTGROUND_KEY",
    "PAINFUL_TEXTING_KEY",
    "STYLE_CONSISTENCY_KEYS",
    "STYLE_NONNATIVE_KEYS",
    "STYLE_TYPO_KEYS",
    "_STYLE_DEFAULT_ON",
    "_STYLE_FORCE_OFF_ENV",
    "_load_style_json",
    "_parse_style_config",
    "_resolve_style_flag",
    "_style_default",
    "_style_force_off",
    "consistency_flag_key",
    "load_cat_stickers_flag",
    "load_consistency_flags",
    "load_factground_flag",
    "load_nonnative_flags",
    "load_painful_texting_flag",
    "load_spacing_flags",
    "load_strip_emojis",
    "load_style_flags",
    "load_typo_flags",
    "load_voice_blocks",
    "nonnative_flag_key",
    "spacing_flag_key",
    "typo_flag_key",
    "NONNATIVE_MISSPELLINGS",
    "NONNATIVE_OUTPUTS",
    "NONNATIVE_PHRASES",
    "NONNATIVE_REGISTER",
    "apply_nonnative_spacing",
    "apply_nonnative_style",
    "_TYPO_FIX_MIN_EXCHANGES",
    "_TYPO_FIX_STATE_KEY",
    "_humanize_typos_impl",
    "_slip_is_ugly",
    "_typo_correction_allowed",
    "apply_typo_throttle",
    "humanize_typos",
    "_DEFAULT_TYPING_WPM",
    "_TYPING_REEMIT_S",
    "hold_with_typing",
    "load_typing_indicator",
    "load_typing_wpm",
    "typing_delay_seconds",
    "build_facts_note",
    "build_rich_note",
    "facts_from_fan",
    "push_nick_and_notes",
    "rich_note_cap",
    "substitute_placeholders",
    "template_fan_name",
    "MSG_CLIP",
    "TURN_NEUTRAL_KINDS",
    "_REACTION_TAG",
    "TurnHandoff",
    "inbound_is_words",
    "worded_inbound_where",
    "_OFF_DEFLECTIONS",
    "_RESTRICTED_RE",
    "_double_first_vowel",
    "apply_word_restriction",
    "guard_offplatform",
    "scan_offplatform",
    "CONTENT_ASK_RE",
    "ESCALATION_RE",
    "content_payer_fans",
    "is_content_ask",
    "is_escalation",
    "norm_text",
    "thread_heat",
    "SPEND_TIERS",
    "build_structured_nickname",
    "is_greetable_name",
    "is_place_word",
    "name_token",
    "resolve_fan_name",
]
