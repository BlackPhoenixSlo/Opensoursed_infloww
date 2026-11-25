#!/usr/bin/env python3
from __future__ import annotations

import _harness

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
from automations.welcome_chatter_for_info import _BREATHER_VARIANTS, _primary_ask_target

LIST = {**DEFAULTS, "info_questions": "list", "lead_in": False}
NAME = "- You DON'T know his real name yet. Ask what his name is / what you should call him."
AGE = "- You DON'T know his age yet. Find out how old he is."
WHERE = "- You DON'T know where he lives. Ask where he's from."
JOB = "- You DON'T know what he does for work. Ask what he does for a living."
HOBBIES = "- You DON'T know his hobbies yet. Ask what he likes to do."
INTO = "- You DON'T know what he's into (boobs/ass). Ask playfully."


def _ids(keys, lines) -> str:
    return "\n".join(f"[{k}] {x}" for k, x in zip(keys, lines))


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

    def __init__(self, x):
        self.x = x

    def random(self):
        return self.x


ASKING = _Rng(0.99)


def case_config_key():
    assert DEFAULTS["info_questions"] == "pick", DEFAULTS
    assert validate(LIST) == [] and validate(DEFAULTS) == []
    assert validate({**DEFAULTS, "info_questions": "all"}) == ["info_questions: must be one of pick, list"]


def case_pick_mode_prompt_unchanged():
    old = _facts(DEFAULTS)
    del old.ask_list
    for route in ("chat", "sext", "ai_dare", "make_right"):
        assert _sys(_facts(DEFAULTS), route) == _sys(old, route), route
        assert _sys(_facts(LIST), route) == _sys(old, route), route


def case_list_lines_are_wcfi_lines():
    al = ij.ask_list(LIST, {}, {}, [("in", "hey you how was your day")], ASKING)
    assert al.keys == ["name", "age", "location", "job", "hobbies", "boobs_ass"], al
    assert al.lines == [NAME, AGE, WHERE, JOB, HOBBIES, INTO] and al.ask and al.presented == al.keys
    need = wr.ASK_HEAD + _ids(al.keys, [NAME, AGE, WHERE, JOB, HOBBIES, INTO])
    block = wr._need_block(_facts(LIST, ask_list=al), False, random.Random(1))
    assert block == wr.Need(need, tuple(al.keys)), block
    assert need in _sys(_facts(LIST, ask_list=al))


def case_list_shrinks_and_info_fields():
    keys = lambda cfg, fi: [k for k, _ in ij.still_needed(cfg, fi, {})]   # noqa: E731
    assert keys(LIST, {"real_name": "Sam", "occupation": "chef"}) == ["age", "location", "hobbies", "boobs_ass"]
    assert keys(LIST, {"home_city": "Leeds"}) == ["name", "age", "country_from_city", "job", "hobbies", "boobs_ass"]
    assert ij.still_needed(LIST, {"home_country": "UK"}, {})[2] == (
        "city", "- You know he's from UK but not which city/area. Ask what part.")
    assert keys(LIST, {"fetishes": "feet"})[-1] == "hobbies"
    cfg = {**LIST, "info_fields": ["real_name", "home_city", "hobbies"]}
    assert keys(cfg, {}) == ["name", "location", "hobbies"], keys(cfg, {})
    assert keys({**LIST, "info_fields": ["home_country"]}, {"home_country": "UK"}) == []
    full = {f: "x" for f in DEFAULTS["info_fields"]}
    al = ij.ask_list(LIST, full, {}, [("in", "hi there you")], ASKING)
    assert al == ij.AskList([], [], False), al
    assert wr._need_block(_facts(LIST, full, al), False, random.Random(1)) == wr.Need(wr.KNOW_ENOUGH)


def case_list_never_nags():
    asked, seen = {}, []
    for _ in range(12):
        al = ij.ask_list(LIST, {}, asked, [("in", "hmm idk really man")], ASKING)
        if not al.lines:
            break
        seen.append(al.keys)
        k = _primary_ask_target(al.presented)
        asked = {**asked, k: asked.get(k, 0) + 1}
    assert seen == [
        ["name", "age", "location", "job", "hobbies", "boobs_ass"],
        ["age", "location", "job", "hobbies", "boobs_ass", "name"],
        ["age", "location", "job", "hobbies", "boobs_ass"],
        ["location", "job", "hobbies", "boobs_ass", "age"],
        ["location", "job", "hobbies", "boobs_ass"],
        ["job", "hobbies", "boobs_ass", "location"],
        ["job", "hobbies", "boobs_ass"],
        ["hobbies", "boobs_ass", "job"],
        ["hobbies", "boobs_ass"],
        ["boobs_ass"],
    ], seen
    assert asked == {"name": 2, "age": 2, "location": 2, "job": 2, "hobbies": 1, "boobs_ass": 1}, asked
    assert ij.asked_marks({"name": 2, "hobbies": 1, "age": 0}) == {"name", "name:2", "hobbies"}
    marked = [_primary_ask_target(k) for k in seen]
    assert all(m not in nxt[:1] or len(nxt) == 1 for m, nxt in zip(marked, seen[1:])), (marked, seen)


def case_list_tiers_as_wcfi():
    hi = [("in", "hey how are you doing")]
    al = ij.ask_list(LIST, {}, {}, [("in", "how about u?")], ASKING)
    assert not al.ask and al.presented == [] and al.lines, al
    assert wr._need_block(_facts(LIST, ask_list=al), True, random.Random(1)) == wr.Need(wr.FAN_ASKED)
    three = [("out", "u?"), ("in", "a b c d"), ("out", "and u?"), ("in", "a b c d"), ("out", "where?"), *hi]
    al = ij.ask_list(LIST, {}, {}, three, ASKING)
    assert not al.ask, al
    assert wr._need_block(_facts(LIST, ask_list=al), False, random.Random(1)).text in _BREATHER_VARIANTS
    assert ij.ask_list(LIST, {}, {}, [("out", "lol same"), *hi], _Rng(0.0)).ask
    assert ij.ask_list(LIST, {}, {}, [("in", "ok")], _Rng(0.6)).ask
    assert not ij.ask_list(LIST, {}, {}, [("in", "ok")], _Rng(0.59)).ask
    assert ij.ask_list(LIST, {}, {}, hi, _Rng(0.33)).ask and not ij.ask_list(LIST, {}, {}, hi, _Rng(0.32)).ask
    two = {f: "x" for f in DEFAULTS["info_fields"] if f not in ("hobbies", "fetishes")}
    assert ij.ask_list(LIST, two, {}, hi, _Rng(0.55)).ask and not ij.ask_list(LIST, two, {}, hi, _Rng(0.54)).ask


def _post(pair, n, text, info, fake_j=None, nano=OK_LINE):
    full = {NANO: nano, OPENROUTER: OK_LINE, ZAI: OK_LINE, DEEPSEEK: OK_LINE}
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
        got, sys_ = _post(pair, 1, "hey you, how was your day", info, nano=OK_LINE + "\nASKED: age")
        assert got["status"] == "sent" and got["route"] == "chat", got
        assert "next_question" not in info.calls[0]["questions"], info.calls[0]["questions"]
        assert {q for q in info.calls[0]["questions"]} == set(ij.STATED)
        (row,) = _rows(A, pair)
        inf = json.loads(row.jev_json)["info"]
        assert inf["info_questions"] == "list" and inf["still_needed"] == [
            "name", "age", "location", "job", "hobbies", "boobs_ass"], inf
        assert inf["presented"] == inf["still_needed"], inf
        assert wr.ASK_HEAD + _ids(inf["presented"], [NAME, AGE, WHERE, JOB, HOBBIES, INTO]) in sys_, sys_
        assert _reply(row)["asked"] == {"age": 1}, _reply(row)
        info = FakeInfoJev()
        got, sys_ = _post("p-info-list-sext", 1, "fuck me", info,
                          FakeJev(({**QUIET, "sexual_now": 0.95}, 3.0)))
        assert got["route"] == "sext", got
        (row,) = _rows(A, "p-info-list-sext")
        assert "info_questions" not in json.loads(row.jev_json)["info"] and wr.ASK_HEAD not in sys_
        assert _reply(row)["asked"] == {}, _reply(row)
        pair = "p-info-list-run"
        marks = ["hobbies", None, "city", "hobbies", "job", None]
        for n, k in enumerate(marks, start=1):
            _post(pair, n, f"hmm idk really {n}", FakeInfoJev(),
                  nano=OK_LINE + (f"\nASKED: {k}" if k else ""))
        rows = _rows(A, pair)
        for prev, row, k in zip([{}] + [_reply(r)["asked"] for r in rows], rows, marks):
            pres = json.loads(row.jev_json)["info"]["presented"]
            want = {**prev, k: prev.get(k, 0) + 1} if k in pres else prev
            assert _reply(row)["asked"] == want, (prev, pres, _reply(row))
            assert _reply(row)["asked_marker"] == k, _reply(row)
        assert "hobbies" not in json.loads(rows[3].jev_json)["info"]["presented"], rows[3].jev_json
        assert all(json.loads(r.jev_json)["info"]["presented"] for r in rows)
        assert _reply(rows[-1])["asked"] == {"hobbies": 1, "job": 1}, _reply(rows[-1])
    finally:
        _store_config(A, {})


def case_list_lead_in():
    _store_config(A, {"checkpoint": {**DEFAULTS, "info_questions": "list"}})
    try:
        got, sys_ = _post("p-info-list-lead", 1, "hey you, how was your day", FakeInfoJev(),
                          nano=OK_LINE + "\nASKED: name")
        assert got["status"] == "sent", got
        (row,) = _rows(A, "p-info-list-lead")
        inf = json.loads(row.jev_json)["info"]
        assert inf["still_needed"] == ["name", "age", "location", "job", "hobbies"], inf
        lead = ("name", "age", "location", "job", "hobbies")
        want = _ids(lead, [wr.LEAD_LINES[k] for k in lead])
        assert wr.LEAD_HEAD + want in sys_ and INTO not in sys_ and wr.ASK_HEAD not in sys_, sys_
        assert _reply(row)["asked"] == {"name": 1}, _reply(row)
    finally:
        _store_config(A, {})
    assert ij.NEVER_LED_KEYS == {"boobs_ass"}, ij.NEVER_LED_KEYS
    assert ij._KEY_FIELDS["location"] == ("home_country", "home_city"), ij._KEY_FIELDS
    assert "recent_events" not in ij._KEY_FIELDS
    al = ij.unled(ij.AskList(["boobs_ass"], ["x"], True))
    assert al == ij.AskList([], [], False), al


if __name__ == "__main__":
    _harness.run()
