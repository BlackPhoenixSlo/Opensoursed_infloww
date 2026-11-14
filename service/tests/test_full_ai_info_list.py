#!/usr/bin/env python3
"""test_full_ai_info_list — Full AI `info_questions: "list"` (DRAFT): the Writer gets wcfi's whole
still-need list, Jev only says what he stated.

   case_config_key                   default "pick"; "list" valid; anything else a field error
   case_pick_mode_prompt_unchanged   no `ask_list` (pick mode / not chat): today's need block
   case_list_lines_are_wcfi_lines    empty fold: ASK_HEAD + wcfi's lines, string equal, in its order
   case_list_shrinks_and_info_fields filled fields drop out (city/country variants as wcfi); a
                                     field the config dropped is never listed; all known: know enough
   case_list_never_nags              scripted session: core keys (name/age/location/job) twice,
                                     others once, an asked-once key moves to the back, the mark is
                                     wcfi's `_primary_ask_target`; capped all: know enough
   case_list_tiers_as_wcfi           he asked -> FAN_ASKED, no ask; 3 asks in a row -> breather;
                                     after a breather -> ask; dice seeded per Turn
   case_list_chat_turns              Test chat: no `next_question` Choice; system holds ASK_HEAD +
                                     the lines; `jev_json.info` records presented; the fold counts
                                     wcfi's key; a sext Turn in list mode: no list, nothing counted

Run: ./venv/bin/python service/tests/test_full_ai_info_list.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_chat_helpers import (
    _CHAIN_KEYS, A, DEEPSEEK, NANO, OK_LINE, OPENROUTER, OWNER_A, TURN, ZAI, _agency_keys, _body,
    _guarded, _reply, _rows, _store_config,
)
import json
import random
from types import SimpleNamespace

from _full_ai_fixtures import QUIET, FakeInfoJev, FakeJev, FakeWriterHTTP, _fake_jev
from automations import _info_jev as ij
from automations import full_ai_writers as wr
from automations.full_ai_config import DEFAULTS, validate
from automations.welcome_chatter_for_info import _BREATHER_VARIANTS

# `lead_in` off: these cases pin wcfi's list as today (the lead form: `case_list_lead_in`).
LIST = {**DEFAULTS, "info_questions": "list", "lead_in": False}
NAME = "- You DON'T know his real name yet. Ask what his name is / what you should call him."
AGE = "- You DON'T know his age yet. Find out how old he is."
WHERE = "- You DON'T know where he lives. Ask where he's from."
JOB = "- You DON'T know what he does for work. Ask what he does for a living."
HOBBIES = "- You DON'T know his hobbies yet. Ask what he likes to do."
INTO = "- You DON'T know what he's into (boobs/ass). Ask playfully."


def _row(direction, text, mid):
    return SimpleNamespace(direction=direction, body=text, created_at=None, message_id=mid,
                           automation_kind=None, media_count=0, raw_json=None,
                           price_cents=None, is_paid=False, purchased_at=None)


def _facts(config, fan_info=None, ask_list=None, text="hey you"):
    return SimpleNamespace(
        account_id="acct_msgs", anchor_key="test:s:1", config=config, fan_info=dict(fan_info or {}),
        next_question=None, spent=[], offer_piece=None, ask_list=ask_list,
        cut_rows=[_row("out", "hii", 1), _row("in", text, 2)])


def _sys(facts, route="chat"):
    return wr.messages_for(route, "otherwise", 2, facts, None)[0]["content"]


class _Rng:
    """A fixed dice: `random()` always answers `x`."""

    def __init__(self, x):
        self.x = x

    def random(self):
        return self.x


ASKING = _Rng(0.99)                 # every dice says ask


def case_config_key():
    assert DEFAULTS["info_questions"] == "pick", DEFAULTS
    assert validate(LIST) == [] and validate(DEFAULTS) == []
    assert validate({**DEFAULTS, "info_questions": "all"}) == ["info_questions: must be one of pick, list"]


def case_pick_mode_prompt_unchanged():
    # No `ask_list` (pick mode, or a non-chat Route in list mode) reads exactly as a facts without it.
    old = _facts(DEFAULTS)
    del old.ask_list
    for route in ("chat", "sext", "ai_dare", "make_right"):
        assert _sys(_facts(DEFAULTS), route) == _sys(old, route), route
        assert _sys(_facts(LIST), route) == _sys(old, route), route


def case_list_lines_are_wcfi_lines():
    al = ij.ask_list(LIST, {}, {}, [("in", "hey you how was your day")], ASKING)
    assert al.keys == ["name", "age", "location", "job", "hobbies", "boobs_ass"], al
    assert al.lines == [NAME, AGE, WHERE, JOB, HOBBIES, INTO] and al.ask and al.presented == al.keys
    need = wr.ASK_HEAD + "\n".join([NAME, AGE, WHERE, JOB, HOBBIES, INTO])
    assert wr._need_block(_facts(LIST, ask_list=al), False, random.Random(1)) == need
    assert need in _sys(_facts(LIST, ask_list=al))


def case_list_shrinks_and_info_fields():
    keys = lambda cfg, fi: [k for k, _ in ij.still_needed(cfg, fi, {})]   # noqa: E731
    assert keys(LIST, {"real_name": "Sam", "occupation": "chef"}) == ["age", "location", "hobbies", "boobs_ass"]
    assert keys(LIST, {"home_city": "Leeds"}) == ["name", "age", "country_from_city", "job", "hobbies", "boobs_ass"]
    assert ij.still_needed(LIST, {"home_country": "UK"}, {})[2] == (
        "city", "- You know he's from UK but not which city/area. Ask what part.")
    assert keys(LIST, {"fetishes": "feet"})[-1] == "hobbies"
    # Only the config's fields: no age, no job; location stays while either place field is on.
    cfg = {**LIST, "info_fields": ["real_name", "home_city", "hobbies"]}
    assert keys(cfg, {}) == ["name", "location", "hobbies"], keys(cfg, {})
    assert keys({**LIST, "info_fields": ["home_country"]}, {"home_country": "UK"}) == []
    # Everything known: nothing listed, the know-enough tier.
    full = {f: "x" for f in DEFAULTS["info_fields"]}
    al = ij.ask_list(LIST, full, {}, [("in", "hi there you")], ASKING)
    assert al == ij.AskList([], [], False), al
    assert wr._need_block(_facts(LIST, full, al), False, random.Random(1)) == wr.KNOW_ENOUGH


def case_list_never_nags():
    """Every Turn asks (fixed dice) and he dodges everything: wcfi's marks over a whole session."""
    asked, seen = {}, []
    for _ in range(12):
        al = ij.ask_list(LIST, {}, asked, [("in", "hmm idk really man")], ASKING)
        if not al.lines:
            break
        seen.append(al.keys)
        asked = ij.mark_asked(asked, al)
    assert seen == [
        ["name", "age", "location", "job", "hobbies", "boobs_ass"],
        ["age", "location", "job", "hobbies", "boobs_ass", "name"],    # asked once: to the back
        ["age", "location", "job", "hobbies", "boobs_ass"],            # name:2 -> dropped
        ["location", "job", "hobbies", "boobs_ass", "age"],
        ["location", "job", "hobbies", "boobs_ass"],
        ["job", "hobbies", "boobs_ass", "location"],
        ["job", "hobbies", "boobs_ass"],
        ["hobbies", "boobs_ass", "job"],
        ["hobbies", "boobs_ass"],
        ["boobs_ass"],                                                 # others: once
    ], seen
    assert asked == {"name": 2, "age": 2, "location": 2, "job": 2, "hobbies": 1, "boobs_ass": 1}, asked
    assert ij.asked_marks({"name": 2, "hobbies": 1, "age": 0}) == {"name", "name:2", "hobbies"}
    # The key a Turn marked is never next Turn's front while a fresh key is left (poke later).
    marked = [ij._primary_ask_target(k) for k in seen]
    assert all(m not in nxt[:1] or len(nxt) == 1 for m, nxt in zip(marked, seen[1:])), (marked, seen)
    # Nothing presented (a breather) marks nothing.
    assert ij.mark_asked({"age": 1}, ij.AskList(["age"], [AGE], False)) == {"age": 1}


def case_list_tiers_as_wcfi():
    hi = [("in", "hey how are you doing")]
    # He asked something: no ask, FAN_ASKED.
    al = ij.ask_list(LIST, {}, {}, [("in", "how about u?")], ASKING)
    assert not al.ask and al.presented == [] and al.lines, al
    assert wr._need_block(_facts(LIST, ask_list=al), True, random.Random(1)) == wr.FAN_ASKED
    # Three asking bot Turns in a row: a breather, whatever the dice.
    three = [("out", "u?"), ("in", "a b c d"), ("out", "and u?"), ("in", "a b c d"), ("out", "where?"), *hi]
    al = ij.ask_list(LIST, {}, {}, three, ASKING)
    assert not al.ask, al
    assert wr._need_block(_facts(LIST, ask_list=al), False, random.Random(1)) in _BREATHER_VARIANTS
    # Her last Turn was a breather: ask, whatever the dice.
    assert ij.ask_list(LIST, {}, {}, [("out", "lol same"), *hi], _Rng(0.0)).ask
    # Low effort (<= 3 words): ask on >= 0.6; else the tapered dice (0.33 with > 2 keys left, 0.55 at <= 2).
    assert ij.ask_list(LIST, {}, {}, [("in", "ok")], _Rng(0.6)).ask
    assert not ij.ask_list(LIST, {}, {}, [("in", "ok")], _Rng(0.59)).ask
    assert ij.ask_list(LIST, {}, {}, hi, _Rng(0.33)).ask and not ij.ask_list(LIST, {}, {}, hi, _Rng(0.32)).ask
    two = {f: "x" for f in DEFAULTS["info_fields"] if f not in ("hobbies", "fetishes")}
    assert ij.ask_list(LIST, two, {}, hi, _Rng(0.55)).ask and not ij.ask_list(LIST, two, {}, hi, _Rng(0.54)).ask


def _post(pair, n, text, info, fake_j=None):
    full = {NANO: OK_LINE, OPENROUTER: OK_LINE, ZAI: OK_LINE, DEEPSEEK: OK_LINE}
    fw = FakeWriterHTTP(full)
    with _agency_keys(_CHAIN_KEYS), _guarded(), fw.on(), _fake_jev(fake_j or FakeJev((QUIET, 1.0)), info):
        r = OWNER_A.post(TURN, json=_body(pair, n, text))
    assert r.status_code == 200, r.text
    (w,) = [x for x in fw.requests if x["host"] == NANO]
    return r.json(), w["body"]["messages"][0]["content"]


def case_list_chat_turns():
    _store_config(A, {"checkpoint": LIST})
    try:
        pair = "p-info-list"
        info = FakeInfoJev()
        got, sys_ = _post(pair, 1, "hey you, how was your day", info)
        assert got["status"] == "sent" and got["route"] == "chat", got
        assert "next_question" not in info.calls[0]["questions"], info.calls[0]["questions"]
        assert {q for q in info.calls[0]["questions"]} == set(ij.STATED)
        (row,) = _rows(A, pair)
        inf = json.loads(row.jev_json)["info"]
        assert inf["info_questions"] == "list" and inf["still_needed"] == [
            "name", "age", "location", "job", "hobbies", "boobs_ass"], inf
        assert inf["presented"] == inf["still_needed"], inf      # this Turn's seeded dice says ask
        assert wr.ASK_HEAD + "\n".join([NAME, AGE, WHERE, JOB, HOBBIES, INTO]) in sys_, sys_
        assert _reply(row)["asked"] == {"name": 1}, _reply(row)
        # A sext Turn in list mode: Nouls only, no list, nothing counted.
        info = FakeInfoJev()
        got, sys_ = _post("p-info-list-sext", 1, "fuck me", info,
                          FakeJev(({**QUIET, "sexual_now": 0.95}, 3.0)))
        assert got["route"] == "sext", got
        (row,) = _rows(A, "p-info-list-sext")
        assert "info_questions" not in json.loads(row.jev_json)["info"] and wr.ASK_HEAD not in sys_
        assert _reply(row)["asked"] == {}, _reply(row)
        # Over a session the ask count moves only on presented Turns, and never past wcfi's caps.
        pair = "p-info-list-run"
        for n in range(1, 7):
            _post(pair, n, f"hmm idk really {n}", FakeInfoJev())
        rows = _rows(A, pair)
        for prev, row in zip([{}] + [_reply(r)["asked"] for r in rows], rows):
            pres = json.loads(row.jev_json)["info"]["presented"]
            want = ij.mark_asked(prev, ij.AskList(pres, [], True)) if pres else prev
            assert _reply(row)["asked"] == want, (prev, pres, _reply(row))
        # OK_LINE ends on no "?": wcfi reads each of her Turns as a breather, so every Turn asks.
        assert all(json.loads(r.jev_json)["info"]["presented"] for r in rows)
        assert _reply(rows[-1])["asked"] == {"name": 2, "age": 2, "location": 2}, _reply(rows[-1])
    finally:
        _store_config(A, {})


def case_list_lead_in():
    """`lead_in` on in list mode: LEAD_HEAD over the LEAD_LINES lines, boobs_ass neither listed nor
    marked."""
    _store_config(A, {"checkpoint": {**DEFAULTS, "info_questions": "list"}})
    try:
        got, sys_ = _post("p-info-list-lead", 1, "hey you, how was your day", FakeInfoJev())
        assert got["status"] == "sent", got
        (row,) = _rows(A, "p-info-list-lead")
        inf = json.loads(row.jev_json)["info"]
        assert inf["still_needed"] == ["name", "age", "location", "job", "hobbies"], inf
        want = "\n".join(wr.LEAD_LINES[k] for k in ("name", "age", "location", "job", "hobbies"))
        assert wr.LEAD_HEAD + want in sys_ and INTO not in sys_ and wr.ASK_HEAD not in sys_, sys_
        assert _reply(row)["asked"] == {"name": 1}, _reply(row)
    finally:
        _store_config(A, {})


if __name__ == "__main__":
    _harness.run()
