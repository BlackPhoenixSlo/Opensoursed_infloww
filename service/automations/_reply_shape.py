"""automations/_reply_shape.py — the sync middle of a chat reply's shaping, shared by
welcome_chatter_for_info (wcfi) and autoreply: one generated reply (already through
`finalize_draft`) -> the bubbles to send, or why the turn is dropped.

Stages, in the order both engines ran them inline:
  1. split (`split_for_bubbles`, seeded `split:{seed_id}:{raw}`) + OF word restriction
     + per-bubble char cap, at most `max_bubbles` (`force_single`: every unit casually joined
     into one bubble, nothing dropped — Full AI's separate PPV caption)
  2. echo drop: a bubble that parrots his last line (`_looks_like_echo`) — wcfi only
  3. lead-reaction dedupe vs our recent outbound (`_dedupe_lead_reaction`) — style on
  4. empty -> drop ("empty" or "echo"), unless `allow_empty` (wcfi: a sticker rides alone)
  5. compliance word filter (`filter_banned`): block -> drop ("banned"); mask -> hits kept
  6. non-native misspellings, then the '?' spacing (one rng `{seed_id}:{raw}:q`)

What stays in each caller, in its own order, because it is not pure: the sticker marker
(`cat_stickers.parse_marker` / `keep_tag`), `await finalize_draft`, wcfi's
`await _bump_attempt`, and `await apply_typo_throttle` after this.

Engine differences are ShapeCtx fields, all required (no defaults: a forgotten field is a
TypeError, never a silently-off stage): autoreply passes `lang=None` (language-blind word
restriction), `echo_of=None` (this engine has no echo pass), `allow_empty=False`.

`_looks_like_echo` is read as this module's attribute at call time (a slop fault patches
`_reply_shape._looks_like_echo`).
"""
from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from . import _language
from ._bubbles import _dedupe_lead_reaction, _looks_like_echo, split_for_bubbles
from ._nonnative import apply_nonnative_spacing, apply_nonnative_style
from ._outbound_guard import apply_word_restriction
from ._wordfilter import filter_banned


@dataclass(frozen=True, kw_only=True)
class ShapeCtx:
    seed_id: int                 # the fan id the engine formats into its rng seeds
    max_bubbles: int
    max_chars: int
    lang: str | None             # None: language-blind word restriction (autoreply)
    echo_of: str | None          # his line for the echo drop; None: the engine has no echo pass
    style_on: bool
    recent_out: Sequence[str]    # our recent outbound bubbles (lead-reaction dedupe)
    allow_empty: bool            # wcfi with a sticker tag: no text is still a reply
    banned_words: Sequence[str]
    banned_mode: str
    nonnative_on: bool
    spacing_on: bool
    name_protect: Sequence[str]  # names the non-native pass must not touch
    force_single: bool = False   # one bubble, every unit joined (Full AI caption); the one default


@dataclass(frozen=True, kw_only=True)
class Shaped:
    parts: list[str]
    dropped_reason: Literal["empty", "echo", "banned"] | None
    banned_hits: list[str]


def shape_parts(raw: str, ctx: ShapeCtx) -> Shaped:
    if ctx.lang is None:
        restrict = apply_word_restriction
    else:
        def restrict(p: str) -> str:
            return _language.apply_word_restriction(p, ctx.lang)
    parts = [restrict(p)[:ctx.max_chars]
             for p in split_for_bubbles(raw, ctx.max_bubbles,
                                        rng=random.Random(f"split:{ctx.seed_id}:{raw}"),
                                        force_single=ctx.force_single)
             if p.strip()][:ctx.max_bubbles]
    reason: Literal["empty", "echo"] = "empty"
    if ctx.echo_of is not None:
        kept = [p for p in parts if not _looks_like_echo(p, ctx.echo_of)]
        if parts and not kept:
            reason = "echo"
        parts = kept
    if ctx.style_on and parts:
        parts = _dedupe_lead_reaction(parts, ctx.recent_out)
    if not parts and not ctx.allow_empty:
        return Shaped(parts=[], dropped_reason=reason, banned_hits=[])
    parts, hits = filter_banned(parts, ctx.banned_words, ctx.banned_mode)
    if parts is None:
        return Shaped(parts=[], dropped_reason="banned", banned_hits=hits)
    if ctx.nonnative_on:
        q_rng = random.Random(f"{ctx.seed_id}:{raw}:q")
        parts = [apply_nonnative_style(p, protect=ctx.name_protect) for p in parts]
        if ctx.spacing_on:
            parts = [apply_nonnative_spacing(p, q_rng) for p in parts]
    return Shaped(parts=parts, dropped_reason=None, banned_hits=hits)
