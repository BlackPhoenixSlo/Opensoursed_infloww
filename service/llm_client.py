from __future__ import annotations

import json
import asyncio
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select, update as sa_update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import llm_anthropic
import model_cap
import tenant_keys
from db.engine import get_session
from db.models import AccountAiConfig, GrokCall, GrokDailyCost, GrokUserDailyCost
from llm_providers import (
    LLMProvider, PROVIDERS, fallback_key, house_key)

log = logging.getLogger("of-relay.llm_client")

from llm_models import LLMModel, MODELS  # noqa: E402,F401


_CHARS_PER_TOKEN = 4
_ASSUMED_OUTPUT_TOKENS = 1024
# grok_calls / grok_*daily_cost `cost_cents` hold MILLICENTS (cents x100): whole cents floored sub-cent DeepSeek calls to 0.
_MILLICENTS_PER_CENT = 100
_DEFAULT_CAP_CENTS = 100
_REQUEST_TIMEOUT_S = 120.0

# Only transient faults retry (timeout, transport, 429, 5xx); 4xx fails fast. Cap reservation and audit row are made once, outside the retry loop.
_LLM_MAX_ATTEMPTS = 3
_LLM_RETRY_BACKOFF_S = 1.5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)



class LLMError(Exception):
    pass


class LLMConfigError(LLMError):
    pass


class LLMCapExceeded(LLMError):

    def __init__(self, account_id: str | None, cap_cents: int, would_be_cents: int):
        self.account_id = account_id
        self.cap_cents = cap_cents
        self.would_be_cents = would_be_cents
        super().__init__(
            f"daily LLM cost cap reached for account={account_id!r}: "
            f"{would_be_cents}c would exceed cap {cap_cents}c"
        )


class LLMHTTPError(LLMError):

    def __init__(self, message: str, *, status: int | None = None):
        self.status = status
        super().__init__(message)


class LLMModelCapTimeout(LLMHTTPError):

    def __init__(self, waited_s: float, cap: int):
        self.waited_s, self.cap = waited_s, cap
        super().__init__(f"model-call cap: waited {waited_s:.1f}s (cap {cap})", status=None)


class LLMKeyError(LLMConfigError, LLMHTTPError):

    def __init__(self, kind: str, provider: str, purpose: str = "", *,
                 status: int | None = None, detail: str = "",
                 house: bool = False):
        self.kind = kind
        self.provider = provider
        self.purpose = purpose
        self.house = house
        LLMHTTPError.__init__(self, detail or f"{provider} API key {kind}",
                              status=status)


# A key refusal never succeeds on re-fire: not retried, the caller is told which. 429 stays transient.
_KEY_STATUS = {401: "invalid", 403: "invalid", 402: "no_credit"}



@dataclass(frozen=True)
class Retry:
    pause_s: float


@dataclass(frozen=True)
class KeyErr:
    kind: str


@dataclass(frozen=True)
class Fail:
    reason: str


def llm_attempt_outcome(status_or_exc_kind: int | str, attempt: int,
                        max_attempts: int) -> Retry | KeyErr | Fail:
    last = attempt + 1 >= max_attempts
    if isinstance(status_or_exc_kind, str) or status_or_exc_kind in _RETRYABLE_STATUS:
        if not last:
            return Retry(_LLM_RETRY_BACKOFF_S * (attempt + 1))
        return Fail("attempts_exhausted")
    kind = _KEY_STATUS.get(status_or_exc_kind)
    if kind:
        return KeyErr(kind)
    return Fail("not_retryable")

KEY_FIX_URL = "/settings/ai-keys"
DESCRIBE_BUDGET = "describe"
_DESCRIBE_PURPOSES = frozenset({"describe_media", "describe_flags", "vault_jev_flags"})


# Vault prep spends its own daily budget row so a vault sweep never starves chats (owner decision).
def budget_key(purpose: str) -> str:
    return DESCRIBE_BUDGET if purpose in _DESCRIBE_PURPOSES else "chat"


PROVIDER_LABELS = {"deepseek": "DeepSeek", "deepinfra": "DeepInfra",
                    "zai": "Z.ai (GLM)", "anthropic": "Anthropic (Claude)",
                    "typesafe": "TypeSafe (Jev)"}
_FEATURE_LABELS = {
    "describe_media": "Vault describe", "describe_flags": "Vault describe",
    "describe_inbound_image": "Photo describe",
    "full_ai_test_photo": "Full AI test photo",
    "customs_brief": "Customs brief",
    "help_assistant": "The help assistant",
    "help_assistant_do": "The help assistant",
    "autoreply": "Auto-reply", "reply_mass_funnel": "Auto Funnel",
    # Named as the sidebar names their pages (app/lib/nav.ts).
    "welcome_chatter_for_info": "Get to know fans", "followup": "Follow-ups",
    "gen_info": "Gen-Info",
    "full_ai_persona": "Full AI persona draft",
    "ultra_plan": "Ultra planning", "ultra_judge": "Ultra AI pick",
    "support_summary": "Support summary",
}


def feature_label(purpose: str) -> str:
    return _FEATURE_LABELS.get(purpose or "", "This AI feature")


def key_error_payload(exc: "LLMKeyError", *, feature: str = "") -> dict[str, Any]:
    feature = feature or feature_label(exc.purpose)
    prov = PROVIDER_LABELS.get(exc.provider, exc.provider)
    if exc.kind == "invalid":
        message = f"{feature} stopped: {prov} rejected the API key (wrong or revoked)."
        fix = "Paste the right key in Settings › AI keys."
    elif exc.kind == "no_credit":
        message = f"{feature} stopped: the {prov} account behind the API key is out of credit."
        fix = f"Top it up at {prov}, or paste another key in Settings › AI keys."
    else:
        message = f"{feature} can't run: no {prov} API key is set."
        fix = ("Add it in Settings › AI keys — for a house account a master "
               "sets it in Settings › System." if exc.house
               else "Add it in Settings › AI keys.")
    return {"error": f"api_key_{exc.kind}", "feature": feature,
            "provider": exc.provider, "fix_url": KEY_FIX_URL,
            "message": message, "fix": fix}


def failure(exc: BaseException, *, capped_text: str, provider_text: str) -> tuple[bool, str] | None:
    if isinstance(exc, LLMCapExceeded):
        return True, capped_text
    if isinstance(exc, LLMKeyError):
        p = key_error_payload(exc)
        return False, f"{p['message']} {p['fix']}"
    if isinstance(exc, LLMHTTPError):
        return False, provider_text
    return None



@dataclass
class LLMResult:
    call_id: int | None
    model: str
    provider: str
    content: str
    parsed: Any | None
    reasoning_content: str | None
    tokens_in: int | None
    tokens_out: int | None
    cache_hit_tokens: int | None
    cost_cents: int
    latency_ms: int
    raw: dict = field(repr=False, default_factory=dict)
    # Tokens written to the provider cache (Anthropic bills 1.25x input).
    cache_write_tokens: int | None = None
    tool_calls: list[dict] = field(default_factory=list)



def _resolve(model: str) -> tuple[LLMModel, LLMProvider]:
    mdl = MODELS.get(model)
    if mdl is None:
        raise LLMConfigError(
            f"unknown model {model!r}; known: {sorted(MODELS)}"
        )
    prov = PROVIDERS.get(mdl.provider)
    if prov is None:
        raise LLMConfigError(
            f"model {model!r} maps to unknown provider {mdl.provider!r}"
        )
    return mdl, prov


def _resolve_effort(mdl: LLMModel, requested: str, stored: str = "") -> str:
    effort = (requested or stored or mdl.reasoning_effort or "").strip()
    if not effort:
        return ""
    if effort not in mdl.effort_choices:
        raise LLMConfigError(
            f"reasoning_effort {effort!r} is not valid for model {mdl.id!r}; "
            f"it accepts {list(mdl.effort_choices) or 'no effort at all'}"
        )
    return effort


def effort_options(model: str) -> list[str]:
    mdl = MODELS.get(model)
    return list(mdl.effort_choices) if mdl else []


def effort_options_by_model() -> dict[str, list[str]]:
    return {mid: list(m.effort_choices) for mid, m in MODELS.items()}


async def _account_effort(account_id: str, mdl: LLMModel) -> str:
    if not account_id or not mdl.effort_choices:
        return ""
    async with get_session() as s:
        val = await s.scalar(
            select(AccountAiConfig.reasoning_effort).where(
                AccountAiConfig.account_id == account_id
            )
        )
    saved = (val or "").strip()
    if saved and saved not in mdl.effort_choices:
        log.warning("stored reasoning_effort %r does not fit model %s %s — "
                    "using the model default %r",
                    saved, mdl.id, list(mdl.effort_choices), mdl.reasoning_effort)
        return ""
    return saved


async def _tenant_api_key(account_id: str, prov: LLMProvider,
                          purpose: str = "") -> str:
    owners = await tenant_keys.owners_of(account_id)
    # Two agencies linked to one creator is reachable by design: bill the one holding a key, refuse only when more than one does.
    if len(owners) > 1:
        keyed = await tenant_keys.keyed_providers(owners)
        payer = tenant_keys.payer_for(owners, keyed, prov.name)
        if payer:
            log.info("shared_account_billed provider=%s account=%s owner=%s "
                     "of=%s", prov.name, account_id, payer, ",".join(owners))
            owners = [payer]
        elif any(prov.name in keyed.get(o, ()) for o in owners):
            raise LLMConfigError(
                f"account {account_id!r} has more than one owner with a "
                f"{prov.name!r} key — cannot tell which agency to bill"
            )
    # House key only for ownerless accounts: an owned one never falls through to it.
    if not owners:
        key = house_key(prov.name)
        if not key:
            raise LLMKeyError(
                "missing", prov.name, purpose, house=True, detail=(
                    f"{prov.api_key_env} is missing/empty — cannot call provider "
                    f"{prov.name!r} for un-owned account {account_id!r}"))
        return key
    owner = owners[0]
    key = await tenant_keys.get_key(owner, prov.name) if len(owners) == 1 else ""
    if not key:
        shared = fallback_key(purpose, prov.name)
        if shared:
            log.info("fallback_key_used purpose=%s provider=%s account=%s "
                     "owner=%s — billed to THIS DEPLOYMENT, not the agency",
                     purpose, prov.name, account_id, owner)
            return shared
        log.warning("tenant_key_missing provider=%s account=%s owner=%s",
                    prov.name, account_id, ",".join(owners))
        who = (f"agency {owner!r} has" if len(owners) == 1
               else f"none of the owners {owners} has")
        raise LLMKeyError("missing", prov.name, purpose, detail=(
            f"{who} no {prov.name!r} API key — add it in "
            f"Settings → AI keys (account {account_id!r})"))
    return key


async def _user_api_key(user_id: str, prov: LLMProvider, purpose: str) -> str:
    # Never house_key here: the asker is a tenant, so it would make the deployment pay for anything any signup sends.
    key = await tenant_keys.get_key(user_id, prov.name) or fallback_key(purpose, prov.name)
    if key:
        return key
    log.warning("tenant_key_missing provider=%s account=- owner=%s", prov.name, user_id)
    raise LLMKeyError("missing", prov.name, purpose, detail=(
        f"agency {user_id!r} has no {prov.name!r} API key — add it in "
        f"Settings → AI keys (no account)"))


async def llm_key_available(account_id: str, provider: str,
                            purpose: str = "") -> bool:
    prov = PROVIDERS.get(provider)
    if prov is None:
        return False
    owners = await tenant_keys.owners_of(account_id)
    if not owners:
        return bool(house_key(prov.name))
    if fallback_key(purpose, prov.name):
        return True
    keyed = await tenant_keys.keyed_providers(owners)
    return tenant_keys.payer_for(owners, keyed, prov.name) is not None


# An image costs hundreds-thousands of tokens, not its string length; flat estimate keeps the pre-flight cap reservation honest.
_IMAGE_TOKENS = 1200


def _estimate_input_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    chars = len(json.dumps(tools, default=str)) if tools else 0
    image_tokens = 0
    for m in messages:
        if m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"], default=str))
        c = m.get("content", "")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_tokens += _IMAGE_TOKENS
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
                else:
                    chars += len(json.dumps(part, default=str))
        else:
            chars += len(json.dumps(c, default=str))
    return chars // _CHARS_PER_TOKEN + image_tokens + 1


def _cost_millicents(model: str, tokens_in: int, tokens_out: int,
                     cache_hit_tokens: int = 0, cache_write_tokens: int = 0) -> int:
    mdl = MODELS.get(model)
    if mdl is None:
        return 0
    hit = max(0, min(cache_hit_tokens, tokens_in))
    write = max(0, min(cache_write_tokens, tokens_in - hit))
    miss = tokens_in - hit - write
    cents = (
        miss / 1000.0 * mdl.input_per_1k_cents
        + hit / 1000.0 * mdl.input_cache_hit_per_1k_cents
        + write / 1000.0 * (mdl.input_cache_write_per_1k_cents or mdl.input_per_1k_cents)
        + tokens_out / 1000.0 * mdl.output_per_1k_cents
    )
    return int(round(cents * _MILLICENTS_PER_CENT))


def _reserve_out_tokens(model: str, max_tokens: int | None = None) -> int:
    if max_tokens:
        return max_tokens
    mdl = MODELS.get(model)
    prov = PROVIDERS.get(mdl.provider) if mdl else None
    if prov is not None and prov.wire == "anthropic":
        return llm_anthropic.MAX_TOKENS
    return _ASSUMED_OUTPUT_TOKENS


def _reserve_millicents(model: str, tokens_in: int, max_tokens: int | None = None) -> int:
    mdl = MODELS.get(model)
    if mdl is None:
        return 0
    write = tokens_in if mdl.input_cache_write_per_1k_cents > mdl.input_per_1k_cents else 0
    return _cost_millicents(model, tokens_in, _reserve_out_tokens(model, max_tokens), 0, write)


def _cache_hit_tokens(usage: dict) -> int | None:
    top = usage.get("prompt_cache_hit_tokens")
    if top is not None:
        return top
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        return details.get("cached_tokens")
    return None


def _reasoning_tokens(usage: dict) -> int | None:
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        return details.get("reasoning_tokens")
    return None


def _clean_content(text: str) -> str:
    if not text:
        return text
    text = _THINK_RE.sub("", text).strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    return text


async def _get_cap_cents(account_id: str | None) -> int:
    if not account_id:
        return _DEFAULT_CAP_CENTS
    async with get_session() as s:
        cap = await s.scalar(
            select(AccountAiConfig.daily_cost_cap_cents).where(
                AccountAiConfig.account_id == account_id
            )
        )
    return int(cap) if cap is not None else _DEFAULT_CAP_CENTS


async def cap_state(account_id: str | None, provider: str,
                    model: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
    provider = provider if provider == DESCRIBE_BUDGET else "chat"
    day = datetime.utcnow().strftime("%Y-%m-%d")
    cap_mc = int(await _get_cap_cents(account_id) * _MILLICENTS_PER_CENT)
    table, col, key = _ledger(account_id, user_id)
    async with get_session() as s:
        row = (await s.execute(
            select(table.cost_cents, table.is_capped).where(
                table.day == day,
                # `== None` renders `= NULL` and matches nothing; the house-account row needs IS NULL.
                col.is_(None) if key is None else col == key,
                table.provider == provider,
            )
        )).first()
    spent_mc = int(row[0] or 0) if row else 0
    flagged = bool(row[1]) if row else False
    left = max(0, cap_mc - spent_mc)
    floor = _reserve_millicents(model, 0) if model else 0
    return {
        "day": day,
        "provider": provider,
        "cap_millicents": cap_mc,
        "spent_millicents": spent_mc,
        "remaining_millicents": left,
        "capped": (spent_mc >= cap_mc or left < floor
                   or (flagged and left < 2 * floor)),
        "flagged": flagged,
    }


async def spend_today(account_id: str) -> dict[str, Any]:
    day = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session() as s:
        rows = (await s.execute(
            select(GrokDailyCost.provider, GrokDailyCost.cost_cents, GrokDailyCost.is_capped)
            .where(GrokDailyCost.day == day, GrokDailyCost.account_id == account_id)
            .order_by(GrokDailyCost.provider)
        )).all()
    return {"day": day, "providers": [
        {"provider": p, "spent_millicents": int(c or 0), "flagged": bool(f)}
        for p, c, f in rows]}


def _ledger(account_id: str | None, user_id: str | None):
    if user_id is not None:
        return GrokUserDailyCost, GrokUserDailyCost.user_id, user_id
    return GrokDailyCost, GrokDailyCost.account_id, account_id


async def _reserve(day: str, account_id: str | None, reserve_cents: int, cap_cents: int,
                   now: datetime, provider: str, user_id: str | None = None) -> int:
    Cost, scope, key = _ledger(account_id, user_id)
    # One INSERT ... ON CONFLICT DO UPDATE is the read-check-write: a plain read-then-decide lets concurrent workers all pass and blow the cap.
    stmt = (
        sqlite_insert(Cost)
        .values(
            day=day,
            **{scope.key: key},
            provider=provider,
            cost_cents=reserve_cents,
            call_count=1,
            is_capped=False,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["day", scope.key, "provider"],
            set_={
                "cost_cents": Cost.cost_cents + reserve_cents,
                "call_count": Cost.call_count + 1,
                "updated_at": now,
            },
            where=(Cost.cost_cents + reserve_cents <= cap_cents),
        )
        .returning(Cost.cost_cents)
    )
    async with get_session() as s:
        total = (await s.execute(stmt)).scalar_one_or_none()

        if total is None:
            existing = await s.scalar(
                select(Cost.cost_cents).where(
                    Cost.day == day,
                    scope == key,
                    Cost.provider == provider,
                )
            )
            await s.execute(
                sa_update(Cost)
                .where(
                    Cost.day == day,
                    scope == key,
                    Cost.provider == provider,
                )
                .values(is_capped=True, updated_at=now)
            )
            raise LLMCapExceeded(
                account_id, cap_cents, (existing or 0) + reserve_cents
            )

        # Fresh-INSERT path only: one call's reserve alone exceeds the cap; back out the inserted row.
        if total > cap_cents:
            await s.execute(
                sa_update(Cost)
                .where(
                    Cost.day == day,
                    scope == key,
                    Cost.provider == provider,
                )
                .values(
                    cost_cents=Cost.cost_cents - reserve_cents,
                    call_count=Cost.call_count - 1,
                    is_capped=True,
                    updated_at=now,
                )
            )
            raise LLMCapExceeded(account_id, cap_cents, total)

    return total


async def _adjust_daily(day: str, account_id: str | None, cost_delta: int,
                        count_delta: int, now: datetime, provider: str,
                        user_id: str | None = None) -> None:
    if cost_delta == 0 and count_delta == 0:
        return
    Cost, scope, key = _ledger(account_id, user_id)
    async with get_session() as s:
        await s.execute(
            sa_update(Cost)
            .where(
                Cost.day == day,
                scope == key,
                Cost.provider == provider,
            )
            .values(
                cost_cents=Cost.cost_cents + cost_delta,
                call_count=Cost.call_count + count_delta,
                updated_at=now,
            )
        )


# prompt_json keeps the words, drops the pixels: base64 data: URIs become manifests (they were 99% of grok_calls size).
# No schema change here: prompt_json is NOT NULL, which the boot schema walker skips, and the service never runs alembic.
_DATA_URI_RE = re.compile(r'data:([a-zA-Z0-9.+/-]+);base64,([A-Za-z0-9+/=]+)')

_RESP_TEXT_CAP = int(os.environ.get("LLM_RESP_TEXT_CAP", "4000"))

_DEGRADED_STUB = '{"v":1,"degraded":true}'

_AUDIT_DEGRADED = 0



def _b64_decoded_len(payload: str) -> int:
    return max(0, (len(payload) * 3) // 4 - payload.count("="))


def _redact_body(body: Any) -> Any:
    if isinstance(body, dict):
        return {k: _redact_body(v) for k, v in body.items()}
    if isinstance(body, list):
        return [_redact_body(v) for v in body]
    if isinstance(body, str):
        return _DATA_URI_RE.sub(
            lambda m: f"<img:{m.group(1)}:{_b64_decoded_len(m.group(2))}b:"
                      f"{hashlib.sha256(m.group(2).encode()).hexdigest()[:16]}>",
            body,
        )
    return body


def _redacted_json(request_body: dict) -> str:
    global _AUDIT_DEGRADED
    try:
        return json.dumps(_redact_body(request_body), ensure_ascii=False, default=str)
    except Exception:
        _AUDIT_DEGRADED += 1
        log.exception("llm_client: prompt redaction failed — storing stub")
        return _DEGRADED_STUB


def audit_degraded_count() -> int:
    return _AUDIT_DEGRADED


async def _insert_pending_call(*, purpose: str, provider: str, account_id: str | None,
                               fan_id: int | None, model: str, endpoint: str,
                               temperature: float, request_body: dict,
                               now: datetime) -> int | None:
    prompt_audit = _redacted_json(request_body)
    try:
        async with get_session() as s:
            call = GrokCall(
                purpose=purpose,
                provider=provider,
                status="pending",
                account_id=account_id,
                fan_id=fan_id,
                model=model,
                endpoint=endpoint,
                temperature=temperature,
                prompt_json=prompt_audit,
                was_dry_run=False,
                called_at=now,
            )
            s.add(call)
            await s.flush()
            return call.id
    except Exception:
        log.exception("llm_client: failed to write pending grok_calls row "
                      "(purpose=%s model=%s) — proceeding without audit id",
                      purpose, model)
        return None


async def _finalize_call(call_id: int | None, **values: Any) -> None:
    if call_id is None:
        return
    try:
        async with get_session() as s:
            await s.execute(
                sa_update(GrokCall).where(GrokCall.id == call_id).values(**values)
            )
    except Exception:
        log.exception("llm_client: failed to finalize grok_calls id=%s", call_id)



async def chat(
    *,
    model: str,
    messages: list[dict],
    purpose: str,
    account_id: str | None,
    fan_id: int | None = None,
    response_format: dict | None = None,
    temperature: float = 0.7,
    reasoning_effort: str = "",
    user_id: str | None = None,
    timeout_s: float | None = None,
    max_attempts: int | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    max_tokens: int | None = None,
    api_key: str | None = None,
) -> LLMResult:
    if user_id is not None and account_id is not None:
        raise LLMConfigError("chat() bills an account OR an agency, not both")
    # Zero attempts would reserve the cap and write a row, then send nothing.
    if max_attempts is not None and max_attempts < 1:
        raise LLMConfigError(f"max_attempts must be >= 1, got {max_attempts}")
    mdl, prov = _resolve(model)
    native = prov.wire == "anthropic"
    if (response_format or {}).get("type") == "json_object" and not mdl.json_object_ok:
        raise LLMConfigError(f"model {mdl.id!r} does not support response_format=json_object")
    if native and response_format is not None:
        raise LLMConfigError(f"model {mdl.id!r}: response_format is not translated "
                             "to the native Messages API")
    if (tools is not None or tool_choice is not None) and prov.name != "deepseek":
        raise LLMConfigError(f"model {mdl.id!r}: tool calls are DeepSeek only "
                             "(the Anthropic adapter is deferred)")
    stored_effort = "" if reasoning_effort else await _account_effort(account_id, mdl)
    effort = _resolve_effort(mdl, reasoning_effort, stored=stored_effort)
    api_key = api_key or (await _user_api_key(user_id, prov, purpose) if user_id is not None
                          else await _tenant_api_key(account_id, prov, purpose))

    url = prov.base_url.rstrip("/") + ("/messages" if native else "/chat/completions")
    endpoint = httpx.URL(url).path

    body: dict[str, Any] = {
        "model": mdl.wire_model(),
        "messages": messages,
        "stream": False,
    }
    if mdl.sends_temperature:
        body["temperature"] = temperature
    if response_format is not None:
        body["response_format"] = response_format
    if tools is not None:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if max_tokens and not native:
        body["max_tokens"] = max_tokens
    # Reasoning mode is stated explicitly, never by omission: provider defaults moved and flash then returns content=""; `enable_thinking: false` is silently ignored.
    body.update(mdl.reasoning_keys())
    if effort:
        body["reasoning_effort"] = effort
    if native:
        try:
            body = llm_anthropic.to_native_body(body, max_tokens or llm_anthropic.MAX_TOKENS)
        except llm_anthropic.NativeShapeError as e:
            raise LLMConfigError(f"model {mdl.id!r}: {e}") from e

    try:
        async with model_cap.call(_REQUEST_TIMEOUT_S if timeout_s is None else timeout_s,
                                  purpose=purpose):
            now = datetime.utcnow()

            hold = await _reserve_call(model, messages, account_id=account_id, user_id=user_id,
                                       provider=budget_key(purpose), now=now,
                                       tools=tools, max_tokens=max_tokens)

            call_id = await _insert_pending_call(
                purpose=purpose, provider=prov.name, account_id=account_id, fan_id=fan_id,
                model=model, endpoint=endpoint, temperature=temperature,
                request_body=body, now=now,
            )

            headers = llm_anthropic.headers(api_key) if native else {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            data, latency_ms = await _fire(url, headers, body, call_id=call_id, hold=hold,
                                           model=model, purpose=purpose,
                                           timeout_s=timeout_s, max_attempts=max_attempts)
            if native:
                data = llm_anthropic.to_openai_response(data)
            return await _finalize_ok(data, latency_ms, call_id=call_id, hold=hold,
                                      model=model, purpose=purpose,
                                      response_format=response_format)
    except model_cap.ModelCapTimeout as e:
        raise LLMModelCapTimeout(e.waited_s, e.cap) from None



@dataclass(frozen=True)
class _Hold:
    now: datetime
    account_id: str | None
    user_id: str | None
    provider: str
    reserve_mc: int

    @property
    def day(self) -> str:
        return self.now.strftime("%Y-%m-%d")

    async def refund(self) -> None:
        await _adjust_daily(self.day, self.account_id, -self.reserve_mc, -1,
                            self.now, self.provider, self.user_id)

    async def settle(self, actual_mc: int) -> None:
        await _adjust_daily(self.day, self.account_id, actual_mc - self.reserve_mc, 0,
                            self.now, self.provider, self.user_id)


async def _reserve_call(model: str, messages: list[dict], *, account_id: str | None,
                        user_id: str | None, provider: str, now: datetime,
                        tools: list[dict] | None = None, max_tokens: int | None = None) -> _Hold:
    est_in = _estimate_input_tokens(messages, tools)
    hold = _Hold(now, account_id, user_id, provider, _reserve_millicents(model, est_in, max_tokens))
    cap_mc = await _get_cap_cents(account_id) * _MILLICENTS_PER_CENT
    await _reserve(hold.day, account_id, hold.reserve_mc, cap_mc, now, provider,
                   user_id)
    return hold


@dataclass(frozen=True)
class ExternalHold:
    hold: _Hold
    call_id: int | None

    async def done(self, actual_mc: int, *, tokens_in: int | None, ok: bool,
                   latency_ms: int, error: str = "", response: str = "",
                   tokens_out: int | None = None) -> None:
        await _finalize_call(
            self.call_id, status="done" if ok else "error",
            error_text=None if ok else error[:2000],
            response_text=response[:_RESP_TEXT_CAP] if ok else None,
            latency_ms=latency_ms, tokens_in=tokens_in, tokens_out=tokens_out,
            cost_cents=actual_mc)
        await self.hold.settle(actual_mc)


async def reserve_external(account_id: str | None, provider: str, model: str,
                           reserve_mc: int, *, purpose: str, request: dict,
                           endpoint: str = "") -> ExternalHold:
    now = datetime.utcnow()
    hold = _Hold(now, account_id, None, budget_key(purpose), int(reserve_mc))
    cap_mc = await _get_cap_cents(account_id) * _MILLICENTS_PER_CENT
    await _reserve(hold.day, account_id, hold.reserve_mc, cap_mc, now, hold.provider)
    call_id = await _insert_pending_call(
        purpose=purpose, provider=provider, account_id=account_id, fan_id=None,
        model=model, endpoint=endpoint or provider, temperature=0.0,
        request_body=request, now=now)
    return ExternalHold(hold, call_id)


async def _give_up(call_id: int | None, hold: _Hold, body: dict, msg: str,
                   latency_ms: int) -> None:
    await _finalize_call(call_id, status="error", error_text=msg[:2000],
                         latency_ms=latency_ms,
                         prompt_json=_redacted_json(body))
    await hold.refund()


async def _fire(url: str, headers: dict, body: dict, *, call_id: int | None,
                hold: _Hold, model: str, purpose: str,
                timeout_s: float | None = None,
                max_attempts: int | None = None) -> tuple[dict, int]:
    provider = MODELS[model].provider
    tries = _LLM_MAX_ATTEMPTS if max_attempts is None else max_attempts
    timeout = _REQUEST_TIMEOUT_S if timeout_s is None else timeout_s
    for attempt in range(tries):
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=body)
            latency_ms = int(round((time.monotonic() - t0) * 1000))
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"response body is a JSON {type(data).__name__}, not an object")
            return data, latency_ms
        except httpx.HTTPStatusError as e:
            latency_ms = int(round((time.monotonic() - t0) * 1000))
            status = e.response.status_code
            outcome = llm_attempt_outcome(status, attempt, tries)
            snippet = (e.response.text or "")[:500]
            if isinstance(outcome, KeyErr):
                # Providers echo part of a refused key in their error body, and this text is stored.
                snippet = f"API key {outcome.kind} (provider body withheld: it can echo the key)"
            msg = f"{provider} HTTP {status}: {snippet}"
            if isinstance(outcome, Retry):
                log.warning("llm_client: %s HTTP %s — retry %d/%d model=%s purpose=%s",
                            provider, status, attempt + 1,
                            tries, model, purpose)
                await asyncio.sleep(outcome.pause_s)
                continue
            await _give_up(call_id, hold, body, msg, latency_ms)
            log.warning("llm_client: %s call failed model=%s purpose=%s status=%s latency=%dms",
                        provider, model, purpose, status, latency_ms)
            if isinstance(outcome, KeyErr):
                raise LLMKeyError(outcome.kind, provider, purpose, detail=msg,
                                  status=status) from e
            raise LLMHTTPError(msg, status=status) from e
        except (httpx.RequestError, ValueError) as e:
            latency_ms = int(round((time.monotonic() - t0) * 1000))
            outcome = llm_attempt_outcome(type(e).__name__, attempt, tries)
            msg = f"{provider} request error: {type(e).__name__}: {e}"
            if isinstance(outcome, Retry):
                log.warning("llm_client: %s %s — retry %d/%d model=%s purpose=%s latency=%dms",
                            provider, type(e).__name__, attempt + 1,
                            tries, model, purpose, latency_ms)
                await asyncio.sleep(outcome.pause_s)
                continue
            await _give_up(call_id, hold, body, msg, latency_ms)
            log.warning("llm_client: %s call errored model=%s purpose=%s latency=%dms (%s)",
                        provider, model, purpose, latency_ms, type(e).__name__)
            raise LLMHTTPError(msg) from e
    raise AssertionError("unreachable: the last attempt always returns or raises")


async def _finalize_ok(data: dict, latency_ms: int, *, call_id: int | None, hold: _Hold,
                       model: str, purpose: str,
                       response_format: dict | None) -> LLMResult:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    raw_content = message.get("content") or ""
    reasoning_content = message.get("reasoning_content")
    content = _clean_content(raw_content)
    tool_calls = [{"id": c.get("id") or "", "type": "function",
                   "function": {"name": (c.get("function") or {}).get("name") or "",
                                "arguments": (c.get("function") or {}).get("arguments") or "{}"}}
                  for c in (message.get("tool_calls") or []) if isinstance(c, dict)]

    usage = data.get("usage") or {}
    tokens_in = usage.get("prompt_tokens")
    tokens_out = usage.get("completion_tokens")
    cache_hit_tokens = _cache_hit_tokens(usage)
    cache_write_tokens = usage.get("cache_creation_input_tokens")
    reasoning_tokens = _reasoning_tokens(usage)

    actual_mc = _cost_millicents(model, tokens_in or 0, tokens_out or 0,
                                 cache_hit_tokens or 0, cache_write_tokens or 0)

    parsed: Any | None = None
    if response_format and response_format.get("type") == "json_object":
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # Length only, never the body (PII).
            log.warning("llm_client: response_format=json_object but content did "
                        "not parse (model=%s purpose=%s len=%d)",
                        model, purpose, len(content or ""))

    await _finalize_call(
        call_id,
        status="done",
        response_text=(content or (json.dumps(tool_calls) if tool_calls else ""))[:_RESP_TEXT_CAP],
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_hit_tokens=cache_hit_tokens,
        cost_cents=actual_mc,
    )
    await hold.settle(actual_mc)

    log.info("llm_client: %s %s purpose=%s latency=%dms in=%s out=%s cache_hit=%s "
             "cache_write=%s reasoning=%s cost=%dmc",
             hold.provider, model, purpose, latency_ms, tokens_in, tokens_out,
             cache_hit_tokens, cache_write_tokens, reasoning_tokens, actual_mc)

    return LLMResult(
        call_id=call_id,
        model=model,
        provider=MODELS[model].provider,
        content=content,
        parsed=parsed,
        reasoning_content=reasoning_content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_hit_tokens=cache_hit_tokens,
        cost_cents=actual_mc,
        latency_ms=latency_ms,
        raw=data,
        cache_write_tokens=cache_write_tokens,
        tool_calls=tool_calls,
    )
