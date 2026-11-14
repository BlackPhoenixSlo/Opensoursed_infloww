#!/usr/bin/env python3
"""test_full_ai_config — Full AI Chat's config: pure tables and the config API (phase 03a).

  case_turn_bound_s_table   20 + (1 + len(writers)) x writer_timeout_s: defaults -> 145,
                            one Writer at 5 s -> 30 (spec › Contracts › One Turn bound)
  case_validate_table       (ticket 37) every refusal the spec names, one key changed each row;
                            DEFAULTS passes
  case_merged_fills_a_later_key  a stored side missing a later key takes it from DEFAULTS
  case_folders_table        (ticket 43) `folders` refs validated by name, default all, a stored
                            v1 without `folders` reads all, unknown key still refused
  case_draft_questions_table (ticket 47) `draft_questions` a bool, default false; a stored v1
                            without it reads false on every side
  case_transitions_and_stale_rev put_draft / save / rollback, StaleRev on a rev mismatch,
                            Invalid on a bad draft, nothing to save, nothing to roll back to
  case_config_api_round_trip GET defaults, PUT 422 / 409 / 200, save, roll back twice = identity;
                            the `full_ai_chat` rule row byte-identical throughout

Run: ./venv/bin/python service/tests/test_full_ai_config.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402

from sqlalchemy import text  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from automations.full_ai_config import (  # noqa: E402
    DEFAULTS, WRITER_PROVIDERS, Invalid, StaleRev, merged, put_draft, rollback, save, turn_bound_s,
    validate,
)
from db.engine import get_session  # noqa: E402
from db.models import AutomationRule  # noqa: E402
from llm_models import MODELS  # noqa: E402


def case_turn_bound_s_table():
    table = [
        (DEFAULTS, 145),
        ({**DEFAULTS, "writers": ["deepseek-v4-flash"], "writer_timeout_s": 5}, 30),
        ({**DEFAULTS, "writers": ["euryale-v2.3", "hermes-4-405b"], "writer_timeout_s": 60}, 200),
    ]
    for cfg, want in table:
        assert turn_bound_s(cfg) == want, (cfg["writers"], cfg["writer_timeout_s"], turn_bound_s(cfg))


# ── validate ──────────────────────────────────────────────────────────

def case_validate_table():
    assert validate(DEFAULTS) == [], validate(DEFAULTS)
    assert {MODELS[w].provider for w in DEFAULTS["writers"]} <= WRITER_PROVIDERS
    assert validate({}) == [], validate({})          # a missing key is its default
    refused = [  # (change, the field its one error names)
        ({"writers": ["gpt-9"]}, "writers"),                                  # unknown model
        ({"writers": ["qwen3-vl-30b"]}, "writers"),                           # provider mismatch
        ({"writers": ["euryale-v2.3", "claude-haiku-5-5"]}, "writers"),       # provider mismatch
        ({"writers": []}, "writers"),
        ({"writers": ["euryale-v2.3", "hermes-4-405b", "glm-5.3-flash", "deepseek-v4-flash",
                      "deepseek-v4-pro"]}, "writers"),                        # five
        ({"writers": ["euryale-v2.3", "euryale-v2.3"]}, "writers"),           # repeated
        ({"writers": "euryale-v2.3"}, "writers"),
        ({"writer_timeout_s": 4}, "writer_timeout_s"),
        ({"writer_timeout_s": 61}, "writer_timeout_s"),
        ({"writer_timeout_s": True}, "writer_timeout_s"),
        ({"writer_timeout_s": "25"}, "writer_timeout_s"),
        ({"sell_on": "yes"}, "sell_on"),                                     # 03b: settable, a bool
        ({"sell_on": 1}, "sell_on"),
        ({"fans_list": []}, "fans_list"),
        ({"reserved": {}}, "reserved"),
        ({"nanogpt_api_key": "sk-x"}, "nanogpt_api_key"),                     # a key never lands here
        ({"reply_by_webhook": "yes"}, "reply_by_webhook"),
        ({"typing_sign": 1}, "typing_sign"),
        ({"typing_notification": None}, "typing_notification"),
        ({"gifs": 0}, "gifs"),
        ({"reply_speed": "fast"}, "reply_speed"),
        ({"text_style": "boy"}, "text_style"),
        ({"version": 2}, "version"),
        ({"info_fields": ["shoe_size"]}, "info_fields"),
    ]
    for change, field in refused:
        errs = validate({**DEFAULTS, **change})
        assert len(errs) == 1 and errs[0].startswith(f"{field}: "), (change, errs)
    assert validate([]) and validate(None), "not an object"
    for ok in ({"writers": ["deepseek-v4-flash"]}, {"writer_timeout_s": 5}, {"writer_timeout_s": 60},
               {"writers": ["hermes-4-405b", "euryale-v2.3"]}, {"reply_speed": "0-15-60"},
               {"text_style": "formal"}, {"gifs": True}, {"info_fields": []}, {"sell_on": True}):
        assert validate({**DEFAULTS, **ok}) == [], (ok, validate({**DEFAULTS, **ok}))


def case_merged_fills_a_later_key():
    old = {k: v for k, v in DEFAULTS.items() if k != "typing_notification"}
    got = merged({"checkpoint": {**old, "gifs": True}, "previous": old,
                  "draft": {**old, "text_style": "formal"}, "rev": 4})
    assert got["checkpoint"] == {**DEFAULTS, "gifs": True}, got["checkpoint"]
    assert got["previous"] == DEFAULTS, got["previous"]
    assert got["draft"] == {**DEFAULTS, "text_style": "formal"}, got["draft"]
    assert got["rev"] == 4
    assert merged(None) == {"checkpoint": DEFAULTS, "previous": None, "draft": DEFAULTS, "rev": 0}
    # A stored v1 config from before 03b (no `sell_on`) reads selling off.
    pre = {k: v for k, v in DEFAULTS.items() if k != "sell_on"}
    assert merged({"checkpoint": pre, "draft": pre, "rev": 1})["draft"]["sell_on"] is False


def case_folders_table():
    """(ticket 43) `folders: {include, exclude}`: refs `vf:<id>` / `of:<id>`; a malformed ref is
    refused by name; the default is empty = all folders; a stored v1 without `folders` reads all."""
    assert DEFAULTS["folders"] == {"include": [], "exclude": []}, DEFAULTS["folders"]
    for ok in ({"include": [], "exclude": []}, {"include": ["vf:12"], "exclude": []},
               {"include": ["vf:1", "of:987654321"], "exclude": ["vf:2"]},
               {"include": [], "exclude": ["of:5"]}):
        assert validate({**DEFAULTS, "folders": ok}) == [], (ok, validate({**DEFAULTS, "folders": ok}))
    refused = [  # (folders, a word the one error must carry: the bad ref or key by name)
        ({"include": ["vf:abc"], "exclude": []}, "'vf:abc'"),
        ({"include": ["vf:"], "exclude": []}, "'vf:'"),
        ({"include": ["12"], "exclude": []}, "'12'"),
        ({"include": ["xx:12"], "exclude": []}, "'xx:12'"),
        ({"include": [], "exclude": ["of:-3"]}, "'of:-3'"),
        ({"include": [], "exclude": ["vf:1 "]}, "'vf:1 '"),
        ({"include": [12], "exclude": []}, "12"),
        ({"include": "vf:1", "exclude": []}, "include"),
        ({"include": [], "exclude": None}, "exclude"),
        ({"include": [], "exclude": [], "only": ["vf:1"]}, "'only'"),
        ({"include": ["vf:3"]}, "['include']"),
        ({}, "got []"),
        (["vf:1"], "object"),
        (None, "object"),
    ]
    for folders, word in refused:
        errs = validate({**DEFAULTS, "folders": folders})
        assert len(errs) == 1 and errs[0].startswith("folders: ") and word in errs[0], (folders, errs)
    # Stored v1 from before 03b (no `folders`): both sides read all folders; unknown keys still refused.
    pre = {k: v for k, v in DEFAULTS.items() if k != "folders"}
    got = merged({"checkpoint": pre, "draft": {**pre, "sell_on": True}, "rev": 2})
    assert got["checkpoint"]["folders"] == got["draft"]["folders"] == {"include": [], "exclude": []}, got
    assert validate({**DEFAULTS, "fans_list": []}) == ["fans_list: unknown key"]
    # A draft PUT stores the side's folders as given, read per side.
    s = put_draft(None, {**DEFAULTS, "folders": {"include": ["vf:7"], "exclude": ["of:9"]}}, 0)
    assert s["draft"]["folders"] == {"include": ["vf:7"], "exclude": ["of:9"]}, s["draft"]
    assert s["checkpoint"]["folders"] == {"include": [], "exclude": []}, s["checkpoint"]
    assert _raises(Invalid, put_draft, None, {**DEFAULTS, "folders": {"include": ["vf:x"], "exclude": []}}, 0).errors == [
        "folders: bad ref 'vf:x' in include (want vf:<id> or of:<id>)"]


def case_draft_questions_table():
    """(ticket 47) `draft_questions`: the DRAFT gate's config half, a bool, off by default."""
    assert DEFAULTS["draft_questions"] is False, DEFAULTS
    for ok in (True, False):
        assert validate({**DEFAULTS, "draft_questions": ok}) == [], ok
    for bad in ("yes", 1, 0, None, "true"):
        assert validate({**DEFAULTS, "draft_questions": bad}) == ["draft_questions: must be true or false"], bad
    # Stored v1 from before ticket 47 (no `draft_questions`): every side reads false.
    pre = {k: v for k, v in DEFAULTS.items() if k != "draft_questions"}
    got = merged({"checkpoint": pre, "previous": pre, "draft": {**pre, "sell_on": True}, "rev": 2})
    assert got["checkpoint"]["draft_questions"] is got["previous"]["draft_questions"] is False, got
    assert got["draft"]["draft_questions"] is False and got["draft"]["sell_on"] is True, got["draft"]
    # A draft PUT stores it per side.
    s = put_draft(None, {**DEFAULTS, "draft_questions": True}, 0)
    assert (s["draft"]["draft_questions"], s["checkpoint"]["draft_questions"]) == (True, False), s


# ── Transitions ───────────────────────────────────────────────────────

def _raises(exc, fn, *a):
    try:
        fn(*a)
    except exc as e:
        return e
    raise AssertionError(f"{fn.__name__}{a!r} did not raise {exc.__name__}")


def case_transitions_and_stale_rev():
    formal = {**DEFAULTS, "text_style": "formal"}
    s1 = put_draft(None, formal, 0)
    assert s1 == {"checkpoint": DEFAULTS, "previous": None, "draft": formal, "rev": 1}, s1
    # A partial draft is stored filled from DEFAULTS.
    assert put_draft(None, {"gifs": True}, 0)["draft"] == {**DEFAULTS, "gifs": True}
    assert _raises(StaleRev, put_draft, s1, DEFAULTS, 0).rev == 1
    assert _raises(Invalid, put_draft, s1, {**DEFAULTS, "sell_on": "yes"}, 1).errors == [
        "sell_on: must be true or false"]
    # 03b: selling is settable on the draft alone; the checkpoint keeps its own (off) value.
    sold = put_draft(s1, {**formal, "sell_on": True}, 1)
    assert sold["draft"]["sell_on"] is True and sold["checkpoint"]["sell_on"] is False, sold
    s2 = save(s1, 1)
    assert s2 == {"checkpoint": formal, "previous": DEFAULTS, "draft": formal, "rev": 2}, s2
    assert _raises(StaleRev, save, s1, 0).rev == 1
    assert _raises(Invalid, save, s2, 2).errors == ["draft: same as the checkpoint, nothing to save"]
    s3 = rollback(s2, 2)
    assert s3 == {"checkpoint": DEFAULTS, "previous": formal, "draft": formal, "rev": 3}, s3
    s4 = rollback(s3, 3)
    assert {k: s4[k] for k in ("checkpoint", "previous", "draft")} == {
        k: s2[k] for k in ("checkpoint", "previous", "draft")} and s4["rev"] == 4, s4
    assert _raises(StaleRev, rollback, s3, 2).rev == 3
    assert _raises(Invalid, rollback, s1, 1).errors == ["previous: nothing to roll back to"]
    # Pure: the inputs are untouched.
    before = copy.deepcopy(s2)
    save(put_draft(s2, DEFAULTS, 2), 3)
    assert s2 == before


# ── The config API ────────────────────────────────────────────────────

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
OWNER_A = fx.login_owner("agency_a_owner")
CONFIG = "/admin/full-ai/config"


def _db(fn):
    return asyncio.run(fn())


async def _seed_rule() -> None:
    async with get_session() as s:
        s.add(AutomationRule(account_id=A, name="Full AI Chat", kind="full_ai_chat",
                             trigger_json=json.dumps({"every_seconds": 86400}), steps_json="{}",
                             is_enabled=True))


_db(_seed_rule)


def _rule_row() -> list[tuple]:
    async def go():
        async with get_session() as s:
            return [tuple(r) for r in (await s.execute(text(
                "SELECT * FROM automation_rules WHERE account_id = :a AND kind = 'full_ai_chat'"),
                {"a": A})).all()]
    return _db(go)


def case_config_api_round_trip():
    rule = _rule_row()
    assert len(rule) == 1, rule
    got = OWNER_A.get(CONFIG, params={"account_id": A})
    assert got.status_code == 200, got.text
    assert got.json() == {"checkpoint": DEFAULTS, "previous": None, "draft": DEFAULTS, "rev": 0,
                          "errors": []}, got.json()
    formal = {**DEFAULTS, "text_style": "formal"}
    bad = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": {**formal, "fans_list": []},
                                               "rev": 0})
    assert bad.status_code == 422 and bad.json() == {"errors": ["fans_list: unknown key"]}, bad.text
    stale = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": formal, "rev": 7})
    assert stale.status_code == 409 and stale.json()["rev"] == 0, stale.text
    ok = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": formal, "rev": 0})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"checkpoint": DEFAULTS, "previous": None, "draft": formal, "rev": 1,
                         "errors": []}, ok.json()
    # The same request again is stale: someone (this tab) stored meanwhile.
    again = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": formal, "rev": 0})
    assert again.status_code == 409 and again.json()["rev"] == 1, again.text
    saved = OWNER_A.post(f"{CONFIG}/save", json={"account_id": A, "rev": 1})
    assert saved.status_code == 200, saved.text
    after_save = saved.json()
    assert after_save == {"checkpoint": formal, "previous": DEFAULTS, "draft": formal, "rev": 2,
                          "errors": []}, after_save
    assert _rule_row() == rule
    assert OWNER_A.post(f"{CONFIG}/save", json={"account_id": A, "rev": 1}).status_code == 409
    nothing = OWNER_A.post(f"{CONFIG}/save", json={"account_id": A, "rev": 2})
    assert nothing.status_code == 422 and nothing.json() == {
        "errors": ["draft: same as the checkpoint, nothing to save"]}, nothing.text
    back = OWNER_A.post(f"{CONFIG}/rollback", json={"account_id": A, "rev": 2})
    assert back.status_code == 200, back.text
    assert (back.json()["checkpoint"], back.json()["previous"], back.json()["rev"]) == (
        DEFAULTS, formal, 3), back.json()
    assert _rule_row() == rule
    forth = OWNER_A.post(f"{CONFIG}/rollback", json={"account_id": A, "rev": 3})
    assert forth.status_code == 200, forth.text
    assert {**forth.json(), "rev": 2} == after_save and forth.json()["rev"] == 4, forth.json()
    assert _rule_row() == rule
    assert OWNER_A.get(CONFIG, params={"account_id": A}).json() == forth.json()


if __name__ == "__main__":
    _harness.run()
