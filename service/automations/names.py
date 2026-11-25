from __future__ import annotations

import html
import re
from collections.abc import Iterable

from db.models import Fan


# Retired as a nickname slot (the tier rotted: 225 of 766 labelled fans were wrong); kept as a denylist so a legacy 'Spender/…' never becomes a name.
SPEND_TIERS = (("Whale", 50000), ("Spender", 5000), ("Buyer", 1), ("Free", 0))

SPEND_TIER_WORDS = frozenset(label.lower() for label, _ in SPEND_TIERS)


# Segment-exact, so Freeman or Freelancer survive; gen_info and apply_profiles feed the stored label back, so a tier written once would re-assert forever.
def strip_spend_tier(label: str | None) -> str:
    if not label:
        return ""
    segs = (p.strip() for p in str(label).split("/"))
    return "/".join(p for p in segs if p and p.lower() not in SPEND_TIER_WORDS)


# Places that are also first names (Chad, Jordan, Georgia...) are deliberately absent; the per-fan home_country check catches those.
_PLACE_WORDS = frozenset("""
afghanistan albania algeria america american andorra angola arab arabia
argentina argentine argentinian armenia aruba asia asian australia australian
austria azerbaijan bahamas bahrain bangladesh barbados belarus belgian belgium
belize benin bermuda bhutan bolivia bosnia bosnian botswana brasil brazil
brazilian britain british brunei bulgaria bulgarian cambodia cameroon canada
canadian chile chilean china chinese colombia colombian comoros congo croatia
croatian cuba cuban curacao cyprus czech czechia danish denmark djibouti
dominica dominican dutch ecuador egypt egyptian emirates england english
eritrea estonia eswatini ethiopia europe european faso fiji filipino finland
finnish france french gabon gambia germany german ghana gibraltar greece greek
greenland grenada guadeloupe guatemala guinea guyana haiti haitian hispanic
holland honduras hungarian hungary iceland indonesia indonesian iran iraq
ireland irish israeli italia italian italy jamaica jamaican japan japanese
kazakhstan korea korean kosovo kuwait kyrgyzstan lanka laos latino latvia
lebanon leone lesotho liberia libya liechtenstein lithuania luxembourg
macedonia madagascar malawi malaysia maldives mali malta mauritania mauritius
mexican mexico méxico moldova monaco mongolia montenegro morocco moroccan
mozambique myanmar namibia nepal netherlands nicaragua niger nigeria nigerian
norway norwegian oman pakistan pakistani palestine panama paraguay peru
peruvian philippines poland polish portugal portuguese qatar rico romania
romanian russia russian rwanda samoa scotia scotland scottish senegal serbia
serbian seychelles singapore slovak slovakia slovenia slovenian somalia spain
spaniard spanish sudan suriname swedish sweden swiss switzerland syria taiwan
tajikistan tanzania thai thailand togo tonga trinidad tunisia turkey turkish
türkiye turkmenistan uganda ukraine ukrainian uruguay uzbekistan vanuatu
vatican venezuela venezuelan vietnam vietnamese wales welsh yemen zambia
zealand zimbabwe réunion reunion españa
alabama alaska arizona arkansas california colorado connecticut delaware
florida hawaii idaho illinois iowa kansas kentucky louisiana maine maryland
massachusetts michigan minnesota mississippi missouri nebraska nevada ohio
oklahoma oregon pennsylvania tennessee texas utah vermont washington wisconsin
wyoming manitoba nunavut ontario quebec saskatchewan yukon newfoundland
unknown null blank none
usa us uk gb uae nz
""".split()) | frozenset({
    "new zealand", "north macedonia", "south africa", "south korea",
    "north korea", "puerto rico", "saudi arabia", "sri lanka", "costa rica",
    "el salvador", "cape verde", "sierra leone", "ivory coast", "hong kong",
    "united states", "united kingdom", "great britain", "new hampshire",
    "new jersey", "new mexico", "new york", "rhode island", "west virginia",
    "nova scotia", "british columbia", "burkina faso", "puerto rican",
}) | SPEND_TIER_WORDS


def is_place_word(s: str | None) -> bool:
    t = " ".join(str(s or "").lower().split()).strip(".,")
    return bool(t) and t in _PLACE_WORDS


def is_greetable_name(s: str | None, *, here: Iterable[str] = ()) -> bool:
    t = " ".join(str(s or "").lower().split())
    if not t or not any(ch.isalpha() for ch in t):
        return False
    if any(ch.isdigit() or ch == "_" for ch in t):
        return False
    if is_place_word(t):
        return False
    return t not in {" ".join(str(p or "").lower().split()) for p in here if p}


# First non-empty slot: a leading '/' is sloppy input, not an unknown name.
def name_token(s: str | None, *, last: bool = False) -> str:
    if not s:
        return ""
    seg = next((p.strip() for p in html.unescape(str(s)).split("/") if p.strip()), "")
    if "," in seg:
        return ""
    words = re.split(r"[\s();&]+", seg) if seg else []
    words = [w for w in words if w]
    if not words:
        return ""
    raw = words[-1] if last else words[0]
    if not raw[:1].isupper():
        return ""
    # A shouted token is a country code from the location slot, never a first name.
    if raw.isupper() and len(raw) <= 4:
        return ""
    w = "".join(ch for ch in raw if ch.isalpha())
    if len(w) < 2:
        return ""
    if is_place_word(w) or is_place_word(seg):
        return ""
    return w


def resolve_fan_name(f) -> str:
    """Single source of truth for 'what real first name do we greet this fan by'.

    Why this exists: OF *message* payloads carry only `fromUser:{id}` — no name — so
    `of_username`/`of_display_name` are empty for ~80% of fans, and the WS pump used
    to clobber them to NULL on every message. The team-curated `custom_nickname`
    ('John/City/Tag') is then the most reliable name signal we hold, but the senders
    never consulted it and emitted a literal 'Babe'.

    Precedence: real_name → custom_nickname → generated_nickname → of_display_name.
    CURATED BEATS RAW: `custom_nickname` is the CRM label the whole UI shows, so it
    outranks OF's own display name — on 154 prod fans the chat greeted "hey
    surferdude" / "hey Gym Guy" while the team had typed 'Marcus' / 'Dave', and
    send_welcome had always ordered it this way. Note the column is NOT purely
    hand-typed: `push_nick_and_notes` mirrors `build_structured_nickname` back into
    it, so ~1.6k of 2k prod values are our own structured push. That is why it sits
    ABOVE generated_nickname rather than below — measured, the two orders disagree on
    exactly ONE fan in 8,550, so the mirror never robs the AI label of a better name.
    `of_username` is deliberately excluded — handles like 'u123' / 'alexnielsen'
    aren't greetable names. Returns '' when we truly have nothing; callers keep their
    own soft 'babe' fallback.

    BOTH nickname columns hold a STRUCTURED LABEL, not a name: gen_info builds
    `Name/City,Country/Age/Job/Tag` and, when it can't find a usable name, blanks the
    first slot — `_clean_nickname` then drops the empty slot so the LOCATION slides
    into first position ('Vancouver,Canada/39', 'USA/Free'). generated_nickname used
    to be returned verbatim, so those labels reached the chat engines as the fan's
    name and she greeted people with "hey Kentucky,USA u still there?". Both now go
    through `name_token`, which keeps a real name slot and rejects a location one.

    `f` may be a Fan ORM row or a dict of the same fields."""
    def _g(attr: str) -> str:
        if f is None:
            return ""
        raw = f.get(attr) if isinstance(f, dict) else getattr(f, attr, "")
        # OF returns these fields HTML-escaped and the greeting uses them verbatim
        return html.unescape(str(raw or "")).strip()

    here = (_g("home_country"), _g("home_city"))
    candidates = (_g("real_name"),
                  name_token(_g("custom_nickname")),
                  name_token(_g("generated_nickname"), last=True),
                  _g("of_display_name"))
    return next((n for n in candidates if is_greetable_name(n, here=here)), "")


_NICK_MAX = 70
# "_" keeps the slot visible; name_token needs a capital letter so it never reads back as a name
_NO_NAME = "_"


def build_structured_nickname(f: Fan) -> str:
    age = (f.his_age or "").strip()
    country = (f.home_country or "").strip()
    city = (f.home_city or "").strip()
    # custom_nickname is mirrored back every tick: take only its name slot or loc/age/job re-append and grow to the cap.
    name = next((n for n in ((getattr(f, "real_name", None) or "").strip(),
                             name_token(getattr(f, "custom_nickname", None)),
                             (getattr(f, "of_display_name", None) or "").strip())
                 if is_greetable_name(n, here=(country, city))), "")
    job = (f.occupation or "").strip()
    loc = ",".join(p for p in (city, country) if p)
    parts = [p for p in (name, loc, age, job) if p]
    if not parts:
        return ""
    if not name:
        parts.insert(0, _NO_NAME)
    return "/".join(parts)[:_NICK_MAX]
