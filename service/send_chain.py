"""The send chain for one tool-written mass or post body (ultra ticket 13; docs/prompts/post-processing.md,
"Mass/post text from a plan").

One body, one Creator, no fan: the per-fan stages (bubble split, echo, lead dedupe, typos, pacing) do not
apply. Every stage reuses the chat chain's own function; nothing is re-implemented. What differs from the chat
chain is the verdict: a chat reply swaps a leak for a deflection, a plan's text is REFUSED instead, because the
owner approves the exact text and a silent rewrite would send words nobody saw.

`chain` is pure (the caller passes the Agency's words and the Creator's emoji flag); `run` loads both.
"""

from __future__ import annotations

from dataclasses import dataclass

from automations._markers import strip_narration
from automations._outbound_guard import apply_word_restriction, scan_offplatform
from automations._style_flags import load_strip_emojis
from automations._textutil import strip_emojis
from automations._wordfilter import banned_hit_summary, filter_banned, load_banned_words
from of_rich_text import of_plain


@dataclass(frozen=True)
class Verdict:
    """`text` is what may be sent (None when refused); `stage` + `detail` name the refusal."""
    text: str | None
    stage: str = ""
    detail: str = ""


def _refuse(stage: str, detail: str) -> Verdict:
    return Verdict(None, stage, detail)


def chain(raw: str, words: list[str], strip_emoji: bool) -> Verdict:
    """Transform (word restriction, emoji strip), then refuse (empty, narration, off-platform, banned word).

    Every refusal scan reads the raw text, the FINAL text and the final text as the fan reads it (`of_plain`,
    what the mass / post boundary's `of_text` leaves of markup), so neither a transform (`tele📱gram` with the
    emoji strip) nor markup (`tele<b>gram</b>`, `<b></b>`) can carry anything past a scan."""
    text = (raw or "").strip()
    if not text:
        return _refuse("empty", "the text is empty")
    final = apply_word_restriction(text)
    if strip_emoji:
        final = strip_emojis(final)
    final = final.strip()
    seen = of_plain(final).strip()
    if not final or not seen:
        return _refuse("empty", "nothing a fan would read is left (after the emoji strip or the markup)")
    forms = list(dict.fromkeys([text, final, seen]))
    if any(strip_narration(f).strip() != f.strip() for f in forms):
        return _refuse("narration", "the text has a *stage direction* (or *emphasis*); write it without stars")
    leaks = list(dict.fromkeys(label for f in forms for label in scan_offplatform(f)))
    if leaks:
        return _refuse("offplatform", "off-platform content: " + ", ".join(leaks))
    kept, hits = filter_banned(forms, words, "block")
    if kept is None:
        return _refuse("banned_words", "the Agency's sensitive words: " + ", ".join(banned_hit_summary(hits)))
    return Verdict(final)


async def run(raw: str, account_id: str) -> Verdict:
    """`chain` with the Creator's Agency word list and emoji flag loaded."""
    words, _mode = await load_banned_words(account_id)
    return chain(raw, words, await load_strip_emojis(account_id))
