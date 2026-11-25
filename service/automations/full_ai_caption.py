from __future__ import annotations

import json
import random
import re

import llm_client
import vault_ai_brief
from automations import _language
from automations._markers import strip_asked
from automations._router_jev import line_text
from automations.full_ai_mode import full
from automations.full_ai_sell import Pick
from automations.full_ai_writers import (
    FREE_TERMS, WriteResult, _fan, copied, nearest_line, own_lines, priced_block, prompt_pieces,
    reject, reoffers, strip_labels, strip_quotes, thread_lines, walk,
)
from automations.names import resolve_fan_name

PURPOSE = "full_ai_caption"
TEMPERATURE = 0.6

GROUND_TRUTH = (
    "GROUND TRUTH: never name a colour, garment, place, body part or act that is\n"
    "not in the facts above. If the facts do not say it, you may not write it.\n"
    "You do not know WHEN this was filmed, whether it expires, or whether it is\n"
    "leaving. Never claim a time, a deadline or a limited window.\n"
)
EXAMPLES = (
    "Match the register of these (adapt to the facts, never copy them):\n"
    '  "couldnt keep the red set on for long"\n'
    '  "you caught me in the tub... come see"\n'
)
STYLES = ("detail", "house", "blunt", "question")
OPEN_RULE = ("OPEN with the most specific visual detail from the facts "
             "(garment, place, position), then the tease.")
STYLE_RULES = {
    "detail": ("ONE {tone} line <= 100 chars. " + OPEN_RULE + "\n"
               "At most ONE emoji, only if it earns its place.\n"),
    "house": ("ONE {tone} line <= 110 chars.\nAt most ONE emoji.\n"),
    "blunt": ("ONE {tone} line <= 70 chars, NO emoji, no hashtags/@. "
              "Say the thing plainly. Shorter always wins.\n"),
    "question": ("ONE {tone} line <= 110 chars ending in a QUESTION he wants "
                 "answered. Never state what the media shows outright.\n"),
}
DIFFERS_RULE = ("ONE {tone} caption <= 220 chars, the only message on the card, in this order: first "
                "say plainly it isn't what he asked for; then what it really shows, from the facts, "
                "naming its kind and how many he {gets} in plain words (\"1 photo\", \"2 videos\")"
                "{price}; then the tease. Never claim it shows what he asked for. At most ONE emoji.\n")
TONE = "sultry"
HEAD = ("You write first-person sales copy for an OnlyFans creator's PPV "
        "send, from the recorded facts about one piece of vault media.\n"
        "  caption - ")
JSON_CONTRACT = 'Respond with STRICT JSON only: {"caption": "..."}.'

FAN_HEAD = "WHO IS READING IT"
STEER_RULE = (
    "Use this to choose WHICH TRUE DETAIL of the media to open on, and how to "
    "address him. It is NOT a list of things the media contains. Never name an act, "
    "a garment or a body part that the facts above do not list, however much he "
    "wants it — the HARD RULE above wins every time."
)
ONE_DETAIL = ("Work in AT MOST ONE thing about him, and only if it lands "
              "naturally. A caption that just sells the media beats one that "
              "name-drops his job.")
_KINK_MAX = 160

FREE_PRICE_BLOCK = "THE PRICE\n" + FREE_TERMS
NAME_PRICE = "\nIn this caption, name it."

SET_FACTS = "THE SET HE GETS: {locked}, locked{previews}. Name only these kinds and counts."
PREVIEW_COUNT = (" A count you give is the locked count; never add the ones he already sees into it. "
                 "Mention those apart, if at all (\"plus one you can already see\"){free}.")

CHAT_HEAD = "THE CHAT SO FAR (oldest first, his newest message last)"
CHAT_RULE = ("Use the chat to choose WHICH TRUE DETAIL to open on, to answer what he just said, and for "
             "your tone. It is NOT a list of things the media contains, and a kind, count or price said "
             "in it is not this piece's: THE SET HE GETS and THE PRICE below are. Never reuse a line you "
             "already sent him. The HARD RULE and GROUND TRUTH win every time.")
CHAT_TAIL = 15
_KIND_WORD = {"photo": "photo", "video": "video", "gif": "gif", "audio": "voice note"}

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _counted(media: list[dict]) -> str:
    order: dict[str, list[int]] = {}
    for m in media:
        order.setdefault(str(m.get("kind") or "photo"), []).append(int(m.get("seconds") or 0))
    out = []
    for kind, secs in order.items():
        word = _KIND_WORD.get(kind, kind)
        total = sum(secs) if kind in ("video", "gif") else 0
        out.append(f"{len(secs)} {word}{'s' * (len(secs) > 1)}"
                   + (f" {total // 60}:{total % 60:02d}" if total else ""))
    return " + ".join(out)


def set_facts(pick: Pick) -> str:
    media = (pick.facts or {}).get("media")
    if not media:
        media = [{"kind": k} for k, n in (pick.facts or {}).get("kinds", {}).items() for _ in range(n)]
        shown = []
    else:
        media, shown = media[:len(pick.media)], media[len(pick.media):]
    previews = f", plus {_counted(shown)} he sees without unlocking" if shown else ""
    count = PREVIEW_COUNT.format(free=", never as free" if pick.price_cents else "") if shown else ""
    return SET_FACTS.format(locked=_counted(media), previews=previews) + count


def style_for(account_id: str, fan_id: int, media_id: int) -> str:
    return random.Random(f"capstyle:{account_id}:{fan_id}:{media_id}").choice(STYLES)


def differs_rule(priced: bool) -> str:
    return DIFFERS_RULE.format(tone=TONE, gets="unlocks" if priced else "gets",
                               price=" and the price from THE PRICE" if priced else "")


def system(style: str, rule: str | None = None) -> str:
    rule = rule or (STYLE_RULES.get(style) or STYLE_RULES["detail"]).format(tone=TONE)
    return HEAD + rule + GROUND_TRUTH + EXAMPLES + JSON_CONTRACT


def him_lines(fan_info: dict) -> list[str]:
    f = _fan(fan_info)
    out: list[str] = []
    name = resolve_fan_name(f)
    if name:
        out.append(f"his name: {str(name).split('/')[0][:40]}")
    if f.fetishes and str(f.fetishes).strip():
        out.append(f"into: {str(f.fetishes).strip()[:_KINK_MAX]}")
    return out


def price_block(pick: Pick, was_cents: int | None) -> str:
    return priced_block(pick.price_cents, was_cents) if pick.price_cents else FREE_PRICE_BLOCK


def body_suffix(lines: list[str], price: str) -> str:
    parts: list[str] = []
    if lines:
        parts.append(FAN_HEAD + "\n" + "\n".join(f"  - {ln}" for ln in lines) + "\n\n"
                     + STEER_RULE + "\n" + ONE_DETAIL)
    parts.append(price)
    return "\n\n" + "\n\n".join(parts)


def _shown(facts) -> list:
    return (getattr(facts, "cut_rows", None) or [])[-CHAT_TAIL:] if full(getattr(facts, "mode", None)) else []


def chat_block(facts) -> str | None:
    lines = thread_lines(_shown(facts), CHAT_TAIL)
    return f"{CHAT_HEAD}\n{lines}\n\n{CHAT_RULE}" if lines else None


def messages(facts, pick: Pick, was_cents: int | None) -> list[dict] | None:
    hero = (pick.facts or {}).get("hero")
    if not hero:
        return None
    fields = hero["fields"]
    user = vault_ai_brief.copy_brief(fields, description=str(fields.get("description") or ""),
                                     duration_seconds=hero.get("seconds"), kind=hero.get("kind") or "")
    if full(getattr(facts, "mode", None)):
        if chat := chat_block(facts):
            user = f"{user}\n\n{chat}"
        user = f"{user}\n\n{set_facts(pick)}"
    rule = None
    if note := nearest_line(facts, pick):
        user, rule = f"{user}\n\n{note}", differs_rule(bool(pick.price_cents))
    return [{"role": "system", "content": system(style_for(facts.account_id, facts.fan_id, hero["media_id"]), rule)},
            {"role": "user", "content": user + body_suffix(him_lines(facts.fan_info), price_block(pick, was_cents)
                                                          + (NAME_PRICE if note and pick.price_cents else ""))}]


def parse(text: str) -> str:
    m = _JSON_OBJ_RE.search(text or "")
    if not m:
        return ""
    try:
        data = json.loads(m.group(0))
    except (TypeError, ValueError):
        return ""
    return str(data.get("caption") or "").strip() if isinstance(data, dict) else ""


async def write(facts, msgs: list[dict], *, deadline: float,
                writers: list[str] | None = None) -> WriteResult:
    cfg = facts.config
    lang = await _language.load_account_language(facts.account_id) if cfg["floor_on"] else ""
    shown = _shown(facts)
    thread = (thread_lines(shown, CHAT_TAIL),)
    prompt = [p for m in msgs for p in prompt_pieces(str(m.get("content") or ""), drop=thread)]
    pick = getattr(facts, "pick", None)
    own = own_lines(facts, pick)
    if not reoffers(facts, pick):
        own += [t for t in (line_text(m) for m in shown if m.direction != "in") if t]

    async def try_once(writer: str, timeout: float) -> tuple[str, str | None]:
        r = await llm_client.chat(model=writer, messages=msgs, purpose=PURPOSE,
                                  account_id=facts.account_id, temperature=TEMPERATURE,
                                  timeout_s=timeout, max_attempts=1)
        text = strip_quotes(strip_labels(strip_asked(parse(r.content or ""), frozenset())[0]))
        return text, (reject(text, lang, False) or copied(text, prompt, own)) \
            if text and cfg["floor_on"] else None

    return await walk(cfg, writers or cfg["writers"], deadline, try_once)
