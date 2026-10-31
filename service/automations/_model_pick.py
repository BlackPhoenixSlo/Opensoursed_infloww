"""LLM model defaults + resolve_model."""
from __future__ import annotations

import json
import logging

import llm_client
from automation_registry import LEGACY_KINDS
from db.engine import get_session
from db.models import AccountAiConfig

log = logging.getLogger("of-relay.automation.common")


# Default model for every account without an explicit brain `model`. DeepSeek is
# the house default now (the Grok provider was removed in cleanup Q20). One
# source of truth for every sender (resolve_model).
DEFAULT_MODEL = "deepseek-v4-flash"

# The purposes an operator may PIN a model to, i.e. the keys `resolve_model`
# below will look up in `account_ai_config.model_by_purpose`. The editors render
# their dropdowns off this list (served by account_config_api).
#
# It lives HERE, next to its only reader, because when the offer list and the
# reader were two hand-maintained copies in two packages they drifted in
# silence: the editors offered "send_welcome"/"send_followup" while the lanes
# asked for "welcome"/"followup", so those two dropdowns wrote a key nothing
# ever read and an operator who picked a model there watched the lane keep
# running the default. Fixed 2026-08-28 — no account had model_by_purpose set,
# so the rename lost no setting.
#
# 🚨 An entry is ONLY ever the string its lane passes to `resolve_model`. Never
# the automation kind, never the grok_calls purpose tag, when those differ.
# (`help_assistant` is the in-product help bot, not a lane, but it asks the same
# question through the same call.)
MODEL_PURPOSES: tuple[str, ...] = (
    "gen_info", "welcome_chatter_for_info", "welcome", "followup",
    "help_assistant",
)

# Purposes whose model must NOT follow the account brain, and what they run
# instead. This sits BETWEEN the operator's own `model_by_purpose` pin and
# `account_ai_config.model`: an explicit pin still wins, the brain no longer
# drags the route along behind it.
#
# `help_assistant` is here because it is priced unlike any lane. ~28k byte-stable
# tokens of manual ride on every call at a measured 98.6% median cache hit
# (median `tokens_in` 28,418 over 228 logged calls), so the bill is almost
# entirely the provider's CACHED-INPUT rate, and the cheapest model on a short
# chat turn is not the cheapest one here.
#
# 🚨 THE PIN IS A BET ON CACHING, NOT ON PRICE, and the difference matters
# because the price table says the opposite. Replayed through
# `_cost_millicents` over those 228 real calls, glm-5.3-flash AT THIS ROUTE'S
# OWN 98.6% HIT RATE costs 0.77x DeepSeek — cheaper. It only reaches 2.75x if it
# never caches at all, and in practice it barely does: 36 of 400 live GLM calls
# hit, 9%. So the pin is worth roughly 2.8x on that assumption alone. When every
# account's brain was switched to glm-5.3-flash, this line is the only thing
# that stopped the help bot going with it — but re-measure the GLM hit rate
# before trusting the number, because the whole justification rests on it.
#
# 🚨 Spelled out, NOT `DEFAULT_MODEL`. This is a PIN, and a pin whose value is a
# symbol designed to move is not one — the day the house default becomes a GLM,
# a line written to keep this route off GLM would quietly take it there.
# Retiring the id costs the CHOICE and never the exemption: being a key here is
# what lifts a purpose off the account brain, so a stale value falls to the
# house model, never back to `cfg.model`. See `resolve_model`.
PURPOSE_DEFAULT_MODELS: dict[str, str] = {
    "help_assistant": "deepseek-v4-flash",
}


async def resolve_model(account_id: str, purpose: str, override: str | None = None) -> str:
    """Resolve the LLM model for one automation run, VALIDATED against
    llm_client.MODELS at every step so a stale/typo value can never reach
    llm_client.chat (where it would fail every fan with LLMConfigError).

    Precedence: payload `override` → account_ai_config.model_by_purpose[purpose]
    → PURPOSE_DEFAULT_MODELS[purpose] → account_ai_config.model → DEFAULT_MODEL.
    TOTAL: a value not in MODELS is skipped and a config read that fails is
    logged, both falling through to the house model, so resolution always yields
    a usable model and never raises.

    The purpose default outranking the brain is deliberate and is the ONLY step
    an operator cannot see in a dropdown — see PURPOSE_DEFAULT_MODELS for the
    one route that needs it and why. Every purpose absent from that map behaves
    exactly as before.

    `purpose` is a MODEL_PURPOSES key when an operator can pin it; any other
    string simply finds no override and falls through, which is what the lanes
    with no dropdown (content_resolver, pins) rely on.
    """
    if override and override in llm_client.MODELS:
        return override
    try:
        async with get_session() as s:
            cfg = await s.get(AccountAiConfig, account_id)
    except Exception:
        # "Always yields a usable model" is this function's contract, and a
        # config READ fails the same way a config VALUE goes stale — the caller
        # can do nothing useful with either. Every caller is a live send or an
        # operator waiting on an answer, and none is better off dying than
        # running the house model, so the total contract covers both.
        log.warning("resolve_model: config read failed account=%s purpose=%s — "
                    "using %s", account_id, purpose, DEFAULT_MODEL, exc_info=True)
        return DEFAULT_MODEL
    if cfg is not None and cfg.model_by_purpose:
        try:
            by_purpose = json.loads(cfg.model_by_purpose) or {}
            chosen = by_purpose.get(purpose)
            # Legacy keys: a blob written before a kind rename (see
            # automation_registry.LEGACY_KINDS) still keys the override by
            # the old name. No-ops once LEGACY_KINDS empties.
            if chosen is None:
                for legacy, live in LEGACY_KINDS.items():
                    if purpose == live:
                        chosen = by_purpose.get(legacy)
                        break
        except Exception:
            chosen = None
            log.warning("bad_model_by_purpose account=%s purpose=%s", account_id, purpose)
        if chosen and chosen in llm_client.MODELS:
            return chosen
    if purpose in PURPOSE_DEFAULT_MODELS:
        # MEMBERSHIP decides, not the value's validity — this branch must be
        # TERMINAL. Written as `if fixed in MODELS: return fixed`, a retired
        # model id (this repo has retired one already: grok-4-1-fast) fell
        # through to `cfg.model`, which is glm-5.3-flash on every live account.
        # That is exactly and only the outcome the map exists to prevent, and it
        # would have happened silently, at ~2.8x, the day someone tidied MODELS.
        fixed = PURPOSE_DEFAULT_MODELS[purpose]
        return fixed if fixed in llm_client.MODELS else DEFAULT_MODEL
    if cfg is not None and cfg.model and cfg.model in llm_client.MODELS:
        return cfg.model
    return DEFAULT_MODEL
