"""service/automations/gen_info_plan.py — the PURE half of gen_info (Automation 02).

Everything here is a deterministic function of its arguments: no DB session, no
LLM, no OF call. gen_info.py keeps the IO (`_gather_candidates`, `_persist`,
`_sync_of_fan_info`, `_enqueue_thin_fan_scrapes`, `run`) and re-exports the names
its importers still use under their old `_private` names.

Moved verbatim from gen_info.py (names lost their leading underscore). New here:
`plan_persist` / `PersistPlan` (the decision half of `_persist`) and
`MANUAL_LANGUAGE_SOURCES` (the operator-pinned language sources).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ._skiplist import should_skip_muted_creator
from .names import is_greetable_name, strip_spend_tier

# ── Knobs (ported from 02_gen_info.md) ───────────────────────────────
QUAL_MIN_FAN_MSGS = 1           # profile ANY fan who has written ≥1 message …
QUAL_MIN_SPEND_CENTS = 1        # …or spent anything (spend no longer gates; all in)
# Re-run cadence (spend-tiered). HARD GATE first: never (re)compile a profile until
# the fan has sent >= MIN_NEW_MSGS new inbound messages since the last generation
# (or >= that many total when never profiled) — no fresh chat ⇒ nothing new to mine
# ⇒ no LLM call. Once that gate is met, regenerate on EITHER a time window OR a
# new-message volume cap, both set by the fan's spend tier (tier_knobs): paying fans
# stay freshest, cold $0 fans back off. Replaces the old Fibonacci milestone ladder.
MIN_NEW_MSGS = 8                          # the gate: < this many new msgs ⇒ never recompile
NEW_SUB_WINDOW = timedelta(days=7)        # subbed within this ⇒ "new sub" (middle tier)
RECENT_SPEND_WINDOW = timedelta(days=7)   # cleared spend within this ⇒ "paying" tier
PAYING_LIFETIME_FLOOR_CENTS = 50000       # >= $500 lifetime ⇒ always paying (whale floor)
# (fresh_after, volume_cap) per tier — fresh_after = time-based refresh window,
# volume_cap = refresh after this many NEW inbound messages.
CADENCE_PAYING = (timedelta(days=2), 55)  # spent in last 7d OR >= $500 lifetime
CADENCE_MIDDLE = (timedelta(days=2), 89)  # new sub <7d OR lapsed payer (any lifetime spend)
CADENCE_COLD = (timedelta(days=7), 89)    # $0 lifetime and not a new sub
MSG_HEAD = 250                  # trim: keep first 250 …
MSG_TAIL = 250                  # … + last 250 when a chat exceeds 500
MSG_CLIP = 250                  # clip each message body to 250 chars
# Spenders get a WIDER window of the already-stored history fed to the model (we
# have it in the DB — use it), since their profile is worth more context.
MSG_HEAD_SPENDER = 500
MSG_TAIL_SPENDER = 500
SPENDER_CENTS = 5000            # ≥ $50 lifetime → "spender" → wider context window

HTML_OPEN = "<"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# ── Small text helpers (local copies — house pattern) ────────────────

def strip_html(s: str | None) -> str:
    if not s:
        return ""
    if HTML_OPEN not in s:
        return s.strip()
    return TAG_RE.sub("", s).strip()


def clean_nickname(s: str | None) -> str:
    """Drop empty + placeholder ('??') segments and any derived SPEND TIER, collapse
    slashes, trim. The model sometimes fills unknown slots with '??' despite the
    prompt (W2h).

    The tier strip is here rather than at one call site because every path through
    this module runs through this function, and the one that matters most is the
    READ: `known_block` hands the stored nickname back to the model as ground truth
    to 'refine + keep complete', so a legacy '/Free' would be copied forward into
    every regeneration for the rest of the fan's life. Stripping on the way in AND
    on the way out means a fan heals on his next profile pass instead of needing a
    sweep. See names.strip_spend_tier for why the tier was retired."""
    if not s:
        return ""
    parts = [p.strip() for p in strip_spend_tier(s).split("/")]
    parts = [p for p in parts if any(ch.isalnum() for ch in p)]   # drop empty/'??'/',' slots
    return WS_RE.sub(" ", "/".join(parts)).strip()


def blank_unknown(s: Any) -> str:
    """Grok may emit 'Unknown' for original_name → treat as blank (02 edge case)."""
    s = (s or "")
    s = s.strip() if isinstance(s, str) else str(s)
    return "" if s.lower() in ("unknown", "n/a", "none") else s


def as_text(v: Any) -> str:
    """Coerce a profile text field to a plain string for the TEXT column. The model
    sometimes returns a multi-line field (notably bullet_points) as a JSON ARRAY of
    lines instead of a string — join those with newlines rather than letting a list
    reach the DB (sqlite bind error 'type list is not supported')."""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip() if not isinstance(v, str) else v


# An "empty" bullet line: a label with no value after the colon, e.g. "- Job:",
# "Rel:", "* Kinks: " (model emits these despite the empty-string instruction).
EMPTY_BULLET_RE = re.compile(r"^[-*\s]*[A-Za-z][\w /]*:\s*$")


def clean_bullets(v: Any) -> str:
    """bullet_points → text with EMPTY label-only lines dropped (skip empty fields).
    Handles the JSON-array shape via as_text first, then filters blank-value lines
    so a stored bullet block never carries a bare 'Job:' / 'Rel:' / 'Kinks:'."""
    text = as_text(v)
    if not text:
        return ""
    lines = [
        ln for ln in (l.rstrip() for l in text.split("\n"))
        if ln.strip() and not EMPTY_BULLET_RE.match(ln.strip())
    ]
    return "\n".join(lines)


def parse_events(raw: Any) -> list[str]:
    """recent_events is a JSON-array TEXT column (default '[]'). Parse defensively
    to a list of non-empty strings (W2h)."""
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
    """This fan's own stored location — never his name. Passed to is_greetable_name
    so a city no static list can hold ('Millbrook') is caught for THIS fan."""
    return (c.known.get("home_country"), c.known.get("home_city"))


def guard_name(nickname: str, c: "Candidate") -> str:
    """Blank the Name slot (first '/'-segment) when it isn't a real first name —
    `is_greetable_name`, the same predicate the senders greet by: a digit-handle
    (111222333, T900, Sparky10, u7654321, the fan id), junk with no letters (',',
    '.'), a place, or this fan's own city/country. With no name to be found the
    model writes the COUNTRY into the Name slot ('Canada/Canada/office job'), which
    every downstream sender then greeted him by. The name_hint fallback re-adds a
    real OF name afterwards (W2h) — it uses the same predicate, so it cannot hand
    back what this just dropped."""
    if not nickname:
        return nickname
    parts = nickname.split("/")
    name = parts[0].strip()
    if not name:
        return nickname
    if is_greetable_name(name, here=_here(c)):
        return nickname
    parts[0] = ""                       # drop the bad name; keep the rest of the tag
    return clean_nickname("/".join(parts))


def name_hint(c: "Candidate") -> str:
    """A real first name to anchor the nickname — prefer the chat-extracted real
    name, then the OF display name, then the OF USERNAME. `is_greetable_name` decides
    what qualifies (same predicate as guard_name and the senders), so a bare number
    or the fan id is never used and digit-handles ('T900', 'Sparky10', 'u7654321',
    'gamer4you'), junk ('.', 'C') and PLACES are skipped. Without the place check
    this handed straight back what guard_name had just dropped: a fan whose OF
    display name is 'Canada' got 'Canada' re-installed as his name one line later.
    The username fallback means a fan whose display name is just their numeric id but
    whose handle is a real word (e.g. id 111222333 / name 'sam k' → 'Sam') gets a
    name, never a number. Capitalised (real name/username used, never digits)."""
    for src in (c.known.get("real_name", ""), c.of_name, c.of_username):
        s = (src or "").strip()
        tok = s.split(" ")[0].strip(".,/") if s else ""
        if len(tok) >= 2 and tok.isalpha() and is_greetable_name(tok, here=_here(c)):
            return tok[:1].upper() + tok[1:]
    return ""


# The nickname's spend tier (`_spend_tier`, and the Bonus slot it filled) is gone —
# see names.strip_spend_tier. `c.spend_cents` is still gathered: tier_knobs below
# spends the PROFILING BUDGET by spend tier, which is a live decision made fresh on
# every pass. That is the difference — a tier is fine to compute, and was only ever
# harmful once it got frozen into a label a human reads days later.
def tier_knobs(lifetime_cents: int, recent_cents: int,
                subscribed_at: "datetime | None", now: datetime) -> tuple:
    """(fresh_after, volume_cap) for a fan, by spend tier — spend the profiling
    budget where the money is. PAYING (spent in the last RECENT_SPEND_WINDOW, or a
    >= $500 lifetime whale) gets the freshest cadence; MIDDLE (a new sub, or a lapsed
    payer with any lifetime spend) the default; COLD ($0 and not new) the laziest.
    First match wins."""
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
    """Should this fan's profile be regenerated? Shared with welcome_chatter_for_info's
    refresh-if-stale hook. `fresh_after`/`volume_cap` come from tier_knobs (the
    caller classifies the fan's spend tier); they default to the MIDDLE tier.

    HARD GATE: returns False unless >= MIN_NEW_MSGS new inbound messages have arrived
    since the last generation (or >= that many total when never profiled) — no fresh
    chat ⇒ nothing to re-mine ⇒ no LLM call. Past the gate, regenerate when never
    profiled, when `volume_cap` new messages have piled up, or when the profile is
    older than `fresh_after`.

    There is no exemption. The gate used to be skipped when a fan's Q- or Tease-lines
    ran out, to refill them; gen_info writes no lines now, so that signal would be
    true for ever and buy an LLM call on every new message."""
    nc = int(now_count)
    prev = int(prev_count) if prev_count is not None else 0
    new_msgs = nc - prev
    if new_msgs < MIN_NEW_MSGS:           # the gate — too little new chat to bother
        return False
    if prev_count is None:                 # never profiled, now past the gate
        return True
    if new_msgs >= volume_cap:             # volume: every `volume_cap` new messages
        return True
    if last_gen_at is not None and (now - last_gen_at) >= fresh_after:  # time
        return True
    return False


def known_block(c: "Candidate") -> str:
    """KNOWN INFO (ground truth) from prior stored facts so the model BUILDS ON what
    we already learned + keeps the nickname complete (W2h). '' when nothing known."""
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


# ── Candidate selection ──────────────────────────────────────────────

class Candidate:
    __slots__ = ("fan_id", "fan_msg_n", "total_msg_n", "spend_cents",
                 "recent_spend_cents", "subscribed_at",
                 "source", "is_muted", "of_name", "of_username", "known", "messages")

    def __init__(self, fan_id: int):
        self.fan_id = fan_id
        self.fan_msg_n = 0
        self.total_msg_n = 0
        self.spend_cents = 0
        self.recent_spend_cents = 0          # cleared spend in the last RECENT_SPEND_WINDOW
        self.subscribed_at = None            # fans.subscribed_at — for the new-sub tier
        self.source = ""    # "fan" = subscribedOn (real fan); else peer creator/unknown
        self.is_muted = False  # OF chat muted — a muted creator is spam, never profile
        self.of_name = ""
        self.of_username = ""
        # Prior extracted facts from the fans row — fed back as ground truth so
        # profiles ACCRETE and the nickname stays complete (W2h). DB-only, no OF call.
        self.known: dict[str, str] = {}
        self.messages: list[tuple[str, str]] = []  # (direction, body)


def select_candidates(
    counts: dict[int, Candidate], *,
    force_ids: set[int], limit: int, promo_spam: set[int],
) -> list[Candidate]:
    """Pure, read-only half of _gather_candidates: the spam guard + qualification
    gate, then the forced-first, spend-desc order capped at max(limit, #forced)."""
    qualifying: list[Candidate] = []
    for fan_id, c in counts.items():
        forced = fan_id in force_ids
        # Promo-spam guard (shares welcome_chatter_for_info's rule): don't waste an LLM profile
        # on peer creators who blast the inbox. Either we've MUTED their chat (a
        # deliberate "silence this creator" — never profile one even if they once
        # paid), or they're in the account's promo-blaster set.
        #
        # The old test was `creator_we_follow` + $0, on the belief that "real fans
        # are NEVER this value". That was false — the flag only means OF says we're
        # subscribed to them, which is true of any fan a free page followed back —
        # and it silently stopped profiling 71 real fans on one live account.
        # Re-evaluated each run.
        #
        # `c.spend_cents` re-checks the spend the SET already tested, deliberately:
        # the set reads `fans.lifetime_spend_cents`, which LAGS ingest, while
        # c.spend_cents is the fresher max(ledger, paid-PPV) this pass already
        # computed. Live now: 9 of Ava's fans have real spend the column still
        # reports as $0. Narrowing here can only ever RESCUE a payer from the guard,
        # never silence one — the direction a spam gate must always fail in.
        is_spam = not forced and (
            should_skip_muted_creator(c)
            or (fan_id in promo_spam and c.spend_cents == 0)
        )
        qualified = forced or (
            not is_spam
            and (c.fan_msg_n >= QUAL_MIN_FAN_MSGS
                 or c.spend_cents >= QUAL_MIN_SPEND_CENTS)
        )
        if qualified:
            qualifying.append(c)

    # Stable, deterministic order; cap the sweep so a tick stays bounded. Forced ids
    # sort FIRST so they always survive the `[:limit]` slice: the rest of the order is
    # spend-desc, so a $0 fan on a big roster ranks below the cap and would otherwise be
    # truncated away — an explicit force (the composer's "Generate new batch") must never
    # be silently dropped just because the fan is poor.
    qualifying.sort(
        key=lambda x: (x.fan_id not in force_ids, -x.spend_cents, -x.fan_msg_n, x.fan_id))
    return qualifying[:max(limit, len(force_ids))]


def trim_messages(messages: list[tuple[str, str]], spender: bool = False) -> str:
    """Fan-only transcript: head + tail window (02 build_prompt). Spenders get a
    WIDER window (500+500 vs 250+250) — we already have the history in the DB, so a
    high-value fan's profile gets more of it; everyone else stays at the default.

    V1 fed Grok the FAN side only and produced sharper profiles, so we drop the
    creator's outbound lines (direction != "in") before trimming — the head/tail
    window then counts fan messages, not the mixed stream."""
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


# ── Persistence ──────────────────────────────────────────────────────

# The extracted facts written back onto the `fans` row, as (json_key, column, kind).
# `kind` drives per-type serialization so a bool/JSON field never reaches the DB as a
# Python repr: the naive `str(val)` path turned has_kids=False into "" (dropped) and
# a bool True into the string "True", which RAISES StatementError on a Boolean column
# and rolls back the whole persist. Adding a field here is now type-safe.
#   str      → cleaned text ("" ⇒ skip); a list is comma-joined
#   bool     → real True/False from yes/no/true/false/1/0 ("unknown"/"" ⇒ skip)
#   json_arr → json.dumps(list)   ("[]"/empty ⇒ skip)
#   json_obj → json.dumps(dict)   ({}/empty ⇒ skip)
FACT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("real_name", "real_name", "str"),
    ("his_age", "his_age", "str"),
    ("home_country", "home_country", "str"),
    ("home_city", "home_city", "str"),
    ("hobbies", "hobbies", "str"),
    ("occupation", "occupation", "str"),
    ("relationship_status", "relationship_status", "str"),
    ("fetishes", "fetishes", "str"),
    # ── Richer facts (R1): fill columns gen_info never wrote before. ──
    ("employer", "employer", "str"),
    ("partner_name", "partner_name", "str"),
    ("relationship_stage", "relationship_stage", "str"),
    ("has_kids", "has_kids", "bool"),
    ("pets", "pets", "json_arr"),
    ("communication_style", "communication_style", "json_obj"),
)

# Profile columns that must be KEPT when the LLM returns them empty (FIX-2): a sparse
# response (~7% are fully empty) must NOT null out a fan's stored nickname / bio.
# These are guarded in the upsert set_. The q1-3 / tease1-3 columns are not written
# at all any more, so old stored lines are left as they are.
PROFILE_KEEP_IF_EMPTY = frozenset((
    "nickname", "short_bio", "bullet_points", "original_name",
))


# ── Language detection (R1) ──────────────────────────────────────────
# gen_info DETECTS the fan's language and stores it as an observation (source="ai").
# It does NOT yet drive routing — the bot's output language is the ACCOUNT default
# (resolve_language) until per-fan routing is switched on. So a wrong detection is a
# display/collection error, never a mis-route. Two guards make it safe:
#   • EVIDENCE FLOOR — need real fan text before trusting a guess (44 fans have zero
#     inbound; 19.7% have < 400 chars). Below the floor ⇒ leave NULL ⇒ "use account".
#   • MANUAL WINS — never overwrite a language an operator pinned (language_source
#     == "manual"). Enforced per-column in the upsert CASE, not a row-level where=.
LANG_EVIDENCE_MIN_CHARS = 40          # min inbound fan text before we trust detection
KNOWN_LANGS = frozenset((             # ISO 639-1 we accept; others ⇒ leave NULL
    "en", "es", "sl", "pt", "fr", "de", "it", "nl", "ru", "pl", "tr", "ar",
    "sv", "no", "da", "fi", "cs", "ro", "hu", "el", "he", "ja", "ko", "zh",
))
LANG_NAME_MAP = {                      # tolerate a name if the model ignores "ISO code"
    "english": "en", "spanish": "es", "español": "es", "espanol": "es",
    "slovenian": "sl", "slovene": "sl", "slovenščina": "sl",
    "portuguese": "pt", "french": "fr", "german": "de", "italian": "it",
}


def norm_lang(raw: Any) -> str:
    """Normalize a model language value to a known ISO 639-1 code, else "". Accepts
    'es', 'ES', 'es-MX', or a language NAME ('Spanish'); rejects anything unknown so a
    junk value never becomes a routing key."""
    s = (raw or "")
    s = s.strip().lower() if isinstance(s, str) else ""
    if not s:
        return ""
    code = s.split("-")[0].split("_")[0]           # 'es-MX' → 'es'
    if code in KNOWN_LANGS:
        return code
    return LANG_NAME_MAP.get(s, "")


def enough_language_evidence(c: "Candidate") -> bool:
    """True when the fan has written enough text to trust a language guess."""
    chars = sum(len(b) for d, b in c.messages if d == "in" and b)
    return chars >= LANG_EVIDENCE_MIN_CHARS


def serialize_fact(kind: str, raw: Any) -> tuple[bool, Any]:
    """(should_write, typed_value) for one extracted fact. Never returns should_write
    for an empty/unknown value, so a sparse run never clobbers a prior fact. See
    FACT_FIELDS for the kinds. This is the single guard against binding a Python repr
    (dict/bool) to a typed column."""
    if raw is None:
        return (False, None)
    if kind == "bool":
        if isinstance(raw, bool):
            return (True, raw)
        s = str(raw).strip().lower()
        if s in ("true", "yes", "y", "1"):
            return (True, True)
        if s in ("false", "no", "n", "0"):
            return (True, False)
        return (False, None)                     # "unknown"/"" ⇒ leave the column alone
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
    # str (default): flatten a list to a comma-joined string.
    if isinstance(raw, (list, tuple)):
        val = ", ".join(str(x).strip() for x in raw if str(x).strip())
    else:
        val = raw.strip() if isinstance(raw, str) else str(raw).strip()
    return (True, val) if val else (False, None)


# ── Persist plan (pure half of gen_info._persist) ────────────────────

# Operator-pinned language sources: gen_info._persist keeps the STORED language when
# fans.language_source is one of these (FIX-3 "manual wins").
MANUAL_LANGUAGE_SOURCES: tuple[str, ...] = ("manual",)


@dataclass(frozen=True)
class PersistPlan:
    """What gen_info._persist writes for ONE fan, decided without the DB. The
    race-safe rules that compare against the row AS STORED (keep-if-empty on
    fan_profiles, the manual-language pin) stay SQL CASEs in _persist."""
    profile_set: dict    # fan_profiles values minus identity (account_id, fan_id)
    fan_set: dict        # fans timestamps (grok_facts_updated_at, updated_at) + generated_nickname
    facts: dict          # typed FACT_FIELDS columns (+ real_name from original_name); empty ⇒ absent
    events: dict         # recent_events (+ recent_events_timeline when something is new); {} if none
    write_lang: str | None  # detected ISO 639-1 code to offer past the evidence floor; None ⇒ don't write


def plan_persist(c: Candidate, data: dict, *, call_id: int | None,
                 now: datetime) -> PersistPlan:
    """Pure decision half of gen_info._persist: nickname guard + name hint, profile
    values, typed facts, recent_events merge + dated timeline, detected language
    past the evidence floor. Every value is derived from THIS candidate `c` and its
    own `data`."""
    nickname = guard_name(clean_nickname(data.get("nickname")), c)
    if not nickname:                       # AI gave nothing usable → keep the old one
        nickname = guard_name(clean_nickname(c.known.get("generated_nickname")), c)
    # Anchor the nickname with the fan's REAL name (the model often drops it even
    # though OF gives us of_display_name). Prepend the hint unless it's already lead.
    hint = name_hint(c)
    if hint and (not nickname or nickname.split("/")[0].strip().lower() != hint.lower()):
        nickname = clean_nickname(hint + "/" + nickname)
    # A name-only nickname ("Mani") now STAYS name-only. It used to get a derived
    # spend tier appended as a Bonus slot ("Mani" → "Mani/Spender") so the label
    # "carried a useful flag" — but the flag was stamped once and never re-derived,
    # so it aged into a lie in the one place the team reads it. A bare name is a
    # thin label; a confidently wrong tier is a harmful one.
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

    # Extracted facts → fans columns. Only overwrite with a non-empty value so a
    # later sparse generation never wipes a fact an earlier one found.
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
    # recent_events: merge new events onto the prior list (accrete, dedup, cap 20)
    # and store as the JSON-array TEXT column (NOT NULL default '[]'). Only write
    # when non-empty so a sparse run never clears prior events.
    new_events = parse_events(data.get("recent_events"))
    if new_events:
        prior_events = parse_events(c.known.get("recent_events"))
        fresh = [e for e in new_events if e not in prior_events]
        merged = prior_events + fresh
        events["recent_events"] = json.dumps(merged[:20], ensure_ascii=False)
        # Dated timeline (step 6): stamp each NEWLY-learned event with today's date and
        # accrete onto the prior timeline (keeps old dates), newest last, cap 30. Read by
        # none of the six recent_events readers — the flat list above is untouched.
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

    # Language: a detected observation (source="ai"), written only past the evidence
    # floor and NEVER over an operator's manual pin. Kept out of the fans SET because it
    # needs a per-column CASE guard (in _persist), not a plain overwrite.
    detected_lang = norm_lang(data.get("language"))
    write_lang = detected_lang if detected_lang and enough_language_evidence(c) else None

    return PersistPlan(
        profile_set=profile_set,
        fan_set=fan_set,
        facts=facts,
        events=events,
        write_lang=write_lang,
    )
