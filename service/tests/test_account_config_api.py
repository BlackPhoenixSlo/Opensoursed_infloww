#!/usr/bin/env python3
"""
account_config_api — read/write the per-account "Brain" (account_ai_config).

Drives the route coroutines directly against the temp DB (auth is a no-op for
unauthed test calls). Covers: defaults for an unset account, a full round-trip,
that the upsert never clobbers the separately-owned nudge_config_json or
split_inbox_json, value validation (model / utc_offset / cap), slot filtering +
id coercion, and that blanks clear the columns.

Run: ./venv/bin/python service/tests/test_account_config_api.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

import os

# This suite drives the route coroutines directly, with no signed-in principal.
# assert_account_owned fails closed on anonymous since 2026-08-10; this env flag
# is its documented escape hatch.
os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

_harness.bootstrap()

import json  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from account_config_api import (  # noqa: E402
    _ConfigBody, get_account_config, put_account_config, MODEL_PURPOSES, TIME_SLOTS,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def case_get_defaults_for_unset():
    aid = "acc_bc_empty"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)
    cfg = resp["config"]
    assert cfg["persona"] is None and cfg["model"] is None, cfg
    assert cfg["utc_offset"] == 0 and cfg["daily_cost_cap_cents"] == 100, cfg
    assert cfg["time_activities"] == {} and cfg["time_images"] == {}, cfg
    # Metadata drives the editor's dropdowns + image slots.
    assert len(resp["slots"]) == 6 and resp["slots"][0] == "morning_1", resp
    assert resp["model_options"], "model options should be non-empty"
    assert set(resp["purposes"]) == set(MODEL_PURPOSES), resp


async def case_save_then_get_roundtrip():
    aid = "acc_bc_save"
    await _seed_account(aid)
    model = (await get_account_config(account_id=aid))["model_options"][0]

    body = {
        "persona": "  Ava, playful island girl  ",  # trimmed on save
        "location": "Vancouver Island",
        "timezone": "America/Vancouver",
        "utc_offset": -6,
        "daily_cost_cap_cents": 250,
        "model": model,
        "model_by_purpose": {"gen_info": model, "welcome_chatter_for_info": ""},  # blank dropped
        "time_activities": {"morning_1": "sipping coffee", "night": "in bed",
                            "not_a_slot": "ignored"},
        "time_images": {"morning_1": "3666527793", "night": 42, "evening": 0},  # str→int, 0 dropped
    }
    out = await put_account_config(_ConfigBody(account_id=aid, config=body))
    c = out["config"]
    assert c["persona"] == "Ava, playful island girl", c
    assert c["timezone"] == "America/Vancouver", c
    assert c["utc_offset"] == -6 and c["daily_cost_cap_cents"] == 250, c
    assert c["model"] == model, c
    assert c["model_by_purpose"] == {"gen_info": model}, c          # blank purpose dropped
    assert c["time_activities"] == {"morning_1": "sipping coffee", "night": "in bed"}, c
    assert c["time_images"] == {"morning_1": 3666527793, "night": 42}, c  # coerced, 0 dropped

    again = (await get_account_config(account_id=aid))["config"]
    assert again == c, (again, c)


async def case_upsert_preserves_nudge_config():
    """The brain upsert must NOT touch nudge_config_json (owned by nudge_config_api)."""
    aid = "acc_bc_nudge"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=0,
                              nudge_config_json=json.dumps({"enabled": True})))

    await put_account_config(_ConfigBody(account_id=aid, config={"persona": "hi"}))

    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    assert row.persona == "hi", row.persona
    assert json.loads(row.nudge_config_json) == {"enabled": True}, row.nudge_config_json


async def case_upsert_preserves_split_inbox():
    """The brain upsert must NOT touch split_inbox_json (owned by split_inbox_api)."""
    aid = "acc_bc_split"
    await _seed_account(aid)
    split = {"group_count": 2, "assignments": {"80001": 2}}
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=0,
                              split_inbox_json=json.dumps(split)))

    await put_account_config(_ConfigBody(account_id=aid, config={"persona": "hi"}))

    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    assert row.persona == "hi", row.persona
    assert json.loads(row.split_inbox_json) == split, row.split_inbox_json


async def case_validation():
    aid = "acc_bc_valid"
    await _seed_account(aid)
    bad_configs = [
        {"model": "not-a-real-model"},          # unknown model
        {"timezone": "Vancouver"},               # not an IANA zone
        {"utc_offset": 99},                      # out of range
        {"daily_cost_cap_cents": -5},            # negative
        {"model_by_purpose": {"gen_info": "nope"}},  # unknown per-purpose model
        {"time_images": {"morning_1": "abc"}},   # non-numeric media id
    ]
    for bad in bad_configs:
        try:
            await put_account_config(_ConfigBody(account_id=aid, config=bad))
            assert False, f"expected 422 for {bad}"
        except HTTPException as e:
            assert e.status_code == 422, (bad, e)


async def case_blanks_clear_columns():
    aid = "acc_bc_clear"
    await _seed_account(aid)
    model = (await get_account_config(account_id=aid))["model_options"][0]
    # First set everything.
    await put_account_config(_ConfigBody(account_id=aid, config={
        "persona": "x", "model": model, "location": "Y",
        "timezone": "America/Vancouver",
        "time_activities": {"morning_1": "a"}, "time_images": {"morning_1": 7},
    }))
    # Then save blanks → cleared.
    out = await put_account_config(_ConfigBody(account_id=aid, config={
        "persona": "", "model": "", "location": "  ", "timezone": "",
        "time_activities": {}, "time_images": {},
    }))
    c = out["config"]
    assert c["persona"] is None and c["model"] is None and c["location"] is None, c
    assert c["timezone"] is None, c
    assert c["time_activities"] == {} and c["time_images"] == {}, c
    # Empty maps store as NULL so the senders fall back to their legacy pickers.
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    assert row.time_activities_json is None and row.time_images_json is None, row


async def case_both_lanes_ride_along_for_the_dropdown():
    """The Brain panel's Creator dropdown is LOCAL FORM STATE until Save, so a payload
    that only carries the STORED lane relabels one Save too late — the operator fills
    "Why she started OF" on an account they have already switched to Male, and Reset
    refills it with Ava. Both lanes therefore ride along, and the panel picks by the
    SELECTED voice.

    This is the branch's headline behavioural fix and it had no test on either side of
    the wire: reverting the endpoint AND the panel left every suite green."""
    aid = "acc_bc_lanes"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)

    # Stored lane is the shipped one, and the singular fields still answer for it —
    # a blank account has no unsaved dropdown, so seeding from `defaults` is right.
    assert resp["config"]["voice"] == "her"
    assert resp["defaults"]["persona"] == resp["defaults_by_voice"]["her"]["persona"]
    assert {m["key"]: m["label"] for m in resp["persona_fact_fields"]}["kinks"] \
        == {m["key"]: m["label"] for m in resp["persona_fact_fields_by_voice"]["her"]}["kinks"]

    # …and BOTH lanes are present, genuinely different where identity lives.
    by_voice = resp["defaults_by_voice"]
    assert set(by_voice) == {"her", "him"}, sorted(by_voice)
    assert by_voice["him"]["persona"] != by_voice["her"]["persona"]
    assert by_voice["him"]["time_activities"] != by_voice["her"]["time_activities"]

    labels = {v: {m["key"]: m["label"] for m in resp["persona_fact_fields_by_voice"][v]}
              for v in ("her", "him")}
    assert labels["her"]["kinks"] == "What she's into"
    assert labels["him"]["kinks"] == "What he's into"
    assert labels["her"].keys() == labels["him"].keys(), "the canon slate must not vary"

    # The PLACEHOLDER is the same column of the same concept as the label — laning one
    # and not the other put "to pay off her studies" under "Why he started OF".
    #
    # Asserted as "the endpoint SERVES `_voice`'s male table", not as "no female word
    # survived a scan". The first fix here WAS a scan — regex hers, blank the matches —
    # and it passed this test while leaving 21 of 26 male placeholders as her copy,
    # because a word list only catches what it knows ("content creator, waitressed
    # before" is not in it). `test_voice_lane.case_every_canon_slot_has_a_male_placeholder`
    # owns whether that table is any good; this owns whether the wire carries it.
    from automations._voice import fact_placeholders
    for lane in ("her", "him"):
        served = {m["key"]: m["placeholder"]
                  for m in resp["persona_fact_fields_by_voice"][lane]}
        assert served == fact_placeholders(lane), lane
    # …and hers is the table that shipped before the lane existed, byte-for-byte.
    # A branch that "fixed" the male lane by emptying the column for everyone would
    # pass every assert above.
    hers = {m["key"]: m["placeholder"] for m in resp["persona_fact_fields_by_voice"]["her"]}
    assert hers["job"] == "content creator, waitressed before"
    assert hers["tattoos"] == "script on her ribs, small rose on left wrist"

    # A male account's SINGULAR fields follow the stored column once it is saved.
    await put_account_config(_ConfigBody(account_id=aid, config={"voice": "him"}))
    him = await get_account_config(account_id=aid)
    assert him["config"]["voice"] == "him"
    assert him["defaults"]["persona"] == by_voice["him"]["persona"]
    assert {m["key"]: m["label"] for m in him["persona_fact_fields"]}["kinks"] \
        == "What he's into"


async def case_cotag_settings_roundtrip():
    """The Brain's co-performer tag knobs: video rule NULL ≡ OFF (a collab
    opt-in), username blank ≡ "No co-creator tag" (ticket 85), absent keys =
    unchanged, junk handles 422, and the account's own handle saves as none."""
    import account_config_api

    aid = "acc_bc_cotag"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)
    assert resp["config"]["cotag_tag_videos"] is False, resp["config"]
    assert resp["config"]["cotag_username"] is None, resp["config"]
    assert "cotag_default_username" not in resp, resp.keys()

    # Who the account is, as /users/me would say — a test must not reach OF.
    real_own = account_config_api._own_handle
    account_config_api._own_handle = lambda _aid: "thecreator"
    try:
        out = await put_account_config(_ConfigBody(account_id=aid, config={
            "cotag_tag_videos": True, "cotag_username": " @SomeOne.Else "}))
        c = out["config"]
        assert c["cotag_tag_videos"] is True, c           # opt-in stored
        assert c["cotag_username"] == "someone.else", c   # trimmed, un-@'d, folded

        # Absent keys = unchanged — an older client saving a persona can't clear them.
        c = (await put_account_config(
            _ConfigBody(account_id=aid, config={"persona": "hi"})))["config"]
        assert c["cotag_tag_videos"] is True and c["cotag_username"] == "someone.else", c

        # Unchecking the box and picking "No co-creator tag" both store NULL.
        await put_account_config(_ConfigBody(account_id=aid, config={
            "cotag_tag_videos": False, "cotag_username": ""}))
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
        assert row.cotag_tag_videos is None and row.cotag_username is None, (
            row.cotag_tag_videos, row.cotag_username)

        # An account cannot tag itself: its own handle is stored as no tag.
        c = (await put_account_config(_ConfigBody(account_id=aid, config={
            "cotag_username": "@TheCreator"})))["config"]
        assert c["cotag_username"] is None, c
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
        assert row.cotag_username is None, row.cotag_username
    finally:
        account_config_api._own_handle = real_own

    try:
        await put_account_config(_ConfigBody(
            account_id=aid, config={"cotag_username": "not a handle"}))
    except HTTPException as e:
        assert e.status_code == 422 and "cotag_username" in str(e.detail), e.detail
    else:
        raise AssertionError("a handle with spaces must 422, not store")


async def case_effort_dropdown_is_served_validated_and_stored():
    """The Brain\'s thinking-effort picker, end to end.

    The options are served PER MODEL because the legal values differ by
    provider — "medium" is good DeepSeek and a hard 400 on z.ai — so a shared
    list would offer at least one account a value that black-holes its replies.
    """
    aid = "acc_bc_effort"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)
    opts = resp["effort_options"]

    # Served for every offerable model, empty where there is no control.
    assert set(opts) == set(resp["model_options"]), opts
    assert opts["glm-5.3-flash"] == ["low", "high", "max"], opts["glm-5.3-flash"]
    assert opts["deepseek-v4-pro"] == ["low", "medium", "high"], opts["deepseek-v4-pro"]
    assert opts["deepseek-v4-flash"] == [], opts["deepseek-v4-flash"]

    # Round-trip a real pick.
    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "glm-5.3-flash", "reasoning_effort": "max"}))
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "max", cfg["reasoning_effort"]

    # A value that is legal on ANOTHER provider is still refused for this model.
    # The union of every provider\'s values is exactly what the dropdown exists
    # to stop being saved.
    for bad in ("medium", "none", "LOW"):
        try:
            await put_account_config(_ConfigBody(account_id=aid, config={
                "model": "glm-5.3-flash", "reasoning_effort": bad}))
        except HTTPException as e:
            assert e.status_code == 422 and "reasoning_effort" in str(e.detail), e.detail
        else:
            raise AssertionError(f"{bad!r} must 422 for glm-5.3-flash")

    # And an effort on a model that has no control is refused rather than stored
    # somewhere it can never be read.
    try:
        await put_account_config(_ConfigBody(account_id=aid, config={
            "model": "deepseek-v4-flash", "reasoning_effort": "low"}))
    except HTTPException as e:
        assert e.status_code == 422, e.detail
    else:
        raise AssertionError("an effort on a no-control model must 422")


async def case_the_effort_box_shows_what_the_account_actually_runs():
    """Blank would be a lie with consequences. An account on a model pinned to
    "high" that renders an empty box invites an operator to save a downgrade
    they never chose — Save cannot tell "left alone" from "set to the first
    entry". So an unset effort reports the model\'s own pin."""
    aid = "acc_bc_effort_show"
    await _seed_account(aid)
    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "deepseek-v4-pro"}))
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "high", cfg["reasoning_effort"]

    # A model with no control reports nothing to show.
    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "deepseek-v4-flash"}))
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "", cfg["reasoning_effort"]


async def case_a_round_trip_save_does_not_materialize_the_default():
    """Every client of this endpoint re-sends the WHOLE config blob (it replaces
    the columns it reads, so they must), and GET reports the model's pin for an
    account that has not chosen one. Without normalisation, saving the AI-chatter
    tab — or anything else — would write that pin into the column as an explicit
    value, freezing the account at whatever the default was that afternoon and
    quietly cutting it off from any later change to the pin.

    The invariant: GET → PUT → GET is idempotent AND leaves the column NULL."""
    aid = "acc_bc_effort_rt"
    await _seed_account(aid)
    await put_account_config(_ConfigBody(account_id=aid, config={"model": "deepseek-v4-pro"}))

    for _ in range(2):  # twice — a second unrelated save must not drift either
        cfg = (await get_account_config(account_id=aid))["config"]
        assert cfg["reasoning_effort"] == "high", cfg["reasoning_effort"]
        await put_account_config(_ConfigBody(account_id=aid, config=cfg))
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
        assert row.reasoning_effort is None, (
            f"the pin was materialized into the column as {row.reasoning_effort!r} — "
            f"this account no longer follows the model default")

    # A DELIBERATE non-default pick is still stored, and still round-trips.
    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "deepseek-v4-pro", "reasoning_effort": "low"}))
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    assert row.reasoning_effort == "low", row.reasoning_effort
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "low", cfg["reasoning_effort"]



async def case_the_editor_is_told_which_purposes_do_not_inherit():
    """A purpose in `PURPOSE_DEFAULT_MODELS` does NOT inherit the account brain,
    and the panel that exists to show model choice was rendering "inherit
    default" over it. The contract carries the answer now — RESOLVED, because
    `resolve_model` falls to the house model when a pinned id has been retired,
    and serving the dead id would lie a second, quieter way."""
    from automations._common import DEFAULT_MODEL, PURPOSE_DEFAULT_MODELS
    from llm_client import MODELS

    await _seed_account("acc_purpose_defaults")
    body = await get_account_config("acc_purpose_defaults")
    served = body["purpose_defaults"]
    assert set(served) == set(PURPOSE_DEFAULT_MODELS), served
    for purpose, model in served.items():
        assert model in MODELS, f"{purpose} is offered a model that does not exist"
    assert served["help_assistant"] == "deepseek-v4-flash", served

    real = dict(PURPOSE_DEFAULT_MODELS)
    PURPOSE_DEFAULT_MODELS["help_assistant"] = "a-model-that-was-retired"
    try:
        served = (await get_account_config(
            "acc_purpose_defaults"))["purpose_defaults"]
        assert served["help_assistant"] == DEFAULT_MODEL, \
            f"the editor was shown a retired id: {served}"
    finally:
        PURPOSE_DEFAULT_MODELS.clear(); PURPOSE_DEFAULT_MODELS.update(real)


async def case_model_notes_roundtrip_and_sparse():
    """Get to know fans' Model info: served with its template, round-trips through
    the whole-object PUT the page sends, is left alone by a PUT that omits it (the
    Brain panel, an older client), clears on blank, and is capped short."""
    from automations._persona import MODEL_NOTES_MAX, MODEL_NOTES_TEMPLATE

    aid = "acc_bc_model_notes"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)
    assert resp["config"]["model_notes"] is None, resp["config"]
    assert resp["model_notes_template"] == MODEL_NOTES_TEMPLATE
    assert "Name:" in MODEL_NOTES_TEMPLATE and "Won't do" in MODEL_NOTES_TEMPLATE

    # The page's save: the stored brain back, only model_notes changed.
    notes = MODEL_NOTES_TEMPLATE.replace("Name: ", "Name: Mia")
    out = await put_account_config(_ConfigBody(
        account_id=aid, config={**resp["config"], "persona": "Ella.", "model_notes": notes}))
    assert out["config"]["model_notes"] == notes.strip(), out["config"]
    again = (await get_account_config(account_id=aid))["config"]
    assert again["model_notes"] == notes.strip() and again["persona"] == "Ella.", again

    # Absent key == unchanged.
    await put_account_config(_ConfigBody(account_id=aid, config={"persona": "Ella."}))
    async with get_session() as s:
        assert (await s.get(AccountAiConfig, aid)).model_notes == notes.strip()

    # Too long is refused before anything is written.
    try:
        await put_account_config(_ConfigBody(
            account_id=aid, config={"persona": "Ella.", "model_notes": "x" * (MODEL_NOTES_MAX + 1)}))
        raise AssertionError("an over-long model_notes was accepted")
    except HTTPException as e:
        assert e.status_code == 422 and "model_notes" in str(e.detail), e.detail
    async with get_session() as s:
        assert (await s.get(AccountAiConfig, aid)).model_notes == notes.strip()

    # Blank clears the column (the page then prefills the template again).
    out = await put_account_config(_ConfigBody(account_id=aid, config={"persona": "Ella.", "model_notes": "  "}))
    assert out["config"]["model_notes"] is None, out["config"]


_harness.run(
    case_get_defaults_for_unset,
    case_save_then_get_roundtrip,
    case_upsert_preserves_nudge_config,
    case_upsert_preserves_split_inbox,
    case_validation,
    case_blanks_clear_columns,
    case_both_lanes_ride_along_for_the_dropdown,
    case_cotag_settings_roundtrip,
    case_effort_dropdown_is_served_validated_and_stored,
    case_the_effort_box_shows_what_the_account_actually_runs,
    case_a_round_trip_save_does_not_materialize_the_default,
    case_the_editor_is_told_which_purposes_do_not_inherit,
    case_model_notes_roundtrip_and_sparse,
)
