#!/usr/bin/env python3
from __future__ import annotations

import _harness

import ast  # noqa: E402
import random  # noqa: E402
from pathlib import Path  # noqa: E402

from automations import _bubbles as b  # noqa: E402


def case_module_is_pure() -> None:
    tree = ast.parse(Path(b.__file__).read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "re", "random"}, mods
    from automations import _reply_shape as rs
    from automations import autoreply as ar
    from automations import welcome_chatter_for_info as wc
    for name in ("_strip_html", "_history_text"):
        assert getattr(wc, name) is getattr(b, name), name
        assert getattr(ar, name) is getattr(b, name), name
    for name in ("split_for_bubbles", "_dedupe_lead_reaction", "_looks_like_echo"):
        assert getattr(rs, name) is getattr(b, name), name


def case_split_for_bubbles_table() -> None:
    rows = [
        ("a\nb\nc", 2, 1, False, ["a", "b"]),
        ("a, b, c, d, e, f, g, h", 3, 5, False,
         ["a, b", "c, d, e", "f, g, h"]),
        ("whats ur job? u gonna spill?", 6, 1, False,
         ["whats ur job", "u gonna spill?"]),
        ("bet ur kitchen is as hot as you are 😏 where ya located", 6, 1, False,
         ["bet ur kitchen is as hot as you are 😏", "where ya located"]),
        ("what's up? 😏", 6, 1, False, ["what's up? 😏"]),
        ("oof — restaurant life is brutal", 2, 1, False,
         ["oof", "restaurant life is brutal"]),
        ("oof, restaurant life is brutal. how old are ya", 6, 1, True,
         ["oof, restaurant life is brutal, how old are ya"]),
    ]
    for text, cap, seed, single, want in rows:
        got = b.split_for_bubbles(text, cap, rng=random.Random(seed), force_single=single)
        assert got == want, (text, cap, seed, single, got)
        assert len(got) <= cap and not any("—" in p or "–" in p for p in got), got
    assert b._merge_orphans(["hey?", "😏"]) == ["hey? 😏"]
    assert b._cap_one_question(["oh yeah?", "how old r u?"]) == ["oh yeah", "how old r u?"]


def case_seeded_rng_is_deterministic() -> None:
    raw = "bet ur kitchen is as hot as you are 😏 where ya located, tell me"
    for cap in (2, 6):
        for seed in range(20):
            runs = {tuple(b.split_for_bubbles(raw, cap, rng=random.Random(f"split:1:{seed}")))
                    for _ in range(3)}
            assert len(runs) == 1, (cap, seed, runs)


def case_dedupe_lead_reaction_table() -> None:
    rows = [
        (["oof", "where u from"], ["oof"], ["where u from"]),
        (["oof babe that's wild"], ["oof"], ["babe that's wild"]),
        (["ooof", "haha"], ["lol", "oof"], ["haha"]),
        (["lol", "nice"], ["oof"], ["lol", "nice"]),
        (["oof", "hi"], ["how was work"], ["oof", "hi"]),
        (["oof"], ["oof"], ["oof"]),
        (["oof", "hi"], ["oof", "a", "b", "c"], ["oof", "hi"]),
        ([], ["oof"], []),
    ]
    for parts, recent, want in rows:
        got = b._dedupe_lead_reaction(parts, recent)
        assert got == want, (parts, recent, got)


def case_looks_like_echo_table() -> None:
    last_in = "long shift too? at least the coffee here is solid"
    rows = [
        (last_in, last_in, True),
        ("Long shift too at least the coffee here is solid!!", last_in, True),
        ("long shift too? at least the coffee here is solid lol", last_in, True),
        ("lol", "lol", False),
        ("where are you from babe", last_in, False),
        ("", last_in, False),
    ]
    for part, his, want in rows:
        assert b._looks_like_echo(part, his) is want, (part, his)


def case_strip_html_and_history_text() -> None:
    from automations._inbound import MSG_CLIP
    assert b._MSG_CLIP == MSG_CLIP, (b._MSG_CLIP, MSG_CLIP)
    assert b._strip_html(None) == ""
    assert b._strip_html("") == ""
    assert b._strip_html("  plain  ") == "plain"
    assert b._strip_html("<p>hi <b>u</b></p>") == "hi u"
    rows = [
        ("in", "<p>hi</p>", "a cat", "hi [he sent: a cat]"),
        ("in", None, "a cat", "[he sent: a cat]"),
        ("in", "hi", None, "hi"),
        ("out", "yo", "a cat", "yo"),
        ("in", "x" * 1000, None, "x" * MSG_CLIP),
    ]
    for d, body, desc, want in rows:
        assert b._history_text(d, body, desc) == want, (d, body, desc)


_harness.run()
