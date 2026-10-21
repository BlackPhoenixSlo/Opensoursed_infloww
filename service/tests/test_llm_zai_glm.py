#!/usr/bin/env python3
"""GLM-5.3-Flash (Z.ai) registered for CHAT — and kept off the image paths.

The model is added, not swapped in: nothing routes to it until an operator
points one account's Brain at it. What that costs us is a set of assumptions
this client had quietly baked in for the two providers it already spoke to, and
each case below is one of them.

  1. The base URL is the one that ANSWERS, not the one the vendor documents.
     `https://api.z.ai/api/openai/v1` returns `{"code":500,"msg":"404 NOT_FOUND"}`
     under an HTTP **200** — a caller trusting the status code sees a successful
     request with no choices, which is the worst shape a wrong URL can take.
  2. Reasoning travels differently. DeepSeek's rule is "state the mode BOTH
     ways, never by omission"; here the `thinking` object is a hard 400 for
     every value, so the field must never be sent at all and a top-level
     `reasoning_effort` string carries it instead.
  3. That string is pinned on the MODEL, not inherited from `chat()`'s
     parameter, because ~30 call sites never pass one and the value that
     travels must be the value someone measured.
  4. `medium` — a legal DeepSeek effort, and one this module's own docstring
     used to advertise — is a 400 here. Caught before the request fires,
     because a 400 on the reply path is not one bad call, it is every
     automation on that account until someone reads a log.
  5. Cached input is reported at `prompt_tokens_details.cached_tokens`, not
     DeepSeek's top-level field. It is billed at a different rate, so reading
     the wrong one misprices the whole input.
  6. The Brain model list is derived from `MODELS.keys()`, so a text model
     becomes selectable the moment it is registered — and the describe routes
     took a model straight off the request body, one of them with no validation
     whatsoever. `vision_ok` is the gate.

Every case is offline: transports are stubbed, no provider is called, no OF
call is possible.

Run: cd service && ALLOW_ANONYMOUS_ADMIN=1 ../venv/bin/python tests/test_llm_zai_glm.py
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import os  # noqa: E402
import uuid  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import tenant_keys  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, User, UserAccount  # noqa: E402
from llm_client import LLMConfigError, MODELS, chat  # noqa: E402

# The house key for this provider, so the orphan half of the fail-closed pair
# has something to resolve TO. Matches how _harness seeds the other providers.
os.environ.setdefault("ZAI_API_KEY", "test-zai-house-key")

GLM = "glm-5.3-flash"
AIR = "glm-4.5-air"


# ── Transport stubs ───────────────────────────────────────────────────────

class _FakeResp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _CapturingClient:
    """Records the URL, body and bearer that chat() actually put on the wire —
    what left the process, not what the resolver claims it chose."""

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
            # High enough that nothing here is refused for money reasons.
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
    """One chat() call through a stubbed transport."""
    client.calls = 0
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = client
    try:
        return await chat(model=model, messages=[{"role": "user", "content": "hi"}],
                          purpose="gen_info", account_id=account_id, **kw)
    finally:
        llm_client.httpx.AsyncClient = orig


# ── 1. Registration ───────────────────────────────────────────────────────

async def case_glm_resolves_to_zai_and_the_url_that_answers():
    """The id maps to the provider, the provider to the base URL the API really
    serves, and the wire name goes out verbatim. The documented OpenAI-compat
    base is asserted ABSENT because it does not fail loudly — it 404s inside a
    200, which reads as a successful call that returned nothing."""
    mdl, prov = llm_client._resolve(GLM)
    assert prov.name == "zai", prov.name
    assert prov.base_url == "https://api.z.ai/api/paas/v4", prov.base_url
    assert "api/openai/v1" not in prov.base_url, prov.base_url
    assert prov.api_key_env == "ZAI_API_KEY", prov.api_key_env
    assert mdl.wire_model() == GLM, mdl.wire_model()

    await _seed_account("acct_glm_url")
    await _fire(GLM, "acct_glm_url")
    assert _CapturingClient.last_url == \
        "https://api.z.ai/api/paas/v4/chat/completions", _CapturingClient.last_url


# ── 2. Reasoning travels as a top-level string, never as `thinking` ───────

async def case_zai_body_carries_the_pinned_effort_and_no_thinking():
    """`thinking` is a 400 here for EVERY value, including "disabled" — so the
    rule that protects DeepSeek (always state the mode explicitly) inverts on
    this provider: never send the field. And the effort that travels is the
    MODEL's pin, not chat()'s parameter default, which no caller passes."""
    await _seed_account("acct_glm_body")
    await _fire(GLM, "acct_glm_body")
    body = _CapturingClient.last_body

    assert body.get("model") == GLM, body.get("model")
    assert "thinking" not in body, body.get("thinking")
    assert body.get("reasoning_effort") == "low", body.get("reasoning_effort")
    assert MODELS[GLM].reasoning_effort == "low", MODELS[GLM].reasoning_effort


async def case_deepseek_reasoning_is_untouched_by_the_new_branch():
    """The regression guard on the change itself. `thinking` still travels both
    ways for DeepSeek, the pro model still carries an effort, and the flash
    model still carries none — the 2026-07-24 outage contract, unmoved."""
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
    """"medium" is a legal DeepSeek effort and a hard 400 on Z.ai. A caller can
    reach it — the docstring advertised it for years — and the blast radius is
    an account's entire reply lane, silently, until someone reads a log. So it
    is caught here, and NOTHING is sent."""
    await _seed_account("acct_glm_medium")

    raised = False
    try:
        await _fire(GLM, "acct_glm_medium", reasoning_effort="medium")
    except LLMConfigError as e:
        raised = True
        assert "medium" in str(e), e
    assert raised, "'medium' must be refused for a zai model"
    assert _CapturingClient.calls == 0, "a rejected effort must send nothing"

    # A value the provider DOES accept still overrides the pin.
    await _fire(GLM, "acct_glm_medium", reasoning_effort="max")
    assert _CapturingClient.last_body.get("reasoning_effort") == "max", \
        _CapturingClient.last_body.get("reasoning_effort")


# ── 3. Usage parsing ──────────────────────────────────────────────────────

def case_cache_hit_tokens_read_from_whichever_field_arrived():
    """Absence, not truthiness. DeepSeek reports a real 0 on a cold prompt and
    `top or nested` would discard it and read the other provider's field — which,
    where both shapes are present, bills a cache MISS at the hit rate."""
    f = llm_client._cache_hit_tokens

    # Z.ai shape only.
    assert f({"prompt_tokens_details": {"cached_tokens": 2432}}) == 2432
    # DeepSeek shape only.
    assert f({"prompt_cache_hit_tokens": 1900}) == 1900
    # A REAL zero at the top level wins over the nested field.
    assert f({"prompt_cache_hit_tokens": 0,
              "prompt_tokens_details": {"cached_tokens": 999}}) == 0
    # Defensive: null, non-dict, missing.
    assert f({"prompt_tokens_details": None}) is None
    assert f({"prompt_tokens_details": []}) is None
    assert f({"prompt_tokens_details": "nope"}) is None
    assert f({}) is None


def case_reasoning_tokens_are_reported_but_never_billed_twice():
    """Providers count reasoning INSIDE completion_tokens, so it is read for the
    log line and deliberately not added to the cost — a diagnostic, not a
    column."""
    f = llm_client._reasoning_tokens
    assert f({"completion_tokens_details": {"reasoning_tokens": 8}}) == 8
    assert f({"completion_tokens_details": None}) is None
    assert f({}) is None


def case_glm_bills_the_cached_slice_at_the_hit_rate():
    """The hit rate here is DEARER than DeepSeek's (~$0.015/M vs $0.0028/M), so
    "cache hits are basically free" is not an assumption that survives the move.
    Cost must still fall when input is cached, and the miss portion must be
    billed at the miss rate."""
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


# ── 4. The vision gate ────────────────────────────────────────────────────

def case_only_the_vision_models_are_cleared_for_an_image():
    """The flag is a POLICY list, not a capability claim — GLM does accept
    images and describes them correctly. Default-off is the point: the Brain
    dropdown is `MODELS.keys()`, so the next model registered for any purpose
    must be text-only until someone says otherwise."""
    cleared = {mid for mid, m in MODELS.items() if m.vision_ok}
    assert cleared == {"qwen3-vl-30b", "qwen3-vl-235b"}, cleared


async def case_both_describe_routes_refuse_a_text_model():
    """One of these validated membership; the other validated nothing at all.
    Neither asked the question that matters. An empty account_id keeps the
    ownership gate out of the way — what is under test is the model check."""
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

    # An id that is not a model at all is still its own, different answer.
    raised = None
    try:
        await vault_ai_api.describe_all({"account_id": "", "model": "not-a-model"})
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.detail.get("error") == "unknown_model", raised

    # And the sweep must not have been started by a refused request.
    assert "" not in vault_ai_api._describe_running, vault_ai_api._describe_running


# ── 5. Credentials ────────────────────────────────────────────────────────

async def case_the_new_provider_inherits_the_fail_closed_key_rule():
    """Both directions, because only the pair proves the rule. An OWNED account
    whose agency has no zai key must fail closed — never fall through to the
    deployment's own key, which would bill the wrong party for a working call.
    An ORPHAN has no tenant to leak across and may use the house key."""
    owner = await _seed_user("agency_zai_none")
    await _seed_account("acct_zai_owned", owner)
    await tenant_keys.set_keys(owner, {"deepseek": "sk-theirs"})  # wrong provider

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

    # And an agency that DOES bring a key bills its own, not the house's.
    keyed = await _seed_user("agency_zai_keyed")
    await _seed_account("acct_zai_keyed", keyed)
    await tenant_keys.set_keys(keyed, {"zai": "sk-agency-zai"})
    await _fire(GLM, "acct_zai_keyed")
    assert _CapturingClient.last_bearer == "sk-agency-zai", _CapturingClient.last_bearer


# ── 6. Errors ─────────────────────────────────────────────────────────────

class _Http401Client(_CapturingClient):
    """A bad key answers 401 here (`{"code":"1000"}`). Retrying it cannot help,
    and three attempts per call turns one wrong key into three times the log
    noise and three times the latency on every automation."""

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
    """The fast, genuinely non-reasoning option — and the case that proves
    `reasoning_control` had to be per-MODEL. This model reads the same
    `thinking` object DeepSeek does and honours it (reasoning_content 565 chars
    enabled, 0 disabled), while its 5.3 sibling on the SAME PROVIDER answers 400
    to that field. One `prov.name ==` branch cannot serve both."""
    await _seed_account("acct_air_body")
    await _fire(AIR, "acct_air_body")
    body = _CapturingClient.last_body

    assert body.get("model") == AIR, body.get("model")
    assert body.get("thinking") == {"type": "disabled"}, body.get("thinking")
    assert "reasoning_effort" not in body, body.get("reasoning_effort")
    assert dict(MODELS[AIR].reasoning_body) == {"thinking": {"type": "disabled"}}, MODELS[AIR]
    assert MODELS[AIR].effort_choices == (), MODELS[AIR]


async def case_an_effort_that_would_be_ignored_is_an_error_not_a_no_op():
    """The trap this provider sets. glm-4.5-air accepts `reasoning_effort` with
    a **200** and ignores it — asked for "none" it returned ~15k characters of
    reasoning. A caller who passes one has a false belief about what is about to
    happen and would be charged full price for the privilege, so the mismatch is
    refused here rather than discovered on a bill. Same reasoning as DeepSeek's
    `enable_thinking:false`, which is also accepted and also does nothing."""
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
    """No model may state its mode by inference. The registry holds the literal
    body keys, so a new model added without them sends nothing and reasons at
    whatever the provider defaults to that week — which is the 2026-07-24
    outage. Pinned as an exact table so adding a model has to touch this."""
    expected = {
        "deepseek-v4-flash": ({"thinking": {"type": "disabled"}}, ()),
        "deepseek-v4-pro": ({"thinking": {"type": "enabled"}}, ("low", "medium", "high")),
        "qwen3-vl-30b": ({}, ()), "qwen3-vl-235b": ({}, ()),
        # The effort string IS the mode here; the thinking object is a 400.
        "glm-5.3-flash": ({}, ("low", "high", "max")),
        # The object IS the mode here; the effort string is accepted and ignored.
        "glm-4.5-air": ({"thinking": {"type": "disabled"}}, ()),
    }
    assert set(MODELS) == set(expected), set(MODELS) ^ set(expected)
    for mid, (body, choices) in expected.items():
        assert dict(MODELS[mid].reasoning_body) == body, (mid, dict(MODELS[mid].reasoning_body))
        assert MODELS[mid].effort_choices == choices, (mid, MODELS[mid].effort_choices)


def case_a_pinned_effort_must_be_one_the_model_offers():
    """The dropdown and the behaviour cannot be allowed to disagree. Enforced at
    IMPORT so a bad row is found by any process that starts, not by the first
    fan of the day. The predecessor let a model claim a mode it could not have:
    glm-5.3-flash, which cannot stop reasoning, was recorded as thinking=False
    and nothing read the field, so nothing objected."""
    for mid, m in MODELS.items():
        if m.reasoning_effort:
            assert m.reasoning_effort in m.effort_choices, (mid, m.reasoning_effort)
        # A model with choices must pin one — the field is mandatory on the
        # wire for the model whose mode IS the string.
        if m.effort_choices:
            assert m.reasoning_effort, f"{mid} offers efforts but pins none"


def case_medium_is_legal_on_one_model_and_a_400_on_another():
    """Why the legal set is per MODEL and not shared. "medium" is the value most
    likely to be typed from memory, is perfectly good DeepSeek, and is a hard
    400 on z.ai — and even within z.ai the two models disagree about whether the
    string is read at all, which is why a provider-keyed table could not express
    this correctly."""
    assert "medium" in MODELS["deepseek-v4-pro"].effort_choices
    assert "medium" not in MODELS[GLM].effort_choices
    assert MODELS[GLM].effort_choices == ("low", "high", "max")
    assert MODELS[AIR].effort_choices == ()


def case_glm_prices_are_list_not_the_expiring_promotion():
    """The 5.3 rates on z.ai's page today are a 50% promotion that page says
    ends 2026-09-09. Seeding the promo would leave the cap under-counting by 2x
    on a date nobody is watching — the exact failure the Qwen re-price was
    written from, which ran ~35% low for months. Erring high only tightens the
    cap, which is the safe direction."""
    flash = MODELS[GLM]
    assert flash.input_per_1k_cents == 0.015, flash.input_per_1k_cents
    assert flash.input_cache_hit_per_1k_cents == 0.003, flash
    assert flash.output_per_1k_cents == 0.05, flash.output_per_1k_cents
    # Neither GLM is a saving, and the reason is the one people get wrong: on
    # THIS workload the cached-input rate is the whole bill. Our system prompts
    # are long and stable, so ~99.9% of input is a cache hit, and every GLM
    # bills that slice ~10x the incumbent's. Headline miss prices flatter GLM
    # by pricing the tokens we almost never send.
    air, ds = MODELS[AIR], MODELS["deepseek-v4-flash"]
    assert air.input_cache_hit_per_1k_cents > ds.input_cache_hit_per_1k_cents
    assert flash.input_cache_hit_per_1k_cents > ds.input_cache_hit_per_1k_cents

    # And of the two GLMs, 5.3-flash is the cheaper on a REALISTIC call — which
    # is the opposite of what the headline miss rates suggest, and is the whole
    # basis for pointing accounts at it rather than at the faster one. Encoded
    # as a test so a future re-price cannot silently invert the choice.
    def per_call(m):
        return (1 / 1000 * m.input_per_1k_cents
                + 1332 / 1000 * m.input_cache_hit_per_1k_cents
                + 14 / 1000 * m.output_per_1k_cents)
    assert per_call(flash) < per_call(air), (per_call(flash), per_call(air))
    assert per_call(ds) < per_call(flash), "the incumbent is still the cheapest of all"


def case_neither_glm_is_offerable_for_vision():
    """Both are chat-lane models. Adding a second one must not quietly widen the
    image path — `vision_ok` defaults off precisely so this stays true without
    anyone remembering to check."""
    assert MODELS[GLM].vision_ok is False
    assert MODELS[AIR].vision_ok is False


# ── 7. Per-account effort, chosen in the Brain dropdown ──────────────────

def case_effort_options_are_per_model_and_weakest_first():
    """What the dropdown is built from. A model with no reasoning control gets
    an empty list so the editor can HIDE the box rather than offer a setting
    that does nothing — and the order is weakest-first because the editor takes
    [0] as the default when a new model is picked."""
    assert llm_client.effort_options(GLM) == ["low", "high", "max"]
    assert llm_client.effort_options("deepseek-v4-pro") == ["low", "medium", "high"]
    # No control: reasoning off, or none at all.
    assert llm_client.effort_options(AIR) == []
    assert llm_client.effort_options("deepseek-v4-flash") == []
    assert llm_client.effort_options("qwen3-vl-30b") == []
    assert llm_client.effort_options("not-a-model") == []
    # Weakest first is load-bearing, not cosmetic.
    for mid in MODELS:
        opts = llm_client.effort_options(mid)
        if opts:
            assert opts[0] == "low", (mid, opts)


async def case_the_account_effort_reaches_the_wire():
    """The dropdown\'s whole point: a saved pick overrides the model\'s pin for
    that account, with no call site passing anything."""
    async with get_session() as s:
        s.add(Account(id="acct_effort_cfg", nickname="acct_effort_cfg"))
        s.add(AccountAiConfig(account_id="acct_effort_cfg",
                              daily_cost_cap_cents=1_000_000,
                              model=GLM, reasoning_effort="max"))
    await _fire(GLM, "acct_effort_cfg")
    assert _CapturingClient.last_body.get("reasoning_effort") == "max", \
        _CapturingClient.last_body.get("reasoning_effort")

    # And an explicit caller argument still outranks it.
    await _fire(GLM, "acct_effort_cfg", reasoning_effort="high")
    assert _CapturingClient.last_body.get("reasoning_effort") == "high", \
        _CapturingClient.last_body.get("reasoning_effort")


async def case_a_stored_effort_that_no_longer_fits_is_dropped_not_raised():
    """Config outlives the choice that made it. An account moved from DeepSeek
    to z.ai keeps a "medium" that z.ai answers 400 to, and a saved value must
    never be able to take a reply lane down — so it falls back to the model\'s
    pin. This is deliberately the OPPOSITE of the caller-argument rule above,
    where the same string raises: a caller passing it is a bug in code, a
    config holding it is a Tuesday."""
    async with get_session() as s:
        s.add(Account(id="acct_effort_stale", nickname="acct_effort_stale"))
        s.add(AccountAiConfig(account_id="acct_effort_stale",
                              daily_cost_cap_cents=1_000_000,
                              model=GLM, reasoning_effort="medium"))
    await _fire(GLM, "acct_effort_stale")
    assert _CapturingClient.last_body.get("reasoning_effort") == "low", \
        _CapturingClient.last_body.get("reasoning_effort")
    assert _CapturingClient.calls == 1, "the call must still go out"

    # A stored value on a model that takes NO effort is likewise inert, not fatal.
    async with get_session() as s:
        s.add(Account(id="acct_effort_inert", nickname="acct_effort_inert"))
        s.add(AccountAiConfig(account_id="acct_effort_inert",
                              daily_cost_cap_cents=1_000_000,
                              model=AIR, reasoning_effort="high"))
    await _fire(AIR, "acct_effort_inert")
    assert "reasoning_effort" not in _CapturingClient.last_body, _CapturingClient.last_body
    assert _CapturingClient.last_body.get("thinking") == {"type": "disabled"}


def case_deepseek_seeds_match_the_2026_08_16_reprice():
    """DeepSeek re-priced on 2026-08-16 and these seeds sat twelve days behind
    it, metering the models that carry nearly all the traffic at a FIFTH of
    their real rate. Seeded at PEAK on purpose — the cap has to assume the
    dearer hour, because over-stating off-peak spend is harmless and the
    opposite mistake lets a sweep run past a limit that was never real."""
    flash, pro = MODELS["deepseek-v4-flash"], MODELS["deepseek-v4-pro"]
    assert (flash.input_per_1k_cents, flash.input_cache_hit_per_1k_cents,
            flash.output_per_1k_cents) == (0.044, 0.0014, 0.132), flash
    assert (pro.input_per_1k_cents, pro.input_cache_hit_per_1k_cents,
            pro.output_per_1k_cents) == (0.132, 0.0044, 0.396), pro
    # The pre-re-price seeds, named so this cannot quietly slide back.
    assert flash.input_cache_hit_per_1k_cents != 0.00028, "stale pre-2026-08-16 seed"


def case_one_calls_body_cannot_rewrite_the_next_ones():
    """The registry's reasoning fragments live for the life of the process and
    are shared by every account, so they are handed out as COPIES. Splicing the
    originals in would mean one in-place edit of one request body silently
    changing the reasoning mode of every later call on the deployment — and the
    nested dict is not something MappingProxyType can protect, because a
    mappingproxy cannot be JSON-serialized onto the wire."""
    mdl = MODELS["deepseek-v4-flash"]
    first = {}
    first.update(mdl.reasoning_keys())
    first["thinking"]["type"] = "MUTATED"       # the failure mode, forced

    second = {}
    second.update(mdl.reasoning_keys())
    assert second["thinking"] == {"type": "disabled"}, second["thinking"]
    assert dict(mdl.reasoning_body) == {"thinking": {"type": "disabled"}}, mdl.reasoning_body

    # And what the registry yields must survive json.dumps — httpx serializes
    # this dict, so an unserializable value here is a dead reply lane.
    import json
    assert json.loads(json.dumps(second)) == {"thinking": {"type": "disabled"}}


_harness.run()
