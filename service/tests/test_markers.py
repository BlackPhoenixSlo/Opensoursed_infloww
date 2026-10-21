#!/usr/bin/env python3
"""What a fan must never see in a draft — automations/_markers.py and its callers.

Two shapes, both usually wearing `*...*`. The PROTOCOL marker the model is told
to emit (`STICKER: <tag>`) and does not reliably place where the protocol
says; and the NARRATION it emits although told not to. Nearly every case
here is a body that really went out — the 07-27 marker audit and the 07-28
104-body star corpus — so each one pins a leak that must be stripped or ordinary
copy that must NOT be.
"""
import _harness  # noqa: F401  — MUST be first (binds the temp DB)

_harness.bootstrap()

from automations import cat_stickers as cs  # noqa: E402
from automations._markers import protocol_marker_re, strip_narration  # noqa: E402


def case_shared_shape():
    """What every protocol gets from the shared matcher, using a throwaway
    keyword so the assertions are about the SHAPE, not the sticker catalog."""
    re_ = protocol_marker_re(r"WIDGET[ \t]*:")
    # anchorless — a marker glued after real text is still a marker
    assert re_.sub("", "hey there WIDGET: blue").strip() == "hey there"
    # ...and the text ahead of it survives, which is the whole point
    assert re_.sub("", "line one\nWIDGET: blue\nline two").strip() == "line one\n\nline two"
    # markdown / roleplay dressing is eaten
    for raw in ("*WIDGET: blue*", "**widget: blue**", "_widget: blue_", "[WIDGET: blue]"):
        assert re_.sub("", raw).strip() == "", raw
    # a word merely ENDING in the keyword is not a marker
    assert re_.sub("", "unwidget: blue") == "unwidget: blue"
    # group 1 is the payload tail, left for the caller
    assert re_.search("WIDGET: blue").group(1) == " blue"


def case_sticker_marker_survives_the_shared_refactor():
    """Spot-check that moving the shape into _markers changed no sticker
    behaviour — the full set lives in test_cat_stickers.py."""
    assert cs.parse_marker("*sticker: flirty*") == ("", "flirty")
    assert cs.parse_marker(
        "so what's the best place u been to in ktown lately? STICKER: flirty"
    ) == ("so what's the best place u been to in ktown lately?", "flirty")
    real = "you design stickers that make people obey"     # real prod body
    assert cs.parse_marker(real) == (real, None)


def case_glued_marker_still_triggers():
    """Live 2026-08-30, your-host.example.com night one: the model glued its Italian prose
    straight onto the marker and the letter-lookbehind refused the camelCase
    seam — the fan read `robypartySTICKER: flirty` verbatim and no sticker went
    out. The seam (lowercase, then the keyword in caps) IS the marker; a prose
    word merely containing the keyword is all one case and stays untouched."""
    assert cs.parse_marker(
        "che dramma la soferenza ti sta bene in quel letto robypartySTICKER: flirty"
    ) == ("che dramma la soferenza ti sta bene in quel letto robyparty", "flirty")
    # all-lowercase glue is prose, not a marker — the old protection holds
    real = "he unstickers: every label off the jar lol"
    assert cs.parse_marker(real) == (real, None)


def case_narration_emote_only_body_sends_nothing():
    """The house rule (07-28): a stage direction is never sendable, and saying
    NOTHING beats narrating. Every one of these is a real outbound prod body —
    an emote and nothing else, so the whole draft goes and the caller falls
    through to the gif, or to no send at all."""
    for raw in ("*he sent a sticker?*",          # ai_upseller, 07-28
                "*mischievous grin*",            # ai_chatter, 07-26
                "*love*",                        # ai_chatter, 07-25
                "* se ríe por dentro *"):        # es lane, 07-24 (padded stars)
        assert strip_narration(raw) == "", raw


def case_narration_rides_after_a_real_line():
    """The shape that costs the most: a good line with an emote bolted on. Only
    the emote goes, and the punctuation it left behind goes with it."""
    assert strip_narration(
        "*stretch and yawn as i read that*, maybe i make you beg a little, "
        "make you earn it"                       # ai_chatter, 07-26
    ) == "maybe i make you beg a little, make you earn it"
    # One-word ACTION, deleted rather than unwrapped — "hey winks how r u" is
    # not a sentence a person types.
    assert strip_narration("hey *winks* how r u") == "hey how r u"


def case_a_cut_leaves_no_orphan_punctuation_anywhere():
    """A cut takes its own comma with it, so there is nothing left to tidy up.

    Two bugs lived in the tidy-afterwards version this replaced. It cleaned only
    the start of the whole string, so an emote opening line 2 sent a bubble that
    read `, u up?` — and a draft becomes one bubble per line downstream, so that
    went straight to a fan. Cleaning per line then fixed the line case and left
    the MID-line one: `so , what u doing later`, which the bubble splitter chops
    at the comma into a bubble that is just `so`.

    Neither shape is in the 104-body corpus, and neither could have been: every
    stored body was unwrapped from its `<p>` tags into one line. A green corpus
    was not coverage."""
    assert strip_narration("hey babe\n*giggles*, u up?") == "hey babe\nu up?"
    assert strip_narration("hi\n*stretch and yawn*, maybe later") == "hi\nmaybe later"
    assert strip_narration(
        "so *she leans in close*, what u doing later") == "so what u doing later"
    assert strip_narration("hey *yawns*, u up?") == "hey u up?"
    # ...and a line that only ever held emphasis keeps its own shape, separator
    # included — an unwrap puts back exactly what the cut would have eaten.
    assert strip_narration("one\ntwo *and* three") == "one\ntwo and three"


def case_the_price_of_keeping_the_rule_two_lines():
    """What this deliberately gets WRONG, so nobody has to rediscover it.

    A whole-body span is usually an emote, but `*maybe i am*` and `*go on*` are
    real replies the model wrapped in stray stars, and they go with the rest.
    Inline, a multi-word span is usually narration, but Spanish uses one for
    slang emphasis and that goes too. Three messages in the 104-body corpus —
    two months of every lane — against a house rule that already says silence
    beats narrating. A pronoun test bought them back once and cost a bug on real
    operator copy, so it is gone. (`_EMOTE_WORDS` is a different thing and stays:
    it decides one-word INLINE spans, which word count cannot.)"""
    assert strip_narration("*maybe i am*") == ""          # autoreply, 07-12
    assert strip_narration("*go on*") == ""               # ai_chatter, 07-02
    assert strip_narration("jajaja *de pelos*?") == "jajaja ?"  # es, 07-22


def case_narration_does_not_eat_emphasis():
    """Most asterisks in prod are EMPHASIS, not narration — deleting the span
    would mangle a good line into "confident thoughtful". The stars go, the word
    stays, and the space before her `?` stays too — that is deliberate house
    style, not a typo, so nothing in the strip is allowed to close it up."""
    assert strip_narration("confident *and* thoughtful ?") == "confident and thoughtful ?"
    assert strip_narration(
        "a gamign youtuber asking for *my* opinion?"
    ) == "a gamign youtuber asking for my opinion?"
    assert strip_narration("si me *dejas* convencerte 😏") == "si me dejas convencerte 😏"
    # A lone star is the *fix typo beat, not a span — never touched.
    assert strip_narration("*fix i meant tuesday") == "*fix i meant tuesday"
    # No span anywhere ⇒ the ORIGINAL comes back, stars and all. This funnel line
    # is operator-written and has gone out 20+ times; an earlier cut of the strip
    # collapsed it to `nude*` because it normalised the run before checking.
    funnel = "nude*** it's the first one I took on OF"
    assert strip_narration(funnel) == funnel
    plain = "u got me blushing over here n i barely woke up"   # real prod body
    assert strip_narration(plain) == plain


_harness.run(
    case_shared_shape,
    case_sticker_marker_survives_the_shared_refactor,
    case_glued_marker_still_triggers,
    case_narration_emote_only_body_sends_nothing,
    case_narration_rides_after_a_real_line,
    case_a_cut_leaves_no_orphan_punctuation_anywhere,
    case_the_price_of_keeping_the_rule_two_lines,
    case_narration_does_not_eat_emphasis,
)
