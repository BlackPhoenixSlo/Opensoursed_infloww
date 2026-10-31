#!/usr/bin/env python3
"""test_account_config_rules.py — the pure rules of the config PUT, by table.

`account_config_rules.clean_head` + `clean_config_put` (the Brain PUT,
`account_config_api`), chained as the route chains them: no DB, no OF, no
request. The 422 texts are pinned byte for byte; the ABSENT-key rows matter
most (a `voice` cleared by a save that never named it is a wrong-gender send).

Run:  ./venv/bin/python service/tests/test_account_config_rules.py  (exit 0 = pass)
"""
import _harness  # noqa: F401 — MUST be first (temp DB, fake keys)

import copy  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import account_config_rules as rules  # noqa: E402
from automations._persona import MODEL_NOTES_MAX  # noqa: E402
from llm_client import MODELS  # noqa: E402

AID = "acc_rules"
NOW = datetime(2026, 10, 31, 12, 0, 0)
ALLOWED = set(MODELS)
AudiencePut = rules.AudiencePut
NO_AUD = AudiencePut(False, None, False, None, False, None)
SPARSE = ("voice", "model_notes", "audience_mode", "audience_list_id", "audience_auto_add",
          "cotag_tag_videos", "cotag_username", "nudge_config_json")


def _put(cfg, aud=NO_AUD):
    """The route's chain: the head first (before the audience IO), then the rest."""
    head, err = rules.clean_head(cfg, ALLOWED)
    if err is not None:
        assert head is None
        return None, err
    return rules.clean_config_put(cfg, rules.PutContext(AID, ALLOWED, NOW, head, aud))


def _ok(cfg, aud=NO_AUD):
    vals, err = _put(cfg, aud)
    assert err is None, (cfg, err.status_code, err.detail)
    return vals


def _err(cfg):
    vals, err = _put(cfg)
    assert vals is None and err is not None, (cfg, vals)
    return err.status_code, err.detail


# ── the Brain PUT ─────────────────────────────────────────────────────────────

def case_absent_keys_are_unchanged():
    """No sparse key joins the upsert unless SENT: voice, notes, audience,
    cotag, and never nudge_config_json."""
    for cfg in ({}, {"persona": "hi"}, {"voice": ""}, {"voice": None},
                {"language": "es", "model": "deepseek-v4-pro"}):
        vals = _ok(cfg)
        leaked = [k for k in SPARSE if k in vals]
        assert not leaked, (cfg, leaked)
        assert vals["account_id"] == AID and vals["updated_at"] == NOW, vals


def case_scalar_defaults():
    vals = _ok({})
    assert {k: vals[k] for k in ("persona", "location", "persona_facts_json", "language",
                                 "timezone", "utc_offset", "daily_cost_cap_cents", "model",
                                 "reasoning_effort", "model_by_purpose", "time_activities_json",
                                 "time_images_json")} == {
        "persona": None, "location": None, "persona_facts_json": None, "language": None,
        "timezone": None, "utc_offset": 0, "daily_cost_cap_cents": 100, "model": None,
        "reasoning_effort": None, "model_by_purpose": None, "time_activities_json": None,
        "time_images_json": None}, vals


def case_voice():
    rows = [({"voice": "him"}, "him"), ({"voice": "HIM"}, "him"), ({"voice": "her"}, None)]
    for cfg, want in rows:
        vals = _ok(cfg)
        assert "voice" in vals and vals["voice"] == want, (cfg, vals.get("voice", "ABSENT"))
    assert _err({"voice": "hom"}) == (422, "voice 'hom' is not supported (expected 'her' or 'him')")


def case_explicit_null_or_empty_clears():
    rows = [({"persona": ""}, "persona", None), ({"persona": "  x "}, "persona", "x"),
            ({"location": None}, "location", None), ({"model_notes": ""}, "model_notes", None),
            ({"model_notes": None}, "model_notes", None),
            ({"model_notes": " note "}, "model_notes", "note"),
            ({"cotag_username": ""}, "cotag_username", None),
            ({"cotag_username": None}, "cotag_username", None),
            ({"cotag_username": " @SomeOne.Else "}, "cotag_username", "someone.else"),
            ({"cotag_tag_videos": False}, "cotag_tag_videos", None),
            ({"cotag_tag_videos": True}, "cotag_tag_videos", True),
            ({"timezone": ""}, "timezone", None),
            ({"time_activities": {}}, "time_activities_json", None),
            ({"persona_facts": {}}, "persona_facts_json", None)]
    for cfg, key, want in rows:
        vals = _ok(cfg)
        assert key in vals and vals[key] == want, (cfg, vals.get(key, "ABSENT"))


def case_persona_facts_allowlist():
    vals = _ok({"persona_facts": {"age": " 24 ", "job": ["a", " ", "b"], "nope": "x",
                                  "zzz_unknown": "y"}})
    assert json.loads(vals["persona_facts_json"]) == {"age": "24", "job": "a, b"}, vals
    vals = _ok({"persona_facts": {"age": "x" * 500}})
    assert json.loads(vals["persona_facts_json"]) == {"age": "x" * 240}
    assert _err({"persona_facts": "age 24"}) == (422, "persona_facts must be an object")


def case_language():
    for cfg, want in (({"language": "es"}, "es"), ({"language": "en"}, None),
                      ({"language": "EN"}, None), ({"language": ""}, None),
                      ({"language": None}, None), ({}, None)):
        assert _ok(cfg)["language"] == want, cfg
    # An unknown code is refused, never stored or silently cleared.
    assert _err({"language": "xx"}) == (422, "language 'xx' is not a supported code")


def case_text_and_notes_limits():
    assert _err({"persona": 5}) == (422, "persona must be text")
    assert _err({"model_notes": "n" * (MODEL_NOTES_MAX + 1)}) == (
        422, f"model_notes must be at most {MODEL_NOTES_MAX} characters")
    assert _ok({"model_notes": "n" * MODEL_NOTES_MAX})["model_notes"] == "n" * MODEL_NOTES_MAX


def case_model_and_effort():
    known = ", ".join(sorted(ALLOWED))
    assert _err({"model": "gpt-9"}) == (422, f"model 'gpt-9' is not a known model ({known})")
    assert _ok({"model": " deepseek-v4-pro "})["model"] == "deepseek-v4-pro"
    assert _ok({"model": ""})["model"] is None
    # Effort is checked against the model being saved; its own default stores NULL.
    assert _ok({"model": "deepseek-v4-pro", "reasoning_effort": "low"})["reasoning_effort"] == "low"
    assert _ok({"model": "deepseek-v4-pro", "reasoning_effort": "high"})["reasoning_effort"] is None
    assert _err({"model": "deepseek-v4-pro", "reasoning_effort": "max"}) == (
        422, "reasoning_effort 'max' is not valid for model 'deepseek-v4-pro' (low, medium, high)")
    assert _err({"model": "glm-4.5-air", "reasoning_effort": "low"}) == (
        422, "model 'glm-4.5-air' takes no reasoning effort — leave reasoning_effort empty")
    assert _err({"reasoning_effort": "low"}) == (
        422, "model '(none)' takes no reasoning effort — leave reasoning_effort empty")
    # The helpers themselves, as the route re-exports them.
    assert rules._validate_model(None, "model", ALLOWED) is None
    assert rules._validate_model("x", "model", set()) == "x"   # no allowlist: kept
    assert rules._validate_effort("", "deepseek-v4-pro") is None
    vals = _ok({"model_by_purpose": {"chat": "glm-5.3-flash", "retired": "", "x": None}})
    assert json.loads(vals["model_by_purpose"]) == {"chat": "glm-5.3-flash"}, vals
    assert _err({"model_by_purpose": {"chat": "nope"}}) == (
        422, f"model_by_purpose.chat 'nope' is not a known model ({known})")
    assert _err({"model_by_purpose": ["chat"]}) == (422, "model_by_purpose must be an object")


def case_numbers_and_slots():
    rows = [({"utc_offset": True}, "utc_offset must be a whole number of hours"),
            ({"utc_offset": "3"}, "utc_offset must be a whole number of hours"),
            ({"utc_offset": 25}, "utc_offset must be between -24 and 24 hours"),
            ({"daily_cost_cap_cents": -1}, "daily_cost_cap_cents must be a non-negative number"),
            ({"daily_cost_cap_cents": False}, "daily_cost_cap_cents must be a non-negative number"),
            ({"timezone": "Mars/Base"},
             "timezone 'Mars/Base' is not a known IANA zone (e.g. America/Vancouver)"),
            ({"time_activities": ["x"]}, "time_activities must be an object"),
            ({"time_activities": {"evening": 3}}, "time_activities.evening must be text"),
            ({"time_images": "x"}, "time_images must be an object"),
            ({"time_images": {"night": True}}, "time_images.night must be a media id"),
            ({"time_images": {"night": "abc"}}, "time_images.night must be a media id"),
            ({"cotag_username": "not a handle"},
             "cotag_username must be an OnlyFans handle (letters, numbers, . _ -)")]
    for cfg, text in rows:
        assert _err(cfg) == (422, text), (cfg, _err(cfg))
    vals = _ok({"utc_offset": -6.0, "daily_cost_cap_cents": 250.9, "timezone": "America/Vancouver",
                "time_activities": {"evening": " out ", "bogus": "x"},
                "time_images": {"night": "42", "morning_1": 0, "evening": 7.0}})
    assert (vals["utc_offset"], vals["daily_cost_cap_cents"], vals["timezone"]) == (
        -6, 250, "America/Vancouver"), vals
    assert json.loads(vals["time_activities_json"]) == {"evening": "out"}
    assert json.loads(vals["time_images_json"]) == {"evening": 7, "night": 42}


def case_audience_branches_join_only_when_sent():
    rows = [(AudiencePut(True, "off", False, None, False, None), {"audience_mode": None}),
            (AudiencePut(True, "shadow", True, 9, True, True),
             {"audience_mode": "shadow", "audience_list_id": 9, "audience_auto_add": True}),
            (AudiencePut(False, None, True, None, True, False),
             {"audience_list_id": None, "audience_auto_add": None})]
    for aud, want in rows:
        vals = _ok({}, aud)
        got = {k: vals[k] for k in ("audience_mode", "audience_list_id", "audience_auto_add")
               if k in vals}
        assert got == want, (aud, got)


def case_clean_head_is_the_prefix_before_the_audience_io():
    """The route runs `clean_head` before the audience branch: its checks are
    the ones that come first, and the rest are left to `clean_config_put`."""
    head = [{"persona": 5}, {"model_notes": "n" * (MODEL_NOTES_MAX + 1)}, {"model": "gpt-9"},
            {"reasoning_effort": "low"}, {"persona_facts": 1}, {"language": "xx"}]
    for cfg in head:
        h, e = rules.clean_head(cfg, ALLOWED)
        assert h is None and e is not None and (e.status_code, e.detail) == _err(cfg), cfg
    h, e = rules.clean_head([], ALLOWED)
    assert h is None and (e.status_code, e.detail) == (422, "config must be an object")
    for cfg in ({"voice": "hom"}, {"utc_offset": 99}, {"cotag_username": "a b"}, {}):
        h, e = rules.clean_head(cfg, ALLOWED)
        assert e is None and isinstance(h, rules.Head), cfg
    # Several bad keys: the first check in the route's order wins.
    assert _err({"voice": "hom", "persona": 5}) == (422, "persona must be text")
    assert _err({"utc_offset": 99, "voice": "hom"})[1].startswith("voice 'hom'")


if __name__ == "__main__":
    _harness.run()
