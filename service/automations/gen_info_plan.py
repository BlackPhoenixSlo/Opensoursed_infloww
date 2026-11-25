from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ._skiplist import should_skip_muted_creator
from .names import is_greetable_name, strip_spend_tier

QUAL_MIN_FAN_MSGS = 1
QUAL_MIN_SPEND_CENTS = 1
MIN_NEW_MSGS = 8
NEW_SUB_WINDOW = timedelta(days=7)
RECENT_SPEND_WINDOW = timedelta(days=7)
PAYING_LIFETIME_FLOOR_CENTS = 50000
CADENCE_PAYING = (timedelta(days=2), 55)
CADENCE_MIDDLE = (timedelta(days=2), 89)
CADENCE_COLD = (timedelta(days=7), 89)
MSG_HEAD = 250
MSG_TAIL = 250
MSG_CLIP = 250
MSG_HEAD_SPENDER = 500
MSG_TAIL_SPENDER = 500
SPENDER_CENTS = 5000

HTML_OPEN = "<"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    if HTML_OPEN not in s:
        return s.strip()
    return TAG_RE.sub("", s).strip()


def clean_nickname(s: str | None) -> str:
    if not s:
        return ""
    parts = [p.strip() for p in strip_spend_tier(s).split("/")]
    parts = [p for p in parts if any(ch.isalnum() for ch in p)]
    return WS_RE.sub(" ", "/".join(parts)).strip()


def blank_unknown(s: Any) -> str:
    s = (s or "")
    s = s.strip() if isinstance(s, str) else str(s)
    return "" if s.lower() in ("unknown", "n/a", "none") else s


def as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip() if not isinstance(v, str) else v


EMPTY_BULLET_RE = re.compile(r"^[-*\s]*[A-Za-z][\w /]*:\s*$")


def clean_bullets(v: Any) -> str:
    text = as_text(v)
    if not text:
        return ""
    lines = [
        ln for ln in (l.rstrip() for l in text.split("\n"))
        if ln.strip() and not EMPTY_BULLET_RE.match(ln.strip())
    ]
    return "\n".join(lines)


def parse_events(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        s = str(raw).strip()
        return [s] if s and s != "[]" else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


def _here(c: "Candidate") -> tuple:
    return (c.known.get("home_country"), c.known.get("home_city"))


def guard_name(nickname: str, c: "Candidate") -> str:
    if not nickname:
        return nickname
    parts = nickname.split("/")
    name = parts[0].strip()
    if not name:
        return nickname
    if is_greetable_name(name, here=_here(c)):
        return nickname
    parts[0] = ""
    return clean_nickname("/".join(parts))


def name_hint(c: "Candidate") -> str:
    for src in (c.known.get("real_name", ""), c.of_name, c.of_username):
        s = (src or "").strip()
        tok = s.split(" ")[0].strip(".,/") if s else ""
        if len(tok) >= 2 and tok.isalpha() and is_greetable_name(tok, here=_here(c)):
            return tok[:1].upper() + tok[1:]
    return ""


def tier_knobs(lifetime_cents: int, recent_cents: int,
                subscribed_at: "datetime | None", now: datetime) -> tuple:
    if recent_cents > 0 or lifetime_cents >= PAYING_LIFETIME_FLOOR_CENTS:
        return CADENCE_PAYING
    new_sub = subscribed_at is not None and (now - subscribed_at) < NEW_SUB_WINDOW
    if new_sub or lifetime_cents > 0:
        return CADENCE_MIDDLE
    return CADENCE_COLD


def profile_is_stale(prev_count: int | None, last_gen_at: datetime | None,
                     now_count: int, now: datetime, *,
                     fresh_after: timedelta = CADENCE_MIDDLE[0],
                     volume_cap: int = CADENCE_MIDDLE[1]) -> bool:
    nc = int(now_count)
    prev = int(prev_count) if prev_count is not None else 0
    new_msgs = nc - prev
    if new_msgs < MIN_NEW_MSGS:
        return False
    if prev_count is None:
        return True
    if new_msgs >= volume_cap:
        return True
    if last_gen_at is not None and (now - last_gen_at) >= fresh_after:
        return True
    return False


def known_block(c: "Candidate") -> str:
    k = c.known or {}
    lines: list[str] = []
    real = (k.get("real_name") or "").strip()
    if real:
        lines.append(f"Real name: {real}")
    loc = ", ".join(x for x in ((k.get("home_city") or "").strip(),
                                (k.get("home_country") or "").strip()) if x)
    if loc:
        lines.append(f"Location: {loc}")
    for label, key in (("Age", "his_age"), ("Job", "occupation"),
                       ("Hobbies", "hobbies"), ("Relationship", "relationship_status"),
                       ("Fetishes", "fetishes")):
        v = (k.get(key) or "").strip()
        if v:
            lines.append(f"{label}: {v}")
    events = parse_events(k.get("recent_events"))
    if events:
        lines.append("Recent events: " + "; ".join(events))
    prior_nick = clean_nickname(k.get("generated_nickname"))
    if prior_nick:
        lines.append(f"Current nickname (refine + keep complete): {prior_nick}")
    if not lines:
        return ""
    return ("KNOWN INFO (already confirmed — ground truth; confirm or correct from "
            "the chat, never drop it):\n" + "\n".join(lines) + "\n\n")



class Candidate:
    __slots__ = ("fan_id", "fan_msg_n", "total_msg_n", "spend_cents",
                 "recent_spend_cents", "subscribed_at",
                 "source", "is_muted", "of_name", "of_username", "known", "messages")

    def __init__(self, fan_id: int):
        self.fan_id = fan_id
        self.fan_msg_n = 0
        self.total_msg_n = 0
        self.spend_cents = 0
        self.recent_spend_cents = 0
        self.subscribed_at = None
        self.source = ""
        self.is_muted = False
        self.of_name = ""
        self.of_username = ""
        self.known: dict[str, str] = {}
        self.messages: list[tuple[str, str]] = []


def select_candidates(
    counts: dict[int, Candidate], *,
    force_ids: set[int], limit: int, promo_spam: set[int],
) -> list[Candidate]:
    qualifying: list[Candidate] = []
    for fan_id, c in counts.items():
        forced = fan_id in force_ids
        is_spam = not forced and (
            should_skip_muted_creator(c)
            # spend_cents is fresher than the lagging lifetime_spend column: this can only rescue a payer from the spam guard, never silence one.
            or (fan_id in promo_spam and c.spend_cents == 0)
        )
        qualified = forced or (
            not is_spam
            and (c.fan_msg_n >= QUAL_MIN_FAN_MSGS
                 or c.spend_cents >= QUAL_MIN_SPEND_CENTS)
        )
        if qualified:
            qualifying.append(c)

    # Forced ids sort first so the [:limit] slice never drops an explicit force.
    qualifying.sort(
        key=lambda x: (x.fan_id not in force_ids, -x.spend_cents, -x.fan_msg_n, x.fan_id))
    return qualifying[:max(limit, len(force_ids))]


def trim_messages(messages: list[tuple[str, str]], spender: bool = False) -> str:
    head = MSG_HEAD_SPENDER if spender else MSG_HEAD
    tail = MSG_TAIL_SPENDER if spender else MSG_TAIL
    fan_msgs = [(d, b) for d, b in messages if d == "in"]
    if len(fan_msgs) > (head + tail):
        fan_msgs = fan_msgs[:head] + fan_msgs[-tail:]
    lines = []
    for _direction, body in fan_msgs:
        if not body:
            continue
        lines.append(f"FAN: {body}")
    return "\n".join(lines)


def build_user_prompt(c: Candidate) -> str:
    history = trim_messages(c.messages, spender=c.spend_cents >= SPENDER_CENTS)
    disp = (c.of_name or "").strip()
    uname = (c.of_username or "").strip()
    name_line = f"Fan OF display name: {disp or '(unknown)'}"
    if uname and uname.lower() != disp.lower():
        name_line += f"  (username/handle: {uname} — a handle, NOT a real name)"
    return (
        f"{name_line}\n"
        f"Fan message count: {c.fan_msg_n}\n"
        f"Lifetime spend: ${c.spend_cents / 100:.2f}\n\n"
        f"{known_block(c)}"
        f"Chat history (oldest→newest):\n{history}\n"
    )



FACT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("real_name", "real_name", "str"),
    ("his_age", "his_age", "str"),
    ("home_country", "home_country", "str"),
    ("home_city", "home_city", "str"),
    ("hobbies", "hobbies", "str"),
    ("occupation", "occupation", "str"),
    ("relationship_status", "relationship_status", "str"),
    ("fetishes", "fetishes", "str"),
    ("employer", "employer", "str"),
    ("partner_name", "partner_name", "str"),
    ("relationship_stage", "relationship_stage", "str"),
    ("has_kids", "has_kids", "bool"),
    ("pets", "pets", "json_arr"),
    ("communication_style", "communication_style", "json_obj"),
)

# A sparse (empty) LLM response must not null out the stored nickname/bio.
PROFILE_KEEP_IF_EMPTY = frozenset((
    "nickname", "short_bio", "bullet_points", "original_name",
))


# Below this much fan text a language guess is not trusted (stays NULL = use account).
LANG_EVIDENCE_MIN_CHARS = 40
KNOWN_LANGS = frozenset((
    "en", "es", "sl", "pt", "fr", "de", "it", "nl", "ru", "pl", "tr", "ar",
    "sv", "no", "da", "fi", "cs", "ro", "hu", "el", "he", "ja", "ko", "zh",
))
LANG_NAME_MAP = {
    "english": "en", "spanish": "es", "español": "es", "espanol": "es",
    "slovenian": "sl", "slovene": "sl", "slovenščina": "sl",
    "portuguese": "pt", "french": "fr", "german": "de", "italian": "it",
}


def norm_lang(raw: Any) -> str:
    s = (raw or "")
    s = s.strip().lower() if isinstance(s, str) else ""
    if not s:
        return ""
    code = s.split("-")[0].split("_")[0]
    if code in KNOWN_LANGS:
        return code
    return LANG_NAME_MAP.get(s, "")


def enough_language_evidence(c: "Candidate") -> bool:
    chars = sum(len(b) for d, b in c.messages if d == "in" and b)
    return chars >= LANG_EVIDENCE_MIN_CHARS


def serialize_fact(kind: str, raw: Any) -> tuple[bool, Any]:
    if raw is None:
        return (False, None)
    # str(val) turned True into "True", which raises StatementError on a Boolean column and rolls back the persist.
    if kind == "bool":
        if isinstance(raw, bool):
            return (True, raw)
        s = str(raw).strip().lower()
        if s in ("true", "yes", "y", "1"):
            return (True, True)
        if s in ("false", "no", "n", "0"):
            return (True, False)
        return (False, None)
    if kind == "json_arr":
        if isinstance(raw, (list, tuple)):
            items = [x for x in raw if x not in (None, "", {}, [])]
            return (True, json.dumps(items, ensure_ascii=False)) if items else (False, None)
        s = str(raw).strip()
        if s and s != "[]":
            return (True, json.dumps([s], ensure_ascii=False))
        return (False, None)
    if kind == "json_obj":
        if isinstance(raw, dict):
            obj = {k: v for k, v in raw.items() if v not in (None, "", [], {})}
            return (True, json.dumps(obj, ensure_ascii=False)) if obj else (False, None)
        return (False, None)
    if isinstance(raw, (list, tuple)):
        val = ", ".join(str(x).strip() for x in raw if str(x).strip())
    else:
        val = raw.strip() if isinstance(raw, str) else str(raw).strip()
    return (True, val) if val else (False, None)



# An operator-pinned language is never overwritten by detection.
MANUAL_LANGUAGE_SOURCES: tuple[str, ...] = ("manual",)


@dataclass(frozen=True)
class PersistPlan:
    profile_set: dict
    fan_set: dict
    facts: dict
    events: dict
    write_lang: str | None


def plan_persist(c: Candidate, data: dict, *, call_id: int | None,
                 now: datetime) -> PersistPlan:
    nickname = guard_name(clean_nickname(data.get("nickname")), c)
    if not nickname:
        nickname = guard_name(clean_nickname(c.known.get("generated_nickname")), c)
    hint = name_hint(c)
    if hint and (not nickname or nickname.split("/")[0].strip().lower() != hint.lower()):
        nickname = clean_nickname(hint + "/" + nickname)
    original_name = blank_unknown(data.get("original_name") or data.get("real_name"))

    profile_set = dict(
        original_name=original_name or None,
        message_count_at_gen=c.fan_msg_n,
        total_spend_at_gen_cents=c.spend_cents,
        nickname=nickname or None,
        short_bio=as_text(data.get("short_bio")) or None,
        bullet_points=clean_bullets(data.get("bullet_points")) or None,
        last_generated_at=now,
        generated_by_grok_call_id=call_id,
    )

    fan_set: dict[str, Any] = {"grok_facts_updated_at": now,
                               "updated_at": now}
    facts: dict[str, Any] = {}
    for key, col, kind in FACT_FIELDS:
        ok, val = serialize_fact(kind, data.get(key))
        if ok:
            facts[col] = val
    if original_name and "real_name" not in facts:
        facts["real_name"] = original_name
    if nickname:
        fan_set["generated_nickname"] = nickname
    events: dict[str, Any] = {}
    new_events = parse_events(data.get("recent_events"))
    if new_events:
        prior_events = parse_events(c.known.get("recent_events"))
        fresh = [e for e in new_events if e not in prior_events]
        merged = prior_events + fresh
        events["recent_events"] = json.dumps(merged[:20], ensure_ascii=False)
        if fresh:
            try:
                prior_tl = json.loads(c.known.get("recent_events_timeline") or "[]")
                prior_tl = [t for t in prior_tl if isinstance(t, dict) and t.get("event")]
            except (json.JSONDecodeError, TypeError):
                prior_tl = []
            seen_ev = {t.get("event") for t in prior_tl}
            day = now.strftime("%Y-%m-%d")
            for e in fresh:
                if e not in seen_ev:
                    prior_tl.append({"date": day, "event": e})
            events["recent_events_timeline"] = json.dumps(prior_tl[-30:], ensure_ascii=False)

    # Written only past the evidence floor, never over a manual pin (per-column CASE guard in _persist).
    detected_lang = norm_lang(data.get("language"))
    write_lang = detected_lang if detected_lang and enough_language_evidence(c) else None

    return PersistPlan(
        profile_set=profile_set,
        fan_set=fan_set,
        facts=facts,
        events=events,
        write_lang=write_lang,
    )
