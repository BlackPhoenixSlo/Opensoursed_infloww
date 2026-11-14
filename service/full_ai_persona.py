"""service/full_ai_persona.py — the Full AI Chat persona draft (spec phase-03c,
Solution 1): her OF name + her existing describe text → one JSON-mode text call
→ the Model info text, assembled in code. Saves nothing; the owner's Save does.

  inputs(account_id)                 the reads: name, voice, image lines
  clean_name / clamp_age / us_city / scrub   pure code rules after the model
  persona_draft_system(voice), persona_draft_user(inputs)   the prompt (NEW-110)
  compose(inputs, model_out, current_text) → Draft
  fill_gap(account_id, have)         the gap describe (ticket 54): under 3 lines,
                                     the vault describe on up to 6 newest blank photos

Stored facts (age, home city, location) are locked into the draft and the
Won't-do line is copied from the textarea, never invented (ticket 53). The gap
describe writes only what the vault describe writes (describe fields + tier).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

import accounts
import llm_client
import vault_ai_vision
import vault_sweep
from automations._persona import DEFAULT_REGISTER_AGE, MODEL_NOTES_LABELS, MODEL_NOTES_MAX
from automations._voice import pronouns
from db.engine import get_session
from db.models import AccountAiConfig, VaultItem
from jsonsafe import load_dict
from vault_ai_effective import effective_value
from vault_ai_vision_decide import describe_selection
from vault_describe_jev import BREAST_BARE, INS, NIP, VUL

MAX_LINES = 12          # newest described items sent
LINE_MAX = 300          # chars per image line
VALUE_MAX = 160         # chars per Looks / Personality / Likes value
SAFE_TIERS = ("sfw", "suggestive")
MIN_AGE = 19
BATCH = 100             # vault rows read per round trip while looking for MAX_LINES
GAP_MIN = 3             # fewer safe lines than this → gap describe first
GAP_SIZE = 6            # newest undescribed photos it describes, at most
GAP_AT_ONCE = 3         # describes in flight at once (under the process-wide `_vision_gate` too)
GAP_MODEL = "qwen3-vl-30b"   # the vault describe button's model
NOT_SAFE = ("explicit", "hardcore")

# ASSUMPTION (rung 5, smallest): ordinary mid-size US cities, no landmarks, no
# celebrity towns ("Prefer a real, ordinary, plausible place"). Overturned if
# the owner wants a different list or per-agency lists.
US_CITIES: tuple[str, ...] = (
    "Austin, TX", "Columbus, OH", "Charlotte, NC", "Nashville, TN", "Denver, CO",
    "Phoenix, AZ", "San Diego, CA", "Sacramento, CA", "Portland, OR", "Seattle, WA",
    "Tampa, FL", "Orlando, FL", "Jacksonville, FL", "Atlanta, GA", "Raleigh, NC",
    "Richmond, VA", "Indianapolis, IN", "Kansas City, MO", "St. Louis, MO", "Omaha, NE",
    "Minneapolis, MN", "Milwaukee, WI", "Madison, WI", "Detroit, MI", "Grand Rapids, MI",
    "Cleveland, OH", "Cincinnati, OH", "Pittsburgh, PA", "Philadelphia, PA", "Baltimore, MD",
    "Louisville, KY", "Memphis, TN", "Birmingham, AL", "Houston, TX", "Dallas, TX",
    "San Antonio, TX", "Oklahoma City, OK", "Tulsa, OK", "Albuquerque, NM", "Salt Lake City, UT",
    "Boise, ID", "Las Vegas, NV", "Tucson, AZ", "Charleston, SC",
)

# Spec › Code rules: the clauses `scrub` drops besides vault_describe_jev's
# NIP / BREAST_BARE / VUL / INS. "sexy" stays (not `sex\b`).
EXPLICIT = re.compile(
    r"\b(nude|nudes|nudity|naked|topless|bottomless|explicit|sex|sexual\w*|porn\w*|dildos?|toys?"
    r"|vibrators?|cum|cums|cumming|cumshots?|orgasm\w*|anal|anus|ass ?holes?|spread\w*|masturbat\w*"
    r"|(bra|panties|underwear|lingerie|thong) (off|down|removed|pulled \w+)"
    r"|(taking|took|pulling|pulled) off (her|his|the) (bra|panties|underwear|lingerie|thong|top)"
    r"|no (bra|panties|underwear))\b", re.I)
_DROP = (NIP, BREAST_BARE, VUL, INS, EXPLICIT)
_NAME = re.compile(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*")
_PUNCT = re.compile(r"[^\w\s]")
WONT_DO = MODEL_NOTES_LABELS[-1]   # "Won't do (hard limits)"
_WONT_DO_LINE = re.compile(r"^[ \t]*" + re.escape(WONT_DO).replace("'", "['’]") + r"[ \t]*:(.*)$", re.I | re.M)
_AGE_DIGITS = re.compile(r"\d{1,3}")
NO_NAME_NOTE = "No OF name stored; type her name."


@dataclass
class PersonaInputs:
    account_id: str
    name_raw: str
    name: str
    voice: str | None
    descs: list[str] = field(default_factory=list)
    # Locked stored facts, parsed once in `inputs` (see `stored_age`); "" / None = not stored.
    age: int | None = None    # persona_facts.age, may be under 19 (compose floors it)
    home_city: str = ""       # persona_facts.home_city
    location: str = ""        # account_ai_config.location

    @property
    def used(self) -> int:
        return len(self.descs)


@dataclass
class Draft:
    text: str
    age: int
    city: str
    notes: list[str] = field(default_factory=list)


# ── Pure rules ────────────────────────────────────────────────────────

def clean_name(raw: Any) -> str:
    """The leading run of letters joined by single spaces, apostrophes or
    hyphens: "Kay 🍒 TOP 0.1%" → "Kay". "" when there is none.
    ASSUMPTION (rung 3, spec wording): the run stops at the first emoji, digit
    or other mark, so "Kay Lee 🍒" keeps "Kay Lee". Overturned by an OF name
    whose first word is not her name."""
    m = _NAME.search(raw) if isinstance(raw, str) else None
    return m.group(0)[:40].strip() if m else ""


def clamp_age(x: Any) -> int:
    """Spec: an int below 19 → 19; 19..99 kept; anything else → 22.
    ASSUMPTION (rung 4): an integral float or a 1-3 digit string counts as the
    int (JSON models emit "24"). Overturned if string ages must fall to 22."""
    if isinstance(x, bool):
        return DEFAULT_REGISTER_AGE
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    elif isinstance(x, str) and re.fullmatch(r"\s*\d{1,3}\s*", x):
        x = int(x)
    if not isinstance(x, int) or x > 99:
        return DEFAULT_REGISTER_AGE
    return max(x, MIN_AGE)


def _norm(s: str) -> str:
    return " ".join(_PUNCT.sub(" ", s.lower()).split())


_CITY_KEYS: dict[str, str] = {}
for _entry in US_CITIES:
    _CITY_KEYS[_norm(_entry)] = _entry
    _CITY_KEYS[_norm(_entry.rsplit(",", 1)[0])] = _entry


def us_city(guess: Any, account_id: str) -> str:
    """The `US_CITIES` entry the guess names (case- and punctuation-insensitive,
    with or without the state: "austin, tx" and "Austin" → "Austin, TX"), else
    one picked by a stable hash of `account_id`."""
    hit = _CITY_KEYS.get(_norm(guess)) if isinstance(guess, str) else None
    if hit:
        return hit
    return US_CITIES[int(hashlib.sha256(str(account_id).encode()).hexdigest(), 16) % len(US_CITIES)]


def scrub(text: Any) -> str:
    """Drop every clause (split on , ; .) naming nudity, sex or a bare body part;
    join the rest with ", " and cut to 160 chars. A list is joined first; any
    other non-string is ""."""
    if isinstance(text, (list, tuple)):
        text = ", ".join(str(t) for t in text if isinstance(t, (str, int, float)))
    if not isinstance(text, str):
        return ""
    kept = [c.strip() for c in re.split(r"[,;.]", text)]
    kept = [c for c in kept if c and not any(rx.search(c) for rx in _DROP)]
    return ", ".join(kept)[:VALUE_MAX].strip(" ,")


# ── Prompt (docs/prompts NEW-110, changed from OLD-OTH-30) ────────────

def persona_draft_system(voice: object) -> str:
    """OLD-OTH-30's opening sentence, five rules and closing NEVER line
    verbatim, plus the three new lines (NEW-110 Port status).
    ASSUMPTION (rung 3): a function, not the spec's `PERSONA_DRAFT_SYSTEM`
    constant, because the rules carry the lane's `{p.*}` pronouns as
    `_enrich_system(voice)` does. Overturned if the female lane alone suffices."""
    p = pronouns(voice)
    return (
        "You fill in the background profile of an OnlyFans creator persona so "
        f"{p.possessive} chat AI never has to improvise an answer about "
        f"{p.reflexive} and contradict it later. You are given {p.possessive} "
        "name, notes on "
        f"{p.possessive} photos and any facts already confirmed. Respond with a "
        "SINGLE JSON object and nothing else.\n"
        "RULES:\n"
        "- Anything the persona already states, COPY EXACTLY. Never change a "
        "stated fact — those are locked.\n"
        "- You are AUTHORING a persona, not extracting facts about a real "
        "person. So where the persona is silent, INVENT something ordinary and "
        "plausible and commit to it — a home city, "
        f"{p.possessive} relationship status, whether {p.subject} has kids. "
        "Leaving these blank is the WORST outcome, "
        "not the safe one: the chat AI will then improvise a DIFFERENT answer "
        "every time a fan asks, and fans notice. A committed invention beats an "
        "improvised one.\n"
        "- Keep every value SHORT and concrete: a city name, one clause, a plain "
        "phrase.\n"
        "- Prefer a real, ordinary, plausible place a real person would be from. "
        "No celebrities, no landmarks, nothing exotic or newsworthy.\n"
        "- Do NOT output a timezone, an offset, or a time — those are computed.\n"
        "- The city must be in the United States.\n"
        "- Looks: hair, face, build and clothing style only, from the image notes; "
        "never body parts, nudity, sex acts or what is visible under clothing.\n"
        "Return {age, from, looks, personality, likes}.\n"
        "NEVER output `kinks`, `limits` or `tattoos` — the first two are the "
        "creator's own business decision, and the third is visible in "
        f"{p.possessive} photos."
    )


def confirmed(inputs: PersonaInputs) -> dict:
    """The stored facts the draft copies (OLD-OTH-30's `already_confirmed`):
    age, home_city, location, each only when set. A stored age under 19 is left
    out: the draft says 19 instead (`compose`)."""
    out: dict[str, Any] = {}
    if inputs.age is not None and inputs.age >= MIN_AGE:
        out["age"] = inputs.age
    for key, val in (("home_city", inputs.home_city), ("location", inputs.location)):
        if val:
            out[key] = val
    return out


def persona_draft_user(inputs: PersonaInputs) -> str:
    """{name, image_notes} plus `already_confirmed` only when a fact is stored,
    so a Creator with none sends the ticket-52 body byte for byte."""
    body: dict[str, Any] = {"name": inputs.name, "image_notes": inputs.descs}
    if got := confirmed(inputs):
        body["already_confirmed"] = got
    return json.dumps(body, ensure_ascii=False)


# ── Reads ─────────────────────────────────────────────────────────────

def _name_raw(account_id: str) -> str:
    meta = accounts.load_meta(account_id) or {}
    name = (meta.get("name") or "").strip()
    nick = (meta.get("nickname") or "").strip()
    return name or ("" if nick == f"Account {account_id}" else nick)


async def inputs(account_id: str) -> PersonaInputs:
    """Her OF name, voice and up to 12 newest safe-tier describe lines."""
    raw = _name_raw(account_id)
    query = (select(VaultItem).where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None))
             .order_by(VaultItem.created_at.desc(), VaultItem.media_id.desc()))
    descs: list[str] = []
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, account_id)
        # Tier and description resolve in Python (effective_value), so read newest-first in pages, not the whole vault.
        offset = 0
        while len(descs) < MAX_LINES:
            page = (await s.execute(query.offset(offset).limit(BATCH))).scalars().all()
            for it in page:
                if effective_value(it, "explicitness_tier") not in SAFE_TIERS:
                    continue
                d = effective_value(it, "description")
                d = d.strip()[:LINE_MAX] if isinstance(d, str) else ""
                if d and d not in descs:
                    descs.append(d)
                    if len(descs) == MAX_LINES:
                        break
            if len(page) < BATCH:
                break
            offset += BATCH
    facts = load_dict(getattr(cfg, "persona_facts_json", None))
    home = facts.get("home_city")
    return PersonaInputs(account_id=account_id, name_raw=raw, name=clean_name(raw),
                         voice=getattr(cfg, "voice", None), descs=descs,
                         age=stored_age(facts.get("age")),
                         home_city=home.strip() if isinstance(home, str) else "",
                         location=(getattr(cfg, "location", None) or "").strip())


# ── Gap describe (ticket 54) ──────────────────────────────────────────

async def gap_photos(account_id: str) -> list[int]:
    """Up to GAP_SIZE of her newest photos the vault's "undescribed" sweep would
    visit (live, not described), minus any already tiered explicit/hardcore."""
    query = (select(VaultItem)
             .where(describe_selection(account_id, "undescribed", "v2"), VaultItem.kind == "photo")
             .order_by(VaultItem.created_at.desc(), VaultItem.media_id.desc()))
    ids: list[int] = []
    async with get_session() as s:
        offset = 0
        while len(ids) < GAP_SIZE:
            page = (await s.execute(query.offset(offset).limit(BATCH))).scalars().all()
            for it in page:
                if effective_value(it, "explicitness_tier") in NOT_SAFE:
                    continue
                ids.append(int(it.media_id))
                if len(ids) == GAP_SIZE:
                    break
            if len(page) < BATCH:
                break
            offset += BATCH
    return ids


async def fill_gap(account_id: str, have: int) -> int:
    """With fewer than GAP_MIN safe lines, run the vault describe
    (`_describe_and_flag`: Jev flags + vision describe) on `gap_photos`, behind the
    describe button's claim + budget/key preflight (`_claim_describe`), walked by
    `vault_sweep.run` GAP_AT_ONCE at a time under `_vision_gate`. Returns how many
    came back ok; 0 (never an error) when there is nothing to describe, a describe
    sweep holds the claim, the vision key is missing or today's cap is hit.
    ASSUMPTION (rung 3, full_ai_prepare): it holds the account's describe claim, so
    a running describe sweep (409) means no gap describe this click."""
    if have >= GAP_MIN:
        return 0
    ids = await gap_photos(account_id)
    if not ids:
        return 0
    try:
        await vault_ai_vision._claim_describe(account_id, GAP_MODEL)
    except HTTPException as e:
        if e.status_code not in (409, 429):
            raise
        return 0
    except llm_client.LLMKeyError:
        return 0
    try:
        # The vault sweep walker: one bad photo costs one photo; a cap or key error stops the rest.
        # ASSUMPTION (rung 4): its progress goes to a throwaway dict, not the vault's describe status.
        c = await vault_sweep.run(
            ids, lambda mid: vault_ai_vision._describe_and_flag(account_id, mid, model=GAP_MODEL),
            concurrency=GAP_AT_ONCE, gate=vault_ai_vision._vision_gate, into={}, key=account_id,
            label=f"persona_gap account={account_id}")
        return c.done - c.failed
    finally:
        vault_ai_vision._describe_running.discard(account_id)


# ── Assembly ──────────────────────────────────────────────────────────

def stored_age(x: Any) -> int | None:
    """The stored persona_facts.age as an int (the first 1-3 digit run: 24,
    "24", "17yo"), None when there is no number or it is over 99 — then it
    counts as unset and the guess (`clamp_age`) is used. Under 19 is kept here;
    `compose` floors it with a note."""
    if isinstance(x, bool) or x is None:
        return None
    m = _AGE_DIGITS.search(str(x))
    return int(m.group(0)) if m and int(m.group(0)) <= 99 else None


def wont_do(current_text: str) -> str:
    """The value of the first `Won't do (hard limits):` line in the textarea
    text, "" when there is none. Never from the model, never from storage."""
    m = _WONT_DO_LINE.search(current_text or "")
    return m.group(1).strip() if m else ""


def compose(inputs: PersonaInputs, model_out: dict, current_text: str) -> Draft:
    """The 03a labels in order plus `Looks:` after `From:` (left out when empty:
    `_persona._model_notes_block` drops only the 03a labels' blank lines).
    Unknown keys and `kinks` / `limits` / `tattoos` / `won't do` are never read.

    Locked over any guess: a stored age (under 19 → 19 + a note); the stored
    home city, else the stored location, as `From:` word for word.
    ASSUMPTION (rung 5): `location` fills `From:` only when no home city is
    stored (`home_city` is the canon's "Lives in"); both are copied as stored,
    so a non-US stored place stays. Overturned if the owner wants a separate
    `Based in:` line.
    ASSUMPTION (rung 4): a stored age with no number ("seventeen") or over 99
    counts as unset (`stored_age`), so the floored guess is used and nothing
    under 19 can be copied. Overturned if word ages must be parsed."""
    notes: list[str] = []
    if inputs.age is None:
        age = clamp_age(model_out.get("age"))
    elif inputs.age < MIN_AGE:
        age = MIN_AGE
        notes.append(f"Stored age {inputs.age} is under {MIN_AGE}; the draft uses {MIN_AGE}.")
    else:
        age = inputs.age
    city = inputs.home_city or inputs.location or us_city(model_out.get("from"), inputs.account_id)
    if not inputs.name:
        notes.append(NO_NAME_NOTE)
    values = {
        "Name": inputs.name, "Age": str(age), "From": city,
        "Looks": scrub(model_out.get("looks")),
        "Personality": scrub(model_out.get("personality")),
        "Likes": scrub(model_out.get("likes")),
        WONT_DO: wont_do(current_text),
    }
    labels = list(MODEL_NOTES_LABELS)
    if values["Looks"]:
        labels.insert(labels.index("From") + 1, "Looks")
    text = "\n".join(f"{label}: {values.get(label, '')}" for label in labels)
    return Draft(text=text[:MODEL_NOTES_MAX], age=age, city=city, notes=notes)
