#!/usr/bin/env python3
import _harness

_harness.bootstrap()

from datetime import datetime  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall, GrokUserDailyCost, User  # noqa: E402
from llm_client import LLMConfigError, chat  # noqa: E402

AID = "acct_tools"
TOOLS = [{"type": "function", "function": {"name": "creators_list", "description": "List Creators.",
                                           "parameters": {"type": "object", "properties": {}}}}]
CALL = {"id": "call_1", "type": "function", "function": {"name": "creators_list", "arguments": "{}"}}
HISTORY = [{"role": "system", "content": "plan"}, {"role": "user", "content": "list them"},
           {"role": "assistant", "content": "", "tool_calls": [CALL]},
           {"role": "tool", "tool_call_id": "call_1", "content": '{"rows": []}'}]


def _reply(message: dict) -> dict:
    return {"choices": [{"message": message, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


class _Client:
    calls: list = []
    answer: dict = _reply({"content": "ok"})

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).calls.append(dict(json or {}))
        return httpx.Response(200, json=type(self).answer, request=httpx.Request("POST", url))


async def _seed() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname=AID))
            s.add(AccountAiConfig(account_id=AID, daily_cost_cap_cents=1_000_000))


async def _fire(answer: dict, **kw):
    await _seed()
    orig, real_key = llm_client.httpx.AsyncClient, llm_providers._api_key
    llm_client.httpx.AsyncClient = _Client
    llm_providers._api_key = lambda env: "sk-test" if env == "DEEPSEEK_API_KEY" else real_key(env)
    _Client.calls, _Client.answer = [], answer
    try:
        return await chat(model="deepseek-v4-flash", purpose="ultra_plan", account_id=AID, **kw)
    finally:
        llm_client.httpx.AsyncClient, llm_providers._api_key = orig, real_key


async def case_tool_payload() -> None:
    res = await _fire(_reply({"content": None, "tool_calls": [
        {"id": "call_2", "type": "function", "function": {"name": "vault_search", "arguments": '{"q": 1}'}}]}),
        messages=HISTORY, tools=TOOLS, tool_choice="auto")
    body = _Client.calls[-1]
    assert body["tools"] == TOOLS and body["tool_choice"] == "auto", body
    assert body["messages"] == HISTORY, body["messages"]
    assert res.content == "" and res.tool_calls == [
        {"id": "call_2", "type": "function", "function": {"name": "vault_search", "arguments": '{"q": 1}'}}], res
    async with get_session() as s:
        text = await s.scalar(select(GrokCall.response_text).where(GrokCall.id == res.call_id))
    assert "vault_search" in text, text


async def case_no_tools_unchanged() -> None:
    res = await _fire(_reply({"content": "hello"}), messages=HISTORY[:2])
    body = _Client.calls[-1]
    assert "tools" not in body and "tool_choice" not in body, body
    assert res.content == "hello" and res.tool_calls == [], res


async def case_other_providers() -> None:
    for model in ("claude-sonnet-5-5", "glm-5.3-flash"):
        _Client.calls = []
        try:
            await chat(model=model, messages=HISTORY[:2], purpose="ultra_plan", account_id=AID, tools=TOOLS)
        except LLMConfigError as e:
            assert "DeepSeek only" in str(e), e
        else:
            raise AssertionError(f"{model}: tools accepted")
        assert _Client.calls == []


async def case_estimate_counts() -> None:
    base = llm_client._estimate_input_tokens(HISTORY[:2])
    assert llm_client._estimate_input_tokens(HISTORY[:2], TOOLS) > base
    assert llm_client._estimate_input_tokens(HISTORY) > base


async def case_cap_state_user() -> None:
    day = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session() as s:
        s.add(User(id="u_tools", username="u_tools", password="x"))
        await s.flush()
        s.add(GrokUserDailyCost(day=day, user_id="u_tools", provider="chat", cost_cents=10_000, call_count=1))
    user = await llm_client.cap_state(None, "deepseek", "deepseek-v4-flash", user_id="u_tools")
    house = await llm_client.cap_state(None, "deepseek", "deepseek-v4-flash")
    assert user["spent_millicents"] == 10_000 and user["capped"], user
    assert house["spent_millicents"] == 0 and not house["capped"], house


if __name__ == "__main__":
    _harness.run()
