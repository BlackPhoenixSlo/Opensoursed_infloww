#!/usr/bin/env python3
from __future__ import annotations

import _harness

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



def case_register_age_from_persona():
    assert persona_register_age(_MIA) == 49, "Age: line"
    assert persona_register_age(_ELLA) == 20, "Age: line, no birthday"
    assert persona_register_age(_AVA) == 22, "prose N-year-old"
    assert persona_register_age("Age: 27 5/24/99") == 27, "Age: with birthday"
    assert persona_register_age("Age: 20 years old") == 20, "Age: with words"
    assert persona_register_age("a playful, confident 23-year-old") == 23, "prose"

    for blank in (None, "", "a warm, flirty OnlyFans creator"):
        assert persona_register_age(blank) == DEFAULT_REGISTER_AGE, repr(blank)

    for minor in ("Age: 16", "Age: 8", "a 17-year-old creator", "Age: 0"):
        assert persona_register_age(minor) == DEFAULT_REGISTER_AGE, minor
    assert persona_register_age("Age: 120") == DEFAULT_REGISTER_AGE, "absurd age"


def case_register_age_reaches_the_builders():
    f = Fan(account_id="a", fan_id=1, of_display_name="JH")
    msgs = [("in", "cuantos años tienes?")]

    for persona, want in ((_MIA, 49), (_ELLA, 20), (_AVA, 22)):
        of_m, _ = welcome_chatter_for_info._build_messages(persona, f, _mk_of_candidate(1, msgs), set())
        want_line = f"HOW YOU TEXT (a real {want}yo girl"
        assert want_line in of_m[0]["content"], f"welcome_chatter_for_info register {want}"



def case_location_line():
    assert _persona_location_line("Argentina") == "You are based in Argentina.\n\n"
    assert _persona_location_line("  Argentina  ") == "You are based in Argentina.\n\n"
    for blank in (None, "", "   "):
        assert _persona_location_line(blank) == "", repr(blank)


def case_compose_persona_is_the_one_assembly_point():
    from types import SimpleNamespace as Cfg

    assert compose_persona(None, fallback="FB") == "FB"
    assert compose_persona(Cfg(persona="  ", location=None, persona_facts_json=None),
                           fallback="FB") == "FB"

    only_loc = compose_persona(
        Cfg(persona="Ella.", location="Argentina", persona_facts_json=None),
        fallback="FB")
    assert only_loc == "Ella.\nYou are based in Argentina.", repr(only_loc)

    full = compose_persona(
        Cfg(persona="Ella.", location="Argentina",
            persona_facts_json='{"age": "22", "home_city": "Cordoba"}'),
        fallback="FB")
    assert full.startswith("Ella.\nYou are based in Argentina."), repr(full[:60])
    assert "- Age: 22" in full and "- Lives in: Cordoba" in full, full
    assert full == full.rstrip(), "no trailing whitespace into the prompt"

    assert compose_persona(Cfg(persona="Ella.", location=None,
                               persona_facts_json=None), fallback="FB") == "Ella."


def case_composed_persona_reaches_every_builder():
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

    of_n, _ = welcome_chatter_for_info._build_messages("p", f, _mk_of_candidate(2, msgs), set())
    assert _LOC not in of_n[0]["content"], "no-location account unchanged"



def case_all_builders_carry_bio_guardrail():
    f = Fan(account_id="a", fan_id=3, of_display_name="JH")
    msgs = [("in", "donde creciste?")]

    of_m, _ = welcome_chatter_for_info._build_messages("p", f, _mk_of_candidate(3, msgs), set())
    assert _MARK in of_m[0]["content"], "welcome_chatter_for_info bio guardrail"

    assert _MARK in autoreply._build_messages("p", f, msgs, "casual")[0]["content"], \
        "autoreply bio guardrail"


def case_guardrail_allows_inventing_but_not_contradicting():
    g = BIO_CONSISTENCY_GUARDRAIL.lower()
    # Probed by guarantee, not by phrase: prompt compaction reworded the prohibition with the same teeth.
    assert "must match your profile" in g, "the actual prohibition, stated positively"
    assert "stick to it" in g, "an improvised detail becomes binding"
    assert "improvise" in g, "inventing stays allowed"
    assert "never plead memory loss" in g, "no 'i forgot' escape hatch"
    assert "never invent" not in g, "a blanket invention ban would stonewall fans"



def case_persona_facts_block():
    for blank in (None, "", "{}", "not json", "[1,2]", '{"nope": "x"}'):
        assert _persona_facts_block(blank) == "", repr(blank)

    block = _persona_facts_block('{"age": "22", "home_city": "Cordoba"}')
    assert "- Age: 22" in block, block
    assert "- Lives in: Cordoba" in block, block
    assert "never say anything that contradicts them" in block, "imperative framing"
    assert "Kids" not in block, block

    assert "- Tattoos: ribs script, wrist rose" in _persona_facts_block(
        '{"tattoos": ["ribs script", "wrist rose"]}')

    assert _parse_persona_facts('{"age": "22", "evil": "x"}') == {"age": "22"}


def case_facts_reach_every_engine_via_load():
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
    from types import SimpleNamespace as Cfg

    base = dict(persona="Ella.", location=None, persona_facts_json=None)
    plain = compose_persona(Cfg(**base), fallback="FB")
    for blank in (None, "", "   ", MODEL_NOTES_TEMPLATE, MODEL_NOTES_TEMPLATE.strip()):
        assert compose_persona(Cfg(**base, model_notes=blank), fallback="FB") == plain, repr(blank)

    notes = MODEL_NOTES_TEMPLATE.replace("Name: ", "Name: Mia").replace("Likes: ", "Likes: hiking, sushi")
    persona = compose_persona(Cfg(persona="Ella.", model_notes=notes,
                                  location="Argentina", persona_facts_json='{"age": "22"}'), fallback="FB")
    assert "MODEL INFO" in persona and "Name: Mia" in persona and "Likes: hiking, sushi" in persona, persona
    assert "Age:" not in persona.split("MODEL INFO", 1)[1].split("THESE ARE THE FACTS", 1)[0], persona
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
    r = resolve_timezone_for_place
    assert r(free_text="Argentina") == "America/Argentina/Buenos_Aires"
    assert r(free_text="Tampa, Florida") == "America/New_York"
    assert r(free_text="Miami, Florida") == "America/New_York"
    assert r(free_text="Colombia") == "America/Bogota"
    assert r(free_text="Ljubljana, Slovenia") == "Europe/Ljubljana"
    assert r(free_text="Vancouver Island, Canada") == "America/Vancouver"
    # Hawaii must be canonical, not the deprecated US/Hawaii alias.
    assert r(free_text="Hawaii") == "Pacific/Honolulu"

    assert r(city="Cordoba", country="Argentina") == "America/Argentina/Cordoba"
    assert r(city="Quintana Roo", country="Mexico") == "America/Cancun"

    # "la" is the Spanish article, never Los Angeles.
    assert r(free_text="La Plata, Argentina") == "America/Argentina/Buenos_Aires"
    assert r(free_text="La Paz, Bolivia") == "America/La_Paz"

    for ambiguous in ("US", "United States", "Canada", "Australia", "Brazil",
                      "Mexico", "", None):
        assert r(free_text=ambiguous) is None, f"{ambiguous!r} must stay ambiguous"


def case_fact_fields_match_the_ui():
    keys = [k for k, _ in PERSONA_FACT_FIELDS]
    assert len(keys) == len(set(keys)), "duplicate fact key"
    assert keys[0] == "age", "age leads — a bullet buried mid-prompt loses"
    for expected in ("age", "job", "home_city", "relationship", "kids",
                     "family", "tattoos", "kinks", "limits"):
        assert expected in keys, expected


def case_operator_only_facts_are_never_model_authored():
    keys = [k for k, _ in PERSONA_FACT_FIELDS]
    assert PERSONA_FACTS_OPERATOR_ONLY == {"kinks", "limits", "tattoos"}, \
        PERSONA_FACTS_OPERATOR_ONLY
    for k in PERSONA_FACTS_OPERATOR_ONLY:
        assert k in keys, f"{k} must still be a real field an operator can fill"


def case_operator_only_facts_still_render_when_set():
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
