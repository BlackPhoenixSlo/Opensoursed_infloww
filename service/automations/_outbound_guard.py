from __future__ import annotations

import re

from . import _voice
from ._textutil import strip_inverted_punct


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
# OF flags a fixed word set; doubling the first vowel keeps the text readable but slips the filter.
_VOWELS = "aeiouAEIOU"
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
    return word[0] + word[0].lower() + word[1:] if word else word


def apply_word_restriction(text: str) -> str:
    if not text:
        return text
    return _RESTRICTED_RE.sub(_double_first_vowel, strip_inverted_punct(text))



_OFF_PHONE_RE = re.compile(r"(?:\+?\d[\s().\-]?){7,}\d")
_OFF_EMAIL_RE = re.compile(r"\b[\w.+\-]+@[\w\-]+\.[a-z]{2,}\b", re.IGNORECASE)
_OFF_CHANNEL_RE = re.compile(
    r"\b(snap\s?chat|telegram|whats\s?app|kik|wickr|signal|discord|"
    r"insta(\s?gram)?|tiktok|cash\s?app|venmo|pay\s?pal|zelle|gmail|e-?mail)\b",
    re.IGNORECASE,
)
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

_OFF_DEFLECTIONS = _voice.HER.off_deflections


def scan_offplatform(text: str) -> list[str]:
    if not text:
        return []
    return [label for label, rx in _OFF_PATTERNS if rx.search(text)]


# Scan before apply_word_restriction, which mangles "meet" and would hide it from these patterns; swap the whole message, never edit it out.
def guard_offplatform(text: str, rng,
                      v: "_voice.VoiceBlocks" = _voice.HER) -> tuple[str, list[str]]:
    reasons = scan_offplatform(text)
    if not reasons:
        return text, reasons
    return rng.choice(v.off_deflections), reasons
