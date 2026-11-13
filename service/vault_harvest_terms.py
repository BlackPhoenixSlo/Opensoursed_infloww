"""vault_harvest_terms.py — which words the OF-search harvest asks OF about (pure).

The harvest (`vault_ai_api._run_harvest_keywords`) runs OF's own vault search per
term and folds the hits into local search. OF matches on data we can't see (post
captions, its own index), so the more selling words we ask, the more of that
hidden index lands locally.

Two sources, seed first:
  SEED            the "what sells" taxonomy: the Jev questions' outfits, settings,
                  positions, acts and body focus, plus the selling slang
                  operators actually type.
  account_terms   this creator's own most frequent describe/Jev terms (tags,
                  garments, acts, setting, body focus, toys, primary folder) —
                  the vocabulary that already describes HER vault.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping

SEED: tuple[str, ...] = (
    # explicit / acts
    "nude", "naked", "topless", "porn", "masturbation", "fingering", "sex", "blowjob",
    "cum", "pussy", "ass", "booty", "boobs", "tits", "feet", "toy", "dildo", "vibrator",
    "anal", "squirt", "creampie", "riding", "handjob", "titjob", "deepthroat", "facial",
    "orgasm", "moaning", "lick", "spit", "kiss", "strip", "striptease", "undress",
    "twerk", "spread", "doggy", "missionary", "cowgirl", "bent over", "oil", "wet",
    "joi", "rating", "sexting", "custom",
    # partners
    "bg", "boy girl", "gg", "girl girl", "lesbian", "threesome", "couple",
    # body focus
    "nipples", "butt", "legs", "toes", "soles", "lips", "tongue", "belly", "thighs",
    # clothing / lingerie
    "lingerie", "bra", "panties", "thong", "bikini", "dress", "outfit", "heels",
    "stockings", "fishnet", "cosplay", "uniform", "bodysuit", "corset", "latex",
    "leather", "skirt", "shorts", "jeans", "leggings", "yoga pants", "socks", "hoodie",
    "shirt", "crop top", "sports bra", "swimsuit", "towel", "robe", "pajamas", "lace",
    "see through", "costume", "maid", "nurse", "bunny",
    # settings / themes
    "shower", "bath", "bed", "bedroom", "bathroom", "kitchen", "couch", "sofa", "pool",
    "beach", "car", "travel", "gym", "mirror", "outdoor", "nature", "hotel", "balcony",
    "christmas", "halloween", "valentine", "birthday", "morning",
    # style / framing
    "pov", "solo", "selfie", "tease", "closeup", "face", "flowers", "standing",
    "sitting", "kneeling", "lying", "bts", "asmr", "voice", "dance",
    # attributes / colors
    "tattoo", "piercing", "blonde", "brunette", "redhead", "glasses", "nails",
    "red", "black", "white", "blue", "pink", "purple", "green",
)

# describe/Jev fields whose values are selling words (lists or single strings).
_FIELDS = ("tags", "clothing_items", "acts", "body_focus", "toys", "setting",
           "primary_folder", "position")
# Bookkeeping values, not things a fan or OF caption would say.
_NOISE = frozenset({
    "none", "other", "unknown", "n/a", "person present", "watermark", "posing",
    "looking at camera", "smiling", "face and chest", "self touch", "breasts focus",
})
_WORD = re.compile(r"^[a-z][a-z' -]{1,22}[a-z]$")


def _norm(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    t = " ".join(v.lower().replace("_", " ").split())
    if t in _NOISE or not _WORD.match(t) or len(t.split()) > 2:
        return None
    return t


def account_terms(ai_fields: Iterable[Mapping[str, Any] | None], *, top: int = 80,
                  min_count: int = 3) -> list[str]:
    """The `top` most frequent selling words across this account's describe
    answers, each seen on at least `min_count` items (one vote per item)."""
    c: Counter[str] = Counter()
    for f in ai_fields:
        if not isinstance(f, Mapping):
            continue
        seen: set[str] = set()
        for k in _FIELDS:
            v = f.get(k)
            for x in (v if isinstance(v, list) else [v]):
                t = _norm(x)
                if t:
                    seen.add(t)
        c.update(seen)
    return [t for t, n in c.most_common() if n >= min_count][:top]


def harvest_terms(ai_fields: Iterable[Mapping[str, Any] | None], *, top: int = 80) -> list[str]:
    """SEED, then this account's own words not already in it. Order = ask order."""
    seed = list(dict.fromkeys(SEED))
    have = set(seed)
    return seed + [t for t in account_terms(ai_fields, top=top) if t not in have]
