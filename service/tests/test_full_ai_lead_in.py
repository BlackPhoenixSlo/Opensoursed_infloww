#!/usr/bin/env python3
"""test_full_ai_lead_in — Full AI lead-in asks (config `lead_in`, test Mode), pure, plain assert.

  case_flag_off_snapshot      flag off (and Shadow with it on): 18 chat prompts byte-identical to
                              origin/main's builder
  case_lead_lines_table       Jev's pick -> LEAD_HEAD + its LEAD_LINES line ({city} / {country}
                              filled), no wcfi ask line, SELF_GIVE for SELF_BAN
  case_fetishes_never_led     a fetishes pick asks nothing; every other fact known -> know enough
  case_lead_examples_table    the "- GOOD:" line: <=2 wcfi riffs then <=2 leads; empty fallback
  case_scene_turn_unchanged   a scene Turn's prompt is the same with the flag on or off
  case_style_draw             the lead draw never returns wcfi's "straight to your next question"
  case_info_jev_wording       the lead flag picks NEXT_QUESTION_LEAD; her_last_line in the state;
                              only the lead wording moves the digest
  case_config_key             `lead_in` default on, bool-checked, labelled
  case_constants_in_catalog   every new constant is in docs/prompts/new/current-repo.md

Run: ./venv/bin/python service/tests/test_full_ai_lead_in.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import hashlib  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from automations import _info_jev as ij  # noqa: E402
from automations import full_ai_writers as wr  # noqa: E402
from automations.full_ai_config import DEFAULTS, validate  # noqa: E402

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "prompts"
# `_info_jev.INFO_VERSION` on origin/main (dacd91707): the flag-off / Shadow digest must not move.
MAIN_INFO_VERSION = "66b043f3a87e"
# sha256 of `_snapshot(lead_in=False)` as origin/main (dacd91707) built it.
FLAG_OFF_SHA = "9d937ec8d923c0037057adca5decf680e89252aef34d8ec5df758ef9fbad85eb"


def _row(d, t, mid):
    return SimpleNamespace(direction=d, body=t, created_at=None, message_id=mid, automation_kind=None,
                           media_count=0, raw_json=None, price_cents=None, is_paid=False, purchased_at=None)


def _turn(text="hey you", *, fan_info=None, nq=None, al=None, mode="test", key="test:s:1", **cfg):
    return SimpleNamespace(account_id="acct_lead", anchor_key=key, config={**DEFAULTS, **cfg},
                           fan_info=dict(fan_info or {}), next_question=nq, ask_list=al, spent=[],
                           offer_piece=None, mode=mode,
                           cut_rows=[_row("out", "hii", 1), _row("in", text, 2)])


def _sys(route="chat", row="otherwise", **kw) -> str:
    return wr.messages_for(route, row, 2, _turn(**kw), None)[0]["content"]


_FANS = ({}, {"his_age": "31", "occupation": "chef"}, {"home_city": "Madrid", "hobbies": "surfing"},
         {"home_country": "Spain", "real_name": "Sam"})


def _snapshot(**cfg) -> list:
    """18 prompts: chat over four folds x (no pick, a pick) x two anchors, plus sext and
    make_right."""
    out = []
    for fi in _FANS:
        for nq in (None, ij.missing(DEFAULTS, fi)[0]):
            for key in ("test:s:1", "test:s:7"):
                out.append(wr.messages_for("chat", "otherwise", 2, _turn(fan_info=fi, nq=nq, key=key, **cfg), None))
    for route, row in (("sext", "sexual_now"), ("make_right", "complains_now")):
        out.append(wr.messages_for(route, row, 3, _turn("this sucks", **cfg), None))
    return out


def _sha(prompts) -> str:
    return hashlib.sha256(json.dumps(prompts, sort_keys=True).encode()).hexdigest()


def case_flag_off_snapshot():
    # Selling off in test Mode puts SELL_OFF_LINE in NO_SELL_OFFERS' place (sell_nearest PR); put
    # back, the snapshot is byte-identical to the pinned one.
    snap = json.loads(json.dumps(_snapshot(lead_in=False)).replace(
        json.dumps(wr.SELL_OFF_LINE)[1:-1], json.dumps(wr.NO_SELL_OFFERS)[1:-1]))
    assert _sha(snap) == FLAG_OFF_SHA
    # Shadow never leads, flag on or off.
    shadow = []
    for fi in _FANS:
        for nq in (None, ij.missing(DEFAULTS, fi)[0]):
            for key in ("test:s:1", "test:s:7"):
                shadow.append(wr.messages_for("chat", "otherwise", 2,
                                              _turn(fan_info=fi, nq=nq, key=key, mode="shadow"), None))
    assert shadow == snap[:16]                     # Shadow keeps NO_SELL_OFFERS, byte-identical
    assert _snapshot(lead_in=True) != _snapshot(lead_in=False)


def case_lead_lines_table():
    table = [
        ({}, "real_name", "name", "- His name. This one you can just ask, light: what should you call him."),
        ({}, "his_age", "age", wr.LEAD_LINES["age"]),
        ({}, "home_city", "location", wr.LEAD_LINES["location"]),
        ({}, "occupation", "job", wr.LEAD_LINES["job"]),
        ({}, "hobbies", "hobbies", wr.LEAD_LINES["hobbies"]),
        ({"home_city": "Madrid"}, "home_country", "country_from_city",
         "- He mentioned Madrid. Guess the country out loud so he confirms it."),
        ({"home_country": "Spain"}, "home_city", "city",
         "- He's in Spain. Say you've always wanted to see it and wonder which part he's in."),
    ]
    for fi, nq, key, line in table:
        assert ij.question_key(nq, fi) == key, (nq, fi)
        s = _sys(fan_info=fi, nq=nq)
        assert wr.LEAD_HEAD + line in s, (nq, s)
        assert wr.ASK_HEAD not in s and "You DON'T know" not in s and ij.question_line(nq, fi) not in s, nq
        assert wr.SELF_GIVE in s and wr.SELF_BAN not in s, nq
    # No pick: no lead head, SELF_GIVE still there.
    s = _sys()
    assert wr.LEAD_HEAD not in s and wr.SELF_GIVE in s, s


def case_fetishes_never_led():
    s = _sys(nq="fetishes")
    assert wr.LEAD_HEAD not in s and wr.ASK_HEAD not in s, s
    assert "boobs/ass" not in s, s
    known = dict(real_name="Sam", his_age="31", home_country="Spain", home_city="Madrid",
                 hobbies="surfing", occupation="chef")
    assert wr.KNOW_ENOUGH in _sys(fan_info=known), "fetishes empty must not block know-enough"
    assert wr.KNOW_ENOUGH not in _sys(fan_info=known, lead_in=False)    # flag off: still waits
    for fi, lead, want in ((known, True, []), (known, False, ["fetishes"]),
                           ({}, True, [f for f in DEFAULTS["info_fields"] if f != "fetishes"])):
        assert ij.askable(DEFAULTS, fi, lead) == want, (fi, lead)


def case_lead_examples_table():
    table = [
        (dict(), False, '- GOOD: "haha thanks what should i call u?" / "u sound like trouble.. let me guess, 25?"\n'),
        (dict(real_name="Sam"), True,
         '- GOOD: "u sound like trouble.. let me guess, 25?" / "shouldnt u be working rn or are u the boss"\n'),
        (dict(real_name="Sam", occupation="chef", home_city="Madrid"), True,
         '- GOOD: "a chef? bet u cook fire, fave dish?" / "Madrid? ive always wanted to go there" / '
         '"u sound like trouble.. let me guess, 25?" / "its so late here.. what time is it for u"\n'),
        (dict(real_name="Sam", his_age="31", occupation="chef", home_city="Madrid", home_country="Spain"), True,
         '- GOOD: "a chef? bet u cook fire, fave dish?" / "Madrid? ive always wanted to go there"\n'),
        (dict(real_name="Sam", his_age="31", occupation="nurse", home_country="Spain"), True,
         '- GOOD: "a nurse? bet u take good care of everyone" / "31 and still trouble huh" / '
         '"its so late here.. what time is it for u"\n'),
    ]
    for fi, durable, want in table:
        assert wr.lead_examples(wr._fan(fi), durable) == want, (fi, wr.lead_examples(wr._fan(fi), durable))
    # wcfi's empty fallback stays its own; a fan with no facts still gets leads, not it.
    empty = SimpleNamespace(**{k: None for k in wr._FAN_FIELDS})
    fallback = wr._good_examples(empty, set(wr._ALL_ASKED), True)
    assert fallback.startswith('- GOOD: "mmm tell me more"'), fallback
    assert "what should i call u" not in wr.lead_examples(empty, True)


def case_scene_turn_unchanged():
    for stage in wr.SCENE_STAGE:
        on, off = (wr.messages_for("sext", "scene_on", 3, _turn("im so hard", lead_in=lead), None,
                                   hot=True, scene=stage, gif_ok=False) for lead in (True, False))
        assert on == off, stage
        assert wr.SCENE_SELF in on[0]["content"] and wr.SELF_GIVE not in on[0]["content"]


def case_style_draw():
    assert wr.NEXT_QUESTION_STYLE not in wr.LEAD_STYLE_VARIANTS
    assert len(wr.LEAD_STYLE_VARIANTS) == len(wr._STYLE_VARIANTS) - 1
    hit_off = False
    for n in range(200):
        assert wr.NEXT_QUESTION_STYLE not in _sys(key=f"test:s:{n}"), n
        hit_off |= wr.NEXT_QUESTION_STYLE in _sys(key=f"test:s:{n}", lead_in=False)
    assert hit_off, "flag off still draws it"


def case_info_jev_wording():
    from typesafe_sdk import Choice  # noqa: F401  (the SDK builds the Choice)
    off, on = ij._questions(["his_age"]), ij._questions(["his_age"], lead=True)
    assert off["next_question"].instructions == ij.NEXT_QUESTION["instructions"]
    assert on["next_question"].instructions == ij.NEXT_QUESTION_LEAD["instructions"]
    assert on["next_question"].criteria == off["next_question"].criteria
    assert ij.NEXT_QUESTION_LEAD["criteria"] == ij.NEXT_QUESTION["criteria"]
    st = ij.state({"fan_new_messages": ["hi"], "thread": [], "her_last_line": "how r u?"}, {}, [])
    assert st["her_last_line"] == "how r u?", st
    assert ij.INFO_VERSION == ij.info_version() == MAIN_INFO_VERSION
    assert ij.INFO_VERSION_LEAD == ij.info_version(lead=True) != MAIN_INFO_VERSION


def case_config_key():
    from assistant_full_ai import label
    assert DEFAULTS["lead_in"] is True
    assert validate({**DEFAULTS, "lead_in": False}) == []
    assert validate({**DEFAULTS, "lead_in": "yes"}) == ["lead_in: must be true or false"]
    assert label("lead_in") == "Lead-in asks"


def case_constants_in_catalog():
    new = " ".join((_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8").split())
    for c in (wr.LEAD_HEAD.strip(), *wr.LEAD_LINES.values(), *wr.LEAD_EXAMPLES.values(), wr.SELF_GIVE.strip(),
              ij.NEXT_QUESTION_LEAD["instructions"]):
        assert " ".join(c.split()) in new, c[:60]


_harness.run()
