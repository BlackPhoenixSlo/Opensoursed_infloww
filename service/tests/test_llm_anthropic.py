#!/usr/bin/env python3
"""Anthropic (Claude) through its OpenAI-compatibility layer — no new client.

Each case pins a wire fact measured live on 2026-11-07 against
https://api.anthropic.com/v1/chat/completions:

  1. Bearer auth on /v1/chat/completions works; the row is a PROVIDERS entry.
  2. `temperature` < 1 is a 400 on Claude 4.7+ ("deprecated for this model"),
     so it must not travel for these models — and still must for the rest.
  3. Opus/Sonnet 5.5 400 on `thinking: disabled`; `enabled` + budget is
     accepted (the layer converts it to adaptive). Haiku 5.5 takes `disabled`.
     `reasoning_effort` is ignored by the layer → no effort choices.
  4. The help assistant may fall back to the deployment's own Anthropic key
     (HELP_ASSISTANT_ANTHROPIC_KEY), a separate credential from the house key.

Offline: the transport is stubbed, nothing leaves the process.

Run: cd service && ALLOW_ANONYMOUS_ADMIN=1 ../venv/bin/python tests/test_llm_anthropic.py
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import secrets_store  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402
from llm_client import MODELS, chat  # noqa: E402

CLAUDE = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")


class _FakeResp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _CapturingClient:
    last_body: dict = {}
    last_url: str = ""
    last_bearer: str = ""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        cls = type(self)
        cls.last_body = dict(json or {})
        cls.last_url = str(url)
        cls.last_bearer = (headers or {}).get("Authorization", "")[len("Bearer "):]
        # The compat layer's real usage shape: no cached-token field at all.
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100,
                      "total_tokens": 1100},
        })


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid, nickname=aid))
        if await s.get(AccountAiConfig, aid) is None:
            s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=1_000_000))


async def _fire(model: str, aid: str):
    orig = llm_client.httpx.AsyncClient
    real_key = llm_providers._api_key
    llm_client.httpx.AsyncClient = _CapturingClient
    llm_providers._api_key = lambda env: (
        "sk-ant-test-house" if env == "ANTHROPIC_API_KEY" else real_key(env))
    try:
        return await chat(model=model, messages=[{"role": "user", "content": "hi"}],
                          purpose="help_assistant", account_id=aid, temperature=0.3)
    finally:
        llm_client.httpx.AsyncClient = orig
        llm_providers._api_key = real_key


async def case_provider_row_and_house_key():
    prov = llm_providers.PROVIDERS["anthropic"]
    assert prov.base_url == "https://api.anthropic.com/v1", prov.base_url
    assert prov.api_key_env == "ANTHROPIC_API_KEY", prov.api_key_env
    assert prov.api_key_env in secrets_store.KNOWN, "no Setup → Keys box"
    real = llm_providers._api_key
    llm_providers._api_key = lambda env: "sk-ant-x" if env == "ANTHROPIC_API_KEY" else ""
    try:
        assert llm_providers.house_key("anthropic") == "sk-ant-x"
        assert llm_providers.fallback_key("help_assistant", "anthropic") == ""
        assert llm_providers.fallback_key("gen_info", "anthropic") == ""
    finally:
        llm_providers._api_key = real
    for mid in CLAUDE:
        mdl, p = llm_client._resolve(mid)
        assert p.name == "anthropic" and mdl.wire_model() == mid, (mid, p.name)


async def case_body_has_no_temperature_and_states_thinking():
    await _seed_account("acct_claude_body")
    for mid in CLAUDE:
        await _fire(mid, "acct_claude_body")
        body = _CapturingClient.last_body
        assert _CapturingClient.last_url == \
            "https://api.anthropic.com/v1/chat/completions", _CapturingClient.last_url
        assert _CapturingClient.last_bearer == "sk-ant-test-house"
        assert body["model"] == mid, body
        assert "temperature" not in body, (mid, body)   # 400 on Claude 4.7+
        assert "reasoning_effort" not in body, (mid, body)   # ignored by the layer
        assert "thinking" in body, f"{mid} states its mode by omission"
        if mid == "claude-haiku-5-5":
            assert body["thinking"] == {"type": "disabled"}, body
        else:   # `disabled` is a 400 on Opus/Sonnet 5.5
            assert body["thinking"]["type"] == "enabled", body
        assert MODELS[mid].effort_choices == (), mid


async def case_other_models_still_send_temperature():
    await _seed_account("acct_ds_temp")
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _CapturingClient
    try:
        await chat(model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}],
                   purpose="gen_info", account_id="acct_ds_temp", temperature=0.3)
    finally:
        llm_client.httpx.AsyncClient = orig
    assert _CapturingClient.last_body.get("temperature") == 0.3, _CapturingClient.last_body


async def case_cost_bills_list_price_with_no_cache_field():
    """1000 in (no cached field → all miss) + 100 out on Opus = 0.4 + 0.2 = 0.6c
    = 60 millicents. A cap that under-counts Opus is the expensive mistake."""
    await _seed_account("acct_claude_cost")
    res = await _fire("claude-opus-5-5", "acct_claude_cost")
    assert res.cost_cents == 60, res
    assert llm_client._cost_millicents("claude-opus-5-5", 1000, 100) == 60
    assert llm_client._cost_millicents("claude-sonnet-5-5", 1000, 100) == 30
    assert llm_client._cost_millicents("claude-haiku-5-5", 1000, 100) == 2


async def case_json_object_on_claude_is_refused_before_it_fires():
    """The compat layer 400s on json_object; the call must die here, free —
    no request, no cap slot — while a DeepSeek JSON call still goes out."""
    from llm_client import LLMConfigError
    await _seed_account("acct_claude_json")
    _CapturingClient.last_url = ""
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _CapturingClient
    try:
        for mid in CLAUDE:
            assert MODELS[mid].json_object_ok is False, mid
            try:
                await chat(model=mid, messages=[{"role": "user", "content": "hi"}],
                           purpose="gen_info", account_id="acct_claude_json",
                           response_format={"type": "json_object"})
                raise AssertionError(f"{mid} json_object call was not refused")
            except LLMConfigError as e:
                assert "json_object" in str(e), e
        assert _CapturingClient.last_url == "", "a refused call still went out"
        await chat(model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}],
                   purpose="gen_info", account_id="acct_claude_json",
                   response_format={"type": "json_object"})
        assert _CapturingClient.last_body.get("response_format") == {"type": "json_object"}
    finally:
        llm_client.httpx.AsyncClient = orig


async def case_json_purposes_never_resolve_to_claude():
    """Override, pin and brain set to Claude: a JSON purpose falls through each
    to the house model (with a warning); a text purpose keeps Claude."""
    import json as _json
    from automations._common import DEFAULT_MODEL, JSON_OBJECT_PURPOSES, resolve_model
    aid = "acct_claude_everywhere"
    await _seed_account(aid)
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, aid)
        cfg.model = "claude-sonnet-5-5"
        cfg.model_by_purpose = _json.dumps(
            {p: "claude-opus-5-5" for p in (*JSON_OBJECT_PURPOSES, "help_assistant")})
    for purpose in JSON_OBJECT_PURPOSES:
        got = await resolve_model(aid, purpose, override="claude-haiku-5-5")
        assert got == DEFAULT_MODEL, (purpose, got)
        # A pin on a JSON purpose to a model that CAN do JSON still wins.
        assert await resolve_model(aid, purpose, override="deepseek-v4-pro") == "deepseek-v4-pro"
    # Text purposes are untouched: the pin and the brain still apply.
    assert await resolve_model(aid, "help_assistant") == "claude-opus-5-5"
    assert await resolve_model(aid, "autoreply") == "claude-sonnet-5-5"


_harness.run(
    case_json_object_on_claude_is_refused_before_it_fires,
    case_json_purposes_never_resolve_to_claude,
    case_provider_row_and_house_key,
    case_body_has_no_temperature_and_states_thinking,
    case_other_models_still_send_temperature,
    case_cost_bills_list_price_with_no_cache_field,
)
