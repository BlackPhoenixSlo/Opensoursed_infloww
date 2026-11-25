from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values, load_dotenv

_HERE = Path(__file__).resolve().parent
_ENV_FILE = _HERE / ".env"
load_dotenv(_ENV_FILE, override=False)


@dataclass(frozen=True)
class LLMProvider:
    name: str
    base_url: str
    api_key_env: str
    wire: Literal["openai", "anthropic"] = "openai"


PROVIDERS: dict[str, LLMProvider] = {
    "deepseek": LLMProvider("deepseek", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "deepinfra": LLMProvider("deepinfra", "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY"),
    # Z.ai's documented OpenAI-compat URL answers HTTP 200 with a 404 body; this is the URL that works.
    "zai": LLMProvider("zai", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
    # Native Messages API: the OpenAI-compat layer does not prompt-cache (help bot's ~39k-token prompt billed in full).
    "anthropic": LLMProvider("anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY",
                             wire="anthropic"),
    # ASSUMPTION: base URLs not probed yet.
    "nanogpt": LLMProvider("nanogpt", "https://nano-gpt.com/api/v1", "NANOGPT_API_KEY"),
    "openrouter": LLMProvider("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}


# compose passes `${KEY:-}` as an empty string, so load_dotenv(override=False) never backfills it: read service/.env directly.
def _api_key(env_name: str) -> str:
    try:
        from secrets_store import stored as _stored
        s = _stored(env_name)
        if s:
            return s
    except Exception:
        pass
    val = (os.environ.get(env_name) or "").strip()
    if val:
        return val
    try:
        return (dotenv_values(_ENV_FILE).get(env_name) or "").strip()
    except Exception:  # pragma: no cover — never let key lookup crash the caller
        return ""


# Env id deliberately not DEEPSEEK_API_KEY: widening the house key would bill us for keyless agencies' sending; empty restores fail-closed.
_FALLBACK_KEY_ENVS: dict[tuple[str, str], str] = {
    ("help_assistant", "deepseek"): "HELP_ASSISTANT_DEEPSEEK_KEY",
    # Shares the Q&A credential (owner call): one small cached call, bounded by the account's daily cost cap.
    ("help_assistant_do", "deepseek"): "HELP_ASSISTANT_DEEPSEEK_KEY",
    ("help_assistant", "anthropic"): "HELP_ASSISTANT_ANTHROPIC_KEY",
}


def fallback_key(purpose: str, provider: str) -> str:
    env = _FALLBACK_KEY_ENVS.get((purpose, provider))
    return _api_key(env) if env else ""


def house_key(provider: str) -> str:
    prov = PROVIDERS.get(provider)
    if prov is None:
        return ""
    return _api_key(prov.api_key_env)


TYPESAFE = "typesafe"
TYPESAFE_KEY_ENV = "TYPESAFE_API_KEY"

TENANT_KEY_PROVIDERS = sorted({*PROVIDERS, TYPESAFE})


def typesafe_key() -> str:
    return _api_key(TYPESAFE_KEY_ENV)
