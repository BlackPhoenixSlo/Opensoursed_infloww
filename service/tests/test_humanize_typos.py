from __future__ import annotations

import _harness
import random
import re

from automations import _common
from automations._common import humanize_typos, STYLE_MAX_BUBBLES

_harness.bootstrap()

_WORD = re.compile(r"[A-Za-z]+")


def _typo_count(orig: list[str], out: list[str]) -> int:
    base = [b for b in out if not b.startswith("*")]
    n = 0
    for a, b in zip(orig, base):
        if a != b:
            n += 1
    return n


def case_at_most_one_typo_per_reply():
    parts = ["hey babe i was just thinking about you",
             "really wanna know what you would do",
             "could be fun honestly maybe later tonight"]
    for seed in range(400):
        out = humanize_typos(parts, random.Random(seed))
        assert _typo_count(parts, out) <= 1, (seed, out)


def case_rate_roughly_one_in_five_sentences():
    one = ["could you really come over later tonight maybe"]
    hits = sum(1 for s in range(2000)
               if _typo_count(one, humanize_typos(one, random.Random(s))))
    rate = hits / 2000.0
    assert 0.15 <= rate <= 0.25, rate


def case_protected_tokens_never_mutate():
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
            assert len(w) >= 3, (seed, w)
    assert seen_typo, "expected at least one typo across the sweep"


def case_self_correct_respects_budget():
    full = ["could you come over", "really tonight maybe", "honestly that sounds good",
            "no pressure though babe", "just thinking about it", "lemme know either way"]
    assert len(full) == STYLE_MAX_BUBBLES
    for seed in range(1000):
        out = humanize_typos(full, random.Random(seed), max_bubbles=STYLE_MAX_BUBBLES)
        assert len(out) <= STYLE_MAX_BUBBLES, (seed, out)
        assert not any(b.startswith("*") for b in out), (seed, out)


def case_self_correct_fires_and_points_at_right_word():
    parts = ["could you really come over tonight maybe"]
    orig = set(_WORD.findall(parts[0].lower()))
    found = False
    saw_omg = saw_star = False
    for seed in range(2000):
        out = humanize_typos(parts, random.Random(seed))
        if len(out) <= len(parts):
            continue
        found = True
        fix = out[-1]
        assert fix != "omg typo", (seed, fix)
        if fix.startswith("omg"):
            saw_omg = True
        if "*" in fix:
            saw_star = True
        toks = [t for t in _WORD.findall(fix.lower()) if t not in ("lol", "omg")]
        assert toks and toks[0] in orig, (seed, fix, out)
    assert found, "self-correct bubble never fired across the sweep"
    assert saw_omg and saw_star, (saw_omg, saw_star)


def case_ugly_slips_get_fixed_more_often():
    from automations._common import _slip_is_ugly  # noqa: PLC0415
    parts = ["honestly could you really believe that happened tonight"]
    ugly_fixed = ugly_tot = subtle_fixed = subtle_tot = 0
    for seed in range(6000):
        out = humanize_typos(parts, random.Random(seed))
        base = [b for b in out if not (b.startswith("*"))]
        if not base or base[0] == parts[0]:
            continue
        ow = _WORD.findall(parts[0].lower())
        nw = _WORD.findall(base[0].lower())
        slipped = next((b for a, b in zip(ow, nw) if a != b), None)
        orig = next((a for a, b in zip(ow, nw) if a != b), None)
        if slipped is None:
            continue
        fixed = len(out) > 1
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


def case_reply_rate_overrides_sentence_rule():
    one = ["maybe tonight babe"]
    for seed in range(300):
        out = humanize_typos(one, random.Random(seed), reply_rate=1.0)
        assert _typo_count(one, out) == 1, (seed, out)
        assert humanize_typos(one, random.Random(seed), reply_rate=0.0) == one, seed
        assert (humanize_typos(one, random.Random(seed), reply_rate=None)
                == humanize_typos(one, random.Random(seed))), seed
    assert humanize_typos(["u up", "lol ok"], random.Random(0), reply_rate=1.0) == ["u up", "lol ok"]
    many = ["maybe tonight babe. honestly cant wait. thinking about you"]
    hits = sum(1 for s in range(2000)
               if _typo_count(many, humanize_typos(many, random.Random(s), reply_rate=0.5)))
    assert 0.44 <= hits / 2000.0 <= 0.56, hits


def case_empty_and_blank_safe():
    assert humanize_typos([], random.Random(0)) == []
    assert humanize_typos(["", "   "], random.Random(0)) == []
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
        case_reply_rate_overrides_sentence_rule,
        case_empty_and_blank_safe,
    )
