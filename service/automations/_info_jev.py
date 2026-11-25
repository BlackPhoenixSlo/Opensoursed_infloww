from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, NamedTuple

import llm_client
from automations import _jev
from automations._markers import strip_asked
from automations._router_jev import GateError, line_text
from automations._textutil import nonempty
from automations.welcome_chatter_for_info import (
    _EXTRACT_FIELDS, _extract_messages, _load_persona, _questions_still_needed, _recent_ask_pattern,
)

MODEL = "jev-1.14.0"
TIMEOUT_S = 10.0
MAX_RETRIES = 1
THRESHOLD = 0.5
EXTRACT_MODEL = "deepseek-v4-flash"
PURPOSE = "full_ai_info"
STATE_KEYS = ("fan_new_messages", "thread", "her_last_line")

_q = _jev.q

STATED: dict[str, dict[str, Any]] = {
    "stated_real_name": _q(
        "Does `fan_new_messages` tell her his name, or what she should call him?",
        "He gives his first name, full name or a name to call him by",
        "He gives no name for himself"),
    "stated_his_age": _q(
        "Does `fan_new_messages` tell her how old he is?",
        "He states his age or the year he was born",
        "He says nothing about his own age"),
    "stated_home_country": _q(
        "Does `fan_new_messages` tell her which country he lives in or is from?",
        "He names his country, or a place that says which country it is",
        "He says nothing about which country he lives in"),
    "stated_home_city": _q(
        "Does `fan_new_messages` tell her which city, town or area he lives in?",
        "He names the city, town or area he lives in",
        "He says nothing about which city or area he lives in"),
    "stated_hobbies": _q(
        "Does `fan_new_messages` tell her what he likes to do in his free time?",
        "He names a hobby, sport, game or something he does for fun",
        "He says nothing about what he does for fun"),
    "stated_occupation": _q(
        "Does `fan_new_messages` tell her what he does for work or study?",
        "He says his job, trade, field, or what he studies",
        "He says nothing about his work or studies"),
    "stated_fetishes": _q(
        "Does `fan_new_messages` tell her what turns him on?",
        "He names a kink, fetish, or a body part or act he is into",
        "He says nothing about what turns him on"),
}
assert set(STATED) == {f"stated_{f}" for f in _EXTRACT_FIELDS}

NEXT_QUESTION: dict[str, Any] = {
    "instructions": (
        "She is getting to know him in a flirty chat. Which ONE thing about him should she ask "
        "next, so it flows from what he just said in `fan_new_messages`? `asked` says how many "
        "times she already asked each one: a topic he dodged can wait, and he must never feel "
        "interrogated. Pick none if he just asked her something or asking now would feel forced."),
    "criteria": {
        "real_name": "His name, or what she should call him",
        "his_age": "How old he is",
        "home_country": "Which country he lives in",
        "home_city": "Which city or area he lives in",
        "hobbies": "What he likes to do for fun",
        "occupation": "What he does for work",
        "fetishes": "What turns him on",
        "none": "Ask him nothing this message",
    },
}
NEXT_QUESTION_LEAD: dict[str, Any] = {
    "instructions": (
        "She is getting to know him in a flirty chat and wants it to feel like talking, not an "
        "interview. Which ONE thing about him could she lead toward next, so it flows from what he "
        "just said in `fan_new_messages`? `asked` says how many times she already went for each one: "
        "a topic he dodged can wait. Pick none if he just asked her something, if `her_last_line` "
        "already ends on a question, or if it would feel forced. Most messages need none."),
    "criteria": NEXT_QUESTION["criteria"],
}
NEVER_LED = ("fetishes",)

LIKES_EXTRACT = (
    "For \"fetishes\" in this chat, the rule above is wider: write what turns him on as a short comma "
    "list (body parts, acts, outfits, places or scenarios), taken from what he praises, asks to see "
    "or describes doing in his own FAN: lines. Keep every item CURRENT already lists and add the new "
    "ones, newest first, at most 8 items, in his words where you can. Use \"\" only when his lines "
    "show nothing he is into. Never take an item from the YOU: lines.")

STATED_WIDE: dict[str, dict[str, Any]] = {
    "stated_hobbies": _q(
        "Does `fan_new_messages` tell her what he likes to do in his free time, or what he is doing "
        "for fun right now?",
        "He names a hobby, sport, game or something he does for fun, or says what he is watching, "
        "playing, reading or listening to right now (a show, Netflix, anime, a game, music), even "
        "in a few words",
        "He says nothing about what he does for fun or what he is watching, playing, reading or "
        "listening to"),
}
HOBBIES_EXTRACT = (
    "For \"hobbies\" in this chat, the rule above is wider: what he says he is watching, playing, "
    "reading or listening to right now counts as what he does for fun (\"im watching netflix\" -> "
    "\"watching Netflix\"). Write it as a short comma list, keep every item CURRENT already lists "
    "and add the new ones, at most 6 items, in his words where you can. Never take an item from the "
    "YOU: lines.")


def info_version(lead: bool = False, likes: bool = False, wide: bool = False) -> str:
    return hashlib.sha256(json.dumps(
        {"model": MODEL, "stated": STATED, "next_question": NEXT_QUESTION_LEAD if lead else NEXT_QUESTION,
         "threshold": THRESHOLD, "state_keys": STATE_KEYS,
         **({"likes_extract": LIKES_EXTRACT} if likes else {}),
         **({"stated_wide": STATED_WIDE, "hobbies_extract": HOBBIES_EXTRACT} if wide else {})},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


INFO_VERSION = info_version()
INFO_VERSION_LEAD = info_version(lead=True)


class ExtractError(Exception):
    pass


class Info(NamedTuple):
    stated: dict[str, float]
    pick: str | None
    fired: list[str]


def missing(config: dict, fan_info: dict) -> list[str]:
    """The config's `info_fields` with no value in `fan_info`, in config order, by wcfi's own
    `nonempty` (so every missing field has a `question_line`). Pure."""
    return [k for k in config["info_fields"] if not nonempty(fan_info.get(k))]


def askable(config: dict, fan_info: dict, lead: bool) -> list[str]:
    return [k for k in missing(config, fan_info) if not (lead and k in NEVER_LED)]


def state(router_state: dict, asked: dict, offered: list[str]) -> dict[str, Any]:
    """His Turn and the thread as the Router reads them, and how often each offered field was
    asked."""
    return {**{k: router_state.get(k) for k in STATE_KEYS},
            "asked": {f: int(asked.get(f, 0)) for f in offered}}


def _client(key: str) -> Any:
    return _jev.client(key, MODEL, TIMEOUT_S, MAX_RETRIES)


def _questions(offered: list[str], lead: bool = False, wide: bool = False) -> dict[str, Any]:
    from typesafe_sdk import Choice, Noul
    stated = {**STATED, **STATED_WIDE} if wide else STATED
    q: dict[str, Any] = {qid: Noul(instructions=v["instructions"], criteria=v["criteria"])
                         for qid, v in stated.items()}
    if offered:
        nq = NEXT_QUESTION_LEAD if lead else NEXT_QUESTION
        crit = nq["criteria"]
        q["next_question"] = Choice(instructions=nq["instructions"],
                                    criteria={k: crit[k] for k in [*offered, "none"]})
    return q


async def ask(st: dict[str, Any], account_id: str, offered: list[str], *, timeout_s: float,
              lead: bool = False, wide: bool = False) -> Info:
    try:
        res, _ = await _jev.ask_one(_client, account_id, st, _questions(offered, lead, wide), MODEL,
                                    min(TIMEOUT_S, timeout_s), GateError)
        stated = {qid.removeprefix("stated_"): float(res.nouls[qid].noul) for qid in STATED}
        bad = [f for f, p in stated.items() if not 0.0 <= p <= 1.0]
        if bad:
            raise GateError(f"answer out of range: {bad}")
        choice = res.choices["next_question"].choice if offered else "none"
        if choice not in (*offered, "none"):
            raise GateError(f"choice not offered: {choice!r}")
    except GateError:
        raise
    except Exception as e:
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    return Info(stated, None if choice == "none" else choice,
                [f for f in _EXTRACT_FIELDS if stated[f] >= THRESHOLD])


async def extract(facts, fields: list[str], *, timeout_s: float, likes: bool = False,
                  wide: bool = False) -> dict[str, str]:
    f = SimpleNamespace(**{k: facts.fan_info.get(k) for k in _EXTRACT_FIELDS},
                        likes_boobs=False, likes_ass=False)
    c = SimpleNamespace(messages=[(m.direction, line_text(m)) for m in facts.cut_rows])
    messages = _extract_messages(f, c, persona=await _load_persona(facts.account_id))
    if likes and "fetishes" in fields:
        messages = [messages[0], {"role": "system", "content": LIKES_EXTRACT}, *messages[1:]]
    if wide and "hobbies" in fields:
        messages = [messages[0], {"role": "system", "content": HOBBIES_EXTRACT}, *messages[1:]]
    res = await llm_client.chat(
        model=EXTRACT_MODEL, messages=messages,
        purpose=PURPOSE, account_id=facts.account_id, temperature=0.2,
        response_format={"type": "json_object"}, timeout_s=timeout_s, max_attempts=1)
    data = res.parsed
    if not isinstance(data, dict):
        raise ExtractError("unparsable")
    return {k: v.strip()[:200] for k in fields
            if isinstance(v := data.get(k), str) and v.strip()}


_LINE_KEYS = {"real_name": ("name",), "his_age": ("age",),
              "home_country": ("country_from_city", "location"), "home_city": ("city", "location"),
              "occupation": ("job",), "hobbies": ("hobbies",), "fetishes": ("boobs_ass",)}


def _wcfi_needed(fan_info: dict, marks: set[str]) -> list[tuple[str, str]]:
    """wcfi's `_questions_still_needed` over the fold (its other fan fields empty) and `marks`."""
    f = SimpleNamespace(custom_nickname=None, likes_boobs=False, likes_ass=False, recent_events=None,
                        **{k: fan_info.get(k) for k in _EXTRACT_FIELDS})
    return _questions_still_needed(f, marks)


def _wcfi_lines(fan_info: dict) -> dict[str, str]:
    return dict(_wcfi_needed(fan_info, set()))


def question_key(field: str, fan_info: dict) -> str:
    lines = _wcfi_lines(fan_info)
    return next(k for k in _LINE_KEYS[field] if k in lines)


def question_line(field: str, fan_info: dict) -> str:
    return _wcfi_lines(fan_info)[question_key(field, fan_info)]


_KEY_FIELDS: dict[str, tuple[str, ...]] = {}
for _f, _ks in _LINE_KEYS.items():
    for _k in _ks:
        _KEY_FIELDS[_k] = _KEY_FIELDS.get(_k, ()) + (_f,)
NEVER_LED_KEYS = frozenset(k for f in NEVER_LED for k in _LINE_KEYS[f])


class AskList(NamedTuple):
    keys: list[str]
    lines: list[str]
    ask: bool

    @property
    def presented(self) -> list[str]:
        return self.keys if self.ask else []


def asked_marks(asked: dict) -> set[str]:
    return {k for k, n in asked.items() if n >= 1} | {f"{k}:2" for k, n in asked.items() if n >= 2}


def still_needed(config: dict, fan_info: dict, asked: dict) -> list[tuple[str, str]]:
    on = set(config["info_fields"])
    return [(k, line) for k, line in _wcfi_needed(fan_info, asked_marks(asked))
            if on.intersection(_KEY_FIELDS.get(k, ()))]


def unled(al: AskList) -> AskList:
    keep = [i for i, k in enumerate(al.keys) if k not in NEVER_LED_KEYS]
    return AskList([al.keys[i] for i in keep], [al.lines[i] for i in keep], al.ask and bool(keep))


def ask_list(config: dict, fan_info: dict, asked: dict, history: list[tuple[str, str]],
             rng) -> AskList:
    needed = still_needed(config, fan_info, asked)
    keys, lines = [k for k, _ in needed], [line for _, line in needed]
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
    breather_p = 0.55 if len(keys) <= 2 else 0.33
    ask = bool(lines)
    if ask:
        if ask_streak >= 3:
            ask = False
        elif fan_just_asked:
            ask = False
        elif last_breather:
            ask = True
        elif fan_low_effort:
            ask = rng.random() >= 0.6
        else:
            ask = rng.random() >= breather_p
    return AskList(keys, lines, ask)




class AskedMarker(NamedTuple):
    text: str
    key: str | None
    raw: str | None


def asked_marker(text: str, offered: frozenset[str]) -> AskedMarker:
    out, values = strip_asked(text, offered)
    raw = values[-1] if values else None
    return AskedMarker(out, raw.lower() if raw and raw.lower() in offered else None, raw)
