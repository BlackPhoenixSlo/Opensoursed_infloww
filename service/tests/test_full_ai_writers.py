#!/usr/bin/env python3
"""Full AI Chat Writers (phase 03a, slice A): the two new hosts and the
one-shot Writer call.

  1. A Writer is tried ONCE with a short timeout (`timeout_s`, `max_attempts`)
     so a 429 or a stall reaches the next Writer fast, not after three 120 s
     retries. Proven at the HTTP seam: what the transport was built with and
     how many requests it saw.
  2. Every existing caller passes neither kwarg and must see today's request
     count and timeout (parity).
  3. Euryale v2.3 (NanoGPT) and Hermes 4 405B (OpenRouter) reach their hosts
     with the spec's wire ids and bill at the D54/D60 prices; neither takes
     the JSON lanes.

Offline: the transport is stubbed, no provider is called.

Run: cd service && ../venv/bin/python tests/test_full_ai_writers.py
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import os  # noqa: E402

import llm_client  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402
from llm_client import LLMConfigError, LLMHTTPError, chat  # noqa: E402

# House keys so an orphan account can resolve one (fake values, never real).
os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")


class _FakeResp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _TimeoutClient:
    """Every request times out. Records the timeout each client was built
    with and how many requests left the process."""

    timeouts: list = []
    calls: int = 0

    def __init__(self, *a, timeout=None, **k):
        type(self).timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).calls += 1
        raise llm_client.httpx.ReadTimeout("timed out")


class _OkClient(_TimeoutClient):
    last_url: str = ""
    last_body: dict = {}
    usage: dict = {"prompt_tokens": 10, "completion_tokens": 5}

    async def post(self, url, headers=None, json=None):
        cls = type(self)
        cls.calls += 1
        cls.last_url = str(url)
        cls.last_body = dict(json or {})
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": dict(cls.usage),
        })


async def _seed_account(account_id: str) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id, nickname=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            s.add(AccountAiConfig(account_id=account_id,
                                  daily_cost_cap_cents=1_000_000))


async def _fire(model: str, account_id: str, client, **kw):
    client.calls = 0
    client.timeouts = []
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = client
    try:
        return await chat(model=model, messages=[{"role": "user", "content": "hi"}],
                          purpose="full_ai_writer", account_id=account_id, **kw)
    finally:
        llm_client.httpx.AsyncClient = orig


async def _expect_http_error(model, account_id, client, **kw):
    try:
        await _fire(model, account_id, client, **kw)
    except LLMHTTPError:
        return
    raise AssertionError("a timed-out call must raise LLMHTTPError")


# ── 1. One attempt at the given bound ─────────────────────────────────────

async def case_one_attempt_times_out_at_the_given_bound():
    await _seed_account("acct_writer_once")
    await _expect_http_error("deepseek-v4-flash", "acct_writer_once", _TimeoutClient,
                             timeout_s=7.5, max_attempts=1)
    assert _TimeoutClient.calls == 1, _TimeoutClient.calls
    assert _TimeoutClient.timeouts == [7.5], _TimeoutClient.timeouts


async def case_two_attempts_means_two_requests():
    await _seed_account("acct_writer_twice")
    orig = llm_client._LLM_RETRY_BACKOFF_S
    llm_client._LLM_RETRY_BACKOFF_S = 0.0
    try:
        await _expect_http_error("deepseek-v4-flash", "acct_writer_twice", _TimeoutClient,
                                 timeout_s=3.0, max_attempts=2)
    finally:
        llm_client._LLM_RETRY_BACKOFF_S = orig
    assert _TimeoutClient.calls == 2, _TimeoutClient.calls
    assert _TimeoutClient.timeouts == [3.0, 3.0], _TimeoutClient.timeouts


# ── 2. Parity: no kwargs = today's 3 attempts at 120 s ────────────────────

async def case_default_kwargs_keep_todays_count_and_timeout():
    await _seed_account("acct_writer_parity")
    orig = llm_client._LLM_RETRY_BACKOFF_S
    llm_client._LLM_RETRY_BACKOFF_S = 0.0
    try:
        await _expect_http_error("deepseek-v4-flash", "acct_writer_parity", _TimeoutClient)
    finally:
        llm_client._LLM_RETRY_BACKOFF_S = orig
    assert _TimeoutClient.calls == 3, _TimeoutClient.calls
    assert _TimeoutClient.timeouts == [120.0, 120.0, 120.0], _TimeoutClient.timeouts


async def case_default_kwargs_send_the_same_body():
    """The kwargs shape the transport, never the request body."""
    await _seed_account("acct_writer_body")
    await _fire("deepseek-v4-flash", "acct_writer_body", _OkClient)
    plain = dict(_OkClient.last_body)
    await _fire("deepseek-v4-flash", "acct_writer_body", _OkClient,
                timeout_s=5.0, max_attempts=1)
    assert _OkClient.last_body == plain, (_OkClient.last_body, plain)
    assert "timeout_s" not in plain and "max_attempts" not in plain, plain


# ── 3. The two new Writers: host, wire id, price ──────────────────────────
# Billed in the internal unit, cents x100. 1M tokens each way so the spec's
# per-1M dollar prices land exact (10 in / 5 out rounds Euryale to 0).
_MILLION = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}


async def _fire_million(model, account_id):
    await _seed_account(account_id)
    _OkClient.usage = _MILLION
    try:
        return await _fire(model, account_id, _OkClient)
    finally:
        _OkClient.usage = {"prompt_tokens": 10, "completion_tokens": 5}


async def case_euryale_goes_to_nanogpt_at_d54_price():
    res = await _fire_million("euryale-v2.3", "acct_euryale")
    assert _OkClient.last_url == "https://nano-gpt.com/api/v1/chat/completions", \
        _OkClient.last_url
    assert _OkClient.last_body.get("model") == "Sao10K/L3.3-70B-Euryale-v2.3", \
        _OkClient.last_body.get("model")
    # D54: $0.493/M in + $0.493/M out = 98.6 cents.
    assert res.cost_cents == 9860, res.cost_cents


async def case_hermes_goes_to_openrouter_at_d60_price():
    res = await _fire_million("hermes-4-405b", "acct_hermes")
    assert _OkClient.last_url == "https://openrouter.ai/api/v1/chat/completions", \
        _OkClient.last_url
    assert _OkClient.last_body.get("model") == "nousresearch/hermes-4-405b", \
        _OkClient.last_body.get("model")
    # D60: $1/M in + $3/M out = 400 cents.
    assert res.cost_cents == 40000, res.cost_cents


async def case_writers_refuse_json_object_before_firing():
    """Not offered on the JSON lanes (gen_info, copilot): refused, no request."""
    await _seed_account("acct_writer_json")
    for mid in ("euryale-v2.3", "hermes-4-405b"):
        try:
            await _fire(mid, "acct_writer_json", _OkClient,
                        response_format={"type": "json_object"})
            raise AssertionError(f"{mid} json_object call was not refused")
        except LLMConfigError:
            pass
        assert _OkClient.calls == 0, (mid, _OkClient.calls)


async def case_zero_attempts_is_refused_before_anything_fires():
    await _seed_account("acct_writer_zero")
    try:
        await _fire("deepseek-v4-flash", "acct_writer_zero", _OkClient, max_attempts=0)
        raise AssertionError("max_attempts=0 was not refused")
    except LLMConfigError:
        pass
    assert _OkClient.calls == 0, _OkClient.calls


_harness.run()
