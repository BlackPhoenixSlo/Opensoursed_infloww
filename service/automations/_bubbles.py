"""
service/automations/_bubbles.py — the reply → texting-bubbles splitter + the history-line
text helpers, shared by welcome_chatter_for_info and autoreply.

Pure: no DB, no I/O. Moved verbatim out of welcome_chatter_for_info.py, which
re-imports (and so still exposes) every name it uses.
"""
from __future__ import annotations

import random
import re

# Clip each history body. == `_inbound.MSG_CLIP` (the handoff seam's clip); a
# literal so this module stays DB-free (`_inbound` imports db.models) —
# test_bubbles pins the two equal.
_MSG_CLIP = 400

# Emoji (with optional variation selector) + the LLM em-dash "tell".
_EMOJI = "[\U0001F300-\U0001FAFF\U00002600-\U000027BF❤]️?"
_EMOJI_RE = re.compile(_EMOJI)
_TRAIL_EMOJI_RE = re.compile(_EMOJI + r"\s*$")
_DASH_RE = re.compile(r"\s*[—–]\s*|\s*--\s*|\s+-\s+")  # em/en dash, --, spaced hyphen
_DASH_CLEAN_RE = re.compile(r"\s*[—–]\s*")     # any residual em/en dash → ", "


def _strip_dash(s: str) -> str:
    """An em/en dash never belongs in a casual text (it's a dead LLM tell). Any
    that survives a split is replaced with a comma so no bubble ever shows one."""
    return _DASH_CLEAN_RE.sub(", ", s).strip().rstrip(",").strip()


# Real texters break a thought into separate sends: a leading reaction, then the
# statement, then the question. The model usually writes it as ONE line with
# punctuation ("oof, restaurant life is brutal. how old are ya"), so in style mode
# we split it ourselves on a leading interjection + sentence boundaries → up to 3
# bubbles ("oof" / "restaurant life is brutal" / "how old are ya").
_REACTIONS = (r"oo+f|lo+l|lma+o|omg|ha+ha+|hah|mm+|mhm+|ugh|hmm+|aw+|damn|stop|oh|yo|"
              r"wait|bet|nice|fair|true|lowkey|ok|okay|yeah|yep|nah")
# Peels a lead reaction that's FUSED into a longer line ("oof, restaurant..." →
# "oof" + rest); requires trailing content, so it won't match a bare reaction.
_LEAD_REACT_RE = re.compile(rf"^({_REACTIONS})\b[,!.]*\s+", re.I)
# Matches the reaction word at the start whether or not anything follows — used to
# fingerprint an opener (incl. a standalone "oof" bubble) for repeat-detection.
_REACT_WORD_RE = re.compile(rf"^({_REACTIONS})\b", re.I)
# Girl-style bubble breaks: a sentence boundary (the .?! is KEPT on the chunk), OR
# a comma / dash-family marker where a real texter would hit send — the comma or
# dash itself is CONSUMED so it never shows inside a bubble. Per the style spec
# every comma is a bubble break ("no, i dont think so" → "no" / "i dont think so").
_SENT_SPLIT_RE = re.compile(r"(?<=[.?!])\s+|\s*,\s*|\s*[—–]\s*|\s*--\s*|\s+-\s+")


# When a chunk is STILL long after the comma/sentence split, break it further at a
# mid emoji (the emoji is KEPT on the left bubble) or before a WH question word that
# has enough lead-in. Short chunks pass through untouched (don't over-split a tiny
# reply). "if the text is long, split at ? or emoji or when/who/what …"
_WH_RE = re.compile(r"\b(what|whats|where|when|who|why|which|how)\b", re.I)
_LONG_CHUNK = 40           # only emoji/WH-split a chunk longer than this many chars
_WH_MIN_LEAD_WORDS = 4     # …and only before a WH-word with ≥ this many words before it


def _split_emoji_wh(seg: str) -> list[str]:
    """Break a LONG segment further: after a mid emoji (emoji KEPT on the left), or
    before a WH question word with ≥ _WH_MIN_LEAD_WORDS words of lead-in. Recurses on
    the remainder. A short segment — or one with no such break — passes through."""
    seg = seg.strip()
    if not seg:
        return []
    if len(seg) <= _LONG_CHUNK:
        return [seg]
    for m in _EMOJI_RE.finditer(seg):           # emoji with content after → split after it
        before, after = seg[:m.end()].strip(), seg[m.end():].strip()
        if before and after:
            return [before] + _split_emoji_wh(after)
    for m in _WH_RE.finditer(seg):              # a WH-word that opens a fresh clause
        if m.start() == 0:
            continue
        before, after = seg[:m.start()].strip().rstrip(","), seg[m.start():].strip()
        if before and after and len(before.split()) >= _WH_MIN_LEAD_WORDS:
            return [before] + _split_emoji_wh(after)
    return [seg]


def _split_units(text: str) -> list[str]:
    """Break ONE line into texting bubbles: split on every comma + sentence boundary
    + dash (comma/dash CONSUMED, .?! KEPT), then break any still-LONG chunk further
    at a mid emoji or WH word. A trailing '.' is dropped (casual). NO cap here — the
    caller caps and merges overflow so nothing is ever dropped."""
    out: list[str] = []
    for chunk in _SENT_SPLIT_RE.split(text.strip()):
        for sub in _split_emoji_wh(chunk):
            if sub.endswith("."):
                sub = sub[:-1].strip()
            if sub:
                out.append(sub)
    return out


def _cap_merge(parts: list[str], max_bubbles: int) -> list[str]:
    """Cap the bubble count at max_bubbles WITHOUT dropping content — any overflow
    merges into the last bubble."""
    if len(parts) > max_bubbles:
        return parts[:max_bubbles - 1] + [" ".join(parts[max_bubbles - 1:])]
    return parts


_HAS_WORD_RE = re.compile(r"[A-Za-z0-9]")


def _merge_orphans(parts: list[str]) -> list[str]:
    """A bubble with NO letters/digits (a stranded emoji or bare punctuation, e.g. a
    trailing '😏' the sentence split peeled off after a '?') isn't a real text — glue
    it onto the END of the previous bubble so we never send a lone '😏' bubble."""
    out: list[str] = []
    for p in parts:
        if out and not _HAS_WORD_RE.search(p):
            out[-1] = (out[-1] + " " + p).strip()
        else:
            out.append(p)
    return out


def _casual_join(parts: list[str]) -> str:
    """Glue bubbles back into ONE casual line: a space after terminal punctuation
    (so '...bbq? bold claim' not '...bbq?, bold claim'), a comma between plain
    clauses (so a trailing vocative reads 'how old are you, jack')."""
    out = (parts[0] or "").strip()
    for p in parts[1:]:
        p = (p or "").strip()
        if not p:
            continue
        sep = " " if out.rstrip().endswith(("?", "!", ".", "…")) else ", "
        out = out.rstrip() + sep + p
    return out


def _target_bubbles(words: int) -> int:
    """How many bubbles a reply of `words` words SHOULD become — short stays on one
    line, longer earns more, but it never explodes (13 words is 2-3 lines, NOT 5).
    A real texter sends ~one short line per handful of words: 3 → 1, 5 → 2, 13 → 3."""
    if words <= 4:
        return 1
    if words <= 9:
        return 2
    if words <= 15:
        return 3
    return 4


def _group_to_target(units: list[str], target: int) -> list[str]:
    """Merge the fine-grained `units` (every comma / clause break) down to `target`
    bubbles by grouping CONTIGUOUS units into roughly equal runs — the extra units go
    to the LAST groups, so a trailing vocative ('where are you from' + 'jack?') rejoins
    instead of stranding. Joined casually (comma between clauses). Never drops content."""
    n = len(units)
    if target <= 1:
        return [_casual_join(units)] if units else []
    if target >= n:
        return units
    base, rem = divmod(n, target)
    sizes = [base] * (target - rem) + [base + 1] * rem   # bigger groups at the end
    out, i = [], 0
    for s in sizes:
        out.append(_casual_join(units[i:i + s]))
        i += s
    return out


def _break_units(text: str) -> list[str]:
    """Every candidate break in `text`, finest-grained: the model's own line breaks,
    then commas / sentence boundaries / dash and (for a long chunk) emoji / WH-word,
    with extra '?' de-marked.

    ONE definition, because both callers need the identical decomposition and only
    disagree about how far to re-merge it — style mode groups to a rolled target,
    the one-bubble return joins all the way down to a single line. Written twice, a
    later step added to one path would silently not exist in the other, and the path
    that diverged would be the return-from-silence one: the hardest to spot in
    production and the one this whole change exists to get right."""
    units: list[str] = []
    for line in text.split("\n"):
        units.extend(_split_units(line))
    return _cap_one_question(_merge_orphans(units))


# Per-reply split STRATEGY — a randomiser so replies don't all chop the same way:
#   length : bubble count tracks word count (the sweet spot; see _target_bubbles).
#   clause : split at (nearly) every comma / clause — a rapid multi-text burst.
#   terse  : one or two bubbles — a short, clipped reply.
# Weighted toward `length`; `clause`/`terse` add variety. Seeded per reply (off the
# text) so a given reply is stable, but different replies vary.
_SPLIT_STRATEGIES = ("length", "clause", "terse")
_SPLIT_WEIGHTS = (58, 22, 20)


def _strategy_target(parts: list[str], max_bubbles: int, rng) -> int:
    """Roll a split strategy and return the bubble-count target for it (clamped to
    [1, min(max_bubbles, len(parts))] — never invents a break, never drops one)."""
    n = max(1, len(parts))
    strat = rng.choices(_SPLIT_STRATEGIES, weights=_SPLIT_WEIGHTS)[0]
    if strat == "clause":                 # split at (nearly) every clause/comma
        target = n
    elif strat == "terse":                # a short, clipped reply
        target = min(2, n)
    else:                                 # length: count tracks word count (default)
        target = _target_bubbles(sum(len(p.split()) for p in parts))
    return max(1, min(target, max_bubbles, n))


def _split_sentences(text: str, max_bubbles: int) -> list[str]:
    """One line → bubbles (see _split_units), capped at max_bubbles (overflow merges
    into the last; nothing dropped). The single-line entry point used in tests;
    split_for_bubbles walks newline-separated lines through _split_units directly."""
    return _cap_merge(_merge_orphans(_split_units(text)), max_bubbles)


_QMARK_TAIL_RE = re.compile(r"\s*\?+\s*$")


def _cap_one_question(parts: list[str]) -> list[str]:
    """At most ONE question MARK across the bubbles — two '?' in a reply is a bot
    tell ('whats ur job? u gonna spill?'). Keep the '?' on the LAST question bubble
    (usually the real ask) and strip it from any earlier question bubble. NEVER drop
    a bubble — that loses the message: 'oh yeah? ... how old r u?' keeps both bubbles,
    only the last stays a question ('oh yeah' / '... how old r u?')."""
    q_idx = [i for i, p in enumerate(parts) if p.rstrip().endswith("?")]
    if len(q_idx) <= 1:
        return parts
    keep = q_idx[-1]
    return [(_QMARK_TAIL_RE.sub("", p) if (i in q_idx and i != keep) else p)
            for i, p in enumerate(parts)]


def _react_token(s: str) -> str | None:
    """The normalized leading reaction word of a bubble, or None if it doesn't open
    with one. Repeated letters collapse so 'oof'/'oooof' and 'lol'/'lolll' map
    together (so we catch the same opener even when the model stretches it)."""
    m = _REACT_WORD_RE.match((s or "").strip())
    if not m:
        return None
    return re.sub(r"(.)\1+", r"\1", m.group(1).lower())


def _dedupe_lead_reaction(parts: list[str], recent_out: list[str]) -> list[str]:
    """Kill the 'oof every message' tell: if this reply opens with the same reaction
    word the bot just used in its last couple of sends, drop that lead — either the
    standalone reaction bubble, or the leading word when it's fused into one line.
    Never empties the reply (a lone reaction with nothing after is left alone)."""
    if not parts:
        return parts
    recent = {t for b in recent_out[-3:] if (t := _react_token(b))}
    if not recent:
        return parts
    tok = _react_token(parts[0])
    if not tok or tok not in recent:
        return parts
    if len(parts) > 1:
        return parts[1:]                              # drop the standalone "oof"
    m = _LEAD_REACT_RE.match(parts[0].strip())        # fused → strip just the opener
    rest = parts[0].strip()[m.end():].strip() if m else ""
    return [rest] if rest else parts


def split_for_bubbles(text: str, max_bubbles: int = 2, rng=None,
                      force_single: bool = False) -> list[str]:
    """Make one generated reply read like real texting, and NO em-dash ever survives
    (every return path runs _strip_dash). Content is NEVER dropped:

      • style mode (max_bubbles ≥ 3) → walk the model's OWN line breaks, then split
        each line on commas + sentence boundaries + dash + (for a long chunk) emoji /
        WH word. A per-reply STRATEGY randomiser (_strategy_target) then picks the
        bubble count — length-based / split-every-clause / terse — so replies don't
        all chop the same way.
      • non-style (cap 2) → the model's two-line style, else a single dash / a
        MID-LINE emoji break (2/3 of the time), else a trailing-emoji drop (1/3).

    EVERY random draw on both paths goes through `rng`, so passing one seeded off
    the reply (the senders use `Random(f"split:{fan_id}:{raw}")`) makes the split
    stable — the same draft re-run after a retry bubbles the same way.
    """
    _rng = rng if rng is not None else random
    text = text.strip()
    # ── ONE BUBBLE, whatever the reply weighs. The caller sets this when she is
    # answering after a real silence: measured against the same accounts' human
    # chatters, a human returns single-bubble ~64% of the time at EVERY gap length
    # from two minutes to two days — flat — while ours goes the other way, 31.9%
    # single at <2min falling to 14.7% at 30min-2h. The longer we had been quiet the
    # more we said on arrival, which is a compounding tell: the gap reads as a person
    # and the wall of text that ends it reads as a queue being drained.
    #
    # Deliberately NOT `max_bubbles=1`: that would fall out of style mode into the
    # non-style path, whose `[:max_bubbles]` TRUNCATES and would drop content. This
    # merges instead — `_group_to_target(..., 1)` casually joins every unit, so a
    # one-bubble reply says everything the multi-bubble one would have.
    if force_single and text:
        units = _break_units(text)
        return [_strip_dash(_casual_join(units) if units else text)]
    if max_bubbles >= 3:                         # STYLE MODE
        parts = _break_units(text)
        parts = _group_to_target(parts, _strategy_target(parts, max_bubbles, _rng))
        if parts:
            return [_strip_dash(p) for p in parts]
    if "\n" in text:                            # non-style: the model's two-line style
        parts = [p.strip() for p in text.split("\n") if p.strip()][:max_bubbles]
        return [_strip_dash(p) for p in parts] or [_strip_dash(text)]
    dm = _DASH_RE.search(text)
    if dm:
        before, after = text[:dm.start()].strip(), text[dm.end():].strip()
        if before and after:
            return [_strip_dash(before), _strip_dash(after)]
    if _rng.random() < (2.0 / 3.0):
        for m in _EMOJI_RE.finditer(text):
            after = text[m.end():].strip()
            if not after:                       # trailing emoji → not a mid-break
                continue
            before = text[:m.end()].strip()     # keep the emoji on bubble 1…
            if _rng.random() < 0.5:
                before = text[:m.start()].strip()   # …but drop it half the time
            if before:
                return [_strip_dash(before), _strip_dash(after)]
    if _rng.random() < (1.0 / 3.0):
        stripped = _TRAIL_EMOJI_RE.sub("", text).strip()
        if stripped and stripped != text:
            return [_strip_dash(stripped)]
    return [_strip_dash(text)]


_ECHO_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm_echo(s: str) -> str:
    return _ECHO_NORM_RE.sub("", (s or "").lower())


def _looks_like_echo(part: str, last_in: str) -> bool:
    """True if `part` just parrots the fan's last message (verbatim or near-so).
    A small-model degeneracy the humanizer can trigger ('FAN: x' → 'YOU: x'). The
    12-char floor keeps legit short reactions (lol / haha / u up) from tripping."""
    a, b = _norm_echo(part), _norm_echo(last_in)
    if len(a) < 12 or len(b) < 12:
        return False
    if a == b:
        return True
    lo, hi = (a, b) if len(a) <= len(b) else (b, a)
    return lo in hi and len(lo) / len(hi) >= 0.7


_HTML_OPEN = "<"
_TAG_RE = re.compile(r"<[^>]+>")


# ── Text helpers (local copies — house pattern) ──────────────────────

def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    if _HTML_OPEN not in s:
        return s.strip()
    return _TAG_RE.sub("", s).strip()


def _history_text(direction: str, body: str | None, image_desc: str | None) -> str:
    """One message row → the history line the reply-LLM reads. Canonical for BOTH
    _gather builders. Inbound media we described at ingest
    rides in as "[he sent: …]" so the AI can rate / react to it — and so a media-only
    DM (empty body) stops being an invisible blank turn.

    The tag says "he sent", not "photo he sent": the same column also carries the
    free Giphy read ("an animated gif: …"), and naming the medium twice is how the
    bot ends up calling a reaction gif a nice pic. The description itself says what
    the thing is."""
    text = _strip_html(body)[:_MSG_CLIP]
    if direction == "in" and image_desc:
        tag = f"[he sent: {image_desc}]"
        text = f"{text} {tag}" if text else tag
    return text
