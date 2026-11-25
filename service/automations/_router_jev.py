from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from automations import _jev
from automations.full_ai_mode import full
from of_shapes import giphy_dm_id

if TYPE_CHECKING:
    from db.models import Message, Transaction

MODEL = "jev-1.14.0"
TIMEOUT_S = 10.0
MAX_RETRIES = 1
WALL_S = TIMEOUT_S * (1 + MAX_RETRIES)
THREAD_LINES = 12
PURCHASE_DAYS = 7
PURCHASE_KINDS = ("tip", "ppv_message", "ppv_post")
# Bump by hand on any change to how stored rows map to the Jev state.
STATE_VERSION = 1


_q = _jev.q


# Wording is what the thresholds were measured on, letter for letter; a reword needs a re-probe.
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
    # Routes nothing (owner: ignore "broke"); only cues the Writer's joke.
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
    "gif_fits": _q(
        "Would a cute reaction GIF from her fit as part of this reply?",
        "Light, playful or warm moment; he greets her, jokes, flirts or reacts with emotion, and "
        "nothing shows he dislikes her GIFs",
        "He is upset or complaining, asks something serious, is mid explicit sext, or earlier "
        "reacted badly to her GIFs"),
}

THRESHOLDS: dict[str, float] = {
    "promo": 0.7, "says_under_18": 0.7, "complains_now": 0.5, "asks_if_ai": 0.7,
    "stop": 0.6, "price": 0.7, "wants_content": 0.7, "declines_buying": 0.95,
    "says_yes_to_offer": 0.7, "sexual_now": 0.7, "gif_fits": 0.6,
}

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


TEST_CHOICES: dict[str, dict[str, Any]] = {
    "asks_subject": {
        "instructions": "In `fan_new_messages`, what does the fan ask to see of her? Pick anything "
                        "if he names nothing specific.",
        "criteria": {
            "feet": "Her feet, toes or soles",
            "butt": "Her butt or ass",
            "tits": "Her tits, boobs or nipples",
            "pussy": "Her pussy",
            "nude": "Her fully naked",
            "lingerie": "Her in lingerie or underwear",
            "bikini": "Her in a bikini or swimwear",
            "shower": "Her in the shower or bath",
            "toy": "Her with a sex toy or dildo",
            "masturbation": "Her touching herself or masturbating",
            "blowjob": "Her giving a blowjob",
            "sex": "Her having sex with someone",
            "anything": "Nothing specific, or something not listed here",
        },
    },
    "asks_format": {
        "instructions": "In `fan_new_messages`, does the fan ask for a photo or a video?",
        "criteria": {
            "photo": "A photo, pic or picture",
            "video": "A video, clip or vid",
            "any": "He does not say, or either is fine",
        },
    },
    "scene_stage": {
        "instructions": "They are sexting. How far along is it, counting `thread` and "
                        "`fan_new_messages` together? `scene` says how far it had got before his "
                        "new messages; it does not go backwards unless he clearly starts over.",
        "criteria": {
            "opening": "It only just turned sexual: first dirty lines, nothing described yet",
            "building": "They describe what they do to each other or to themselves, and it is "
                        "getting more explicit",
            "peak": "He is close to finishing: he says he is stroking, about to cum, cannot hold "
                    "it, or begs her",
            "after": "He says he came or finished, or thanks her for it",
            "none": "They are not sexting",
        },
    },
    "offer_level": {
        "instructions": "If she sends him a piece of her content to buy now, how explicit should "
                        "it be? Go by how turned on he is in `fan_new_messages`, what he asks for, "
                        "and what he already bought in `purchases`: one step further than the last "
                        "thing he bought, never the same level again.",
        "criteria": {
            "soft": "Teasing: lingerie, topless, or naked with her pussy hidden",
            "nude": "Fully naked with her pussy showing",
            "explicit": "Touching herself inside, using a toy, or sex",
        },
    },
}
CHOICE_DEFAULT = {"asks_subject": "anything", "asks_format": "any", "scene_stage": "building",
                  "offer_level": "any"}

TEST_NOULS: dict[str, dict[str, Any]] = {
    "counter_offer": _q(
        "In `fan_new_messages`, does the fan ask her for a lower price or offer to pay less?",
        "He names a lower amount, asks for a discount or a deal, or says he would buy it for less",
        "He accepts the price, says no without bargaining, only asks what it costs, or does not "
        "mention the price"),
    "asks_offer_details": _q(
        "In `fan_new_messages`, is a factual question about content she already offered or sent "
        "him the only thing the fan wants: what is in it, whether it is a photo or a video, how "
        "many, how long, how much it was, which one, or whether it is the same as before?",
        "He only asks what is in something she sent or offered, its type, count, length or price, "
        "which one she means, or whether it matches an earlier one, even when he is short or annoyed",
        "He asks for something new, different, more or else, even when he also asks about the one "
        "already offered; asks the price of something she has not offered yet; asks for a lower "
        "price or a deal; says yes, buys or says no; only reacts with a short word such as ok, nice "
        "or lol; or chats, flirts or sexts without asking about something already offered"),
    "offer_moment": _q(
        "Would this be a good moment for her to offer him some of her content to buy, even "
        "though he did not ask for it?",
        "He is warm, flirty or turned on, compliments her body, or the chat has built up to it, "
        "and nothing shows he is upset or cannot pay",
        "He is upset or complaining, says he cannot pay, asks something serious, or the chat is "
        "only small talk so far"),
    "scene_on": _q(
        "Is a sexual chat between her and the fan going on right now, counting `thread` and "
        "`fan_new_messages` together?",
        "The last lines of `thread` are sexting between them and in `fan_new_messages` he stays in "
        "it: he reacts to it, enjoys it, answers her, asks for more, or says he just came, even "
        "when his own words are short or not sexual by themselves",
        "The last lines of `thread` are not sexual, or in `fan_new_messages` he changes the subject, "
        "says he has to go, is upset, or asks something serious"),
    "scene_offer": _q(
        "They are sexting. Is this a good moment for her to send him a locked photo or video as the "
        "next step of it?",
        "He is turned on and adding to the scene himself (he says what he wants, what he would do "
        "to her, or asks for more), they have each sent several sexting messages, no locked message "
        "of hers is waiting unbought in `thread`, and he has written three or more lines since the "
        "last locked message she sent",
        "The sexting only just started, a locked message "
        "of hers in `thread` is still not bought, she sent or offered him something in one of her "
        "last two messages, he has written fewer than three lines since her last locked message, "
        "his lines are getting shorter or cooler, or he just came"),
    "chat_tease": _q(
        "They are chatting, not sexting, and he did not ask to see anything. Is this a good moment "
        "for her to slip a teasing photo of herself in with her normal reply?",
        "They are chatting back and forth and he is friendly or flirty, `his_lines_this_sitting` is "
        "5 or more, `his_lines_since_last_piece` is 3 or more or says no piece yet, and he is not "
        "upset",
        "He is upset or complaining, asks something serious, "
        "`his_lines_this_sitting` is under 5, he has sent fewer than 3 lines since her last piece "
        "(`his_lines_since_last_piece` is 0, 1 or 2), or she already sent 3 pieces "
        "he did not ask for (`unasked_pieces_this_sitting` is 3 or more)"),
}

DRAFT = frozenset({"gif_fits", "counter_offer", "offer_moment"})
# asks_offer_details 0.6 measured 2026-11-17: factual questions scored 0.73-0.97, every other line <=0.50 (59 states, small sample); wants_content 0.65 here only.
TEST_THRESHOLDS: dict[str, float] = {"counter_offer": 0.7, "offer_moment": 0.7,
                                     "scene_on": 0.7, "scene_offer": 0.7, "wants_content": 0.65,
                                     "chat_tease": 0.7, "asks_offer_details": 0.6}
SCENE = frozenset({"scene_on", "scene_offer", "scene_stage", "offer_level"})
SCENE_STATE_KEYS = ("purchases", "scene")
TEASE = frozenset({"chat_tease"})
TEASE_STATE_KEYS = ("his_lines_this_sitting", "teases_sent")

# Measured: your-host.example.com bought 18% back-to-back, 42-44% with 3+ of his lines between.
TEST_SPACING: dict[str, dict[str, Any]] = {
    "offer_moment": _q(
        "Would this be a good moment for her to offer him some of her content to buy, even "
        "though he did not ask for it?",
        "He is warm, flirty or turned on, compliments her body, or the chat has built up to it, "
        "nothing shows he is upset or cannot pay, and she has room to offer: "
        "`his_lines_since_last_piece` is 3 or more or says no piece yet, and "
        "`unasked_pieces_this_sitting` is under 3",
        "He is upset or complaining, says he cannot pay, asks something serious, the chat is only "
        "small talk so far, he has sent fewer than 3 lines since her last piece "
        "(`his_lines_since_last_piece` is 0, 1 or 2), or she already offered 3 pieces he did not "
        "ask for (`unasked_pieces_this_sitting` is 3 or more)"),
    "scene_offer": _q(
        "They are sexting. Is this a good moment for her to send him a locked photo or video as the "
        "next step of it?",
        "He is turned on and into it, they have been sexting for a few messages or he bought and "
        "still wants more, no locked message of hers is waiting unbought in `thread`, "
        "`his_lines_since_last_piece` is 3 or more or says no piece yet, and "
        "`unasked_pieces_this_sitting` is under 3",
        "The sexting only just started, a locked message "
        "of hers in `thread` is still not bought, she offered him something in her last message, "
        "he just came, he has sent fewer than 3 lines since her last piece "
        "(`his_lines_since_last_piece` is 0, 1 or 2), or she already offered 3 pieces he did not "
        "ask for (`unasked_pieces_this_sitting` is 3 or more)"),
}
SPACING_STATE_KEYS = ("his_lines_since_last_piece", "pieces_this_sitting", "unasked_pieces_this_sitting")

TEST_LIKES: dict[str, dict[str, Any]] = {
    "asks_subject": {
        "instructions": "What should she show him? First what he asks to see in `fan_new_messages`. "
                        "If he names nothing specific there, go by what he is into: `he_likes`, and "
                        "what he praised, asked to see or described in his own lines in `thread`. "
                        "Pick anything only when none of these names one of the choices.",
        "criteria": TEST_CHOICES["asks_subject"]["criteria"],
    },
}
LIKES_STATE_KEYS = ("he_likes",)

TEST_IMPLIED: dict[str, dict[str, Any]] = {
    "wants_content": _q(
        "In `fan_new_messages`, does the fan say he wants to see or get her photos, videos or body "
        "now? Read his lines with `her_last_line` and `thread`.",
        "He says show me, send me, let me see, can I see, I want to see your body or a part of it, or "
        "asks where her content is or how to unlock it; he asks her to send him something even if "
        "vague (send me something, something fun, a surprise); he complains he cannot see her naked "
        "or that her feed or page shows nothing nude; or he begs or says please right after "
        "`her_last_line` or `thread` shows she held back or teased showing him something",
        "He only compliments her, says what he would do to her, says he is looking at or likes her "
        "posts, feed or body, asks what kind of content she makes, offers to send her his own pics, "
        "or says please about something other than seeing her"),
}

# New messages only: one 'are you a bot?' kept asks_if_ai at .96-.98 on his next four Turns, so each routed ai_dare and repeated the brush-off.
TEST_NEW_ONLY: dict[str, dict[str, Any]] = {
    "asks_if_ai": _q(
        "In `fan_new_messages`, does the fan ask or suggest that she is a bot or an AI rather than a "
        "real person?",
        "He asks if she is real, a bot, an AI or ChatGPT, or says her replies sound automated or "
        "copy-pasted",
        "He talks to her as the real person she is, even if he asks personal questions or asked "
        "whether she is real earlier in `thread`"),
}


def question_version(mode: str = "shadow") -> str:
    d: dict[str, Any] = {
        "model": MODEL, "questions": QUESTIONS, "thresholds": THRESHOLDS, "intensity": INTENSITY,
        "state_version": STATE_VERSION, "thread_lines": THREAD_LINES,
        "purchase_days": PURCHASE_DAYS, "purchase_kinds": sorted(PURCHASE_KINDS)}
    if full(mode):
        d |= {"test_choices": TEST_CHOICES, "test_nouls": TEST_NOULS,
              "test_thresholds": TEST_THRESHOLDS, "draft": sorted(DRAFT),
              "scene": sorted(SCENE), "scene_state_keys": list(SCENE_STATE_KEYS),
              "test_spacing": TEST_SPACING, "spacing_state_keys": list(SPACING_STATE_KEYS),
              "test_likes": TEST_LIKES, "likes_state_keys": list(LIKES_STATE_KEYS),
              "tease": sorted(TEASE), "tease_state_keys": list(TEASE_STATE_KEYS),
              "test_implied": TEST_IMPLIED, "test_new_only": TEST_NEW_ONLY}
    return hashlib.sha256(json.dumps(
        d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


QUESTION_VERSION = question_version()


class GateError(Exception):
    pass


class Answers(NamedTuple):
    answers: dict[str, float]
    intensity: float
    intensity_p: dict[str, float]
    model: str | None
    ms: int
    choices: dict[str, dict[str, float]]


def fired(answers: dict[str, float], mode: str = "shadow") -> frozenset[str]:
    test = TEST_THRESHOLDS if full(mode) else {}
    ids = {q for q, t in THRESHOLDS.items() if answers[q] >= test.get(q, t)}
    ids |= {q for q, t in test.items() if q not in THRESHOLDS and q in answers and answers[q] >= t}
    return frozenset(ids)


def choice_of(choices: dict[str, dict[str, float]], qid: str) -> str:
    return choice_or_none(choices, qid) or CHOICE_DEFAULT[qid]


def choice_or_none(choices: dict[str, dict[str, float]] | None, qid: str) -> str | None:
    probs = (choices or {}).get(qid) or {}
    top = max(probs.values(), default=None)
    best = [k for k, p in probs.items() if p == top]
    if len(best) == 1 and best[0] in TEST_CHOICES[qid]["criteria"]:
        return best[0]
    return None


MEDIA_ONLY = _jev.MEDIA_ONLY
GIF_ONLY = "[sent a GIF]"
HER_MEDIA = "[photo or video]"
LOCKED = "[locked message]"
REACTION = {"image_reply": "[she sent him a pic back]", "tip_reward": "[she sent him his tip reward]"}


def _giphy(raw_json: str | None) -> bool:
    try:
        return bool(raw_json) and giphy_dm_id(json.loads(raw_json)) is not None
    except ValueError:
        return False


def line_text(m: Message) -> str:
    t = _jev.text(m.body)
    desc = getattr(m, "photo_read", None)
    if desc:
        tag = f"[he sent: {desc}]"
        return f"{t} {tag}" if t else tag
    if t:
        return t
    if m.media_count:
        return HER_MEDIA if m.direction == "out" else MEDIA_ONLY
    return GIF_ONLY if _giphy(m.raw_json) else ""


def read_photos(rows: list, on: bool) -> None:
    for m in rows:
        m.photo_read = (getattr(m, "image_desc", None) or None) if on and m.direction == "in" \
            and m.media_count else None


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
    minutes = max(0.0, _minutes(tx.occurred_at, t0)) if tx is not None else None
    if minutes is None or minutes > PURCHASE_DAYS * 1440:
        return "none in the last 7 days"
    what = "tipped her" if tx.kind == "tip" else "bought a locked message for"
    return f"he {what} ${tx.amount_cents / 100:.0f}, {_ago(minutes)}"


def pending_offer(m: Message | None) -> str:
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
    return _jev.client(key, MODEL, TIMEOUT_S, MAX_RETRIES)


def _test_ids(src: dict[str, Any], scene: bool, tease: bool = False) -> list[str]:
    return [qid for qid in src if (scene or qid not in SCENE) and (tease or qid not in TEASE)]


def _questions(mode: str = "shadow", scene: bool = False, spacing: bool = False,
               likes: bool = False, tease: bool = False, implied: bool = False) -> dict[str, Any]:
    from typesafe_sdk import Choice, Noul, Score
    shadow = {**QUESTIONS, **TEST_NEW_ONLY, **(TEST_IMPLIED if implied else {})} if full(mode) else QUESTIONS
    q: dict[str, Any] = {qid: Noul(instructions=v["instructions"], criteria=v["criteria"])
                         for qid, v in shadow.items()}
    q["intensity"] = Score(instructions=INTENSITY["instructions"], criteria=INTENSITY["criteria"])
    if full(mode):
        src = {**TEST_NOULS, **TEST_SPACING} if spacing else TEST_NOULS
        q |= {qid: Noul(instructions=src[qid]["instructions"], criteria=src[qid]["criteria"])
              for qid in _test_ids(TEST_NOULS, scene, tease)}
        csrc = {**TEST_CHOICES, **TEST_LIKES} if likes else TEST_CHOICES
        q |= {qid: Choice(instructions=csrc[qid]["instructions"], criteria=csrc[qid]["criteria"])
              for qid in _test_ids(TEST_CHOICES, scene)}
    return q


async def ask(st: dict[str, Any], account_id: str | None = None,
              mode: str = "shadow", scene: bool = False, spacing: bool = False,
              likes: bool = False, tease: bool = False, implied: bool = False,
              timeout_s: float | None = None) -> Answers:
    try:
        q = _questions(mode, scene, spacing, likes, tease, implied)
        cap = WALL_S if timeout_s is None else min(WALL_S, timeout_s)
        res, ms = await _jev.ask_one(_client, account_id, st, q, MODEL, cap, GateError)
        answers = {qid: float(res.nouls[qid].noul) for qid in q if qid != "intensity" and qid not in TEST_CHOICES}
        choices = {qid: {str(k): float(v) for k, v in res.choices[qid].probabilities.items()}
                   for qid in q if qid in TEST_CHOICES}
        bad = [q for q, p in answers.items() if not 0.0 <= p <= 1.0]
        if bad:
            raise GateError(f"answer out of range: {bad}")
        sc = res.scores["intensity"]
        intensity = float(sc.score)
        if not 0.0 <= intensity <= 4.0:
            raise GateError(f"intensity out of range: {intensity}")
        p = {str(k): float(v) for k, v in (sc.probabilities or {}).items()}
    except GateError:
        raise
    except Exception as e:
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    return Answers(answers, intensity, p, getattr(res, "model", None), ms, choices)
