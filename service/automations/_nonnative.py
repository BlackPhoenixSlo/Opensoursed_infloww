from __future__ import annotations

import re

from ._textutil import _TYPO_EDGE_PUNCT, _WORD_RE


NONNATIVE_MISSPELLINGS = {
    "definitely": "deffinetly",
    "gonna": "conna",
    "official": "oficial",
    "alone": "aloane",
    "theirs": "thers",
    "subscription": "subscribtion",
    "telegram": "tegelgram",
    "beautiful": "beautifull",
    "how": "hiw",
}
NONNATIVE_PHRASES = {
    "of course": "ofcoas",
}
NONNATIVE_OUTPUTS = tuple(NONNATIVE_MISSPELLINGS.values()) + tuple(NONNATIVE_PHRASES.values())
_NONNATIVE_PHRASE_RES = tuple(
    (re.compile(rf"\b{re.escape(p)}\b", re.I), r) for p, r in NONNATIVE_PHRASES.items()
)


def _match_case(src: str, repl: str) -> str:
    if src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl.capitalize()
    return repl


# Rolled per '?' run (about a quarter of the creator's questions); always-on reads as a broken keyboard.
_NONNATIVE_SPACE_Q_RATE = 0.26
_Q_RUN_RE = re.compile(r"(?<=[^\W\d_])(\?+)")
_Q_SKIP_MARKERS = ("@", "/", "$", "http", "www", ".com")


# rng must be shared across a reply's bubbles; a fresh seed per bubble makes every '?' agree.
def apply_nonnative_spacing(text: str, rng, *, rate: float = _NONNATIVE_SPACE_Q_RATE) -> str:
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


# Deterministic, never rate-gated (same word misspelled the same way every time); in code because the model ignores or 'fixes' prompt-only misspellings.
def apply_nonnative_style(text: str, *, protect=()) -> str:
    if not text:
        return text
    protect_set = {w.lower() for name in protect for w in _WORD_RE.findall(str(name))}
    for rx, repl in _NONNATIVE_PHRASE_RES:
        text = rx.sub(lambda m: _match_case(m.group(), repl), text)
    out = []
    for tok in re.split(r"(\s+)", text):
        if not tok or tok.isspace():
            out.append(tok)
            continue
        core = tok.strip(_TYPO_EDGE_PUNCT)
        repl = NONNATIVE_MISSPELLINGS.get(core.lower())
        if repl is None or not core.isalpha() or core.lower() in protect_set:
            out.append(tok)
            continue
        lead = len(tok) - len(tok.lstrip(_TYPO_EDGE_PUNCT))
        out.append(tok[:lead] + _match_case(core, repl) + tok[lead + len(core):])
    return "".join(out)


NONNATIVE_REGISTER = (
    "non-native english — sometimes drop a tiny word (a, the, is), never "
    "cartoonish."
)
