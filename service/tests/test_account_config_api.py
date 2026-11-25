#!/usr/bin/env python3
from __future__ import annotations

import _harness

import os

# assert_account_owned fails closed on anonymous; this env flag is its escape hatch.
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
    assert len(resp["slots"]) == 6 and resp["slots"][0] == "morning_1", resp
    assert resp["model_options"], "model options should be non-empty"
    from automations._common import DEFAULT_MODEL
    assert resp["default_model"] == DEFAULT_MODEL and DEFAULT_MODEL in resp["model_options"], resp
    assert set(resp["purposes"]) == set(MODEL_PURPOSES), resp


async def case_save_then_get_roundtrip():
    aid = "acc_bc_save"
    await _seed_account(aid)
    model = (await get_account_config(account_id=aid))["model_options"][0]

    body = {
        "persona": "  Ava, playful island girl  ",
        "location": "Vancouver Island",
        "timezone": "America/Vancouver",
        "utc_offset": -6,
        "daily_cost_cap_cents": 250,
        "model": model,
        "model_by_purpose": {"gen_info": model, "welcome_chatter_for_info": ""},
        "time_activities": {"morning_1": "sipping coffee", "night": "in bed",
                            "not_a_slot": "ignored"},
        "time_images": {"morning_1": "3666527793", "night": 42, "evening": 0},
    }
    out = await put_account_config(_ConfigBody(account_id=aid, config=body))
    c = out["config"]
    assert c["persona"] == "Ava, playful island girl", c
    assert c["timezone"] == "America/Vancouver", c
    assert c["utc_offset"] == -6 and c["daily_cost_cap_cents"] == 250, c
    assert c["model"] == model, c
    assert c["model_by_purpose"] == {"gen_info": model}, c
    assert c["time_activities"] == {"morning_1": "sipping coffee", "night": "in bed"}, c
    assert c["time_images"] == {"morning_1": 3666527793, "night": 42}, c

    again = (await get_account_config(account_id=aid))["config"]
    assert again == c, (again, c)


async def case_upsert_preserves_nudge_config():
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
        {"model": "not-a-real-model"},
        {"timezone": "Vancouver"},
        {"utc_offset": 99},
        {"daily_cost_cap_cents": -5},
        {"model_by_purpose": {"gen_info": "nope"}},
        {"time_images": {"morning_1": "abc"}},
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
    await put_account_config(_ConfigBody(account_id=aid, config={
        "persona": "x", "model": model, "location": "Y",
        "timezone": "America/Vancouver",
        "time_activities": {"morning_1": "a"}, "time_images": {"morning_1": 7},
    }))
    out = await put_account_config(_ConfigBody(account_id=aid, config={
        "persona": "", "model": "", "location": "  ", "timezone": "",
        "time_activities": {}, "time_images": {},
    }))
    c = out["config"]
    assert c["persona"] is None and c["model"] is None and c["location"] is None, c
    assert c["timezone"] is None, c
    assert c["time_activities"] == {} and c["time_images"] == {}, c
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    assert row.time_activities_json is None and row.time_images_json is None, row


async def case_both_lanes_ride_along_for_the_dropdown():
    aid = "acc_bc_lanes"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)

    assert resp["config"]["voice"] == "her"
    assert resp["defaults"]["persona"] == resp["defaults_by_voice"]["her"]["persona"]
    assert {m["key"]: m["label"] for m in resp["persona_fact_fields"]}["kinks"] \
        == {m["key"]: m["label"] for m in resp["persona_fact_fields_by_voice"]["her"]}["kinks"]

    by_voice = resp["defaults_by_voice"]
    assert set(by_voice) == {"her", "him"}, sorted(by_voice)
    assert by_voice["him"]["persona"] != by_voice["her"]["persona"]
    assert by_voice["him"]["time_activities"] != by_voice["her"]["time_activities"]

    labels = {v: {m["key"]: m["label"] for m in resp["persona_fact_fields_by_voice"][v]}
              for v in ("her", "him")}
    assert labels["her"]["kinks"] == "What she's into"
    assert labels["him"]["kinks"] == "What he's into"
    assert labels["her"].keys() == labels["him"].keys(), "the canon slate must not vary"

    # Asserts the endpoint serves _voice's male table, not a word scan: a scan passed while most male placeholders were still her copy.
    from automations._voice import fact_placeholders
    for lane in ("her", "him"):
        served = {m["key"]: m["placeholder"]
                  for m in resp["persona_fact_fields_by_voice"][lane]}
        assert served == fact_placeholders(lane), lane
    hers = {m["key"]: m["placeholder"] for m in resp["persona_fact_fields_by_voice"]["her"]}
    assert hers["job"] == "content creator, waitressed before"
    assert hers["tattoos"] == "script on her ribs, small rose on left wrist"

    await put_account_config(_ConfigBody(account_id=aid, config={"voice": "him"}))
    him = await get_account_config(account_id=aid)
    assert him["config"]["voice"] == "him"
    assert him["defaults"]["persona"] == by_voice["him"]["persona"]
    assert {m["key"]: m["label"] for m in him["persona_fact_fields"]}["kinks"] \
        == "What he's into"


async def case_cotag_settings_roundtrip():
    import account_config_api

    aid = "acc_bc_cotag"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)
    assert resp["config"]["cotag_tag_videos"] is False, resp["config"]
    assert resp["config"]["cotag_username"] is None, resp["config"]
    assert "cotag_default_username" not in resp, resp.keys()

    real_own = account_config_api._own_handle
    account_config_api._own_handle = lambda _aid: "thecreator"
    try:
        out = await put_account_config(_ConfigBody(account_id=aid, config={
            "cotag_tag_videos": True, "cotag_username": " @SomeOne.Else "}))
        c = out["config"]
        assert c["cotag_tag_videos"] is True, c
        assert c["cotag_username"] == "someone.else", c

        c = (await put_account_config(
            _ConfigBody(account_id=aid, config={"persona": "hi"})))["config"]
        assert c["cotag_tag_videos"] is True and c["cotag_username"] == "someone.else", c

        await put_account_config(_ConfigBody(account_id=aid, config={
            "cotag_tag_videos": False, "cotag_username": ""}))
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
        assert row.cotag_tag_videos is None and row.cotag_username is None, (
            row.cotag_tag_videos, row.cotag_username)

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
    aid = "acc_bc_effort"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)
    opts = resp["effort_options"]

    assert set(opts) == set(resp["model_options"]), opts
    assert opts["glm-5.3-flash"] == ["low", "high", "max"], opts["glm-5.3-flash"]
    assert opts["deepseek-v4-pro"] == ["low", "medium", "high"], opts["deepseek-v4-pro"]
    assert opts["deepseek-v4-flash"] == [], opts["deepseek-v4-flash"]

    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "glm-5.3-flash", "reasoning_effort": "max"}))
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "max", cfg["reasoning_effort"]

    for bad in ("medium", "none", "LOW"):
        try:
            await put_account_config(_ConfigBody(account_id=aid, config={
                "model": "glm-5.3-flash", "reasoning_effort": bad}))
        except HTTPException as e:
            assert e.status_code == 422 and "reasoning_effort" in str(e.detail), e.detail
        else:
            raise AssertionError(f"{bad!r} must 422 for glm-5.3-flash")

    try:
        await put_account_config(_ConfigBody(account_id=aid, config={
            "model": "deepseek-v4-flash", "reasoning_effort": "low"}))
    except HTTPException as e:
        assert e.status_code == 422, e.detail
    else:
        raise AssertionError("an effort on a no-control model must 422")


async def case_the_effort_box_shows_what_the_account_actually_runs():
    aid = "acc_bc_effort_show"
    await _seed_account(aid)
    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "deepseek-v4-pro"}))
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "high", cfg["reasoning_effort"]

    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "deepseek-v4-flash"}))
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "", cfg["reasoning_effort"]


async def case_a_round_trip_save_does_not_materialize_the_default():
    aid = "acc_bc_effort_rt"
    await _seed_account(aid)
    await put_account_config(_ConfigBody(account_id=aid, config={"model": "deepseek-v4-pro"}))

    for _ in range(2):
        cfg = (await get_account_config(account_id=aid))["config"]
        assert cfg["reasoning_effort"] == "high", cfg["reasoning_effort"]
        await put_account_config(_ConfigBody(account_id=aid, config=cfg))
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
        assert row.reasoning_effort is None, (
            f"the pin was materialized into the column as {row.reasoning_effort!r} — "
            f"this account no longer follows the model default")

    await put_account_config(_ConfigBody(account_id=aid, config={
        "model": "deepseek-v4-pro", "reasoning_effort": "low"}))
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    assert row.reasoning_effort == "low", row.reasoning_effort
    cfg = (await get_account_config(account_id=aid))["config"]
    assert cfg["reasoning_effort"] == "low", cfg["reasoning_effort"]



class _no_anthropic_key:

    def __init__(self, house: str = "", fallback: str = ""):
        self.vals = {"ANTHROPIC_API_KEY": house,
                     "HELP_ASSISTANT_ANTHROPIC_KEY": fallback}

    def __enter__(self):
        import llm_providers
        self.real = llm_providers._api_key
        llm_providers._api_key = lambda env: (
            self.vals[env] if env in self.vals else self.real(env))
        return self

    def __exit__(self, *a):
        import llm_providers
        llm_providers._api_key = self.real
        return False


async def case_help_assistant_default_is_opus_only_where_anthropic_is_keyed():
    from automations._common import resolve_model

    aid = "acc_help_opus"
    await _seed_account(aid)
    with _no_anthropic_key():
        served = (await get_account_config(aid))["purpose_defaults"]
        assert served["help_assistant"] == "deepseek-v4-flash", served
        assert await resolve_model(aid, "help_assistant") == "deepseek-v4-flash"
        assert await resolve_model("", "help_assistant") == "deepseek-v4-flash"
    with _no_anthropic_key(house="sk-ant-house"):
        served = (await get_account_config(aid))["purpose_defaults"]
        assert served["help_assistant"] == "claude-opus-5-5", served
        assert await resolve_model(aid, "help_assistant") == "claude-opus-5-5"
        # The house key alone does NOT pay a no-account ask (billed to the
        # asker or the fallback) — so that path must stay on DeepSeek.
        assert await resolve_model("", "help_assistant") == "deepseek-v4-flash"
    with _no_anthropic_key(fallback="sk-ant-fallback"):
        assert await resolve_model("", "help_assistant") == "claude-opus-5-5"
        async with get_session() as s:
            s.add(AccountAiConfig(account_id=aid, model_by_purpose=json.dumps(
                {"help_assistant": "deepseek-v4-pro"})))
        assert await resolve_model(aid, "help_assistant") == "deepseek-v4-pro"


async def case_a_json_purpose_refuses_a_model_that_cannot_return_json():
    from automations._common import JSON_OBJECT_PURPOSES

    aid = "acc_json_pin"
    await _seed_account(aid)
    for purpose in sorted(JSON_OBJECT_PURPOSES):
        try:
            await put_account_config(_ConfigBody(account_id=aid, config={
                "model_by_purpose": {purpose: "claude-opus-5-5"}}))
            raise AssertionError(f"{purpose} accepted a model that cannot return JSON")
        except HTTPException as e:
            assert e.status_code == 422 and "JSON" in str(e.detail), e.detail
        out = await put_account_config(_ConfigBody(account_id=aid, config={
            "model_by_purpose": {purpose: "deepseek-v4-flash"}}))
        assert out["config"]["model_by_purpose"] == {purpose: "deepseek-v4-flash"}, out
    out = await put_account_config(_ConfigBody(account_id=aid, config={
        "model_by_purpose": {"help_assistant": "claude-opus-5-5"}}))
    assert out["config"]["model_by_purpose"] == {"help_assistant": "claude-opus-5-5"}, out


async def case_the_editor_is_told_which_purposes_do_not_inherit():
    from automations._common import DEFAULT_MODEL, PURPOSE_DEFAULT_MODELS
    from llm_client import MODELS

    await _seed_account("acc_purpose_defaults")
    with _no_anthropic_key():
        body = await get_account_config("acc_purpose_defaults")
    served = body["purpose_defaults"]
    assert set(served) == set(PURPOSE_DEFAULT_MODELS), served
    for purpose, model in served.items():
        assert model in MODELS, f"{purpose} is offered a model that does not exist"
    assert served["help_assistant"] == "deepseek-v4-flash", served

    real = dict(PURPOSE_DEFAULT_MODELS)
    PURPOSE_DEFAULT_MODELS["help_assistant"] = "a-model-that-was-retired"
    try:
        with _no_anthropic_key():
            served = (await get_account_config(
                "acc_purpose_defaults"))["purpose_defaults"]
        assert served["help_assistant"] == DEFAULT_MODEL, \
            f"the editor was shown a retired id: {served}"
    finally:
        PURPOSE_DEFAULT_MODELS.clear(); PURPOSE_DEFAULT_MODELS.update(real)


async def case_model_notes_roundtrip_and_sparse():
    from automations._persona import MODEL_NOTES_MAX, MODEL_NOTES_TEMPLATE

    aid = "acc_bc_model_notes"
    await _seed_account(aid)
    resp = await get_account_config(account_id=aid)
    assert resp["config"]["model_notes"] is None, resp["config"]
    assert resp["model_notes_template"] == MODEL_NOTES_TEMPLATE
    assert "Name:" in MODEL_NOTES_TEMPLATE and "Won't do" in MODEL_NOTES_TEMPLATE

    notes = MODEL_NOTES_TEMPLATE.replace("Name: ", "Name: Mia")
    out = await put_account_config(_ConfigBody(
        account_id=aid, config={**resp["config"], "persona": "Ella.", "model_notes": notes}))
    assert out["config"]["model_notes"] == notes.strip(), out["config"]
    again = (await get_account_config(account_id=aid))["config"]
    assert again["model_notes"] == notes.strip() and again["persona"] == "Ella.", again

    await put_account_config(_ConfigBody(account_id=aid, config={"persona": "Ella."}))
    async with get_session() as s:
        assert (await s.get(AccountAiConfig, aid)).model_notes == notes.strip()

    try:
        await put_account_config(_ConfigBody(
            account_id=aid, config={"persona": "Ella.", "model_notes": "x" * (MODEL_NOTES_MAX + 1)}))
        raise AssertionError("an over-long model_notes was accepted")
    except HTTPException as e:
        assert e.status_code == 422 and "model_notes" in str(e.detail), e.detail
    async with get_session() as s:
        assert (await s.get(AccountAiConfig, aid)).model_notes == notes.strip()

    out = await put_account_config(_ConfigBody(account_id=aid, config={"persona": "Ella.", "model_notes": "  "}))
    assert out["config"]["model_notes"] is None, out["config"]


async def case_daily_cost_cap_put_roundtrip_bound_and_owner_only():
    import auth
    import chatters
    from datetime import datetime
    from db.models import GrokDailyCost

    aid = "acc_bc_cap"
    await _seed_account(aid)
    out = await put_account_config(_ConfigBody(account_id=aid, config={"daily_cost_cap_cents": 1234}))
    assert out["config"]["daily_cost_cap_cents"] == 1234, out["config"]
    async with get_session() as s:
        assert (await s.get(AccountAiConfig, aid)).daily_cost_cap_cents == 1234

    try:
        await put_account_config(_ConfigBody(account_id=aid, config={"daily_cost_cap_cents": 10_001}))
        raise AssertionError("a cap over $100/day was accepted")
    except HTTPException as e:
        assert (e.status_code, e.detail) == (
            422, "daily_cost_cap_cents must be at most 10000 ($100/day)"), e.detail
    c = (await put_account_config(_ConfigBody(account_id=aid, config={"persona": "hi"})))["config"]
    assert c["daily_cost_cap_cents"] == 1234, c

    tok_u = auth._request_user.set(None)
    tok_c = chatters._request_chatter.set(chatters.ChatterIdentity(
        "c-cap", "cap_chatter", None, None, frozenset({"u-cap"}), frozenset({aid})))
    try:
        c = (await put_account_config(_ConfigBody(account_id=aid, config={
            "persona": "by chatter", "daily_cost_cap_cents": 5})))["config"]
    finally:
        auth._request_user.reset(tok_u)
        chatters._request_chatter.reset(tok_c)
    assert c["persona"] == "by chatter" and c["daily_cost_cap_cents"] == 1234, c

    aid2 = "acc_bc_cap_fresh"
    await _seed_account(aid2)
    c = (await put_account_config(_ConfigBody(account_id=aid2, config={"persona": "x"})))["config"]
    assert c["daily_cost_cap_cents"] == 100, c

    day = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session() as s:
        s.add(GrokDailyCost(day=day, account_id=aid, provider="deepseek", cost_cents=4200,
                            call_count=3, is_capped=False))
        s.add(GrokDailyCost(day=day, account_id=aid, provider="deepinfra", cost_cents=99,
                            call_count=1, is_capped=True))
        s.add(GrokDailyCost(day="2000-01-01", account_id=aid, provider="deepseek",
                            cost_cents=1, call_count=1, is_capped=False))
    resp = await get_account_config(account_id=aid)
    assert resp["ai_spend_today"] == {"day": day, "providers": [
        {"provider": "deepinfra", "spent_millicents": 99, "flagged": True},
        {"provider": "deepseek", "spent_millicents": 4200, "flagged": False}]}, resp["ai_spend_today"]
    assert "ai_spend_today" not in resp["config"]
    assert (await get_account_config(account_id=aid2))["ai_spend_today"]["providers"] == []


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
    case_help_assistant_default_is_opus_only_where_anthropic_is_keyed,
    case_a_json_purpose_refuses_a_model_that_cannot_return_json,
    case_model_notes_roundtrip_and_sparse,
    case_daily_cost_cap_put_roundtrip_bound_and_owner_only,
)
