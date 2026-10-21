#!/usr/bin/env python3
"""W0 — DeepSeek wire-name + MILLICENT cost accounting + daily-cap teeth.

Three things this wave fixed, each a case below:

  1. _cost_millicents counts in cents x100, so a real DeepSeek call no longer
     floors to 0 (the old int(round(cents)) bug) — the rollup can accumulate.
  2. chat() reserves/reconciles in millicents against a (cents x100) cap, so the
     per-account daily soft cap actually trips → LLMCapExceeded. Driven here with
     a stubbed transport (no network, deterministic).
  3. DeepSeek ids go to the wire VERBATIM (no api_model remap), and reasoning
     on/off travels as an explicit `thinking` body flag — both ways, never by
     omission. api_model is for genuine name differences (DeepInfra's vendor
     paths) and must never encode a mode: this used to pick thinking via the
     model NAME, DeepSeek retired those aliases on 2026-07-24, and every LLM
     automation on every account 400'd for 35 minutes.

Plus an OPTIONAL live case: a real DeepSeek call returns 200, comes back with
NON-EMPTY content, and records a non-zero millicent cost. This is the canary for
(3) — provider drift is not something the type system can catch, so it wants a
scheduled run, not just a pre-deploy one. Omitting the thinking flag makes the
flash model burn its whole output budget reasoning and return content="", so the
non-empty assertion is load-bearing, not decoration. It self-skips when the real
key is absent (the harness injects a fake one) or the network is unreachable, so
the suite stays green offline.

Run: ./venv/bin/python service/tests/test_llm_millicents.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

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
    """grok_daily_cost.account_id + account_ai_config FK accounts.id."""
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            s.add(AccountAiConfig(account_id=account_id, daily_cost_cap_cents=cap_cents))


# ── 1. millicent resolution ──────────────────────────────────────────────

def case_cost_in_millicents_not_floored():
    """A real-sized DeepSeek call is sub-cent but NON-zero in millicents; the
    same call under the old whole-cent rounding would have been 0."""
    mc = llm_client._cost_millicents("deepseek-v4-flash", tokens_in=2000, tokens_out=1000)
    assert mc > 0, f"expected non-zero millicents, got {mc}"
    # Old behavior, reconstructed: round(cents) where cents < 0.5 → 0.
    mdl = MODELS["deepseek-v4-flash"]
    cents = 2000 / 1000 * mdl.input_per_1k_cents + 1000 / 1000 * mdl.output_per_1k_cents
    assert cents < 1.0 and round(cents) == 0, f"precondition: call should be sub-cent ({cents}c)"
    assert mc == round(cents * 100), (mc, cents)


def case_wire_model_only_remaps_real_name_differences():
    """api_model exists for genuine vendor-path differences — NOT to encode a
    mode. DeepSeek names its models the way we do, so id == wire; only
    DeepInfra publishes a different path. The predecessor of this case asserted
    `wire_model() == "deepseek-chat"`, which pinned the mapping rather than
    testing it: it would have gone RED on the fix and stayed green through the
    outage. Assert the invariant instead — no remap without a real difference.
    """
    for mid in ("deepseek-v4-flash", "deepseek-v4-pro"):
        assert MODELS[mid].wire_model() == mid, (mid, MODELS[mid].wire_model())
        assert not MODELS[mid].api_model, f"{mid} must not remap its wire name"
    assert MODELS["qwen3-vl-30b"].wire_model() == "Qwen/Qwen3-VL-30B-A3B-Instruct"


# ── 2. the daily cap actually trips (stubbed transport, no network) ───────

class _FakeResp:
    status_code = 200

    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):  # 200 → no-op
        return None

    def json(self):
        return self._data


class _FakeClient:
    """Drop-in for httpx.AsyncClient that returns a canned 200 with usage so
    chat() records a real millicent cost without touching the network."""

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
    """Records the JSON body chat() actually put on the wire."""

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
    """Reasoning mode is stated BOTH ways, never by omission. An absent
    `thinking` field means "whatever DeepSeek defaults to today", which is the
    assumption that broke us — and on the flash model it is the SILENT failure:
    the call 200s but burns its whole output budget reasoning and comes back
    with content="". Providers that reject the field must not receive it.
    """
    flash = await _sent_body("deepseek-v4-flash")
    assert flash.get("model") == "deepseek-v4-flash", flash.get("model")
    assert flash.get("thinking") == {"type": "disabled"}, flash.get("thinking")
    assert "reasoning_effort" not in flash, flash.get("reasoning_effort")

    pro = await _sent_body("deepseek-v4-pro")
    assert pro.get("model") == "deepseek-v4-pro", pro.get("model")
    assert pro.get("thinking") == {"type": "enabled"}, pro.get("thinking")
    assert pro.get("reasoning_effort"), pro


async def case_daily_cap_trips_with_llmcapexceeded():
    """With a tiny 1-cent (=100 millicent) cap, repeated calls accumulate real
    millicent cost until a reservation no longer fits → LLMCapExceeded. Proves
    the cap has teeth (it never did while sub-cent calls floored to 0)."""
    acct = "acc_cap_w0"
    await _seed_account(acct, cap_cents=1)  # 1 cent == 100 millicents
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

    # The cap gates each RESERVATION, not the post-hoc actual-vs-estimate
    # reconcile, so the final rollup may land a single call's delta over the cap.
    # What matters: real millicent cost accumulated until a reserve no longer fit.
    # (The is_capped flag is intentionally NOT asserted: _reserve writes it in the
    # same session that then raises LLMCapExceeded, which get_session rolls back —
    # a pre-existing observability quirk, not part of this wave's cap-teeth fix.)
    async with get_session() as s:
        row = await s.scalar(
            select(GrokDailyCost).where(
                GrokDailyCost.account_id == acct, GrokDailyCost.provider == "deepseek"
            )
        )
    assert row is not None and row.cost_cents > 0, row
    # Assert the INVARIANT, not a number tuned to a price list. The cap trips
    # when the next RESERVATION no longer fits, so accumulated spend lands
    # within one reservation of the cap — wherever prices happen to be. The
    # previous `>= 100` was a proxy for that and it went stale the moment
    # DeepSeek re-priced on 2026-08-16: real spend reached 88 of a 100-millicent
    # cap and the reserve for call nine was 14, which is the cap working
    # exactly as designed and a test failing anyway.
    reserve_mc = llm_client._cost_millicents(
        "deepseek-v4-flash",
        llm_client._estimate_input_tokens([{"role": "user", "content": "hi"}]),
        llm_client._ASSUMED_OUTPUT_TOKENS)
    assert row.cost_cents + reserve_mc > 100, (
        f"the cap tripped with {row.cost_cents}mc spent and room for a {reserve_mc}mc "
        f"reserve — that reserve DID fit, so something other than the cap stopped it")


# ── 3. OPTIONAL live call — real 200 + non-zero millicent cost ────────────

async def case_live_deepseek_records_nonzero_cost():
    """A real DeepSeek call returns 200, non-empty content, and a non-zero
    millicent cost. THE provider-drift canary: no local structure can detect
    that DeepSeek renamed a model or flipped its reasoning default — only a real
    call can. Self-skips without a real key / network so the suite stays green
    offline."""
    real_key = (dotenv_values(_REAL_ENV).get("DEEPSEEK_API_KEY") or "").strip()
    if not real_key or real_key.startswith("test-"):
        print("    [skip] no real DEEPSEEK_API_KEY — live call not exercised")
        return
    os.environ["DEEPSEEK_API_KEY"] = real_key  # harness injected a fake; use the real one

    acct = "acc_live_w0"
    await _seed_account(acct, cap_cents=100)  # generous cap for a single call
    # Ask for enough output that the (sub-cent) cost still rounds to >=1 millicent.
    # At the 2026-06 DeepSeek price ($0.28/1M out) 1 millicent ≈ 357 output tokens,
    # so request ~500 words (~650 tokens) to clear the rounding floor reliably.
    messages = [{"role": "user", "content": "Write about 500 words describing a sunny morning."}]
    try:
        res = await chat(
            model="deepseek-v4-flash", messages=messages, purpose="gen_info", account_id=acct,
        )
    except llm_client.LLMHTTPError as e:
        if getattr(e, "status", None) is None:  # network/transport failure → skip, don't fail
            print(f"    [skip] DeepSeek unreachable — live call not exercised ({e})")
            return
        raise  # a real non-2xx (e.g. 400) IS a failure

    assert res.provider == "deepseek", res.provider
    # Load-bearing: with thinking left implicit this 200s with content="".
    assert res.content, "flash (thinking disabled) must return non-empty content"
    assert res.cost_cents > 0, f"live call must record non-zero millicents, got {res.cost_cents}"

    async with get_session() as s:
        call = await s.get(GrokCall, res.call_id)
        assert call.status == "done", call.status
        assert call.provider == "deepseek" and call.model == "deepseek-v4-flash"
        assert (call.cost_cents or 0) > 0, call.cost_cents
        daily = await s.scalar(
            select(GrokDailyCost.cost_cents).where(
                GrokDailyCost.account_id == acct, GrokDailyCost.provider == "deepseek"
            )
        )
    assert (daily or 0) > 0, f"daily rollup must reflect the call, got {daily}"
    print(f"    [live] 200 OK — recorded {res.cost_cents} millicents "
          f"(in={res.tokens_in} out={res.tokens_out})")


# ── 4. Transient-failure retry (the single fire, 19 §2 step 4) ────────────
#
# A one-shot POST made a flaky provider a PERMANENT per-item failure: a
# DeepInfra ReadTimeout stamped `describe_status='failed'` with no retry, so a
# 97-item vault sweep left a random 3-5 undone every run. Every automation
# funnels through `chat()`, so the retry lives here. These drive it with a
# transport that fails N times then succeeds — no network, no sleep of note
# (backoff is 1.5s×attempt, ~4.5s worst case).


class _FlakyClient:
    """Transport that raises `exc` on its first `fail_times` posts, then returns
    a canned 200. One class instance is shared across attempts via a class-level
    counter, because chat() builds a fresh `httpx.AsyncClient()` per attempt."""

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
    # No real waiting between attempts.
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
    """Two ReadTimeouts then a 200 → chat() returns the 200. Before the retry
    the FIRST timeout raised and the item was marked failed forever."""
    _FlakyClient.calls = 0
    _FlakyClient.fail_times = 2
    _FlakyClient.exc = llm_client.httpx.ReadTimeout("read timed out")
    res = await _run_with(_FlakyClient)
    assert res.content == "ok", res
    assert _FlakyClient.calls == 3, f"expected 2 retries then success, got {_FlakyClient.calls}"

    # The audit row is finalized ONCE, as done — not one error row per attempt.
    async with get_session() as s:
        rows = (await s.execute(select(GrokCall).where(
            GrokCall.account_id == "acc_retry_w0",
            GrokCall.purpose == "describe_media"))).scalars().all()
    done = [r for r in rows if r.status == "done"]
    assert len(done) == 1, f"exactly one finalized call expected, got {[r.status for r in rows]}"


async def case_retry_gives_up_after_the_cap_and_records_one_error():
    """Persistent timeouts exhaust the attempts and raise LLMHTTPError — with a
    SINGLE error row and the reservation released once, not per attempt."""
    _FlakyClient.calls = 0
    _FlakyClient.fail_times = 99  # never recovers
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
    """A 400 is a real client error — bad request, auth, content refusal — and
    must NOT be retried: a re-fire cannot fix it and only wastes the provider."""

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
