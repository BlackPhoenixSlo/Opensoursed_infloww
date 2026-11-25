from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import llm_client
from db.models import Fan
from jsonsafe import load_dict
from llm_client import LLMCapExceeded

from . import _persona, _voice

log = logging.getLogger("of-relay.daylog")


SLOT_KEYS: tuple[str, ...] = (
    "morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night")

_SLOT_HOURS: dict[str, str] = {
    "morning_1": "5am-9am, just woken up",
    "morning_2": "9am-12pm, mid-morning",
    "afternoon_1": "12pm-3pm, early afternoon",
    "afternoon_2": "3pm-6pm, late afternoon",
    "evening": "6pm-9pm, evening",
    "night": "9pm-5am, late night",
}


def slot_index(hour: int) -> int:
    if 5 <= hour < 9:
        return 0
    if 9 <= hour < 12:
        return 1
    if 12 <= hour < 15:
        return 2
    if 15 <= hour < 18:
        return 3
    if 18 <= hour < 21:
        return 4
    return 5


def slot_key(hour: int) -> str:
    return SLOT_KEYS[slot_index(hour)]


# None must never default to the server clock: no tz means no day log.
def local_now(tz_offset_minutes: int | None, now: datetime | None = None) -> datetime | None:
    if tz_offset_minutes is None:
        return None
    return (now or datetime.utcnow()) + timedelta(minutes=int(tz_offset_minutes))


# Day starts 05:00, not midnight: the night slot spans midnight, so a 2am fan must not roll onto a new day.
_DAY_STARTS_AT_HOUR = 5


def local_date_str(tz_offset_minutes: int | None, now: datetime | None = None) -> str:
    lnow = local_now(tz_offset_minutes, now)
    return (lnow - timedelta(hours=_DAY_STARTS_AT_HOUR)).strftime("%Y-%m-%d") if lnow else ""


_BEAT_CLIP = 160
_MAX_BEATS = 6
_MAX_COVERS = 3


_MAX_TOPICS = 6
_TOPIC_CLIP = 24


def _topics(raw) -> list[str]:
    if isinstance(raw, str):
        raw = re.split(r"[,;/]", raw)
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for t in raw[:_MAX_TOPICS]:
        s = str(t).strip().lower()[:_TOPIC_CLIP]
        if s and s not in out:
            out.append(s)
    return out


_SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("hiking", "hike", "trail", "trails", "walk", "walking", "ridge", "lookout", "trek"),
    ("fishing", "fish", "trout", "salmon", "rod", "lure", "pier", "tackle"),
    ("music", "song", "songs", "band", "guitar", "playlist", "album", "skynyrd",
     "rock", "country", "vinyl", "concert", "gig"),
    ("dancing", "dance", "two-step", "twostep", "dancehall"),
    ("cooking", "cook", "baking", "bake", "dinner", "chili", "grill", "bbq",
     "barbecue", "recipe", "kitchen"),
    ("movie", "movies", "film", "films", "cinema", "western", "netflix", "watching"),
    ("dogs", "dog", "puppy", "pups", "pup", "heeler", "collie", "shelter", "animal"),
    ("gym", "workout", "lifting", "climbing", "bouldering", "running", "swim",
     "swimming", "laps"),
    ("reading", "book", "books", "novel", "magazine"),
    ("cars", "car", "truck", "driving", "drive", "road", "roadtrip"),
    ("building", "carpenter", "carpentry", "woodworking", "hardware", "renovation",
     "architecture", "heritage", "houses", "construction", "tools"),
    ("shopping", "thrift", "thrifting", "vintage", "market", "groceries", "grocery"),
    ("outdoors", "camping", "campfire", "lake", "river", "beach", "mountain", "park"),
)
_SYN_INDEX: dict[str, set[str]] = {}
for _group in _SYNONYMS:
    for _w in _group:
        _SYN_INDEX.setdefault(_w, set()).update(_group)


# The model often returns covers as an extra element of beats, past the _MAX_BEATS slice; look in both.
def _covers_of(data: dict) -> list:
    top = data.get("covers")
    if isinstance(top, list) and top:
        return top
    for row in (data.get("beats") or []):
        if isinstance(row, dict) and isinstance(row.get("covers"), list):
            return row["covers"]
    return []


def parse_day_log(raw) -> dict:
    data = load_dict(raw)
    date = str(data.get("date") or "").strip()[:10]
    if not date:
        return {}
    beats, seen = [], set()
    for row in (data.get("beats") or [])[:_MAX_BEATS]:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("id") or "").strip()[:8]
        slot = str(row.get("slot") or "").strip()
        text = str(row.get("text") or "").strip()[:_BEAT_CLIP]
        if not (bid and text) or slot not in SLOT_KEYS or bid in seen:
            continue
        seen.add(bid)
        beats.append({"id": bid, "slot": slot, "text": text,
                      "topics": _topics(row.get("topics"))})
    covers = []
    for row in _covers_of(data)[:_MAX_COVERS]:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()[:8]
        text = str(row.get("text") or "").strip()[:_BEAT_CLIP]
        if cid and text:
            covers.append({"id": cid, "kind": str(row.get("kind") or "busy").strip()[:12],
                           "text": text})
    if not beats:
        return {}
    return {"date": date, "weekday": str(data.get("weekday") or "").strip()[:12],
            "beats": beats, "covers": covers}


def is_fresh(day_log: dict, tz_offset_minutes: int | None,
             now: datetime | None = None) -> bool:
    today = local_date_str(tz_offset_minutes, now)
    return bool(today) and bool(day_log) and day_log.get("date") == today


# Falls backward to an earlier slot, never forward: a later slot would claim the future as done.
def beat_for_hour(day_log: dict, hour: int) -> dict:
    if not day_log:
        return {}
    by_slot = {b["slot"]: b for b in day_log.get("beats", [])}
    for i in range(slot_index(hour), -1, -1):
        hit = by_slot.get(SLOT_KEYS[i])
        if hit:
            return hit
    return {}


_ASKS_ABOUT_HER_DAY_RE = re.compile(
    r"("
    r"\bwyd\b|\bw\s?y\s?d\b|"
    r"\bwhat(?:'?s| is| are| r| you| u)?[^?.!]{0,24}\b(?:up to|doing|been up to|"
    r"get up to|got up to)\b|"
    r"\bhow(?:'?s| was| is| did| has)\b[^?.!]{0,40}\b(?:day|today|evening|morning|"
    r"night|weekend)\b|"
    r"\bhow(?:'?s| was| is| did)\b[^?.!]{0,24}\b(?:treat|treating)\b|"
    r"\bwhat(?:'?d| did| have)?\s?(?:you|u|ya)\b[^?.!]{0,24}\b(?:do|been doing|get "
    r"up to)\b|"
    r"\bwhat(?:'?s| is)\s?(?:new|goin|going)\b|"
    r"\bbusy\s?(?:day|today|night)\b|"
    r"\btell me about (?:your|ur) day\b|"
    r"\bqu[ée]\s+(?:hac[ée]s|estas haciendo|est[áa]s haciendo|hiciste)\b|"
    r"\bc[óo]mo\s+(?:estuvo|va|fue|te fue)\b[^?.!]{0,24}\b(?:d[íi]a|hoy|noche)\b|"
    r"\bqu[ée]\s+tal\s+(?:tu\s+)?d[íi]a\b"
    r")",
    re.I,
)


def asks_about_her_day(text: str | None) -> bool:
    return bool(_ASKS_ABOUT_HER_DAY_RE.search(text or ""))


def day_block(day_log: dict, hour: int | None, voice: object = None) -> str:
    if hour is None:
        return ""
    beat = beat_for_hour(day_log, hour)
    if not beat:
        return ""
    v = _voice.blocks(voice)
    lane = ("" if not v.is_male else
            " Say it flat — it is information, not an invitation for him to ask "
            "about you.")
    return (
        f"YOUR DAY SO FAR: {beat['text']}\n"
        "WHAT HAPPENED, not a script: never quote it, rephrase fresh. the ONE "
        "thing you may raise unprompted — half a sentence, in passing, once. "
        "never contradict it, never invent or stretch an activity to match his."
        f"{lane}\n\n")


def relatable_block(day_log: dict, hour: int | None, f: Fan | None) -> str:
    if hour is None:
        return ""
    beat = relatable_beat(day_log, hour, f)
    if not beat:
        return ""
    cur = beat_for_hour(day_log, hour)
    if cur and cur.get("id") == beat.get("id"):
        return ("HE WOULD ACTUALLY CARE ABOUT WHAT YOU DID TODAY — it lines up with "
                "something he's into. Say what it was and let him have the opening; "
                "don't explain the connection or tell him it reminded you of him.\n\n")
    return (f"ALSO TODAY, EARLIER: {beat['text']}\n"
            "matches what he's into — one offhand clause if it fits, else skip. "
            "never announce the link.\n\n")


_STOP = frozenset(
    "and the with a to my out for in of on at some little bit really just got back "
    "from her his their this that then was were been are is am not too very more "
    "into like likes love loves doing did day today going go went new other stuff "
    "things thing lot lots good great nice".split())


def _words(*vals) -> set[str]:
    out: set[str] = set()
    for v in vals:
        if isinstance(v, (list, tuple)):
            v = " ".join(str(x) for x in v)
        for w in re.findall(r"[a-zA-Z']{3,}", str(v or "").lower()):
            if w in _STOP:
                continue
            out.add(w)
            out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w + "s")
            out |= _SYN_INDEX.get(w, set())
    return out


# Count distinct synonym groups, not words: a big group (cooking) otherwise outscores a direct hit.
def _concepts(words: set[str]) -> int:
    groups, loose = set(), 0
    for w in words:
        group = _SYN_INDEX.get(w)
        if group:
            groups.add(min(group))
        else:
            loose += 1
    return len(groups) + (loose + 1) // 2


def fan_interests(f: Fan | None) -> set[str]:
    if f is None:
        return set()
    return _words(getattr(f, "hobbies", None), getattr(f, "occupation", None),
                  getattr(f, "recent_events", None), getattr(f, "home_city", None))


# Earlier-or-current beats only: a plan stated as done is the one lie to avoid; ties go to the most recent.
def relatable_beat(day_log: dict, hour: int, f: Fan | None) -> dict:
    if not day_log:
        return {}
    his = fan_interests(f)
    if not his:
        return {}
    cur = slot_index(hour)
    best, best_score = {}, 0
    for beat in day_log.get("beats", []):
        idx = SLOT_KEYS.index(beat["slot"]) if beat["slot"] in SLOT_KEYS else -1
        if idx < 0 or idx > cur:
            continue
        hits = _concepts(his & _words(beat.get("topics"), beat.get("text")))
        if hits and hits >= best_score:
            best, best_score = beat, hits
    return best


def day_ask_block(day_log: dict, hour: int | None, last_inbound: str) -> str:
    if hour is None or not asks_about_her_day(last_inbound):
        return ""
    if not beat_for_hour(day_log, hour):
        return ""
    return ("HE ASKED ABOUT YOUR DAY — answer FIRST from YOUR DAY SO FAR, own "
            "words, half a sentence. dont bounce it back; then one question "
            "max.\n\n")


_SYSTEM = (
    "Write a DIFFERENT believable day in this OnlyFans creator's life, as SHE "
    "would text it — same person/city/habits as the sample, never contradict "
    "her facts.\n"
    "Respond with a SINGLE JSON object and nothing else:\n"
    '{"beats":[{"id":"","slot":"","text":""}],"covers":[{"id":"","kind":"","text":""}]}\n'
    "- exactly 6 beats, one per slot, in order: morning_1, morning_2, "
    "afternoon_1, afternoon_2, evening, night. `id` short unique; `topics` = "
    "2-4 lowercase words naming what the beat is ABOUT.\n"
    "- ONE continuous ORDINARY day — no drama, sex, filming/creator work, or "
    "odd money — across 4+ life areas (food, chores, friends, gym, town, "
    "pets, shows), max TWO beats per topic. beats may refer back, never "
    "contradict or repeat.\n"
    "- `text`: HALF A SENTENCE she'd text — lowercase, concrete, 3-14 words, "
    "no asterisks, at most one emoji. 'took the dogs up the ridge trail' "
    "beats 'went for a walk'.\n"
    "- 3 `covers`: sorry-was-away lines that look BACK at the beats "
    "(`kind`: busy, asleep, long) — never a new activity."
)


def _user_prompt(persona: str, seed_acts: dict, weekday: str, date: str) -> str:
    seed = "\n".join(f"- {k}: {seed_acts[k]}" for k in SLOT_KEYS
                     if str(seed_acts.get(k) or "").strip())
    slots = "\n".join(f"- {k} ({_SLOT_HOURS[k]})" for k in SLOT_KEYS)
    return (
        f"WHO SHE IS:\n{persona.strip()}\n\n"
        + (f"THE KIND OF DAY SHE HAS (tone and texture only — do NOT reuse these "
           f"lines, write a different day):\n{seed}\n\n" if seed else "")
        + f"THE SLOTS:\n{slots}\n\n"
        f"Write her day for {weekday}, {date}.")


# Two job kinds can hit a cold cache in one tick; the in-lock DB re-read makes the second adopt the first's day.
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(account_id: str) -> asyncio.Lock:
    lock = _locks.get(str(account_id))
    if lock is None:
        lock = _locks[str(account_id)] = asyncio.Lock()
    return lock


async def generate_day_log(account_id: str, persona: str, seed_acts: dict,
                           tz_offset_minutes: int | None, model: str,
                           purpose: str, now: datetime | None = None) -> dict:
    lnow = local_now(tz_offset_minutes, now)
    if not lnow or not persona.strip():
        return {}
    day_start = lnow - timedelta(hours=_DAY_STARTS_AT_HOUR)
    date = day_start.strftime("%Y-%m-%d")
    weekday = day_start.strftime("%A")
    try:
        res = await llm_client.chat(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": _user_prompt(
                          persona, seed_acts or {}, weekday, date)}],
            purpose=purpose, account_id=account_id,
            # Warm: 0.0 converges on the same day every day.
            temperature=0.9,
            response_format={"type": "json_object"},
        )
        parsed = getattr(res, "parsed", None)
        raw = parsed if parsed is not None else res.content
    except LLMCapExceeded:
        return {}
    except Exception:
        log.warning("day log generation failed account=%s", account_id, exc_info=True)
        return {}
    data = load_dict(raw)
    data["date"], data["weekday"] = date, weekday
    row = parse_day_log(data)
    if row:
        log.info("day log account=%s date=%s beats=%d covers=%d",
                 account_id, date, len(row["beats"]), len(row["covers"]))
    return row


DAY_LOG_ENABLED_KEY = "day_log_enabled"

DAY_LOG_DEFAULT = True


def enabled_for(cfg_row) -> bool:
    stored = load_dict(getattr(cfg_row, "style_config_json", None) if cfg_row else None)
    return bool(stored.get(DAY_LOG_ENABLED_KEY, DAY_LOG_DEFAULT))


async def ensure_day_log(account_id: str, cfg_row, model: str, purpose: str,
                         now: datetime | None = None) -> dict:
    if cfg_row is None:
        return {}
    from . import rhythm
    tz_off = rhythm.tz_offset_for(getattr(cfg_row, "timezone", None),
                                  getattr(cfg_row, "utc_offset", None))
    if tz_off is None:
        return {}
    stored = parse_day_log(getattr(cfg_row, "day_log_json", None))
    if is_fresh(stored, tz_off, now):
        return stored

    async with _lock_for(account_id):
        fresh = await _load_day_log_row(account_id)
        if is_fresh(fresh, tz_off, now):
            return fresh
        persona = _persona.compose_persona(cfg_row, fallback="").strip()
        seed = load_dict(getattr(cfg_row, "time_activities_json", None))
        row = await generate_day_log(account_id, persona, seed, tz_off,
                                     model, purpose, now)
        if row:
            await _store_day_log(account_id, row)
        return row


async def _load_cfg_row(account_id: str):
    from db.engine import get_session
    from db.models import AccountAiConfig
    async with get_session() as s:
        return await s.get(AccountAiConfig, str(account_id))


async def _load_day_log_row(account_id: str) -> dict:
    return parse_day_log(getattr(await _load_cfg_row(account_id), "day_log_json", None))


async def _store_day_log(account_id: str, row: dict) -> None:
    import json

    from db.engine import get_session
    from db.models import AccountAiConfig
    try:
        async with get_session() as s:
            cfg = await s.get(AccountAiConfig, str(account_id))
            if cfg is None:
                return
            cfg.day_log_json = json.dumps(row, ensure_ascii=False)
            await s.commit()
    except Exception:
        log.warning("day log store failed account=%s", account_id, exc_info=True)


_UNSET = object()


@dataclass(frozen=True)
class Day:

    log: dict = field(default_factory=dict)
    hour: int | None = None

    def __bool__(self) -> bool:
        return bool(self.log) and self.hour is not None

    @property
    def date(self) -> str:
        return str(self.log.get("date") or "")

    def system_block(self, voice: object) -> str:
        return day_block(self.log, self.hour, voice)

    def user_block(self, f: Fan | None, last_inbound: str) -> str:
        return (relatable_block(self.log, self.hour, f)
                + day_ask_block(self.log, self.hour, last_inbound))


NO_DAY = Day()


async def load_day(account_id: str, cfg_row=_UNSET, *, model: str, purpose: str,
                   clock_tz: int | None, now: datetime | None = None) -> Day:
    row = await _load_cfg_row(account_id) if cfg_row is _UNSET else cfg_row
    if not enabled_for(row):
        return NO_DAY
    log = await ensure_day_log(account_id, row, model=model, purpose=purpose, now=now)
    if not log or clock_tz is None:
        return NO_DAY
    return Day(log, local_now(clock_tz, now).hour)
