#!/usr/bin/env python3
"""The send chain for a plan's mass/post text (service/send_chain.py; ultra ticket 13;
docs/prompts/post-processing.md "Mass/post text from a plan").

Cases:
  case_refusals         — table: empty / whitespace, a *stage direction*, off-platform (channel, phone, meetup),
                          an Agency sensitive word → refused with that stage; nothing is rewritten into a deflection.
  case_transforms       — OF-restricted words get the doubled vowel; the emoji strip runs only when the flag is
                          on; clean text passes byte-for-byte (trimmed).
  case_banned_after_transform — a sensitive word is caught on the raw text even though the transform changes it.
  case_scans_final_and_visible — the scans read the final text and its fan-visible form (of_plain): "tele📱gram" with
                          the emoji strip, "tele<b>gram</b>", "<b></b>", "<b>*smiles*</b>" and a sensitive word split
                          by markup are all refused; bold prose passes with its markup kept.
  case_run_loads_agency — run(): the Creator's Agency's Sensitive words and her strip_emojis flag come from the DB;
                          another Agency's words never apply.

Run: ./venv/bin/python service/tests/test_send_chain.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import json  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import send_chain  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountAiConfig, SensitiveWord  # noqa: E402

IDS = fx.seed_two_agencies()
CA, CB = IDS["creator_a"], IDS["creator_b"]


def case_refusals() -> None:
    table = [
        ("", [], "empty"),
        ("   \n ", [], "empty"),
        ("*smiles* new set tonight", [], "narration"),
        ("new set tonight *wink*", [], "narration"),
        ("add me on telegram babe", [], "offplatform"),
        ("text me 555 123 4567", [], "offplatform"),
        ("lets meet up later", [], "offplatform"),
        ("brand new set tonight", ["set"], "banned_words"),
        ("😘", [], "empty"),  # with the emoji strip on (below), nothing is left
    ]
    for raw, words, stage in table:
        v = send_chain.chain(raw, words, strip_emoji=raw == "😘")
        assert v.text is None and v.stage == stage and v.detail, (raw, v)


def case_transforms() -> None:
    v = send_chain.chain("  my new video tonight  ", [], False)
    assert v.text == "my new video tonight" and not v.stage, v
    v = send_chain.chain("drink with me tonight", [], False)
    assert v.text == "driink with me tonight", v  # apply_word_restriction
    assert send_chain.chain("hi babe 😘", [], True).text == "hi babe"
    assert send_chain.chain("hi babe 😘", [], False).text == "hi babe 😘"


def case_banned_after_transform() -> None:
    v = send_chain.chain("one drink tonight", ["drink"], False)  # final text reads "driink"
    assert v.text is None and v.stage == "banned_words", v


def case_scans_final_and_visible() -> None:
    table = [
        ("add me on tele📱gram", [], True, "offplatform"),   # the emoji strip joins the word
        ("tele📱gram", [], True, "offplatform"),
        ("tele<b>gram</b>", [], False, "offplatform"),       # the fan reads "telegram"
        ("my snap<i>chat</i> is ava", [], False, "offplatform"),
        ("<b></b>", [], False, "empty"),                     # the fan reads nothing
        ("<b> </b>😘", [], True, "empty"),
        ("<b>*smiles*</b> new set", [], False, "narration"),
        ("big pro<b>mo</b> tonight", ["promo"], False, "banned_words"),
    ]
    for raw, words, strip, stage in table:
        v = send_chain.chain(raw, words, strip)
        assert v.text is None and v.stage == stage, (raw, v)
    assert send_chain.chain("new <b>set</b> tonight", [], False).text == "new <b>set</b> tonight"


async def case_run_loads_agency() -> None:
    async with get_session() as s:
        s.add(SensitiveWord(agency_user_id=IDS["agency_a_owner"], word="Promo", word_key="promo"))
        s.add(SensitiveWord(agency_user_id=IDS["agency_b_owner"], word="tonight", word_key="tonight"))
        s.add(AccountAiConfig(account_id=CA, style_config_json=json.dumps({"strip_emojis": True})))
    v = await send_chain.run("big promo tonight", CA)
    assert v.text is None and v.stage == "banned_words" and "promo" in v.detail.lower(), v
    assert (await send_chain.run("new video tonight 😘", CA)).text == "new video tonight"  # B's word: not A's
    v = await send_chain.run("new video tonight 😘", CB)
    assert v.text is None and v.stage == "banned_words", v
    assert (await send_chain.run("big promo 😘", CB)).text == "big promo 😘"  # B: no emoji flag, no "promo"


if __name__ == "__main__":
    _harness.run()
