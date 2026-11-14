"""automations/full_ai_writers.py — Full AI Chat's Writers: per-Route prompt assembly and the Writer call.

  messages_for(route, row, heat, facts, pick, *, persona, hot, plain, scene, gif_ok)  pure: the Route's chat messages
  scene_flag / is_hot / scene_turn / scene_of / gif_offered   pure: the sext scene's switches (`sext_scene`)
  write(decision, facts, *, deadline) -> WriteResult       the Writer chain through llm_client.chat
  floor(text, lang, offer_ref=None) -> str | None          pure: the code floor's reject reason
  strip_offer(text) -> str                                 pure: every whole `>>OFFER <ref>` line out
  spend_line(spent) -> str | None                          pure: OLD-AIC-22, his purchases as a fact (03b)

The chat Route is the old ai_chatter reply prompt, verbatim (docs/prompts/README.md, "full_ai_writers
chat assembly"): the OLD-AIC-18 system skeleton (ai_chatter.py:6546-6633) with the OLD-AIC-10 goal
tiers (:6440-6459) and the OLD-CORE-03 guardrail, and the OLD-AIC-21 user message (:6635-6645). Its
style and goal pools and few-shot line are wcfi's, imported as ai_chatter imported them
(ai_chatter.py:172-180, "deliberate sibling reuse"); the strings the old engine wrote inline are
copied below, each with its catalog id.

Per Route (ticket 34) the Route's beat takes the OLD-AIC-18 goal slot (`{need_block}`), as the old
engine's beats did: chat its OLD-AIC-10 tier; sext OLD-AIC-08 (no sell step) and a NEW Heat line;
ai_dare OLD-AIC-01 then OLD-AIC-07 joined by NEW glue into one reply; make_right NEW glue over the old
`_APOLOGY_FRAMES` with no free item. Rows `sell_off` / `tease_off` carry the NEW sell-off line in
OLD-AIC-17's place. sell_now with a Pick (03b, NEW-116) is the old content-ask reply: OLD-AIC-11's
intro in the offers slot, OLD-AIC-04 with `_CLOSE_BY_ID` as the beat, the OLD-AIC-12 block (one item
line + SELLING RULES) and OLD-CORE-33's plain price block in OLD-AIC-18's `{sell_section}`, and the
contract with its `>>OFFER` exception (ticket 47: row offer_moment's beat is OLD-AIC-05, a sell
while `sexual_now` fired gets OLD-AIC-08 with its step 4, and a haggle row's price block is
OLD-CORE-33's `was_cents` form); with a Refusal it is chat plus the need-line in that slot
(OLD-AIC-12's "filming more soon" sentence; none on inventory_unknown). A tease with a Pick (ticket 46) puts
OLD-CORE-24's goal head, the DRAFT tease goal line (NEW-123) and the item line without terms in the
goal slot; make_right with a Free item swaps the apology-only tail for the item line with OLD-AIC-12's
FREE terms. With `config.gifs` on, the cat-sticker block (NEW-32) and OLD-AIC-18's sticker
exception join the prompt. no_send builds no messages.
`write` walks the side's `config.writers` chain, each Writer once; `floor` is the code floor that
sends a broken reply to the next Writer.

Sends nothing: no direct import of an OF client, executor, lease, DM rate or OF write module (AST
scan + runtime send traps in test_full_ai_test_chat.py; shared helpers load them transitively).
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import llm_client
from automations import _language, _voice, cat_stickers
from automations._info_jev import missing as info_missing, question_line
from automations._nonnative import NONNATIVE_REGISTER
from automations._persona import persona_register_age
from automations._prompt_rules import (
    BIO_CONSISTENCY_GUARDRAIL, NO_NARRATION_RULE, ONPLATFORM_GUARDRAIL, STYLE_3LINE, STYLE_BRIEF,
)
from automations._router_jev import line_text
from automations.full_ai_config import style_layers
from automations.full_ai_sell import Pick, Refusal, Teased, _money
from automations.names import resolve_fan_name
from automations.welcome_chatter_for_info import (
    _BREATHER_VARIANTS, _HISTORY_TAIL, _REPLY_TEMPERATURE, _STYLE_VARIANTS, _good_examples,
    _load_persona,
)

PURPOSE = "full_ai_writer"
# wcfi's `_load_persona` fallback, verbatim (welcome_chatter_for_info.py:237-238).
PERSONA_FALLBACK = "You are a warm, flirty OnlyFans creator chatting with one of your fans."

# OLD-AIC-10 tiers, verbatim (ai_chatter.py:6446, :6448-6452, :6455-6458).
KNOW_ENOUGH = "You know enough about him now — just chat and flirt naturally."
ASK_HEAD = ("YOUR GOAL THIS MESSAGE: find out ONE of these, whichever flows from "
            "what he just said, woven in naturally. If he dodged one, don't re-ask "
            "back-to-back:\n")
FAN_ASKED = ("He just asked you something — answer warmly and briefly, and DON'T "
             "ask back this time.")
# OLD-AIC-18 pieces, verbatim (ai_chatter.py:6518-6520 no-sell offers line, :6555-6557 role line,
# :6566-6567 the self-disclosure ban with no day log, :6569, :6577-6584, :6590-6593 contract).
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
# OLD-AIC-18 sticky name (ai_chatter.py:6468-6470).
CALL_HIM = ("\n\nHIS NAME: call him {name} from here on — we already "
            "know it, so NEVER ask his name again; just use it naturally.")
# OLD-AIC-21 (ai_chatter.py:6118-6119 empty facts, :6156-6159 his kink line) and the quote tail
# `_quotes.REPLY_NOW` (old _quotes.py:47; not in this repo).
NOTHING_ON_FILE = "- (nothing on file yet)"
HIS_KINK = ("HE HAS ALREADY TOLD YOU WHAT HE'S INTO: {fetishes}. Talk INSIDE that, his words — NEVER "
            "re-ask what he's into or wants.")
REPLY_NOW = "Reply to his last message now, in the STYLE FOR THIS MESSAGE above."
# OLD-AIC-18's sticker exception, verbatim (ai_chatter.py, `STICKER_EXCEPTION`), after the contract
# when a sticker block is in the prompt.
STICKER_EXCEPTION = " A final STICKER: <tag> line is ALSO allowed (stripped — he only sees the gif)."

# NEW-111 (ticket 34): the sell-off line, in OLD-AIC-17's `{offers_line}` slot on rows sell_off /
# tease_off (spec 03a ASSUMPTION wording, D59; pending the owner's OK).
SELL_OFF_LINE = ("you're not selling in chat right now — if he asks to see something, tell him "
                 "warmly it's on your page and in your mass messages.")
# OLD-AIC-08 BASE, verbatim (ai_chatter.py:6416-6435); its sell step is SELL_STEP (ticket 47).
SEXT_HOT = ("THE THREAD IS HOT — a live sexual scene RIGHT NOW. The one way to throw it away is a "
            "get-to-know question (job, day, city, age) — never. Run the scene:\n"
            "1. STAY IN IT — present tense, first person, dirty, SHORT.\n"
            "2. MAKE HIM SAY WHAT HE WANTS ('what would you do to me if you were here right now?') "
            "— his answer is the whole game.\n"
            "3. MIRROR IT BACK, HOTTER — his words escalated, as if it's already happening.")
# NEW-114 (ticket 34): the Heat line under OLD-AIC-08 (Heat = his level + 1, D44).
SEXT_HEAT = "HEAT {heat} of 4 — run it one step hotter than he is right now, never colder."
# OLD-AIC-01 and OLD-AIC-07, verbatim (ai_chatter.py:6244-6254, :6393-6401).
BRUSH_OFF = ("He thinks you might be a bot — defending is what a bot does. ONE breezy brush-off, then "
             "something HE told you. No sell, no ask.")
DARE = ("He questioned whether you're real last message and you laughed it off. Now DARE him: send a "
        "picture right now and you'll tell him exactly what you see — a bot couldn't. Promise a "
        "rating out of ten; filthy about what you want a picture OF if the thread's explicit, cheeky "
        "if tame. ONE short message. A dare, not a sale: no price, no offer, no questions.")
# NEW-113 (ticket 34): the dare joining, one reply holding both beats (no pending-dare state, D32).
DARE_JOIN = ("\n\nBOTH BEATS GO IN THIS ONE REPLY: the brush-off above first, then right after it "
             "the dare below (the \"last message\" it means is the brush-off you just wrote):\n")
# The old make_right `_APOLOGY_FRAMES`, her lane, the four purchase kinds `complains_now` covers
# (fastt make_right.py:175-184: dup_charge, paid_undelivered, content_dispute, content_letdown;
# not in this repo), verbatim. NEW-112 holds them with the glue.
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
# OLD-CORE-24's goal head (_openers.py:383-388), also the tease's (ticket 46).
GOAL_HEAD = "YOUR GOAL THIS MESSAGE:\n"
# NEW-112 (ticket 34): the make_right glue over the frames, apology only (a Free item: ticket 46).
MAKE_RIGHT_HEAD = (GOAL_HEAD + "- START FROM THIS (rewrite it in your own voice, keep "
                   "the apology) — the one line below that fits what he is unhappy about:\n")
MAKE_RIGHT_TAIL = "- The apology only: no offer, no price and nothing free this time."

# 03b sell_now (NEW-116 assembly), each piece verbatim. OLD-AIC-04 (ai_chatter.py:6331-6336):
CONTENT_ASK = "HE IS ASKING FOR CONTENT RIGHT NOW — stay on it, answer the ask: {close}"
# OLD-AIC-11 (ai_chatter.py:2867-2897): `_CLOSE_BY_ID` and `_INTRO_BY_ID`.
CLOSE_BY_ID = ("Pick the piece from CONTENT YOU CAN ACTUALLY SEND HIM that best fits, tease it from "
               "its description, give the terms, and end with the >>OFFER line.")
INTRO_BY_ID = ("you DO have real content you can send or sell when the moment is right — see CONTENT "
               "YOU CAN ACTUALLY SEND HIM below.")
# OLD-AIC-12 (ai_chatter.py:2899-3058): the item line, its terms, the block (`sell_customs` off:
# `_no_customs` = "never customs, ", no customs rule) and the need-line sentence it ends on.
ITEM_HEAD = "- [id {iid}] {kind}{dur} — {label}: {description}"     # a tease's: no terms (ticket 46)
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
# OLD-CORE-33 plain form (_ppv_caption.py:253-254), `px` as `_money` renders it.
PRICE_BLOCK = ("THE PRICE\nIt unlocks at {px}. You may name it or not, but if you name a price it "
               "must be exactly {px}.")
# OLD-CORE-33 `was_cents` form (_ppv_caption.py:247-251), the old discount resend: a haggle row's
# block when the quote is under the list (ticket 47). `was` = the list, `px` = the quote.
WAS_PRICE_BLOCK = ("THE PRICE\nHe already saw this piece at {was} and did not buy. It is {px} now "
                   "because you cut it for him. You may name {px}; if you name a price it must be "
                   "exactly {px}. Never beg and never apologise for the first price.")
# OLD-AIC-05 (ai_chatter.py:6341-6346), the offer_moment row's beat (ticket 47).
ESCALATION = ("HE'S CLEARLY INTO IT RIGHT NOW — the moment to SELL, not tease. Match his heat in one "
              "short line, then close it: {close}")
# OLD-AIC-08's step 4, appended to SEXT_HOT on a sell Turn while `sexual_now` fired (ticket 47);
# `example` = the lane's `sell_caption_example`. Cut: its last sentence ("If he hasn't described
# anything yet, do step 2 first and sell on the next message.") — the Pick rides this Turn whatever
# the Writer writes, so a "sell later" reply would put the PPV on a question (rwl fa3, ticket 47).
SELL_STEP = ("\n4. THEN SELL HIM WHAT HE JUST DESCRIBED. {close} Write it matched to HIS OWN WORDS, as "
             "the NEXT LINE OF THIS SCENE — never as a product. {example} — not 'check out my new "
             "video'.")
# OLD-AIC-18's OUTPUT_CONTRACT when the sell surface has the marker.
CONTRACT_OFFER = (CONTRACT + " ONE exception: the final >>OFFER line when you pitch a piece "
                  "(stripped — he never sees it).")
# Sext scene (config `sext_scene`, test Mode; owner 2026-11-14 "improve prompts go for it"),
# DRAFT NEW-129..132. SEXT_SCENE replaces SEXT_HOT on a scene Turn (`scene_turn`); its lines 1 and
# 3 ("STAY IN IT…", "MIRROR IT BACK, HOTTER…") are OLD-AIC-08's, verbatim.
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
# The saved scene's stage (`full_ai_scene`), the line under SEXT_SCENE.
SCENE_STAGE = {
    "opening": "WHERE THE SCENE IS: just starting. Pull him in: say what you have on (or don't) "
               "and the first thing you'd do to him if he were here. The idea, never these "
               "words: 'im in bed in just a tshirt rn.. thinking about ur hands under it'",
    "building": "WHERE THE SCENE IS: building. Clothes come off, hands go where he says. Tell "
                "him what you're doing to yourself for him right now and what you want him to "
                "do next — tell him to touch himself for you. The idea, never these words: "
                "'sliding my fingers in while i read that.. stroke it slow for me'",
    "peak": "WHERE THE SCENE IS: he's close. No questions now. Your shortest, dirtiest lines: "
            "you're about to cum, tell him to cum for you. The idea, never these words: "
            "'fuck im so close.. cum with me baby'",
    "after": "WHERE THE SCENE IS: he just finished. Come down with him: one warm, breathless "
             "line about how good that was and what he does to you. No question, nothing to "
             "sell, no new subject in this message.",
}
# The hot sell on a scene Turn (replaces SEXT_HOT + SELL_STEP); `close` / `example` as SELL_STEP's.
SCENE_SELL = ("\nTHIS MESSAGE SENDS HIM A LOCKED PIECE. {close} Write it as the NEXT LINE OF "
              "THIS SCENE, matched to HIS OWN WORDS — what you're doing in it, for him — never "
              "as a product. {example} — not 'check out my new video'.")
# `_chat_system` on a scene Turn: NO_NARRATION_RULE -> SCENE_NARRATION, SELF_BAN -> SCENE_SELF,
# EXPLICIT_EARLY dropped.
SCENE_NARRATION = ("- No *asterisk actions* and no story about yourself in third person — say "
                   "what you're doing as a text to him ('im touching myself rn'), sooner send "
                   "nothing.\n")
SCENE_SELF = "Use what you've learned about him; "
# Refusal -> need-line in the sell slot (spec 03b › Contracts, ticket 10 r3); inventory_unknown: none.
_NEED_LINES = {"no_match": FILMING_MORE, "all_owned": FILMING_MORE, "no_priced_items": FILMING_MORE}

# 03b tease (ticket 46). NEW-123, DRAFT (pending the owner's OK): the tease goal line over the
# Pick's OLD-AIC-12 item line without terms (no price, no `>>OFFER`; his next reply sells it).
TEASE_GOAL = ("- Tease this piece from its description only — make him want it. Name no price and "
              "don't send it yet: it comes with your next message.\n")
# OLD-AIC-12's free terms, verbatim (ai_chatter.py:2930-2939), on a make_right Free item's line.
FREE_TERMS = "FREE — just send it when the moment fits"
# NEW-126, DRAFT (pending the owner's OK): `caption_writer` "caption" — the chat bubbles before a
# PPV whose caption the separate call writes (`full_ai_caption`): no item, price or `>>OFFER`.
CAPTION_APART = ("- A piece goes to him right after this message, with its own caption — lead into "
                 "it warmly. Don't describe it and name no price.\n")

# The Fan fields the prompt reads (`_good_examples`, `resolve_fan_name`, the facts block). A test
# Fan has no `fans` row: these come from the session's `fan_info` fold, the rest read None.
_FAN_FIELDS = ("real_name", "custom_nickname", "generated_nickname", "of_display_name", "his_age",
               "home_country", "home_city", "occupation", "hobbies", "fetishes", "likes_boobs",
               "likes_ass", "recent_events")
_FACT_LABELS = (("age", "his_age"), ("city", "home_city"), ("country", "home_country"),
                ("hobbies", "hobbies"), ("occupation", "occupation"), ("fetishes", "fetishes"))


@dataclass
class WriteResult:
    text: str | None                     # the answering Writer's text; None when none answered
    writer: str | None                   # the MODELS id that answered
    attempts: list[dict[str, Any]] = field(default_factory=list)   # [{writer, outcome, ms}]
    floor_reason: str | None = None


def _fan(fan_info: dict) -> SimpleNamespace:
    return SimpleNamespace(**{k: fan_info.get(k) for k in _FAN_FIELDS})


def _filled(v) -> bool:
    return v is not None and str(v).strip() != ""


def _need_block(facts, fan_just_asked: bool, rng: random.Random) -> str:
    """OLD-AIC-10's tiers in their order: nothing missing -> know enough; the info Jev's pick
    (`facts.next_question`) -> the ask head + wcfi's line for it; he asked -> answer; else a
    breather. With `info_questions: "list"` on chat (`facts.ask_list`) wcfi's own tiers: nothing
    left to ask -> know enough; its ask call -> the ask head + every still-need line; he asked ->
    answer; else a breather."""
    if (al := getattr(facts, "ask_list", None)) is not None:
        if not al.lines:
            return KNOW_ENOUGH
        if al.ask:
            return ASK_HEAD + "\n".join(al.lines)
        return FAN_ASKED if fan_just_asked else rng.choice(_BREATHER_VARIANTS)
    if not info_missing(facts.config, facts.fan_info):
        return KNOW_ENOUGH
    if facts.next_question:                     # a `missing` field (`full_ai_turn._info`): wcfi has its line
        return ASK_HEAD + question_line(facts.next_question, facts.fan_info)
    if fan_just_asked:
        return FAN_ASKED
    return rng.choice(_BREATHER_VARIANTS)


def _chat_system(persona: str, need_block: str, call_him: str, style: str, good: str, *,
                 style_on: bool, nonnative_on: bool, painful_on: bool, offers: str,
                 sticker_block: str, sell_block: str = "", marker: bool = False,
                 v: _voice.VoiceBlocks = _voice.HER, scene: bool = False) -> str:
    """OLD-AIC-18 (ai_chatter.py:6546-6633) with no day log, clock, language directive, customs or
    life tip (none exists for a test Fan); `offers` fills its `{offers_line}` slot, `sticker_block`
    its `{stickers}` slot (plus the sticker exception), `sell_block` its `{sell_section}` (03b) and
    `marker` picks the contract with the `>>OFFER` exception. `scene` (a scene Turn with config
    `sext_scene`): SCENE_SELF for SELF_BAN, SCENE_NARRATION for NO_NARRATION_RULE, no EXPLICIT_EARLY."""
    humanizer = f"\n\n{v.humanizer}" if style_on else v.emoji_vocab
    nonnative = f"\n\n{NONNATIVE_REGISTER}" if nonnative_on else ""
    stickers = f"\n\n{sticker_block}" if sticker_block else ""
    return (
        f"{persona}\n\n"
        + ROLE + (SCENE_SELF if scene else SELF_BAN) + (f"{offers} " if offers else "") + READ_ALL
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
    )


def spend_line(spent) -> str | None:
    """OLD-AIC-22 (ai_chatter.py:5440-5489, text 5482-5487) over his bought PPVs `spent`
    (`amount_cents` each); None for a non-spender. Its tip part waits for a tip source (live,
    Phase 05): the Test chat has PPV purchases only."""
    ppv = [b.amount_cents for b in spent]
    if not ppv:
        return None
    ppv_n, ppv_total, ppv_max = len(ppv), sum(ppv), max(ppv)
    return (f"he's spent: unlocked {ppv_n} PPV{'s' if ppv_n != 1 else ''} (${ppv_total // 100} total, "
            f"biggest ${ppv_max // 100}) — talk like you remember it, never like he's never paid.")


def _chat_user(f: SimpleNamespace, rows: list, spent: list) -> str:
    """OLD-AIC-21 (ai_chatter.py:6095-6162, :6187-6190, :6635-6645): facts (with OLD-AIC-22's
    spend line when he has bought), his kink, the last `_HISTORY_TAIL` lines, the quote tail."""
    facts = []
    name = resolve_fan_name(f)
    if name:
        facts.append(f"name/nickname: {name.split('/')[0][:40]}")
    for label, attr in _FACT_LABELS:
        val = getattr(f, attr)
        if _filled(val):
            facts.append(f"{label}: {str(val).strip()[:80]}")
    if spend := spend_line(spent):
        facts.append(spend)
    facts_block = "\n".join(f"- {x}" for x in facts) if facts else NOTHING_ON_FILE
    personal_block = ("\n" + HIS_KINK.format(fetishes=str(f.fetishes).strip()[:160])
                      if _filled(f.fetishes) else "")
    lines = [(m.direction, line_text(m)) for m in rows[-_HISTORY_TAIL:]]
    convo = "\n".join(f"{'FAN' if d == 'in' else 'YOU'}: {b}" for d, b in lines if b)
    return (f"What you know about him:\n{facts_block}{personal_block}\n\n"
            f"Recent conversation (oldest→newest):\n{convo}\n\n"
            + REPLY_NOW)


def style_flags(config: dict) -> dict[str, bool]:
    """The side's `style` layers (`full_ai_config.style_layers`; an old `text_style` side: girl =
    every layer on, formal = all off) as the reply chain's style switches."""
    s = style_layers(config)
    return {"style_on": s["texting"], "nonnative_on": s["nonnative"], "spacing_on": s["spacing"],
            "typo_on": s["typos"], "painful_on": s["painful"]}


def _his_first_name(f: SimpleNamespace, v: _voice.VoiceBlocks) -> str:
    """The name an apology frame opens with, as the old make_right `_fan_first_name` took it: the
    first word of his name when it is 2-20 letters, else her lane's fan address."""
    name = (resolve_fan_name(f) or "").split("/")[0].split()
    first = name[0] if name else ""
    return first if first.isalpha() and 2 <= len(first) <= 20 else v.fan_address


def _beat(route: str, heat: int, f: SimpleNamespace, item: Pick | None) -> str | None:
    """The Route's beat in OLD-AIC-18's goal slot; None keeps the chat goal (`_need_block`).
    `item` is the Pick the prompt carries (`_carries_item`). A tease with one: OLD-CORE-24's head,
    the DRAFT tease goal line and the item line without terms. make_right with a Free item: the
    frames, then the item line with OLD-AIC-12's FREE terms in place of the apology-only tail (no
    SELLING RULES)."""
    if route == "tease" and item:
        return GOAL_HEAD + TEASE_GOAL + item_line(item, None)
    if route == "sext":
        return f"{SEXT_HOT}\n{SEXT_HEAT.format(heat=heat)}"
    if route == "ai_dare":
        return BRUSH_OFF + DARE_JOIN + DARE
    if route == "make_right":
        name = _his_first_name(f, _voice.HER)
        return (MAKE_RIGHT_HEAD + "".join(f"  - {x.replace('{name}', name)}\n" for x in APOLOGY_FRAMES)
                + (item_line(item, FREE_TERMS) if item else MAKE_RIGHT_TAIL))
    return None


def _carries_item(route: str, pick: Pick | Refusal | None) -> bool:
    """A tease with a Pick, or make_right with a Free item (a Pick at price 0; a priced Pick there
    is ignored, as on every non-selling Route)."""
    return isinstance(pick, Pick) and (route == "tease" or (route == "make_right" and pick.price_cents == 0))


def item_line(pick: Pick, terms: str | None) -> str:
    """OLD-AIC-12's item line for the Pick: its `ref` as the id, the anchor's kind and length
    (` m:ss` on a clip), the label and the anchor's describe text (`pick.facts["description"]`);
    `terms` None drops the ` — {terms}` tail (a tease names no price).

    ASSUMPTION: the vault has no item label, so the label is OLD-AIC-12's own fallback
    'untitled', or "<n> photos" for a photo set (the count is true; the Writer must not invent
    one). Overturned by an owner-set label field."""
    facts = pick.facts or {}
    items = facts.get("items") or []
    secs = items[0].get("seconds") if items else None
    dur = f" {secs // 60}:{secs % 60:02d}" if pick.format == "video" and secs else ""
    label = f"{len(pick.media)} photos" if len(pick.media) > 1 else "untitled"
    line = ITEM_HEAD if terms is None else ITEM_LINE
    return line.format(iid=pick.ref, kind=pick.format, dur=dur, label=label,
                       description=str(facts.get("description") or "").strip(), terms=terms)


def sell_section(pick: Pick, was_cents: int | None) -> str:
    """The sell_now `{sell_section}`: the OLD-AIC-12 block with the one item line, then
    OLD-CORE-33's price block at the Pick's price: its `was_cents` form when `was_cents` (the price
    he already saw this piece at, `was_cents_of`) is over the price, as the old code used it only
    when `was > price`; else the plain form."""
    line = item_line(pick, TERMS.format(dollars=pick.price_cents // 100))
    px = _money(pick.price_cents)
    price = (WAS_PRICE_BLOCK.format(was=_money(was_cents), px=px)
             if was_cents and was_cents > pick.price_cents else PRICE_BLOCK.format(px=px))
    return MANIFEST.format(no_customs=NO_CUSTOMS, items=line) + "\n\n" + price


def was_cents_of(row: str, pick: Pick, offer_piece: Teased | None) -> int | None:
    """The price he already saw `pick` at: on a haggle row re-offering the open Offer's own piece
    (`offer_piece`, `TurnFacts.offer_piece`; same locked media), that Offer's list; else None. A
    Pending tease named no price and a re-pick is a piece he never saw, so neither has one."""
    if row != "haggle" or offer_piece is None or tuple(sorted(pick.media)) != offer_piece.locked:
        return None
    return offer_piece.list_cents


def scene_flag(facts) -> bool:
    """Config `sext_scene` counts: test Mode only (Shadow / live never)."""
    return getattr(facts, "mode", None) == "test" and bool(facts.config.get("sext_scene"))


def is_hot(fired, facts) -> bool:
    """The side's `sext_on` and `sexual_now` fired, or with `scene_flag` `scene_on`."""
    return bool(facts.config["sext_on"]) and (
        "sexual_now" in fired or (scene_flag(facts) and "scene_on" in fired))


def scene_turn(decision, facts) -> bool:
    """With `scene_flag`: a scene Turn is Route sext, or sell_now while `is_hot`."""
    return scene_flag(facts) and (
        decision.route == "sext" or (decision.route == "sell_now" and is_hot(decision.fired, facts)))


def gif_offered(decision, facts) -> bool:
    """The sticker block goes in the prompt: `config.gifs`; with `scene_flag` never on a scene Turn,
    else only when Jev's `gif_fits` fired. Flag off: every Turn, as before."""
    if not facts.config.get("gifs"):
        return False
    if not scene_flag(facts):
        return True
    return not scene_turn(decision, facts) and "gif_fits" in decision.fired


def scene_of(decision, facts) -> dict | None:
    """This Turn's saved scene on a scene Turn (`facts.scene_now`, set by `run_turn`; a fresh
    opening at the Turn's Heat when unset), else None."""
    if not scene_turn(decision, facts):
        return None
    return getattr(facts, "scene_now", None) or {"n": 1, "stage": "opening", "heat": decision.heat}


def _scene_head(stage: str) -> str:
    return f"{SEXT_SCENE}\n{SCENE_STAGE[stage]}"


def sell_beat(row: str, hot: bool, scene: str | None = None) -> str:
    """The sell_now beat in OLD-AIC-18's goal slot: OLD-AIC-04 (rows sell, haggle) or OLD-AIC-05
    (offer_moment), each closing with `_CLOSE_BY_ID`; while `sexual_now` fired (`hot`, any sell row)
    OLD-AIC-08 with its step 4 instead.
    ASSUMPTION: `hot` also needs the side's `sext_on` (`write`): with sexting off no sell Turn gets
    the sext scene prompt. Overturned if the owner wants step 4 whatever `sext_on` says.
    ASSUMPTION: the hot sell beat carries no NEW-114 Heat line (old OLD-AIC-08 had none; the Heat
    line is the sext Route's). Overturned if the owner wants it on hot sells too.
    `scene` (the stage on a scene Turn, `sext_scene`): SEXT_SCENE + the stage line + SCENE_SELL."""
    if scene:
        return _scene_head(scene) + SCENE_SELL.format(close=CLOSE_BY_ID,
                                                      example=_voice.HER.sell_caption_example)
    if hot:
        return SEXT_HOT + SELL_STEP.format(close=CLOSE_BY_ID, example=_voice.HER.sell_caption_example)
    return (ESCALATION if row == "offer_moment" else CONTENT_ASK).format(close=CLOSE_BY_ID)


def messages_for(route: str, row: str, heat: int, facts, pick: Pick | Refusal | None, *,
                 persona: str = PERSONA_FALLBACK, hot: bool = False, plain: bool = False,
                 scene: str | None = None, gif_ok: bool | None = None) -> list[dict]:
    """The Route's Writer messages; [] for no_send (no Writer call). Pure; the style and breather
    draws are seeded per Turn (`facts.anchor_key`), so a replay builds the same prompt. `pick` is
    the sell step's result (03b): on sell_now a Pick makes the content-ask sell prompt (its item's
    describe text from `pick.facts["description"]`), a Refusal chat plus its need-line; on tease a
    Pick makes the priceless tease (`_beat`), a Refusal chat plus its need-line; on make_right a
    Free item (price 0) joins the apology; ignored on every other Route. On sell_now the beat is
    `sell_beat(row, hot)` (`hot`: `sexual_now` fired on a `sext_on` side) and the price block
    `sell_section(pick, was_cents_of(row, pick, facts.offer_piece))`. `plain` (the separate
    caption wrote the PPV's line, `config.caption_writer` "caption"): a sell_now Pick or Free item
    gets no item line, price block or marker — the DRAFT `CAPTION_APART` goal (under OLD-AIC-08's
    scene while `hot`, under the apology frames on make_right) and OLD-AIC-17's `NO_SELL_OFFERS`.
    `scene`: the saved scene's stage on a scene Turn (`scene_turn`, `sext_scene`): SEXT_SCENE + the
    stage line take SEXT_HOT's place (sext: + SEXT_HEAT at `heat`, the folded scene heat; a hot sell:
    + SCENE_SELL; apart: + CAPTION_APART; a sell Refusal: + its need-line) and `_chat_system` runs
    its scene form. `gif_ok`: the sticker block (`gif_offered`); None = `config.gifs`, as before."""
    if route == "no_send":
        return []
    rows = facts.cut_rows
    rng = random.Random(f"full_ai:{facts.anchor_key}")
    flags = style_flags(facts.config)
    style_extra = ((STYLE_3LINE,) * 2 + (STYLE_BRIEF,) * 2) if flags["style_on"] else ()
    style = rng.choice(_STYLE_VARIANTS + style_extra)
    fan_run: list[str] = []
    for m in reversed(rows):
        if m.direction == "in" and line_text(m):
            fan_run.append(line_text(m))
        elif fan_run:
            break
    f = _fan(facts.fan_info)
    selling = route == "sell_now" and isinstance(pick, Pick)
    apart = plain and (selling or (route == "make_right" and _carries_item(route, pick)))
    if apart:
        if route == "make_right":
            name = _his_first_name(f, _voice.HER)
            need = (MAKE_RIGHT_HEAD + "".join(f"  - {x.replace('{name}', name)}\n" for x in APOLOGY_FRAMES)
                    + CAPTION_APART)
        else:
            need = (f"{_scene_head(scene)}\n{CAPTION_APART}" if scene
                    else f"{SEXT_HOT}\n{CAPTION_APART}" if hot else GOAL_HEAD + CAPTION_APART)
        sell_block, offers, selling = "", NO_SELL_OFFERS, False
    elif selling:
        need = sell_beat(row, hot, scene)
        sell_block, offers = sell_section(pick, was_cents_of(row, pick, facts.offer_piece)), INTRO_BY_ID
    else:
        item = pick if _carries_item(route, pick) else None
        if scene:
            need = _scene_head(scene) + (f"\n{SEXT_HEAT.format(heat=heat)}" if route == "sext" else "")
        else:
            need = _beat(route, heat, f, item) or _need_block(facts, "?" in " ".join(fan_run), rng)
        refused = route in ("sell_now", "tease") and isinstance(pick, Refusal)
        sell_block = _NEED_LINES.get(pick.reason, "") if refused else ""
        # ASSUMPTION (ticket 46): a tease / Free item leaves the offers slot empty — OLD-AIC-17's
        # "never … pitch a piece yourself" fights its goal, and `_INTRO_BY_ID` points at a manifest
        # these prompts don't carry.
        offers = "" if item else SELL_OFF_LINE if row in ("sell_off", "tease_off") else NO_SELL_OFFERS
    durable = _filled(f.real_name) or _filled(f.custom_nickname)
    name = resolve_fan_name(f)
    call_him = CALL_HIM.format(name=name.split("/")[0][:40]) if durable and name else ""
    system = _chat_system(persona, need, call_him, style, _good_examples(f, set(), durable),
                          style_on=flags["style_on"], nonnative_on=flags["nonnative_on"],
                          painful_on=flags["painful_on"], v=_voice.HER, offers=offers,
                          sell_block=sell_block, marker=selling, scene=scene is not None,
                          # GIFs on: the pack offered every Turn (no roll), her lane (`gif_ok`).
                          sticker_block=cat_stickers.prompt_block("allow", _voice.VOICE_HER)
                          if (facts.config.get("gifs") if gif_ok is None else gif_ok) else "")
    # No spend line beside a Pick (sold, teased or free): its amounts would fail the price check
    # (rwl fa3 S3).
    spent = [] if apart or selling or _carries_item(route, pick) else facts.spent
    return [{"role": "system", "content": system}, {"role": "user", "content": _chat_user(f, rows, spent)}]


# The code floor (research 11 › §6): a reply holding prompt or protocol text, junk script or no
# words at all is rejected before the shared chain and the next Writer is tried (`floor_on`).
_BRACKET = re.compile(r"\[.*?\]", re.S)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")
# OLD-AIC-12's marker as a whole line (the old `_parse_offer_marker` stripped every marker).
_OFFER_LINE = re.compile(r"^[ \t]*>>OFFER[ \t]+(\S+)[ \t]*$", re.M)


def strip_offer(text: str) -> str:
    """The Writer's text with every whole `>>OFFER <ref>` line removed: he never sees it, and the
    Pick never depends on it (spec 03b ASSUMPTION). Pure."""
    return re.sub(r"\n{3,}", "\n\n", _OFFER_LINE.sub("", text)).strip()


def floor(text: str, lang: str, offer_ref: int | None = None) -> str | None:
    """The code floor's reject reason, None when the reply passes. Pure. A whole `>>OFFER <ref>`
    line naming the Pick's `offer_ref` is stripped before the checks; one naming another ref
    (or any, with no Pick) rejects `offer_ref`; any other `>>` is stray (`chevron`). A missing
    marker is fine.

    ASSUMPTION: the marker line is accepted anywhere in the reply, not only last (a `STICKER:`
    line may follow it, as OLD-AIC-18 allows both); the old parser stripped every marker. Overturned
    if only the final line may carry it."""
    if any(m.group(1) != str(offer_ref) for m in _OFFER_LINE.finditer(text)):
        return "offer_ref"
    text = strip_offer(text)
    if _BRACKET.search(text):
        return "bracket"
    if "framework:" in text.lower():
        return "framework"
    if ">>" in text:
        return "chevron"
    if lang == "en" and _CJK.search(text):
        return "cjk"
    if not any(ch.isalpha() for ch in text):
        return "no_letters"
    return None


def reject(text: str, lang: str, gifs: bool, offer_ref: int | None = None, *,
           item: bool = False) -> str | None:
    """The floor on what the fan would read. Sticker markers go first (the Turn strips them
    before the chain anyway), so `[STICKER: kiss]` is not a `bracket` reject. A reply that is
    only a marker passes with GIFs on and a known tag (the gif is the reply) when it carries no
    item (no offer expected, `offer_ref` None, and no tease / Free item, `item` False); otherwise
    it has no words left and the next Writer is tried."""
    body, tag = cat_stickers.parse_marker(text)
    if not body:
        return None if gifs and tag and offer_ref is None and not item else "no_letters"
    return floor(body, lang, offer_ref)


def _outcome(e: llm_client.LLMError) -> str:
    """An `llm_client.chat` failure as the attempt's outcome (spec › Interfaces › full_ai_writers):
    a key refusal by status, a missing key or provider `no_key`, a transport fault `timeout`."""
    if isinstance(e, llm_client.LLMCapExceeded):
        return "cap"
    if isinstance(e, llm_client.LLMKeyError) and e.kind != "missing":
        return f"http_{e.status}"
    if isinstance(e, llm_client.LLMConfigError):
        return "no_key"
    status = getattr(e, "status", None)
    return f"http_{status}" if status is not None else "timeout"


async def write(decision, facts, *, deadline: float, writers: list[str] | None = None,
                plain: bool = False) -> WriteResult:
    """Build the Route's messages once (her persona read as wcfi reads it), then walk the side's
    `writers` in order, one attempt each within `writer_timeout_s` capped at the time left before
    `deadline` (the Turn's `time.monotonic()` instant, set by `run_turn`). The next Writer runs
    only when the one before fails: an `llm_client` error (`_outcome`), an empty reply, or a
    code-floor reject (`floor_on`). With no time left a Writer is not called and is recorded
    `timeout`. `floor_reason` is the first floor reject's reason. `facts.pick` (03b's sell
    step) reaches `messages_for`, and the answering text has its `>>OFFER` line stripped
    (`strip_offer`, floor on or off). `writers` replaces the side's list (the Claim audit's one
    rewrite passes the Writer that answered, ticket 45). `plain`: the chat bubbles beside a separate
    caption (`messages_for`), so no `>>OFFER` line is expected (any rejects `offer_ref`). On a scene
    Turn (`scene_of`) the Writer's Heat and stage are the saved scene's (never colder)."""
    cfg = facts.config
    pick = facts.pick
    selling = decision.route == "sell_now" and isinstance(pick, Pick)
    offer_ref = pick.ref if selling and not plain else None
    item = _carries_item(decision.route, pick) or selling and plain   # no sticker-only reply (S2)
    now = scene_of(decision, facts)
    gif_ok = gif_offered(decision, facts)
    msgs = messages_for(decision.route, decision.row, now["heat"] if now else decision.heat, facts,
                        pick, persona=await _load_persona(facts.account_id),
                        hot=is_hot(decision.fired, facts), plain=plain,
                        scene=now["stage"] if now else None, gif_ok=gif_ok)
    lang = await _language.load_account_language(facts.account_id) if cfg["floor_on"] else ""
    res = WriteResult(None, None)
    for writer in writers or cfg["writers"]:
        timeout = min(float(cfg["writer_timeout_s"]), deadline - time.monotonic())
        if timeout <= 0:
            res.attempts.append({"writer": writer, "outcome": "timeout", "ms": 0})
            continue
        t0, text, reason = time.perf_counter(), "", None
        try:
            r = await llm_client.chat(model=writer, messages=msgs, purpose=PURPOSE,
                                      account_id=facts.account_id, temperature=_REPLY_TEMPERATURE,
                                      timeout_s=timeout, max_attempts=1)
            text = (r.content or "").strip()
            reason = (reject(text, lang, gif_ok, offer_ref, item=item)
                      if text and cfg["floor_on"] else None)
            outcome = "empty" if not text else f"floor:{reason}" if reason else "ok"
        except llm_client.LLMError as e:
            outcome = _outcome(e)
        res.attempts.append({"writer": writer, "outcome": outcome,
                             "ms": int((time.perf_counter() - t0) * 1000)})
        if outcome == "ok":
            res.text, res.writer = strip_offer(text), writer
            return res
        if reason and res.floor_reason is None:
            res.floor_reason = reason
    return res
