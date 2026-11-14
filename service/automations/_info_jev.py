"""automations/_info_jev.py — Full AI Chat's get-to-know questions: one Jev call, one extract.

Not a stream: it registers no kind and holds no outbound primitive (`_router_jev`'s shape).
On a speaking Turn `full_ai_turn` asks Jev, in ONE request, a Noul `stated_<field>` per wcfi
extract field (did he just state it?) and, on a chat Turn, a Choice `next_question` over every
`info_fields` field still missing from the fold, plus `none` (which one should she ask next?). The Jev state
carries `asked` (field -> times asked); no code filter drops a field for being asked before
(D32: wcfi's `X:2` cap is not reused). For the fired fields only, the values come from wcfi's
verbatim extract prompt (`_EXTRACT_SYSTEM` / `_extract_messages`, NEW-45/46) on DeepSeek.
Every wording, the threshold and the model pin live here; `INFO_VERSION` (their digest) goes
on the row's `jev_json.info_version`. Wording: new (no old info Jev existed), docs/prompts
NEW-115; not probed yet.

  - `STATED`, `NEXT_QUESTION`, `THRESHOLD`, `INFO_VERSION` (`info_version()`).
  - `missing(config, fan_info)`: the `info_fields` the fold has no value for, in config order.
  - `state(router_state, asked, offered)`: the info Jev state.
  - `ask(state, account_id, offered, *, timeout_s)`: one request; `Info`, or `GateError` on any
    failure (no key, no SDK, timeout, HTTP error, a missing or out-of-range answer).
  - `extract(facts, fields, *, timeout_s)`: the fired fields' new values; raises
    `llm_client.LLMError` or `ExtractError("unparsable")`.
  - `question_line(field, fan_info)`: wcfi's verbatim ask line for a `missing` field.

The key is `_router_jev`'s (`tenant_keys.typesafe_key_for`). `_client` is the tests' fake seam.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from typing import Any, NamedTuple

import llm_client
from automations import _jev
from automations._router_jev import GateError, line_text
from automations._textutil import nonempty
from automations.welcome_chatter_for_info import (
    _EXTRACT_FIELDS, _extract_messages, _load_persona, _questions_still_needed,
)

MODEL = "jev-1.14.0"
TIMEOUT_S = 10.0
MAX_RETRIES = 1
# ASSUMPTION (unprobed): a fired Noul costs one cheap extract that keeps current values
# unless he said something new, so the bar sits at even odds.
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


def info_version() -> str:
    """A short digest of what changes what Jev answers: model, wording, threshold, state keys."""
    return hashlib.sha256(json.dumps(
        {"model": MODEL, "stated": STATED, "next_question": NEXT_QUESTION, "threshold": THRESHOLD,
         "state_keys": STATE_KEYS}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


INFO_VERSION = info_version()


class ExtractError(Exception):
    """The extract answered, but not with a JSON object."""


class Info(NamedTuple):
    stated: dict[str, float]        # field -> P(he stated it this Turn)
    pick: str | None                # the field to ask next, None for `none`
    fired: list[str]                # stated fields at or above THRESHOLD


def missing(config: dict, fan_info: dict) -> list[str]:
    """The config's `info_fields` with no value in `fan_info`, in config order, by wcfi's own
    `nonempty` (so every missing field has a `question_line`). Pure."""
    return [k for k in config["info_fields"] if not nonempty(fan_info.get(k))]


def state(router_state: dict, asked: dict, offered: list[str]) -> dict[str, Any]:
    """His Turn and the thread as the Router reads them, and how often each offered field was
    asked."""
    return {**{k: router_state.get(k) for k in STATE_KEYS},
            "asked": {f: int(asked.get(f, 0)) for f in offered}}


def _client(key: str) -> Any:
    return _jev.client(key, MODEL, TIMEOUT_S, MAX_RETRIES)


def _questions(offered: list[str]) -> dict[str, Any]:
    from typesafe_sdk import Choice, Noul
    q: dict[str, Any] = {qid: Noul(instructions=v["instructions"], criteria=v["criteria"])
                         for qid, v in STATED.items()}
    if offered:                                 # nothing to offer: nothing to pick
        crit = NEXT_QUESTION["criteria"]
        q["next_question"] = Choice(instructions=NEXT_QUESTION["instructions"],
                                    criteria={k: crit[k] for k in [*offered, "none"]})
    return q


async def ask(st: dict[str, Any], account_id: str, offered: list[str], *, timeout_s: float) -> Info:
    """Every `stated_*` Noul and the `next_question` Choice over `offered` + none (no Choice when
    nothing is offered), in one request within `min(TIMEOUT_S, timeout_s)`. Raises `GateError` on
    any failure."""
    from tenant_keys import typesafe_key_for
    try:
        key = await typesafe_key_for(account_id)
        if not key:
            raise GateError("no TypeSafe key (agency or TYPESAFE_API_KEY)")
        res = await asyncio.wait_for(_client(key).system_one(st, _questions(offered), model=MODEL),
                                     min(TIMEOUT_S, timeout_s))
        stated = {qid.removeprefix("stated_"): float(res.nouls[qid].noul) for qid in STATED}
        bad = [f for f, p in stated.items() if not 0.0 <= p <= 1.0]
        if bad:
            raise GateError(f"answer out of range: {bad}")
        choice = res.choices["next_question"].choice if offered else "none"
        if choice not in (*offered, "none"):
            raise GateError(f"choice not offered: {choice!r}")
    except GateError:
        raise
    except Exception as e:      # SDK missing, HTTP, timeout, a missing answer
        raise GateError(f"{type(e).__name__}: {e}"[:300]) from e
    return Info(stated, None if choice == "none" else choice,
                [f for f in _EXTRACT_FIELDS if stated[f] >= THRESHOLD])


async def extract(facts, fields: list[str], *, timeout_s: float) -> dict[str, str]:
    """wcfi's extract over the Turn's rows and the fold, on DeepSeek, one attempt: the new value of
    each field in `fields` he stated (a newer value replaces the fold's)."""
    f = SimpleNamespace(**{k: facts.fan_info.get(k) for k in _EXTRACT_FIELDS},
                        likes_boobs=False, likes_ass=False)
    c = SimpleNamespace(messages=[(m.direction, line_text(m)) for m in facts.cut_rows])
    res = await llm_client.chat(
        model=EXTRACT_MODEL, messages=_extract_messages(f, c, persona=await _load_persona(facts.account_id)),
        purpose=PURPOSE, account_id=facts.account_id, temperature=0.2,
        response_format={"type": "json_object"}, timeout_s=timeout_s, max_attempts=1)
    data = res.parsed
    if not isinstance(data, dict):
        raise ExtractError("unparsable")
    return {k: v.strip()[:200] for k in fields
            if isinstance(v := data.get(k), str) and v.strip()}


# Each info field's line in wcfi's question list (`_questions_still_needed`); a place picks by what
# the fold already holds, as wcfi does.
_LINE_KEYS = {"real_name": ("name",), "his_age": ("age",),
              "home_country": ("country_from_city", "location"), "home_city": ("city", "location"),
              "occupation": ("job",), "hobbies": ("hobbies",), "fetishes": ("boobs_ass",)}


def question_line(field: str, fan_info: dict) -> str:
    """wcfi's verbatim ask line for a `missing` field given the fold (wcfi lists a line for every
    field `missing` returns: both read `nonempty`). Pure."""
    f = SimpleNamespace(custom_nickname=None, likes_boobs=False, likes_ass=False, recent_events=None,
                        **{k: fan_info.get(k) for k in _EXTRACT_FIELDS})
    lines = dict(_questions_still_needed(f, set()))
    return next(lines[k] for k in _LINE_KEYS[field] if k in lines)
