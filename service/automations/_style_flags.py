from __future__ import annotations

import json

from automation_registry import LEGACY_KINDS
from db.engine import get_session
from db.models import AccountAiConfig

from . import _voice


STYLE_AUTOMATIONS = ("welcome_chatter_for_info", "autoreply")

# Only engines that call verify_self_consistency; widen in the commit that adds the call (test_consistency_check.case_no_inert_flags).
CONSISTENCY_AUTOMATIONS = ("welcome_chatter_for_info",)


_STYLE_DEFAULT_ON: dict[str, bool] = {"autoreply": True}

# Panic switch: forces every realism flag False for all accounts regardless of stored config.
_STYLE_FORCE_OFF_ENV = "STYLE_FORCE_OFF"


def _style_force_off() -> bool:
    import runtime_switches
    return runtime_switches.on(_STYLE_FORCE_OFF_ENV)


def _style_default(automation: str) -> bool:
    return _STYLE_DEFAULT_ON.get(automation, False)


def _parse_style_config(raw) -> dict:
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
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    return _parse_style_config(getattr(cfg, col, None) if cfg else None)


async def _load_style_json(account_id: str) -> dict:
    return await _load_json_col(account_id, "style_config_json")


def _resolve_style_flag(stored: dict, automation: str, key: str) -> bool:
    if key in stored:
        return bool(stored.get(key))
    return _style_default(automation)


async def load_style_flags(account_id: str) -> dict[str, bool]:
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    stored = await _load_style_json(account_id)
    return {k: _resolve_style_flag(stored, k, k) for k in STYLE_AUTOMATIONS}


async def load_painful_texting_flag(account_id: str) -> bool:
    if _style_force_off():
        return False
    val = (await _load_style_json(account_id)).get(PAINFUL_TEXTING_KEY)
    return True if val is None else bool(val)


async def load_voice_blocks(account_id: str) -> "_voice.VoiceBlocks":
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    return _voice.blocks(getattr(cfg, "voice", None) if cfg else None)


async def load_cat_stickers_flag(account_id: str) -> bool:
    if _style_force_off():
        return False
    val = (await _load_style_json(account_id)).get(CAT_STICKERS_KEY)
    return True if val is None else bool(val)


async def load_strip_emojis(account_id: str) -> bool:
    return bool((await _load_style_json(account_id)).get("strip_emojis"))


def typo_flag_key(automation: str) -> str:
    return f"typos_{automation}"


STYLE_TYPO_KEYS = tuple(typo_flag_key(k) for k in STYLE_AUTOMATIONS)


async def load_typo_flags(account_id: str) -> dict[str, bool]:
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    stored = await _load_style_json(account_id)
    return {k: _resolve_style_flag(stored, k, typo_flag_key(k)) for k in STYLE_AUTOMATIONS}


def nonnative_flag_key(automation: str) -> str:
    return f"nonnative_{automation}"


STYLE_NONNATIVE_KEYS = tuple(nonnative_flag_key(k) for k in STYLE_AUTOMATIONS)


def spacing_flag_key(automation: str) -> str:
    return f"nonnative_spacing_{automation}"


async def load_spacing_flags(account_id: str) -> dict[str, bool]:
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    stored = _parse_style_config(getattr(cfg, "style_config_json", None) if cfg else None)
    return {k: _resolve_style_flag(stored, k, spacing_flag_key(k)) for k in STYLE_AUTOMATIONS}


def consistency_flag_key(automation: str) -> str:
    return f"consistency_{automation}"


STYLE_CONSISTENCY_KEYS = tuple(consistency_flag_key(k) for k in CONSISTENCY_AUTOMATIONS)


async def load_consistency_flags(account_id: str) -> dict[str, bool]:
    if _style_force_off():
        return {k: False for k in CONSISTENCY_AUTOMATIONS}
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    stored = _parse_style_config(getattr(cfg, "style_config_json", None) if cfg else None)
    # Off unless explicit: this one costs a second LLM call, so never take it from the default map.
    return {k: bool(stored.get(consistency_flag_key(k), False))
            for k in CONSISTENCY_AUTOMATIONS}


async def load_nonnative_flags(account_id: str) -> dict[str, bool]:
    if _style_force_off():
        return {k: False for k in STYLE_AUTOMATIONS}
    stored = await _load_style_json(account_id)
    return {k: _resolve_style_flag(stored, k, nonnative_flag_key(k)) for k in STYLE_AUTOMATIONS}


FACTGROUND_KEY = "factground_welcome_chatter_for_info"
PAINFUL_TEXTING_KEY = "painful_texting"
CAT_STICKERS_KEY = "cat_stickers"
CAT_STICKER_SKIP_PCT_KEY = "cat_sticker_skip_pct"
CAT_STICKER_SOLO_PCT_KEY = "cat_sticker_solo_pct"
CAT_STICKER_GAP_MIN_KEY = "cat_sticker_gap_min"


async def load_factground_flag(account_id: str) -> bool:
    # A stored null reads False (bool(None)): only the retired settings import can write one.
    return bool((await _load_style_json(account_id)).get(FACTGROUND_KEY, True))
