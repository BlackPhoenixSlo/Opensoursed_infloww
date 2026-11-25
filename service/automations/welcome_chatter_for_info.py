from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import dm_rate
import read_flip
import run_slot
import llm_client
from . import _daylog
from . import _language
from . import _voice
from . import _openers
from attribution import write_outbound_attribution
from automation_registry import register
from db.engine import get_session
from db.models import (
    AccountAiConfig, AutomationRule, Blacklist, Fan, FanProfile, FunnelState,
    MassRun, Message, ScheduledJob, SkipList,
)
from llm_client import LLMCapExceeded
from ._prompt_rules import (
    BIO_CONSISTENCY_GUARDRAIL,
    NO_NARRATION_RULE, ONPLATFORM_GUARDRAIL,
    STYLE_3LINE, STYLE_BRIEF, STYLE_MAX_BUBBLES,
)
from ._textutil import is_substantive_msg, nonempty
from ._style_flags import (
    load_consistency_flags, load_factground_flag, load_nonnative_flags,
    load_painful_texting_flag, load_spacing_flags, load_strip_emojis, load_style_flags,
    load_typo_flags, load_voice_blocks,
)
from ._nonnative import NONNATIVE_OUTPUTS, NONNATIVE_REGISTER
from ._inbound import (
    TurnHandoff,
    TURN_NEUTRAL_KINDS, _REACTION_TAG,
)
from ._fan_notes import build_facts_note, facts_from_fan, push_nick_and_notes
from .names import build_structured_nickname, resolve_fan_name
from ._knobs import coerce_ids
from ._intent import content_payer_fans
from ._typing_hold import (
    hold_with_typing, load_typing_indicator, load_typing_wpm, typing_delay_seconds,
)
from ._typos import apply_typo_throttle
from ._send_failure import quarantine_if_undeliverable, skip_unreachable_fan
from ._model_pick import resolve_model
from ._skiplist import load_promo_spam_ids, should_skip_muted_creator
from ._bubbles import _TRAIL_EMOJI_RE, _history_text, _strip_html
from . import wcfi_decide
from . import _reply_shape
from ._wordfilter import (
    banned_hit_summary, load_banned_words,
)
from ._clock import clock_block, clock_line, load_clock_tz
from ._persona import (
    claims_to_scalars, compose_persona, fan_claims_block, mentions_self_claim,
    merge_persona_claims, parse_persona_claims, persona_register_age,
)
from ._outbound import ConsistencyCtx, finalize_draft
from ._model_wait import freed_chat
from .rhythm import INLINE_MAX_S
from . import cat_stickers
from . import gen_info
import smart_message_extras as extras

# Pause long enough for scrape_chats to record the real send first.
_NOID_PAUSE = timedelta(hours=1)

log = logging.getLogger("of-relay.automation.welcome_chatter_for_info")

_PURPOSE = "welcome_chatter_for_info"
_MAX_FAN_MESSAGES = 10
# Counts OUR confirmed replies (turn_counter), so a fan who chats forever without revealing bio facts still graduates.
_MAX_TURNS = 30
_INFO_COMPLETE_RATIO = 0.75
_DEFAULT_LIMIT = 200
_DEFAULT_MAX_REPLIES = 25
_FAN_SELECT_CHUNK = 500
_REPLY_TEMPERATURE = 0.85
# Durable info rides in the facts block, so ~20 turns is enough and halves the uncached input vs 40.
_HISTORY_TAIL = 20
_EXTRACT_HISTORY_TAIL = 8
_REPLY_MAX_CHARS = 600
# Live chat: a short rest, just long enough to stop a double-fire; this lane also releases its lease on success, so this is the sole gate.
_REPLY_COOLDOWN_S = 10

_STYLE_VARIANTS = (
    "one short line, one emoji that fits.",
    "one short line, NO emoji this time.",
    ("TWO tiny texts on separate lines — a 2-4 word reaction, then your "
     "line/question. 0-1 emoji."),
    "one lazy lowercase line, no ending punctuation.",
    "one short line, emoji NOT 😏 (😈 🙈 😅 🥵) or none.",
    "dont gush over his answer — a 1-2 word ack, then straight to your next question.",
)

_BREATHER_VARIANTS = (
    "THIS MESSAGE: don't ask anything — just react, let it breathe.",
    "THIS MESSAGE: don't ask anything — tease him a lil, playful not mean.",
    "THIS MESSAGE: don't ask anything — react + a small thought of your own.",
)


def _is_info_complete(f: Fan) -> bool:
    groups = (
        nonempty(f.his_age),
        nonempty(f.home_country) or nonempty(f.home_city),
        nonempty(f.hobbies),
        (nonempty(f.recent_events) or nonempty(f.fetishes)
         or bool(f.likes_boobs) or bool(f.likes_ass)),
    )
    return (sum(1 for g in groups if g) / len(groups)) >= _INFO_COMPLETE_RATIO


async def _load_persona(account_id: str) -> str:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, account_id)
    return compose_persona(cfg, fallback=(
        "You are a warm, flirty OnlyFans creator chatting with one of your fans."))



async def _load_stop_lists(account_id: str) -> tuple[set[int], set[int]]:
    async with get_session() as s:
        bl = (await s.execute(select(Blacklist.fan_id))).all()
        sk = (await s.execute(
            select(SkipList.fan_id).where(SkipList.account_id == str(account_id))
        )).all()
    return {int(r[0]) for r in bl}, {int(r[0]) for r in sk}


async def _load_mid_funnel_fans(account_id: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(FunnelState.fan_id)
            .join(MassRun, MassRun.id == FunnelState.mass_run_id)
            .where(MassRun.account_id == str(account_id),
                   FunnelState.status == "pending")
        )).all()
    return {int(r[0]) for r in rows}


class _Candidate:
    __slots__ = ("fan_id", "fan_msg_n", "last_dir", "last_body", "messages",
                 "last_in_body", "turn", "closing_cut")

    def __init__(self, fan_id: int):
        self.fan_id = fan_id
        self.fan_msg_n = 0
        self.last_dir = ""
        self.last_body = ""
        self.last_in_body = ""
        # send_welcome's turn handoff — his newest WORDED inbound (distinct from
        # `last_in_body`, his newest inbound of ANY kind) and whether anything
        # but a welcome bubble has answered him since. The whole seam is
        # `_inbound.TurnHandoff`; this lane only feeds it rows and asks `admit`.
        # Every non-welcome outbound narrows the window, blasts included — this
        # lane's turn gate is already blast-blind, so a handoff cancelled by a
        # mass send just degrades to today's behaviour (he waits for his own
        # next message). Errs toward silence, the safe direction for a rescue.
        self.turn = TurnHandoff()
        self.messages: list[tuple[str, str]] = []
        self.closing_cut = False


async def _gather(account_id: str,
                  fan_ids: set[int] | None = None) -> dict[int, _Candidate]:
    out: dict[int, _Candidate] = {}
    where = [Message.account_id == str(account_id), Message.is_unsent.is_(False)]
    if fan_ids:
        where.append(Message.fan_id.in_(fan_ids))
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.direction, Message.body,
                   Message.image_desc,
                   # Read for two things: `out_since_in_all_welcome` (the guard on
                   # the turn handoff) and the turn-neutral rule below.
                   Message.automation_kind)
            .where(*where)
            .order_by(Message.fan_id, Message.created_at, Message.message_id)
        )).all()
    for fan_id, direction, body, image_desc, automation_kind in rows:
        c = out.get(fan_id)
        if c is None:
            c = out[fan_id] = _Candidate(int(fan_id))
        text = _history_text(direction, body, image_desc)
        if direction == "out" and automation_kind in TURN_NEUTRAL_KINDS:
            tag = _REACTION_TAG[automation_kind]
            text = f"{text} {tag}" if text else tag
        c.messages.append((direction, text))
        answers_him = not (direction == "out"
                           and automation_kind in TURN_NEUTRAL_KINDS)
        if answers_him:
            c.last_dir = direction
            c.last_body = text
        if direction == "in":
            c.last_in_body = text
            # …and the handoff seam. ⚠️ `_strip_html(body)`, NOT `text`: `text`
            # is this lane's HISTORY LINE and carries "[he sent: …]" for any
            # described row — our own synthesis, not him speaking — and the seam
            # installs this string as the model's "his line". The describe is not
            # lost: it is in `c.messages` via `_history_text`.
            c.turn.on_inbound(body, _strip_html(body))
        else:
            c.turn.on_outbound(took_the_turn=answers_him,
                               automation_kind=automation_kind)
        if direction == "in" and is_substantive_msg(text):
            c.fan_msg_n += 1
    return out


def _questions_still_needed(f: Fan, asked: set[str]) -> list[tuple[str, str]]:
    name = nonempty(f.real_name) or nonempty(f.custom_nickname)
    age = nonempty(f.his_age)
    country = nonempty(f.home_country)
    city = nonempty(f.home_city)
    occupation = nonempty(f.occupation)
    hobbies = nonempty(f.hobbies)
    fetishes = nonempty(f.fetishes)
    boobs = bool(f.likes_boobs)
    ass = bool(f.likes_ass)
    events = nonempty(f.recent_events)

    q: list[tuple[str, str]] = []
    if not name and "name:2" not in asked:
        q.append(("name", "- You DON'T know his real name yet. Ask what his name is "
                  "/ what you should call him."))
    if not age and "age:2" not in asked:
        q.append(("age", "- You DON'T know his age yet. Find out how old he is."))
    if not country and not city and "location:2" not in asked:
        q.append(("location", "- You DON'T know where he lives. Ask where he's from."))
    if not country and city and "country_from_city" not in asked:
        q.append(("country_from_city",
                  f"- He mentioned {str(f.home_city).strip()} but you don't know "
                  "which country. Confirm or guess the country."))
    if country and not city and "city" not in asked:
        q.append(("city",
                  f"- You know he's from {str(f.home_country).strip()} but not which "
                  "city/area. Ask what part."))
    if not occupation and "job:2" not in asked:
        q.append(("job", "- You DON'T know what he does for work. Ask what he does for a living."))
    if not hobbies and "hobbies" not in asked:
        q.append(("hobbies", "- You DON'T know his hobbies yet. Ask what he likes to do."))
    if not events and "recent_events" not in asked:
        q.append(("recent_events", "- Ask what's new in his life lately."))
    if not boobs and not ass and not fetishes and "boobs_ass" not in asked:
        q.append(("boobs_ass", "- You DON'T know what he's into (boobs/ass). Ask playfully."))
    q.sort(key=lambda kv: kv[0] in asked)
    return q


# Colorful, job-specific riffs for the grounded occupation example (flavor B):
# keyed on a lowercased occupation, generic fallback otherwise. Every riff rides
# on his REAL job — nothing invented — so "a chef? bet u cook fire" only ever
# reaches a fan we actually know is a chef.
_JOB_RIFFS = {
    "chef": "bet u cook fire, fave dish?",
    "cook": "bet u cook fire, fave dish?",
    "nurse": "bet u take good care of everyone",
    "teacher": "bet the class has a crush on u",
    "pilot": "bet uve got the best stories",
    "cop": "ooh someone who likes bein in charge",
    "police": "ooh someone who likes bein in charge",
    "firefighter": "so u run into fires huh, brave",
    "lawyer": "bet u always win the argument",
    "engineer": "brains huh, i like that",
    "doctor": "bet u know exactly what ur doin",
    "trucker": "all those miles alone, bet u get bored",
    "driver": "all those miles, bet u get bored",
}


def _good_examples(f: Fan, asked: set[str], have_durable_name: bool) -> str:
    needed = {k for k, _ in _questions_still_needed(f, asked)}

    ask_ex: list[str] = []
    if not have_durable_name and "name" in needed:
        ask_ex.append('"haha thanks what should i call u?"')
    if "age" in needed:
        ask_ex.append('"aww how old are ya"')
    if "job" in needed:
        ask_ex.append('"so what do u do for work?"')
    if needed & {"location", "city", "country_from_city"}:
        ask_ex.append('"where u textin me from"')

    def _clip(v) -> str:
        return str(v).strip()[:30]
    known_ex: list[str] = []
    if nonempty(f.occupation):
        _job = _clip(f.occupation).lower()
        known_ex.append(f'"a {_job}? {_JOB_RIFFS.get(_job, "bet that keeps u busy")}"')
    if nonempty(f.home_city):
        known_ex.append(f'"{_clip(f.home_city)}? ive always wanted to go there"')
    if nonempty(f.his_age):
        known_ex.append(f'"{_clip(f.his_age)} and still trouble huh"')
    if nonempty(f.hobbies):
        known_ex.append(f'"still into {_clip(f.hobbies).lower()}? love that about u"')
    if nonempty(f.recent_events):
        known_ex.append(f'"hows {_clip(f.recent_events).lower()} going btw"')
    if nonempty(f.fetishes):
        known_ex.append(f'"mmm {_clip(f.fetishes).lower()}? had a feeling about u"')
    if f.likes_ass and f.likes_boobs:
        known_ex.append('"so u like it all huh, greedy"')
    elif f.likes_ass:
        known_ex.append('"an ass man huh, noted"')
    elif f.likes_boobs:
        known_ex.append('"a boobs guy huh, good to know"')

    ex = known_ex[:2] + ask_ex[:2]
    if not ex:
        ex = ['"mmm tell me more"', '"u always know what to say"',
              '"ok thats actually hot"']
    return "- GOOD: " + " / ".join(ex[:4]) + "\n"


_ASK_PRIORITY = ("name", "age", "location", "country_from_city", "city",
                 "job", "hobbies", "recent_events", "boobs_ass")


def _primary_ask_target(presented: list[str]) -> str | None:
    s = set(presented)
    for k in _ASK_PRIORITY:
        if k in s:
            return k
    return presented[0] if presented else None


def _gather_done(f: Fan, asked: set[str]) -> bool:
    if not _questions_still_needed(f, asked):
        return True
    return int(getattr(f, "turn_counter", 0) or 0) >= _MAX_TURNS


def _turn_asked(bubbles: list[str]) -> bool:
    for b in bubbles:
        if _TRAIL_EMOJI_RE.sub("", b or "").rstrip().endswith("?"):
            return True
    return False


def _recent_ask_pattern(history: list[tuple[str, str]]) -> tuple[int, bool]:
    turns: list[bool] = []
    run: list[str] = []
    for d, b in history:
        if d == "out":
            run.append(b)
        elif run:
            turns.append(_turn_asked(run))
            run = []
    if run:
        turns.append(_turn_asked(run))
    if not turns:
        return 0, False
    streak = 0
    for asked_q in reversed(turns):
        if not asked_q:
            break
        streak += 1
    return streak, (not turns[-1])


def _build_messages(persona: str, f: Fan, c: _Candidate,
                    asked: set[str],
                    history_tail: int = _HISTORY_TAIL,
                    style_on: bool = False,
                    nonnative_on: bool = False,
                    painful_on: bool = True,
                    lang: str = "en",
                    profile: "FanProfile | None" = None,
                    clock: str = "",
                    sticker_mode: str = "skip",
                    opener: "_openers.Opener | None" = None,
                    v: "_voice.VoiceBlocks" = _voice.HER,
                    day: "_daylog.Day" = _daylog.NO_DAY,
                    ) -> tuple[list[dict], list[str]]:
    questions = _questions_still_needed(f, asked)
    question_lines = "\n".join(line for _, line in questions)
    presented = [k for k, _ in questions]

    facts = []
    name = resolve_fan_name(f)
    have_durable_name = bool(name) and (nonempty(f.custom_nickname)
                                        or nonempty(f.real_name))
    if name:
        facts.append(f"name/nickname: {name.split('/')[0][:40]}")
    for label, val in (("age", f.his_age), ("city", f.home_city),
                       ("country", f.home_country), ("hobbies", f.hobbies),
                       ("occupation", f.occupation), ("fetishes", f.fetishes)):
        if nonempty(val):
            facts.append(f"{label}: {str(val).strip()[:80]}")
    if profile is not None:
        if nonempty(profile.short_bio):
            facts.append(f"about him: {str(profile.short_bio).strip()[:400]}")
        if nonempty(profile.bullet_points):
            bp = str(profile.bullet_points).strip().replace("\n", "; ")[:600]
            facts.append(f"notes on him: {bp}")
    facts_block = ("\n".join(f"- {x}" for x in facts)
                   if facts else "- (nothing on file yet)")
    personal_lines: list[str] = []
    if profile is not None and (nonempty(profile.short_bio) or nonempty(profile.bullet_points)):
        personal_lines.append(
            "Work in ONE specific, natural detail from what you know about him above "
            "(his job, a hobby, something going on in his life) — like you actually "
            "remember him. Don't recite a list; drop one nugget the way a girlfriend would.")
    personal_block = ("\n" + "\n".join(personal_lines)) if personal_lines else ""

    history = c.messages[-history_tail:]
    convo = "\n".join(
        f"{'FAN' if d == 'in' else 'YOU'}: {b}" for d, b in history if b
    )

    fan_run: list[str] = []
    for d, b in reversed(history):
        if d == "in" and b:
            fan_run.append(b)
        elif fan_run:
            break
    fan_last_text = " ".join(reversed(fan_run))
    fan_just_asked = "?" in fan_last_text
    fan_low_effort = len(fan_last_text.split()) <= 3 and not fan_just_asked
    ask_streak, last_breather = _recent_ask_pattern(history)
    breather_p = 0.55 if len(presented) <= 2 else 0.33

    ask = bool(question_lines)
    if ask:
        if ask_streak >= 3:
            ask = False
        elif fan_just_asked:
            ask = False
        elif last_breather:
            ask = True
        elif fan_low_effort:
            ask = random.random() >= 0.6
        else:
            ask = random.random() >= breather_p
    if not ask:
        presented = []

    if opener is not None:
        need_block = _openers.need_block(opener)
    elif not question_lines:
        need_block = "You know enough — just chat and flirt naturally."
    elif ask:
        need_block = (
            "YOUR GOAL THIS MESSAGE: find out ONE of these about him — whichever "
            "flows naturally from what he just said. DON'T re-ask a dodge "
            "back-to-back; poke it again later:\n" + question_lines
        )
    elif fan_just_asked:
        need_block = (
            "THIS MESSAGE: he just asked you something — answer it warmly in your "
            "own words, DON'T fire a question back this time."
        )
    else:
        need_block = random.choice(_BREATHER_VARIANTS)

    name_dodged = (not nonempty(f.real_name) and "name:2" in asked)
    dodge_note = (
        "\n\nIMPORTANT: he dodged his name twice — NEVER ask it again; use a "
        "playful nickname instead."
        if name_dodged else "")

    style_extra = ((STYLE_3LINE,) * 2 + (STYLE_BRIEF,) * 2) if style_on else ()
    style = random.choice(_STYLE_VARIANTS + style_extra)
    if sticker_mode == "solo":
        style = ("if a CAT STICKER below fits his last message, reply with ONLY "
                 "the STICKER line, no text. text only if truly none fits. "
                 "Never write this instruction out as the message.")
    humanizer = f"\n\n{v.humanizer}" if style_on else v.emoji_vocab
    nonnative = f"\n\n{NONNATIVE_REGISTER}" if nonnative_on else ""
    _sticker_block = cat_stickers.prompt_block(sticker_mode, v.voice)
    stickers = f"\n\n{_sticker_block}" if _sticker_block else ""

    offer_clause = "don't offer pics or videos yet; "
    nudes_rule = (
        "- if he pushes nudes/pics early: don't go along and don't offer anything "
        "— tease, slow it down, steer back to getting to know him. warm, never "
        "preachy.\n")
    day_sys = day.system_block(v.voice)
    system = (
        f"{persona}\n"
        "You're texting a fan — flirting, getting to know him, quietly making "
        "him feel like the only one. 100% human, never a bot or an assistant. "
        + ("Use only what you've learned about him; don't share your own info "
           "unless he asks; " if not day_sys else
           "Use what you've learned about him and give a little back — one short "
           "beat of your day, never a paragraph; ")
        + f"{offer_clause}he may "
        "send several texts — read all, reply to the latest.\n\n"
        f"{v.painful_texting + chr(10) + chr(10) if painful_on else ''}"
        f"{clock_block(clock)}{day_sys}"
        f"{need_block}{dodge_note}\n\n"
        f"STYLE FOR THIS MESSAGE — {style}\n\n"
        f"HOW YOU TEXT (a real {persona_register_age(persona)}yo {v.texter_noun}, "
        "not an assistant):\n"
        "- short and casual: lowercase, u/ur/ya. react to what he said first.\n"
        "- VARY it — never reuse an opener, phrase, or emoji from this chat.\n"
        "- at most ONE question, never one he already answered (vague answer → "
        "quick follow-up). no paragraphs.\n"
        f"{NO_NARRATION_RULE}"
        f"{nudes_rule}"
        f"{_good_examples(f, asked, have_durable_name)}\n"
        f"{ONPLATFORM_GUARDRAIL}\n\n"
        f"{v.live_proof}\n\n"
        f"{BIO_CONSISTENCY_GUARDRAIL}"
        f"{humanizer}{nonnative}{stickers}\n\n"
        "Your reply is ONLY the message text — no JSON, quotes, or metadata."
        + (" The final STICKER: <tag> line is ALSO allowed (stripped before "
           "sending — he only sees the gif)." if _sticker_block else "")
        + _language.output_language_directive(lang)
    )
    claims_block = fan_claims_block(f)
    day_user = day.user_block(
        f, (c.last_body or "") if c.last_dir == "in" else "")
    user = (
        f"What you know about him:\n{facts_block}{personal_block}\n\n"
        f"{claims_block}"
        f"{day_user}"
        f"Recent conversation (oldest→newest):\n{convo}\n\n"
        "Reply to his last message now, in the STYLE FOR THIS MESSAGE above."
    )
    return ([{"role": "system", "content": system},
             {"role": "user", "content": user}], presented)



async def _add_to_skip_list(account_id: str, fan_id: int, reason: str) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(SkipList)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    reason=reason, added_at=datetime.utcnow())
            .on_conflict_do_nothing(index_elements=["account_id", "fan_id"])
        )


async def _skip_and_collect(account_id: str, fan_id: int, reason: str) -> None:
    await _add_to_skip_list(account_id, fan_id, reason)
    await ax.enqueue_job(account_id, "gen_info", payload={"force_ids": [int(fan_id)]})


_EXTRACT_FIELDS = ("real_name", "his_age", "home_country", "home_city",
                   "hobbies", "occupation", "fetishes")
_EXTRACT_SYSTEM = (
    "You are a profile analyzer. From the chat, extract ONLY facts the fan ACTUALLY "
    "stated. Return ONLY a JSON object with these exact fields. Keep the CURRENT value "
    "if there is no new info; use \"\" if it was never stated — NEVER guess (don't "
    "guess a city from a country, don't invent a job/hobby):\n"
    '{"real_name":"","his_age":"","home_country":"","home_city":"","hobbies":"",'
    '"occupation":"","fetishes":"","likes_boobs":false,"likes_ass":false,'
    '"recent_events":[],"her_claims":[]}\n'
    "\nAlso: \"her_claims\" — things the CREATOR (the YOU: lines) said about "
    "HERSELF in this chat. This is a DEVIATIONS-ONLY list. You are given HER "
    "PROFILE; record a claim ONLY when it is absent from that profile, or when it "
    "CONTRADICTS it. If everything she said already matches her profile, return an "
    "empty list — that is the normal, expected answer. Each entry is "
    '{"topic":"<one or two words, e.g. hometown, living situation, her ex>",'
    '"claim":"<what she told him, in her words, one short line>"}. Never invent a '
    "claim she did not make, and never copy something the FAN said."
)


def _extract_messages(f: Fan, c: _Candidate,
                      history_tail: int = _EXTRACT_HISTORY_TAIL,
                      persona: str = "") -> list[dict]:
    current = {k: (getattr(f, k) or "") for k in _EXTRACT_FIELDS}
    current["likes_boobs"] = bool(f.likes_boobs)
    current["likes_ass"] = bool(f.likes_ass)
    history = c.messages[-history_tail:]
    convo = "\n".join(f"{'FAN' if d == 'in' else 'YOU'}: {b}" for d, b in history if b)
    user = (f"HER PROFILE (what is already true of her everywhere):\n{persona}\n\n"
            f"CURRENT (ground truth — keep unless he says something new):\n"
            f"{json.dumps(current)}\n\n"
            f"Chat (oldest→newest):\n{convo}\n\n"
            "Update the JSON with anything new he stated, and list any claim she "
            "made about herself that her profile does not already cover.")
    return [{"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user}]


def _extract_worthwhile(f: Fan, c: _Candidate) -> bool:
    for col in _EXTRACT_FIELDS:
        if not nonempty(getattr(f, col, None)):
            return True
    if not nonempty(getattr(f, "recent_events", None)):
        return True
    return any(mentions_self_claim(b)
               for d, b in c.messages[-_EXTRACT_HISTORY_TAIL:] if d == "out")


def _claim_updates(f: Fan, claims) -> dict:
    if not isinstance(claims, list) or not claims:
        return {}
    merged = merge_persona_claims(
        f.persona_claims_json, claims,
        now_iso=datetime.utcnow().isoformat(timespec="seconds"))
    updates: dict = {}
    if merged != parse_persona_claims(f.persona_claims_json):
        updates["persona_claims_json"] = json.dumps(merged, ensure_ascii=False)
    updates.update(claims_to_scalars(merged))
    return updates


async def _extract_and_fill(account_id: str, fan_id: int, f: Fan,
                            c: _Candidate, model: str,
                            history_tail: int = _EXTRACT_HISTORY_TAIL,
                            purpose: str = _PURPOSE,
                            persona: str = "") -> Fan:
    if not _extract_worthwhile(f, c):
        return f
    res = await freed_chat(
        budget_s=INLINE_MAX_S,
        model=model, messages=_extract_messages(f, c, history_tail, persona),
        purpose=purpose,
        account_id=account_id, fan_id=fan_id, temperature=0.2,
        response_format={"type": "json_object"},
    )
    data = getattr(res, "parsed", None)
    if data is None:
        try:
            data = json.loads((res.content or "").strip())
        except Exception:
            return f
    if not isinstance(data, dict):
        return f

    updates: dict = {}
    for col in _EXTRACT_FIELDS:
        v = data.get(col)
        if isinstance(v, str) and v.strip() and not nonempty(getattr(f, col, None)):
            updates[col] = v.strip()[:200]
    for col in ("likes_boobs", "likes_ass"):
        if data.get(col) is True and not bool(getattr(f, col, False)):
            updates[col] = True
    ev = data.get("recent_events")
    if isinstance(ev, list) and ev and not nonempty(f.recent_events):
        updates["recent_events"] = json.dumps([str(x)[:120] for x in ev][:6])

    updates.update(_claim_updates(f, data.get("her_claims")))

    if not updates:
        return f

    now = datetime.utcnow()
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    grok_facts_updated_at=now, updated_at=now, **updates)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={**updates, "grok_facts_updated_at": now, "updated_at": now},
            )
        )
    for k, v in updates.items():
        setattr(f, k, v)
    return f


async def _graduate(client, account_id: str, fan_id: int, f: Fan) -> None:
    await _skip_and_collect(account_id, fan_id, "info")
    try:
        await push_nick_and_notes(
            client, account_id, fan_id,
            nick=build_structured_nickname(f),
            # 200 pinned: this PUTs the note to OnlyFans, so it must never inherit a widened default.
            notes=build_facts_note(facts_from_fan(f), max_len=200),
        )
    except Exception:
        log.debug("welcome_chatter_for_info graduation push failed account=%s fan=%s",
                  account_id, fan_id, exc_info=True)


_CLOSING_PPV_DEFAULT_TEXT = (
    "loved getting to know u 🙈 made u a lil something, open it when ur alone 😘")
_CLOSING_PPV_DEFAULT_PRICE_CENTS = 1000
_FAN_MESSAGES_MIN, _FAN_MESSAGES_MAX = 3, 100
_RULE_SETTING_KEYS = ("max_fan_messages", "closing_ppv_text",
                      "closing_ppv_media_ids", "closing_ppv_price_cents")


class _ClosingPPV:
    __slots__ = ("text", "media_ids", "price_cents")

    def __init__(self, text: str, media_ids: list[int], price_cents: int):
        self.text, self.media_ids, self.price_cents = text, media_ids, price_cents


def _closing_ppv_of(payload: dict) -> _ClosingPPV | None:
    price = payload.get("closing_ppv_price_cents")
    media, price = extras.media_and_price({
        "media_ids": payload.get("closing_ppv_media_ids"),
        "price_cents": price if price is not None else _CLOSING_PPV_DEFAULT_PRICE_CENTS,
    })
    if not media:
        return None
    text = str(payload.get("closing_ppv_text") or "").strip() or _CLOSING_PPV_DEFAULT_TEXT
    return _ClosingPPV(text, media, price or _CLOSING_PPV_DEFAULT_PRICE_CENTS)


def _cutoff_of(payload: dict) -> int:
    n = payload.get("max_fan_messages")
    if isinstance(n, bool) or not isinstance(n, int):
        return _MAX_FAN_MESSAGES
    return max(_FAN_MESSAGES_MIN, min(n, _FAN_MESSAGES_MAX))


async def _load_rule_settings(account_id: str, payload: dict) -> dict:
    own = {k: payload[k] for k in _RULE_SETTING_KEYS if k in payload}
    if len(own) == len(_RULE_SETTING_KEYS):
        return own
    try:
        rid = await ax.enabled_rule_id(account_id, _PURPOSE)
        if rid is None:
            return own
        async with get_session() as s:
            rule = await s.get(AutomationRule, rid)
        steps = json.loads((rule.steps_json if rule else None) or "{}")
    except Exception:
        log.warning("welcome_chatter_for_info rule settings read failed account=%s",
                    account_id, exc_info=True)
        return own
    if not isinstance(steps, dict):
        return own
    return {**{k: steps[k] for k in _RULE_SETTING_KEYS if k in steps}, **own}


async def _send_closing_ppv(client, account_id: str, fan_id: int,
                            ppv: _ClosingPPV, *, dry_run: bool) -> str:
    """Send the closing PPV to one fan. The caller holds the fan lease. Returns
    "sent", "dry_run" (would send), "already" (he had it — once per fan, stamped
    on `fans.gather_close_at`), "owned" (he owns some of the media) or "failed".
    Never raises: a failure must not block the graduation that follows."""
    try:
        async with get_session() as s:
            stamped = (await s.execute(
                select(Fan.gather_close_at).where(
                    Fan.account_id == str(account_id), Fan.fan_id == int(fan_id))
            )).scalar_one_or_none()
        # Once per fan: gather_close_at is stamped right after the send is on the wire, so a second closing PPV can never go out.
        if stamped is not None:
            return "already"
        # Never to a fan who already owns any of the media.
        if int(fan_id) in await extras.owners(account_id, ppv.media_ids,
                                              ppv.price_cents, [fan_id]):
            log.info("welcome_chatter_for_info closing PPV skipped (owns media) "
                     "account=%s fan=%s", account_id, fan_id)
            return "owned"
        if dry_run:
            return "dry_run"
        await dm_rate.turn(account_id)
        result = await asyncio.to_thread(
            lambda: client.send_message(fan_id, ppv.text,
                                        media_files=list(ppv.media_ids),
                                        price=ppv.price_cents / 100))
        msg_id = result.get("id") if isinstance(result, dict) else None
        if not msg_id:
            log.warning("welcome_chatter_for_info closing PPV returned no id "
                        "account=%s fan=%s", account_id, fan_id)
            return "failed"
        # Stamp first: the send is on the wire, and a second closing PPV to the same fan must never happen.
        now = datetime.utcnow()
        async with get_session() as s:
            await s.execute(
                sqlite_insert(Fan)
                .values(account_id=str(account_id), fan_id=int(fan_id),
                        gather_close_at=now, updated_at=now)
                .on_conflict_do_update(
                    index_elements=["account_id", "fan_id"],
                    set_={"gather_close_at": now, "updated_at": now},
                )
            )
        await write_outbound_attribution(
            account_id=account_id,
            fan_id=int(fan_id),
            message_id=int(msg_id),
            sent_by_employee_id=None,
            automation_kind=_PURPOSE,
            body=str(result.get("text") or ppv.text),
            price_cents=ppv.price_cents,
            created_at=ax._parse_iso(result.get("createdAt")) or now,
            emit_live=True,
        )
        log.info("welcome_chatter_for_info closing PPV sent account=%s fan=%s "
                 "media=%d price_cents=%d", account_id, fan_id,
                 len(ppv.media_ids), ppv.price_cents)
        return "sent"
    except Exception:
        log.warning("welcome_chatter_for_info closing PPV failed account=%s fan=%s",
                    account_id, fan_id, exc_info=True)
        return "failed"


async def _maybe_push_nickname(client, account_id: str, fan_id: int, f: Fan) -> None:
    nick = build_structured_nickname(f)
    if nick and nick != (f.custom_nickname or ""):
        await push_nick_and_notes(client, account_id, fan_id, nick=nick)
        f.custom_nickname = nick


async def _mark_question_asked(account_id: str, fan_id: int, key: str,
                               asked: set[str]) -> None:
    mark = key if key not in asked else f"{key}:2"
    new_set = sorted(asked | {mark})
    now = datetime.utcnow()
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    questions_asked=json.dumps(new_set), updated_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"questions_asked": json.dumps(new_set), "updated_at": now},
            )
        )


async def _bump_attempt(account_id: str, fan_id: int, now: datetime) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    turn_counter=1, updated_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"turn_counter": Fan.turn_counter + 1, "updated_at": now},
            )
        )


async def _load_profiles(account_id: str, fan_ids) -> dict[int, FanProfile]:
    ids = [int(x) for x in fan_ids]
    if not ids:
        return {}
    async with get_session() as s:
        rows = (await s.execute(
            select(FanProfile).where(FanProfile.account_id == str(account_id),
                                     FanProfile.fan_id.in_(ids))
        )).scalars().all()
        s.expunge_all()
    return {int(r.fan_id): r for r in rows}


async def _mark_reply_sent(account_id: str, fan_id: int, now: datetime) -> None:
    async with get_session() as s:
        await s.execute(
            update(Fan)
            .where(Fan.account_id == str(account_id), Fan.fan_id == int(fan_id))
            .values(last_message_sent_at=now, updated_at=now)
        )


async def _maybe_refresh_profile(account_id: str, fan_id: int, fan_msg_n: int,
                                 now: datetime) -> bool:
    try:
        async with get_session() as s:
            prof = (await s.execute(
                select(FanProfile.message_count_at_gen, FanProfile.last_generated_at)
                .where(FanProfile.account_id == str(account_id),
                       FanProfile.fan_id == int(fan_id))
            )).first()
            fresh_after, volume_cap = await gen_info.fan_cadence_knobs(
                s, account_id, fan_id, now)
        prev_count = int(prof.message_count_at_gen) if prof is not None else None
        last_gen_at = prof.last_generated_at if prof is not None else None
        if not gen_info.profile_is_stale(prev_count, last_gen_at, fan_msg_n, now,
                                         fresh_after=fresh_after, volume_cap=volume_cap):
            return False
        async with get_session() as s:
            pending = (await s.execute(
                select(ScheduledJob.id)
                .where(ScheduledJob.account_id == str(account_id),
                       ScheduledJob.kind == "gen_info",
                       ScheduledJob.status.in_(("pending", "running")),
                       ScheduledJob.payload_json.like(f"%[{int(fan_id)}]%"))
                .limit(1)
            )).first()
        # Don't stack a second regen when one is already queued for this fan.
        if pending is not None:
            return False
        await ax.enqueue_job(account_id, "gen_info",
                             payload={"refill_ids": [int(fan_id)]})
        return True
    except Exception:
        log.debug("welcome_chatter_for_info profile-refresh enqueue skipped account=%s fan=%s",
                  account_id, fan_id, exc_info=True)
        return False


async def _pause_fan(account_id: str, fan_id: int, until: datetime) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    automation_paused_until=until)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"automation_paused_until": until, "updated_at": datetime.utcnow()},
            )
        )


def _snapshot_of(c: _Candidate, f: Fan | None, *, now: datetime, handoff: bool,
                 listed: bool, mid_funnel: bool, forced: bool, promo_spam: bool,
                 content_payer: bool, max_fan_messages: int,
                 closing_set: bool) -> wcfi_decide.FanSnapshot:
    paused = muted = gather_done = closing_due = False
    if f is not None:
        asked = wcfi_decide.asked_topics(f)
        paused = bool(f.automation_paused_until and f.automation_paused_until > now)
        muted = should_skip_muted_creator(f)
        gather_done = _gather_done(f, asked)
        closing_due = closing_set and f.gather_close_at is None
    return wcfi_decide.FanSnapshot(
        listed=listed, mid_funnel=mid_funnel, forced=forced, his_turn=c.last_dir == "in",
        handoff=handoff, has_fan_row=f is not None, paused=paused, muted_creator=muted,
        promo_spam=promo_spam, content_payer=content_payer, gather_done=gather_done,
        fan_msg_n=c.fan_msg_n, max_fan_messages=max_fan_messages, closing_due=closing_due)



@dataclass(frozen=True)
class _PayloadKnobs:
    dry_run: bool
    limit: int
    max_replies: int
    history_tail: int
    force_ids: set[int]
    only_fan_ids: set[int]
    turn_handoff_ids: set[int]

    @classmethod
    def of(cls, payload: dict) -> _PayloadKnobs:
        dry_run = bool(payload.get("dry_run"))
        limit = int(payload.get("limit") or _DEFAULT_LIMIT)
        max_replies = int(payload.get("max_replies") or _DEFAULT_MAX_REPLIES)
        history_tail = int(payload.get("history_tail") or _HISTORY_TAIL)
        force_ids = coerce_ids(payload.get("force_ids"))
        only_fan_ids = coerce_ids(payload.get("only_fan_ids"))
        turn_handoff_ids = coerce_ids(payload.get("turn_handoff_ids"))
        return cls(dry_run=dry_run, limit=limit, max_replies=max_replies,
                   history_tail=history_tail, force_ids=force_ids, only_fan_ids=only_fan_ids,
                   turn_handoff_ids=turn_handoff_ids)


@dataclass(frozen=True)
class _RunConfig(_PayloadKnobs):
    account_id: str
    model: str
    llm_capped: bool
    typing_wpm: float
    typing_indicator: bool
    style_on: bool
    consistency_on: bool
    typo_on: bool
    nonnative_on: bool
    spacing_on: bool
    factground_on: bool
    painful_on: bool
    sticker_cfg: cat_stickers.StickerConfig
    account_lang: str
    voice_blocks: _voice.VoiceBlocks
    strip_emoji_on: bool
    max_bubbles: int
    persona: str
    clock_tz: int | None
    day: _daylog.Day
    banned_words: list[str]
    banned_mode: str
    blacklist: set[int]
    skip_list: set[int]
    max_fan_messages: int
    closing: _ClosingPPV | None
    mid_funnel_fans: set[int]
    promo_spam: set[int]


async def _load_run_config(account_id: str, payload: dict, knobs: _PayloadKnobs, *,
                           model: str, llm_capped: bool) -> _RunConfig:
    typing_wpm = await load_typing_wpm(account_id)
    typing_indicator = await load_typing_indicator(account_id)
    style_on = (await load_style_flags(account_id))[_PURPOSE]
    consistency_on = (await load_consistency_flags(account_id))[_PURPOSE]
    typo_on = (await load_typo_flags(account_id))[_PURPOSE]
    nonnative_on = (await load_nonnative_flags(account_id))[_PURPOSE]
    spacing_on = (await load_spacing_flags(account_id))[_PURPOSE]
    factground_on = await load_factground_flag(account_id)
    painful_on = await load_painful_texting_flag(account_id)
    sticker_cfg = await cat_stickers.load_cat_sticker_config(account_id)
    account_lang = await _language.load_account_language(account_id)
    voice_blocks = await load_voice_blocks(account_id)
    strip_emoji_on = await load_strip_emojis(account_id)
    max_bubbles = STYLE_MAX_BUBBLES if style_on else 2
    persona = await _load_persona(account_id)
    clock_tz = await load_clock_tz(account_id)
    day = _daylog.NO_DAY if llm_capped else await _daylog.load_day(
        account_id, model=model, purpose=_PURPOSE, clock_tz=clock_tz)
    banned_words, banned_mode = await load_banned_words(account_id)
    blacklist, skip_list = await _load_stop_lists(account_id)
    rule_settings = await _load_rule_settings(account_id, payload)
    max_fan_messages = _cutoff_of(rule_settings)
    closing = _closing_ppv_of(rule_settings)
    mid_funnel_fans = await _load_mid_funnel_fans(account_id)
    promo_spam = await load_promo_spam_ids(account_id)
    return _RunConfig(
        **vars(knobs), account_id=account_id, model=model, llm_capped=llm_capped,
        typing_wpm=typing_wpm, typing_indicator=typing_indicator, style_on=style_on,
        consistency_on=consistency_on, typo_on=typo_on, nonnative_on=nonnative_on,
        spacing_on=spacing_on, factground_on=factground_on, painful_on=painful_on,
        sticker_cfg=sticker_cfg, account_lang=account_lang, voice_blocks=voice_blocks,
        strip_emoji_on=strip_emoji_on, max_bubbles=max_bubbles, persona=persona,
        clock_tz=clock_tz, day=day, banned_words=banned_words, banned_mode=banned_mode,
        blacklist=blacklist, skip_list=skip_list, max_fan_messages=max_fan_messages,
        closing=closing, mid_funnel_fans=mid_funnel_fans, promo_spam=promo_spam)


TurnKind = Literal["sent", "dry_run", "cooldown", "locked", "closing_cut", "closing_preview",
                   "graduated", "generate_failed", "empty", "echo", "banned", "send_failed",
                   "no_id", "sticker_failed"]


@dataclass
class TurnOutcome:
    kind: TurnKind = "sent"
    replies_sent: int = 0
    stickers_sent: int = 0
    closing_ppvs_sent: int = 0
    newly_skiplisted: int = 0
    skipped_locked: int = 0
    skipped_cooldown: int = 0
    skipped_banned: int = 0
    errors: int = 0


def _fold(tally: Counter, skips: Counter, out: TurnOutcome) -> None:
    tally["replies_sent"] += out.replies_sent
    tally["stickers_sent"] += out.stickers_sent
    tally["closing_ppvs_sent"] += out.closing_ppvs_sent
    tally["skipped_locked"] += out.skipped_locked
    tally["skipped_cooldown"] += out.skipped_cooldown
    tally["skipped_banned"] += out.skipped_banned
    tally["errors"] += out.errors
    skips["newly_skiplisted"] += out.newly_skiplisted


async def _record_send(account_id: str, fan_id: int, msg_id: int | str, result: dict,
                       body: str) -> None:
    await write_outbound_attribution(
        account_id=account_id,
        fan_id=int(fan_id),
        message_id=int(msg_id),
        sent_by_employee_id=None,
        automation_kind=_PURPOSE,
        body=str(result.get("text") or body),
        price_cents=0,
        created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
        emit_live=True,
    )


@dataclass
class _Turn:
    cfg: _RunConfig
    c: _Candidate
    client: Any
    profile: FanProfile | None
    now: datetime
    out: TurnOutcome
    f: Fan
    sent_ok: bool = False


async def _close_with_ppv(t: _Turn) -> bool:
    if t.cfg.closing is None:
        return False
    outcome = await _send_closing_ppv(t.client, t.cfg.account_id, t.c.fan_id, t.cfg.closing,
                                      dry_run=t.cfg.dry_run)
    if outcome == "dry_run":
        t.out.closing_ppvs_sent += 1
        t.out.replies_sent += 1
        return True
    if outcome == "sent":
        t.out.closing_ppvs_sent += 1
        t.out.replies_sent += 1
        t.sent_ok = True
        await _mark_reply_sent(t.cfg.account_id, t.c.fan_id, t.now)
    return False


async def _turn_fill_facts(t: _Turn) -> None:
    account_id, fan_id = t.cfg.account_id, t.c.fan_id
    try:
        t.f = await _extract_and_fill(account_id, fan_id, t.f, t.c, t.cfg.model,
                                      _EXTRACT_HISTORY_TAIL, persona=t.cfg.persona)
    except LLMCapExceeded:
        log.warning("welcome_chatter_for_info LLM cap reached (extract) account=%s — stopping",
                    account_id)
        raise
    except llm_client.LLMKeyError:
        raise
    except run_slot.SlotLost:
        raise
    except Exception:
        log.debug("welcome_chatter_for_info fact-extract failed account=%s fan=%s",
                  account_id, fan_id, exc_info=True)
    try:
        await _maybe_push_nickname(t.client, account_id, fan_id, t.f)
    except Exception:
        log.debug("welcome_chatter_for_info nick push failed account=%s fan=%s",
                  account_id, fan_id, exc_info=True)


async def _turn_finish_lane(t: _Turn) -> None:
    if await _close_with_ppv(t):
        t.out.kind = "closing_preview"
        return  # dry-run preview: he stays in the lane
    await _graduate(t.client, t.cfg.account_id, t.c.fan_id, t.f)
    t.out.kind = "graduated"
    t.out.newly_skiplisted += 1


def _turn_sticker_roll(t: _Turn) -> str:
    sticker_cfg = t.cfg.sticker_cfg
    if not sticker_cfg.enabled:
        return "skip"
    account_id, fan_id = t.cfg.account_id, t.c.fan_id
    return cat_stickers.roll_mode(
        random.Random(f"sticker:{account_id}:{fan_id}:{t.c.last_body}"),
        cat_stickers.cooldown_active(account_id, fan_id, gap_min=sticker_cfg.gap_min),
        skip_w=sticker_cfg.skip_w, solo_w=sticker_cfg.solo_w)


async def _turn_generate(t: _Turn, asked: set, opener, fan_lang: str,
                         sticker_mode: str) -> tuple[str, list[str]] | None:
    cfg, c = t.cfg, t.c
    msgs, presented = _build_messages(
        cfg.persona, t.f, c, asked, cfg.history_tail,
        style_on=cfg.style_on, nonnative_on=cfg.nonnative_on,
        painful_on=cfg.painful_on, lang=fan_lang,
        profile=t.profile if cfg.factground_on else None,
        clock=clock_line(cfg.clock_tz),
        sticker_mode=sticker_mode,
        day=cfg.day,
        opener=opener, v=cfg.voice_blocks)
    try:
        res = await freed_chat(
            budget_s=INLINE_MAX_S,
            model=cfg.model,
            messages=msgs,
            purpose=_PURPOSE,
            account_id=cfg.account_id,
            fan_id=c.fan_id,
            temperature=_REPLY_TEMPERATURE,
        )
    except run_slot.SlotLost:
        raise
    except LLMCapExceeded:
        log.warning("welcome_chatter_for_info daily LLM cap reached account=%s — stopping",
                    cfg.account_id)
        raise
    except llm_client.LLMKeyError:
        raise
    except Exception:
        log.warning("welcome_chatter_for_info generate failed account=%s fan=%s",
                    cfg.account_id, c.fan_id, exc_info=True)
        t.out.kind, t.out.errors = "generate_failed", 1
        return None
    return (res.content or "").strip(), presented


async def _turn_tag_and_finalize(t: _Turn, raw: str, sticker_mode: str):
    cfg, account_id, fan_id = t.cfg, t.cfg.account_id, t.c.fan_id
    raw, sticker_tag = cat_stickers.parse_marker(raw)
    if sticker_mode == "skip":
        sticker_tag = None
    if sticker_tag is not None:
        sticker_tag = cat_stickers.keep_tag(
            account_id, fan_id, sticker_tag, has_text=bool(raw))
        if sticker_tag is None:
            log.info("welcome_chatter_for_info sticker tag repeat dropped account=%s "
                     "fan=%s", account_id, fan_id)
    strip_emoji_on = cfg.strip_emoji_on
    raw, _leak = await finalize_draft(
        raw, account_id=account_id, fan_id=fan_id, purpose=_PURPOSE,
        consistency=ConsistencyCtx(
            fan=t.f, persona=cfg.persona, model=cfg.model,
            last_inbound=t.c.last_body or "") if cfg.consistency_on else None,
        strip_emoji=strip_emoji_on, v=cfg.voice_blocks)
    return raw, sticker_tag


async def _turn_shape(t: _Turn, raw: str, fan_lang: str, sticker_tag) -> list[str] | None:
    cfg, c, f = t.cfg, t.c, t.f
    account_id, fan_id = cfg.account_id, c.fan_id
    name_protect = [n for n in (f.real_name, f.generated_nickname,
                                f.of_display_name) if n]
    shaped = _reply_shape.shape_parts(raw, _reply_shape.ShapeCtx(
        seed_id=fan_id, max_bubbles=cfg.max_bubbles, max_chars=_REPLY_MAX_CHARS,
        lang=fan_lang, echo_of=c.last_body, style_on=cfg.style_on,
        recent_out=[b for d, b in c.messages if d == "out"],
        allow_empty=sticker_tag is not None,
        banned_words=cfg.banned_words, banned_mode=cfg.banned_mode,
        nonnative_on=cfg.nonnative_on, spacing_on=cfg.spacing_on,
        name_protect=name_protect))
    if shaped.dropped_reason == "banned":
        log.warning("of_ai_chat BLOCKED reply — banned word(s) %r account=%s fan=%s",
                    banned_hit_summary(shaped.banned_hits), account_id, fan_id)
        t.out.kind, t.out.skipped_banned = "banned", 1
        return None
    if shaped.dropped_reason is not None:
        log.debug("welcome_chatter_for_info dropped echo-only reply account=%s fan=%s",
                  account_id, fan_id)
        t.out.kind, t.out.errors = shaped.dropped_reason, 1
        return None
    if shaped.banned_hits:
        log.info("of_ai_chat masked banned word(s) %r account=%s fan=%s",
                 banned_hit_summary(shaped.banned_hits), account_id, fan_id)
    parts = shaped.parts
    if cfg.typo_on:
        protect = name_protect + (list(NONNATIVE_OUTPUTS) if cfg.nonnative_on else [])
        parts = await apply_typo_throttle(
            account_id, fan_id, parts, random.Random(f"{fan_id}:{raw}"),
            protect=protect, max_bubbles=cfg.max_bubbles)
    return parts


async def _turn_send_bubbles(t: _Turn, parts: list[str]) -> bool:
    cfg, out = t.cfg, t.out
    account_id, fan_id = cfg.account_id, t.c.fan_id
    for idx, part in enumerate(parts):
        await hold_with_typing(account_id, fan_id,
                               typing_delay_seconds(part, cfg.typing_wpm),
                               typing_indicator=cfg.typing_indicator)
        await dm_rate.turn(account_id, release_budget_s=INLINE_MAX_S)
        try:
            result = await asyncio.to_thread(t.client.send_message, fan_id, part)
        except Exception as e:
            out.errors += 1
            await skip_unreachable_fan(account_id, fan_id, e, log=log)
            log.warning("welcome_chatter_for_info send failed account=%s fan=%s",
                        account_id, fan_id, exc_info=True)
            out.kind = "send_failed"
            return True
        msg_id = wcfi_decide.msg_id_of(result)
        if msg_id:
            await _record_send(account_id, fan_id, msg_id, result, part)
            t.sent_ok = True
        elif idx == 0:
            # 200 without a message id can't be persisted (PK), so "fan spoke last" would re-fire every tick.
            out.kind = "no_id"
            out.errors += 1
            reason = await quarantine_if_undeliverable(t.client, account_id, fan_id)
            if reason is None:
                await _pause_fan(account_id, fan_id, t.now + _NOID_PAUSE)
                log.warning("welcome_chatter_for_info send returned no id account=%s fan=%s — paused %s",
                            account_id, fan_id, _NOID_PAUSE)
            return True
    return False


async def _turn_send_sticker(t: _Turn, sticker_tag, parts: list[str]) -> bool:
    if sticker_tag is None:
        return False
    account_id, fan_id = t.cfg.account_id, t.c.fan_id
    gid = cat_stickers.pick_gif(
        sticker_tag,
        random.Random(f"gif:{account_id}:{fan_id}:{t.c.last_body}"),
        account_id=account_id, fan_id=fan_id,
        voice=t.cfg.voice_blocks.voice)
    if gid is None:
        return False
    srng = random.Random(f"sdelay:{fan_id}:{gid}")
    await hold_with_typing(account_id, fan_id,
                           2.0 + 4.0 * srng.random(),
                           typing_indicator=t.cfg.typing_indicator)
    await dm_rate.turn(account_id, release_budget_s=INLINE_MAX_S)
    try:
        result = await asyncio.to_thread(
            lambda g=gid: t.client.send_message(fan_id, "",
                                                giphy_id=g))
    except Exception:
        result = None
        log.warning("welcome_chatter_for_info sticker send failed account=%s "
                    "fan=%s tag=%s", account_id, fan_id,
                    sticker_tag, exc_info=True)
    s_msg_id = wcfi_decide.msg_id_of(result)
    if not s_msg_id:
        return False
    await _record_send(account_id, fan_id, s_msg_id, result, "")
    cat_stickers.mark_sent(account_id, fan_id,
                           tag=sticker_tag, gif_id=gid)
    t.sent_ok = True
    t.out.stickers_sent += 1
    log.info("welcome_chatter_for_info sticker sent account=%s fan=%s "
             "tag=%s gif=%s solo=%s", account_id, fan_id,
             sticker_tag, gid, not parts)
    return True


async def _turn_bookkeep(t: _Turn, parts: list[str], presented, asked: set,
                         opener) -> None:
    account_id, fan_id = t.cfg.account_id, t.c.fan_id
    await _mark_reply_sent(account_id, fan_id, t.now)
    target = _primary_ask_target(presented) if parts else None
    if target:
        await _mark_question_asked(account_id, fan_id, target, asked)
    if opener is not None and parts:
        await _openers.record_used(account_id, fan_id, t.f,
                                   t.profile, opener.slot)
    await _maybe_refresh_profile(account_id, fan_id, t.c.fan_msg_n, t.now)
    t.out.kind = "sent"
    t.out.replies_sent += 1


async def _turn_mark_read(t: _Turn) -> None:
    try:
        read, at = await read_flip.write(t.cfg.account_id, t.c.fan_id, lambda: t.client.mark_chat_read(t.c.fan_id),
                                         only_if_unread=True)
    except Exception:
        log.warning("welcome_chatter_for_info mark_chat_read failed account=%s fan=%s",
                    t.cfg.account_id, t.c.fan_id, exc_info=True)
        return
    await read_flip.after_write(t.cfg.account_id, t.c.fan_id, 0, read, at=at)


# On success the short cooldown replaces the lease; if the cooldown write fails keep the lease as the fallback brake.
async def _turn_release(t: _Turn) -> None:
    account_id, fan_id = t.cfg.account_id, t.c.fan_id
    if t.sent_ok:
        try:
            await ax.start_fan_cooldown(
                account_id, fan_id, cooldown_s=_REPLY_COOLDOWN_S
            )
            await ax.release_fan_lease(account_id, fan_id)
        except Exception:
            log.warning("welcome_chatter_for_info cooldown set failed account=%s fan=%s "
                        "— keeping lease as fallback guard",
                        account_id, fan_id, exc_info=True)
    else:
        await ax.release_fan_lease(account_id, fan_id)


async def _turn(cfg: _RunConfig, c: _Candidate, fan_row: Fan | None,
                profile: FanProfile | None, client, now: datetime) -> TurnOutcome:
    account_id, fan_id = cfg.account_id, c.fan_id
    t = _Turn(cfg, c, client, profile, now, TurnOutcome(),
              fan_row or Fan(account_id=str(account_id), fan_id=fan_id))
    # Another automation messaged this fan recently → rest it (W3 cooldown).
    if await ax.fan_on_cooldown(account_id, fan_id):
        t.out.kind, t.out.skipped_cooldown = "cooldown", 1
        return t.out
    if not await ax.acquire_fan_lease(account_id, fan_id, "welcome_chatter_for_info"):
        t.out.kind, t.out.skipped_locked = "locked", 1
        return t.out
    try:
        if c.closing_cut:
            t.out.kind = "closing_cut"
            if not await _close_with_ppv(t):
                await _skip_and_collect(account_id, fan_id, "too_long")
                t.out.newly_skiplisted += 1
            return t.out
        await _turn_fill_facts(t)
        asked = wcfi_decide.asked_topics(t.f)
        opener = None
        if fan_id not in cfg.force_ids and _gather_done(t.f, asked):
            opener = _openers.next_for(t.f, profile)
            if opener is None:
                await _turn_finish_lane(t)
                return t.out
        fan_lang = _language.resolve_language(cfg.account_lang, getattr(t.f, "language", None))
        sticker_mode = _turn_sticker_roll(t)
        gen = await _turn_generate(t, asked, opener, fan_lang, sticker_mode)
        if gen is None:
            return t.out
        raw, presented = gen
        raw, sticker_tag = await _turn_tag_and_finalize(t, raw, sticker_mode)
        if not cfg.dry_run:
            await _bump_attempt(account_id, fan_id, now)
        parts = await _turn_shape(t, raw, fan_lang, sticker_tag)
        if parts is None:
            return t.out
        if cfg.dry_run:
            t.out.kind, t.out.replies_sent = "dry_run", 1
            return t.out
        try:
            if await _turn_send_bubbles(t, parts):
                return t.out
            sticker_sent = await _turn_send_sticker(t, sticker_tag, parts)
        except run_slot.SlotLost:
            if t.sent_ok:
                await _turn_bookkeep(t, parts, presented, asked, opener)
            raise
        if not parts and not sticker_sent:
            t.out.kind = "sticker_failed"
            t.out.errors += 1
            return t.out
        await _turn_bookkeep(t, parts, presented, asked, opener)
        await _turn_mark_read(t)
        return t.out
    finally:
        await _turn_release(t)


@register("welcome_chatter_for_info")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    knobs = _PayloadKnobs.of(payload)
    model = await resolve_model(account_id, _PURPOSE, payload.get("model"))
    provider = llm_client.MODELS[model].provider
    if not await llm_client.llm_key_available(account_id, provider, _PURPOSE):
        return {"no_llm_key": provider, "candidates": 0, "replies_sent": 0}
    llm_capped = (await llm_client.cap_state(account_id, provider, model))["capped"]
    if llm_capped and not knobs.only_fan_ids:
        log.info("welcome_chatter_for_info llm cap reached account=%s provider=%s "
                 "— skipping the sweep", account_id, provider)
        return {"llm_capped": provider, "candidates": 0, "replies_sent": 0}
    cfg = await _load_run_config(account_id, payload, knobs, model=model,
                                 llm_capped=llm_capped)
    by_fan = await _gather(account_id, cfg.only_fan_ids or None)

    import audience_include as _audiences
    audience_stats: dict = {}
    _kept = set(await _audiences.filter_candidates(
        account_id, list(by_fan), kind="welcome_chatter_for_info",
        stats=audience_stats, extra_allowed_ids=cfg.force_ids))
    by_fan = {fid: c for fid, c in by_fan.items() if fid in _kept}
    from automations import full_ai_owner_io
    _claimed, claimed_stats = await full_ai_owner_io.stand_down(
        account_id, list(by_fan), lane="welcome_chatter_for_info")
    by_fan = {fid: c for fid, c in by_fan.items() if fid not in _claimed}

    # Content buyers = a tip or PPV unlock, never the subscription: counting it graduated every new subscriber to the seller on a paid page.
    content_payers = await content_payer_fans(account_id, set(by_fan))

    client = await asyncio.to_thread(ax._make_client, account_id)

    fans: dict[int, Fan] = {}
    ids = list(by_fan)
    async with get_session() as s:
        for i in range(0, len(ids), _FAN_SELECT_CHUNK):
            for f in (await s.execute(
                select(Fan).where(Fan.account_id == str(account_id),
                                  Fan.fan_id.in_(ids[i:i + _FAN_SELECT_CHUNK]))
            )).scalars():
                fans[int(f.fan_id)] = f

    now = datetime.utcnow()
    candidates: list[_Candidate] = []
    skips: Counter[str] = Counter(dict.fromkeys(wcfi_decide.COUNTERS, 0))

    for fan_id, c in by_fan.items():
        his_words = c.turn.admit(fan_id, cfg.turn_handoff_ids)
        v = wcfi_decide.decide(_snapshot_of(
            c, fans.get(fan_id), now=now, handoff=his_words is not None,
            listed=fan_id in cfg.blacklist or fan_id in cfg.skip_list,
            mid_funnel=fan_id in cfg.mid_funnel_fans, forced=fan_id in cfg.force_ids,
            promo_spam=fan_id in cfg.promo_spam, content_payer=fan_id in content_payers,
            max_fan_messages=cfg.max_fan_messages, closing_set=cfg.closing is not None))
        if v.handoff_admitted:
            c.last_dir, c.last_body = "in", his_words
            skips["turn_handoffs"] += 1
        if isinstance(v, wcfi_decide.Skip):
            if v.durable:
                await _skip_and_collect(account_id, fan_id, v.reason)
            skips[wcfi_decide.STAT[v.reason]] += 1
            continue
        if isinstance(v, wcfi_decide.ClosePpv):
            c.closing_cut = True
        candidates.append(c)

    candidates.sort(key=lambda x: (-x.fan_msg_n, x.fan_id))
    candidates = candidates[:cfg.limit]
    if cfg.llm_capped:
        candidates = [c for c in candidates if c.closing_cut]

    profiles: dict[int, FanProfile] = await _load_profiles(
        account_id, [c.fan_id for c in candidates])

    tally: Counter[str] = Counter()
    cap_hit = cfg.llm_capped
    key_error = None
    for c in candidates:
        if tally["replies_sent"] >= cfg.max_replies:
            log.info("welcome_chatter_for_info batch capped account=%s cap=%d (rest next tick)",
                     account_id, cfg.max_replies)
            break
        try:
            out = await _turn(cfg, c, fans.get(c.fan_id), profiles.get(c.fan_id), client, now)
        except LLMCapExceeded:
            cap_hit = True
            break
        except llm_client.LLMKeyError as e:
            key_error = llm_client.key_error_payload(e)
            break
        _fold(tally, skips, out)

    return {
        "candidates": len(candidates),
        **audience_stats,
        **claimed_stats,
        "replies_sent": tally["replies_sent"],
        "stickers_sent": tally["stickers_sent"],
        "closing_ppvs_sent": tally["closing_ppvs_sent"],
        **skips,
        "skipped_locked": tally["skipped_locked"],
        "skipped_cooldown": tally["skipped_cooldown"],
        "skipped_banned": tally["skipped_banned"],
        "errors": tally["errors"],
        "cap_hit": cap_hit,
        "dry_run": cfg.dry_run,
        "model": cfg.model,
        **({"key_error": key_error} if key_error else {}),
    }
