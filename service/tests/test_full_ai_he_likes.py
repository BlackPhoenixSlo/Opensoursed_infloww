#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_sell_helpers import (  # noqa: E402
    A, IDS, NANO, OWNER_A, TURN, _body, _db, _guarded, _picks, _put_draft, _reply, _rows, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import QUIET, QUIET_TEST, FakeInfoJev, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import assistant_full_ai  # noqa: E402
import tenant_keys  # noqa: E402
from automations import _info_jev as ij  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_test as t  # noqa: E402
from automations.full_ai_config import DEFAULTS, merged, validate  # noqa: E402
from automations.full_ai_writers import likes_flag  # noqa: E402
from automations.welcome_chatter_for_info import _EXTRACT_FIELDS, _EXTRACT_SYSTEM  # noqa: E402

DEEPSEEK = "api.deepseek.com"
NO = "nothing stored yet"
SHADOW_VERSION = "14f5d4f6222f"
MAIN_INFO_VERSION = "66b043f3a87e"
LIKES_WORDING = (
    "What should she show him? First what he asks to see in `fan_new_messages`. If he names nothing "
    "specific there, go by what he is into: `he_likes`, and what he praised, asked to see or described "
    "in his own lines in `thread`. Pick anything only when none of these names one of the choices.")
EXTRACT_WORDING = (
    "For \"fetishes\" in this chat, the rule above is wider: write what turns him on as a short comma "
    "list (body parts, acts, outfits, places or scenarios), taken from what he praises, asks to see or "
    "describes doing in his own FAN: lines. Keep every item CURRENT already lists and add the new ones, "
    "newest first, at most 8 items, in his words where you can. Use \"\" only when his lines show "
    "nothing he is into. Never take an item from the YOU: lines.")



def case_flag_table():
    assert DEFAULTS["he_likes"] is True, DEFAULTS
    for ok in (True, False):
        assert validate({**DEFAULTS, "he_likes": ok}) == [], ok
    for bad in (1, "yes", None):
        assert validate({**DEFAULTS, "he_likes": bad}) == ["he_likes: must be true or false"], bad
    assert assistant_full_ai.label("he_likes") == "He likes"
    assert "he_likes" in assistant_full_ai.CONFIG_KEYS
    pre = {k: v for k, v in DEFAULTS.items() if k != "he_likes"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": pre, "rev": 3})
    assert got["checkpoint"]["he_likes"] is got["previous"]["he_likes"] is got["draft"]["he_likes"] is True, got


def case_likes_of_and_flag():
    for fan_info, want in (({}, NO), ({"fetishes": ""}, NO), ({"fetishes": "   "}, NO),
                           ({"fetishes": None}, NO), ({"fetishes": 7}, NO),
                           ({"fetishes": "  ass, feet "}, "ass, feet"),
                           ({"fetishes": "x" * 250}, "x" * 200)):
        assert t.likes_of(fan_info) == want, (fan_info, t.likes_of(fan_info))
    for mode, on, want in (("test", True, True), ("test", False, False), ("shadow", True, False),
                           ("live", True, True)):
        assert likes_flag(SimpleNamespace(mode=mode, config={"he_likes": on})) is want, (mode, on)


def _dump(q: dict) -> dict:
    return {k: v.model_dump(mode="json") for k, v in q.items()}


def case_questions():
    assert rj.TEST_LIKES["asks_subject"]["instructions"] == LIKES_WORDING
    assert rj.TEST_LIKES["asks_subject"]["criteria"] == rj.TEST_CHOICES["asks_subject"]["criteria"]
    assert rj.LIKES_STATE_KEYS == ("he_likes",)
    for scene in (False, True):
        for spacing in (False, True):
            off = rj._questions("test", scene, spacing)
            assert _dump(rj._questions("test", scene, spacing, False)) == _dump(off)
            on = rj._questions("test", scene, spacing, likes=True)
            assert list(on) == list(off), (scene, spacing)
            assert on["asks_subject"].instructions == LIKES_WORDING
            assert off["asks_subject"].instructions == rj.TEST_CHOICES["asks_subject"]["instructions"]
            assert dict(on["asks_subject"].criteria) == dict(off["asks_subject"].criteria)
            assert type(on["asks_subject"]).__name__ == "Choice"
            assert {k: v for k, v in _dump(on).items() if k != "asks_subject"} == \
                {k: v for k, v in _dump(off).items() if k != "asks_subject"}, (scene, spacing)
            assert _dump(rj._questions("shadow", scene, spacing, likes=True)) == _dump(rj._questions())
    assert rj.question_version() == rj.QUESTION_VERSION == SHADOW_VERSION
    base = rj.question_version("test")
    for name, val in (("TEST_LIKES", {"asks_subject": {**rj.TEST_LIKES["asks_subject"], "instructions": "x"}}),
                      ("LIKES_STATE_KEYS", ())):
        real = getattr(rj, name)
        setattr(rj, name, val)
        try:
            assert rj.question_version("test") != base, name
            assert rj.question_version() == SHADOW_VERSION, name
        finally:
            setattr(rj, name, real)


def case_info_versions():
    assert ij.LIKES_EXTRACT == EXTRACT_WORDING
    assert ij.INFO_VERSION == ij.info_version() == ij.info_version(False, False) == MAIN_INFO_VERSION
    assert ij.INFO_VERSION_LEAD == ij.info_version(lead=True)
    vs = {ij.INFO_VERSION, ij.INFO_VERSION_LEAD, ij.info_version(likes=True), ij.info_version(lead=True, likes=True)}
    assert len(vs) == 4, vs
    before, real = ij.info_version(likes=True), ij.LIKES_EXTRACT
    ij.LIKES_EXTRACT = "x"
    try:
        assert ij.info_version(likes=True) != before
        assert ij.info_version() == MAIN_INFO_VERSION
    finally:
        ij.LIKES_EXTRACT = real


def case_wording_in_catalog():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[2] / "docs" / "prompts" / "new" / "current-repo.md").read_text(encoding="utf-8")
    assert "### NEW-144 " in doc and ij.LIKES_EXTRACT in doc and LIKES_WORDING in doc



@contextlib.contextmanager
def _deepseek_key():
    owner = IDS["agency_a_owner"]
    before = _db(lambda: tenant_keys.get_key(owner, "deepseek"))
    _db(lambda: tenant_keys.set_keys(owner, {"deepseek": "test-deepseek-agency-key"}))
    try:
        yield
    finally:
        _db(lambda: tenant_keys.set_keys(owner, {"deepseek": before}))


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


def _extract_says(**vals) -> str:
    return "ok:" + json.dumps({**dict.fromkeys(_EXTRACT_FIELDS, ""), "likes_boobs": False,
                               "likes_ass": False, "recent_events": [], "her_claims": [], **vals})


def _turn(pair: str, n: int, text: str, info: FakeInfoJev, extract: str | None = None,
          jev=(QUIET, 1.0)):
    fj = FakeJev(jev)
    fw = FakeWriterHTTP({NANO: "ok:mm babe", DEEPSEEK: extract or "ok:{}"})
    with _deepseek_key(), _guarded(), fw.on(), _fake_jev(fj, info):
        r = OWNER_A.post(TURN, json=_body(pair, text, n=n))
    assert r.status_code == 200, r.text
    (call,) = fj.calls
    ex = [x for x in fw.requests if x["host"] == DEEPSEEK]
    assert len(ex) == (1 if extract else 0), fw.requests
    return r.json(), call, (ex[0] if ex else None), _rows(pair)[n - 1]


def _saved(row) -> dict:
    return json.loads(row.jev_json)


def case_extract_to_next_turn():
    pair = "hl-on"
    with _draft():
        g, call, ex, row = _turn(pair, 1, "mm i love ur ass and feet", FakeInfoJev(({"fetishes": .9}, "none")),
                                 _extract_says(fetishes="ass, feet"))
    assert call["state"]["he_likes"] == NO and _saved(row)["state"]["he_likes"] == NO, call["state"]
    assert call["questions"]["asks_subject"].instructions == LIKES_WORDING
    msgs = ex["body"]["messages"]
    assert [m["role"] for m in msgs] == ["system", "system", "user"], msgs
    assert msgs[0]["content"] == _EXTRACT_SYSTEM and msgs[1]["content"] == ij.LIKES_EXTRACT, msgs
    assert "FAN: mm i love ur ass and feet" in msgs[2]["content"], msgs[2]
    assert g["fan_info"] == {"fetishes": "ass, feet"} == _reply(row)["fan_info"], (g, _reply(row))
    assert _saved(row)["info_version"] == ij.info_version(lead=True, likes=True, wide=True), row.jev_json
    with _draft():
        _, call, _, row = _turn(pair, 2, "send me pics", FakeInfoJev())
    assert call["state"]["he_likes"] == "ass, feet" == _saved(row)["state"]["he_likes"], call["state"]
    assert list(call["state"])[-1] == "he_likes", list(call["state"])
    with _draft():
        _, _, ex, row = _turn(pair, 3, "im 31", FakeInfoJev(({"his_age": .9}, "none")), _extract_says(his_age="31"))
    assert [m["role"] for m in ex["body"]["messages"]] == ["system", "user"], ex["body"]["messages"]
    assert _reply(row)["fan_info"] == {"fetishes": "ass, feet", "his_age": "31"}, _reply(row)


def case_switch_off():
    pair = "hl-off"
    with _draft(he_likes=False, info_wide=False):
        _, call, ex, row = _turn(pair, 1, "mm i love ur ass", FakeInfoJev(({"fetishes": .9}, "none")),
                                 _extract_says(fetishes="ass"))
    assert "he_likes" not in call["state"] and "he_likes" not in _saved(row)["state"], call["state"]
    assert call["questions"]["asks_subject"].instructions == rj.TEST_CHOICES["asks_subject"]["instructions"]
    msgs = ex["body"]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"] and msgs[0]["content"] == _EXTRACT_SYSTEM, msgs
    assert ij.LIKES_EXTRACT not in json.dumps(msgs)
    assert _saved(row)["info_version"] == ij.INFO_VERSION_LEAD, row.jev_json
    with _draft(he_likes=False, info_wide=False):
        _, call, _, _ = _turn(pair, 2, "send me pics", FakeInfoJev())
    assert "he_likes" not in call["state"], call["state"]


BUTT = {"butt_focus": "y"}


def case_generic_ask_sells_butt():
    pair = "hl-butt"
    with _draft(sell_on=True, sext_scene=False), _vault({101: "$10"}), _vault({201: "$10", 202: "$10"}, tags=BUTT):
        _turn(pair, 1, "mm i love ur ass", FakeInfoJev(({"fetishes": .9}, "none")), _extract_says(fetishes="ass"))
        with _picks() as picks:
            g, call, _, row = _turn(pair, 2, "send me pics of you", FakeInfoJev(),
                                    jev=({**QUIET_TEST, "wants_content": .9}, 2.0, {"asks_subject": "butt"}))
    assert call["state"]["he_likes"] == "ass", call["state"]
    assert (row.route, row.route_row) == ("sell_now", "sell"), (row.route, row.route_row)
    (pick,) = picks
    assert pick.media and set(pick.media) <= {201, 202}, pick
    assert json.loads(row.offer_item_ref)["subject"] == "butt", row.offer_item_ref
    assert g["offer"] and row.offer_price_cents, g


_harness.run()
