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

MAX_LINES = 12
LINE_MAX = 300
VALUE_MAX = 160
SAFE_TIERS = ("sfw", "suggestive")
MIN_AGE = 19
BATCH = 100             # vault rows read per round trip while looking for MAX_LINES
GAP_MIN = 3             # fewer safe lines than this → gap describe first
GAP_SIZE = 6            # newest undescribed photos it describes, at most
GAP_AT_ONCE = 3         # describes in flight at once (under the process-wide `_vision_gate` too)
GAP_MODEL = "qwen3-vl-30b"   # the vault describe button's model
NOT_SAFE = ("explicit", "hardcore")

# Ordinary mid-size US cities, no landmarks or celebrity towns.
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

EXPLICIT = re.compile(
    r"\b(nude|nudes|nudity|naked|topless|bottomless|explicit|sex|sexual\w*|porn\w*|dildos?|toys?"
    r"|vibrators?|cum|cums|cumming|cumshots?|orgasm\w*|anal|anus|ass ?holes?|spread\w*|masturbat\w*"
    r"|(bra|panties|underwear|lingerie|thong) (off|down|removed|pulled \w+)"
    r"|(taking|took|pulling|pulled) off (her|his|the) (bra|panties|underwear|lingerie|thong|top)"
    r"|no (bra|panties|underwear))\b", re.I)
_DROP = (NIP, BREAST_BARE, VUL, INS, EXPLICIT)
_NAME = re.compile(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*")
_PUNCT = re.compile(r"[^\w\s]")
WONT_DO = MODEL_NOTES_LABELS[-1]
_WONT_DO_LINE = re.compile(r"^[ \t]*" + re.escape(WONT_DO).replace("'", "['’]") + r"[ \t]*:(.*)$", re.I | re.M)
_AGE_DIGITS = re.compile(r"\d{1,3}")
NO_NAME_NOTE = "No OF name stored; type the Creator's name."


@dataclass
class PersonaInputs:
    account_id: str
    name_raw: str
    name: str
    voice: str | None
    descs: list[str] = field(default_factory=list)
    age: int | None = None
    home_city: str = ""
    location: str = ""

    @property
    def used(self) -> int:
        return len(self.descs)


@dataclass
class Draft:
    text: str
    age: int
    city: str
    notes: list[str] = field(default_factory=list)



def clean_name(raw: Any) -> str:
    m = _NAME.search(raw) if isinstance(raw, str) else None
    return m.group(0)[:40].strip() if m else ""


def clamp_age(x: Any) -> int:
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
    hit = _CITY_KEYS.get(_norm(guess)) if isinstance(guess, str) else None
    if hit:
        return hit
    return US_CITIES[int(hashlib.sha256(str(account_id).encode()).hexdigest(), 16) % len(US_CITIES)]


def scrub(text: Any) -> str:
    if isinstance(text, (list, tuple)):
        text = ", ".join(str(t) for t in text if isinstance(t, (str, int, float)))
    if not isinstance(text, str):
        return ""
    kept = [c.strip() for c in re.split(r"[,;.]", text)]
    kept = [c for c in kept if c and not any(rx.search(c) for rx in _DROP)]
    return ", ".join(kept)[:VALUE_MAX].strip(" ,")



def persona_draft_system(voice: object) -> str:
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
    out: dict[str, Any] = {}
    if inputs.age is not None and inputs.age >= MIN_AGE:
        out["age"] = inputs.age
    for key, val in (("home_city", inputs.home_city), ("location", inputs.location)):
        if val:
            out[key] = val
    return out


def persona_draft_user(inputs: PersonaInputs) -> str:
    body: dict[str, Any] = {"name": inputs.name, "image_notes": inputs.descs}
    if got := confirmed(inputs):
        body["already_confirmed"] = got
    return json.dumps(body, ensure_ascii=False)



def _name_raw(account_id: str) -> str:
    meta = accounts.load_meta(account_id) or {}
    name = (meta.get("name") or "").strip()
    nick = (meta.get("nickname") or "").strip()
    return name or ("" if nick == f"Account {account_id}" else nick)


async def inputs(account_id: str) -> PersonaInputs:
    raw = _name_raw(account_id)
    # Tier and description resolve in Python (effective_value), so read newest-first in pages, not the whole vault.
    query = (select(VaultItem).where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None))
             .order_by(VaultItem.created_at.desc(), VaultItem.media_id.desc()))
    descs: list[str] = []
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, account_id)
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



async def gap_photos(account_id: str) -> list[int]:
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
    if have >= GAP_MIN:
        return 0
    ids = await gap_photos(account_id)
    if not ids:
        return 0
    try:
        # Holds the account's describe claim: a running describe sweep (409) means no gap describe this click.
        await vault_ai_vision._claim_describe(account_id, GAP_MODEL)
    except HTTPException as e:
        if e.status_code not in (409, 429):
            raise
        return 0
    except llm_client.LLMKeyError:
        return 0
    try:
        # One bad photo costs one photo; a cap or key error stops the rest. Progress goes to a throwaway dict, not the vault's describe status.
        c = await vault_sweep.run(
            ids, lambda mid: vault_ai_vision._describe_and_flag(account_id, mid, model=GAP_MODEL),
            concurrency=GAP_AT_ONCE, gate=vault_ai_vision._vision_gate, into={}, key=account_id,
            label=f"persona_gap account={account_id}")
        return c.done - c.failed
    finally:
        vault_ai_vision._describe_running.discard(account_id)



def stored_age(x: Any) -> int | None:
    if isinstance(x, bool) or x is None:
        return None
    m = _AGE_DIGITS.search(str(x))
    return int(m.group(0)) if m and int(m.group(0)) <= 99 else None


def wont_do(current_text: str) -> str:
    m = _WONT_DO_LINE.search(current_text or "")
    return m.group(1).strip() if m else ""


# Locked over any guess: stored age (under 19 -> 19), home city, location. Won't-do is copied from the textarea; kinks/limits/tattoos never read.
def compose(inputs: PersonaInputs, model_out: dict, current_text: str) -> Draft:
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
