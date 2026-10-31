"""Text predicates/strippers, word tokenizing, bot-accusation detector."""
from __future__ import annotations

import re


# ── Canonical "does this column carry signal" predicate ───────────────
# Promoted here from welcome_chatter_for_info (its 50 call sites keep working via a re-export)
# so the shared layer owns it: it is a general predicate over nullable text/JSON
# columns, not an welcome_chatter_for_info concept, and _persona needs it too. Adding a second
# near-identical helper instead of promoting this one was the original mistake.
def nonempty(v) -> bool:
    """True when a column carries real signal (not '', not '[]'/'{}')."""
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip()
        return bool(s) and s not in ("[]", "{}")
    return bool(v)


# Emoji (with optional variation selector / ZWJ / regional-indicator) stripper —
# the model ignores a "no emojis" prompt and its emoji PLACEMENT is itself a dead
# LLM tell, so when the account opts in we remove emojis IN CODE at the send
# chokepoint. Targets the emoji unicode blocks only — NOT general punctuation, so
# an em-dash "—" or apostrophe survives. Collapses any double space left behind.
_EMOJI_STRIP_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0001F1E6-\U0001F1FF‍♀♂]+"
)
_EMOJI_WS_RE = re.compile(r"[ \t]{2,}")


def strip_emojis(s: str) -> str:
    """Remove emojis and tidy the spacing they leave behind. Keeps em-dashes and
    apostrophes (only the emoji unicode blocks are targeted)."""
    return _EMOJI_WS_RE.sub(" ", _EMOJI_STRIP_RE.sub("", s or "")).strip()


def has_emoji(s: str) -> bool:
    """Does this text carry an emoji? The exact complement of `strip_emojis` —
    same pattern, so the two can never disagree about what an emoji is.

    Lives HERE rather than next to its caller (`pacing.bubble_pace`, which charges
    emoji-picking time) precisely so there is one definition: a second copy of the
    class would eventually charge for a character the send path had already
    removed, or skip one it kept."""
    return bool(_EMOJI_STRIP_RE.search(s or ""))


# Inverted Spanish punctuation ("¿", "¡") — correct ORTHOGRAPHY, wrong REGISTER.
# Casual native texters drop the openers and just close with ?/! ("y cuando vas
# a grabar...?"), so a model "¿Y cuándo...?" reads edited/proper — a bot tell in
# a DM. The model always emits them (trained on edited prose) and ignores a
# prompt not to, so — like emojis — remove IN CODE. Unconditional, no toggle:
# deleting the opener can never change meaning (the closing ?/! carries it), and
# the chars never occur in en/sl output, so outside the es lane the fast path
# below makes this a byte-for-byte no-op. Rides inside apply_word_restriction
# (both variants) — the one last-mile pass every sender already runs — so no
# per-sender wiring and future senders inherit it.

def strip_inverted_punct(s: str) -> str:
    """Drop inverted ¿/¡ and tidy any double space left behind ("hola ¿ como" →
    "hola como"). Text without the chars passes through byte-identical."""
    if not s or ("¿" not in s and "¡" not in s):
        return s or ""
    return _EMOJI_WS_RE.sub(" ", s.replace("¿", "").replace("¡", "")).strip()


def is_substantive_msg(text: str | None) -> bool:
    """True if an inbound carries real conversational content — at least one
    alphanumeric char once emoji are stripped. Pure reactions ('😍', '🔥🔥', '...')
    are NOT a real message turn: they must not burn a slot toward welcome_chatter_for_info's
    runaway cap (_MAX_FAN_MESSAGES) nor inflate gen_info's message_count_at_gen
    (the profile-staleness baseline). welcome_chatter_for_info AND gen_info both call this so the
    cap-count and the staleness baseline use ONE convention. Pass HTML-STRIPPED
    text (the '<p>' tags are alnum and would falsely read as content)."""
    return bool(text) and any(ch.isalnum() for ch in _EMOJI_STRIP_RE.sub("", text))


# Word tokenizing shared by the typo + non-native layers.
_WORD_RE = re.compile(r"[A-Za-z]+")
_TYPO_EDGE_PUNCT = ".,!?;:\"'()*"  # stripped from a token's edges before the alpha check


# ── "Are you a bot?" accusation detector (§6.4) ───────────────────────
# Built from the 74 REAL accusations in the paying-fan archive ("u a bot or
# sumthing? lol", "Heyy are you real or a chatbot or ai", "Do you have a bot talking
# for you or something", "Are you real?", "is this really you? or a bot?", "which
# bot", "what bot do you use"). A FALSE positive silences a live chat. Two tiers,
# deliberately:
#   • HARD — the literal words 'bot' / 'chatbot' are an identity accusation FULL STOP,
#     even if the same message also talks about a photo. Nothing else means 'bot'.
#   • IDENTITY — softer tells ('are you real', 'real person', 'is this really you',
#     'is this ai') that a fan ALSO uses to complain about an AI-GENERATED PHOTO. These
#     fire only when the message is NOT about a pic/photo/image (the guard below).
# 'real' is only ever a trigger when paired with you/u/person/or — never bare — so
# "keeping it real" and the RELATIONSHIP sense "are you really into me" (\breal\b never
# matches "really") can't arm it. Pure, no DB.
_BOT_HARD_RE = re.compile(r"\b(?:chat\s?)?bots?\b", re.I)
_BOT_IDENTITY_RE = re.compile(
    r"\b(?:are|r)\s+(?:you|u)\s+(?:a\s+)?real\b"        # are you real / r u real
    r"|\b(?:you|u|ur)\s+(?:a\s+)?real\b"               # u a real / you real
    r"|\breal\s+person\b"                               # a real person
    r"|\breal\s+or\b"                                   # real or (a bot/ai)
    r"|\bfor\s+real\s+or\b"                             # for real or fake
    r"|\bis\s+(?:this|it)\s+really\s+you\b"            # is this really you
    r"|\bwho\s+is\s+this\s+really\b"                   # who is this really
    r"|\b(?:are|r)\s+(?:you|u)\s+a\.?\s?i\.?\b"        # are you ai
    r"|\bis\s+(?:this|it)\s+(?:a\s+)?a\.?\s?i\.?\b"    # is this ai / is this a ai
    # "human" — the whole other half of how fans ask this, and the regex was deaf to
    # every one of them. A prod thread ran "wait are you human?" past the detector as
    # ordinary chat: no brush-off, no one-line cap, `bot_accusations: 0`, and a $3
    # paywall went out on the answer. `\bhuman\b` (not `humans?`) keeps "you humans" out.
    #
    # ⚠️ ADJACENCY IS NOT ENOUGH, and an earlier version of this comment claimed it was.
    # The sympathy sense puts the pronoun RIGHT NEXT to the word just as often as the
    # accusation does — "that just makes you human", "and ya should be, means ur human"
    # — so a bare `(?:you|u|ur)\s+human` alternative fires on reassurance and hands the
    # fan a brush-off plus a `seller_off` turn for being kind. The accusation always
    # carries a FRAME: a question word, or a negation. Match the frame, not the pair.
    # One optional intensifier is allowed between, because "are you EVEN human" and
    # "so ur NOT human then" are the sharpest forms of the ask, not edge cases.
    r"|\b(?:are|r|is)\s+(?:you|u|this|it)\s+"
    r"(?:even\s+|actually\s+|really\s+|genuinely\s+|not\s+)?"
    r"(?:an?\s+)?(?:real\s+)?human\b"                  # are you (even) (a real) human
    r"|\b(?:you|u|ur|youre|you're)\s+not\s+(?:an?\s+)?(?:real\s+)?human\b"  # ur not human
    # Bare "u human?" — the pronoun pair WITHOUT a question word, which is the shape
    # the sympathy sense also takes. What separates them is position: the accusation
    # OPENS the message ("u human?", "wait ur human right?"), the reassurance is buried
    # inside one ("that just makes you human"). Anchored to the start, past a filler.
    # …and it has to END there too. "youre human babe it happens" and "ur a human
    # being like the rest of us" both OPEN with the pair and are both reassurance, so
    # position alone is not enough either — the accusation is the whole message.
    r"|^\W*(?:wait\s+|so\s+|ok\s+|but\s+|hey\s+)*"
    r"(?:you|u|ur|youre|you're)\s+(?:an?\s+)?(?:real\s+)?human"
    r"(?!\s+being)\b(?:\s+right)?\s*\??\s*$"
    r"|^\s*human\??\s*$"                              # "human?" as the whole message
    # The conversation itself, in the first person. Without the "am i / are we / is
    # this" anchor this matched a fan narrating his day — "i was talking to a human at
    # the bank all day" is small talk, not an accusation.
    r"|\b(?:am\s+i|are\s+we|is\s+this)\s+(?:even\s+|actually\s+|really\s+)?"
    r"(?:\w+\s+){0,2}?(?:talking|chatting|texting|speaking|typing)\s+(?:to|with)\s+"
    r"(?:an?\s+)?(?:real\s+)?human\b"
    # …and the elliptical form, where he drops the "am i". Anchored for the same
    # reason: at the start it is the question, buried in a sentence it is his day.
    r"|^\W*(?:talking|chatting|texting|speaking|typing)\s+(?:to|with)\s+"
    r"(?:an?\s+)?(?:real\s+)?human\b"
    r"|\bhuman\s+(?:typing|behind|answering|writing|replying)\b",  # a human typing this
    re.I,
)
# When ONLY the softer identity tell fires, a pic/photo/image word means he's talking
# about the CONTENT looking AI-made, not accusing HER of being a bot — don't fire.
_BOT_PHOTO_CTX_RE = re.compile(
    r"\b(?:pic|pics|picture|pictures|photo|photos|image|images|selfie|selfies)\b", re.I)
# Exposed union (hard | identity) for callers/tests that want the raw matcher; the
# photo guard lives in detect_bot_accusation, not in the regex.
BOT_ACCUSED_RE = re.compile(
    _BOT_HARD_RE.pattern + "|" + _BOT_IDENTITY_RE.pattern, re.I)


def detect_bot_accusation(text: str | None) -> bool:
    """True when an inbound accuses HER of being a bot / not a real person (§6.4).
    'bot'/'chatbot' always fire; the softer 'are you real'/'is this ai' tells fire
    only when the message isn't about an AI-generated PHOTO. Never fires on the
    relationship sense ('are you really into me'). Pure, no DB."""
    if not text:
        return False
    if _BOT_HARD_RE.search(text):
        return True                       # 'bot'/'chatbot' — identity, always
    if _BOT_PHOTO_CTX_RE.search(text):
        return False                      # 'this pic looks ai' / 'is that photo real'
    return bool(_BOT_IDENTITY_RE.search(text))
