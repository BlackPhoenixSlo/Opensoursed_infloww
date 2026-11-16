"""service/automations/_markers.py — the shapes a fan must never see in a draft.

Two of them, both written as `*...*` often enough to share this module: the
PROTOCOL markers the model is told to emit, and the stage directions it emits
although it is told not to. Each has its own regex; what they share is that both
shapes are recognised HERE and stripped by the callers, and neither is ever sent.

── the protocol markers ──

Both chat protocols hide an instruction in the reply text: `STICKER: <tag>` for
the cat pack, `>>OFFER <id>` for the 1:1 offer engine. Each says "end your reply
with a line that is exactly this", each is stripped before the fan sees it, and
each used to be matched with its own line-anchored regex.

A prod audit (07-27, every outbound body that ever contained either keyword)
found the model does not comply, and that BOTH protocols had leaked to fans:

    *sticker: flirty*                                    dressed as an emote
    ...best place u been to in ktown? STICKER: flirty     inline after real text
    i dare ya 😏, OFFER 20                                arrows dropped

None of those START a line, so neither engine's regex caught any of them. This
module is the one place that shape is written down. A pure leaf — `re` and
nothing else — so the leaf modules that need it stay leaves.
"""
from __future__ import annotations

import re

# Markdown/roleplay dressing the model wraps a marker in: *sticker: flirty*,
# **STICKER: shy**, [sticker: sleepy].
_WRAP = r"[*_~`\"'()\[\]{}]*"
# The keyword boundary `protocol_marker_re` documents: no letter before, or a camelCase seam.
_BOUND = r"(?:(?<![A-Za-z])|(?-i:(?<=[a-z])(?=[A-Z])))"


def protocol_marker_re(keyword: str) -> re.Pattern[str]:
    """Matcher for a `<keyword><payload>` marker, wherever the model put it.
    Group 1 is the payload tail, left for the caller to resolve.

    No line anchor, wrapper punctuation eaten, and a lookbehind rather than `\\b`
    so `_sticker:` matches while a word merely ENDING in the keyword
    (`unsticker:`) does not.

    Text BEFORE the marker survives; the marker itself runs to end of line. That
    split is straight off the audit: both leaks carried real fan-facing text
    AHEAD of the marker — a question to the fan, a dare — so the old whole-line
    strips would have deleted the message along with the protocol. Nothing has
    ever followed a marker on its line, because the protocol puts it last, so
    anything there is residue and goes.

    `keyword` carries the discrimination, and that is the CALLER's job: ordinary
    prose must not match it. Stickers lean on the colon ("you design stickers
    that make people obey" is a real fan-facing body). Offers need the arrows or
    a trailing id, because "well i usually offer 1k per custom vid" is also a
    real body — 636 outbound messages say "offer", and exactly one was a marker.

    The boundary is "no letter before" OR a camelCase seam. Live 2026-08-30, on
    your-host.example.com night one: the model glued its prose straight onto the marker —
    `...in quel letto robypartySTICKER: flirty` — and the letter-lookbehind
    refused the seam, so the fan read the protocol verbatim AND no sticker went
    out. The model writes the marker in caps as instructed even when it forgets
    the space, so a lowercase letter followed by the keyword in caps IS the
    marker; `unstickers:` in prose stays all-lowercase and still never matches.
    `(?-i:...)` scopes the case-sensitivity that seam needs away from the
    IGNORECASE the wrapper shapes still want.
    """
    return re.compile(
        rf"{_WRAP}{_BOUND}(?:{keyword})([^\n]*)",
        re.IGNORECASE | re.MULTILINE)


# The cat pack's keyword (`cat_stickers._MARKER_RE`): the COLON is its discriminator.
STICKER_KEYWORD = r"STICKERS?[ \t]*:"
_STICKER_RE = protocol_marker_re(STICKER_KEYWORD)

# ── the Asked marker (Full AI NEW-168) ──
#
# `ASKED: <id>` names the get-to-know fact her reply asked or led to. Unlike STICKER it is a
# word prose uses ("since u asked: im 24"), so the shape alone decides. Contract-shaped (caps
# `ASKED` anywhere, or `asked` in any case opening its own line, then a separator): a marker,
# and like every protocol marker it runs to end of line whatever follows (residue) — up to a
# STICKER marker after it on the line, which its own pass still needs. Anything else is a
# marker only when its value is a printed id or `none` ending the line: mid-line `asked` in
# any case with a separator; or caps / line-opening `asked` with no separator.
_ASK_SEP = r"[ \t]*[:=\-–—]"
_EOL = r"(?![\w])[^\w\n]*$"
_VALUE = re.compile(rf"[ \t]*{_WRAP}[ \t]*(\w*)")


def _asked_re(ids: frozenset[str]) -> re.Pattern[str]:
    known = "|".join(re.escape(k) for k in sorted({"none", *ids}, key=len, reverse=True))
    caps = protocol_marker_re(rf"(?-i:ASKED){_WRAP}{_ASK_SEP}").pattern
    opens = rf"^[ \t]*{_WRAP}asked{_WRAP}{_ASK_SEP}([^\n]*)"
    sep = rf"{_WRAP}{_BOUND}asked{_WRAP}{_ASK_SEP}[ \t]*{_WRAP}[ \t]*({known}){_EOL}"
    bare = (rf"(?:^[ \t]*{_WRAP}asked|{_WRAP}{_BOUND}(?-i:ASKED)){_WRAP}[ \t]+{_WRAP}[ \t]*"
            rf"({known}){_EOL}")
    return re.compile(rf"[ \t]*(?:{caps}|{opens}|{sep}|{bare})", re.IGNORECASE | re.MULTILINE)


def strip_asked(text: str, ids: frozenset[str]) -> tuple[str, list[str]]:
    """`text` without every Asked marker and every printed `[id]` echo (`ids`), and each
    marker's value as written in order: its first word ("" for none). Only a marker's line
    changes; `text` comes back as it was when there is nothing to strip. Pure."""
    values: list[str] = []

    def cut(m: re.Match[str]) -> str:
        tail = m.group(1) if m.group(1) is not None else m.group(2)
        if tail is None:                                # a printed id / none ending the line
            values.append(m.group(3) if m.group(3) is not None else m.group(4))
            return ""
        values.append(_VALUE.match(tail).group(1))
        s = _STICKER_RE.search(tail)                    # its own pass reads it later
        if s:
            return tail[len(tail[:s.start()].rstrip()):]
        return ""

    out, n = _asked_re(ids).subn(cut, text or "")
    if ids:
        echo = "|".join(re.escape(k) for k in ids)
        out, e = re.subn(rf"^[ \t]*\[(?:{echo})\][ \t]*|[ \t]*\[(?:{echo})\]", "", out,
                         flags=re.IGNORECASE | re.MULTILINE)
        n += e
    return (out.strip(), values) if n else (text, [])


# A `*...*` span PLUS whatever separates it from the next word: group 1 is the
# inside, group 2 the trailing comma/space. Non-greedy and newline-bounded so two
# emotes on two lines never merge into one span that eats the real text between.
#
# Group 2 is what keeps this small. A deleted span used to leave its own
# punctuation behind (`*yawns*, maybe…` → `, maybe…`), and that was repaired
# afterwards by a leading-punctuation strip and a double-space collapse — two
# rules cleaning up at a distance, one of which needed MULTILINE to work per line
# and shipped `, u up?` to a fan when it didn't have it. A deletion that takes its
# own separator with it cannot leave a mess to clean, so both rules are gone —
# and with no cleanup pass, nothing can touch a space BEFORE punctuation, which
# is how `thoughtful ?` survives. That spacing is deliberate house style.
#
# Named for the SHAPE, not for either caller's meaning. Private: the group layout
# exists for the cut-with-separator trick below, so nothing outside this module
# should depend on it — callers ask `bare_star_span` instead.
_STAR_SPAN_RE = re.compile(r"\*\s*([^*\n]+?)\s*\*([ \t]*[,;:]?[ \t]*)")
# The one-word spans that are an ACTION rather than emphasis. Not a guess: prod
# really sent `*laughs* anything goes huh?` and `*blushes* damn papi u really
# know`, and word count alone unwraps those into "laughs anything goes huh?".
# Short on purpose — English only, and only the reflex verbs a chat model reaches
# for. Every inline span in the corpus that ISN'T one of these is a function word
# (`*and*`, `*my*`, `*vos*`), so growing this list can only start eating real
# emphasis, which is the more expensive mistake.
#
# `stretch`/`yawn`/`snap`/`squeeze` are here on softer evidence than the rest: the
# corpus has them only inside PHRASE spans (`*stretch and yawn as i read that*`,
# `*snaps fingers*`), which word count already deletes. They are in the list
# because the model demonstrably reaches for those verbs and a one-word form
# unwraps into nonsense ("hey yawns, u up?"), and because no one writes *yawns*
# for emphasis. That reasoning does NOT extend to a verb prod has never written.
_EMOTE_WORDS = frozenset(
    "wink winks giggle giggles blush blushes smirk smirks grin grins laugh "
    "laughs sigh sighs shrug shrugs moan moans pout pouts smile smiles "
    "nod nods stretch stretches yawn yawns snap snaps squeeze squeezes".split())


def bare_star_span(text: str) -> str | None:
    """The inside of a `*...*` that IS the whole message, else None — the one
    question both callers ask of the span shape. cat_stickers uses it to spot a
    reaction it owns a gif for; `strip_narration` to spot one it must drop."""
    m = _STAR_SPAN_RE.fullmatch((text or "").strip())
    return m.group(1) if m else None


def strip_narration(raw: str) -> str:
    """Model prose with every `*...*` stage direction removed — the house rule is
    that a real chatter never types one, and that saying NOTHING beats narrating
    (07-28). Returns "" when the emote WAS the message; no caller needs new
    plumbing for that, because an empty draft is already dropped rather than sent.

    Two rules, and the whole 104-body star corpus prod has ever sent decides both:

      the message IS the span   `*mischievous grin*`, `*love*`, `* se ríe por
                                dentro *`  ->  "" — a reaction, not a sentence
      a span inside a line      a PHRASE is narration and goes (`*stretch and
                                yawn as i read that*, maybe i make you beg`
                                keeps the real line); one word is emphasis, so
                                only its stars go (`confident *and* thoughtful`)
                                — unless the word is an emote verb, `*laughs*`

    Word count carries the inline case because that is how the corpus actually
    splits: every inline emphasis span is one word (`*and*`, `*my*`, `*vos*`,
    `*dejas*`), every inline narration span is a phrase. A lone `*` can never
    match, so both the `*fix` typo beat and the `nude***` funnel template — 20+
    sends of operator-written copy — come back untouched without a special case.

    What this deliberately does NOT do: tell an emote from a real line by reading
    who is speaking in it. `*maybe i am*` and `*go on*` are real replies wrapped
    in stray stars, and they are dropped with the rest — 3 messages in two months,
    against a rule that already says silence beats narrating. A pronoun test
    ("is anyone talking inside the span?") bought exactly those 3 back and cost a
    bug on real operator copy, so it is gone.

    `_EMOTE_WORDS` above is NOT that rejected test and is not vestigial: it does a
    narrower job the word count cannot, deciding one-word INLINE spans, where the
    corpus really does contain `*laughs* anything goes huh?`. Delete it and that
    ships as "laughs anything goes huh?".
    """
    text = (raw or "").strip()
    if bare_star_span(text) is not None:    # the message was nothing but the emote
        return ""
    # A cut takes group 2 with it; an unwrap puts it back. See _STAR_SPAN_RE.
    return _STAR_SPAN_RE.sub(
        lambda m: "" if (" " in m.group(1)
                         or m.group(1).lower() in _EMOTE_WORDS)
        else m.group(1) + m.group(2), text).strip()


# A `(...)` aside plus the space before it. Live 2026-11-16 (Twin): a fan got
# `hey sweetie\n(Can't have a longer response here as per your instructions so
# I'll keep it to one line with no emoji as requested.)` — the model answering
# its prompt inside the reply. Owner: drop everything in brackets. Newline-bounded
# and un-nested like the star span. The two guards keep emoticons whole: `:(` /
# `(:` open no span and `:)` closes none, so `:( miss u :)` is left alone.
_ASIDE_RE = re.compile(r"[ \t]*(?<![:;=8xX])\((?![:;=])[^()\n]*(?<![:;=^-])\)")


def strip_asides(raw: str) -> str:
    """Model prose with every `(...)` aside removed; "" when the aside WAS the
    message (an empty draft is dropped, not sent). A line the cut emptied goes
    too, because every line downstream becomes its own bubble. A blank line the
    model wrote stays: it is the shape of a one-message text (a paid
    caption). The ends are stripped either way."""
    raw = raw or ""
    out: list[str] = []
    for ln in raw.split("\n"):
        kept = _ASIDE_RE.sub("", ln)
        if kept == ln:
            out.append(ln)
        elif kept.strip():
            out.append(kept.strip())
    text = "\n".join(out)
    if text != raw:     # a dropped line's two blank neighbours: one
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
