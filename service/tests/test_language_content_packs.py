#!/usr/bin/env python3
"""test_language_content_packs.py — the buy-signal detectors in `_language` work
in es / sl without leaking across languages.

Run:  ./venv/bin/python service/tests/test_language_content_packs.py
"""
import _harness  # noqa: F401 — MUST be first
_harness.bootstrap()

from automations import _language as L  # noqa: E402


def case_closer_detectors_bilingual():
    # the closer's buy-signals now recognize Spanish (via the _language dispatchers)
    assert L.is_content_ask("mándame fotos", "es"), "es content-ask"
    assert L.is_escalation("estoy caliente", "es"), "es escalation"
    assert L.is_content_ask("send me pics", "en"), "en unchanged"
    # gate design: a Spanish ask must NOT trip the English detector
    assert not L.is_content_ask("mándame fotos", "en"), "no cross-language leak"


def case_slovenian_detectors():
    assert L.is_content_ask("pošlji mi slike", "sl"), "sl content-ask (send me pics)"
    assert L.is_content_ask("koliko stane", "sl"), "sl price ask"
    assert L.is_content_ask("hočem te videt golo", "sl"), "sl want-to-see"
    assert L.is_escalation("vroč sem", "sl"), "sl escalation (he: I'm hot, masc)"
    assert L.is_escalation("horni sem", "sl"), "sl escalation (English code-switch: horny)"
    assert L.is_escalation("hard sem", "sl"), "sl escalation (English: hard)"
    assert L.is_escalation("tako si vroča", "sl"), "sl escalation (he calls her hot, fem)"
    assert L.is_escalation("so wet", "sl"), "sl escalation (English: so wet)"
    assert L.is_content_ask("send me pics", "sl"), "sl content-ask (English code-switch)"
    assert L.is_escalation("hočem te pofukat", "sl"), "sl escalation (explicit)"
    # es detectors unchanged after the per-lang-map refactor (regression guard)
    assert L.is_content_ask("mándame fotos", "es") and not L.is_content_ask("mándame fotos", "en")
    assert L.is_escalation("estoy caliente", "es")
    # thread_heat is now bilingual for sl too
    assert L.thread_heat([("in", "živjo"), ("in", "pošlji mi slike")], "sl")
    assert not L.thread_heat([("in", "hello there")], "sl")


if __name__ == "__main__":
    _harness.run(
        case_closer_detectors_bilingual,
        case_slovenian_detectors,
    )
