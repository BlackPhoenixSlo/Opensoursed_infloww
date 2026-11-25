from __future__ import annotations

import _harness
import os

from db.engine import get_session
from db.models import Account, AccountAiConfig
from automations._common import (
    detect_bot_accusation, BOT_ACCUSED_RE,
    load_style_flags, load_typo_flags, load_nonnative_flags, load_spacing_flags,
    STYLE_AUTOMATIONS, _STYLE_FORCE_OFF_ENV,
)

_harness.bootstrap()


def case_bot_accusation_positives():
    positives = [
        "u a bot or sumthing? lol",
        "Heyy are you real or a chatbot or ai",
        "Do you have a bot talking for you or something",
        "Are you real?",
        "is this really you? or a bot?",
        "which bot",
        "what bot do you use",
        "are you a bot",
        "is this a bot",
        "is this ai",
        "is this a chatbot",
        "real person or someone else",
        "who is this really",
        "am i talking to a bot",
        "u a bot",
        "chatbot",
        "are you ai",
        "is this a real person",
    ]
    for t in positives:
        assert detect_bot_accusation(t) is True, t
        assert BOT_ACCUSED_RE.search(t), t


def case_bot_accusation_negatives():
    negatives = [
        "this pic looks ai",
        "is that photo real",
        "that selfie looks ai generated",
        "are you really into me",
        "are you really into this",
        "keeping it real babe",
        "hey how are you doing tonight",
        "i really like you",
        "",
        None,
    ]
    for t in negatives:
        assert detect_bot_accusation(t) is False, t


def case_bot_accusation_hears_human():
    positives = [
        "are you human",
        "wait are you human?",
        "u human?",
        "you human",
        "ur a human?",
        "r u human",
        "is this a human",
        "are you a human being",
        "am i chatting with a human",
        "talking to a real human",
        "is a human typing this",
        "is there a human behind this account",
        "are you even human lol",
        "so ur not human then",
        "is this even a real human",
        "am i really talking to a human",
        "wait ur human right?",
        "human?",
    ]
    for t in positives:
        assert detect_bot_accusation(t) is True, t
        assert BOT_ACCUSED_RE.search(t), t


def case_human_sympathy_sense_is_not_an_accusation():
    negatives = [
        "ur only human",
        "youre only human babe",
        "we are all human",
        "i am human too",
        "you humans are wild",
        "thats so human of you",
        "being human is hard",
        "my humanity is gone lol",
        "human resources is a joke",
        "nah dont stress, that just makes you human",
        "and ya should be means ur human",
        "honestly that makes u human and i like that",
        "i was talking to a human at the bank all day and got nowhere",
        "my dog is more human than my boss",
    ]
    for t in negatives:
        assert detect_bot_accusation(t) is False, t


def case_bot_hard_term_beats_photo_guard():
    assert detect_bot_accusation("is that pic real or are you a bot") is True
    assert detect_bot_accusation("nice pic but which bot writes this") is True
    for t in ("i feel like a robot today", "both of us", "bottom line babe"):
        assert detect_bot_accusation(t) is False, t


async def _seed(aid: str, raw):
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, style_config_json=raw))


async def case_tristate_absent_key_defaults():
    await _seed("tri_empty", "{}")
    await _seed("tri_null", None)
    await _seed("tri_garbage", "{not json")
    for aid in ("tri_missing_row", "tri_empty", "tri_null", "tri_garbage"):
        for loader in (load_style_flags, load_typo_flags, load_nonnative_flags,
                       load_spacing_flags):
            flags = await loader(aid)
            for k in STYLE_AUTOMATIONS:
                assert flags[k] is (k == "autoreply"), (loader.__name__, aid, k, flags)


async def case_tristate_explicit_false_stays_off():
    await _seed("tri_off", '{"autoreply": false}')
    await _seed("tri_typo_off", '{"typos_autoreply": false}')
    await _seed("tri_nn_off", '{"nonnative_autoreply": false}')
    await _seed("tri_ofchat_on", '{"welcome_chatter_for_info": true}')

    assert (await load_style_flags("tri_off"))["autoreply"] is False
    assert (await load_typo_flags("tri_typo_off"))["autoreply"] is False
    assert (await load_nonnative_flags("tri_nn_off"))["autoreply"] is False
    on = await load_style_flags("tri_ofchat_on")
    assert on["welcome_chatter_for_info"] is True and on["autoreply"] is True, on


async def case_style_force_off_kills_everything():
    await _seed("tri_all_on", '{"autoreply": true, "typos_autoreply": true, '
                              '"nonnative_autoreply": true, "welcome_chatter_for_info": true}')
    os.environ[_STYLE_FORCE_OFF_ENV] = "1"
    try:
        for loader in (load_style_flags, load_typo_flags, load_nonnative_flags):
            flags = await loader("tri_all_on")
            assert flags == {k: False for k in STYLE_AUTOMATIONS}, (loader.__name__, flags)
            assert (await loader("tri_missing_row2")) == {k: False for k in STYLE_AUTOMATIONS}
    finally:
        os.environ.pop(_STYLE_FORCE_OFF_ENV, None)
    assert (await load_style_flags("tri_all_on"))["autoreply"] is True


if __name__ == "__main__":
    _harness.run(
        case_bot_accusation_positives,
        case_bot_accusation_negatives,
        case_bot_accusation_hears_human,
        case_human_sympathy_sense_is_not_an_accusation,
        case_bot_hard_term_beats_photo_guard,
        case_tristate_absent_key_defaults,
        case_tristate_explicit_false_stays_off,
        case_style_force_off_kills_everything,
    )
