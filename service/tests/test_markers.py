#!/usr/bin/env python3
import _harness  # noqa: F401  — MUST be first (binds the temp DB)

_harness.bootstrap()

from automations import cat_stickers as cs  # noqa: E402
from automations._markers import protocol_marker_re, strip_asides, strip_narration  # noqa: E402


def case_shared_shape():
    re_ = protocol_marker_re(r"WIDGET[ \t]*:")
    assert re_.sub("", "hey there WIDGET: blue").strip() == "hey there"
    assert re_.sub("", "line one\nWIDGET: blue\nline two").strip() == "line one\n\nline two"
    for raw in ("*WIDGET: blue*", "**widget: blue**", "_widget: blue_", "[WIDGET: blue]"):
        assert re_.sub("", raw).strip() == "", raw
    assert re_.sub("", "unwidget: blue") == "unwidget: blue"
    assert re_.search("WIDGET: blue").group(1) == " blue"


def case_sticker_marker_survives_the_shared_refactor():
    assert cs.parse_marker("*sticker: flirty*") == ("", "flirty")
    assert cs.parse_marker(
        "so what's the best place u been to in ktown lately? STICKER: flirty"
    ) == ("so what's the best place u been to in ktown lately?", "flirty")
    real = "you design stickers that make people obey"
    assert cs.parse_marker(real) == (real, None)


def case_glued_marker_still_triggers():
    assert cs.parse_marker(
        "che dramma la soferenza ti sta bene in quel letto robypartySTICKER: flirty"
    ) == ("che dramma la soferenza ti sta bene in quel letto robyparty", "flirty")
    real = "he unstickers: every label off the jar lol"
    assert cs.parse_marker(real) == (real, None)


def case_narration_emote_only_body_sends_nothing():
    for raw in ("*he sent a sticker?*",
                "*mischievous grin*",
                "*love*",
                "* se ríe por dentro *"):
        assert strip_narration(raw) == "", raw


def case_narration_rides_after_a_real_line():
    assert strip_narration(
        "*stretch and yawn as i read that*, maybe i make you beg a little, "
        "make you earn it"
    ) == "maybe i make you beg a little, make you earn it"
    assert strip_narration("hey *winks* how r u") == "hey how r u"


def case_a_cut_leaves_no_orphan_punctuation_anywhere():
    assert strip_narration("hey babe\n*giggles*, u up?") == "hey babe\nu up?"
    assert strip_narration("hi\n*stretch and yawn*, maybe later") == "hi\nmaybe later"
    assert strip_narration(
        "so *she leans in close*, what u doing later") == "so what u doing later"
    assert strip_narration("hey *yawns*, u up?") == "hey u up?"
    assert strip_narration("one\ntwo *and* three") == "one\ntwo and three"


def case_the_price_of_keeping_the_rule_two_lines():
    assert strip_narration("*maybe i am*") == ""
    assert strip_narration("*go on*") == ""
    assert strip_narration("jajaja *de pelos*?") == "jajaja ?"


def case_narration_does_not_eat_emphasis():
    # the space before `?` is deliberate house style; the strip must not close it up
    assert strip_narration("confident *and* thoughtful ?") == "confident and thoughtful ?"
    assert strip_narration(
        "a gamign youtuber asking for *my* opinion?"
    ) == "a gamign youtuber asking for my opinion?"
    assert strip_narration("si me *dejas* convencerte 😏") == "si me dejas convencerte 😏"
    assert strip_narration("*fix i meant tuesday") == "*fix i meant tuesday"
    funnel = "nude*** it's the first one I took on OF"
    assert strip_narration(funnel) == funnel
    plain = "u got me blushing over here n i barely woke up"
    assert strip_narration(plain) == plain


def case_bracket_aside_never_reaches_the_fan():
    assert strip_asides(
        "hey sweetie\n(Can't have a longer response here as per your instructions "
        "so I'll keep it to one line with no emoji as requested.)") == "hey sweetie"
    assert strip_asides("hey sweetie (keeping it short as requested) u up?") == "hey sweetie u up?"
    assert strip_asides("(Note: one line, no emoji.)") == ""
    assert strip_asides("(a) hi\n(b) there") == "hi\nthere"
    for keep in ("miss u :( come back :)", "(: hey u :)", "aww :( ok (;", "hi\nthere",
                 "u got me blushing over here n i barely woke up", "lol =) ok :-)"):
        assert strip_asides(keep) == keep, keep
    caption = "B nothing much rn 🙈\n\nbut i made u something.. open it?"
    assert strip_asides(caption) == caption
    assert strip_asides(f"  {caption}\n") == caption
    assert strip_asides("hey\n\n(Note: kept short.)\n\nopen it?") == "hey\n\nopen it?"
    assert strip_asides("hey (short)\n\nopen it?") == "hey\n\nopen it?"


_harness.run(
    case_bracket_aside_never_reaches_the_fan,
    case_shared_shape,
    case_sticker_marker_survives_the_shared_refactor,
    case_glued_marker_still_triggers,
    case_narration_emote_only_body_sends_nothing,
    case_narration_rides_after_a_real_line,
    case_a_cut_leaves_no_orphan_punctuation_anywhere,
    case_the_price_of_keeping_the_rule_two_lines,
    case_narration_does_not_eat_emphasis,
)
