#!/usr/bin/env python3
"""
Gather-close PPV + the ledger-aware payer floor — automation tests.

Two features, one incident (Tomas 587103163 / chatter, 2026-08-16):

  * `content_payer_fans` reads the transactions LEDGER as well as `messages`.
    A fan who bought OF's native welcome PPV seconds after subscribing exists
    only in the ledger — the purchased message was never ingested and OF sends
    no purchase event to stamp `is_paid` later. 822 of 2,035 real buyers were
    invisible to the messages-only predicate.
  * The closing PPV: ONE fixed PPV — caption, vault media, price, all from the
    rule (caption and price default) — sent as the lane's last message when it
    is finished with a fan: info gathered or the message cutoff
    (`max_fan_messages`), whichever comes first. The AI never pitches; off until
    media is picked.

  case_ledger_only_buyer_is_content_payer:
      a fan whose only purchase is a ledger row (kind=ppv_message, pending) is
      a content payer; subs/rebills and chargedback rows are not.
  case_too_long_cut_sends_no_ppv / case_info_graduation_sends_no_ppv:
      with no closing PPV configured, the two graduations send nothing priced,
      even with photos in the vault, and the skip_list row still lands.
  case_too_long_cut_sends_closing_ppv / case_info_graduation_sends_closing_ppv:
      configured, each way out sends EXACTLY ONE PPV — the caption verbatim, the
      picked media, the price — then the skip_list row lands; once per fan.
  case_closing_ppv_read_off_the_rule_on_a_w7_job:
      a real-time job carries only `only_fan_ids`; the config comes off the rule.
  case_closing_ppv_defaults_when_only_media_picked:
      media alone → the default caption at the default $10.
  case_custom_cutoff_* : a non-default `max_fan_messages`, from the payload and
      off the rule on a W7 job; the default cutoff leaves the same fan chatting.
  case_catalog_defaults_match_the_engine:
      the editor's prefilled caption/price are the engine's defaults.
  case_closing_ppv_skips_media_he_owns / case_closing_ppv_send_failure_still_graduates
  / case_closing_ppv_dry_run_sends_nothing_and_keeps_him / case_closing_ppv_save_validation

Run: ./venv/bin/python service/tests/test_gather_close.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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
# The bench — FakeOF, the LLM stub, the seeders — lives in _gc_fixtures.
from _gc_fixtures import (  # noqa: E402
    _FOLDER, _T0, _add_msgs, _patch_llm, _seed_account,
    _seed_fan, _seed_photos, _seed_tx, _use_fake,
)


# ── The ledger-aware payer floor ──────────────────────────────────────

async def case_ledger_only_buyer_is_content_payer():
    """The Tomas shape: his $20 welcome-PPV purchase exists ONLY in the ledger
    (the purchased message was never ingested), and he must still count as a
    content payer. Subs/rebills stay non-purchases; a chargedback row is money
    that went back."""
    aid = "acc_ledger1"
    await _seed_account(aid)
    for fid in (71, 72, 73, 74):
        await _seed_fan(aid, fid)
    await _seed_tx(aid, 71, "ppv_message", status="pending")   # the live case
    await _seed_tx(aid, 72, "subscription", cents=600, status="cleared")
    await _seed_tx(aid, 72, "rebill", cents=600, status="cleared")
    await _seed_tx(aid, 73, "ppv_message", status="chargedback")
    # 74 buys the messages-table way (is_paid priced outbound) — still counted.
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=74, message_id=74900,
                      direction="out", body="unlock me", is_paid=True,
                      price_cents=500, created_at=_T0))

    got = await content_payer_fans(aid, [71, 72, 73, 74])
    assert got == {71, 74}, got


# ── The gather-close PPV ──────────────────────────────────────────────

async def case_too_long_cut_sends_no_ppv():
    """No closing PPV configured: photos in the vault do not turn the runaway
    cut into a priced send — nothing goes on the wire and skip_list('too_long')
    lands the same tick."""
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
    """The OTHER way out of the lane — profile complete, every topic asked,
    openers exhausted — with no closing PPV configured graduates him silently:
    no PPV, skip_list('info')."""
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



# ── The closing PPV (configured) ──────────────────────────────────────

_CLOSING = {"closing_ppv_text": "a little goodbye gift before my team takes over 😘",
            "closing_ppv_media_ids": [501, 502], "closing_ppv_price_cents": 1500}


async def _seed_graduate(aid: str, fan_id: int) -> None:
    """A fan the lane is finished with: every topic filled/asked, no openers."""
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
    """A fan still being interviewed with `n` messages in (10 = the default cut)."""
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
    assert text == _CLOSING["closing_ppv_text"], text      # verbatim, no AI
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
    """Configured: the runaway cut's last message is the operator's PPV —
    exactly one, as written — and skip_list('too_long') still lands. Lifting
    the skip row and running again sends nothing more (once per fan)."""
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
    """Configured: the info graduation sends exactly one PPV before
    skip_list('info') lands — no AI reply that tick."""
    aid = "acc_gc_cp2"
    await _seed_graduate(aid, 7502)
    fake = _use_fake()
    _patch_llm()

    res = await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
    assert res["closing_ppvs_sent"] == 1, res
    _assert_one_closing_ppv(fake, 7502)
    await _assert_closed(aid, 7502, "info")


async def case_closing_ppv_read_off_the_rule_on_a_w7_job():
    """A real-time (W7) job carries only `only_fan_ids` + `_rule_id`; the
    closing PPV still goes out, read off the enabled rule's steps_json."""
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
    """He already bought one of the picked media: no PPV (never re-sell what a
    fan owns), no stamp, and he graduates exactly as before."""
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
    """OF refuses the PPV: the graduation is not blocked — skip_list('too_long')
    lands, nothing is stamped or persisted."""
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
    """dry_run counts the would-send but puts nothing on the wire, stamps
    nothing, and leaves the fan in the lane — a preview must not cost him his
    closing PPV."""
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
    """Picking media is all it takes: the default caption at the default $10."""
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
    """`max_fan_messages: 5` cuts a still-interviewed fan at 5 messages — the
    closing PPV, then skip_list('too_long') — where the default (10) would not."""
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
    """The same 5-message fan under the default cutoff is not cut: he gets an
    ordinary (free) reply and stays in the lane."""
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
    """A W7 job carries neither the cutoff nor the PPV: both come off the
    enabled rule — cut at 5, closing PPV at the default caption/price."""
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
    """The editor prefills the catalog defaults; the engine falls back to its
    own. They must be the same values, or the UI shows one PPV and sends another."""
    knobs = {k["key"]: k for k in rules_api._CATALOG["welcome_chatter_for_info"]["knobs"]}
    assert knobs["closing_ppv_text"]["default"] == wc._CLOSING_PPV_DEFAULT_TEXT
    assert knobs["closing_ppv_price_cents"]["default"] == wc._CLOSING_PPV_DEFAULT_PRICE_CENTS
    assert knobs["closing_ppv_text"].get("prefill") and knobs["closing_ppv_price_cents"].get("prefill")
    cut = knobs["max_fan_messages"]
    assert (cut["default"], cut["min"], cut["max"]) == (
        wc._MAX_FAN_MESSAGES, wc._FAN_MESSAGES_MIN, wc._FAN_MESSAGES_MAX), cut


async def case_closing_ppv_save_validation():
    """Saved through the rules API: the price is bounded $3-$200, the cutoff
    3-100, at most 40 media; media alone saves (defaults apply), and clearing
    the media (switching it off) saves."""
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


_harness.run()
