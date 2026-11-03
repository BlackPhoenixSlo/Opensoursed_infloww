#!/usr/bin/env python3
"""
automations/_reply_shape.py — the sync shaping middle welcome_chatter_for_info and
autoreply share, as tables. The golden rows were captured from the two engines'
inline shaping in their `run` BEFORE it moved here (68646e684), over the same helpers:
one input, each engine's ctx → today's output.

  case_module_is_pure                  no async code; imports only its named helper
                                       modules; the echo predicate is read as this
                                       module's attribute at call time
  case_golden_wcfi_vs_autoreply        one row per stage (empty, echo, lead-reaction
                                       dupe, banned block / mask, bubble cap, char cap,
                                       word restriction, non-native, sticker) + the
                                       engine differences: the same raw reply through
                                       each engine's ctx → the output each produced
  case_echo_predicate_patchable        patching `_reply_shape._looks_like_echo` turns
                                       the echo drop off (the slop fault's seam)

Run: ./venv/bin/python service/tests/test_reply_shape.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

from automations import _reply_shape as rs  # noqa: E402

DM = "slop wcfi round 1 1/1"
HIST = [("in", "hey gorgeous"), ("out", "oof long day, better now"), ("in", DM)]
FAN = 4242
LONG = "so " + "really " * 120 + "long"


def _ctx(*, lang, echo_of, allow_empty, style_on=False, banned_words=(),
         banned_mode="block", nonnative_on=False, spacing_on=False) -> rs.ShapeCtx:
    """Every ShapeCtx field, spelled out (it has no defaults); the knobs default to the
    engines' off state."""
    return rs.ShapeCtx(seed_id=FAN, max_bubbles=3 if style_on else 2, max_chars=600,
                       lang=lang, echo_of=echo_of, style_on=style_on,
                       recent_out=[b for d, b in HIST if d == "out"], allow_empty=allow_empty,
                       banned_words=banned_words, banned_mode=banned_mode,
                       nonnative_on=nonnative_on, spacing_on=spacing_on, name_protect=["Jack"])


def _wcfi_ctx(lang="en", sticker=False, **k) -> rs.ShapeCtx:
    """wcfi's ctx (welcome_chatter_for_info._turn): his language, echo drop on his
    last line, a sticker tag lets an empty text through."""
    return _ctx(lang=lang, echo_of=DM, allow_empty=sticker, **k)


def _ar_ctx(**k) -> rs.ShapeCtx:
    """autoreply's ctx: language-blind restriction, no echo pass, no sticker."""
    return _ctx(lang=None, echo_of=None, allow_empty=False, **k)


def _got(s: rs.Shaped):
    return (s.parts, s.dropped_reason, s.banned_hits)


def case_module_is_pure() -> None:
    tree = ast.parse(Path(rs.__file__).read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree))
    mods: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):   # `from . import x` has no module: name x
            mods |= {n.module} if n.module else {a.name for a in n.names}
        elif isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
    assert mods == {"__future__", "random", "collections.abc", "dataclasses", "typing",
                    "_language", "_bubbles", "_nonnative", "_outbound_guard",
                    "_wordfilter"}, mods
    from automations import _bubbles
    assert rs._looks_like_echo is _bubbles._looks_like_echo


# Golden: (name, raw, knobs, wcfi output, autoreply output); output = (parts,
# dropped_reason, hits). Captured from the inline code before the move.
GOLDEN = [
    ("empty", "", {}, ([], "empty", []), ([], "empty", [])),
    ("whitespace_only", "   ", {}, ([], "empty", []), ([], "empty", [])),
    ("plain", "haha you are trouble", {},
     (["haha you are trouble"], None, []), (["haha you are trouble"], None, [])),
    ("multi_bubble", "haha you are trouble\nso what keeps you busy these days?", {},
     (["haha you are trouble", "so what keeps you busy these days?"], None, []),
     (["haha you are trouble", "so what keeps you busy these days?"], None, [])),
    ("over_cap_split", "line one here\nline two here\nline three here", {},
     (["line one here", "line two here"], None, []),
     (["line one here", "line two here"], None, [])),
    ("over_cap_split_style", "a, b, c, d, e, f, g, h", {"style_on": True},
     (["a, b", "c, d, e", "f, g, h"], None, []), (["a, b", "c, d, e", "f, g, h"], None, [])),
    ("over_char_cap", LONG, {}, ([LONG[:600]], None, []), ([LONG[:600]], None, [])),
    ("word_restriction", "lets meet up tonight", {},
     (["lets meeet up tonight"], None, []), (["lets meeet up tonight"], None, [])),
    ("echo_bubble", f"{DM}\nso what keeps you busy these days?", {},
     (["so what keeps you busy these days?"], None, []),
     ([DM, "so what keeps you busy these days?"], None, [])),
    ("echo_only", DM, {}, ([], "echo", []), ([DM], None, [])),
    ("lead_reaction_dupe", "oof\nwhat are you up to tonight", {"style_on": True},
     (["what are you up to tonight"], None, []), (["what are you up to tonight"], None, [])),
    ("banned_block", "you can find me on skype babe",
     {"banned_words": ["skype"], "banned_mode": "block"},
     ([], "banned", ["skype"]), ([], "banned", ["skype"])),
    ("banned_mask", "you can find me on skype babe",
     {"banned_words": ["skype"], "banned_mode": "mask"},
     (["you can find me on s**** babe"], None, ["skype"]),
     (["you can find me on s**** babe"], None, ["skype"])),
    ("nonnative_spacing", "you are beautiful? how are you? definitely gonna see? alone?",
     {"nonnative_on": True, "spacing_on": True},
     (["you are beautifull? hiw are you? deffinetly conna see ? aloane ?"], None, []),
     (["you are beautifull? hiw are you? deffinetly conna see ? aloane ?"], None, [])),
    ("sticker_only_empty", "", {"sticker": True}, ([], None, []), ([], "empty", [])),
    ("echo_only_with_sticker", DM, {"sticker": True}, ([], None, []), ([DM], None, [])),
    ("en_vs_es_meet", "estoy borracha y sola, meet me", {},
     (["estoy borracha y sola, meeet me"], None, []),
     (["estoy borracha y sola, meeet me"], None, [])),
    ("es_word_restriction", "estoy borracha y sola, meet me", {"lang": "es"},
     (["estoy boorracha y sola, meet me"], None, []),
     (["estoy borracha y sola, meeet me"], None, [])),
]


def case_golden_wcfi_vs_autoreply() -> None:
    for name, raw, knobs, want_w, want_a in GOLDEN:
        k = dict(knobs)
        sticker, lang = k.pop("sticker", False), k.pop("lang", "en")
        got_w = _got(rs.shape_parts(raw, _wcfi_ctx(sticker=sticker, lang=lang, **k)))
        got_a = _got(rs.shape_parts(raw, _ar_ctx(**k)))
        assert got_w == want_w, (name, "wcfi", got_w, want_w)
        assert got_a == want_a, (name, "autoreply", got_a, want_a)


def case_echo_predicate_patchable() -> None:
    real = rs._looks_like_echo
    rs._looks_like_echo = lambda part, echo_of: False
    try:
        got = _got(rs.shape_parts(DM, _wcfi_ctx()))
    finally:
        rs._looks_like_echo = real
    assert got == ([DM], None, []), got


_harness.run()
