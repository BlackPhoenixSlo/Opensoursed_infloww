from __future__ import annotations

import re


def nonempty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip()
        return bool(s) and s not in ("[]", "{}")
    return bool(v)


EMOJI_CLASS = (
    "[\U0001F000-\U0001FAFF\u231a\u231b\u2328\u23cf\u23e9-\u23f3\u23f8-\u23fa\U00002600-\U000027BF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF]"
)
# The model ignores a no-emoji prompt, so emojis go in code; em-dash and apostrophe survive.
_EMOJI_STRIP_RE = re.compile(rf"(?:{EMOJI_CLASS}|[\ufe00-\ufe0f\u200d])+")
_EMOJI_WS_RE = re.compile(r"[ \t]{2,}")


def strip_emojis(s: str) -> str:
    return _EMOJI_WS_RE.sub(" ", _EMOJI_STRIP_RE.sub("", s or "")).strip()


def has_emoji(s: str) -> bool:
    return bool(_EMOJI_STRIP_RE.search(s or ""))



# Dropping the opener never changes meaning (the closing ?/! carries it); the model always emits them and ignores a prompt not to.
def strip_inverted_punct(s: str) -> str:
    if not s or ("¿" not in s and "¡" not in s):
        return s or ""
    return _EMOJI_WS_RE.sub(" ", s.replace("¿", "").replace("¡", "")).strip()


# Pure reactions must not burn a slot toward the runaway cap or inflate message_count_at_gen.
def is_substantive_msg(text: str | None) -> bool:
    return bool(text) and any(ch.isalnum() for ch in _EMOJI_STRIP_RE.sub("", text))


_WORD_RE = re.compile(r"[A-Za-z]+")
_TYPO_EDGE_PUNCT = ".,!?;:\"'()*"


# A false positive silences a live chat; soft identity tells skip when the fan is talking about an AI-looking photo.
_BOT_HARD_RE = re.compile(r"\b(?:chat\s?)?bots?\b", re.I)
_BOT_IDENTITY_RE = re.compile(
    r"\b(?:are|r)\s+(?:you|u)\s+(?:a\s+)?real\b"
    r"|\b(?:you|u|ur)\s+(?:a\s+)?real\b"
    r"|\breal\s+person\b"
    r"|\breal\s+or\b"
    r"|\bfor\s+real\s+or\b"
    r"|\bis\s+(?:this|it)\s+really\s+you\b"
    r"|\bwho\s+is\s+this\s+really\b"
    r"|\b(?:are|r)\s+(?:you|u)\s+a\.?\s?i\.?\b"
    r"|\bis\s+(?:this|it)\s+(?:a\s+)?a\.?\s?i\.?\b"
    # 'human' needs a question/negation frame: a bare pronoun pair also matches reassurance ('that makes you human').
    r"|\b(?:are|r|is)\s+(?:you|u|this|it)\s+"
    r"(?:even\s+|actually\s+|really\s+|genuinely\s+|not\s+)?"
    r"(?:an?\s+)?(?:real\s+)?human\b"
    r"|\b(?:you|u|ur|youre|you're)\s+not\s+(?:an?\s+)?(?:real\s+)?human\b"
    r"|^\W*(?:wait\s+|so\s+|ok\s+|but\s+|hey\s+)*"
    # Bare "u human?" must open and close the message: "youre human babe it happens" is reassurance.
    r"(?:you|u|ur|youre|you're)\s+(?:an?\s+)?(?:real\s+)?human"
    r"(?!\s+being)\b(?:\s+right)?\s*\??\s*$"
    r"|^\s*human\??\s*$"
    r"|\b(?:am\s+i|are\s+we|is\s+this)\s+(?:even\s+|actually\s+|really\s+)?"
    r"(?:\w+\s+){0,2}?(?:talking|chatting|texting|speaking|typing)\s+(?:to|with)\s+"
    r"(?:an?\s+)?(?:real\s+)?human\b"
    r"|^\W*(?:talking|chatting|texting|speaking|typing)\s+(?:to|with)\s+"
    r"(?:an?\s+)?(?:real\s+)?human\b"
    r"|\bhuman\s+(?:typing|behind|answering|writing|replying)\b",
    re.I,
)
_BOT_PHOTO_CTX_RE = re.compile(
    r"\b(?:pic|pics|picture|pictures|photo|photos|image|images|selfie|selfies)\b", re.I)
BOT_ACCUSED_RE = re.compile(
    _BOT_HARD_RE.pattern + "|" + _BOT_IDENTITY_RE.pattern, re.I)


def detect_bot_accusation(text: str | None) -> bool:
    if not text:
        return False
    if _BOT_HARD_RE.search(text):
        return True
    if _BOT_PHOTO_CTX_RE.search(text):
        return False
    return bool(_BOT_IDENTITY_RE.search(text))
