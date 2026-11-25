#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import os  # noqa: E402
import uuid  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import tenant_keys  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, User, UserAccount  # noqa: E402
from llm_client import LLMConfigError, MODELS, chat  # noqa: E402

os.environ.setdefault("ZAI_API_KEY", "test-zai-house-key")

GLM = "glm-5.3-flash"
AIR = "glm-4.5-air"



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
    calls: int = 0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        cls = type(self)
        cls.calls += 1
        cls.last_body = dict(json or {})
        cls.last_url = str(url)
        auth = (headers or {}).get("Authorization", "")
        cls.last_bearer = auth[len("Bearer "):] if auth.startswith("Bearer ") else auth
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                      "prompt_tokens_details": {"cached_tokens": 0}},
        })


async def _seed_account(account_id: str, *owner_ids: str) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id, nickname=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            s.add(AccountAiConfig(account_id=account_id,
                                  daily_cost_cap_cents=1_000_000))
        for uid in owner_ids:
            s.add(UserAccount(user_id=uid, account_id=account_id))


async def _seed_user(username: str) -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password="x"))
    return uid


async def _fire(model: str, account_id: str, *, client=_CapturingClient, **kw):
    client.calls = 0
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = client
    try:
        return await chat(model=model, messages=[{"role": "user", "content": "hi"}],
                          purpose="gen_info", account_id=account_id, **kw)
    finally:
        llm_client.httpx.AsyncClient = orig



async def case_glm_resolves_to_zai_and_the_url_that_answers():
    mdl, prov = llm_client._resolve(GLM)
    assert prov.name == "zai", prov.name
    assert prov.base_url == "https://api.z.ai/api/paas/v4", prov.base_url
    # the documented api/openai/v1 base answers {"code":500,"msg":"404 NOT_FOUND"} under HTTP 200
    assert "api/openai/v1" not in prov.base_url, prov.base_url
    assert prov.api_key_env == "ZAI_API_KEY", prov.api_key_env
    assert mdl.wire_model() == GLM, mdl.wire_model()

    await _seed_account("acct_glm_url")
    await _fire(GLM, "acct_glm_url")
    assert _CapturingClient.last_url == \
        "https://api.z.ai/api/paas/v4/chat/completions", _CapturingClient.last_url



async def case_zai_body_carries_the_pinned_effort_and_no_thinking():
    await _seed_account("acct_glm_body")
    await _fire(GLM, "acct_glm_body")
    body = _CapturingClient.last_body

    assert body.get("model") == GLM, body.get("model")
    assert "thinking" not in body, body.get("thinking")
    assert body.get("reasoning_effort") == "low", body.get("reasoning_effort")
    assert MODELS[GLM].reasoning_effort == "low", MODELS[GLM].reasoning_effort


async def case_deepseek_reasoning_is_untouched_by_the_new_branch():
    await _seed_account("acct_ds_unmoved")

    await _fire("deepseek-v4-flash", "acct_ds_unmoved")
    flash = _CapturingClient.last_body
    assert flash.get("thinking") == {"type": "disabled"}, flash.get("thinking")
    assert "reasoning_effort" not in flash, flash.get("reasoning_effort")

    await _fire("deepseek-v4-pro", "acct_ds_unmoved")
    pro = _CapturingClient.last_body
    assert pro.get("thinking") == {"type": "enabled"}, pro.get("thinking")
    assert pro.get("reasoning_effort") == "high", pro.get("reasoning_effort")


async def case_medium_effort_is_refused_before_the_request_fires():
    await _seed_account("acct_glm_medium")

    raised = False
    try:
        await _fire(GLM, "acct_glm_medium", reasoning_effort="medium")
    except LLMConfigError as e:
        raised = True
        assert "medium" in str(e), e
    assert raised, "'medium' must be refused for a zai model"
    assert _CapturingClient.calls == 0, "a rejected effort must send nothing"

    await _fire(GLM, "acct_glm_medium", reasoning_effort="max")
    assert _CapturingClient.last_body.get("reasoning_effort") == "max", \
        _CapturingClient.last_body.get("reasoning_effort")



def case_cache_hit_tokens_read_from_whichever_field_arrived():
    f = llm_client._cache_hit_tokens

    assert f({"prompt_tokens_details": {"cached_tokens": 2432}}) == 2432
    assert f({"prompt_cache_hit_tokens": 1900}) == 1900
    assert f({"prompt_cache_hit_tokens": 0,
              "prompt_tokens_details": {"cached_tokens": 999}}) == 0
    assert f({"prompt_tokens_details": None}) is None
    assert f({"prompt_tokens_details": []}) is None
    assert f({"prompt_tokens_details": "nope"}) is None
    assert f({}) is None


def case_reasoning_tokens_are_reported_but_never_billed_twice():
    f = llm_client._reasoning_tokens
    assert f({"completion_tokens_details": {"reasoning_tokens": 8}}) == 8
    assert f({"completion_tokens_details": None}) is None
    assert f({}) is None


def case_glm_bills_the_cached_slice_at_the_hit_rate():
    mdl = MODELS[GLM]
    assert mdl.input_cache_hit_per_1k_cents < mdl.input_per_1k_cents, mdl

    cold = llm_client._cost_millicents(GLM, tokens_in=2484, tokens_out=41)
    warm = llm_client._cost_millicents(GLM, tokens_in=2484, tokens_out=41,
                                       cache_hit_tokens=2432)
    assert warm < cold, (warm, cold)

    expect = round((
        (2484 - 2432) / 1000 * mdl.input_per_1k_cents
        + 2432 / 1000 * mdl.input_cache_hit_per_1k_cents
        + 41 / 1000 * mdl.output_per_1k_cents
    ) * 100)
    assert warm == expect, (warm, expect)



def case_only_the_vision_models_are_cleared_for_an_image():
    cleared = {mid for mid, m in MODELS.items() if m.vision_ok}
    assert cleared == {"qwen3-vl-30b", "qwen3-vl-235b"}, cleared


async def case_both_describe_routes_refuse_a_text_model():
    import vault_ai_api
    from fastapi import HTTPException

    for route, payload in (
        (vault_ai_api.describe_one, {"account_id": "", "media_id": 1, "model": GLM}),
        (vault_ai_api.describe_all, {"account_id": "", "model": GLM}),
    ):
        raised = None
        try:
            await route(payload)
        except HTTPException as e:
            raised = e
        assert raised is not None, f"{route.__name__} accepted a text model"
        assert raised.status_code == 400, (route.__name__, raised.status_code)
        assert raised.detail.get("error") == "model_not_vision", \
            (route.__name__, raised.detail)

    raised = None
    try:
        await vault_ai_api.describe_all({"account_id": "", "model": "not-a-model"})
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.detail.get("error") == "unknown_model", raised

    assert "" not in vault_ai_api._describe_running, vault_ai_api._describe_running



async def case_the_new_provider_inherits_the_fail_closed_key_rule():
    owner = await _seed_user("agency_zai_none")
    await _seed_account("acct_zai_owned", owner)
    await tenant_keys.set_keys(owner, {"deepseek": "sk-theirs"})

    raised = False
    try:
        await _fire(GLM, "acct_zai_owned")
    except LLMConfigError as e:
        raised = True
        assert "zai" in str(e), e
    assert raised, "an owned account with no zai key must fail closed"
    assert _CapturingClient.calls == 0, "a fail-closed call must send nothing"

    await _seed_account("acct_zai_orphan")
    await _fire(GLM, "acct_zai_orphan")
    assert _CapturingClient.last_bearer == llm_providers.house_key("zai"), \
        _CapturingClient.last_bearer

    keyed = await _seed_user("agency_zai_keyed")
    await _seed_account("acct_zai_keyed", keyed)
    await tenant_keys.set_keys(keyed, {"zai": "sk-agency-zai"})
    await _fire(GLM, "acct_zai_keyed")
    assert _CapturingClient.last_bearer == "sk-agency-zai", _CapturingClient.last_bearer



class _Http401Client(_CapturingClient):

    async def post(self, url, headers=None, json=None):
        type(self).calls += 1
        resp = _FakeResp({"error": {"code": "1000", "message": "Authentication Failed"}})

        def _raise():
            raise llm_client.httpx.HTTPStatusError(
                "401", request=llm_client.httpx.Request("POST", url),
                response=llm_client.httpx.Response(401, text="Authentication Failed"))

        resp.raise_for_status = _raise
        return resp


async def case_a_401_fails_on_the_first_try():
    await _seed_account("acct_glm_401")
    raised = False
    try:
        await _fire(GLM, "acct_glm_401", client=_Http401Client)
    except llm_client.LLMHTTPError as e:
        raised = True
        assert e.status == 401, e
    assert raised, "a 401 must raise"
    assert 401 not in llm_client._RETRYABLE_STATUS
    assert _Http401Client.calls == 1, \
        f"a 401 must not be retried, got {_Http401Client.calls} attempts"


async def case_air_disables_thinking_with_the_object_not_the_string():
    await _seed_account("acct_air_body")
    await _fire(AIR, "acct_air_body")
    body = _CapturingClient.last_body

    assert body.get("model") == AIR, body.get("model")
    assert body.get("thinking") == {"type": "disabled"}, body.get("thinking")
    assert "reasoning_effort" not in body, body.get("reasoning_effort")
    assert dict(MODELS[AIR].reasoning_body) == {"thinking": {"type": "disabled"}}, MODELS[AIR]
    assert MODELS[AIR].effort_choices == (), MODELS[AIR]


async def case_an_effort_that_would_be_ignored_is_an_error_not_a_no_op():
    await _seed_account("acct_air_effort")
    for bad_model in (AIR, "qwen3-vl-30b"):
        raised = False
        try:
            await _fire(bad_model, "acct_air_effort", reasoning_effort="low")
        except LLMConfigError as e:
            raised = True
            assert "reasoning_effort" in str(e), e
        assert raised, f"{bad_model} must refuse an effort it cannot honour"
        assert _CapturingClient.calls == 0, "a refused call must send nothing"


def case_every_model_carries_its_own_reasoning_body():
    expected = {
        "deepseek-v4-flash": ({"thinking": {"type": "disabled"}}, ()),
        "deepseek-v4-pro": ({"thinking": {"type": "enabled"}}, ("low", "medium", "high")),
        "qwen3-vl-30b": ({}, ()), "qwen3-vl-235b": ({}, ()),
        # The effort string IS the mode here; the thinking object is a 400.
        "glm-5.3-flash": ({}, ("low", "high", "max")),
        "glm-4.5-air": ({"thinking": {"type": "disabled"}}, ()),
        "claude-opus-5-5": ({"thinking": {"type": "adaptive"}}, ()),
        "claude-sonnet-5-5": ({"thinking": {"type": "adaptive"}}, ()),
        "claude-haiku-5-5": ({"thinking": {"type": "disabled"}}, ()),
        "euryale-v2.3": ({}, ()),
        "euryale-v2.2": ({}, ()), "euryale-v2.3-deepinfra": ({}, ()),
        "hermes-4-405b": ({}, ()),
    }
    assert set(MODELS) == set(expected), set(MODELS) ^ set(expected)
    for mid, (body, choices) in expected.items():
        assert dict(MODELS[mid].reasoning_body) == body, (mid, dict(MODELS[mid].reasoning_body))
        assert MODELS[mid].effort_choices == choices, (mid, MODELS[mid].effort_choices)


def case_a_pinned_effort_must_be_one_the_model_offers():
    for mid, m in MODELS.items():
        if m.reasoning_effort:
            assert m.reasoning_effort in m.effort_choices, (mid, m.reasoning_effort)
        if m.effort_choices:
            assert m.reasoning_effort, f"{mid} offers efforts but pins none"


def case_medium_is_legal_on_one_model_and_a_400_on_another():
    assert "medium" in MODELS["deepseek-v4-pro"].effort_choices
    assert "medium" not in MODELS[GLM].effort_choices
    assert MODELS[GLM].effort_choices == ("low", "high", "max")
    assert MODELS[AIR].effort_choices == ()


def case_glm_prices_are_list_not_the_expiring_promotion():
    flash = MODELS[GLM]
    assert flash.input_per_1k_cents == 0.015, flash.input_per_1k_cents
    assert flash.input_cache_hit_per_1k_cents == 0.003, flash
    assert flash.output_per_1k_cents == 0.05, flash.output_per_1k_cents
    air, ds = MODELS[AIR], MODELS["deepseek-v4-flash"]
    assert air.input_cache_hit_per_1k_cents > ds.input_cache_hit_per_1k_cents
    assert flash.input_cache_hit_per_1k_cents > ds.input_cache_hit_per_1k_cents

    def per_call(m):
        return (1 / 1000 * m.input_per_1k_cents
                + 1332 / 1000 * m.input_cache_hit_per_1k_cents
                + 14 / 1000 * m.output_per_1k_cents)
    assert per_call(flash) < per_call(air), (per_call(flash), per_call(air))
    assert per_call(ds) < per_call(flash), "the incumbent is still the cheapest of all"


def case_neither_glm_is_offerable_for_vision():
    assert MODELS[GLM].vision_ok is False
    assert MODELS[AIR].vision_ok is False



def case_effort_options_are_per_model_and_weakest_first():
    assert llm_client.effort_options(GLM) == ["low", "high", "max"]
    assert llm_client.effort_options("deepseek-v4-pro") == ["low", "medium", "high"]
    assert llm_client.effort_options(AIR) == []
    assert llm_client.effort_options("deepseek-v4-flash") == []
    assert llm_client.effort_options("qwen3-vl-30b") == []
    assert llm_client.effort_options("not-a-model") == []
    for mid in MODELS:
        opts = llm_client.effort_options(mid)
        if opts:
            assert opts[0] == "low", (mid, opts)


async def case_the_account_effort_reaches_the_wire():
    async with get_session() as s:
        s.add(Account(id="acct_effort_cfg", nickname="acct_effort_cfg"))
        s.add(AccountAiConfig(account_id="acct_effort_cfg",
                              daily_cost_cap_cents=1_000_000,
                              model=GLM, reasoning_effort="max"))
    await _fire(GLM, "acct_effort_cfg")
    assert _CapturingClient.last_body.get("reasoning_effort") == "max", \
        _CapturingClient.last_body.get("reasoning_effort")

    await _fire(GLM, "acct_effort_cfg", reasoning_effort="high")
    assert _CapturingClient.last_body.get("reasoning_effort") == "high", \
        _CapturingClient.last_body.get("reasoning_effort")


async def case_a_stored_effort_that_no_longer_fits_is_dropped_not_raised():
    async with get_session() as s:
        s.add(Account(id="acct_effort_stale", nickname="acct_effort_stale"))
        s.add(AccountAiConfig(account_id="acct_effort_stale",
                              daily_cost_cap_cents=1_000_000,
                              model=GLM, reasoning_effort="medium"))
    await _fire(GLM, "acct_effort_stale")
    assert _CapturingClient.last_body.get("reasoning_effort") == "low", \
        _CapturingClient.last_body.get("reasoning_effort")
    assert _CapturingClient.calls == 1, "the call must still go out"

    async with get_session() as s:
        s.add(Account(id="acct_effort_inert", nickname="acct_effort_inert"))
        s.add(AccountAiConfig(account_id="acct_effort_inert",
                              daily_cost_cap_cents=1_000_000,
                              model=AIR, reasoning_effort="high"))
    await _fire(AIR, "acct_effort_inert")
    assert "reasoning_effort" not in _CapturingClient.last_body, _CapturingClient.last_body
    assert _CapturingClient.last_body.get("thinking") == {"type": "disabled"}


def case_deepseek_seeds_match_the_2026_08_16_reprice():
    flash, pro = MODELS["deepseek-v4-flash"], MODELS["deepseek-v4-pro"]
    assert (flash.input_per_1k_cents, flash.input_cache_hit_per_1k_cents,
            flash.output_per_1k_cents) == (0.044, 0.0014, 0.132), flash
    assert (pro.input_per_1k_cents, pro.input_cache_hit_per_1k_cents,
            pro.output_per_1k_cents) == (0.132, 0.0044, 0.396), pro
    assert flash.input_cache_hit_per_1k_cents != 0.00028, "stale pre-2026-08-16 seed"


def case_one_calls_body_cannot_rewrite_the_next_ones():
    mdl = MODELS["deepseek-v4-flash"]
    first = {}
    first.update(mdl.reasoning_keys())
    first["thinking"]["type"] = "MUTATED"

    second = {}
    second.update(mdl.reasoning_keys())
    assert second["thinking"] == {"type": "disabled"}, second["thinking"]
    assert dict(mdl.reasoning_body) == {"thinking": {"type": "disabled"}}, mdl.reasoning_body

    import json
    assert json.loads(json.dumps(second)) == {"thinking": {"type": "disabled"}}


_harness.run()
