from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import NamedTuple

from ._common import (
    CAT_STICKER_GAP_MIN_KEY, CAT_STICKER_SKIP_PCT_KEY, CAT_STICKER_SOLO_PCT_KEY,
    CAT_STICKERS_KEY, _load_style_json, _style_force_off,
)

log = logging.getLogger("of-relay.automation.cat_stickers")



class StickerConfig(NamedTuple):
    enabled: bool
    skip_w: float
    solo_w: float
    gap_min: float


async def load_cat_sticker_config(account_id: str) -> StickerConfig:
    stored = await _load_style_json(account_id)
    if _style_force_off():
        enabled = False
    else:
        val = stored.get(CAT_STICKERS_KEY)
        enabled = True if val is None else bool(val)

    def _num(key: str, default: float, scale: float, hi: float) -> float:
        v = stored.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return default
        return min(max(float(v) * scale, 0.0), hi)

    return StickerConfig(
        enabled,
        _num(CAT_STICKER_SKIP_PCT_KEY, DEFAULT_SKIP, 0.01, 1.0),
        _num(CAT_STICKER_SOLO_PCT_KEY, DEFAULT_SOLO, 0.01, 1.0),
        _num(CAT_STICKER_GAP_MIN_KEY, DEFAULT_GAP_MIN, 1.0, 7 * 24 * 60))


from ._markers import STICKER_KEYWORD, bare_star_span, protocol_marker_re

log = logging.getLogger("of-relay.automation.cat_stickers")

_CATALOG: dict[str, tuple[str, tuple[str, ...]]] = {
    'laugh': ('genuinely funny',
              ('2g6sCTsSoVuSfSxK4W', 'M8lbkkn8BFFLO', '96suQaNpBRyE')),
    'love': ('he said something sweet',
             ('a9VAlh8bgb0SA', 'LVXJQat47MwQU', 'ohiWzVWGkAOCA', '5QXd9CLYmU944', 'zGJegUgNbPOtW')),
    'kiss': ('goodnight/goodbye kiss',
             ('W1hd3uXRIbddu', 'xI1pK446iNJeg')),
    'flirty': ('playful teasing',
               ('KI5JqBqOKCPjG', 'HB9nUzmw6L74HHWpqN')),
    'shy': ('play coy after a compliment',
            ('xFOc3rYIGE3aE', 'Iwt30C4BH94ty', '33JJnbUuorikA5zWgB', 'dxqOkrl29R8ac')),
    'celebrate': ('he bought/tipped or good news',
                  ('TbRkubcqlgBksEqMv4', 'A0Zt7yuDULiy4ofmVD', 'NfzERYyiWcXU4', 'Ga0gHvT84m3yTE8lIp')),
    'miss_you': ('he was away',
                 ('vxsoC27UotxBK', 'vFjAksOeerSdW', 'MDJ9IbxxvDUQM', '1FkCqpyObTuo0', 'd9eL06htb5Vks', 'SgZtvjwcfq0ww')),
    'eyeroll': ('sassy, something silly',
                ('1wqK6DFqm5FW8ZCdJ9', 'NxwRDSUNzXshW', 'nazt106Gb1Ga4')),
    'shocked': ('wild thing he said',
                ('Cdkk6wFFqisTe', '135QXxqZ9d0QGk', 'BBNYBoYa5VwtO', '113YkW9oWdtFlu')),
    'sleepy': ('goodnight, cozy in bed',
               ('12cYyFxlbIgXeg', 'GxQABXQhII7cY', 'Tfr91anUahoME', 'lFpvlU0or3SHC', 'DRNsbfCHNznxe')),
    'good_morning': ('morning greeting',
                     ('8B0TmFIOZ9iJJgJu8T', 'OWQzUnzgX7bS8', '10zHDq77BLwcy4', 'cwxKYaFLOBd1S', 'AC8n0wdJvnA6A', 'papAALBn286ty')),
    'waiting': ('he went quiet',
                ('ZT0YXuyEN2ZdNLmAq8', 'cbLcSvHw50bJ8UuImn', 'm22Lj3VfcwDNvqc2Rd', 'tTImgMAq1DDuVnPrbX')),
    'money': ('money talk, he spoils you',
              ('XQKBuQmfjt1xm', '10RTemEe5yjo0U', 'cLLgfNJiKppgA', 'ND6xkVPaj8tHO')),
}

TAGS = frozenset(_CATALOG)

# Rate control is in code: DeepSeek attaches a sticker to ~48% of replies when the block is visible.
DEFAULT_SKIP = 0.0
DEFAULT_SOLO = 0.05
DEFAULT_GAP_MIN = 0.0

_last_sent: dict[tuple[str, int], datetime] = {}
_last_pick: dict[tuple[str, int], tuple[str, str]] = {}

_MARKER_RE = protocol_marker_re(STICKER_KEYWORD)

_STICKER_WORD_RE = re.compile(r"(?<![A-Za-z])stickers?(?![A-Za-z])", re.IGNORECASE)


def _tag_for(words: str) -> str | None:
    parts = [p for p in re.split(r"[^A-Za-z]+", (words or "").lower()) if p]
    for take in (2, 1):
        key = "_".join(parts[:take])
        if not key:
            return None
        if key in _CATALOG:
            return key
        near = [t for t in _CATALOG if t.startswith(key)]
        if len(near) == 1:
            return near[0]
    return None


# Marker text is always stripped; prose still naming a sticker above a valid marker is dropped whole (the gif is the reply) and logged.
def parse_marker(raw: str) -> tuple[str, str | None]:
    m = _MARKER_RE.search(raw or "")
    clean = _MARKER_RE.sub("", raw or "").strip()
    if m:
        if clean and _STICKER_WORD_RE.search(clean):
            log.info("cat_stickers suppressed prose about the sticker: %r", clean[:120])
            clean = ""
        return clean, _tag_for(m.group(1))
    # Exact tag only, not prefix: prefix-matching a bare emote turns '*go on*' into a good_morning gif.
    if bare := bare_star_span(clean):
        tag = bare.lower().replace(" ", "_")
        if tag in _CATALOG:
            return "", tag
    return clean, None


def roll_mode(rng, on_cooldown: bool,
              skip_w: float = DEFAULT_SKIP,
              solo_w: float = DEFAULT_SOLO) -> str:
    if on_cooldown:
        return "skip"
    skip_w = min(max(float(skip_w), 0.0), 1.0)
    solo_w = min(max(float(solo_w), 0.0), 1.0 - skip_w)
    r = rng.random()
    if r < solo_w:
        return "solo"
    if r < 1.0 - skip_w:
        return "allow"
    return "skip"


def cooldown_active(account_id: str, fan_id: int,
                    now: datetime | None = None,
                    gap_min: float = DEFAULT_GAP_MIN) -> bool:
    if gap_min <= 0:
        return False
    last = _last_sent.get((str(account_id), int(fan_id)))
    return (last is not None
            and (now or datetime.utcnow()) - last < timedelta(minutes=gap_min))


def mark_sent(account_id: str, fan_id: int,
              now: datetime | None = None,
              tag: str | None = None, gif_id: str | None = None) -> None:
    _last_sent[(str(account_id), int(fan_id))] = now or datetime.utcnow()
    if tag is not None or gif_id is not None:
        _last_pick[(str(account_id), int(fan_id))] = (tag or "", gif_id or "")


def keep_tag(account_id: str, fan_id: int, tag: str | None,
             *, has_text: bool) -> str | None:
    if tag is None or not has_text:
        return tag
    prev = _last_pick.get((str(account_id), int(fan_id)))
    return None if (prev and prev[0] == str(tag)) else tag


# No fallback to the female pool for him; excludes the fan's previous clip because pools are 2-6 wide and repeats ~25% otherwise.
def pick_gif(tag: str, rng, account_id: str, fan_id: int,
             voice: str = "her") -> str | None:
    if _is_him(voice):
        gifs = _CATALOG_HIM.get(tag, ())
    else:
        gifs = _CATALOG.get(tag, ("", ()))[1]
    if not gifs:
        return None
    prev = _last_pick.get((str(account_id), int(fan_id)))
    if prev and prev[1]:
        fresh = tuple(g for g in gifs if g != prev[1])
        if fresh:
            gifs = fresh
    return rng.choice(gifs)


# Submissive/eager tags read as performing for approval, the register the male lane inverts.
_TAGS_NOT_FOR_HIM = frozenset({
    "shy", "pout", "beg", "miss_you", "kiss", "love", "dance", "celebrate",
    "excited",
})

# Male pack is animals only: giphy's gym/combat supply is recognisable people, worse than the tonal problem.
_CATALOG_HIM: dict[str, tuple[str, ...]] = {
    'laugh': ('FLKUJnRt6cGBG102B0', 'Ut0KxC3gnIwcEpmTZW', 'XN8YOV0H6YfVFFGxth'),
    'flirty': ('sWBzg2D15WwQjHcxbt', 'eKP4xPPkYm7WyMyDR2', 'zZbkdtXpqqkARUomtQ'),
    'eyeroll': ('Wwn5NKv4At2CIc8XQa', '11nQ2iZnQpPkgo', 'TZC932cYxsgr87gowA'),
    'shocked': ('ZK92FCOPbY8JaFhiMM', '1ZNI35FsYGMtko7m9k', 'hoictzHHdRbZr0XrqE'),
    'sleepy': ('d26dt3KtXoPeft6Lm6', '13MqteASr9UOGs', 'NFnR57Oj2LiWcJUb01'),
    'good_morning': ('b9NywKMAEpmPm', 'ROjjp6hqqgACs', 'OssGz3OQzVqb6'),
    'waiting': ('hgT3tIssMXLTc7ZwwT', '1xV85u4aYIXfpVh8xW', 'UNkS45j4Rcam9TyOQ2'),
    'money': ('RoS4JYcw0RvK8', 'VRwGkD5zYcbW8', '12pJ8OxSWwO86Y'),
}

_PACK_NOUN = {"her": "cat", "him": "dog & wolf"}


def _is_him(voice: str) -> bool:
    return str(voice or "").strip().lower() == "him"


def prompt_block(mode: str, voice: str = "her") -> str:
    if mode not in ("allow", "solo"):
        return ""
    male = _is_him(voice)
    items = [(t, w) for t, (w, _) in _CATALOG.items()
             if not male or t in _CATALOG_HIM]
    tag_lines = "\n".join(f"- {t}: {when}" for t, when in items)
    frame = ("the kind you fire off when a word would be too much"
             if male else "the kind real girls spam in texts")
    noun = _PACK_NOUN["him" if male else "her"]
    block = (
        f"{noun.upper()} STICKERS — {noun} reaction gifs, "
        f"{frame}. Tags:\n" + tag_lines + "\n"
        "Rules: MOST replies need NO sticker, max ONE. to attach, end your "
        "reply with a line that is exactly: STICKER: <tag> — it's stripped, "
        "the fan only sees the gif. it can BE the whole reply (ONLY the "
        "STICKER line, no text). "
        "NEVER mention the sticker in your text."
    )
    if mode == "solo":
        block += (
            "\n- THIS message: if ANY sticker fits, reply with ONLY the "
            "STICKER line, no text.")
    return block
