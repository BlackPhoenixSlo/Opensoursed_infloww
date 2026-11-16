"""full_ai_caption — the separate PPV caption call of a Full AI Turn (`config.caption_writer`
"caption"; default "chat" never reaches here).

On a Turn that sends a PPV (a priced sell_now Pick, or make_right's Free item) ONE call writes the
caption the PPV rides on, from the old 1:1 caption prompt, verbatim (fastt `_ppv_caption.caption_for`
→ `describe_media._copy_call`): system `caption_style_prompt(style, "her", audience="1to1")`, user
`vault_ai_brief.copy_brief` over the Pick's hero media + `_ppv_caption.body_suffix` (his facts
under the steer rule, then the price block). The chat Writer then writes only the bubbles before it
(`full_ai_writers.messages_for(plain=True)`). `full_ai_turn` runs the result through the shared chain
as one bubble and the Claim audit; a miss falls back to the chat Writer's caption (today's path).

Pure prompt assembly + one Writer walk; sends nothing.
"""
from __future__ import annotations

import json
import random
import re

import llm_client
import vault_ai_brief
from automations import _language
from automations.full_ai_mode import full
from automations.full_ai_sell import Pick
from automations.full_ai_writers import (
    FREE_TERMS, WriteResult, _fan, copied, nearest_line, own_lines, priced_block, prompt_pieces,
    reject, strip_labels, strip_quotes, walk,
)
from automations.names import resolve_fan_name

PURPOSE = "full_ai_caption"
TEMPERATURE = 0.6                    # old `describe_media._copy_call`

# OLD-OTH-25..27, verbatim (fastt describe_media.py:122-142, :168-195, :229-254; `_COPY_TONE["her"]`).
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
TONE = "sultry"
HEAD = ("You write first-person sales copy for an OnlyFans creator's PPV "
        "send, from the recorded facts about one piece of vault media.\n"
        "  caption - ")
JSON_CONTRACT = 'Respond with STRICT JSON only: {"caption": "..."}.'

# OLD-CORE-32, verbatim (fastt _ppv_caption.py:125-243): the fan half of the body suffix.
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

# NEW-127, DRAFT (pending the owner's OK): a Free item's price block — OLD-CORE-33's heading over
# OLD-AIC-12's free terms (`FREE_TERMS`), no new sentence.
FREE_PRICE_BLOCK = "THE PRICE\n" + FREE_TERMS

# NEW-164 (test / live Mode; owner-forwarded M3 2026-11-16): the facts above name the hero's kind
# only, so a 1-photo card read "i just filmed it for u"; the whole set's kinds and counts under them.
SET_FACTS = "THE SET HE GETS: {locked}, locked{previews}. Name only these kinds and counts."
_KIND_WORD = {"photo": "photo", "video": "video", "gif": "gif", "audio": "voice note"}

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)     # old `describe_media._JSON_OBJ_RE`


def _counted(media: list[dict]) -> str:
    """"3 photos" / "1 video 0:30" / "2 photos + 1 video 1:10": kinds in first-seen order, a moving
    kind with its summed length when known."""
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
    """SET_FACTS over the Pick's true set: its locked items (`facts["media"]`'s first
    `len(pick.media)`, else `facts["kinds"]`) and, apart, its free previews. Pure."""
    media = (pick.facts or {}).get("media")
    if not media:
        media = [{"kind": k} for k, n in (pick.facts or {}).get("kinds", {}).items() for _ in range(n)]
        shown = []
    else:
        media, shown = media[:len(pick.media)], media[len(pick.media):]
    previews = f", plus {_counted(shown)} he sees without unlocking" if shown else ""
    return SET_FACTS.format(locked=_counted(media), previews=previews)


def style_for(account_id: str, fan_id: int, media_id: int) -> str:
    """Old `_ppv_caption.style_for`, seeded as `caption_for` seeded it: same fan, same media, same
    style (a replay builds the same prompt)."""
    return random.Random(f"capstyle:{account_id}:{fan_id}:{media_id}").choice(STYLES)


def system(style: str) -> str:
    """Old `caption_style_prompt(style, "her", audience="1to1")`: no mass-audience clause."""
    rule = STYLE_RULES.get(style) or STYLE_RULES["detail"]
    return HEAD + rule.format(tone=TONE) + GROUND_TRUTH + EXAMPLES + JSON_CONTRACT


def him_lines(fan_info: dict) -> list[str]:
    """Old `_ppv_caption.him_lines` over the session's fan fold: his name and his kink.
    ASSUMPTION: no `about him` / `notes on him` (a test Fan has no profile row) and no spend facts
    (their amounts would fail the price check, as on the chat prompt, rwl fa3 S3). Overturned when
    live Turns carry a fan profile."""
    f = _fan(fan_info)
    out: list[str] = []
    name = resolve_fan_name(f)
    if name:
        out.append(f"his name: {str(name).split('/')[0][:40]}")
    if f.fetishes and str(f.fetishes).strip():
        out.append(f"into: {str(f.fetishes).strip()[:_KINK_MAX]}")
    return out


def price_block(pick: Pick, was_cents: int | None) -> str:
    """OLD-CORE-33 as `full_ai_writers.sell_section` picks it (was-price form only when `was_cents`
    is over the price), or the DRAFT free block for a Free item (price 0)."""
    return priced_block(pick.price_cents, was_cents) if pick.price_cents else FREE_PRICE_BLOCK


def body_suffix(lines: list[str], price: str) -> str:
    """Old `_ppv_caption.body_suffix`: his facts, then the price block."""
    parts: list[str] = []
    if lines:
        parts.append(FAN_HEAD + "\n" + "\n".join(f"  - {ln}" for ln in lines) + "\n\n"
                     + STEER_RULE + "\n" + ONE_DETAIL)
    parts.append(price)
    return "\n\n" + "\n\n".join(parts)


def messages(facts, pick: Pick, was_cents: int | None) -> list[dict] | None:
    """The caption call's messages; None when no locked item is described (`pick.facts["hero"]`,
    old `_copy_call`'s `no_description` stop, before any spend). Test / live Mode: `set_facts` (the
    whole set's kinds and counts, the hero's facts naming its kind only) under the media facts.
    A Pick not what he asked for (`full_ai_writers.nearest_line`, test / live unless "plain"):
    NEAREST_NOTE under them. Shadow: neither."""
    hero = (pick.facts or {}).get("hero")
    if not hero:
        return None
    fields = hero["fields"]
    user = vault_ai_brief.copy_brief(fields, description=str(fields.get("description") or ""),
                                     duration_seconds=hero.get("seconds"), kind=hero.get("kind") or "")
    if full(getattr(facts, "mode", None)):
        user = f"{user}\n\n{set_facts(pick)}"
    if note := nearest_line(facts, pick):
        user = f"{user}\n\n{note}"
    return [{"role": "system", "content": system(style_for(facts.account_id, facts.fan_id, hero["media_id"]))},
            {"role": "user", "content": user + body_suffix(him_lines(facts.fan_info), price_block(pick, was_cents))}]


def parse(text: str) -> str:
    """Old `_parse_copy` + `caption_for`'s read: the `caption` of the first JSON object, else ""."""
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
    """`full_ai_writers.walk` for the caption: the side's `writers` in order (tries, per-Writer
    timeouts and the deadline as there), the next only after a failure, a
    reply with no caption (`empty`) or a code-floor reject (`floor_on`, no marker allowed): the
    chat Writer's strips and floor (`strip_labels`, `strip_quotes`, `reject`, no gif-only reply),
    then `copied` against every message of this call (`echo`; no persona in it, the vault
    description is in it) and her last outbound lines of the thread (`repeat`; none on a re-offer
    of the same piece, `full_ai_writers.reoffers`).
    ASSUMPTION: no `response_format` (not every Writer provider takes it); a reply without the JSON
    caption is `empty`, as the old lane kept its canned line. Overturned if the chain's providers
    all accept json_object."""
    cfg = facts.config
    lang = await _language.load_account_language(facts.account_id) if cfg["floor_on"] else ""
    prompt = [p for m in msgs for p in prompt_pieces(str(m.get("content") or ""))]
    own = own_lines(facts, getattr(facts, "pick", None))

    async def try_once(writer: str, timeout: float) -> tuple[str, str | None]:
        r = await llm_client.chat(model=writer, messages=msgs, purpose=PURPOSE,
                                  account_id=facts.account_id, temperature=TEMPERATURE,
                                  timeout_s=timeout, max_attempts=1)
        text = strip_quotes(strip_labels(parse(r.content or "")))
        return text, (reject(text, lang, False) or copied(text, prompt, own)) \
            if text and cfg["floor_on"] else None

    return await walk(cfg, writers or cfg["writers"], deadline, try_once)
