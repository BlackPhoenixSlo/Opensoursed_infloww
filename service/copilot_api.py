"""service/copilot_api.py — Infloww's AI Copilot: reply suggestions in Messages Pro.

    POST /admin/copilot/{account_id}/{fan_id}/suggest
         body {mode, avoid?: [str]}  →  {mode, suggestions: [str, str, str]}

Infloww's flow (help.infloww.com articles 262036 and 262040, read 2026-10-19):
the chatter clicks "AI" in a fan's chat, picks Casual, Re-engage, Tip request
or Sexting, gets three suggestions for that thread, picks one, edits it and
presses Send. "Regenerate" asks again. Nothing is ever sent from here: this
route touches no OnlyFans call and no queue; the employee sends from the
Composer.

The prompt is Auto Convo's (automations/autoreply.py): the same persona, voice
blocks, fan facts, transcript, clock, guardrails and output language, with the
picked mode as the message directive. One LLM call per click returns all three
options as JSON, so a Regenerate is one more call and nothing is generated and
then thrown away. `avoid` carries the set on screen so a Regenerate differs.

Infloww bills one credit per generation. We bill the agency's own AI key and
its daily soft cap (llm_client): a missing or rejected key is the app-wide 424
(server.py's LLMKeyError handler), the cap is a 429.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

import llm_client
from auth import assert_account_owned
from automations import _language, _voice
from automations._clock import clock_block, clock_line, load_clock_tz
from automations._common import (
    BIO_CONSISTENCY_GUARDRAIL, NO_NARRATION_RULE, ONPLATFORM_GUARDRAIL,
    apply_word_restriction, load_painful_texting_flag, load_strip_emojis,
    load_voice_blocks, resolve_model,
)
from automations._outbound import finalize_draft
from automations._wordfilter import filter_banned, load_banned_words
from automations.autoreply import (
    _fan_facts, _history, _load_persona, _transcript,
)
from db.engine import get_session
from db.models import Fan
from llm_client import LLMCapExceeded, LLMHTTPError

log = logging.getLogger("of-relay.copilot")

router = APIRouter()

PURPOSE = "copilot"
N_SUGGESTIONS = 3
_HISTORY_TAIL = 16
_TEMPERATURE = 0.9
_MAX_CHARS = 600
_SHAPE = '{"suggestions": [' + ", ".join(['"..."'] * N_SUGGESTIONS) + ']}'

Mode = Literal["casual", "reengage", "tip_request", "sexting"]

# Infloww's four modes, in its order. Each is the "THIS MESSAGE" directive.
MODES: dict[str, str] = {
    "casual": (
        "CASUAL — keep the conversation going. Answer what he said, light and "
        "warm, a little flirty; an easy question back is fine. Nothing paid."),
    "reengage": (
        "RE-ENGAGE — the chat went quiet or flat. Pull him back in with a hook he "
        "wants to answer: something from your chat or what you know about him, "
        "a tease, a playful question. Never needy, never guilt him for being "
        "away. Nothing paid."),
    "tip_request": (
        "TIP REQUEST — ask him for a tip, in the flow of the chat. Give him a "
        "playful reason to spoil you and make it feel like his idea. One clear "
        "ask; name an amount only if the chat already did. Never beg or "
        "pressure, never promise content or a pic for it."),
    "sexting": (
        "SEXTING — turn up the heat. React to what he said and build tension: "
        "what you're feeling, wanting, doing to yourself right now, said in "
        "first person as a text. Suggestive to explicit, matching how far the "
        "chat already went. No pics or PPV offers."),
}


class SuggestBody(BaseModel):
    mode: Mode
    # The set on screen when the chatter presses Regenerate.
    avoid: list[str] = Field(default_factory=list, max_length=10)


def build_messages(persona: str, f: Fan, history: list[tuple[str, str]], mode: str,
                   *, avoid: list[str] = (), painful_on: bool = True,
                   lang: str = "en", clock: str = "",
                   v: "_voice.VoiceBlocks" = _voice.HER) -> list[dict]:
    convo = "\n".join(f"{'FAN' if d == 'in' else 'YOU'}: {b}" for d, b in history if b)
    last = next((d for d, b in reversed(history) if b), None)
    turn = ("He spoke last: answer him." if last == "in"
            else "You spoke last: write your natural next text, not a repeat."
            if last == "out" else "No messages yet: open the chat.")
    no_paid = ("" if mode == "tip_request" else
               "- NEVER offer or hint at PPV, pics, or anything paid.\n")
    system = (
        f"{persona}\n"
        "You are writing the NEXT text you send this fan. 100% human, never "
        "a bot.\n\n"
        f"{v.painful_texting + chr(10) + chr(10) if painful_on else ''}"
        f"{clock_block(clock)}"
        f"THIS MESSAGE — {MODES[mode]}\n\n"
        "HARD RULES:\n"
        f"{no_paid}"
        "- quietly make him feel like the only one. you KNOW him: never "
        "re-ask name/age/job, use it.\n"
        "- never apologize for the delay, never needy.\n"
        "- SHORT: lowercase, u/ur, 0-1 emoji, never reuse a line or emoji from "
        "this chat, no paragraphs.\n"
        f"{NO_NARRATION_RULE}"
        f"{ONPLATFORM_GUARDRAIL}\n\n"
        f"{v.live_proof}\n\n"
        f"{BIO_CONSISTENCY_GUARDRAIL}\n\n"
        f"{v.emoji_vocab}"
        f"Write {N_SUGGESTIONS} different options: each a complete text on its "
        f"own, each a different angle or wording. Answer ONLY with JSON {_SHAPE}."
        f"{_language.output_language_directive(lang)}"
    )
    avoid_block = ("Don't repeat or closely echo these earlier options:\n"
                   + "\n".join(f"- {a[:_MAX_CHARS]}" for a in avoid if a.strip())
                   + "\n\n") if any(a.strip() for a in avoid) else ""
    user = (
        f"What you know about him:\n{_fan_facts(f, v)}\n\n"
        f"Recent conversation (oldest→newest):\n{convo or '(none)'}\n\n"
        f"{avoid_block}"
        f"{turn} Write the {N_SUGGESTIONS} options now, in THIS MESSAGE's style."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def _options(res: llm_client.LLMResult) -> list[str]:
    parsed = res.parsed if isinstance(res.parsed, dict) else {}
    raw = parsed.get("suggestions")
    if not isinstance(raw, list):
        return []
    return [s.strip() for s in raw if isinstance(s, str) and s.strip()]


@router.post("/admin/copilot/{account_id}/{fan_id}/suggest")
async def suggest(account_id: str, fan_id: int,
                  body: SuggestBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        f = await s.get(Fan, (str(account_id), int(fan_id)))
    if f is None:
        raise HTTPException(status_code=404, detail="fan not found")

    v = await load_voice_blocks(account_id)
    lang = _language.resolve_language(await _language.load_account_language(account_id),
                                      getattr(f, "language", None))
    history = _transcript(await _history(account_id, int(fan_id), _HISTORY_TAIL))
    msgs = build_messages(
        await _load_persona(account_id), f, history, body.mode, avoid=body.avoid,
        painful_on=await load_painful_texting_flag(account_id), lang=lang,
        clock=clock_line(await load_clock_tz(account_id)), v=v)
    model = await resolve_model(account_id, PURPOSE)
    try:
        # A missing or rejected key raises LLMKeyError → server.py's 424.
        res = await llm_client.chat(model=model, messages=msgs, purpose=PURPOSE,
                                    account_id=account_id, fan_id=int(fan_id),
                                    response_format={"type": "json_object"},
                                    temperature=_TEMPERATURE)
    except llm_client.LLMKeyError:
        raise  # before LLMHTTPError, which it also subclasses
    except LLMCapExceeded:
        raise HTTPException(status_code=429, detail="Today's AI limit for this "
                            "creator is reached.")
    except LLMHTTPError:
        log.warning("copilot: provider error account=%s fan=%s", account_id, fan_id,
                    exc_info=True)
        raise HTTPException(status_code=502, detail="The AI provider failed. "
                            "Try again.")

    # The same floor every sender runs, per option: narration strip and
    # off-platform guard, the account's emoji strip, OF's word restrictions,
    # then the agency's banned words (a blocked option is dropped).
    strip_emoji = await load_strip_emojis(account_id)
    banned, banned_mode = await load_banned_words(account_id)
    out: list[str] = []
    for opt in _options(res)[:N_SUGGESTIONS]:
        text, _leak = await finalize_draft(opt, account_id=account_id,
                                           fan_id=int(fan_id), purpose=PURPOSE,
                                           strip_emoji=strip_emoji, v=v)
        text = apply_word_restriction(text)[:_MAX_CHARS].strip()
        kept, _hits = filter_banned([text], banned, banned_mode)
        if kept and kept[0].strip():
            out.append(kept[0])
    if not out:
        raise HTTPException(status_code=502, detail="The AI returned no usable "
                            "suggestion. Try again.")
    return {"mode": body.mode, "suggestions": out}
