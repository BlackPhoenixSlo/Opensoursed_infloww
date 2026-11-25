#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import automation_rules_api as rules_api  # noqa: E402
import automations.welcome_chatter_for_info as wc  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations._common import content_payer_fans  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    AutomationRule, ContentOffer, Fan, Message, SkipList, VaultSend,
)
from _gc_fixtures import (  # noqa: E402
    _FOLDER, _T0, _add_msgs, _patch_llm, _seed_account,
    _seed_fan, _seed_photos, _seed_tx, _use_fake,
)



async def case_ledger_only_buyer_is_content_payer():
    aid = "acc_ledger1"
    await _seed_account(aid)
    for fid in (71, 72, 73, 74):
        await _seed_fan(aid, fid)
    await _seed_tx(aid, 71, "ppv_message", status="pending")
    await _seed_tx(aid, 72, "subscription", cents=600, status="cleared")
    await _seed_tx(aid, 72, "rebill", cents=600, status="cleared")
    await _seed_tx(aid, 73, "ppv_message", status="chargedback")
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=74, message_id=74900,
                      direction="out", body="unlock me", is_paid=True,
                      price_cents=500, created_at=_T0))

    got = await content_payer_fans(aid, [71, 72, 73, 74])
    assert got == {71, 74}, got



async def case_too_long_cut_sends_no_ppv():
    aid = "acc_gc1"
    await _seed_account(aid)
    await _seed_fan(aid, 7001)
    await _add_msgs(aid, 7001, [("in", f"msg {i}") for i in range(10)])
    await _seed_photos(aid, [501, 502, 503])
    fake = _use_fake(_FOLDER)
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    assert res["closing_ppvs_sent"] == 0, res
    assert res["replies_sent"] == 0, res
    assert res["newly_skiplisted"] == 1, res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 7001))
        assert sk is not None and sk.reason == "too_long", sk
        offers = (await s.execute(
            select(ContentOffer).where(ContentOffer.account_id == aid,
                                       ContentOffer.fan_id == 7001)
        )).scalars().all()
        assert offers == [], offers


async def case_info_graduation_sends_no_ppv():
    aid = "acc_gc5"
    await _seed_graduate(aid, 7401)
    await _seed_photos(aid, [501, 502, 503])
    fake = _use_fake(_FOLDER)
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["closing_ppvs_sent"] == 0, res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 7401))
        assert sk is not None and sk.reason == "info", sk




_CLOSING = {"closing_ppv_text": "a little goodbye gift before my team takes over 😘",
            "closing_ppv_media_ids": [501, 502], "closing_ppv_price_cents": 1500}


async def _seed_graduate(aid: str, fan_id: int) -> None:
    await _seed_account(aid)
    await _seed_fan(aid, fan_id)
    await _add_msgs(aid, fan_id, [("in", "hey")])
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan_id))
        f.real_name = "Jack"; f.his_age = "31"; f.home_city = "Austin"
        f.home_country = "USA"; f.hobbies = "hiking"; f.occupation = "engineer"
        f.likes_boobs = True; f.recent_events = '["a trip"]'; f.fetishes = "feet"
        f.questions_asked = json.dumps(
            ["name", "age", "location", "country_from_city", "city",
             "job", "hobbies", "boobs_ass", "recent_events"])


async def _seed_runaway(aid: str, fan_id: int, n: int = 10) -> None:
    await _seed_account(aid)
    await _seed_fan(aid, fan_id)
    await _add_msgs(aid, fan_id, [("in", f"msg {i}") for i in range(n)])


async def _seed_rule(aid: str, steps: dict) -> int:
    async with get_session() as s:
        rule = AutomationRule(account_id=aid, name="wc", kind="welcome_chatter_for_info",
                              trigger_json='{"every_seconds": 60}',
                              steps_json=json.dumps(steps), is_enabled=True)
        s.add(rule)
        await s.flush()
        return rule.id


def _assert_one_closing_ppv(fake, fan_id: int) -> None:
    assert len(fake.sent) == 1, fake.sent
    chat, text, kw = fake.sent[0]
    assert chat == fan_id, fake.sent
    assert text == _CLOSING["closing_ppv_text"], text
    assert kw.get("media_files") == [501, 502], kw
    assert kw.get("price") == 15.0, kw


async def _assert_closed(aid: str, fan_id: int, reason: str) -> None:
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, fan_id))
        assert sk is not None and sk.reason == reason, sk
        f = await s.get(Fan, (aid, fan_id))
        assert f.gather_close_at is not None, "once-per-fan stamp missing"
        out = (await s.execute(
            select(Message).where(Message.account_id == aid,
                                  Message.fan_id == fan_id,
                                  Message.direction == "out")
        )).scalars().all()
        assert len(out) == 1 and out[0].price_cents == 1500, \
            [(m.body, m.price_cents) for m in out]
        assert out[0].automation_kind == "welcome_chatter_for_info", out[0].automation_kind


async def case_too_long_cut_sends_closing_ppv():
    aid = "acc_gc_cp1"
    await _seed_runaway(aid, 7501)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
    assert res["status"] == "ok", res
    assert res["closing_ppvs_sent"] == 1, res
    assert res["newly_skiplisted"] == 1, res
    _assert_one_closing_ppv(fake, 7501)
    await _assert_closed(aid, 7501, "too_long")

    async with get_session() as s:
        await s.delete(await s.get(SkipList, (aid, 7501)))
    await _add_msgs(aid, 7501, [("in", "still here")], base=500)
    res = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
    assert res["closing_ppvs_sent"] == 0, res
    assert len(fake.sent) == 1, fake.sent


async def case_info_graduation_sends_closing_ppv():
    aid = "acc_gc_cp2"
    await _seed_graduate(aid, 7502)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
    assert res["closing_ppvs_sent"] == 1, res
    _assert_one_closing_ppv(fake, 7502)
    await _assert_closed(aid, 7502, "info")


async def case_closing_ppv_read_off_the_rule_on_a_w7_job():
    aid = "acc_gc_cp3"
    await _seed_graduate(aid, 7503)
    rid = await _seed_rule(aid, _CLOSING)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload={"only_fan_ids": [7503], "_rule_id": rid})
    assert res["status"] == "ok", res
    assert res["closing_ppvs_sent"] == 1, res
    _assert_one_closing_ppv(fake, 7503)
    await _assert_closed(aid, 7503, "info")


async def case_closing_ppv_skips_media_he_owns():
    aid = "acc_gc_cp4"
    await _seed_graduate(aid, 7504)
    async with get_session() as s:
        s.add(VaultSend(account_id=aid, fan_id=7504, media_id=502,
                        price_cents=900, was_purchased=True))
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
    assert res["closing_ppvs_sent"] == 0, res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 7504))
        assert sk is not None and sk.reason == "info", sk
        assert (await s.get(Fan, (aid, 7504))).gather_close_at is None


async def case_closing_ppv_send_failure_still_graduates():
    aid = "acc_gc_cp5"
    await _seed_runaway(aid, 7505)
    fake = _use_fake()
    _patch_llm()

    def _boom(chat_id, text, **kw):
        raise RuntimeError("OF 500")
    fake.send_message = _boom

    res = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
    assert res["status"] == "ok", res
    assert res["closing_ppvs_sent"] == 0, res
    assert res["newly_skiplisted"] == 1, res
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 7505))
        assert sk is not None and sk.reason == "too_long", sk
        assert (await s.get(Fan, (aid, 7505))).gather_close_at is None


async def case_closing_ppv_dry_run_sends_nothing_and_keeps_him():
    aid = "acc_gc_cp6"
    await _seed_graduate(aid, 7506)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload={**_CLOSING, "dry_run": True})
    assert res["closing_ppvs_sent"] == 1, res
    assert fake.sent == [], fake.sent
    async with get_session() as s:
        assert await s.get(SkipList, (aid, 7506)) is None
        assert (await s.get(Fan, (aid, 7506))).gather_close_at is None


async def case_closing_ppv_defaults_when_only_media_picked():
    aid = "acc_gc_cp7"
    await _seed_graduate(aid, 7507)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload={"closing_ppv_media_ids": [501, 502]})
    assert res["closing_ppvs_sent"] == 1, res
    assert len(fake.sent) == 1, fake.sent
    _, text, kw = fake.sent[0]
    assert text == wc._CLOSING_PPV_DEFAULT_TEXT, text
    assert kw.get("media_files") == [501, 502] and kw.get("price") == 10.0, kw


async def case_custom_cutoff_sends_closing_ppv_at_its_count():
    aid = "acc_gc_cut1"
    await _seed_runaway(aid, 7601, n=5)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload={**_CLOSING, "max_fan_messages": 5})
    assert res["closing_ppvs_sent"] == 1, res
    assert res["replies_sent"] == 1 and res["newly_skiplisted"] == 1, res
    _assert_one_closing_ppv(fake, 7601)
    await _assert_closed(aid, 7601, "too_long")


async def case_custom_cutoff_default_leaves_him_chatting():
    aid = "acc_gc_cut2"
    await _seed_runaway(aid, 7602, n=5)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
    assert res["closing_ppvs_sent"] == 0 and res["newly_skiplisted"] == 0, res
    assert fake.sent and all("price" not in kw for _, _, kw in fake.sent), fake.sent
    async with get_session() as s:
        assert await s.get(SkipList, (aid, 7602)) is None


async def case_custom_cutoff_read_off_the_rule_on_a_w7_job():
    aid = "acc_gc_cut3"
    await _seed_runaway(aid, 7603, n=5)
    rid = await _seed_rule(aid, {"max_fan_messages": 5,
                                 "closing_ppv_media_ids": [501, 502]})
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info",
                         payload={"only_fan_ids": [7603], "_rule_id": rid})
    assert res["closing_ppvs_sent"] == 1, res
    assert len(fake.sent) == 1 and fake.sent[0][2].get("price") == 10.0, fake.sent
    async with get_session() as s:
        sk = await s.get(SkipList, (aid, 7603))
        assert sk is not None and sk.reason == "too_long", sk


def case_catalog_defaults_match_the_engine():
    knobs = {k["key"]: k for k in rules_api._CATALOG["welcome_chatter_for_info"]["knobs"]}
    assert knobs["closing_ppv_text"]["default"] == wc._CLOSING_PPV_DEFAULT_TEXT
    assert knobs["closing_ppv_price_cents"]["default"] == wc._CLOSING_PPV_DEFAULT_PRICE_CENTS
    assert knobs["closing_ppv_text"].get("prefill") and knobs["closing_ppv_price_cents"].get("prefill")
    cut = knobs["max_fan_messages"]
    assert (cut["default"], cut["min"], cut["max"]) == (
        wc._MAX_FAN_MESSAGES, wc._FAN_MESSAGES_MIN, wc._FAN_MESSAGES_MAX), cut


async def case_closing_ppv_save_validation():
    v = rules_api._validate_payload_for_kind
    for bad in ({"closing_ppv_media_ids": [501], "closing_ppv_price_cents": 299},
                {"closing_ppv_media_ids": [501], "closing_ppv_price_cents": 20_001},
                {"closing_ppv_media_ids": list(range(1, 42))},
                {"max_fan_messages": 2}, {"max_fan_messages": 101},
                {"max_fan_messages": "10"}):
        try:
            v("welcome_chatter_for_info", bad)
        except HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError(f"{bad} saved")
    ok = v("welcome_chatter_for_info", dict(_CLOSING))
    assert ok["closing_ppv_media_ids"] == [501, 502], ok
    assert v("welcome_chatter_for_info", {"closing_ppv_media_ids": [501]}) == \
        {"closing_ppv_media_ids": [501]}
    assert v("welcome_chatter_for_info", {"max_fan_messages": 25}) == {"max_fan_messages": 25}
    off = v("welcome_chatter_for_info", {"closing_ppv_price_cents": 1500})
    assert off == {"closing_ppv_price_cents": 1500}, off



async def case_capped_account_still_cuts_and_skiplists_but_calls_no_llm():
    from datetime import datetime
    from db.models import GrokDailyCost
    import llm_client
    aid = "acc_gc_capped"
    await _seed_runaway(aid, 7701)
    await _seed_fan(aid, 7702)
    await _add_msgs(aid, 7702, [("in", "hey")])
    await _seed_fan(aid, 7703)
    await _add_msgs(aid, 7703, [("in", "hi")])
    await _seed_tx(aid, 7703, "ppv_message", status="pending")
    model = await wc.resolve_model(aid, wc._PURPOSE, None)
    async with get_session() as s:
        s.add(GrokDailyCost(
            day=datetime.utcnow().strftime("%Y-%m-%d"), account_id=aid,
            provider=llm_client.budget_key(wc._PURPOSE), cost_cents=10**9,
            call_count=1, is_capped=True, updated_at=datetime.utcnow()))
    fake = _use_fake()

    async def _no_llm(**kw):
        raise AssertionError(f"a capped run called the LLM: {kw.get('purpose')}")
    saved = llm_client.chat
    llm_client.chat = _no_llm
    async def _no_gather(*a, **k):
        raise AssertionError("a capped sweep gathered")
    saved_gather = wc._gather
    try:
        wc._gather = _no_gather
        swept = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
        assert swept["status"] == "ok" and "llm_capped" in swept, swept
        wc._gather = saved_gather
        res = await run_once(aid, "welcome_chatter_for_info",
                             payload={**_CLOSING, "only_fan_ids": [7701, 7702, 7703]})
    finally:
        llm_client.chat, wc._gather = saved, saved_gather
    assert res["status"] == "ok" and res["cap_hit"] is True, res
    assert res["closing_ppvs_sent"] == 1 and res["newly_skiplisted"] == 2, res
    _assert_one_closing_ppv(fake, 7701)
    await _assert_closed(aid, 7701, "too_long")
    async with get_session() as s:
        assert (await s.get(SkipList, (aid, 7703))).reason == "spent"
        assert await s.get(SkipList, (aid, 7702)) is None

_harness.run()
