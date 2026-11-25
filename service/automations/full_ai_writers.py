from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, NamedTuple

import llm_client
from automations import _language, _voice, cat_stickers, full_ai_config
from automations._info_jev import AskedMarker, askable as info_askable, asked_marker, question_key, question_line
from automations._nonnative import NONNATIVE_REGISTER
from automations._persona import persona_register_age
from automations._prompt_rules import (
    BIO_CONSISTENCY_GUARDRAIL, NO_NARRATION_RULE, ONPLATFORM_GUARDRAIL, STYLE_3LINE, STYLE_BRIEF,
)
from automations._router_jev import line_text
from automations.full_ai_config import style_layers
from automations.full_ai_mode import full
from automations.full_ai_offer_details import OfferFacts
from automations.full_ai_sell import Pick, Refusal, Teased, _buckets, _media_phrase, _money, kind_of
from automations.names import resolve_fan_name
from automations.welcome_chatter_for_info import (
    _ASK_PRIORITY, _BREATHER_VARIANTS, _HISTORY_TAIL, _REPLY_TEMPERATURE, _STYLE_VARIANTS,
    _good_examples, _load_persona, _questions_still_needed,
)

PURPOSE = "full_ai_writer"
PERSONA_FALLBACK = "You are a warm, flirty OnlyFans creator chatting with one of your fans."

KNOW_ENOUGH = "You know enough about him now — just chat and flirt naturally."
ASK_HEAD = ("YOUR GOAL THIS MESSAGE: find out ONE of these, whichever flows from "
            "what he just said, woven in naturally. If he dodged one, don't re-ask "
            "back-to-back:\n")
FAN_ASKED = ("He just asked you something — answer warmly and briefly, and DON'T "
             "ask back this time.")
NO_SELL_OFFERS = ("never name a price or pitch a piece yourself — if he asks to see "
                  "something, say yes warmly and let it arrive.")
ROLE = ("You're texting a fan — flirting, getting to know him, quietly making "
        "him feel like the only one. 100% human, never a bot or an assistant. ")
SELF_BAN = "Use only what you've learned about him; don't share your own info unless he asks; "
READ_ALL = "He may send several texts — read all, reply to the latest.\n\n"
HOW_YOU_TEXT = ("- Short and casual — lowercase, u/ur. React to what he said first.\n"
                "- VARY it — never reuse an opener, phrase, or emoji from this chat.\n"
                "- At most ONE question, never one he already answered. No paragraphs.\n")
EXPLICIT_EARLY = ("- If he gets explicit early: playfully tease and slow it down — warm, "
                  "never preachy.\n")
CONTRACT = "Your reply is ONLY the message text — no JSON, quotes, or metadata."
LEAD_HEAD = ("ONE THING YOU'D LIKE TO LEARN ABOUT HIM — without interviewing him. Don't ask it "
             "straight. Lead him there: say a little something of your own, or guess about him, "
             "and let him fill it in. Only if it flows from what he just said; if it doesn't, "
             "just chat and leave it for later:\n")
LEAD_LINES = {
    "name": "- His name. This one you can just ask, light: what should you call him.",
    "age": "- His age. Guess it playfully wrong, or tease that he sounds older or younger than "
           "he is, so he corrects you.",
    "location": "- Where he is. Say it's late or early for you, or that you wish he was closer, "
                "and wonder how far away he is.",
    "country_from_city": "- He mentioned {city}. Guess the country out loud so he confirms it.",
    "city": "- He's in {country}. Say you've always wanted to see it and wonder which part "
            "he's in.",
    "job": "- What he does for work. Tease him: is he texting you from work, or guess what he "
           "does from how he talks, so he tells you.",
    "hobbies": "- What he does for fun. Say what you'd rather be doing right now, or guess "
               "'bet ur the type who…', so he tells you his.",
}
LEAD_EXAMPLES = {
    "name": '"haha thanks what should i call u?"',
    "age": '"u sound like trouble.. let me guess, 25?"',
    "job": '"shouldnt u be working rn or are u the boss"',
    "location": '"its so late here.. what time is it for u"',
}
SELF_GIVE = ("Use what you've learned about him, and give a little back: a small beat about "
             "your own moment (what you're doing, how you feel), half a sentence, never a "
             "paragraph, never a fact that clashes with your profile; ")
NEXT_QUESTION_STYLE = "dont gush over his answer — a 1-2 word ack, then straight to your next question."
assert NEXT_QUESTION_STYLE in _STYLE_VARIANTS
LEAD_STYLE_VARIANTS = tuple(v for v in _STYLE_VARIANTS if v != NEXT_QUESTION_STYLE)
_ALL_ASKED = frozenset(_ASK_PRIORITY) | {f"{k}:2" for k in _ASK_PRIORITY}
CALL_HIM = ("\n\nHIS NAME: call him {name} from here on — we already "
            "know it, so NEVER ask his name again; just use it naturally.")
NOTHING_ON_FILE = "- (nothing on file yet)"
HIS_KINK = ("HE HAS ALREADY TOLD YOU WHAT HE'S INTO: {fetishes}. Talk INSIDE that, his words — NEVER "
            "re-ask what he's into or wants.")
REPLY_NOW = "Reply to his last message now, in the STYLE FOR THIS MESSAGE above."
STICKER_EXCEPTION = " A final STICKER: <tag> line is ALSO allowed (stripped — he only sees the gif)."
ASKED_EXCEPTION = (" End with one more line, ASKED: <id> — the [id] of the one fact above that "
                   "your message asks or leads him to — or ASKED: none if it doesn't (stripped — he "
                   "never sees it).")

SELL_OFF_LINE = ("you're not selling in chat right now — if he asks to see something, tell him "
                 "warmly it's on your page and in your mass messages.")
SELL_OFF_SCENE = ("you can't send pictures or videos in this chat right now — never say you're "
                  "sending one, that you took one, or that he'll see one. If he asks to see "
                  "you, tell him in one hot line that the real thing is on your page, then stay "
                  "in the scene with words.")
NEAREST_NOTE = ("- He asked for {asked}, and that one isn't here to send. This piece is {got}. "
                "Tell him plainly, in your own words, that it isn't what he asked for and what it "
                "is instead. Say what it really shows, from its description. Never say or hint that "
                "it shows what he asked for, and never call it anything but {got}. Then make him "
                "want this one.")


def asked_words(asked: dict) -> str:
    subject, fmt = asked.get("subject") or "anything", asked.get("format") or "any"
    if subject == "anything":
        return f"a {fmt}"
    return f"a {subject} piece" if fmt == "any" else f"a {subject} {fmt}"


def got_words(pick) -> str:
    kinds = (pick.facts or {}).get("kinds") or {pick.format: len(pick.media)}
    counts = zip(_buckets(kinds), ("photo", "video", "voice note"))
    return " and ".join(f"a {w}" if n == 1 else f"{n} {w}s" for n, w in counts if n)


def nearest_line(facts, pick) -> str | None:
    asked = (getattr(pick, "facts", None) or {}).get("asked")
    if not asked or not full(getattr(facts, "mode", None)) or facts.config.get("sell_nearest") == "plain":
        return None
    return NEAREST_NOTE.format(asked=asked_words(asked), got=got_words(pick))


SEXT_HOT = ("THE THREAD IS HOT — a live sexual scene RIGHT NOW. The one way to throw it away is a "
            "get-to-know question (job, day, city, age) — never. Run the scene:\n"
            "1. STAY IN IT — present tense, first person, dirty, SHORT.\n"
            "2. MAKE HIM SAY WHAT HE WANTS ('what would you do to me if you were here right now?') "
            "— his answer is the whole game.\n"
            "3. MIRROR IT BACK, HOTTER — his words escalated, as if it's already happening.")
SEXT_HEAT = "HEAT {heat} of 4 — run it one step hotter than he is right now, never colder."
BRUSH_OFF = ("He thinks you might be a bot. Never defend yourself and never say you're real — that's "
             "what a bot does. Laugh it off with ONE playful joke instead, in your own words: play "
             "along as if you really were a robot, or tease him for asking. Warm, never annoyed or "
             "hurt. Then pick up something HE told you. No sell, no ask, and don't ask him for a "
             "picture.")
DARE = ("He questioned whether you're real last message and you laughed it off. Now DARE him: send a "
        "picture right now and you'll tell him exactly what you see — a bot couldn't. Promise a "
        "rating out of ten; filthy about what you want a picture OF if the thread's explicit, cheeky "
        "if tame. ONE short message. A dare, not a sale: no price, no offer, no questions.")
DARE_RATE = ("He doubts you're real and sent a picture to test you — the [he sent: …] note in the chat is "
             "what's in it. Prove you're looking at it: name one or two things you actually see in it, in "
             "your own voice, then give him his rating out of ten. Playful, never mean about his looks. "
             "ONE or two short messages. No price, no offer, no questions, and don't ask for another "
             "picture.")
DARE_BLIND = ("HE SENT A PHOTO you can't make out — [he sent a photo] in the chat. Never say "
              "or imply what's in it. If he wrote something, answer that. If it's just the "
              "photo, react warmly and naturally anyway: a playful guess said AS a guess, or a "
              "flirty question about it, is fine.")
GIF_NOW = "\n- THIS message: a sticker fits the moment. Attach one, after your text."
DARE_NEXT = ("He questioned whether you're real a moment ago and you laughed it off. This reply is the "
             "DARE: tell him to send a picture right now and you'll tell him exactly what you see — a bot "
             "couldn't. Promise a rating out of ten; filthy about what you want a picture OF if the "
             "thread's explicit, cheeky if tame. You may open with a few words answering what he just "
             "said, but the dare MUST be in this reply. A dare, not a sale: no price, no offer, no questions.")
DARE_JOIN = ("\n\nBOTH BEATS GO IN THIS ONE REPLY: the brush-off above first, then right after it "
             "the dare below (the \"last message\" it means is the brush-off you just wrote):\n")
APOLOGY_FRAMES = (
    "hey {name} 🙈 i think my messages got crossed and i sent you the same thing twice — that's "
    "totally on me, i'm so sorry",
    "omg {name} i just realised i doubled up on you by mistake 🥺 that was my fault, i feel awful",
    "hey {name} 🙈 i just saw you paid and i never sent you anything back — that's completely on "
    "me, i'm so sorry",
    "oh no {name} 🙈 if you'd already seen those then i've charged you for nothing and that's "
    "completely on me, i'm sorry",
    "aw {name} i'm sorry that one missed 🙈 that's on me for not reading you better — let me make "
    "it up to you",
)
GOAL_HEAD = "YOUR GOAL THIS MESSAGE:\n"
MAKE_RIGHT_HEAD = (GOAL_HEAD + "- START FROM THIS (rewrite it in your own voice, keep "
                   "the apology) — the one line below that fits what he is unhappy about:\n")
MAKE_RIGHT_TAIL = "- The apology only: no offer, no price and nothing free this time."

CONTENT_ASK = "HE IS ASKING FOR CONTENT RIGHT NOW — stay on it, answer the ask: {close}"
BROKE_JOKE = ("HE SAYS HE IS BROKE OR WON'T PAY — pay it no mind. Don't believe it, pity him, argue, "
              "or change what you were going to do or what anything costs because of it. "
              "At most one light, playful joke about it (like \"lol not too broke for me 😏\"), then "
              "carry on exactly as you would have.")
CLOSE_BY_ID = ("Pick the piece from CONTENT YOU CAN ACTUALLY SEND HIM that best fits, tease it from "
               "its description, give the terms, and end with the >>OFFER line.")
INTRO_BY_ID = ("you DO have real content you can send or sell when the moment is right — see CONTENT "
               "YOU CAN ACTUALLY SEND HIM below.")
ITEM_HEAD = "- [id {iid}] {kind}{dur} — {label}: {description}"
ITEM_LINE = ITEM_HEAD + " — {terms}"
TERMS = "${dollars} to unlock"
NO_CUSTOMS = "never customs, "
FILMING_MORE = "If he wants more, you're filming more soon — never promise specifics."
MANIFEST = ("CONTENT YOU CAN ACTUALLY SEND HIM (these are real, already filmed — NEVER invent or "
            "promise anything not on this list, {no_customs}and describe a piece using ONLY its "
            "description):\n{items}\n\n"
            "SELLING RULES:\n"
            "- Pitch ONLY when the vibe is warm or he's asking for content — at most ONE piece, woven "
            "in naturally (\"its $10 to unlock babe 😏\"), never pushy. When he asks or is turned on, "
            "dont stall or be coy: tease the best fit from its description and name the price NOW. A "
            "FREE piece is a spontaneous treat when he's sweet.\n"
            "- When (and ONLY when) you pitch/send a piece this message, end your reply with a final "
            "line that is exactly:\n>>OFFER <id>\n"
            "- No pitch → do NOT write >>OFFER, and never tease that you \"have something\" without "
            "actually pitching it.\n"
            "- The list above is COMPLETE and CURRENT: anything not on it is gone — never re-offer, "
            "re-price, or invent sets, lengths, counts, or prices. " + FILMING_MORE)
MANIFEST_TEST = MANIFEST.replace("these are real, already filmed", "these are real, already made")
PRICE_BLOCK = ("THE PRICE\nIt unlocks at {px}. You may name it or not, but if you name a price it "
               "must be exactly {px}.")
WAS_PRICE_BLOCK = ("THE PRICE\nHe already saw this piece at {was} and did not buy. It is {px} now "
                   "because you cut it for him. You may name {px}; if you name a price it must be "
                   "exactly {px}. Never beg and never apologise for the first price.")
ESCALATION = ("HE'S CLEARLY INTO IT RIGHT NOW — the moment to SELL, not tease. Match his heat in one "
              "short line, then close it: {close}")
SELL_STEP = ("\n4. THEN SELL HIM WHAT HE JUST DESCRIBED. {close} Write it matched to HIS OWN WORDS, as "
             "the NEXT LINE OF THIS SCENE — never as a product. {example} — not 'check out my new "
             "video'.")
SEXT_HOT_TEST = ("THE THREAD IS HOT — a live sexual scene RIGHT NOW. The one way to throw it away is a "
                 "get-to-know question (job, day, city, age) or a change of subject — never. Run the scene:\n"
                 "1. STAY IN IT — present tense, first person, dirty, SHORT.\n"
                 "2. GIVE HIM SOMETHING FIRST — one thing you are doing or want right now, in plain "
                 "dirty words. If he has not said what he wants yet, then ask him once what he would do "
                 "to you; once he has said it, never ask again.\n"
                 "3. MIRROR IT BACK, HOTTER — his words escalated, as if it's already happening. Each "
                 "message goes one step further than your last one, never cooler.")
SELL_STEP_TEST = ("\n4. THIS MESSAGE SENDS HIM THE PIECE. {close} Write it as the NEXT LINE OF THIS "
                  "SCENE, matched to HIS OWN WORDS — what you're doing in it, for him — never as a "
                  "product, never 'check out my new video'. Call it what it is (a pic, pics or a video, "
                  "as its line says) and claim nothing its description does not show.")
ESCALATION_TEST = ("HE'S CLEARLY INTO IT RIGHT NOW, AND HE DID NOT ASK — the moment to SEND him "
                   "something, not tease and not pitch. One short line that answers what he just said, "
                   "at his heat, then the piece as the thing his line made you want to show him. No "
                   "'do you want to see', no question after it: {close}")
RIDE_NOTE = ("- A photo of you, or a few, goes out attached to this message by itself, free or "
             "locked. Write only your normal reply to what he said and keep the chat going: no word "
             "about the photo, no price, no 'want to see'.\n")
CONTRACT_OFFER = (CONTRACT + " ONE exception: the final >>OFFER line when you pitch a piece "
                  "(stripped — he never sees it).")
SEXT_SCENE = (
    "YOU ARE SEXTING HIM RIGHT NOW — a live scene, already going. The one way to throw it away "
    "is a get-to-know question (job, day, city, age) or a change of subject — never. Run the "
    "scene:\n"
    "1. STAY IN IT — present tense, first person, dirty, SHORT.\n"
    "2. GIVE BEFORE YOU ASK — every message tells him one thing YOU are doing right now (to "
    "yourself, for him) or one thing you want to do to him, in plain dirty words: where your "
    "hand is, what you just took off, how wet he makes you, what your mouth would do to him.\n"
    "3. MIRROR IT BACK, HOTTER — his words escalated, as if it's already happening.\n"
    "4. NEVER GO BACKWARDS — each message goes one step further than your last one. No cooling "
    "it down, no 'slow down', no going sweet or small-talk until he has finished.\n"
    "5. At most one question, and only after you gave him something. Never two messages in a "
    "row ending on a question, never the same question twice.")
SCENE_STAGE = {
    "opening": "WHERE THE SCENE IS: just starting. Pull him in: say what you have on (or don't) "
               "and the first thing you'd do to him if he were here.",
    "building": "WHERE THE SCENE IS: building. Clothes come off, hands go where he says. Tell "
                "him what you're doing to yourself for him right now and what you want him to "
                "do next — tell him to touch himself for you.",
    "peak": "WHERE THE SCENE IS: he's close. No questions now. Your shortest, dirtiest lines: "
            "you're about to cum, tell him to cum for you.",
    "after": "WHERE THE SCENE IS: he just finished. Come down with him: one warm, breathless "
             "line about how good that was and what he does to you. No question, nothing to "
             "sell, no new subject in this message.",
}
SCENE_SELL = ("\nTHIS MESSAGE SENDS HIM A LOCKED PIECE. {close} Write it as the NEXT LINE OF "
              "THIS SCENE, matched to HIS OWN WORDS — what you're doing in it, for him — never "
              "as a product, never 'check out my new video'.")
SCENE_NARRATION = ("- No *asterisk actions* and no story about yourself in third person — say "
                   "what you're doing as a text to him, in your own words, sooner send "
                   "nothing.\n")
SCENE_SELF = "Use what you've learned about him; "
OFFER_OPEN = ("He just said yes to the piece you already sent him{piece} — it is still sitting locked "
              "right here in this chat. Tell him it's right there and to unlock it. If he says he "
              "already unlocked it, believe him: don't tell him to unlock it, ask how he liked it. "
              "Send nothing new, pitch nothing else, and name no price.")
_NEED_LINES = {"no_match": FILMING_MORE, "all_owned": FILMING_MORE, "no_priced_items": FILMING_MORE}


def offer_open_line(piece: Teased | None) -> str:
    n = len(piece.locked) if piece else 0
    if n == 1:
        what = {"video": "a video", "audio": "a voice note"}.get(kind_of(piece.format), "a photo")
        return OFFER_OPEN.format(piece=f" ({what}: call it nothing else)")
    return OFFER_OPEN.format(piece=f" ({n} pieces: name no kind)" if n else "")

TEASE_GOAL = ("- Tease this piece from its description only — make him want it. Name no price and "
              "don't send it yet: it comes with your next message.\n")
FREE_TERMS = "FREE — just send it when the moment fits"
CAPTION_APART = ("- A piece goes to him right after this message, with its own caption — lead into "
                 "it warmly. Don't describe it and name no price.\n")
OFFER_GOAL = ("- He is asking about something you already offered or sent him. Answer exactly what "
              "he asked FIRST, using only THE OFFER HE MEANS below — what's in it, photo or video, "
              "how many, how long, what it cost. Never add a count, length, price or detail that "
              "isn't there.\n"
              "- If the description there doesn't say what he asked, tell him you can't confirm "
              "that.\n"
              "- If no offer is named below, ask him which one he means and say nothing about any "
              "piece.\n"
              "- An answer, not a sale: don't pitch anything new and don't ask him about himself.\n")
OFFER_HEAD = "THE OFFER HE MEANS (the only facts you may state about it):"
OFFER_NONE = "- none: nothing he said points to one offer, so you don't know which one he means."
OFFER_TYPE = "- what it is: {what}"
OFFER_LOCKED = "- {n} locked (paid)"
OFFER_PREVIEWS = "- {n} free preview{s} ({what}), not paid"
OFFER_LENGTHS = "- length: {lengths}"
OFFER_SHOWS = "- what it shows: {shows}"
OFFER_PRICE = "- price it went out at: {px}"
OFFER_UNPRICED = "no price named yet"
OFFER_FREE = "free"
OFFER_UNKNOWN = "not on record"
OFFER_SAME = "- same pieces as the 1st offer, sent {day}: {same}"

_FAN_FIELDS = ("real_name", "custom_nickname", "generated_nickname", "of_display_name", "his_age",
               "home_country", "home_city", "occupation", "hobbies", "fetishes", "likes_boobs",
               "likes_ass", "recent_events")
_FACT_LABELS = (("age", "his_age"), ("city", "home_city"), ("country", "home_country"),
                ("hobbies", "hobbies"), ("occupation", "occupation"), ("fetishes", "fetishes"))


@dataclass
class WriteResult:
    text: str | None
    writer: str | None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    floor_reason: str | None = None
    asked_ids: tuple[str, ...] = ()
    asked: str | None = None
    asked_marker: str | None = None


def _fan(fan_info: dict) -> SimpleNamespace:
    return SimpleNamespace(**{k: fan_info.get(k) for k in _FAN_FIELDS})


def _filled(v) -> bool:
    return v is not None and str(v).strip() != ""


def lead_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("lead_in"))


def lead_line(key: str, fan_info: dict) -> str | None:
    line = LEAD_LINES.get(key)
    return line and line.format(city=str(fan_info.get("home_city") or "").strip(),
                                country=str(fan_info.get("home_country") or "").strip())


def lead_examples(f: SimpleNamespace, durable: bool) -> str:
    riffs = _good_examples(f, set(_ALL_ASKED), True)
    if riffs == _good_examples(_fan({}), set(_ALL_ASKED), True):
        riffs = ""
    needed = {k for k, _ in _questions_still_needed(f, set())}
    leads = [LEAD_EXAMPLES[k] for k, on in (
        ("name", not durable and "name" in needed), ("age", "age" in needed), ("job", "job" in needed),
        ("location", bool(needed & {"location", "city", "country_from_city"}))) if on][:2]
    if not leads:
        return riffs or _good_examples(f, set(_ALL_ASKED), True)
    return (riffs.rstrip("\n") + " / " if riffs else "- GOOD: ") + " / ".join(leads) + "\n"


class Need(NamedTuple):
    text: str
    asked_ids: tuple[str, ...] = ()


def _asks(head: str, lines: list[tuple[str, str]]) -> Need:
    return Need(head + "\n".join(f"[{k}] {x}" for k, x in lines), tuple(k for k, _ in lines))


def _need_block(facts, fan_just_asked: bool, rng: random.Random, lead: bool = False) -> Need:
    head = LEAD_HEAD if lead else ASK_HEAD
    if (al := getattr(facts, "ask_list", None)) is not None:
        lines = ([(k, x) for k in al.keys if (x := lead_line(k, facts.fan_info))] if lead
                 else list(zip(al.keys, al.lines)))
        if not lines:
            return Need(KNOW_ENOUGH)
        if al.ask:
            return _asks(head, lines)
        return Need(FAN_ASKED if fan_just_asked else rng.choice(_BREATHER_VARIANTS))
    left = info_askable(facts.config, facts.fan_info, lead)
    nq = facts.next_question
    if not left:
        return Need(KNOW_ENOUGH)
    if lead:
        if nq in left:
            return _asks(head, [(nq, lead_line(question_key(nq, facts.fan_info), facts.fan_info))])
    elif nq:
        return _asks(head, [(nq, question_line(nq, facts.fan_info))])
    return Need(FAN_ASKED if fan_just_asked else rng.choice(_BREATHER_VARIANTS))


def _chat_system(persona: str, need_block: str, call_him: str, style: str, good: str, *,
                 style_on: bool, nonnative_on: bool, painful_on: bool, offers: str,
                 sticker_block: str, sell_block: str = "", marker: bool = False,
                 v: _voice.VoiceBlocks = _voice.HER, scene: bool = False, lead: bool = False,
                 asked: bool = False) -> str:
    humanizer = f"\n\n{v.humanizer}" if style_on else v.emoji_vocab
    nonnative = f"\n\n{NONNATIVE_REGISTER}" if nonnative_on else ""
    stickers = f"\n\n{sticker_block}" if sticker_block else ""
    return (
        f"{persona}\n\n"
        + ROLE + (SCENE_SELF if scene else SELF_GIVE if lead else SELF_BAN) + (f"{offers} " if offers else "") + READ_ALL
        + f"{v.painful_texting + chr(10) + chr(10) if painful_on else ''}"
        f"{need_block}{call_him}\n\n"
        f"STYLE FOR THIS MESSAGE — {style}\n\n"
        f"HOW YOU TEXT (a real {persona_register_age(persona)}yo {v.texter_noun}, "
        "not an assistant):\n"
        + HOW_YOU_TEXT
        + (SCENE_NARRATION if scene else f"{NO_NARRATION_RULE}" + EXPLICIT_EARLY)
        + f"{good}\n"
        f"{ONPLATFORM_GUARDRAIL}\n\n"
        f"{BIO_CONSISTENCY_GUARDRAIL}"
        f"{humanizer}{nonnative}{stickers}"
        + (f"\n\n{sell_block.strip()}\n\n" if sell_block else "\n\n")
        + (CONTRACT_OFFER if marker else CONTRACT)
        + (STICKER_EXCEPTION if sticker_block else "")
        + (ASKED_EXCEPTION if asked else "")
    )


def spend_line(spent, tips=()) -> str | None:
    ppv = [b.amount_cents for b in spent]
    tip_total = sum(int(x or 0) for x in tips)
    tip_n = sum(1 for x in tips if int(x or 0) > 0)
    if tip_total <= 0 and not ppv:
        return None
    parts: list[str] = []
    if ppv:
        ppv_n, ppv_total, ppv_max = len(ppv), sum(ppv), max(ppv)
        parts.append(f"unlocked {ppv_n} PPV{'s' if ppv_n != 1 else ''} "
                     f"(${ppv_total // 100} total, biggest ${ppv_max // 100})")
    if tip_total > 0:
        parts.append(f"tipped ${tip_total // 100} across "
                     f"{tip_n} tip{'s' if tip_n != 1 else ''}")
    return "he's spent: " + " and ".join(parts) + " — talk like you remember it, never like he's never paid."


def thread_lines(rows: list, tail: int = _HISTORY_TAIL) -> str:
    lines = [(m.direction, line_text(m)) for m in rows[-tail:]]
    return "\n".join(f"{'FAN' if d == 'in' else 'YOU'}: {b}" for d, b in lines if b)


def _chat_user(f: SimpleNamespace, rows: list, spent: list, tips=()) -> str:
    facts = []
    name = resolve_fan_name(f)
    if name:
        facts.append(f"name/nickname: {name.split('/')[0][:40]}")
    for label, attr in _FACT_LABELS:
        val = getattr(f, attr)
        if _filled(val):
            facts.append(f"{label}: {str(val).strip()[:80]}")
    if spend := spend_line(spent, tips):
        facts.append(spend)
    facts_block = "\n".join(f"- {x}" for x in facts) if facts else NOTHING_ON_FILE
    personal_block = ("\n" + HIS_KINK.format(fetishes=str(f.fetishes).strip()[:160])
                      if _filled(f.fetishes) else "")
    return (f"What you know about him:\n{facts_block}{personal_block}\n\n"
            f"Recent conversation (oldest→newest):\n{thread_lines(rows)}\n\n"
            + REPLY_NOW)


def style_flags(config: dict) -> dict[str, bool]:
    s = style_layers(config)
    return {"style_on": s["texting"], "nonnative_on": s["nonnative"], "spacing_on": s["spacing"],
            "typo_on": s["typos"], "painful_on": s["painful"]}


def typo_rate(config: dict) -> float | None:
    pct = config.get("typo_pct")
    return None if pct is None else pct / 100


def _his_first_name(f: SimpleNamespace, v: _voice.VoiceBlocks) -> str:
    name = (resolve_fan_name(f) or "").split("/")[0].split()
    first = name[0] if name else ""
    return first if first.isalpha() and 2 <= len(first) <= 20 else v.fan_address


def _beat(route: str, heat: int, f: SimpleNamespace, item: Pick | None, test: bool = False) -> str | None:
    if route == "tease" and item:
        return GOAL_HEAD + TEASE_GOAL + item_line(item, None)
    if route == "sext":
        return f"{SEXT_HOT_TEST if test else SEXT_HOT}\n{SEXT_HEAT.format(heat=heat)}"
    if route == "ai_dare":
        return BRUSH_OFF
    if route == "make_right":
        name = _his_first_name(f, _voice.HER)
        return (MAKE_RIGHT_HEAD + "".join(f"  - {x.replace('{name}', name)}\n" for x in APOLOGY_FRAMES)
                + (item_line(item, FREE_TERMS) if item else MAKE_RIGHT_TAIL))
    return None


def his_photo(rows) -> str | None:
    turn = []
    for m in reversed(rows):
        if m.direction != "in":
            break
        turn.append(m)
    if any(getattr(m, "photo_read", None) for m in turn):
        return "seen"
    return "unseen" if any(getattr(m, "media_count", 0) for m in turn) else None


def _dare_beat(route: str, need: Need, photo: str | None, dared: bool, due: bool = False) -> Need:
    if route == "ai_dare":
        if photo == "seen":
            return Need(DARE_RATE)
        if dared:
            return Need(BRUSH_OFF + (f"\n{DARE_BLIND}" if photo else ""))
        if due:
            return Need(BRUSH_OFF + DARE_JOIN + DARE)
    elif route in ("chat", "sext"):
        if (dared or due) and photo == "seen":
            return Need(need.text.rstrip("\n") + "\n" + DARE_RATE, need.asked_ids)
        if due and not photo:
            return Need(DARE_NEXT)
    return need


def _carries_item(route: str, pick: Pick | Refusal | None) -> bool:
    return isinstance(pick, Pick) and (route == "tease" or (route == "make_right" and pick.price_cents == 0))


def _clock(secs: int) -> str:
    return f"{secs // 60}:{secs % 60:02d}"


def offer_facts_block(of: OfferFacts | None) -> str:
    if of is None:
        return f"{OFFER_HEAD}\n{OFFER_NONE}"
    lines = [OFFER_TYPE.format(what=OFFER_UNKNOWN if "media" in of.missing else _media_phrase(of.locked_kinds)),
             OFFER_LOCKED.format(n=of.locked)]
    if of.previews:
        lines.append(OFFER_PREVIEWS.format(n=of.previews, s="s" * (of.previews > 1),
                                           what=_media_phrase(of.preview_kinds)))
    if of.seconds:
        lines.append(OFFER_LENGTHS.format(lengths=", ".join(_clock(s) for s in of.seconds)))
    lines.append(OFFER_SHOWS.format(shows=" / ".join(of.descriptions) or OFFER_UNKNOWN))
    px = (OFFER_UNPRICED if of.quoted_cents is None else OFFER_FREE if of.quoted_cents == 0
          else _money(of.quoted_cents))
    lines.append(OFFER_PRICE.format(px=px))
    if of.same_as_first is not None:
        at, same = of.same_as_first
        lines.append(OFFER_SAME.format(day=f"{at:%a %b} {at.day}", same="yes" if same else "no"))
    return "\n".join([OFFER_HEAD, *lines])


def item_line(pick: Pick, terms: str | None) -> str:
    facts = pick.facts or {}
    items = facts.get("items") or []
    secs = sum(int(i.get("seconds") or 0) for i in items) if pick.format == "video" else 0
    dur = f" {_clock(secs)}" if secs else ""
    label = f"{len(pick.media)} {pick.format}s" if len(pick.media) > 1 else "untitled"
    line = ITEM_HEAD if terms is None else ITEM_LINE
    return line.format(iid=pick.ref, kind=pick.format, dur=dur, label=label,
                       description=str(facts.get("description") or "").strip(), terms=terms)


def sell_section(pick: Pick, was_cents: int | None, note: str | None = None, test: bool = False) -> str:
    line = item_line(pick, TERMS.format(dollars=_money(pick.price_cents)[1:]))
    if note:
        line = f"{line}\n{note}"
    block = MANIFEST_TEST if test else MANIFEST
    return block.format(no_customs=NO_CUSTOMS, items=line) + "\n\n" + priced_block(pick.price_cents, was_cents)


def priced_block(price_cents: int, was_cents: int | None) -> str:
    px = _money(price_cents)
    if was_cents and was_cents > price_cents:
        return WAS_PRICE_BLOCK.format(was=_money(was_cents), px=px)
    return PRICE_BLOCK.format(px=px)


def was_cents_of(row: str, pick: Pick, offer_piece: Teased | None) -> int | None:
    if row != "haggle" or offer_piece is None or tuple(sorted(pick.media)) != offer_piece.locked:
        return None
    return offer_piece.list_cents


def nearest_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and facts.config.get("sell_nearest") in ("plain", "note")


def scene_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("sext_scene"))


def spacing_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("sell_spacing"))


def likes_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("he_likes"))


def tease_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("chat_tease"))


def implied_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("ask_implied"))


def wide_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("info_wide"))


def _tease_row(route: str, row: str, hot: bool, facts) -> bool:
    return tease_flag(facts) and route == "sell_now" and (
        row == "chat_tease" or (row == "offer_moment" and not hot))


def tease_turn(decision, facts) -> bool:
    return _tease_row(decision.route, decision.row, is_hot(decision.fired, facts), facts)


def is_ride(pick) -> bool:
    return isinstance(pick, Pick) and bool((pick.facts or {}).get("ride"))


def bundle_of(facts) -> str:
    return facts.config.get("sell_bundle", "shoot") if full(getattr(facts, "mode", None)) else "shoot"


def count_flag(facts) -> bool:
    return full(getattr(facts, "mode", None)) and bool(facts.config.get("sell_count"))


def is_hot(fired, facts) -> bool:
    return bool(facts.config["sext_on"]) and (
        "sexual_now" in fired or (scene_flag(facts) and "scene_on" in fired))


def scene_turn(decision, facts) -> bool:
    return scene_flag(facts) and (
        decision.route == "sext" or (decision.route == "sell_now" and is_hot(decision.fired, facts)))


def gif_rolled(facts) -> bool:
    pct = facts.config.get("gif_pct")
    if pct is None:
        return True
    seed = f"gifpct:{getattr(facts, 'account_id', '')}:{getattr(facts, 'fan_id', '')}:{facts.anchor_key}"
    return random.Random(seed).random() * 100 < pct


def gif_offered(decision, facts) -> bool:
    if not facts.config.get("gifs") or decision.row == "offer_details":
        return False
    if "gif_fits" not in decision.fired or scene_turn(decision, facts):
        return False
    return gif_rolled(facts)


def scene_of(decision, facts) -> dict | None:
    if not scene_turn(decision, facts):
        return None
    return getattr(facts, "scene_now", None) or {"n": 1, "stage": "opening", "heat": decision.heat}


def _scene_head(stage: str) -> str:
    return f"{SEXT_SCENE}\n{SCENE_STAGE[stage]}"


def sell_beat(row: str, hot: bool, scene: str | None = None, test: bool = False) -> str:
    if scene:
        return _scene_head(scene) + SCENE_SELL.format(close=CLOSE_BY_ID,
                                                      example=_voice.HER.sell_caption_example)
    if hot:
        return ((SEXT_HOT_TEST if test else SEXT_HOT)
                + (SELL_STEP_TEST if test else SELL_STEP).format(close=CLOSE_BY_ID,
                                                                 example=_voice.HER.sell_caption_example))
    escalation = ESCALATION_TEST if test else ESCALATION
    return (escalation if row == "offer_moment" else CONTENT_ASK).format(close=CLOSE_BY_ID)


def _sell_off_test(facts) -> bool:
    return full(getattr(facts, "mode", None)) and not facts.config.get("sell_on")


class Prompt(NamedTuple):
    messages: list[dict]
    asked_ids: tuple[str, ...]


def messages_for(route: str, row: str, heat: int, facts, pick: Pick | Refusal | None, *,
                 persona: str = PERSONA_FALLBACK, hot: bool = False, plain: bool = False,
                 scene: str | None = None, gif_ok: bool | None = None, broke: bool = False) -> list[dict]:
    return prompt(route, row, heat, facts, pick, persona=persona, hot=hot, plain=plain, scene=scene,
                  gif_ok=gif_ok, broke=broke).messages


def prompt(route: str, row: str, heat: int, facts, pick: Pick | Refusal | None, *,
           persona: str = PERSONA_FALLBACK, hot: bool = False, plain: bool = False,
           scene: str | None = None, gif_ok: bool | None = None, broke: bool = False) -> Prompt:
    if route == "no_send":
        return Prompt([], ())
    rows = facts.cut_rows
    asked_ids: tuple[str, ...] = ()
    rng = random.Random(f"full_ai:{facts.anchor_key}")
    flags = style_flags(facts.config)
    style_extra = ((STYLE_3LINE,) * 2 + (STYLE_BRIEF,) * 2) if flags["style_on"] else ()
    lead = lead_flag(facts) and scene is None
    style = rng.choice((LEAD_STYLE_VARIANTS if lead else _STYLE_VARIANTS) + style_extra)
    fan_run: list[str] = []
    for m in reversed(rows):
        if m.direction == "in" and line_text(m):
            fan_run.append(line_text(m))
        elif fan_run:
            break
    f = _fan(facts.fan_info)
    test = full(getattr(facts, "mode", None))
    ride = route == "sell_now" and is_ride(pick) and not plain
    selling = route == "sell_now" and isinstance(pick, Pick) and not ride
    apart = plain and (selling or (route == "make_right" and _carries_item(route, pick)))
    details = row == "offer_details"
    if apart:
        if route == "make_right":
            name = _his_first_name(f, _voice.HER)
            need = (MAKE_RIGHT_HEAD + "".join(f"  - {x.replace('{name}', name)}\n" for x in APOLOGY_FRAMES)
                    + CAPTION_APART)
        else:
            need = (f"{_scene_head(scene)}\n{CAPTION_APART}" if scene
                    else f"{SEXT_HOT_TEST if test else SEXT_HOT}\n{CAPTION_APART}" if hot
                    else GOAL_HEAD + CAPTION_APART)
        sell_block, offers, selling = "", NO_SELL_OFFERS, False
    elif selling:
        need = sell_beat(row, hot, scene, test)
        sell_block = sell_section(pick, was_cents_of(row, pick, facts.offer_piece), nearest_line(facts, pick), test)
        offers = INTRO_BY_ID
    elif details:
        need, sell_block, offers = GOAL_HEAD + OFFER_GOAL, offer_facts_block(facts.offer_facts), ""
    else:
        item = pick if _carries_item(route, pick) else None
        if scene:
            need = _scene_head(scene) + (f"\n{SEXT_HEAT.format(heat=heat)}" if route == "sext" else "")
        else:
            beat = _beat(route, heat, f, item, test)
            ask = Need(beat) if beat else _need_block(facts, "?" in " ".join(fan_run), rng, lead)
            if not item:
                ask = _dare_beat(route, ask, his_photo(rows), bool(getattr(facts, "dared", False)),
                                 bool(getattr(facts, "dare_due", False)))
            need, asked_ids = ask
        if ride:
            need = f"{need}\n{RIDE_NOTE}"
        refused = (route in ("sell_now", "tease") and isinstance(pick, Refusal)
                   and not _tease_row(route, row, hot, facts))
        sell_block = ((offer_open_line(getattr(facts, "offer_piece", None)) if pick.reason == "offer_open"
                       else _NEED_LINES.get(pick.reason, "")) if refused else "")
        offers = "" if item else SELL_OFF_LINE if row in ("sell_off", "tease_off") else NO_SELL_OFFERS
        if offers == NO_SELL_OFFERS and _sell_off_test(facts):
            offers = SELL_OFF_SCENE if scene else SELL_OFF_LINE
    if broke and route not in ("make_right", "ai_dare"):
        need = need.rstrip("\n") + "\n" + BROKE_JOKE
    durable = _filled(f.real_name) or _filled(f.custom_nickname)
    name = resolve_fan_name(f)
    call_him = CALL_HIM.format(name=name.split("/")[0][:40]) if durable and name else ""
    good = (_good_examples(f, set(_ALL_ASKED), durable) if details
            else lead_examples(f, durable) if lead else _good_examples(f, set(), durable))
    system = _chat_system(persona, need, call_him, style, good, lead=lead,
                          style_on=flags["style_on"], nonnative_on=flags["nonnative_on"],
                          painful_on=flags["painful_on"], v=_voice.HER, offers=offers,
                          sell_block=sell_block, marker=selling, scene=scene is not None,
                          asked=bool(asked_ids),
                          sticker_block=cat_stickers.prompt_block("allow", _voice.VOICE_HER)
                          + (GIF_NOW if facts.config.get("gif_pct") is not None else "")
                          if ((facts.config.get("gifs") and not scene and gif_rolled(facts))
                              if gif_ok is None else gif_ok)
                          else "")
    bare = apart or selling or ride or details or _carries_item(route, pick)
    spent, tips = ([], []) if bare else (facts.spent, getattr(facts, "tips", []))
    return Prompt([{"role": "system", "content": system},
                   {"role": "user", "content": _chat_user(f, rows, spent, tips)}], asked_ids)


_BRACKET = re.compile(r"\[.*?\]", re.S)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")
_OFFER_LINE = re.compile(r"^[ \t]*>>OFFER[ \t]+(\S+)[ \t]*$", re.M)


def strip_offer(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", _OFFER_LINE.sub("", text)).strip()


_YOU_LABEL = re.compile(r"^[ \t]*YOU[ \t]*:[ \t]*", re.M)
_FAN_LINE = re.compile(r"^[ \t]*FAN[ \t]*:.*$", re.M)


def strip_labels(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", _YOU_LABEL.sub("", _FAN_LINE.sub("", text))).strip()


_QUOTE_CLOSE = {'"': '"”', "“": '”"', "'": "'’", "‘": "’'"}
_QUOTE_KIND = {'"': '"“”', "“": '"“”', "'": "'‘’", "‘": "'‘’"}


def strip_quotes(text: str) -> str:
    t = text.strip()
    if len(t) < 2 or t[-1] not in _QUOTE_CLOSE.get(t[0], ""):
        return text
    inner = t[1:-1]
    for i, ch in enumerate(inner):
        if ch not in _QUOTE_KIND[t[0]] or 0 < i < len(inner) - 1 and inner[i - 1].isalpha() \
                and inner[i + 1].isalpha():
            continue
        if i and not inner[i - 1].isspace():
            return text
        break
    return inner.strip()


_TAG = re.compile(r"<[/A-Za-z][^<>\n]*>")
_PLACEHOLDER = re.compile(r"\{[A-Za-z_][^{}\n]*\}")
_META_WORDS = ("response|reply|output|assistant|creator|model|system|character|persona|bot|ai|user|"
               "caption|message")
_LABEL = re.compile(
    r"^[ \t\"'“‘*_]*(?:[a-z'’]+[ \t]+){0,2}(?:" + _META_WORDS + r")[ \t]*:(?=[ \t]|$)", re.M | re.I)
_COLON_TAIL = re.compile(r"[^\W\d_]{2}[ \t]*:[ \t]*$", re.M)
_AI_SELF = re.compile(
    r"\bas an ai\b"
    r"|(?:^|[.!?,;][ \t]*)[ \t\"'“‘*_]*(?:i['’]m|i am|im)[ \t]+(?:just[ \t]+)?an?[ \t]+"
    r"(?:ai|large language model|language model|ai language model|ai assistant|ai model)\b"
    r"|\b(?:cannot|can['’]?t|can not|am not able to|am unable to|(?:i['’]?m|i am) (?:not able|unable) to"
    r"|won['’]?t)[ \t]+(?:create|generate|produce|provide|write)\b(?:\W+\w+){0,4}?\W+"
    r"(?:content|material|response|explicit|sexual)"
    r"|\b(?:fulfil{1,2}|comply with|assist with)[ \t]+(?:this|that|your)[ \t]+request"
    r"|sexuali[sz]es?[ \t]+(?:a[ \t]+)?minors?|content polic"
    r"|\b(?:my|content|community|usage|safety)[ \t]+guidelines", re.I | re.M)


def floor(text: str, lang: str, offer_ref: int | None = None) -> str | None:
    if any(m.group(1) != str(offer_ref) for m in _OFFER_LINE.finditer(text)):
        return "offer_ref"
    text = strip_offer(text)
    if _BRACKET.search(text) or _TAG.search(text) or _PLACEHOLDER.search(text):
        return "bracket"
    if "framework:" in text.lower():
        return "framework"
    if ">>" in text:
        return "chevron"
    if lang == "en" and _CJK.search(text):
        return "cjk"
    if not any(ch.isalpha() for ch in text):
        return "no_letters"
    if _AI_SELF.search(text):
        return "ai_self"
    if _LABEL.search(text):
        return "label"
    if _COLON_TAIL.search(text):
        return "colon_tail"
    return None


ECHO_RUN, REPEAT_RUN, OWN_LINES = 7, 8, 10


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", re.sub(r"['’]", "", text.lower()))


def _shares_run(text: str, sources: list[str], n: int) -> bool:
    w = _words(text)
    grams = {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}
    return bool(grams) and any(tuple(sw[i:i + n]) in grams
                               for sw in map(_words, sources) for i in range(len(sw) - n + 1))


def copied(text: str, prompt: list[str], own: list[str]) -> str | None:
    if _shares_run(text, prompt, ECHO_RUN):
        return "echo"
    return "repeat" if _shares_run(text, own, REPEAT_RUN) else None


_GOOD_LINE = re.compile(r"^- GOOD:.*$", re.M)


def reoffers(facts, pick) -> bool:
    if not isinstance(pick, Pick):
        return False
    return any(p is not None and set(pick.media) == set(p.locked)
               for p in (getattr(facts, "offer_piece", None), getattr(facts, "tease", None)))


def prompt_pieces(content: str, persona: str = "", drop: Sequence[str] = ()) -> list[str]:
    parts = content.split(persona) if persona else [content]
    parts = [q for p in parts for q in _GOOD_LINE.split(p)]
    for d in filter(None, drop):
        parts = [q for p in parts for q in p.split(d)]
    return [q for q in parts if q.strip()]


def own_lines(facts, pick=None) -> list[str]:
    if reoffers(facts, pick):
        return []
    of = getattr(facts, "offer_facts", None)
    caps = {" ".join(c.split()).lower() for c in (of.captions if of is not None else ())}
    rows = [m for m in getattr(facts, "cut_rows", None) or [] if m.direction != "in"]
    return [t for t in (line_text(m) for m in rows[-OWN_LINES:]) if t and " ".join(t.split()).lower() not in caps]


def reject(text: str, lang: str, gifs: bool, offer_ref: int | None = None, *,
           item: bool = False) -> str | None:
    body, tag = cat_stickers.parse_marker(text)
    if not body:
        return None if gifs and tag and offer_ref is None and not item else "no_letters"
    return floor(body, lang, offer_ref)


def _outcome(e: llm_client.LLMError) -> str:
    if isinstance(e, llm_client.LLMCapExceeded):
        return "cap"
    if isinstance(e, llm_client.LLMKeyError) and e.kind != "missing":
        return f"http_{e.status}"
    if isinstance(e, llm_client.LLMConfigError):
        return "no_key"
    status = getattr(e, "status", None)
    return f"http_{status}" if status is not None else "timeout"


def retryable(outcome: str) -> bool:
    return outcome in ("timeout", "http_429") or outcome.startswith("http_5")


async def walk(cfg: dict, writers: list[str], deadline: float, try_once) -> WriteResult:
    res = WriteResult(None, None)
    for writer in writers:
        for _ in range(1 + int(cfg.get("writer_retries") or 0)):
            timeout = min(full_ai_config.writer_timeout(cfg, writer), deadline - time.monotonic())
            if timeout <= 0:
                res.attempts.append({"writer": writer, "outcome": "timeout", "ms": 0})
                break
            t0, text, reason = time.perf_counter(), "", None
            try:
                text, reason = await asyncio.wait_for(try_once(writer, timeout), timeout)
                outcome = "empty" if not text else f"floor:{reason}" if reason else "ok"
            except llm_client.LLMError as e:
                outcome = _outcome(e)
            except asyncio.TimeoutError:
                outcome = "timeout"
            res.attempts.append({"writer": writer, "outcome": outcome,
                                 "ms": int((time.perf_counter() - t0) * 1000)})
            if outcome == "ok":
                res.text, res.writer = text, writer
                return res
            if reason and res.floor_reason is None:
                res.floor_reason = reason
            if not retryable(outcome):
                break
    return res


async def write(decision, facts, *, deadline: float, writers: list[str] | None = None,
                plain: bool = False) -> WriteResult:
    cfg = facts.config
    pick = facts.pick
    selling = decision.route == "sell_now" and isinstance(pick, Pick)
    ride = is_ride(pick)
    offer_ref = pick.ref if selling and not (plain or ride) else None
    item = _carries_item(decision.route, pick) or selling and (plain or ride)
    now = scene_of(decision, facts)
    gif_ok = gif_offered(decision, facts)
    persona = await _load_persona(facts.account_id)
    msgs, asked_ids = prompt(decision.route, decision.row, now["heat"] if now else decision.heat,
                             facts, pick, persona=persona,
                             hot=is_hot(decision.fired, facts), plain=plain,
                             scene=now["stage"] if now else None, gif_ok=gif_ok,
                             broke="declines_buying" in decision.fired)
    lang = await _language.load_account_language(facts.account_id) if cfg["floor_on"] else ""
    ids = frozenset(asked_ids)
    facts_lines = (offer_facts_block(getattr(facts, "offer_facts", None)).split("\n")[1:]
                   if decision.row == "offer_details" else [])
    pieces = prompt_pieces(msgs[0]["content"], persona, facts_lines) if msgs else []
    own = own_lines(facts, pick)
    marks: dict[str, AskedMarker] = {}

    async def try_once(writer: str, timeout: float) -> tuple[str, str | None]:
        r = await llm_client.chat(model=writer, messages=msgs, purpose=PURPOSE,
                                  account_id=facts.account_id, temperature=_REPLY_TEMPERATURE,
                                  timeout_s=timeout, max_attempts=1)
        mark = asked_marker(strip_quotes(strip_labels((r.content or "").strip())), ids)
        text = strip_quotes(strip_labels(mark.text))
        marks[text] = mark
        return text, (reject(text, lang, gif_ok, offer_ref, item=item)
                      or copied(text, pieces, own)) if text and cfg["floor_on"] else None

    res = await walk(cfg, writers or cfg["writers"], deadline, try_once)
    res.asked_ids = asked_ids
    if res.text is not None:
        mark = marks.get(res.text)
        res.text = strip_quotes(strip_labels(strip_offer(res.text)))
        if mark is not None:
            res.asked, res.asked_marker = mark.key, mark.raw
    return res
