#!/usr/bin/env python3
"""test_consistency_check.py — PHASE 2: verify the draft before it is sent.

The guardrail states the rule (never contradict yourself), the canon and the
claims ledger supply the answers — and nothing checked the outcome. That gap is
measurable rather than theoretical: on prod, 323 of 468 times the AI re-asked a
question it had already asked, the earlier asking was STILL INSIDE the history
window, and it asked a $691 fan his job with `occupation` populated AND injected.
Injection is necessary and not sufficient. This is the sufficiency half.

  case_flag_is_off_unless_explicitly_enabled:
      the trap this nearly shipped with — _resolve_style_flag falls back to
      _STYLE_DEFAULT_ON, so routing this layer through it could switch a paid
      second call on for every account whose engine defaults a style flag ON.
      Explicit-only resolution, verified per automation.
  case_gate_skips_replies_that_claim_nothing:
      no self-claim in the DRAFT ⇒ no call. This is the cost bound: a reply that
      says nothing about her cannot contradict anything.
  case_gate_skips_when_there_is_nothing_to_check_against:
      no canon and no ledger ⇒ no call.
  case_contradiction_is_rewritten:
      a draft that fights the ledger comes back as the model's minimal fix.
  case_clean_draft_is_untouched:
      byte-identical passthrough — the common case must not be perturbed.
  case_fails_open_on_every_failure:
      cap, timeout, junk JSON, and a `true` verdict with no usable fix all return
      the ORIGINAL draft. A verifier that can swallow a reply is worse than the
      contradiction it exists to catch.
  case_verdict_parse_is_defensive:
      the parser alone, over the shapes a model actually emits.

Run: ./venv/bin/python service/tests/test_consistency_check.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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


# ── the flag ──────────────────────────────────────────────────────────

def case_flag_is_off_unless_explicitly_enabled():
    """Caught the first time this was run: routing through _resolve_style_flag
    returned the engine's _STYLE_DEFAULT_ON value, silently enabling a PAID
    second call on every account of that engine. Explicit-only, or it is not
    opt-in."""
    assert asyncio.run(load_consistency_flags("no-such-account")) == {
        k: False for k in CONSISTENCY_AUTOMATIONS}, "absent config must be OFF everywhere"

    # An explicit True switches exactly one automation on, and nothing else.
    stored = _parse_style_config(json.dumps(
        {consistency_flag_key("welcome_chatter_for_info"): True}))
    resolved = {k: bool(stored.get(consistency_flag_key(k), False))
                for k in CONSISTENCY_AUTOMATIONS}
    assert resolved["welcome_chatter_for_info"] is True, resolved
    assert not any(v for k, v in resolved.items()
                   if k != "welcome_chatter_for_info"), resolved

    # An explicit False is honoured (not treated as absent).
    off = _parse_style_config(json.dumps(
        {consistency_flag_key("welcome_chatter_for_info"): False}))
    assert bool(off.get(consistency_flag_key("welcome_chatter_for_info"), False)) is False


def case_no_inert_flags():
    """Every flag this feature exposes must reach an engine that PERFORMS the check.

    Keying the flags off STYLE_AUTOMATIONS (the wider tuple) minted consistency
    flags for engines without the call (e.g. `consistency_autoreply`): settable,
    persisted, and
    read by nothing, so an operator could switch on a check that no code performs
    and get silence. That is the same shape as the hot-lead trinity flag deleted in
    dc2c3b8 — an operator-facing switch wired to nothing.

    This asserts the two halves can't drift: the flag list is exactly the set of
    engine modules that hand _outbound.finalize_draft a ConsistencyCtx. Wiring a
    third engine fails here until CONSISTENCY_AUTOMATIONS is widened to match, and
    widening it ahead of the wiring fails here too.

    Anchored on ConsistencyCtx rather than on `verify_self_consistency(` because
    every engine now reaches the verifier through the shared send chokepoint —
    grepping for the call itself would only ever find _outbound, and would have
    quietly stopped testing anything the moment that refactor landed. (It did not
    stay quiet: this case failed on exactly that, which is why it reads this way.)"""
    import pathlib

    engines = pathlib.Path(__file__).resolve().parent.parent / "automations"
    performs = {p.stem for p in engines.glob("*.py")
                if "ConsistencyCtx(" in p.read_text(encoding="utf-8")
                and p.stem != "_outbound"}         # _outbound DEFINES it
    assert performs == set(CONSISTENCY_AUTOMATIONS), (
        "consistency flags and the engines that implement the check have drifted",
        "flags:", sorted(CONSISTENCY_AUTOMATIONS), "callers:", sorted(performs))

    # And the loader really only hands back those keys.
    assert set(asyncio.run(load_consistency_flags("no-such-account"))) == performs


# ── the gate (this is the cost bound) ─────────────────────────────────

def case_gate_skips_replies_that_claim_nothing():
    """A reply that says nothing about her cannot contradict anything, so skipping
    is free rather than a heuristic. This is what keeps it off ~95% of replies."""
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
    """No canon and no ledger ⇒ nothing to be inconsistent WITH."""
    bare = Fan(account_id="acc", fan_id=1)
    calls = []
    llm_client.chat = _fake_llm(calls, content='{"contradicts": false}')
    draft = "i grew up in rosario"
    assert _run(bare, draft, persona="") == draft
    assert calls == [], "no yardstick ⇒ no call"


def case_his_question_is_the_second_trigger():
    """An ELLIPTICAL answer carries no first-person verb: "en córdoba, cora 😅"
    states her city while matching no self-claim pattern. That was step three of
    the real Chile cascade, and the first version of this gate missed it live.

    So the gate also fires on HIS biographical question — the claim is in the
    exchange even when it is not in her sentence."""
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)

    for q in ("y en que parte vivis", "donde vives?", "how old are you",
              "are you single", "tienes novio?", "what do you do for work",
              "did you grow up there", "cuantos años tenes"):
        assert asks_about_her(q), f"MISSED a bio question: {q!r}"
    for chatter in ("hey how was your day", "send me a pic", "que lindo",
                    "you're my favorite", "", None):
        assert not asks_about_her(chatter), f"FALSE POSITIVE: {chatter!r}"

    # Elliptical draft + a bio question ⇒ the check runs.
    calls = []
    llm_client.chat = _fake_llm(calls, content=json.dumps(
        {"contradicts": True, "which": "córdoba vs buenos aires",
         "fix": "en buenos aires, cora 😅"}))
    out = asyncio.run(verify_self_consistency(
        "acc", 1, f, "en córdoba, cora 😅", _PERSONA, "m", "welcome_chatter_for_info",
        last_inbound="y en que parte vivis"))
    assert out == "en buenos aires, cora 😅", out
    assert len(calls) == 1

    # The same elliptical draft with NO question before it stays free.
    calls.clear()
    out2 = asyncio.run(verify_self_consistency(
        "acc", 1, f, "en córdoba, cora 😅", _PERSONA, "m", "welcome_chatter_for_info",
        last_inbound="que lindo"))
    assert out2 == "en córdoba, cora 😅" and calls == [], calls


# ── the verdict ───────────────────────────────────────────────────────

def case_contradiction_is_rewritten():
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    calls = []
    llm_client.chat = _fake_llm(calls, content=json.dumps(
        {"contradicts": True, "which": "says Chile, already told him Argentina",
         "fix": "estoy en argentina igual que siempre 😏"}))
    out = _run(f, "y sí, estoy acá en Chile")
    assert out == "estoy en argentina igual que siempre 😏", out
    assert len(calls) == 1, calls
    # The check must see BOTH yardsticks, or it cannot judge.
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
    """This sits between generation and send. Every failure mode must return the
    ORIGINAL draft — a verifier that can silently swallow a reply is a worse
    failure than the contradiction it exists to catch."""
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    draft = "y sí, estoy acá en Chile"

    llm_client.chat = _fake_llm([], raises=llm_client.LLMCapExceeded("acc", 100, 200))
    assert _run(f, draft) == draft, "daily cap must not eat the reply"

    llm_client.chat = _fake_llm([], raises=TimeoutError("slow"))
    assert _run(f, draft) == draft, "a transport error must not eat the reply"

    for junk in ("not json", "", None, "[1,2]", "{}"):
        llm_client.chat = _fake_llm([], content=junk)
        assert _run(f, draft) == draft, f"junk {junk!r} must not eat the reply"

    # A verdict we cannot act on is not a verdict.
    llm_client.chat = _fake_llm([], content='{"contradicts": true, "which": "x"}')
    assert _run(f, draft) == draft, "contradicts=true with no fix must pass through"
    llm_client.chat = _fake_llm([], content='{"contradicts": true, "fix": "   "}')
    assert _run(f, draft) == draft, "a blank fix must pass through"


def case_verdict_parse_is_defensive():
    assert parse_consistency_verdict('{"contradicts": false}') == (False, "", "")
    ok = parse_consistency_verdict(
        '{"contradicts": true, "which": "says Chile", "fix": "estoy en argentina"}')
    assert ok == (True, "says Chile", "estoy en argentina"), ok
    # A pre-parsed dict (llm_client.parsed) works the same as raw text.
    assert parse_consistency_verdict(
        {"contradicts": True, "which": "w", "fix": "f"}) == (True, "w", "f")
    for junk in (None, "", "nope", "[1]", "{}", 42, '{"contradicts": true}'):
        assert parse_consistency_verdict(junk) == (False, "", ""), repr(junk)


def case_prompt_forbids_apologising_and_prefers_false():
    """Two failure modes the prompt has to pre-empt: a rewrite that apologises
    reads worse than the contradiction, and an over-eager verifier rewrites
    messages that were fine."""
    sysp = consistency_messages("d", "p", "")[0]["content"]
    low = sysp.lower()
    # main's prompt-diet pass (0bf4d80) compacted "- When in doubt, answer false."
    # to "when in doubt: false." and did not come back for this assertion, so this
    # case has been red on main since. The RULE is what the test is for; accept
    # either wording rather than pin the prose it happens to be written in.
    assert ("when in doubt, answer false" in low
            or "when in doubt: false" in low), "must bias toward leaving it alone"
    # Same compaction: "never say she forgot" became "or mention a mistake".
    assert "never apologise" in low
    assert ("never say she forgot" in low
            or "mention a mistake" in low), "the rewrite must not confess"
    assert "language" in low, "the fix must stay in her language"
    # Flirting/fantasy must be explicitly exempt or every tease trips it.
    assert "fantasy" in low
    assert ("never contradictions" in low
            or "never count" in low), "flirting/fantasy must be exempt, not judged"


def case_verifier_lives_with_its_prompt_not_in_an_engine():
    """The verifier is engine-agnostic and _persona already owned both halves of it
    (the prompt and the parser). It was once defined in one engine and IMPORTED
    by another — the same cross-engine broker pattern that _nonempty had, deleted
    one commit earlier and then reintroduced for a bigger function.

    No engine may reach it through another engine. Since the send chokepoint was
    extracted, no engine reaches it DIRECTLY either — _outbound is the single
    caller — so this now asserts the stronger thing: the verifier is absent from
    every engine's namespace, and only the chokepoint and its owner know it."""
    from automations import _outbound, autoreply, welcome_chatter_for_info

    assert verify_self_consistency.__module__.endswith("_persona"), \
        verify_self_consistency.__module__
    # The chokepoint reaches the canonical owner, unrebound.
    assert _outbound.verify_self_consistency is verify_self_consistency

    # No ENGINE holds it at all — not defined, not imported, not re-exported.
    for eng in (welcome_chatter_for_info, autoreply):
        assert getattr(eng, "verify_self_consistency", None) is None, (
            f"{eng.__name__} holds the verifier; it must go through _outbound")


def case_claims_block_has_one_construction_site():
    """The four-getattr dance had reached three verbatim copies. fan_claims_block
    takes the row, so the column names are spelled once."""
    import inspect
    from automations import autoreply, welcome_chatter_for_info, _persona
    for mod in (welcome_chatter_for_info, autoreply):
        src = inspect.getsource(mod)
        assert "age_claimed=getattr(" not in src, \
            f"{mod.__name__} still builds the claims block by hand"
    f = Fan(account_id="acc", fan_id=1, persona_claims_json=_CLAIMED)
    assert "soy de buenos aires" in _persona.fan_claims_block(f)
    assert _persona.fan_claims_block(Fan(account_id="a", fan_id=2)) == ""


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
