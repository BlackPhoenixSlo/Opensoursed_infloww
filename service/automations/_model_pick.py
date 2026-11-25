from __future__ import annotations

import json
import logging

import llm_client
import llm_providers
from automation_registry import LEGACY_KINDS
from db.engine import get_session
from db.models import AccountAiConfig

log = logging.getLogger("of-relay.automation.common")


DEFAULT_MODEL = "deepseek-v4-flash"

# An entry is only ever the string its lane passes to resolve_model, never the automation kind.
MODEL_PURPOSES: tuple[str, ...] = (
    "gen_info", "welcome_chatter_for_info", "welcome", "followup",
    "help_assistant", "help_assistant_do",
)

JSON_OBJECT_PURPOSES: frozenset[str] = frozenset(
    {"gen_info", "welcome_chatter_for_info", "copilot"})


def model_fits(model: str | None, purpose: str) -> bool:
    mdl = llm_client.MODELS.get(model or "")
    return mdl is not None and (mdl.json_object_ok or purpose not in JSON_OBJECT_PURPOSES)


def _fits_or_warn(model: str | None, purpose: str, account_id: str, step: str) -> bool:
    if model_fits(model, purpose):
        return True
    if model in llm_client.MODELS:
        log.warning("resolve_model: %s %s cannot serve JSON purpose %s account=%s — "
                    "falling through", step, model, purpose, account_id)
    return False


PURPOSE_DEFAULT_MODELS: dict[str, str] = {
    # help_assistant pin is a bet on DeepSeek prefix caching (~98.6% hit on the 28k-token manual); spelled out, not DEFAULT_MODEL, so it never moves with the house default.
    "help_assistant": "deepseek-v4-flash",
    "help_assistant_do": "deepseek-v4-flash",
    "full_ai_persona": "deepseek-v4-flash",
}


KEYED_PURPOSE_DEFAULTS: dict[str, str] = {
    "help_assistant": "claude-opus-5-5",
}


async def _provider_keyed(account_id: str, provider: str, purpose: str) -> bool:
    if not account_id:
        return bool(llm_providers.fallback_key(purpose, provider))
    try:
        return await llm_client.llm_key_available(account_id, provider, purpose)
    except Exception:
        log.warning("purpose_default: key check failed account=%s provider=%s",
                    account_id, provider, exc_info=True)
        return False


def _fixed_default(purpose: str) -> str:
    fixed = PURPOSE_DEFAULT_MODELS[purpose]
    # Membership is terminal: a retired id falls to the house model, never to cfg.model.
    return fixed if fixed in llm_client.MODELS else DEFAULT_MODEL


async def _keyed_default(account_id: str, purpose: str) -> str | None:
    keyed = KEYED_PURPOSE_DEFAULTS.get(purpose)
    if keyed and (mdl := llm_client.MODELS.get(keyed)):
        if await _provider_keyed(account_id, mdl.provider, purpose):
            return keyed
    return None


async def purpose_default(account_id: str, purpose: str) -> str:
    return await _keyed_default(account_id, purpose) or _fixed_default(purpose)


async def resolve_model(account_id: str, purpose: str, override: str | None = None) -> str:
    return (await resolve_model_and_fallback(account_id, purpose, override))[0]


async def resolve_model_and_fallback(
        account_id: str, purpose: str, override: str | None = None,
) -> tuple[str, str | None]:
    if override and _fits_or_warn(override, purpose, account_id, "override"):
        return override, None
    try:
        async with get_session() as s:
            cfg = await s.get(AccountAiConfig, account_id)
    except Exception:
        log.warning("resolve_model: config read failed account=%s purpose=%s — "
                    "using %s", account_id, purpose, DEFAULT_MODEL, exc_info=True)
        return DEFAULT_MODEL, None
    if cfg is not None and cfg.model_by_purpose:
        try:
            by_purpose = json.loads(cfg.model_by_purpose) or {}
            chosen = by_purpose.get(purpose)
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
        keyed, fixed = await _keyed_default(account_id, purpose), _fixed_default(purpose)
        return (keyed, fixed) if keyed else (fixed, None)
    if cfg is not None and cfg.model and _fits_or_warn(cfg.model, purpose, account_id, "brain"):
        return cfg.model, None
    return DEFAULT_MODEL, None
