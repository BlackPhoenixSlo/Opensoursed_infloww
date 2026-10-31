#!/usr/bin/env python3
"""automations.names — characterisation tables for what we may CALL a fan
(strip_spend_tier / is_place_word / is_greetable_name / name_token /
resolve_fan_name / build_structured_nickname). Risk = the wrong name in a fan
DM or the OF chat header, so the rows lean on emoji, spend-tier suffixes,
place words, empty/None, whitespace and username-like handles. Pins today's
behaviour, including rows that look questionable (marked PIN: in the label).
Pure; no DB writes (Fan rows are transient).

Run: ./venv/bin/python service/tests/test_names.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from db.models import Fan  # noqa: E402
from automations.names import (  # noqa: E402
    build_structured_nickname,
    is_greetable_name,
    is_place_word,
    name_token,
    resolve_fan_name,
    strip_spend_tier,
)


def case_strip_spend_tier():
    rows = [
        (None, "", "None"),
        ("", "", "empty"),
        ("DaddyWilko/Free", "DaddyWilko", "trailing /Free"),
        ("Garrett/Delta,Canada/30/Spender", "Garrett/Delta,Canada/30", "trailing /Spender"),
        ("Spender", "", "tier only collapses"),
        ("WHALE/Bob", "Bob", "case-insensitive, leading tier"),
        ("Bob/buyer/30", "Bob/30", "middle tier"),
        ("Freeman/Freetown/Freelancer", "Freeman/Freetown/Freelancer", "substrings survive"),
        ("Free Spender", "Free Spender", "multi-word segment is not a tier"),
        (" Bob / free / 30 ", "Bob/30", "segments trimmed"),
        ("Bob//30", "Bob/30", "empty segment dropped"),
        ("/Christopher/", "Christopher", "leading/trailing slash"),
        ("Mike😈/Free", "Mike😈", "emoji kept"),
    ]
    for raw, exp, label in rows:
        got = strip_spend_tier(raw)
        assert got == exp, f"strip_spend_tier[{label}]: got {got!r}, expected {exp!r}"


def case_is_place_word():
    rows = [
        (None, False, "None"),
        ("", False, "empty"),
        ("   ", False, "whitespace"),
        ("Canada", True, "country"),
        (" CANADA, ", True, "case + trailing comma"),
        ("canada.", True, "trailing dot"),
        ("New   York", True, "multi-word, whitespace collapsed"),
        ("York", False, "tail of New York is not listed"),
        ("Zealand", True, "tail word of New Zealand listed"),
        ("usa", True, "code"),
        ("us", True, "two-letter code"),
        ("Free", True, "spend tier"),
        ("Whale", True, "spend tier"),
        ("Freeman", False, "tier substring"),
        ("Chad", False, "place that is also a name"),
        ("Jordan", False, "place that is also a name"),
        ("Austin", False, "cities are not listed"),
        ("unknown", True, "placeholder word"),
        ("Canada!", False, "PIN: only . and , are stripped"),
    ]
    for s, exp, label in rows:
        got = is_place_word(s)
        assert got is exp, f"is_place_word[{label}]: got {got!r}, expected {exp!r}"


def case_is_greetable_name():
    rows = [
        # (s, here, expected, label)
        (None, (), False, "None"),
        ("", (), False, "empty"),
        ("   ", (), False, "whitespace"),
        (",", (), False, "no letters"),
        ("😀", (), False, "emoji only"),
        ("Mike 😀", (), True, "name + emoji"),
        ("u1234567", (), False, "handle with digits"),
        ("Sparky10", (), False, "trailing digits"),
        ("joe_the_man", (), False, "underscore handle"),
        ("_", (), False, "the _NO_NAME marker"),
        ("Canada", (), False, "country"),
        ("canada.", (), False, "country with dot"),
        ("USA", (), False, "code"),
        ("new  zealand", (), False, "multi-word place, spaces collapsed"),
        ("Spender", (), False, "spend tier"),
        ("Chad", (), True, "Chad keeps his name"),
        ("Jordan", ("Jordan", ""), False, "his own country"),
        ("Austin", (), True, "city-name with no home"),
        ("Austin", ("USA", "Austin"), False, "his own city"),
        ("millbrook ", ("", "Millbrook"), False, "own city, case/space insensitive"),
        ("Millbrook", (None, "Springfield"), True, "someone else's city"),
        ("garrett baydala", (), True, "lowercase display name"),
        ("Mr.T", (), True, "punctuation ok"),
        ("alexnielsen", (), True, "PIN: lowercase handle without digits passes"),
    ]
    for s, here, exp, label in rows:
        got = is_greetable_name(s, here=here)
        assert got is exp, f"is_greetable_name[{label}]: got {got!r}, expected {exp!r}"


def case_name_token():
    rows = [
        # (s, last, expected, label)
        (None, False, "", "None"),
        ("", False, "", "empty"),
        ("   ", False, "", "whitespace"),
        ("John/Orange City,USA/Horny-Fan", False, "John", "structured first slot"),
        ("Sexy Sofie", True, "Sofie", "last word"),
        ("Sexy Sofie", False, "Sexy", "first word"),
        ("Mike/Free", False, "Mike", "tier slot ignored"),
        ("Free/Mike", False, "", "tier in name slot"),
        ("Spender", True, "", "tier only"),
        ("Canada/Canada/office job", False, "", "country in name slot"),
        ("New Zealand", True, "", "multi-word place, last word"),
        ("New Zealand", False, "", "multi-word place, whole segment"),
        ("Whistler,Canada/Whale", False, "", "City,Country slot"),
        ("USA/Free", False, "", "shouted code"),
        ("JOHN", False, "", "PIN: shouted <=4 rejected even if a name"),
        ("JOHNNY", False, "JOHNNY", "PIN: shouted >4 kept verbatim"),
        ("u1234567", False, "", "lowercase handle"),
        ("xx_gamer_99", False, "", "underscore handle"),
        ("_/Canada/office job", False, "", "_NO_NAME marker"),
        ("Mike123", False, "Mike", "PIN: digits stripped, handle becomes a name"),
        ("Fanlover577", False, "Fanlover", "PIN: digits stripped, handle becomes a name"),
        ("😀 Mike", False, "", "PIN: leading emoji word kills the name"),
        ("😀 Mike", True, "Mike", "emoji then name, last"),
        ("Mike😀", False, "Mike", "trailing emoji stripped"),
        ("Alex&amp;Sam", False, "Alex", "html-escaped couple"),
        ("Sunny Shine &lt;33", False, "Sunny", "html-escaped heart"),
        ("/Christopher/", False, "Christopher", "leading slash"),
        ("J", False, "", "single letter"),
        ("Jo", False, "Jo", "two letters"),
        ("José", False, "José", "accent kept"),
        ("John-Paul", False, "JohnPaul", "PIN: hyphen dropped, names glued"),
        ("O'Brien", False, "OBrien", "PIN: apostrophe dropped"),
        ("Kevin(on the other account)", False, "Kevin", "bracket note"),
        ("Ed; New Jersey", False, "Ed", "semicolon note"),
        ("Ed; New Jersey", True, "Jersey", "PIN: last=True on a note picks a place tail"),
        ("Chad", False, "Chad", "Chad"),
    ]
    for s, last, exp, label in rows:
        got = name_token(s, last=last)
        assert got == exp, f"name_token[{label} last={last}]: got {got!r}, expected {exp!r}"


def case_resolve_fan_name():
    rows = [
        (None, "", "None fan"),
        ({}, "", "empty dict"),
        ({"real_name": "  Alex  "}, "Alex", "real_name trimmed"),
        ({"real_name": "john"}, "john", "PIN: real_name verbatim, lowercase ok"),
        ({"real_name": "   ", "custom_nickname": "Dave"}, "Dave", "blank real_name falls through"),
        ({"real_name": "Canada", "custom_nickname": "John/Orange City,USA/X"}, "John",
         "place real_name skipped"),
        ({"real_name": "Alex&amp;Sam"}, "Alex&Sam", "PIN: real_name unescaped, kept whole"),
        ({"custom_nickname": "John Miller", "of_display_name": "surferdude"}, "John",
         "curated first word beats display"),
        ({"custom_nickname": "DaddyWilko/Free"}, "DaddyWilko", "tier suffix"),
        ({"custom_nickname": "Spender", "of_display_name": "garrett baydala"}, "garrett baydala",
         "tier-only curated falls to display"),
        ({"custom_nickname": "Sparky10"}, "Sparky", "PIN: curated handle stripped to a name"),
        ({"of_display_name": "Sparky10"}, "", "display handle rejected"),
        ({"generated_nickname": "Sexy Sofie"}, "Sofie", "AI label last word"),
        ({"generated_nickname": "Garrett/Delta,Canada/30/Spender"}, "Garrett", "AI structured"),
        ({"generated_nickname": "Kentucky,USA/Musician"}, "", "location label"),
        ({"generated_nickname": "USA/Free", "of_display_name": "Foxy's Hubby Jeremiah"},
         "Foxy's Hubby Jeremiah", "display beats country label"),
        ({"of_display_name": "u1234567", "of_username": "alexnielsen"}, "", "handles only"),
        ({"of_username": "Alex"}, "", "of_username never used"),
        ({"of_display_name": "😈 Daddy 😈"}, "😈 Daddy 😈", "PIN: display greeted verbatim w/ emoji"),
        ({"of_display_name": "😈😈"}, "", "emoji-only display"),
        ({"of_display_name": "Alex&amp;Sam"}, "Alex&Sam", "display unescaped"),
        ({"real_name": "Austin", "custom_nickname": "Austin", "generated_nickname": "Austin",
          "of_display_name": "Austin", "home_city": "Austin"}, "", "his city everywhere"),
        ({"custom_nickname": "Jordan/Amman", "of_display_name": "jj",
          "home_country": "Jordan"}, "jj", "his country skipped, chain continues"),
        ({"custom_nickname": "_/Canada/office job", "of_display_name": "Marcus"}, "Marcus",
         "_NO_NAME marker skipped"),
    ]
    for fan, exp, label in rows:
        got = resolve_fan_name(fan)
        assert got == exp, f"resolve_fan_name[{label}]: got {got!r}, expected {exp!r}"
    orm = Fan(account_id="a", fan_id=1, custom_nickname="Dave/Leeds", of_display_name="x_1")
    got = resolve_fan_name(orm)
    assert got == "Dave", f"resolve_fan_name[ORM row]: got {got!r}, expected 'Dave'"


def _fan(**kw):
    return Fan(account_id="a", fan_id=1, **kw)


def case_build_structured_nickname():
    long_job = "x" * 100
    rows = [
        ({}, "", "nothing known"),
        ({"real_name": "  ", "home_city": " ", "his_age": ""}, "", "whitespace only"),
        ({"real_name": "Mike"}, "Mike", "name only"),
        ({"real_name": "Mike", "home_city": "Austin", "home_country": "USA", "his_age": "30",
          "occupation": "chef"}, "Mike/Austin,USA/30/chef", "full"),
        ({"home_country": "Canada", "occupation": "office job"}, "_/Canada/office job",
         "no name -> _ marker"),
        ({"real_name": "Canada", "home_country": "Canada"}, "_/Canada", "place name rejected"),
        ({"real_name": "Austin", "home_city": "Austin"}, "_/Austin", "own city rejected"),
        ({"custom_nickname": "Donovon/chef/25", "his_age": "25", "occupation": "chef"},
         "Donovon/25/chef", "curated re-fed: only name slot reused"),
        ({"custom_nickname": "DaddyWilko/Free"}, "DaddyWilko", "tier dropped"),
        ({"of_display_name": "Fanlover577", "his_age": "30"}, "_/30", "display handle rejected"),
        ({"custom_nickname": "Fanlover577"}, "Fanlover", "PIN: curated handle stripped to name"),
        ({"of_display_name": "garrett baydala"}, "garrett baydala", "display verbatim"),
        ({"of_display_name": "😈", "his_age": "30"}, "_/30", "emoji display rejected"),
        ({"generated_nickname": "Sofie"}, "", "PIN: generated_nickname not consulted"),
        ({"real_name": "Mike", "occupation": long_job}, ("Mike/" + long_job)[:70], "70 cap"),
        ({"home_city": "Leeds"}, "_/Leeds", "city only"),
        ({"real_name": "Bob", "custom_nickname": "Dave"}, "Bob", "real_name beats curated"),
    ]
    for kw, exp, label in rows:
        got = build_structured_nickname(_fan(**kw))
        assert got == exp, f"build_structured_nickname[{label}]: got {got!r}, expected {exp!r}"
        assert len(got) <= 70, f"build_structured_nickname[{label}]: len {len(got)} > 70"


_harness.run(
    case_strip_spend_tier,
    case_is_place_word,
    case_is_greetable_name,
    case_name_token,
    case_resolve_fan_name,
    case_build_structured_nickname,
)
