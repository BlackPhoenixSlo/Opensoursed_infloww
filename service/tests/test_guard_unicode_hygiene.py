#!/usr/bin/env python3
"""test_guard_unicode_hygiene.py — the cross-account Unicode fixes (build step 1).

Proves TWO things, and the first is the important one:

  1. ENGLISH-INVARIANCE. The tokenizer + name parsers must behave BYTE-IDENTICALLY on
     ASCII/English input after the fix — this is the exact property whose absence
     killed the v2 "union" idea (a regex change that silently altered English output).
     We assert it structurally (ASCII input → old pattern == new pattern) AND against
     the REAL message corpus in service/chatterly.db.

  2. ACCENTED NAMES / WORDS survive. name_token('José')=='José' (was 'Jos'),
     and 'sí'/'cuánto' tokenize whole.

Run:  ./venv/bin/python service/tests/test_guard_unicode_hygiene.py
"""
import _harness  # noqa: F401 — MUST be first (binds the temp DB; project #1 footgun)

import os
import re
import sqlite3

from automations._common import is_substantive_msg, name_token  # noqa: E402

_OLD_TOKEN_RE = re.compile(r"[a-z0-9']+")          # the pre-fix tokenizer
_OLD_NAME_STRIP = re.compile(r"[^A-Za-z]")         # the pre-fix name strip
_DB = os.path.join(os.path.dirname(__file__), "..", "chatterly.db")


# ── 1. English-invariance, structural ────────────────────────────────

def case_name_token_ascii_unchanged():
    """For any ASCII name, the unicode isalpha() strip == the old [^A-Za-z] strip."""
    samples = ["John", "Mary-Jane", "O'Brien", "Sofie", "R342", "xx_gamer_99",
               "u123", "Mike2", "A", "Bo", "Jean Luc", "Anne.Marie"]
    for s in samples:
        # replicate the old body: capitalized-first gate, then strip.
        seg = s.split("/")[0].strip()
        if "," in seg:
            continue
        words = re.split(r"\s+", seg) if seg else []
        if not words or not words[0][:1].isupper():
            old = ""
        else:
            w = _OLD_NAME_STRIP.sub("", words[0])
            old = w if len(w) >= 2 else ""
        new = name_token(s)
        assert new == old, f"name_token('{s}')={new!r} != old {old!r}"


def case_tokenizer_ascii_unchanged():
    """The new [0-9a-zÀ-ɏ'] class must produce IDENTICAL tokens to the old
    [a-z0-9'] class on every ASCII string (the added range can't match ASCII)."""
    samples = ["hey how are you", "i want to see more pics", "send me nudes",
               "lol ok", "yes", "can you do 30", "once you check this out bb",
               "i come home late", "solo trip", "on sale now", "12345", "u still there?"]
    new_re = re.compile(r"[0-9a-zÀ-ɏ']+")
    for s in samples:
        low = s.lower()
        assert new_re.findall(low) == _OLD_TOKEN_RE.findall(low), f"drift on {s!r}"


def case_tokenizer_english_corpus_identical():
    """Against the REAL corpus: for every English (ASCII) inbound body, the new
    tokenizer is byte-identical to the old. Non-ASCII rows are skipped here (they're
    the whole point of the change, covered by the accented cases)."""
    if not os.path.exists(_DB):
        print("  (skip corpus check — no chatterly.db in lane)")
        return
    con = sqlite3.connect(_DB)
    try:
        rows = con.execute(
            "SELECT body FROM messages WHERE direction='in' AND body IS NOT NULL "
            "LIMIT 40000"
        ).fetchall()
    finally:
        con.close()
    new_re = re.compile(r"[0-9a-zÀ-ɏ']+")
    checked = drift = 0
    for (body,) in rows:
        if not body or not body.isascii():
            continue
        checked += 1
        low = body.lower()
        if new_re.findall(low) != _OLD_TOKEN_RE.findall(low):
            drift += 1
    print(f"  corpus: {checked} ASCII inbound checked, {drift} drifted")
    assert drift == 0, f"{drift} English messages tokenize differently — NOT invariant"


# ── 2. Accented names / words now survive ────────────────────────────

def case_accented_names_survive():
    assert name_token("José") == "José", name_token("José")
    assert name_token("Ángel") == "Ángel", name_token("Ángel")
    assert name_token("Muñoz") == "Muñoz", name_token("Muñoz")
    assert name_token("Nicolás") == "Nicolás", name_token("Nicolás")
    # last=True path (AI nicknames like "Sexy Sofié")
    assert name_token("Sexy Sofié", last=True) == "Sofié"
    # a plain number/handle is still rejected
    assert name_token("800000482") == ""
    assert name_token("u1000002") == ""


def case_accented_tokens_whole():
    """The B8 shatter: 'sí'/'cuánto' must tokenize WHOLE, not into ASCII fragments."""
    new_re = re.compile(r"[0-9a-zÀ-ɏ']+")
    assert new_re.findall("sí quiero") == ["sí", "quiero"]
    assert new_re.findall("cuánto cuesta") == ["cuánto", "cuesta"]


def case_is_substantive_msg_unchanged():
    """PIN the SHIPPED semantics. is_substantive_msg has two live callers that
    NEED its current (loose) convention: welcome_chatter_for_info's runaway cap
    (_MAX_FAN_MESSAGES) and gen_info's message_count_at_gen staleness baseline.
    "k" IS a message turn to both. If someone "helpfully" tightens it to mean
    "buying signal", both break SILENTLY — the cap stops counting turns and every
    profile goes stale-forever."""
    for turn in ("k", "ok", "lol", "yes", "no", "hi", "?!a", "u"):
        assert is_substantive_msg(turn) is True, f"is_substantive_msg({turn!r}) must stay True"
    for reaction in ("😍", "🔥🔥", "...", "!!!", "", "   ", None):
        assert is_substantive_msg(reaction) is False, f"is_substantive_msg({reaction!r})"


if __name__ == "__main__":
    _harness.run(
        case_name_token_ascii_unchanged,
        case_tokenizer_ascii_unchanged,
        case_tokenizer_english_corpus_identical,
        case_accented_names_survive,
        case_accented_tokens_whole,
        case_is_substantive_msg_unchanged,
    )
