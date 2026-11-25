#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import os  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import select  # noqa: E402

import llm_client  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall, GrokDailyCost  # noqa: E402
from llm_client import LLMCapExceeded, MODELS, chat  # noqa: E402

_REAL_ENV = Path(__file__).resolve().parents[1] / ".env"


async def _seed_account(account_id: str, cap_cents: int) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            s.add(AccountAiConfig(account_id=account_id, daily_cost_cap_cents=cap_cents))



def case_cost_in_millicents_not_floored():
    mc = llm_client._cost_millicents("deepseek-v4-flash", tokens_in=2000, tokens_out=1000)
    assert mc > 0, f"expected non-zero millicents, got {mc}"
    mdl = MODELS["deepseek-v4-flash"]
    cents = 2000 / 1000 * mdl.input_per_1k_cents + 1000 / 1000 * mdl.output_per_1k_cents
    assert cents < 1.0 and round(cents) == 0, f"precondition: call should be sub-cent ({cents}c)"
    assert mc == round(cents * 100), (mc, cents)


def case_wire_model_only_remaps_real_name_differences():
    for mid in ("deepseek-v4-flash", "deepseek-v4-pro"):
        assert MODELS[mid].wire_model() == mid, (mid, MODELS[mid].wire_model())
        assert not MODELS[mid].api_model, f"{mid} must not remap its wire name"
    assert MODELS["qwen3-vl-30b"].wire_model() == "Qwen/Qwen3-VL-30B-A3B-Instruct"



class _FakeResp:
    status_code = 200

    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeClient:

    _USAGE = {"prompt_tokens": 2000, "completion_tokens": 1000, "prompt_cache_hit_tokens": 0}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": dict(self._USAGE),
        })


class _BodyCapturingClient(_FakeClient):

    last_body: dict = {}

    async def post(self, url, headers=None, json=None):
        type(self).last_body = dict(json or {})
        return await super().post(url, headers=headers, json=json)


async def _sent_body(model: str) -> dict:
    acct = "acc_thinking_w0"
    await _seed_account(acct, cap_cents=100_000)
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _BodyCapturingClient
    try:
        await chat(model=model, messages=[{"role": "user", "content": "hi"}],
                   purpose="gen_info", account_id=acct)
    finally:
        llm_client.httpx.AsyncClient = orig
    return _BodyCapturingClient.last_body


async def case_thinking_is_always_explicit_for_deepseek():
    flash = await _sent_body("deepseek-v4-flash")
    assert flash.get("model") == "deepseek-v4-flash", flash.get("model")
    assert flash.get("thinking") == {"type": "disabled"}, flash.get("thinking")
    assert "reasoning_effort" not in flash, flash.get("reasoning_effort")

    pro = await _sent_body("deepseek-v4-pro")
    assert pro.get("model") == "deepseek-v4-pro", pro.get("model")
    assert pro.get("thinking") == {"type": "enabled"}, pro.get("thinking")
    assert pro.get("reasoning_effort"), pro


async def case_daily_cap_trips_with_llmcapexceeded():
    acct = "acc_cap_w0"
    await _seed_account(acct, cap_cents=1)
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _FakeClient
    raised = False
    succeeded = 0
    try:
        for _ in range(50):
            try:
                res = await chat(
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "hi"}],
                    purpose="gen_info",
                    account_id=acct,
                )
                succeeded += 1
                assert res.cost_cents > 0, "each fake call must record non-zero millicents"
            except LLMCapExceeded:
                raised = True
                break
    finally:
        llm_client.httpx.AsyncClient = orig

    assert succeeded >= 1, "at least one call must succeed before the cap trips"
    assert raised, "cap never tripped — soft cap has no teeth"

    async with get_session() as s:
        row = await s.scalar(
            select(GrokDailyCost).where(
                GrokDailyCost.account_id == acct, GrokDailyCost.provider == "chat"
            )
        )
    assert row is not None and row.cost_cents > 0, row
    reserve_mc = llm_client._cost_millicents(
        "deepseek-v4-flash",
        llm_client._estimate_input_tokens([{"role": "user", "content": "hi"}]),
        llm_client._ASSUMED_OUTPUT_TOKENS)
    # is_capped is not asserted: _reserve sets it in the session that raises LLMCapExceeded, which rolls back
    assert row.cost_cents + reserve_mc > 100, (
        f"the cap tripped with {row.cost_cents}mc spent and room for a {reserve_mc}mc "
        f"reserve — that reserve DID fit, so something other than the cap stopped it")



async def case_live_deepseek_records_nonzero_cost():
    real_key = (dotenv_values(_REAL_ENV).get("DEEPSEEK_API_KEY") or "").strip()
    if not real_key or real_key.startswith("test-"):
        print("    [skip] no real DEEPSEEK_API_KEY — live call not exercised")
        return
    os.environ["DEEPSEEK_API_KEY"] = real_key

    acct = "acc_live_w0"
    await _seed_account(acct, cap_cents=100)
    messages = [{"role": "user", "content": "Write about 500 words describing a sunny morning."}]
    try:
        res = await chat(
            model="deepseek-v4-flash", messages=messages, purpose="gen_info", account_id=acct,
        )
    except llm_client.LLMHTTPError as e:
        if getattr(e, "status", None) is None:
            print(f"    [skip] DeepSeek unreachable — live call not exercised ({e})")
            return
        raise

    assert res.provider == "deepseek", res.provider
    assert res.content, "flash (thinking disabled) must return non-empty content"
    assert res.cost_cents > 0, f"live call must record non-zero millicents, got {res.cost_cents}"

    async with get_session() as s:
        call = await s.get(GrokCall, res.call_id)
        assert call.status == "done", call.status
        assert call.provider == "deepseek" and call.model == "deepseek-v4-flash"
        assert (call.cost_cents or 0) > 0, call.cost_cents
        daily = await s.scalar(
            select(GrokDailyCost.cost_cents).where(
                GrokDailyCost.account_id == acct, GrokDailyCost.provider == "chat"
            )
        )
    assert (daily or 0) > 0, f"daily rollup must reflect the call, got {daily}"
    print(f"    [live] 200 OK — recorded {res.cost_cents} millicents "
          f"(in={res.tokens_in} out={res.tokens_out})")




class _FlakyClient:

    fail_times = 0
    exc = None
    calls = 0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).calls += 1
        if type(self).calls <= type(self).fail_times:
            raise type(self).exc
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                      "prompt_cache_hit_tokens": 0},
        })


async def _run_with(client_cls, *, cap_cents: int = 100_000) -> object:
    acct = "acc_retry_w0"
    await _seed_account(acct, cap_cents=cap_cents)
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = client_cls
    orig_sleep = llm_client.asyncio.sleep

    async def _no_sleep(_s):
        return None

    llm_client.asyncio.sleep = _no_sleep
    try:
        return await chat(model="deepseek-v4-flash",
                          messages=[{"role": "user", "content": "hi"}],
                          purpose="describe_media", account_id=acct)
    finally:
        llm_client.httpx.AsyncClient = orig
        llm_client.asyncio.sleep = orig_sleep


async def case_transient_timeout_is_retried_then_succeeds():
    _FlakyClient.calls = 0
    _FlakyClient.fail_times = 2
    _FlakyClient.exc = llm_client.httpx.ReadTimeout("read timed out")
    res = await _run_with(_FlakyClient)
    assert res.content == "ok", res
    assert _FlakyClient.calls == 3, f"expected 2 retries then success, got {_FlakyClient.calls}"

    async with get_session() as s:
        rows = (await s.execute(select(GrokCall).where(
            GrokCall.account_id == "acc_retry_w0",
            GrokCall.purpose == "describe_media"))).scalars().all()
    done = [r for r in rows if r.status == "done"]
    assert len(done) == 1, f"exactly one finalized call expected, got {[r.status for r in rows]}"


async def case_retry_gives_up_after_the_cap_and_records_one_error():
    _FlakyClient.calls = 0
    _FlakyClient.fail_times = 99
    _FlakyClient.exc = llm_client.httpx.ConnectError("connection refused")
    raised = False
    try:
        await _run_with(_FlakyClient)
    except llm_client.LLMHTTPError:
        raised = True
    assert raised, "a persistent transport error must still raise"
    assert _FlakyClient.calls == llm_client._LLM_MAX_ATTEMPTS, _FlakyClient.calls

    async with get_session() as s:
        rows = (await s.execute(select(GrokCall).where(
            GrokCall.account_id == "acc_retry_w0",
            GrokCall.purpose == "describe_media"))).scalars().all()
    errs = [r for r in rows if r.status == "error"]
    assert len(errs) == 1, f"one error row expected, got {[r.status for r in rows]}"


class _Http400Client(_FlakyClient):

    async def post(self, url, headers=None, json=None):
        type(self).calls += 1
        resp = _FakeResp({"error": "bad request"})

        def _raise():
            raise llm_client.httpx.HTTPStatusError(
                "400", request=llm_client.httpx.Request("POST", url),
                response=llm_client.httpx.Response(400, text="bad request"))

        resp.raise_for_status = _raise
        return resp


async def case_client_error_is_not_retried():
    _Http400Client.calls = 0
    raised = False
    try:
        await _run_with(_Http400Client)
    except llm_client.LLMHTTPError as e:
        raised = True
        assert e.status == 400, e
    assert raised, "a 400 must raise"
    assert _Http400Client.calls == 1, f"a 4xx must fail on the first try, got {_Http400Client.calls}"


_harness.run(
    case_cost_in_millicents_not_floored,
    case_wire_model_only_remaps_real_name_differences,
    case_thinking_is_always_explicit_for_deepseek,
    case_daily_cap_trips_with_llmcapexceeded,
    case_transient_timeout_is_retried_then_succeeds,
    case_retry_gives_up_after_the_cap_and_records_one_error,
    case_client_error_is_not_retried,
    case_live_deepseek_records_nonzero_cost,
)
