#!/usr/bin/env python3
"""Anthropic (Claude) through its NATIVE Messages API with prompt caching.

Each case pins a wire fact measured live on 2026-11-07 against
https://api.anthropic.com/v1/messages:

  1. `x-api-key` + `anthropic-version` on POST /v1/messages; the system prompt
     travels as a text block with `cache_control: ephemeral`, and usage splits
     the prompt into input / cache_creation / cache_read tokens.
  2. `temperature` < 1 is a 400 on Claude 4.7+, so it must not travel for
     these models — and still must for the rest.
  3. Every 5.5 model 400s on `thinking: enabled`; Opus/Sonnet 5.5 also on
     `disabled`, so they state `adaptive`. Haiku 5.5 takes `disabled`.
  4. Cache reads bill the hit rate, cache writes 1.25x input.
  5. Error statuses map to the same kinds as every provider (401 key invalid,
     429/529 retried, 400 not retried).

Offline: the transport is stubbed, nothing leaves the process.

Run: cd service/tests && ../../venv/bin/python test_llm_anthropic.py
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import httpx  # noqa: E402

import llm_anthropic  # noqa: E402
import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import secrets_store  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall  # noqa: E402
from llm_client import (LLMConfigError, LLMHTTPError, LLMKeyError, MODELS,  # noqa: E402
                        chat)

CLAUDE = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
SYSTEM = "You are the help bot. " * 50


def _native(usage: dict, content=None, stop="end_turn") -> dict:
    return {"id": "msg_x", "type": "message", "role": "assistant", "model": "m",
            "content": content if content is not None else [{"type": "text", "text": "ok"}],
            "stop_reason": stop, "usage": usage}


_COLD = {"input_tokens": 50, "cache_creation_input_tokens": 38900,
         "cache_read_input_tokens": 0, "output_tokens": 300}
_WARM = {"input_tokens": 50, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 38900, "output_tokens": 300}


class _Client:
    """httpx.AsyncClient stand-in: records each POST, answers from `script`
    (a list of (status, json) consumed in order; the last one repeats)."""
    calls: list = []
    script: list = [(200, _native(_COLD))]

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        cls = type(self)
        cls.calls.append({"url": str(url), "headers": dict(headers or {}),
                          "body": dict(json or {})})
        status, data = cls.script[min(len(cls.calls) - 1, len(cls.script) - 1)]
        return httpx.Response(status, json=data, request=httpx.Request("POST", url))

    @classmethod
    def reset(cls, *script):
        cls.calls = []
        cls.script = list(script) or [(200, _native(_COLD))]

    @classmethod
    def last(cls) -> dict:
        return cls.calls[-1]


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid, nickname=aid))
        if await s.get(AccountAiConfig, aid) is None:
            s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=1_000_000))


async def _fire(model: str, aid: str, messages=None, **kw):
    orig = llm_client.httpx.AsyncClient
    real_key = llm_providers._api_key
    backoff = llm_client._LLM_RETRY_BACKOFF_S
    llm_client.httpx.AsyncClient = _Client
    llm_client._LLM_RETRY_BACKOFF_S = 0
    llm_providers._api_key = lambda env: (
        "sk-ant-test-house" if env == "ANTHROPIC_API_KEY" else real_key(env))
    try:
        return await chat(model=model, messages=messages or [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "hi"}],
            purpose="help_assistant", account_id=aid, temperature=0.3, **kw)
    finally:
        llm_client.httpx.AsyncClient = orig
        llm_client._LLM_RETRY_BACKOFF_S = backoff
        llm_providers._api_key = real_key


async def _row(call_id: int) -> GrokCall:
    async with get_session() as s:
        return await s.get(GrokCall, call_id)


async def case_provider_row_and_house_key():
    prov = llm_providers.PROVIDERS["anthropic"]
    assert prov.base_url == "https://api.anthropic.com/v1", prov.base_url
    assert prov.wire == "anthropic", prov.wire
    assert all(p.wire == "openai" for n, p in llm_providers.PROVIDERS.items()
               if n != "anthropic")
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


async def case_native_request_shape_with_cached_system_block():
    await _seed_account("acct_claude_body")
    for mid in CLAUDE:
        _Client.reset()
        await _fire(mid, "acct_claude_body")
        call = _Client.last()
        body, h = call["body"], call["headers"]
        assert call["url"] == "https://api.anthropic.com/v1/messages", call["url"]
        assert h.get("x-api-key") == "sk-ant-test-house", "key header"
        assert h.get("anthropic-version") == "2023-06-01", h
        assert "Authorization" not in h, "bearer must not travel natively"
        assert body["model"] == mid, body
        assert body["max_tokens"] == llm_anthropic.MAX_TOKENS == 4096, body
        assert body["system"] == [{"type": "text", "text": SYSTEM,
                                   "cache_control": {"type": "ephemeral"}}], body["system"]
        assert body["messages"] == [{"role": "user", "content": "hi"}], body["messages"]
        for k in ("temperature", "reasoning_effort", "stream", "response_format"):
            assert k not in body, (mid, k, body)
        if mid == "claude-haiku-5-5":
            assert body["thinking"] == {"type": "disabled"}, body
        else:   # `enabled` and `disabled` are 400s on Opus/Sonnet 5.5 natively
            assert body["thinking"] == {"type": "adaptive"}, body
        assert MODELS[mid].effort_choices == (), mid


def case_adapter_puts_the_breakpoint_on_the_last_system_block():
    out = llm_anthropic.to_native_body({
        "model": "m", "stream": False, "thinking": {"type": "adaptive"},
        "messages": [
            {"role": "system", "content": "A"},
            {"role": "system", "content": [{"type": "text", "text": "B"}]},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": [{"type": "text", "text": "q"},
                                         {"type": "text", "text": "2"}]}]})
    assert out["system"] == [{"type": "text", "text": "A"},
                             {"type": "text", "text": "B",
                              "cache_control": {"type": "ephemeral"}}], out
    assert out["messages"] == [{"role": "user", "content": "q1"},
                               {"role": "assistant", "content": "a1"},
                               {"role": "user", "content": "q2"}], out
    assert "stream" not in out and out["thinking"] == {"type": "adaptive"}
    no_sys = llm_anthropic.to_native_body({"model": "m", "messages": [
        {"role": "user", "content": "x"}]})
    assert "system" not in no_sys, no_sys


def case_response_is_normalized_to_the_openai_shape():
    data = llm_anthropic.to_openai_response(_native(
        {"input_tokens": 7, "cache_creation_input_tokens": 100,
         "cache_read_input_tokens": 900, "output_tokens": 40,
         "output_tokens_details": {"thinking_tokens": 25}},
        content=[{"type": "thinking", "thinking": "hmm", "signature": "s"},
                 {"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}],
        stop="end_turn"))
    ch = data["choices"][0]
    assert ch["message"]["content"] == "Hello", ch
    assert ch["message"]["reasoning_content"] == "hmm", ch
    assert ch["finish_reason"] == "stop", ch
    u = data["usage"]
    assert u["prompt_tokens"] == 1007 and u["completion_tokens"] == 40, u
    assert u["prompt_tokens_details"] == {"cached_tokens": 900}, u
    assert u["cache_creation_input_tokens"] == 100, u
    assert u["completion_tokens_details"] == {"reasoning_tokens": 25}, u
    assert llm_client._cache_hit_tokens(u) == 900
    assert llm_anthropic.to_openai_response(_native(_WARM))["choices"][0][
        "finish_reason"] == "stop"


async def case_cache_write_then_read_bill_their_own_rates():
    """Opus, 50 fresh + 38.9k system + 300 out:
      write call: 50*0.4 + 38900*0.5 + 300*2.0 per 1k = 20.07c = 2007 mc
      read  call: 50*0.4 + 38900*0.02 + 300*2.0 per 1k = 1.398c = 140 mc
    against 38950*0.4 + 0.6 = 16.18c = 1618 mc when nothing caches."""
    aid = "acct_claude_cache"
    await _seed_account(aid)
    _Client.reset((200, _native(_COLD)), (200, _native(_WARM)))
    cold = await _fire("claude-opus-5-5", aid)
    warm = await _fire("claude-opus-5-5", aid)
    assert (cold.tokens_in, cold.cache_hit_tokens, cold.cache_write_tokens) == \
        (38950, 0, 38900), cold
    assert (warm.tokens_in, warm.cache_hit_tokens, warm.cache_write_tokens) == \
        (38950, 38900, 0), warm
    assert cold.cost_cents == 2007, cold.cost_cents
    assert warm.cost_cents == 140, warm.cost_cents
    assert llm_client._cost_millicents("claude-opus-5-5", 38950, 300) == 1618
    for res in (cold, warm):
        row = await _row(res.call_id)
        assert row.status == "done" and row.cost_cents == res.cost_cents, row
        assert row.cache_hit_tokens == res.cache_hit_tokens, row
        assert row.tokens_in == 38950 and row.endpoint == "/v1/messages", row
    # Sonnet / Haiku write rates are 1.25x their input too.
    assert llm_client._cost_millicents("claude-sonnet-5-5", 1000, 0, 0, 1000) == 25
    assert llm_client._cost_millicents("claude-haiku-5-5", 8000, 0, 0, 8000) == 10
    # Clamp: write can't exceed what the hit left of tokens_in.
    assert llm_client._cost_millicents("claude-opus-5-5", 1000, 0, 900, 900) == \
        llm_client._cost_millicents("claude-opus-5-5", 1000, 0, 900, 100)
    # A model with no write rate bills a (never-reported) write at miss.
    assert llm_client._cost_millicents("deepseek-v4-flash", 1000, 0, 0, 1000) == \
        llm_client._cost_millicents("deepseek-v4-flash", 1000, 0)


async def case_help_http_route_caches_prompt_and_persists_costs():
    """Real HTTP route + resolver + client + DB, only provider wire stubbed.

    Bypasses: local anonymous-admin mode, seeded account, scripted provider
    usage. Proves integration/accounting, not Anthropic's actual cache hit.
    """
    import json
    import os
    from fastapi import FastAPI
    from sqlalchemy import select
    import assistant_api
    from db.models import AssistantTurn

    aid = "acct_claude_http"
    await _seed_account(aid)
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, aid)
        cfg.model_by_purpose = json.dumps({"help_assistant": "claude-opus-5-5"})
    app = FastAPI()
    app.include_router(assistant_api.router)
    real_client = httpx.AsyncClient
    real_key = llm_providers._api_key
    old_admin = os.environ.get("ALLOW_ANONYMOUS_ADMIN")
    calls = []

    def provider(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant-test-http"
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=_native(_COLD if len(calls) == 1 else _WARM))

    # Construct the inbound ASGI client before replacing outbound clients.
    async with real_client(transport=httpx.ASGITransport(app=app),
                           base_url="http://test") as client:
        os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
        llm_providers._api_key = lambda env: "sk-ant-test-http" if env == "ANTHROPIC_API_KEY" else ""
        llm_client.httpx.AsyncClient = lambda **kw: real_client(
            **kw, transport=httpx.MockTransport(provider))
        try:
            turn_ids = []
            for question in ("How do I make autopost?", "Where are my scripts?"):
                response = await client.post("/admin/assistant/ask", json={
                    "account_id": aid, "question": question})
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["error"] is None and result["answer"] == "ok", result
                turn_ids.append(result["id"])
        finally:
            llm_client.httpx.AsyncClient = real_client
            llm_providers._api_key = real_key
            if old_admin is None:
                os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)
            else:
                os.environ["ALLOW_ANONYMOUS_ADMIN"] = old_admin

    assert len(calls) == 2, calls
    assert calls[0]["system"] == calls[1]["system"]
    assert calls[0]["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "# NOT SUPPORTED" in calls[0]["system"][0]["text"]
    assert calls[0]["messages"] != calls[1]["messages"]
    async with get_session() as s:
        rows = (await s.scalars(select(GrokCall).where(
            GrokCall.account_id == aid).order_by(GrokCall.id))).all()
        assert [r.cost_cents for r in rows] == [2007, 140]
        assert [r.cache_hit_tokens for r in rows] == [0, 38900]
        assert all(r.status == "done" and r.endpoint == "/v1/messages" for r in rows)
        turns = [await s.get(AssistantTurn, tid) for tid in turn_ids]
        assert all(t is not None and t.answer == "ok" for t in turns)


async def case_error_statuses_map_to_the_shared_kinds():
    aid = "acct_claude_err"
    await _seed_account(aid)
    err = {"type": "error", "error": {"type": "x", "message": "key sk-ant-…abcd bad"}}
    _Client.reset((401, err))
    try:
        await _fire("claude-opus-5-5", aid)
        raise AssertionError("401 did not raise")
    except LLMKeyError as e:
        assert e.kind == "invalid" and e.status == 401 and e.provider == "anthropic", e
        assert "abcd" not in str(e), "provider body (can echo the key) leaked"
    assert len(_Client.calls) == 1, "a key refusal was retried"

    _Client.reset((400, err))
    try:
        await _fire("claude-opus-5-5", aid)
        raise AssertionError("400 did not raise")
    except LLMKeyError:
        raise AssertionError("400 is not a key error")
    except LLMHTTPError as e:
        assert e.status == 400, e
    assert len(_Client.calls) == 1, "a 400 was retried"

    for status in (429, 529):
        _Client.reset((status, err), (200, _native(_WARM)))
        res = await _fire("claude-opus-5-5", aid)
        assert len(_Client.calls) == 2 and res.content == "ok", (status, _Client.calls)
        _Client.reset((status, err))
        try:
            await _fire("claude-opus-5-5", aid)
            raise AssertionError(f"{status} exhausted did not raise")
        except LLMHTTPError as e:
            assert e.status == status and not isinstance(e, LLMKeyError), e
        assert len(_Client.calls) == llm_client._LLM_MAX_ATTEMPTS, status


async def case_untranslatable_body_is_refused_before_it_fires():
    aid = "acct_claude_img"
    await _seed_account(aid)
    _Client.reset()
    try:
        await _fire("claude-opus-5-5", aid, messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}])
        raise AssertionError("image part was not refused")
    except LLMConfigError as e:
        assert not isinstance(e, LLMKeyError), e
    assert _Client.calls == [], "a refused call still went out"
    try:
        await _fire("claude-opus-5-5", aid,
                    response_format={"type": "json_schema", "json_schema": {}})
        raise AssertionError("response_format was not refused")
    except LLMConfigError as e:
        assert "response_format" in str(e), e
    assert _Client.calls == []


async def case_other_models_still_speak_openai_with_temperature():
    await _seed_account("acct_ds_temp")
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _Client
    _Client.reset((200, {"choices": [{"message": {"content": "ok"}}],
                         "usage": {"prompt_tokens": 10, "completion_tokens": 1}}))
    try:
        res = await chat(model="deepseek-v4-flash",
                         messages=[{"role": "system", "content": "s"},
                                   {"role": "user", "content": "hi"}],
                         purpose="gen_info", account_id="acct_ds_temp", temperature=0.3)
    finally:
        llm_client.httpx.AsyncClient = orig
    call = _Client.last()
    assert call["url"].endswith("/chat/completions"), call["url"]
    assert call["headers"]["Authorization"].startswith("Bearer "), call["headers"]
    assert call["body"].get("temperature") == 0.3, call["body"]
    assert call["body"]["messages"][0] == {"role": "system", "content": "s"}
    assert "max_tokens" not in call["body"], call["body"]
    assert res.cache_write_tokens is None, res


async def case_json_object_on_claude_is_refused_before_it_fires():
    """Claude 400s on json_object; the call must die here, free — no request,
    no cap slot — while a DeepSeek JSON call still goes out."""
    await _seed_account("acct_claude_json")
    _Client.reset((200, {"choices": [{"message": {"content": "{}"}}], "usage": {}}))
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _Client
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
        assert _Client.calls == [], "a refused call still went out"
        await chat(model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}],
                   purpose="gen_info", account_id="acct_claude_json",
                   response_format={"type": "json_object"})
        assert _Client.last()["body"].get("response_format") == {"type": "json_object"}
    finally:
        llm_client.httpx.AsyncClient = orig


async def case_reservation_counts_the_full_native_output_and_the_write_rate():
    """The pre-flight reserve is the most the call can bill: Claude may write
    the whole prompt to cache (1.25x input) and spend MAX_TOKENS (4096, adaptive
    thinking included), not the 1024 assumed for the OpenAI lanes. A cap the old
    all-miss/1024 reserve fit under (~2.2c on Opus) but the real worst case
    (~8.3c) doesn't is refused before the request goes out."""
    tokens_in = 270
    assert llm_client._reserve_millicents("claude-opus-5-5", tokens_in) == \
        llm_client._cost_millicents("claude-opus-5-5", tokens_in,
                                    llm_anthropic.MAX_TOKENS, 0, tokens_in)
    # No write rate, no stated max: unchanged all-miss + 1024.
    assert llm_client._reserve_millicents("deepseek-v4-flash", tokens_in) == \
        llm_client._cost_millicents("deepseek-v4-flash", tokens_in,
                                    llm_client._ASSUMED_OUTPUT_TOKENS)
    aid = "acct_claude_reserve"
    await _seed_account(aid)
    async with get_session() as s:
        (await s.get(AccountAiConfig, aid)).daily_cost_cap_cents = 5
    _Client.reset()
    try:
        await _fire("claude-opus-5-5", aid)
        raise AssertionError("a call whose worst case exceeds the cap went out")
    except llm_client.LLMCapExceeded:
        pass
    assert _Client.calls == [], "the request fired past the cap"


async def case_output_cut_at_max_tokens_returns_empty_not_a_fragment():
    """Claude's stop_reason max_tokens (adaptive thinking ate MAX_TOKENS) is a
    fragment: the caller gets content="" (its empty-answer path), the row stays
    done with the billed cost. Narrow to the native wire: an OpenAI-lane
    "length" reply keeps its text (pre-#302 behaviour)."""
    data = llm_anthropic.to_openai_response(_native(
        _COLD, content=[{"type": "text", "text": "Hel"}], stop="max_tokens"))
    assert data["choices"][0]["message"]["content"] == "", data
    assert data["choices"][0]["finish_reason"] == "length", data
    aid = "acct_claude_cut"
    await _seed_account(aid)
    _Client.reset((200, _native(_COLD, content=[{"type": "text", "text": "Hel"}],
                                stop="max_tokens")))
    res = await _fire("claude-opus-5-5", aid)
    assert res.content == "", res.content
    row = await _row(res.call_id)
    assert row.status == "done" and row.cost_cents == res.cost_cents > 0, row
    _Client.reset((200, _native(_COLD)))
    assert (await _fire("claude-opus-5-5", aid)).content == "ok"
    await _seed_account("acct_ds_cut")
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _Client
    _Client.reset((200, {"choices": [{"message": {"content": "Hel"}, "finish_reason": "length"}],
                         "usage": {"prompt_tokens": 10, "completion_tokens": 1}}))
    try:
        ds = await chat(model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}],
                        purpose="gen_info", account_id="acct_ds_cut")
    finally:
        llm_client.httpx.AsyncClient = orig
    assert ds.content == "Hel", ds.content


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
    case_native_request_shape_with_cached_system_block,
    case_adapter_puts_the_breakpoint_on_the_last_system_block,
    case_response_is_normalized_to_the_openai_shape,
    case_cache_write_then_read_bill_their_own_rates,
    case_help_http_route_caches_prompt_and_persists_costs,
    case_error_statuses_map_to_the_shared_kinds,
    case_untranslatable_body_is_refused_before_it_fires,
    case_other_models_still_speak_openai_with_temperature,
    case_reservation_counts_the_full_native_output_and_the_write_rate,
    case_output_cut_at_max_tokens_returns_empty_not_a_fragment,
)
