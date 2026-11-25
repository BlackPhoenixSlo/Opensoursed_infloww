#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first

import os  # noqa: E402
import re  # noqa: E402
import sqlite3  # noqa: E402

from automations import _language as L  # noqa: E402
from automations import _common  # noqa: E402

_DB = os.path.join(os.path.dirname(__file__), "..", "chatterly.db")



def case_spanish_fires():
    assert L.is_content_ask("mándame fotos", "es")
    assert L.is_content_ask("cuánto cuesta esa foto?", "es")
    assert L.is_content_ask("quiero verte desnuda", "es")
    assert L.is_escalation("estoy muy caliente", "es")
    assert L.is_escalation("quiero cogerte", "es")
    assert L.detect_bot_accusation("eres un robot?", "es")
    assert L.detect_bot_accusation("esto es una IA", "es")
    assert L.thread_heat([("in", "hola"), ("in", "mándame algo rico")], "es")
    assert L.apply_word_restriction("eres menor?", "es") != "eres menor?"


def case_spanish_does_not_overfire():
    for benign in ["hola guapa como estas", "que tal tu dia", "buenos dias preciosa",
                   "me encanta hablar contigo", "eres muy linda"]:
        assert not L.is_content_ask(benign, "es"), benign
        assert not L.is_escalation(benign, "es"), benign



_EN_MARKERS = {"the", "you", "and", "that", "for", "have", "this", "what", "are",
               "was", "with", "your", "but", "not", "just", "would", "like", "get"}
_ES_MARKERS = {"que", "por", "para", "con", "los", "las", "una", "uno", "esto", "eres",
               "tengo", "quiero", "dinero", "gracias", "rica", "rico", "foto", "fotos",
               "mas", "más", "muy", "nada", "pero", "como", "estas", "está", "cojerte",
               "hola", "guapa", "amor", "nena", "cuánto", "cuanto", "desnuda"}


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "")


def _is_high_conf_english(body: str) -> bool:
    if not body or not body.isascii():
        return False
    words = set(re.findall(r"[a-z']+", _strip_tags(body).lower()))
    return len(words & _EN_MARKERS) >= 2 and not (words & _ES_MARKERS)


def case_zero_english_false_positives():
    if not os.path.exists(_DB):
        print("  (skip — no chatterly.db in lane)")
        return
    con = sqlite3.connect(_DB)
    try:
        inbound = [r[0] for r in con.execute(
            "SELECT body FROM messages WHERE direction='in' AND body IS NOT NULL "
            "AND body != '' LIMIT 60000").fetchall()]
        outbound = [r[0] for r in con.execute(
            "SELECT body FROM messages WHERE direction='out' AND body IS NOT NULL "
            "AND body != '' LIMIT 60000").fetchall()]
    finally:
        con.close()

    inbound_en = [b for b in inbound if _is_high_conf_english(b)]
    outbound_en = [b for b in outbound if b and b.isascii()]

    harmful = {"escalation": 0, "bot": 0, "restricted_outbound": 0}
    content_ask_fires = []
    for b in inbound_en:
        if L.is_escalation(b, "es"): harmful["escalation"] += 1
        if L.detect_bot_accusation(b, "es"): harmful["bot"] += 1
        if L.is_content_ask(b, "es"): content_ask_fires.append(b)
    for b in outbound_en:
        if L.apply_word_restriction(b, "es") != b:
            harmful["restricted_outbound"] += 1

    print(f"  high-conf English inbound={len(inbound_en)} ascii outbound={len(outbound_en)}")
    print(f"  harmful es-guard fires: {harmful}")
    print(f"  content_ask fires on English (loanword, benign)={len(content_ask_fires)}")
    for b in content_ask_fires[:200]:
        low = _strip_tags(b).lower()
        assert "nude" in low or "pic" in low or "vid" in low or "see" in low, \
            f"content_ask on non-ask English: {b!r}"
    assert sum(harmful.values()) == 0, f"es guards harmed English: {harmful}"



def case_english_delegates_unchanged():
    for text in ["send me nudes", "i'm broke", "no thanks", "are you a bot?",
                 "what else you got", "can you do 30"]:
        assert L.is_content_ask(text, "en") == _common.is_content_ask(text)
        assert L.is_escalation(text, "en") == _common.is_escalation(text)
    for w in ["once you check this out", "come see my set", "solo content", "on sale now"]:
        assert L.apply_word_restriction(w, "en") == _common.apply_word_restriction(w)



def case_resolve_and_directive():
    assert L.resolve_language("es") == "es"
    assert L.resolve_language(None) == "en"
    assert L.resolve_language("en", "es") == "es"
    assert L.resolve_language("es", None) == "es"
    assert L.resolve_language("klingon") == "en"
    assert L.output_language_directive("en") == ""
    d = L.output_language_directive("es")
    assert "Español" in d and "STICKER:" in d
    assert d.startswith("\n\n"), "appended at prompt end, prefix untouched"


if __name__ == "__main__":
    _harness.run(
        case_spanish_fires,
        case_spanish_does_not_overfire,
        case_zero_english_false_positives,
        case_english_delegates_unchanged,
        case_resolve_and_directive,
    )
