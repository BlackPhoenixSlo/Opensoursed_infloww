#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

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
        ("😘", [], "empty"),
    ]
    for raw, words, stage in table:
        v = send_chain.chain(raw, words, strip_emoji=raw == "😘")
        assert v.text is None and v.stage == stage and v.detail, (raw, v)


def case_transforms() -> None:
    v = send_chain.chain("  my new video tonight  ", [], False)
    assert v.text == "my new video tonight" and not v.stage, v
    v = send_chain.chain("drink with me tonight", [], False)
    assert v.text == "driink with me tonight", v
    assert send_chain.chain("hi babe 😘", [], True).text == "hi babe"
    assert send_chain.chain("hi babe 😘", [], False).text == "hi babe 😘"


def case_banned_after_transform() -> None:
    v = send_chain.chain("one drink tonight", ["drink"], False)
    assert v.text is None and v.stage == "banned_words", v


def case_scans_final_and_visible() -> None:
    table = [
        ("add me on tele📱gram", [], True, "offplatform"),
        ("tele📱gram", [], True, "offplatform"),
        ("tele<b>gram</b>", [], False, "offplatform"),
        ("my snap<i>chat</i> is ava", [], False, "offplatform"),
        ("<b></b>", [], False, "empty"),
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
    assert (await send_chain.run("new video tonight 😘", CA)).text == "new video tonight"
    v = await send_chain.run("new video tonight 😘", CB)
    assert v.text is None and v.stage == "banned_words", v
    assert (await send_chain.run("big promo 😘", CB)).text == "big promo 😘"


if __name__ == "__main__":
    _harness.run()
