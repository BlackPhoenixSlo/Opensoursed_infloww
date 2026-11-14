"""automations/_router_jev.py — Full AI Chat's Router questions and the one Jev call.

Not a stream: it registers no kind and holds no outbound primitive (ADR-0033).
On every Turn the shadow runner (`full_ai_chat`) asks Jev (TypeSafe's System
One model) every Router question in ONE request; the pure Route table
(`full_ai_decide.decide_turn`) maps the answers to a Route (ADR-0032). Every
question's wording, its criteria, the thresholds, the `intensity` levels and
the model pin live in this module and nowhere else, so a wording change is a
data edit the owner can audit (spec story 21), and `QUESTION_VERSION` (a
digest of all of them and of the state's shape) goes on every Decision row
(story 22).

Wording: the strings the thresholds were measured on, letter for letter
(`.scratch/full-ai-chat/research/jevprobe/probe.py`, the R7 freeze in
`.scratch/full-ai-chat/DECISIONS.md`): `wants_content`, `declines_buying` and
`says_yes_to_offer` its B variant, `complains_now` its `complains_purchase` A,
every other question and the `intensity` Score its A; `gif_fits` (not probed
yet, ticket 23) from `.scratch/full-ai-chat/OWNER-REVIEW-router.md` item 12.
The owner approves that review, which shows these strings (D28). Request
shape: the probe's.

  - `QUESTIONS`, `THRESHOLDS`, `INTENSITY`, `STATE_VERSION`,
    `QUESTION_VERSION` (`question_version()`).
  - `fired(answers)`: the ids at or above their threshold.
  - `line_text(m)`: one stored message as a person reads it (`MEDIA_ONLY`,
    `GIF_ONLY` with no text).
  - `thread`, `her_last_line`, `last_purchase`, `pending_offer`: the rest of
    the state in the probe's words, from stored rows (pure).
  - `state(...)`: the Jev state (spec › Contracts).
  - `ask(state, account_id)`: one request; `Answers`, or `GateError` on any
    failure (no key, no SDK, timeout, HTTP error, a missing or out-of-range
    answer or Score). A failed call is an error, never a "no".

The key is the Creator's agency's own TypeSafe key, else the deployment's
`TYPESAFE_API_KEY` (`tenant_keys.typesafe_key_for`); `TYPESAFE_BASE_URL` (the
SDK's own env) moves the endpoint. `_client` is the tests' fake seam over the
shared transport (`_jev.client`).
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from automations import _jev
from of_shapes import giphy_dm_id   # stdlib-only OF payload-shape reader

if TYPE_CHECKING:  # annotation only: no DB import at runtime
    from db.models import Message, Transaction

# A versioned id, not `jev-latest`: the thresholds were probed on it.
MODEL = "jev-1.14.0"
# Total budget per call, retries included (the SDK's RetryPolicy.timeout).
TIMEOUT_S = 10.0
MAX_RETRIES = 1
# Chat lines before his Turn that Jev reads as `thread` (probe.py).
THREAD_LINES = 12
# The one named D32 exception in PR1 (spec › Contracts): past this many days
# his last purchase reads as none, as in the probe the thresholds were measured on.
PURCHASE_DAYS = 7
PURCHASE_KINDS = ("tip", "ppv_message", "ppv_post")
# Bump by hand on any change to how stored rows map to the Jev state (`thread`,
# `her_last_line`, `last_purchase`, `pending_offer`, `state`, `line_text`'s
# words, `full_ai_chat.build_state` and the reads feeding it).
STATE_VERSION = 1


_q = _jev.q


# The Nouls, by id, in the owner review's order (items 1-10, 12). Ids are for
# code; Jev reads only the wording.
QUESTIONS: dict[str, dict[str, Any]] = {
    "promo": _q(
        "Is `fan_new_messages` an advertisement for someone else's page or account?",
        "It promotes another creator, page, link or service, like a promo or spam bot",
        "He is talking to her about himself, about her, or about their chat"),
    "says_under_18": _q(
        "In `thread` or `fan_new_messages`, does the fan say that he himself is under 18 years old?",
        "He gives his own age as under 18, says he is a minor, in middle or high school, or not 18 yet",
        "He says he is 18 or older, gives no age, or mentions the age of someone else"),
    "complains_now": _q(
        "In `fan_new_messages`, is the fan unhappy about something he paid her for?",
        "He says he paid and got nothing, that what he paid for was already his or is free on her "
        "page, that he was charged twice, or that what he bought was disappointing: too tame, too "
        "short, too few, or not what she said it was",
        "He praises what he got, wants more or different content, haggles, says he is broke, "
        "flirts, or is unhappy about something he never paid for"),
    "asks_if_ai": _q(
        "Does the fan ask or suggest that she is a bot or an AI rather than a real person?",
        "He asks if she is real, a bot, an AI or ChatGPT, or says her replies sound automated or "
        "copy-pasted",
        "He talks to her as the real person she is, even if he asks personal questions"),
    "stop": _q(
        "Does the fan ask her to stop messaging him or to pause contact?",
        "He says stop, leave me alone, stop messaging me, no more of these messages, unsubscribe, "
        "or asks her not to message him for a while",
        "He keeps the chat going, even if he is short or rude, says he is not buying, or says he "
        "is busy and will talk later"),
    "price": _q(
        "Does the fan ask about a price, or what something costs?",
        "He asks how much, what it costs, the price, or what he would pay for something",
        "He says nothing about prices or paying"),
    "wants_content": _q(
        "In `fan_new_messages`, does the fan say he wants to see or get her photos, videos or body now?",
        "He says show me, send me, let me see, can I see, I want to see your body or a part of it, or "
        "asks where her content is or how to unlock it",
        "He only compliments her, says what he would do to her, asks what kind of content she makes, "
        "or offers to send her his own pics"),
    "declines_buying": _q(
        "In `fan_new_messages`, does the fan say he will not pay or cannot pay her for something?",
        "He says no to buying, that he has no money or cannot afford it, that it costs too much or is "
        "not worth the money, or that he only wants to chat and not pay",
        "He asks for her content or a price, agrees to buy, says goodbye or is sad without mentioning "
        "paying, or does not mention buying or money"),
    "says_yes_to_offer": _q(
        "In `fan_new_messages`, does the fan accept what she offers or teases in `pending_offer`?",
        "He says yes, send it, he wants it, he will unlock or buy it, asks her to show him what she "
        "teased, or says he already unlocked it",
        "He turns it down, ignores it and talks about something else, or only asks what it is"),
    "sexual_now": _q(
        "In `fan_new_messages`, does the fan talk about sex or bodies in a sexual way?",
        "He talks about sex, being turned on, what he would do to her, or her body or his in a "
        "sexual way",
        "He talks about everyday things, compliments her without anything sexual, or asks a "
        "plain question"),
    # ASSUMPTION: `gif_fits` (no probe string yet) is the review's item 12 in
    # the probe's form (first letter capitalised, no final period), as every
    # measured line is. Overturned by ticket 23's measured wording.
    "gif_fits": _q(
        "Would a cute reaction GIF from her fit as part of this reply?",
        "Light, playful or warm moment; he greets her, jokes, flirts or reacts with emotion, and "
        "nothing shows he dislikes her GIFs",
        "He is upset or complaining, asks something serious, is mid explicit sext, or earlier "
        "reacted badly to her GIFs"),
}

# At or above its threshold a question fires (the R7 freeze). `gif_fits` is a
# DRAFT, asked and kept, never read by the Route table (story 24).
THRESHOLDS: dict[str, float] = {
    "promo": 0.7, "says_under_18": 0.7, "complains_now": 0.5, "asks_if_ai": 0.7,
    "stop": 0.6, "price": 0.7, "wants_content": 0.7, "declines_buying": 0.5,
    "says_yes_to_offer": 0.7, "sexual_now": 0.7, "gif_fits": 0.6,
}

# The Score that sets Heat: its levels 0-4, in order (item 11).
INTENSITY: dict[str, Any] = {
    "instructions": "How sexual is what the fan writes in `fan_new_messages`?",
    "criteria": [
        "He writes about everyday things, with no flirting",
        "He flirts or compliments her looks, with nothing sexual",
        "He is suggestive: he hints at sex or teases without saying it outright",
        "He talks explicitly about sex: what he wants to do with her or to see",
        "He describes graphic sex acts in detail",
    ],
}

def question_version() -> str:
    """A short digest of what changes what Jev answers: the model, the wording,
    thresholds and levels, and the state's shape (`STATE_VERSION`, the
    `THREAD_LINES`, `PURCHASE_DAYS` and `PURCHASE_KINDS` it reads)."""
    return hashlib.sha256(json.dumps(
        {"model": MODEL, "questions": QUESTIONS, "thresholds": THRESHOLDS, "intensity": INTENSITY,
         "state_version": STATE_VERSION, "thread_lines": THREAD_LINES,
         "purchase_days": PURCHASE_DAYS, "purchase_kinds": sorted(PURCHASE_KINDS)},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


QUESTION_VERSION = question_version()


class GateError(Exception):
    """Jev could not judge (no key, no SDK, timeout, an HTTP error, a missing or
    out-of-range answer or Score). Never read as an answer."""


class Answers(NamedTuple):
    answers: dict[str, float]       # question id -> P(yes), as Jev gave it
    intensity: float                # the Score, 0..4
    intensity_p: dict[str, float]   # level -> probability
    model: str | None               # the model id Jev reports
    ms: int                         # the call's wall time


def fired(answers: dict[str, float]) -> frozenset[str]:
    """The question ids at or above their threshold."""
    return frozenset(q for q, t in THRESHOLDS.items() if answers[q] >= t)


# How a message with no text reads. His media DM and every word below but
# `GIF_ONLY` are the probe's (probe.py:61-115), letter for letter: the
# thresholds were measured on them. A Giphy DM, which OF sends with `media: []`
# and `mediaCount: 0` (of_shapes.giphy_dm_id), is new words in `MEDIA_ONLY`'s shape.
MEDIA_ONLY = _jev.MEDIA_ONLY          # his photo or video
GIF_ONLY = "[sent a GIF]"
HER_MEDIA = "[photo or video]"
LOCKED = "[locked message]"           # her priced message with no words
REACTION = {"image_reply": "[she sent him a pic back]", "tip_reward": "[she sent him his tip reward]"}


def _giphy(raw_json: str | None) -> bool:
    try:
        return bool(raw_json) and giphy_dm_id(json.loads(raw_json)) is not None
    except ValueError:
        return False


def line_text(m: Message) -> str:
    """A stored message as a person reads it (OF bodies are HTML), untruncated
    (probe.py `text`); with no text, `MEDIA_ONLY` (hers `HER_MEDIA`) or `GIF_ONLY`."""
    t = _jev.text(m.body)
    if t:
        return t
    if m.media_count:
        return HER_MEDIA if m.direction == "out" else MEDIA_ONLY
    return GIF_ONLY if _giphy(m.raw_json) else ""


def _when(minutes: float) -> str:
    if minutes < 10:
        return "minutes before"
    if minutes < 120:
        return "within the last two hours"
    if minutes < 24 * 60:
        return "earlier the same day"
    return "days before"


def _minutes(at: datetime, t0: datetime) -> float:
    return (t0 - at).total_seconds() / 60


def _bought(m: Message) -> bool:
    return bool(m.is_paid) or m.purchased_at is not None


def _ppv(m: Message) -> str | None:
    if m.direction != "out" or not m.price_cents:
        return None
    return f"locked ${m.price_cents / 100:.0f} message, he {'bought it' if _bought(m) else 'has not bought it'}"


def thread(rows: list[Message], t0: datetime) -> list[dict[str, Any]]:
    """The chat lines `rows` (stored messages, oldest first) as Jev reads them,
    each `when` before `t0` (his Turn's first message) and, on her priced
    message, its `ppv` note; a line with nothing to read is left out
    (probe.py `build_state`)."""
    out = []
    for m in rows:
        her = m.direction == "out"
        e = {"from": "her" if her else "fan",
             "text": (REACTION.get(m.automation_kind) if her else None)
             or line_text(m),
             "when": _when(_minutes(m.created_at, t0))}
        p = _ppv(m)
        if p:
            e["ppv"] = p
        elif not e["text"]:
            continue
        if not e["text"]:
            e["text"] = LOCKED
        out.append(e)
    return out


def her_last_line(rows: list[Message]) -> str:
    """Her newest line in `rows` with words or a price, with its `ppv` note, else
    "none" (probe.py `build_state`)."""
    outs = [m for m in rows if m.direction == "out" and (line_text(m) or m.price_cents)]
    if not outs:
        return "none"
    m = outs[-1]
    p = _ppv(m)
    return (line_text(m) or LOCKED) + (f" ({p})" if p else "")


def _ago(minutes: float) -> str:
    if minutes < 60:
        return f"{int(minutes)} minutes ago"
    if minutes < 48 * 60:
        return f"about {round(minutes / 60)} hours ago"
    return f"about {round(minutes / 1440)} days ago"



def last_purchase(tx: Transaction | None, t0: datetime) -> str:
    """His last purchase `tx` (a `PURCHASE_KINDS` row), aged from `t0` (his
    Turn's first message; one inside his Turn reads 0 minutes), else
    "none in the last 7 days" (probe.py `build_state`)."""
    minutes = max(0.0, _minutes(tx.occurred_at, t0)) if tx is not None else None
    if minutes is None or minutes > PURCHASE_DAYS * 1440:
        return "none in the last 7 days"
    what = "tipped her" if tx.kind == "tip" else "bought a locked message for"
    return f"he {what} ${tx.amount_cents / 100:.0f}, {_ago(minutes)}"


def pending_offer(m: Message | None) -> str:
    """The Pending offer `m` (her priced, unbought message), with its caption,
    else "none" (probe.py `build_state`)."""
    if m is None:
        return "none"
    cap = line_text(m)
    return f"locked ${m.price_cents / 100:.0f} message{': ' + cap if cap else ''}"


def state(fan_messages: list[str], thread: list[dict[str, Any]], her_last_line: str,
          last_purchase: str, pending_offer: str) -> dict[str, Any]:
    """The Jev state: his Turn untruncated, the lines before it, her last line,
    his last purchase and the Pending offer (probe.py `build_state`)."""
    return {
        "fan_new_messages": [t for t in fan_messages if t],
        "thread": list(thread),
        "her_last_line": her_last_line,
        "last_purchase": last_purchase,
        "pending_offer": pending_offer,
    }


def _client(key: str) -> Any:
    """One async client per event loop and key (`_jev.client`)."""
    return _jev.client(key, MODEL, TIMEOUT_S, MAX_RETRIES)


def _questions() -> dict[str, Any]:
    from typesafe_sdk import Noul, Score
    q: dict[str, Any] = {qid: Noul(instructions=v["instructions"], criteria=v["criteria"])
                         for qid, v in QUESTIONS.items()}
    q["intensity"] = Score(instructions=INTENSITY["instructions"], criteria=INTENSITY["criteria"])
    return q


async def ask(st: dict[str, Any], account_id: str | None = None) -> Answers:
    """Ask every Router question and the `intensity` Score over `st` in one
    request, on `account_id`'s TypeSafe key. Raises `GateError` on any failure."""
    from tenant_keys import typesafe_key_for
    try:
        key = await typesafe_key_for(account_id)   # DB reads: may raise
        if not key:
            raise GateError("no TypeSafe key (agency or TYPESAFE_API_KEY)")
        # ASSUMPTION: Jev wall time is the request alone (SDK retries included),
        # not the key read before it. Overturned if p95 should include the DB.
        t0 = time.perf_counter()
        res = await _client(key).system_one(st, _questions(), model=MODEL)
        ms = int((time.perf_counter() - t0) * 1000)
        answers = {qid: float(res.nouls[qid].noul) for qid in QUESTIONS}
        bad = [q for q, p in answers.items() if not 0.0 <= p <= 1.0]   # NaN fails too
        if bad:
            raise GateError(f"answer out of range: {bad}")
        sc = res.scores["intensity"]
        intensity = float(sc.score)
        if not 0.0 <= intensity <= 4.0:
            raise GateError(f"intensity out of range: {intensity}")
        p = {str(k): float(v) for k, v in (sc.probabilities or {}).items()}
    except GateError:
        raise
    except Exception as e:      # SDK missing, HTTP, timeout, a missing answer
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    return Answers(answers, intensity, p, getattr(res, "model", None), ms)
