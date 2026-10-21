#!/usr/bin/env python3
"""test_bio_consistency.py — the creator-side twin of the prompt clock: every
conversational engine tells the model to stay consistent about HERSELF, pins the
account's configured location, and takes its texting register from the persona.

Root incident (2026-07-25, Ellafree fan 514288063 / 142678649): the reply prompt
carries only the last _HISTORY_TAIL bubbles, so in a long thread everything she
had ever said about herself had scrolled out and she re-answered from scratch.
Measured on prod: 56% of repeat biographical questions arrived with the earlier
answer already out of the window (mean gap 127 messages). One 966-turn thread
walked "nunca fui a chile" → "no soy chilena, soy argentina de verdad" → "y sí,
estoy acá en Chile" → "en córdoba", and the fan closed with "ya no creo nada".

  case_register_age_from_persona:
      persona_register_age parses both live shapes ("Age: 49 March 1977" and
      "a flirty and fabulous 22-year-old"), falls back to DEFAULT_REGISTER_AGE
      when there is no age, and REJECTS anything under 18 — an under-18 age must
      never reach a prompt whatever an operator typed into the persona box.
  case_register_age_reaches_the_builders:
      welcome_chatter_for_info renders the persona's age in the HOW YOU TEXT line
      (a register instruction — how to text — never a claim about her age).
  case_location_line:
      _persona_location_line matches send_followup's phrasing and is "" when
      unset, so an account with no location gets a byte-identical prompt.
  case_all_builders_carry_bio_guardrail:
      welcome_chatter_for_info / autoreply put the
      WHO YOU ARE rule in the system prompt — unconditionally, like the two
      guardrails it sits beside.
  case_all_builders_pin_location:
      the same prompts carry "You are based in X." when the account has a
      location, and stay byte-free of it when it doesn't.
  case_guardrail_allows_inventing_but_not_contradicting:
      the rule forbids CONTRADICTION, not improvisation — a persona can't cover
      every question, so inventing is allowed and becomes binding once said.
      This is what lets it compose with the claimed-facts ledger.

Run: ./venv/bin/python service/tests/test_bio_consistency.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()


from db.models import Fan  # noqa: E402
from automations import autoreply, welcome_chatter_for_info  # noqa: E402
from automations._common import BIO_CONSISTENCY_GUARDRAIL  # noqa: E402
from automations._persona import (  # noqa: E402
    DEFAULT_REGISTER_AGE, MODEL_NOTES_TEMPLATE, PERSONA_FACT_FIELDS, PERSONA_FACTS_OPERATOR_ONLY,
    _parse_persona_facts, _persona_facts_block, _persona_location_line,
    compose_persona, persona_register_age,
)
from geo_timezones import resolve_timezone_for_place  # noqa: E402

# The load-bearing fragment of the guardrail — asserted rather than the whole
# block so a copy-edit to the prose doesn't fail the wiring test.
_MARK = "WHO YOU ARE (hard rule)"
_LOC = "You are based in Argentina."

# Persona shapes as operators write them (fictional creators).
_ELLA = "First Name: Ella\nLast Name: Pearl\n\nAge: 20\n\nOccupation: creator"
_MIA = "First Name: Mia\n\nAge: 49 March 1977\n\nOccupation: creator"
_AVA = ("You are Ava, a playful 22-year-old OnlyFans creator "
         "from Austin, Texas.")


def _mk_of_candidate(fan_id, msgs):
    c = welcome_chatter_for_info._Candidate(fan_id)
    c.messages = list(msgs)
    c.last_body = msgs[-1][1] if msgs else ""
    return c


# ── the register age ──────────────────────────────────────────────────

def case_register_age_from_persona():
    assert persona_register_age(_MIA) == 49, "Age: line"
    assert persona_register_age(_ELLA) == 20, "Age: line, no birthday"
    assert persona_register_age(_AVA) == 22, "prose N-year-old"
    assert persona_register_age("Age: 27 5/24/99") == 27, "Age: with birthday"
    assert persona_register_age("Age: 20 years old") == 20, "Age: with words"
    assert persona_register_age("a playful, confident 23-year-old") == 23, "prose"

    # No usable age anywhere → the default, so the prompt is byte-identical to
    # what these accounts already sent.
    for blank in (None, "", "a warm, flirty OnlyFans creator"):
        assert persona_register_age(blank) == DEFAULT_REGISTER_AGE, repr(blank)

    # Under 18 is REJECTED, not clamped and not echoed.
    for minor in ("Age: 16", "Age: 8", "a 17-year-old creator", "Age: 0"):
        assert persona_register_age(minor) == DEFAULT_REGISTER_AGE, minor
    assert persona_register_age("Age: 120") == DEFAULT_REGISTER_AGE, "absurd age"


def case_register_age_reaches_the_builders():
    """The HOW YOU TEXT line is a REGISTER instruction (text young and casual),
    not an assertion about her age — but a 49yo persona shouldn't be told to
    text like a 22-year-old, so it tracks the persona."""
    f = Fan(account_id="a", fan_id=1, of_display_name="JH")
    msgs = [("in", "cuantos años tienes?")]

    for persona, want in ((_MIA, 49), (_ELLA, 20), (_AVA, 22)):
        of_m, _ = welcome_chatter_for_info._build_messages(persona, f, _mk_of_candidate(1, msgs), set())
        want_line = f"HOW YOU TEXT (a real {want}yo girl"
        assert want_line in of_m[0]["content"], f"welcome_chatter_for_info register {want}"


# ── the pinned location ───────────────────────────────────────────────

def case_location_line():
    # Phrasing matches send_followup._compose_system verbatim.
    assert _persona_location_line("Argentina") == "You are based in Argentina.\n\n"
    assert _persona_location_line("  Argentina  ") == "You are based in Argentina.\n\n"
    # Unset → "", so a no-location account's prompt is unchanged.
    for blank in (None, "", "   "):
        assert _persona_location_line(blank) == "", repr(blank)


def case_compose_persona_is_the_one_assembly_point():
    """The identity preamble — prose, location, canon — is assembled ONCE.

    There used to be three composers and they had already diverged: a since-retired
    engine folded the location into the persona string while the others carried a
    `location` builder param, a local, a loader and a call-site argument. Same
    concept, two mechanisms. compose_persona deleted that plumbing; this pins it
    shut so a fourth engine can't reintroduce a third way."""
    from types import SimpleNamespace as Cfg

    # No row at all → exactly the fallback, byte-identical to the pre-feature prompt.
    assert compose_persona(None, fallback="FB") == "FB"
    assert compose_persona(Cfg(persona="  ", location=None, persona_facts_json=None),
                           fallback="FB") == "FB"

    # Location pins under the prose.
    only_loc = compose_persona(
        Cfg(persona="Ella.", location="Argentina", persona_facts_json=None),
        fallback="FB")
    assert only_loc == "Ella.\nYou are based in Argentina.", repr(only_loc)

    # Canon pins under both, and nothing trails.
    full = compose_persona(
        Cfg(persona="Ella.", location="Argentina",
            persona_facts_json='{"age": "22", "home_city": "Cordoba"}'),
        fallback="FB")
    assert full.startswith("Ella.\nYou are based in Argentina."), repr(full[:60])
    assert "- Age: 22" in full and "- Lives in: Cordoba" in full, full
    assert full == full.rstrip(), "no trailing whitespace into the prompt"

    # Un-enriched account with no location is untouched.
    assert compose_persona(Cfg(persona="Ella.", location=None,
                               persona_facts_json=None), fallback="FB") == "Ella."


def case_composed_persona_reaches_every_builder():
    """Whatever compose_persona produced must land in every prompt. The
    builders no longer know what a location IS — they render a persona string,
    which is the point."""
    f = Fan(account_id="a", fan_id=2, of_display_name="JH")
    msgs = [("in", "donde vives?")]
    from types import SimpleNamespace as Cfg
    persona = compose_persona(
        Cfg(persona="Ella.", location="Argentina",
            persona_facts_json='{"home_city": "Rosario"}'), fallback="FB")

    of_m, _ = welcome_chatter_for_info._build_messages(persona, f, _mk_of_candidate(2, msgs), set())
    ar_m = autoreply._build_messages(persona, f, msgs, "casual")
    for name, m in (("welcome_chatter_for_info", of_m), ("autoreply", ar_m)):
        sys_prompt = m[0]["content"]
        assert _LOC in sys_prompt, f"{name}: location"
        assert "- Lives in: Rosario" in sys_prompt, f"{name}: canon"

    # And a bare persona leaves every prompt free of both.
    of_n, _ = welcome_chatter_for_info._build_messages("p", f, _mk_of_candidate(2, msgs), set())
    assert _LOC not in of_n[0]["content"], "no-location account unchanged"


# ── the guardrail itself ──────────────────────────────────────────────

def case_all_builders_carry_bio_guardrail():
    """Unconditional, like ONPLATFORM_GUARDRAIL and LIVE_PROOF_GUARDRAIL —
    there is no opt-in and no config that switches it off."""
    f = Fan(account_id="a", fan_id=3, of_display_name="JH")
    msgs = [("in", "donde creciste?")]

    of_m, _ = welcome_chatter_for_info._build_messages("p", f, _mk_of_candidate(3, msgs), set())
    assert _MARK in of_m[0]["content"], "welcome_chatter_for_info bio guardrail"

    assert _MARK in autoreply._build_messages("p", f, msgs, "casual")[0]["content"], \
        "autoreply bio guardrail"


def case_guardrail_allows_inventing_but_not_contradicting():
    """A persona can never cover every question a fan asks, so the rule targets
    CONTRADICTION, not improvisation: an invented detail is allowed and becomes
    binding the moment it is said. That is what lets the guardrail compose with
    the claimed-facts ledger instead of fighting it."""
    g = BIO_CONSISTENCY_GUARDRAIL.lower()
    # ⚠️ PROBED BY GUARANTEE, NOT BY PHRASE. The 2026-08-15 compaction restated the
    # prohibition positively — "every personal fact must match your profile + what
    # you already told him" is "never contradict" with the same teeth — so these
    # assert the four things the guardrail must still DO, and each names which.
    assert "must match your profile" in g, "the actual prohibition, stated positively"
    assert "stick to it" in g, "an improvised detail becomes binding"
    assert "improvise" in g, "inventing stays allowed"
    assert "never plead memory loss" in g, "no 'i forgot' escape hatch"
    # It must NOT issue a blanket ban on inventing — that would make her stonewall
    # every question the persona doesn't cover.
    assert "never invent" not in g, "a blanket invention ban would stonewall fans"


# ── the structured canon (persona_facts_json) ─────────────────────────

def case_persona_facts_block():
    """Renders only what is set; empty → "" so an un-enriched account sends a
    byte-identical prompt."""
    for blank in (None, "", "{}", "not json", "[1,2]", '{"nope": "x"}'):
        assert _persona_facts_block(blank) == "", repr(blank)

    block = _persona_facts_block('{"age": "22", "home_city": "Cordoba"}')
    assert "- Age: 22" in block, block
    assert "- Lives in: Cordoba" in block, block
    assert "never say anything that contradicts them" in block, "imperative framing"
    # Unset slots must not render as empty labels — a "- Kids:" line reads to
    # the model as a fact it may fill in.
    assert "Kids" not in block, block

    # A list value joins rather than rendering a Python repr into the prompt.
    assert "- Tattoos: ribs script, wrist rose" in _persona_facts_block(
        '{"tattoos": ["ribs script", "wrist rose"]}')

    # Unknown keys are dropped, not rendered.
    assert _parse_persona_facts('{"age": "22", "evil": "x"}') == {"age": "22"}


def case_facts_reach_every_engine_via_load():
    """The canon is composed at LOAD time (account-constant, never per-fan), so
    every builder gets it without another param threaded through every signature."""
    f = Fan(account_id="a", fan_id=9, of_display_name="JH")
    msgs = [("in", "donde creciste?")]
    persona = "Ella, a creator.\n\n" + _persona_facts_block(
        '{"age": "22", "home_city": "Rosario"}').rstrip()

    of_m, _ = welcome_chatter_for_info._build_messages(persona, f, _mk_of_candidate(9, msgs), set())
    ar_m = autoreply._build_messages(persona, f, msgs, "casual")
    for name, m in (("welcome_chatter_for_info", of_m), ("autoreply", ar_m)):
        assert "- Lives in: Rosario" in m[0]["content"], f"{name} canon"
        assert "Ella, a creator." in m[0]["content"], f"{name} lost the prose persona"


def case_model_notes_pin_into_the_persona_and_reach_both_engines():
    """Get to know fans' Model info (account_ai_config.model_notes) is composed into
    the persona, so info-gather and Auto-reply both see it. Empty, or the prefilled
    template left untouched, renders nothing: a byte-identical prompt."""
    from types import SimpleNamespace as Cfg

    base = dict(persona="Ella.", location=None, persona_facts_json=None)
    plain = compose_persona(Cfg(**base), fallback="FB")
    for blank in (None, "", "   ", MODEL_NOTES_TEMPLATE, MODEL_NOTES_TEMPLATE.strip()):
        assert compose_persona(Cfg(**base, model_notes=blank), fallback="FB") == plain, repr(blank)

    # A half-filled template keeps only the lines someone wrote.
    notes = MODEL_NOTES_TEMPLATE.replace("Name: ", "Name: Mia").replace("Likes: ", "Likes: hiking, sushi")
    persona = compose_persona(Cfg(persona="Ella.", model_notes=notes,
                                  location="Argentina", persona_facts_json='{"age": "22"}'), fallback="FB")
    assert "MODEL INFO" in persona and "Name: Mia" in persona and "Likes: hiking, sushi" in persona, persona
    assert "Age:" not in persona.split("MODEL INFO", 1)[1].split("THESE ARE THE FACTS", 1)[0], persona
    # Under the prose and location, above the canon; nothing trails.
    assert persona.index("You are based in") < persona.index("MODEL INFO") < persona.index("- Age: 22"), persona
    assert persona == persona.rstrip()

    f = Fan(account_id="a", fan_id=11, of_display_name="JH")
    msgs = [("in", "what do u like to do?")]
    of_m, _ = welcome_chatter_for_info._build_messages(persona, f, _mk_of_candidate(11, msgs), set())
    ar_m = autoreply._build_messages(persona, f, msgs, "casual")
    for name, m in (("welcome_chatter_for_info", of_m), ("autoreply", ar_m)):
        assert "Likes: hiking, sushi" in m[0]["content"], f"{name} lost the Model info"


async def _load_persona_reads_model_notes():
    from db.engine import get_session
    from db.models import Account, AccountAiConfig
    async with get_session() as s:
        s.add(Account(id="acc_model_notes"))
        await s.flush()
        s.add(AccountAiConfig(account_id="acc_model_notes", utc_offset=0, persona="Ella.",
                              model_notes="Name: Mia\nAge: \nWon't do (hard limits): no feet"))
    persona = await welcome_chatter_for_info._load_persona("acc_model_notes")
    assert "Name: Mia" in persona and "no feet" in persona, persona
    assert "Age:" not in persona, persona


def case_the_engines_loader_reads_model_notes_from_the_row():
    import asyncio
    asyncio.run(_load_persona_reads_model_notes())


def case_timezone_resolver_is_deterministic():
    """The zone is CODE, never model output. Six live accounts were 1-4h wrong and
    the clock block then hard-instructs the model to DEFEND the wrong hour, so a
    guessed zone is the one failure this whole feature exists to stop."""
    r = resolve_timezone_for_place
    # Every account that was wrong on 2026-07-25, from its own location text.
    assert r(free_text="Argentina") == "America/Argentina/Buenos_Aires"
    assert r(free_text="Tampa, Florida") == "America/New_York"
    assert r(free_text="Miami, Florida") == "America/New_York"
    assert r(free_text="Colombia") == "America/Bogota"
    assert r(free_text="Ljubljana, Slovenia") == "Europe/Ljubljana"
    assert r(free_text="Vancouver Island, Canada") == "America/Vancouver"
    # Hawaii must be canonical, NOT the deprecated US/Hawaii alias the raw IANA
    # tail scan would otherwise hand back.
    assert r(free_text="Hawaii") == "Pacific/Honolulu"

    # A city beats its country, and the longest key wins.
    assert r(city="Cordoba", country="Argentina") == "America/Argentina/Cordoba"
    assert r(city="Quintana Roo", country="Mexico") == "America/Cancun"

    # "la" is the Spanish definite article — it must never be read as Los Angeles.
    assert r(free_text="La Plata, Argentina") == "America/Argentina/Buenos_Aires"
    assert r(free_text="La Paz, Bolivia") == "America/La_Paz"

    # Ambiguous ⇒ None ⇒ the UI asks. Guessing here is the original bug.
    for ambiguous in ("US", "United States", "Canada", "Australia", "Brazil",
                      "Mexico", "", None):
        assert r(free_text=ambiguous) is None, f"{ambiguous!r} must stay ambiguous"


def case_fact_fields_match_the_ui():
    """PERSONA_FACT_FIELDS is the contract: the save-path allowlist, the prompt
    renderer and the BrainPanel form all key off it. A drift here means a field an
    operator can type into that silently never reaches a fan.

    The slate is driven by a measured sweep of what fans actually ask (2026-07-25)
    — relationship [325], age [173], kids [163], location [92], name [89] ..."""
    keys = [k for k, _ in PERSONA_FACT_FIELDS]
    assert len(keys) == len(set(keys)), "duplicate fact key"
    assert keys[0] == "age", "age leads — a bullet buried mid-prompt loses"
    # The high-ask core the slate was cut to on 2026-08-15 (was 26 slots).
    for expected in ("age", "job", "home_city", "relationship", "kids",
                     "family", "tattoos", "kinks", "limits"):
        assert expected in keys, expected


def case_operator_only_facts_are_never_model_authored():
    """kinks/limits are a BUSINESS decision, not something to infer. A model
    guessing them either invents a limit that costs a sale or promises something
    the creator does not offer — both worse than an empty slot."""
    keys = [k for k, _ in PERSONA_FACT_FIELDS]
    assert PERSONA_FACTS_OPERATOR_ONLY == {"kinks", "limits", "tattoos"}, \
        PERSONA_FACTS_OPERATOR_ONLY
    for k in PERSONA_FACTS_OPERATOR_ONLY:
        assert k in keys, f"{k} must still be a real field an operator can fill"


def case_operator_only_facts_still_render_when_set():
    """Skipped by enrich, but a fact like all the others once the operator fills
    it — it must reach the prompt or the whole field is decorative."""
    block = _persona_facts_block(
        '{"kinks": "loves being watched", "limits": "no feet", '
        '"tattoos": "script on left forearm"}')
    assert "- What she's into: loves being watched" in block, block
    assert "- What she won't do: no feet" in block, block
    assert "- Tattoos: script on left forearm" in block, block


CASES = [
    case_register_age_from_persona,
    case_register_age_reaches_the_builders,
    case_location_line,
    case_compose_persona_is_the_one_assembly_point,
    case_composed_persona_reaches_every_builder,
    case_all_builders_carry_bio_guardrail,
    case_guardrail_allows_inventing_but_not_contradicting,
    case_persona_facts_block,
    case_facts_reach_every_engine_via_load,
    case_model_notes_pin_into_the_persona_and_reach_both_engines,
    case_the_engines_loader_reads_model_notes_from_the_row,
    case_timezone_resolver_is_deterministic,
    case_fact_fields_match_the_ui,
    case_operator_only_facts_are_never_model_authored,
    case_operator_only_facts_still_render_when_set,
]

if __name__ == "__main__":
    for c in CASES:
        c()
        print(f"  ok  {c.__name__}")
    print("all cases passed")
