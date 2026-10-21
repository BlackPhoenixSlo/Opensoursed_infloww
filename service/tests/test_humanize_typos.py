"""Tests for the "hard" thumb-typo injector (_common.humanize_typos).

Pure + seeded — no DB, no network. Verifies: at most one typo per reply, the
~1-per-5-sentences rate, protected tokens (names / prices / links / @ / emoji)
never mutate, mutations stay readable, the "*fix" self-correct bubble respects
the bubble budget, and determinism (same seed → same output).

Run: ./venv/bin/python service/tests/test_humanize_typos.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB + TEST_MODE
import random
import re

from automations import _common
from automations._common import humanize_typos, STYLE_MAX_BUBBLES

_harness.bootstrap()

_WORD = re.compile(r"[A-Za-z]+")


def _typo_count(orig: list[str], out: list[str]) -> int:
    """How many of the original (non-'*fix') bubbles were altered."""
    base = [b for b in out if not b.startswith("*")]
    n = 0
    for a, b in zip(orig, base):
        if a != b:
            n += 1
    return n


def case_at_most_one_typo_per_reply():
    # Long multi-bubble reply, swept across many seeds: never more than 1 inline typo.
    parts = ["hey babe i was just thinking about you",
             "really wanna know what you would do",
             "could be fun honestly maybe later tonight"]
    for seed in range(400):
        out = humanize_typos(parts, random.Random(seed))
        assert _typo_count(parts, out) <= 1, (seed, out)


def case_rate_roughly_one_in_five_sentences():
    # A single one-sentence bubble → ~20% of seeds get a typo (the 1-in-5 target).
    one = ["could you really come over later tonight maybe"]
    hits = sum(1 for s in range(2000)
               if _typo_count(one, humanize_typos(one, random.Random(s))))
    rate = hits / 2000.0
    assert 0.15 <= rate <= 0.25, rate


def case_protected_tokens_never_mutate():
    # name, price, @handle, link, emoji — must survive byte-for-byte.
    parts = ["hey Jacob i sent you the $25 unlock",
             "check onlyfans.com/ava and @ava_xo 😈",
             "its only 100 percent worth it babe"]
    protect = ["Jacob"]
    for seed in range(1000):
        out = humanize_typos(parts, random.Random(seed), protect=protect)
        joined = " ".join(out)
        for must in ("Jacob", "$25", "onlyfans.com/ava", "@ava_xo", "😈", "100"):
            assert must in joined, (seed, must, out)


def case_mutations_stay_readable():
    # Every produced inline slip is a length-1 edit of some original word
    # (transpose / drop / collapse) — never a wrong dictionary word swap.
    parts = ["honestly could you really believe that happened"]
    orig_words = set(_WORD.findall(parts[0].lower()))
    seen_typo = False
    for seed in range(2000):
        out = humanize_typos(parts, random.Random(seed))
        base = [b for b in out if not b.startswith("*")][0]
        if base == parts[0]:
            continue
        seen_typo = True
        new_words = _WORD.findall(base.lower())
        changed = [w for w in new_words if w not in orig_words]
        assert changed, (seed, base)
        for w in changed:
            assert len(w) >= 3, (seed, w)  # collapse/drop keep it pronounceable
    assert seen_typo, "expected at least one typo across the sweep"


def case_self_correct_respects_budget():
    # When already at max_bubbles, a typo must NOT append a "*fix" bubble.
    full = ["could you come over", "really tonight maybe", "honestly that sounds good",
            "no pressure though babe", "just thinking about it", "lemme know either way"]
    assert len(full) == STYLE_MAX_BUBBLES
    for seed in range(1000):
        out = humanize_typos(full, random.Random(seed), max_bubbles=STYLE_MAX_BUBBLES)
        assert len(out) <= STYLE_MAX_BUBBLES, (seed, out)
        assert not any(b.startswith("*") for b in out), (seed, out)


def case_self_correct_fires_and_points_at_right_word():
    # With room to spare, some seeds produce a follow-up correction bubble. Its
    # SHAPE varies (*word / word* / *word lol / omg *word / bare retype) but it
    # ALWAYS names an ORIGINAL word — there is no generic "omg typo" filler.
    parts = ["could you really come over tonight maybe"]  # 1 bubble, room for 2 more
    orig = set(_WORD.findall(parts[0].lower()))
    found = False
    saw_omg = saw_star = False
    for seed in range(2000):
        out = humanize_typos(parts, random.Random(seed))
        if len(out) <= len(parts):      # no correction appended this seed
            continue
        found = True
        fix = out[-1]                   # the correction is always the last bubble
        assert fix != "omg typo", (seed, fix)   # the generic filler is gone
        if fix.startswith("omg"):
            saw_omg = True
        if "*" in fix:
            saw_star = True
        # every form names a real original word ('omg'/'lol' are just fillers)
        toks = [t for t in _WORD.findall(fix.lower()) if t not in ("lol", "omg")]
        assert toks and toks[0] in orig, (seed, fix, out)
    assert found, "self-correct bubble never fired across the sweep"
    assert saw_omg and saw_star, (saw_omg, saw_star)   # both shapes appear


def case_ugly_slips_get_fixed_more_often():
    # Severity weighting: across a corpus, an obviously-wrong garble is corrected
    # at a HIGHER rate than a subtle one. We can't force a specific slip, but the
    # fix-rate among ugly slips should exceed that among subtle ones.
    from automations._common import _slip_is_ugly  # noqa: PLC0415
    parts = ["honestly could you really believe that happened tonight"]
    ugly_fixed = ugly_tot = subtle_fixed = subtle_tot = 0
    for seed in range(6000):
        out = humanize_typos(parts, random.Random(seed))
        base = [b for b in out if not (b.startswith("*"))]
        if not base or base[0] == parts[0]:
            continue  # no inline typo this seed
        # which original word changed?
        ow = _WORD.findall(parts[0].lower())
        nw = _WORD.findall(base[0].lower())
        slipped = next((b for a, b in zip(ow, nw) if a != b), None)
        orig = next((a for a, b in zip(ow, nw) if a != b), None)
        if slipped is None:
            continue
        fixed = len(out) > 1  # a correction bubble was appended
        if _slip_is_ugly(orig, slipped):
            ugly_tot += 1; ugly_fixed += int(fixed)
        else:
            subtle_tot += 1; subtle_fixed += int(fixed)
    assert ugly_tot and subtle_tot, (ugly_tot, subtle_tot)
    assert (ugly_fixed / ugly_tot) > (subtle_fixed / subtle_tot), \
        (ugly_fixed, ugly_tot, subtle_fixed, subtle_tot)


def case_deterministic():
    parts = ["could you really come over later tonight maybe babe"]
    for seed in (1, 7, 42, 999):
        a = humanize_typos(parts, random.Random(seed))
        b = humanize_typos(parts, random.Random(seed))
        assert a == b, (seed, a, b)


def case_empty_and_blank_safe():
    assert humanize_typos([], random.Random(0)) == []
    assert humanize_typos(["", "   "], random.Random(0)) == []
    # short-word-only reply has no eligible tokens → unchanged
    assert humanize_typos(["u up", "lol ok"], random.Random(0)) == ["u up", "lol ok"]


if __name__ == "__main__":
    _harness.run(
        case_at_most_one_typo_per_reply,
        case_rate_roughly_one_in_five_sentences,
        case_protected_tokens_never_mutate,
        case_mutations_stay_readable,
        case_self_correct_respects_budget,
        case_self_correct_fires_and_points_at_right_word,
        case_ugly_slips_get_fixed_more_often,
        case_deterministic,
        case_empty_and_blank_safe,
    )
