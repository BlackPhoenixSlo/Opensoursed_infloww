"""Tests for the unconditional inverted-¿/¡ strip (Spanish register floor).

Casual native texters drop the inverted openers and just close with ?/!, so a
model "¿Y cuándo...?" reads edited/proper — a bot tell in a DM. The model always
emits them and ignores a prompt not to, so (like emojis) they are removed IN
CODE. The strip rides inside apply_word_restriction — BOTH the _common English
variant and the _language lang-aware variant — because that is the one last-mile
pass every sender already runs, so every sender inherits it with no per-sender
wiring. Verifies: the util strips ¿/¡ anywhere (leading, mid-sentence, standing
alone) and tidies the space left behind; text WITHOUT the chars passes through
byte-identical (the en/sl no-op guarantee); both apply_word_restriction variants
carry the strip (es branch included — it does NOT delegate to _common's); and
banned-word softening still runs on the stripped text.

Run: ./venv/bin/python service/tests/test_strip_inverted_punct.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import inspect

from automations import _common, _language
from automations._common import apply_word_restriction, strip_inverted_punct

_harness.bootstrap()


def case_strip_inverted_punct_util():
    """Strips ¿/¡ wherever they sit, tidies the double space a standalone char
    leaves, and is empty/None-safe. The closing ?/! always survives."""
    assert strip_inverted_punct("¿Y cuándo vas a grabar?") == "Y cuándo vas a grabar?"
    assert strip_inverted_punct("hola ¿como estas?") == "hola como estas?"   # mid, attached
    assert strip_inverted_punct("hola ¿ como estas?") == "hola como estas?"  # mid, standalone
    assert strip_inverted_punct("¡hola bebé! ¿que tal?") == "hola bebé! que tal?"
    assert strip_inverted_punct("¿¿en serio??") == "en serio??"              # doubled opener
    assert strip_inverted_punct("") == "" and strip_inverted_punct(None) == ""


def case_no_chars_is_byte_identical():
    """Without ¿/¡ the input passes through UNTOUCHED — no trim, no whitespace
    collapse — so the en/sl lanes (and every existing test expectation on them)
    see a byte-for-byte no-op."""
    for s in ("hey  babe ", " leading space", "y cuando vas a grabar?",
              "tabs\tand  doubles", "già perché"):  # non-es accents untouched too
        assert strip_inverted_punct(s) == s, s


def case_common_apply_word_restriction_carries_strip():
    """The English-variant chokepoint strips the openers AND still softens
    restricted words on the stripped text."""
    assert apply_word_restriction("¿Y cuándo vas a grabar?") == "Y cuándo vas a grabar?"
    assert apply_word_restriction("¡let's meet!") == "let's meeet!"  # strip + soften
    assert apply_word_restriction("") == "" and apply_word_restriction(None) is None


def case_language_apply_word_restriction_carries_strip():
    """The lang-aware chokepoint strips on BOTH branches — es (its own banned
    list, no delegation to _common's filter) and en (delegates)."""
    assert _language.apply_word_restriction("¿te gusta, bebé?", "es") == "te gusta, bebé?"
    assert _language.apply_word_restriction("¡hola! ¿lista?", "es") == "hola! lista?"
    assert _language.apply_word_restriction("¿really? let's meet", "en") == "really? let's meeet"
    assert _language.apply_word_restriction("", "es") == ""
    assert _language.apply_word_restriction(None, "es") is None


def case_strip_wired_into_both_variants():
    """Both apply_word_restriction variants keep the strip_inverted_punct hook —
    it is the ONLY wiring (senders are not edited), so losing either silently
    reopens the ¿ tell on that branch."""
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
