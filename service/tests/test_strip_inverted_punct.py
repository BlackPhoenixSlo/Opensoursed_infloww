from __future__ import annotations

import _harness  # MUST be first: binds temp DB
import inspect

from automations import _common, _language
from automations._common import apply_word_restriction, strip_inverted_punct

_harness.bootstrap()


def case_strip_inverted_punct_util():
    assert strip_inverted_punct("¿Y cuándo vas a grabar?") == "Y cuándo vas a grabar?"
    assert strip_inverted_punct("hola ¿como estas?") == "hola como estas?"
    assert strip_inverted_punct("hola ¿ como estas?") == "hola como estas?"
    assert strip_inverted_punct("¡hola bebé! ¿que tal?") == "hola bebé! que tal?"
    assert strip_inverted_punct("¿¿en serio??") == "en serio??"
    assert strip_inverted_punct("") == "" and strip_inverted_punct(None) == ""


def case_no_chars_is_byte_identical():
    for s in ("hey  babe ", " leading space", "y cuando vas a grabar?",
              "tabs\tand  doubles", "già perché"):
        assert strip_inverted_punct(s) == s, s


def case_common_apply_word_restriction_carries_strip():
    assert apply_word_restriction("¿Y cuándo vas a grabar?") == "Y cuándo vas a grabar?"
    assert apply_word_restriction("¡let's meet!") == "let's meeet!"
    assert apply_word_restriction("") == "" and apply_word_restriction(None) is None


def case_language_apply_word_restriction_carries_strip():
    assert _language.apply_word_restriction("¿te gusta, bebé?", "es") == "te gusta, bebé?"
    assert _language.apply_word_restriction("¡hola! ¿lista?", "es") == "hola! lista?"
    assert _language.apply_word_restriction("¿really? let's meet", "en") == "really? let's meeet"
    assert _language.apply_word_restriction("", "es") == ""
    assert _language.apply_word_restriction(None, "es") is None


def case_strip_wired_into_both_variants():
    assert "strip_inverted_punct" in inspect.getsource(_common.apply_word_restriction)
    assert "strip_inverted_punct" in inspect.getsource(_language.apply_word_restriction)


if __name__ == "__main__":
    _harness.run(
        case_strip_inverted_punct_util,
        case_no_chars_is_byte_identical,
        case_common_apply_word_restriction_carries_strip,
        case_language_apply_word_restriction_carries_strip,
        case_strip_wired_into_both_variants,
    )
