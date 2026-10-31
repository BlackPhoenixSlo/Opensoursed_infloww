"""Non-native English style layer (pure)."""
from __future__ import annotations

import re

from ._textutil import _TYPO_EDGE_PUNCT, _WORD_RE


# ── "Non-native English" style layer (opt-in, deterministic) ──────────
# A non-native speaker misspells the SAME word the SAME way EVERY time — a
# consistent fingerprint, NOT a random thumb-slip (humanize_typos). So this layer is
# applied ALWAYS when the flag is on, never rate-gated. And
# it MUST be code-level: prompt-only misspellings are ignored / "fixed" by the model.
#
# Entries are REAL observed misspellings, not invented — expand from real captures.
# Same PROTECT rules as humanize_typos: never touch a token carrying a digit, an
# @handle, a link, a '$', an emoji, or a protected name. Only the alpha core of a
# token is swapped; surrounding punctuation/spacing is preserved.
NONNATIVE_MISSPELLINGS = {
    "definitely": "deffinetly",
    "gonna": "conna",
    "official": "oficial",
    "alone": "aloane",
    "theirs": "thers",
    "subscription": "subscribtion",
    "telegram": "tegelgram",
    # Harvested from Sophiepaid's own sent messages (2026-07-25): every misspelling
    # below is one she repeats verbatim across separate conversations, which is
    # exactly the fingerprint this layer wants — not a one-off thumb slip.
    #   'beautifull' ×3  "Its so beautifull , expensive but beautifull"
    #   'hiw'        ×3  "Hiw long do you want?" / "Hiw are u today ?"
    # Fire rate matters here — this layer is deterministic, so a common word would
    # read as a tic rather than a fingerprint. Measured over 32,392 bot sends
    # (07-18→07-25): 'how' 2.4%, 'beautiful' 0.01% (vs 'gonna' 0.5% today). One in
    # ~42 messages carrying 'hiw' is the intended texture; anything much denser
    # would need a rate gate instead of a dict entry.
    "beautiful": "beautifull",
    "how": "hiw",
    # "then" -> "than" is CONTEXT-RISKY (it would corrupt real "than"); left OUT.
    # 'switterland' (Switzerland ×2) is hers too but a proper noun the copy never
    # emits on its own, so it would only ever fire by coincidence — left OUT.
}
# Multi-word phrases (applied before the single-word pass).
NONNATIVE_PHRASES = {
    "of course": "ofcoas",
}
# Every misspelled OUTPUT form — pass to humanize_typos' `protect` so the thumb-typo
# pass never re-mangles a word this layer already mangled (no double-corruption).
NONNATIVE_OUTPUTS = tuple(NONNATIVE_MISSPELLINGS.values()) + tuple(NONNATIVE_PHRASES.values())
_NONNATIVE_PHRASE_RES = tuple(
    (re.compile(rf"\b{re.escape(p)}\b", re.I), r) for p, r in NONNATIVE_PHRASES.items()
)


def _match_case(src: str, repl: str) -> str:
    """Carry `src`'s casing onto `repl` (the voice is lowercase, but be safe)."""
    if src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl.capitalize()
    return repl


# A space before '?' — "Do you like it ?" — is the loudest habit in the creator's
# own sent messages, and one the bot has never once produced: measured 2026-07-25
# over Sophiepaid's outbound, 187 of her 728 question-carrying messages have it
# against 0 of 3,336 bot sends. Unlike the misspelling dict this is NOT applied
# every time — she does it on about a QUARTER of her questions, and always-on
# would read as a broken keyboard rather than a habit. So it rolls per '?' run
# against the caller's seeded rng (same seed as the thumb-typo pass → the same
# reply always renders the same way).
#
# Not universal across creators: Nora's 106 question messages have zero. It
# rides the per-account non-native flag for that reason.
_NONNATIVE_SPACE_Q_RATE = 0.26
_Q_RUN_RE = re.compile(r"(?<=[^\W\d_])(\?+)")
# Tokens that must never be touched — a '?' inside one is query-string syntax or
# part of a handle, not punctuation. Mirrors the typo pass's protect intent.
_Q_SKIP_MARKERS = ("@", "/", "$", "http", "www", ".com")


def apply_nonnative_spacing(text: str, rng, *, rate: float = _NONNATIVE_SPACE_Q_RATE) -> str:
    """Sometimes detach a '?' from the word before it ("Do you like it ?").

    Rolls independently per question-mark RUN so "u sure??" stays one unit rather
    than splitting into "? ?". A run is only eligible when the character before it
    is a LETTER, and the whole whitespace-token is skipped when it carries a
    link/handle/price marker — that keeps 'onlyfans.com/x?y=1' intact.

    `rng` is the caller's seeded Random and MUST be shared across the bubbles of
    one reply — pass the same object, not a fresh Random per bubble. Re-seeding
    per bubble replays the same roll for each, so every '?' in the reply agrees
    and a 3-bubble answer renders "you like it ? really ? u sure ?" — the broken
    keyboard this rate exists to avoid. Same reason `humanize_typos` takes the
    rng from its caller rather than minting one."""
    if not text or "?" not in text or rate <= 0:
        return text
    out = []
    for tok in re.split(r"(\s+)", text):
        if not tok or tok.isspace() or any(mk in tok.lower() for mk in _Q_SKIP_MARKERS):
            out.append(tok)
            continue
        out.append(_Q_RUN_RE.sub(
            lambda m: (" " + m.group(1)) if rng.random() < rate else m.group(1), tok))
    return "".join(out)


def apply_nonnative_style(text: str, *, protect=()) -> str:
    """Deterministically swap known words for their non-native misspelling at word
    boundaries (case-insensitive). Pure + reversible (nothing persisted); empty input
    returns input. Protected: a token with a digit / @handle / link / '$' / emoji, a
    non-alpha core, or a name in `protect` is never touched.

    The occasional space-before-'?' habit is a SEPARATE, rng-driven step
    (`apply_nonnative_spacing`) the senders apply after this one — keeping it out
    of here is what lets this function stay deterministic, as its name promises."""
    if not text:
        return text
    protect_set = {w.lower() for name in protect for w in _WORD_RE.findall(str(name))}
    for rx, repl in _NONNATIVE_PHRASE_RES:            # multi-word phrases first
        text = rx.sub(lambda m: _match_case(m.group(), repl), text)
    out = []
    for tok in re.split(r"(\s+)", text):             # keep whitespace runs intact
        if not tok or tok.isspace():
            out.append(tok)
            continue
        core = tok.strip(_TYPO_EDGE_PUNCT)
        repl = NONNATIVE_MISSPELLINGS.get(core.lower())
        if repl is None or not core.isalpha() or core.lower() in protect_set:
            out.append(tok)                          # unknown / unsafe / protected
            continue
        lead = len(tok) - len(tok.lstrip(_TYPO_EDGE_PUNCT))
        out.append(tok[:lead] + _match_case(core, repl) + tok[lead + len(core):])
    return "".join(out)


# Thin prompt block — ONLY the broken grammar a dict can't do (the dict GUARANTEES
# the signature misspellings; this just SETS THE REGISTER). Gated by the same flag.
NONNATIVE_REGISTER = (
    "non-native english — sometimes drop a tiny word (a, the, is), never "
    "cartoonish."
)
