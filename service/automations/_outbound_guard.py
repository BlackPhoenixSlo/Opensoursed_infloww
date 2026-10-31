"""Outbound word restriction + off-platform guard."""
from __future__ import annotations

import re

from . import _voice
from ._textutil import strip_inverted_punct


# ── Word restriction (port of V1 TgAiChattingShare/word_filter.py) ────
# OnlyFans soft-blocks / flags a fixed set of words; V1 doubled the first vowel of
# each ("meet" → "meeet", "rape" → "raape") so the copy reads naturally to the fan
# but slips the filter. Every outbound automation send should pass through this —
# the legacy `apply_word_restriction` ran on EVERY message. One source of truth.
_RESTRICTED_WORDS = {
    "abduction", "abduct", "abducting", "abducted", "animal", "asphyxia", "asphyxication",
    "asphyxiation", "asphyxiated", "asphyxiate", "asphyxiating", "ballbusting", "bait",
    "bareback", "blackmail", "beastiality", "bleeding", "blood", "bloodplay", "blooded",
    "blacked", "bukkake", "bestiality", "caned", "caning", "canned", "canning", "cbt",
    "cashapp", "cannibal", "cervix", "cervics", "cerviks", "cervicks", "comatose", "coma",
    "child", "chocked", "choke", "choking", "chokes", "chocking", "choked", "choloroforming",
    "chloroform", "chloroformed", "chloroforming", "cycle", "cp", "consent", "drink",
    "drinking", "drunken", "drunk", "diapers", "doze", "dog", "eleven", "entrance", "escort",
    "escorted", "escorting", "enema", "fansonly", "fansly", "fuckfan", "fanfuck", "fetal",
    "fuckafan", "fanfucked", "fecal", "facentro", "fancentro", "foetal", "fisted", "fist",
    "fisting", "farm", "flogging", "forcing", "force", "forced", "forceful", "forced bi",
    "fifteen", "gaping", "golden", "gangbang", "gangbanging", "gangbanged", "gangbangs",
    "hardsports", "hypno", "hypnotize", "hypnotization", "hypnotizing", "hypnotized", "hooker",
    "inbreed", "inbreeded", "inbreeding", "incapacitation", "incapacitate", "inzest", "incest",
    "intox", "jail", "jailed", "jailbait", "kidnap", "kidnapped", "kidnapping", "kidnapper",
    "knocked", "knock", "knocking", "lactation", "lactating", "lactate", "lolicon", "lolita",
    "lalita", "menstruate", "menstruating", "menstruation", "menstrual", "many vids",
    "medical play", "molested", "molesting", "molest", "meet", "mutilated", "mutilate",
    "mutilating", "mutilation", "necrophilia", "nigger", "pedo", "pedophile", "pedophilia",
    "prostituted", "paralyze", "paralyzed", "paralyzation", "pee", "peeplay", "pissed",
    "poo", "pissing", "piss", "poop", "pooped", "pooping", "pegging", "paddling", "paypal",
    "passed out", "prostitution", "prostitute", "prostituting", "pse", "preteen", "pre-teen",
    "pre-scat", "rapped", "rapping", "rape", "raped", "raping", "rapist", "restricted",
    "snuff", "showers", "skat", "strangle", "strangling", "strangled", "suffocate",
    "suffocation", "suffocated", "teen", "toilet", "torture", "slave", "scat", "strangulation",
    "slavery", "torturing", "tortured", "trance", "twelve", "unconsciousness", "unconscious",
    "unwilling", "underage", "vomit", "vomited", "vomiting", "vomino", "venmo", "whipped",
    "whipping", "watersports", "young", "zoophilia",
}
_VOWELS = "aeiouAEIOU"
# Longest-first so a phrase ("medical play") matches before a contained word ("play").
_RESTRICTED_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_RESTRICTED_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _double_first_vowel(m: "re.Match") -> str:
    word = m.group(0)
    for i, ch in enumerate(word):
        if ch in _VOWELS:
            dup = ch.lower() if i == 0 and ch.isupper() else ch
            return word[: i + 1] + dup + word[i + 1:]
    # no vowel (e.g. "cp", "cbt") → double the first char instead
    return word[0] + word[0].lower() + word[1:] if word else word


def apply_word_restriction(text: str) -> str:
    """Double the first vowel of any OnlyFans-restricted word, whole-word,
    case-insensitive ("Let's meet" → "Let's meeet"). Empty/None passes through.
    Also carries the register floor: inverted ¿/¡ are stripped here because this
    is the one pass every sender runs on outbound (see strip_inverted_punct)."""
    if not text:
        return text
    return _RESTRICTED_RE.sub(_double_first_vowel, strip_inverted_punct(text))


# ── Deterministic off-platform / contact / meetup guard ──────────────
# ONPLATFORM_GUARDRAIL (the system-prompt rule) lowers the odds the model drifts
# into arranging an in-person meetup or swapping contact info — but a prompt is
# probabilistic and a pushy fan can still win. This is the deterministic FLOOR:
# scan the model's OUTBOUND text and, if it leaks a phone number, an off-platform
# channel, or an in-person meet arrangement, swap the WHOLE message for a warm
# on-platform deflection. Whole-message (not surgical) on purpose — editing out
# "thursday" from "i'll be at the harbour thursday" is exactly how you leave the
# arrangement half-standing. Scan BEFORE apply_word_restriction, which mangles
# "meet"->"meeet" and would hide it from these patterns.

# 7+ digits with optional separators — a phone number in a flirty DM is ~never benign.
_OFF_PHONE_RE = re.compile(r"(?:\+?\d[\s().\-]?){7,}\d")
# An email address.
_OFF_EMAIL_RE = re.compile(r"\b[\w.+\-]+@[\w\-]+\.[a-z]{2,}\b", re.IGNORECASE)
# Named off-platform channels (some overlap the word filter — harmless, different action).
_OFF_CHANNEL_RE = re.compile(
    r"\b(snap\s?chat|telegram|whats\s?app|kik|wickr|signal|discord|"
    r"insta(\s?gram)?|tiktok|cash\s?app|venmo|pay\s?pal|zelle|gmail|e-?mail)\b",
    re.IGNORECASE,
)
# Asking for / handing over contact details.
_OFF_CONTACT_RE = re.compile(
    r"\b("
    r"(my|ur|your|the)\s+(number|digits|cell|phone)|"
    r"(text|call|message|msg|dm|hit|add|reach|find|ping)\s+me\s+(on|at|up\s+on|via|through)|"
    r"(give|send|drop|share|swap|exchange)\s+(me\s+)?(?:(?:ur|your|my)\s+)?(number|digits|contact|snap|insta|socials?)|"
    r"what'?s?\s+(ur|your)\s+(number|snap|insta|@)|"
    r"add\s+me\s+on"
    r")\b",
    re.IGNORECASE,
)
# Arranging an in-person meet (the OF-flag category itself).
_OFF_MEETUP_RE = re.compile(
    r"\b("
    r"meet\s?up|meet\s+(me|you|u|irl|in\s+person)|let'?s\s+meet|gonna\s+meet|"
    r"in\s+person|irl|see\s+(you|u)\s+(there|then|soon|tonight|tomorrow)|"
    r"come\s+(see|over|visit)\s+me|come\s+(to|to\s+my)|"
    r"grab\s+(a\s+)?(drink|coffee|dinner|bite)\s+(with|together|sometime)|"
    r"link\s+up\s+(irl|in\s+person)|hook\s?up\s+in\s+person"
    r")\b",
    re.IGNORECASE,
)
# "i'll be at <place> <day/time>" — names a real-world rendezvous (place + when).
# Kept separate from bland "i'll be in bed" by REQUIRING a day-of-week / clock anchor.
_OFF_RENDEZVOUS_RE = re.compile(
    r"\bi'?(ll|m\s+gonna)\s+be\s+(at|in|near|by|around|outside)\b.{0,40}\b("
    r"mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|fri(day)?|sat(urday)?|sun(day)?|"
    r"tomorrow|tonight|this\s+(week|weekend)|next\s+week|noon|"
    r"\d{1,2}\s?(am|pm)|morning|afternoon|evening"
    r")\b",
    re.IGNORECASE,
)

_OFF_PATTERNS = (
    ("phone", _OFF_PHONE_RE),
    ("email", _OFF_EMAIL_RE),
    ("channel", _OFF_CHANNEL_RE),
    ("contact", _OFF_CONTACT_RE),
    ("meetup", _OFF_MEETUP_RE),
    ("rendezvous", _OFF_RENDEZVOUS_RE),
)

# Warm, on-voice redirects back to the chat. Emojis are fine — an account that
# opts into the emoji strip loses them at the send chokepoint; everywhere else
# they read normally. Re-exported from `_voice` (female lane); the male set
# lives beside it there.
_OFF_DEFLECTIONS = _voice.HER.off_deflections


def scan_offplatform(text: str) -> list[str]:
    """Return the category labels of any off-platform/contact/meetup leak in
    `text` (empty list = clean). Scan the model's RAW text, before word
    restriction. Used as a deterministic safety net over ONPLATFORM_GUARDRAIL."""
    if not text:
        return []
    return [label for label, rx in _OFF_PATTERNS if rx.search(text)]


def guard_offplatform(text: str, rng,
                      v: "_voice.VoiceBlocks" = _voice.HER) -> tuple[str, list[str]]:
    """If `text` leaks off-platform content, swap the WHOLE message for a canned
    on-platform deflection; else pass it through. Returns (text, reasons) so the
    caller can log when it fired. `rng` is a seeded random.Random for stable picks.

    `v` is the account's voice bundle and DEFAULTS TO THE REAL FEMALE ONE, not to
    a sentinel. The first cut took a bare `deflections: tuple = ()` threaded down
    from `finalize_draft` through `_guard`, so "the default lane" was spelled as
    an empty tuple at three levels and then recovered by a truthiness fallback
    here. The bundle says what it is, cannot be empty, and deletes the fallback.

    Worth threading a lane this far down for one reason: this is the only place a
    canned line reaches a fan with the model cut out of the loop entirely, so on
    a male account it is the one string no prompt work can correct."""
    reasons = scan_offplatform(text)
    if not reasons:
        return text, reasons
    return rng.choice(v.off_deflections), reasons
