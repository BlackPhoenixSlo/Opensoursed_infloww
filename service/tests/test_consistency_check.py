#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402

import llm_client  # noqa: E402
from db.models import Fan  # noqa: E402
from automations import _persona  # noqa: E402
from automations._common import (  # noqa: E402
    CONSISTENCY_AUTOMATIONS, _parse_style_config, consistency_flag_key,
    load_consistency_flags,
)
from automations._persona import (  # noqa: E402
    asks_about_her, consistency_messages, parse_consistency_verdict,
    verify_self_consistency,
)

_PERSONA = "Ella, 20, Argentine.\n\nTHESE ARE THE FACTS ABOUT YOU.\n- Lives in: Buenos Aires"
_CLAIMED = '[{"topic":"hometown","claim":"soy de buenos aires","at":"1"}]'


class _Res:
    def __init__(self, content, parsed=None):
        self.content = content
        self.parsed = parsed


def _fake_llm(calls, *, content=None, parsed=None, raises=None):
    async def _chat(**kw):
        calls.append(kw)
        if raises is not None:
            raise raises
        return _Res(content, parsed)
    return _chat


def _run(f, draft, *, persona=_PERSONA, model="deepseek-v4-flash"):
    return asyncio.run(verify_self_consistency(
        "acc", 1, f, draft, persona, model, "welcome_chatter_for_info"))



def case_flag_is_off_unless_explicitly_enabled():
    assert asyncio.run(load_consistency_flags("no-such-account")) == {
        k: False for k in CONSISTENCY_AUTOMATIONS}, "absent config must be OFF everywhere"

    stored = _parse_style_config(json.dumps(
        {consistency_flag_key("welcome_chatter_for_info"): True}))
    resolved = {k: bool(stored.get(consistency_flag_key(k), False))
                for k in CONSISTENCY_AUTOMATIONS}
    assert resolved["welcome_chatter_for_info"] is True, resolved
    assert not any(v for k, v in resolved.items()
                   if k != "welcome_chatter_for_info"), resolved

    off = _parse_style_config(json.dumps(
        {consistency_flag_key("welcome_chatter_for_info"): False}))
    assert bool(off.get(consistency_flag_key("welcome_chatter_for_info"), False)) is False


def case_no_inert_flags():
    import pathlib

    engines = pathlib.Path(__file__).resolve().parent.parent / "automations"
    performs = {p.stem for p in engines.glob("*.py")
                if "ConsistencyCtx(" in p.read_text(encoding="utf-8")
                and p.stem != "_outbound"}
    assert performs == set(CONSISTENCY_AUTOMATIONS), (
        "consistency flags and the engines that implement the check have drifted",
        "flags:", sorted(CONSISTENCY_AUTOMATIONS), "callers:", sorted(performs))

    assert set(asyncio.run(load_consistency_flags("no-such-account"))) == performs



def case_gate_skips_replies_that_claim_nothing():
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    calls = []
    llm_client.chat = _fake_llm(calls, content='{"contradicts": false}')
    for banter in ("jaja siempre tan cuidado con lo que decís 😏",
                   "hey you, how was your day",
                   "mmm tell me more about that",
                   "", "   "):
        assert _run(f, banter) == banter, repr(banter)
    assert calls == [], f"the gate must not reach the LLM: {len(calls)} call(s)"


def case_gate_skips_when_there_is_nothing_to_check_against():
    bare = Fan(account_id="acc", fan_id=1)
    calls = []
    llm_client.chat = _fake_llm(calls, content='{"contradicts": false}')
    draft = "i grew up in rosario"
    assert _run(bare, draft, persona="") == draft
    assert calls == [], "no yardstick ⇒ no call"


def case_his_question_is_the_second_trigger():
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)

    for q in ("y en que parte vivis", "donde vives?", "how old are you",
              "are you single", "tienes novio?", "what do you do for work",
              "did you grow up there", "cuantos años tenes"):
        assert asks_about_her(q), f"MISSED a bio question: {q!r}"
    for chatter in ("hey how was your day", "send me a pic", "que lindo",
                    "you're my favorite", "", None):
        assert not asks_about_her(chatter), f"FALSE POSITIVE: {chatter!r}"

    calls = []
    llm_client.chat = _fake_llm(calls, content=json.dumps(
        {"contradicts": True, "which": "córdoba vs buenos aires",
         "fix": "en buenos aires, cora 😅"}))
    out = asyncio.run(verify_self_consistency(
        "acc", 1, f, "en córdoba, cora 😅", _PERSONA, "m", "welcome_chatter_for_info",
        last_inbound="y en que parte vivis"))
    assert out == "en buenos aires, cora 😅", out
    assert len(calls) == 1

    calls.clear()
    out2 = asyncio.run(verify_self_consistency(
        "acc", 1, f, "en córdoba, cora 😅", _PERSONA, "m", "welcome_chatter_for_info",
        last_inbound="que lindo"))
    assert out2 == "en córdoba, cora 😅" and calls == [], calls



def case_contradiction_is_rewritten():
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    calls = []
    llm_client.chat = _fake_llm(calls, content=json.dumps(
        {"contradicts": True, "which": "says Chile, already told him Argentina",
         "fix": "estoy en argentina igual que siempre 😏"}))
    out = _run(f, "y sí, estoy acá en Chile")
    assert out == "estoy en argentina igual que siempre 😏", out
    assert len(calls) == 1, calls
    user = calls[0]["messages"][1]["content"]
    assert "Buenos Aires" in user, "canon missing from the check"
    assert "soy de buenos aires" in user, "this fan's ledger missing from the check"
    assert "estoy acá en Chile" in user, "the draft itself missing"
    assert calls[0]["temperature"] == 0.0, "the verdict must not be creative"


def case_clean_draft_is_untouched():
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    calls = []
    llm_client.chat = _fake_llm(calls, content='{"contradicts": false, "which": "", "fix": ""}')
    draft = "sí, vivo en buenos aires hace años"
    assert _run(f, draft) == draft, "a clean draft must pass through byte-identical"
    assert len(calls) == 1


def case_fails_open_on_every_failure():
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    draft = "y sí, estoy acá en Chile"

    llm_client.chat = _fake_llm([], raises=llm_client.LLMCapExceeded("acc", 100, 200))
    assert _run(f, draft) == draft, "daily cap must not eat the reply"

    llm_client.chat = _fake_llm([], raises=TimeoutError("slow"))
    assert _run(f, draft) == draft, "a transport error must not eat the reply"

    for junk in ("not json", "", None, "[1,2]", "{}"):
        llm_client.chat = _fake_llm([], content=junk)
        assert _run(f, draft) == draft, f"junk {junk!r} must not eat the reply"

    llm_client.chat = _fake_llm([], content='{"contradicts": true, "which": "x"}')
    assert _run(f, draft) == draft, "contradicts=true with no fix must pass through"
    llm_client.chat = _fake_llm([], content='{"contradicts": true, "fix": "   "}')
    assert _run(f, draft) == draft, "a blank fix must pass through"


def case_verdict_parse_is_defensive():
    assert parse_consistency_verdict('{"contradicts": false}') == (False, "", "")
    ok = parse_consistency_verdict(
        '{"contradicts": true, "which": "says Chile", "fix": "estoy en argentina"}')
    assert ok == (True, "says Chile", "estoy en argentina"), ok
    assert parse_consistency_verdict(
        {"contradicts": True, "which": "w", "fix": "f"}) == (True, "w", "f")
    for junk in (None, "", "nope", "[1]", "{}", 42, '{"contradicts": true}'):
        assert parse_consistency_verdict(junk) == (False, "", ""), repr(junk)


def case_prompt_forbids_apologising_and_prefers_false():
    sysp = consistency_messages("d", "p", "")[0]["content"]
    low = sysp.lower()
    # Accept either wording: the rule is under test, not the prose.
    assert ("when in doubt, answer false" in low
            or "when in doubt: false" in low), "must bias toward leaving it alone"
    assert "never apologise" in low
    assert ("never say she forgot" in low
            or "mention a mistake" in low), "the rewrite must not confess"
    assert "language" in low, "the fix must stay in her language"
    assert "fantasy" in low
    assert ("never contradictions" in low
            or "never count" in low), "flirting/fantasy must be exempt, not judged"


def case_verifier_lives_with_its_prompt_not_in_an_engine():
    from automations import _outbound, autoreply, welcome_chatter_for_info

    assert verify_self_consistency.__module__.endswith("_persona"), \
        verify_self_consistency.__module__
    assert _outbound.verify_self_consistency is verify_self_consistency

    for eng in (welcome_chatter_for_info, autoreply):
        assert getattr(eng, "verify_self_consistency", None) is None, (
            f"{eng.__name__} holds the verifier; it must go through _outbound")


def case_claims_block_has_one_construction_site():
    import inspect
    from automations import autoreply, welcome_chatter_for_info, _persona
    for mod in (welcome_chatter_for_info, autoreply):
        src = inspect.getsource(mod)
        assert "age_claimed=getattr(" not in src, \
            f"{mod.__name__} still builds the claims block by hand"
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    assert "soy de buenos aires" in _persona.fan_claims_block(f)
    assert _persona.fan_claims_block(Fan(account_id="a", fan_id=2)) == ""


def case_check_waits_off_the_run_slot():
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    chat = llm_client.chat = _harness.parking_chat(_fake_llm(
        [], content='{"contradicts": true, "which": "w", "fix": "estoy en argentina"}'))
    out = asyncio.run(_harness.slot_parked(lambda: verify_self_consistency(
        "acc", 1, f, "y sí, estoy acá en Chile", _PERSONA, "deepseek-v4-flash",
        "welcome_chatter_for_info"), chat))
    assert out == "estoy en argentina", out


def case_lost_slot_is_not_failed_open():
    import run_slot
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    chat = llm_client.chat = _harness.parking_chat(_fake_llm(
        [], content='{"contradicts": false}'))
    real, _persona.INLINE_MAX_S = _persona.INLINE_MAX_S, 0.2
    try:
        asyncio.run(_harness.slot_parked(lambda: verify_self_consistency(
            "acc", 1, f, "y sí, estoy acá en Chile", _PERSONA, "deepseek-v4-flash",
            "welcome_chatter_for_info"), chat, keep_s=0.5))
    except run_slot.SlotLost:
        pass
    else:
        raise AssertionError("a lost slot was swallowed into 'send the draft'")
    finally:
        _persona.INLINE_MAX_S = real


CASES = [
    case_flag_is_off_unless_explicitly_enabled,
    case_no_inert_flags,
    case_gate_skips_replies_that_claim_nothing,
    case_gate_skips_when_there_is_nothing_to_check_against,
    case_his_question_is_the_second_trigger,
    case_contradiction_is_rewritten,
    case_clean_draft_is_untouched,
    case_fails_open_on_every_failure,
    case_verdict_parse_is_defensive,
    case_prompt_forbids_apologising_and_prefers_false,
    case_verifier_lives_with_its_prompt_not_in_an_engine,
    case_claims_block_has_one_construction_site,
    case_check_waits_off_the_run_slot,
    case_lost_slot_is_not_failed_open,
]

if __name__ == "__main__":
    _real = llm_client.chat
    try:
        for c in CASES:
            c()
            print(f"  ok  {c.__name__}")
    finally:
        llm_client.chat = _real
    print("all cases passed")
