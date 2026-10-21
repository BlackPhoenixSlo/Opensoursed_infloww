"""Tests for the §6.4 / §3.7 realism detectors + the TRI-STATE style-flag default.

Covers two seams added to automations/_common.py:
  • detect_bot_accusation — fires on the 74-corpus "are you a bot / real / ai" tells,
    but NOT on AI-generated-PHOTO complaints ('this pic looks ai') nor the RELATIONSHIP
    sense ('are you really into me').
  • the tri-state style default — an EXPLICIT stored value wins; an ABSENT key
    resolves to the per-automation default (ON for autoreply, OFF for the rest);
    STYLE_FORCE_OFF kills every flag regardless.

Run: ./venv/bin/python service/tests/test_realism_detectors.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
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
    """Every required identity accusation fires — the real-corpus samples and the
    spec's explicit MUST-fire set."""
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
        # the exposed union regex also matches (photo guard aside)
        assert BOT_ACCUSED_RE.search(t), t


def case_bot_accusation_negatives():
    """AI-PHOTO complaints and the relationship-'real' sense must NOT fire, and
    ordinary chat is quiet."""
    negatives = [
        "this pic looks ai",            # complaining about the CONTENT, not her
        "is that photo real",           # same — photo, not identity
        "that selfie looks ai generated",
        "are you really into me",       # relationship-real, not identity-real
        "are you really into this",
        "keeping it real babe",         # bare 'real', no identity frame
        "hey how are you doing tonight",
        "i really like you",
        "",
        None,
    ]
    for t in negatives:
        assert detect_bot_accusation(t) is False, t


def case_bot_accusation_hears_human():
    """'human' is the other half of how a fan asks this, and the detector was deaf to
    all of it. Prod thread 800000630 ran 'wait are you human?' through as ordinary
    chat — no brush-off, no one-line cap, bot_accusations 0 — and a $3 paywall went
    out on the answer."""
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
        # the sharpest forms — an intensifier or a negation between the pair, which an
        # adjacency-only rule silently dropped
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
    """'you're only human' is comfort, not a challenge.

    ⚠️ ADJACENCY IS NOT THE TEST, and the first version of this claimed it was: the
    sympathy sense puts the pronoun right next to the word as often as the accusation
    does — "that just makes you human", "means ur human" — so a bare pronoun+human rule
    fires on reassurance and answers a kind fan with a brush-off and a seller_off turn.
    What separates them is the FRAME (a question word or a negation) and the POSITION
    (the accusation OPENS the message; the comfort is buried inside one). 'humans' plural and 'humanity' are other
    words entirely and \\bhuman\\b must not reach into them."""
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
        # the pronoun IS adjacent in every one of these, and every one is kindness
        "nah dont stress, that just makes you human",
        "and ya should be means ur human",
        "honestly that makes u human and i like that",
        # his day, not a question about her
        "i was talking to a human at the bank all day and got nowhere",
        "my dog is more human than my boss",
    ]
    for t in negatives:
        assert detect_bot_accusation(t) is False, t


def case_bot_hard_term_beats_photo_guard():
    """'bot'/'chatbot' is an identity accusation even when a photo word rides in the
    same message — the photo guard only suppresses the SOFTER tells."""
    assert detect_bot_accusation("is that pic real or are you a bot") is True
    assert detect_bot_accusation("nice pic but which bot writes this") is True
    # 'robot' / 'both' / 'bottom' must not trip the \bbot\b matcher
    for t in ("i feel like a robot today", "both of us", "bottom line babe"):
        assert detect_bot_accusation(t) is False, t


async def _seed(aid: str, raw):
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, style_config_json=raw))


async def case_tristate_absent_key_defaults():
    """ABSENT key → autoreply ON, every other automation OFF — across all four
    loaders (humanizer / typos / non-native / spacing). The no-row and NULL/garbage
    paths resolve to the same per-automation defaults."""
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
    """An EXPLICIT stored value is honoured verbatim — False stays off, True turns
    on — and absent keys still follow the per-automation default."""
    await _seed("tri_off", '{"autoreply": false}')
    await _seed("tri_typo_off", '{"typos_autoreply": false}')
    await _seed("tri_nn_off", '{"nonnative_autoreply": false}')
    await _seed("tri_ofchat_on", '{"welcome_chatter_for_info": true}')

    assert (await load_style_flags("tri_off"))["autoreply"] is False
    assert (await load_typo_flags("tri_typo_off"))["autoreply"] is False
    assert (await load_nonnative_flags("tri_nn_off"))["autoreply"] is False
    # explicit True on a normally-OFF automation turns it on; autoreply absent → ON
    on = await load_style_flags("tri_ofchat_on")
    assert on["welcome_chatter_for_info"] is True and on["autoreply"] is True, on


async def case_style_force_off_kills_everything():
    """The STYLE_FORCE_OFF env panic switch forces every flag False regardless of
    stored config (including explicit Trues)."""
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
    # sanity: with the switch cleared, the stored Trues are back
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
