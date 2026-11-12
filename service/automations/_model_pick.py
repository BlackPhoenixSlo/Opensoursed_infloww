"""LLM model defaults + resolve_model."""
from __future__ import annotations

import json
import logging

import llm_client
import llm_providers
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
# question through the same call; `help_assistant_do` is its "Do it for me"
# form-fill draft, assistant_draft.py.)
MODEL_PURPOSES: tuple[str, ...] = (
    "gen_info", "welcome_chatter_for_info", "welcome", "followup",
    "help_assistant", "help_assistant_do",
)

# Purposes whose lane asks for `response_format: json_object` and resolves its
# model through `resolve_model` (gen_info.py, welcome_chatter_for_info.py's
# extraction, copilot_api.py). A model with `json_object_ok=False` is skipped
# at every resolve step for these and refused as a pin (account_config_rules).
# NOT `help_assistant_do`: the draft sends json_object only to a model that
# takes it and parses a Claude reply out of plain text (assistant_draft
# `parse_json_object`), so a Sonnet/Opus pin is allowed there (owner 2026-11-11).
JSON_OBJECT_PURPOSES: frozenset[str] = frozenset(
    {"gen_info", "welcome_chatter_for_info", "copilot"})


def model_fits(model: str | None, purpose: str) -> bool:
    """A real MODELS id this purpose can call (JSON lanes need json_object)."""
    mdl = llm_client.MODELS.get(model or "")
    return mdl is not None and (mdl.json_object_ok or purpose not in JSON_OBJECT_PURPOSES)


def _fits_or_warn(model: str | None, purpose: str, account_id: str, step: str) -> bool:
    if model_fits(model, purpose):
        return True
    if model in llm_client.MODELS:   # real model, wrong shape: say why it was skipped
        log.warning("resolve_model: %s %s cannot serve JSON purpose %s account=%s — "
                    "falling through", step, model, purpose, account_id)
    return False


# Purposes whose model must NOT follow the account brain, and what they run
# instead. This sits BETWEEN the operator's own `model_by_purpose` pin and
# `account_ai_config.model`: an explicit pin still wins, the brain no longer
# drags the route along behind it.
#
# `help_assistant` is here so the account brain cannot drag it along: ~28k
# tokens of manual ride on every call, so its bill is unlike any lane's, and
# it is priced on its own terms. With no Anthropic key it runs DeepSeek, whose
# prefix cache serves that manual at a measured 98.6% median hit (median
# `tokens_in` 28,418 over 228 logged calls), and there the cheapest model on a
# short chat turn is not the cheapest one here.
#
# 🚨 THE DEEPSEEK PIN IS A BET ON CACHING, NOT ON PRICE, and the difference
# matters because the price table says the opposite. Replayed through
# `_cost_millicents` over those 228 real calls, glm-5.3-flash AT THIS ROUTE'S
# OWN 98.6% HIT RATE costs 0.77x DeepSeek — cheaper. It only reaches 2.75x if it
# never caches at all, and in practice it barely does: 36 of 400 live GLM calls
# hit, 9%. So the pin is worth roughly 2.8x on that assumption alone. When every
# account's brain was switched to glm-5.3-flash, this line is the only thing
# that stopped the help bot going with it — but re-measure the GLM hit rate
# before trusting the number, because the whole justification rests on it.
# (The keyed Claude Opus default below does NOT cache at all; it is an opt-in
# quality choice, priced at the miss rate.)
#
# 🚨 Spelled out, NOT `DEFAULT_MODEL`. This is a PIN, and a pin whose value is a
# symbol designed to move is not one — the day the house default becomes a GLM,
# a line written to keep this route off GLM would quietly take it there.
# Retiring the id costs the CHOICE and never the exemption: being a key here is
# what lifts a purpose off the account brain, so a stale value falls to the
# house model, never back to `cfg.model`. See `resolve_model`.
#
# `help_assistant_do` (the help bot's form-fill draft, assistant_draft.py)
# rides with `help_assistant`: its small byte-stable prefix is a cache bet too.
# Unlike it, NO keyed Opus default: slot-fill needs no Opus
# (docs/spec/assistant-do-mode.md D3); an operator may still pin Sonnet/Opus.
PURPOSE_DEFAULT_MODELS: dict[str, str] = {
    "help_assistant": "deepseek-v4-flash",
    "help_assistant_do": "deepseek-v4-flash",
}


# A purpose default that moves to a better model when THIS account can pay that
# model's provider (read off MODELS) — never otherwise, so a deployment without
# the key behaves exactly as before. `help_assistant` → Claude Opus when an
# Anthropic key resolves (the agency's own, or the deployment's
# HELP_ASSISTANT_ANTHROPIC_KEY). The Anthropic compat layer does not cache, so
# this is ~100x the DeepSeek bill per question (~28k input tokens at the miss
# rate): keying it is opting in. A keyed default that fails (cap, key, provider)
# falls back once to the PURPOSE_DEFAULT_MODELS model — see
# `resolve_model_and_fallback`.
KEYED_PURPOSE_DEFAULTS: dict[str, str] = {
    "help_assistant": "claude-opus-5-5",
}


async def _provider_keyed(account_id: str, provider: str, purpose: str) -> bool:
    """Would a `purpose` call for this account find a `provider` key? "" account
    = the no-account help ask, billed to the asker's own key or the purpose
    fallback (never the house key), and only the fallback is visible here."""
    if not account_id:
        return bool(llm_providers.fallback_key(purpose, provider))
    try:
        return await llm_client.llm_key_available(account_id, provider, purpose)
    except Exception:
        log.warning("purpose_default: key check failed account=%s provider=%s",
                    account_id, provider, exc_info=True)
        return False


def _fixed_default(purpose: str) -> str:
    """The PURPOSE_DEFAULT_MODELS model, or the house model once it is retired."""
    fixed = PURPOSE_DEFAULT_MODELS[purpose]
    return fixed if fixed in llm_client.MODELS else DEFAULT_MODEL


async def _keyed_default(account_id: str, purpose: str) -> str | None:
    """The KEYED_PURPOSE_DEFAULTS model when this account has its provider's
    key, else None."""
    keyed = KEYED_PURPOSE_DEFAULTS.get(purpose)
    if keyed and (mdl := llm_client.MODELS.get(keyed)):
        if await _provider_keyed(account_id, mdl.provider, purpose):
            return keyed
    return None


async def purpose_default(account_id: str, purpose: str) -> str:
    """What `purpose` (a PURPOSE_DEFAULT_MODELS key) runs on this account with
    no operator pin. Always a MODELS id — see resolve_model on retired ids."""
    return await _keyed_default(account_id, purpose) or _fixed_default(purpose)


async def resolve_model(account_id: str, purpose: str, override: str | None = None) -> str:
    """The model one run calls; see `resolve_model_and_fallback`."""
    return (await resolve_model_and_fallback(account_id, purpose, override))[0]


async def resolve_model_and_fallback(
        account_id: str, purpose: str, override: str | None = None,
) -> tuple[str, str | None]:
    """Resolve the LLM model for one automation run, VALIDATED against
    llm_client.MODELS at every step so a stale/typo value can never reach
    llm_client.chat (where it would fail every fan with LLMConfigError).

    Precedence: payload `override` → account_ai_config.model_by_purpose[purpose]
    → purpose_default (KEYED_PURPOSE_DEFAULTS, else PURPOSE_DEFAULT_MODELS) → account_ai_config.model → DEFAULT_MODEL.
    TOTAL: a value not in MODELS is skipped and a config read that fails is
    logged, both falling through to the house model, so resolution always yields
    a usable model and never raises.

    The second value is what to retry on ONCE when the first fails on a cap, a
    key or the provider: the PURPOSE_DEFAULT_MODELS model when the first is a
    KEYED default (an opt-in upgrade must not take the route down with its
    budget or key), else None — an override, an operator pin, the brain and the
    house model are choices, and a failed choice is reported, not swapped.

    The purpose default outranking the brain is deliberate and is the ONLY step
    an operator cannot see in a dropdown — see PURPOSE_DEFAULT_MODELS for the
    one route that needs it and why. Every purpose absent from that map behaves
    exactly as before.

    `purpose` is a MODEL_PURPOSES key when an operator can pin it; any other
    string simply finds no override and falls through, which is what the lanes
    with no dropdown (content_resolver, pins) rely on.
    """
    if override and _fits_or_warn(override, purpose, account_id, "override"):
        return override, None
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
        return DEFAULT_MODEL, None
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
        if chosen and _fits_or_warn(chosen, purpose, account_id, "pin"):
            return chosen, None
    if purpose in PURPOSE_DEFAULT_MODELS:
        # MEMBERSHIP decides, not the value's validity — this branch must be
        # TERMINAL. Written as `if fixed in MODELS: return fixed`, a retired
        # model id (this repo has retired one already: grok-4-1-fast) fell
        # through to `cfg.model`, which is glm-5.3-flash on every live account.
        # That is exactly and only the outcome the map exists to prevent, and it
        # would have happened silently, at ~2.8x, the day someone tidied MODELS.
        keyed, fixed = await _keyed_default(account_id, purpose), _fixed_default(purpose)
        return (keyed, fixed) if keyed else (fixed, None)
    if cfg is not None and cfg.model and _fits_or_warn(cfg.model, purpose, account_id, "brain"):
        return cfg.model, None
    return DEFAULT_MODEL, None
