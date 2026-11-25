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
    seed_id: int
    max_bubbles: int
    max_chars: int
    lang: str | None
    echo_of: str | None
    style_on: bool
    recent_out: Sequence[str]
    allow_empty: bool
    banned_words: Sequence[str]
    banned_mode: str
    nonnative_on: bool
    spacing_on: bool
    name_protect: Sequence[str]
    force_single: bool = False


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
