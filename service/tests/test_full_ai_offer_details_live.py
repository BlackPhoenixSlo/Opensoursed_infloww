#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from _full_ai_fixtures import _msg  # noqa: E402
from _full_ai_fixtures import QUIET  # noqa: E402
from _full_ai_live_helpers import FakeJev, dm_turn, her_reply, live_rows, reply, seed_live  # noqa: E402
from automations import full_ai_live  # noqa: E402
from automations.full_ai_offer_details import resolve_offer  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision  # noqa: E402

NOW = datetime.utcnow


async def _offer_row(aid: str, fan: int, key: int, *, price: int, ago_h: float, omid: int | None) -> int:
    at = NOW() - timedelta(hours=ago_h)
    async with get_session() as s:
        r = AiDecision(
            account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=str(key),
            route="sell_now", heat=1, route_row="sell", question_version="v", status="sent", created_at=at,
            jev_json=json.dumps({"state": {"fan_new_messages": ["show me"]}}),
            reply_json=json.dumps({"parts": [{"text": "for u", "ppv": {"ref": key, "price_cents": price}}]}),
            offer_message_id=omid, offer_price_cents=price, offer_list_cents=price,
            offer_media_json=json.dumps({"locked": [key], "previews": [],
                                         "items": [{"id": key, "kind": "photo", "seconds": None}]}),
            offer_item_ref=json.dumps({"ref": key, "subject": "lingerie", "format": "photo", "lane": "chat",
                                       "kind": "offer"}))
        s.add(r)
        await s.flush()
        return r.id


async def _load(aid: str, fan: int, mid: int, text: str, raw: dict | None = None):
    await _msg(aid, fan, mid, "in", text, NOW(), raw_json=json.dumps(raw) if raw is not None else None)
    facts = await full_ai_live.load(aid, fan, None)
    assert facts is not None and facts.offer_ask is not None
    return facts.offer_ask


async def case_quote_reply_from_raw_frame():
    aid, fan = "fa_od_quote", 811
    await seed_live(aid, {})
    old = await _offer_row(aid, fan, 8111, price=2000, ago_h=3, omid=501)
    await _offer_row(aid, fan, 8112, price=3000, ago_h=1, omid=502)
    ask = await _load(aid, fan, 8113, "this one?", {"id": 8113, "text": "this one?",
                                                   "replyToMessage": {"id": 501, "text": "for u"}})
    assert ask.quote_message_id == 501 and ask.text == "this one?", ask
    got = resolve_offer(ask)
    assert (got.row.id, got.step) == (old, "quote_reply"), got


async def case_other_account_never_resolves():
    aid, other, fan = "fa_od_mine", "fa_od_other", 812
    await seed_live(aid, {})
    await seed_live(other, {})
    theirs = await _offer_row(other, fan, 8121, price=2000, ago_h=1, omid=601)
    ask = await _load(aid, fan, 8122, "the $20 one?", {"replyToMessageId": 601})
    assert ask.quote_message_id == 601 and theirs not in {r.id for r in ask.candidates}, ask
    got = resolve_offer(ask)
    assert (got.row, got.step) == (None, "none"), got


async def case_old_offer_named_by_price():
    aid, fan = "fa_od_old", 813
    await seed_live(aid, {})
    old = await _offer_row(aid, fan, 8131, price=2000, ago_h=30, omid=701)
    ask = await _load(aid, fan, 8132, "what was in the $20 one")
    assert ask.open_ids == frozenset() and ask.quote_message_id is None, ask
    got = resolve_offer(ask)
    assert (got.row.id, got.step) == (old, "price"), got


ASKS = {**QUIET, "asks_offer_details": 0.9}


async def _tease(aid: str, fan: int, key: int) -> int:
    at = NOW() - timedelta(minutes=10)
    async with get_session() as s:
        r = AiDecision(
            account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=str(key),
            route="tease", heat=1, route_row="tease", question_version="v", status="sent", created_at=at,
            jev_json=json.dumps({"state": {"fan_new_messages": ["u got pics?"]}}),
            reply_json=json.dumps({"parts": [{"text": "maybe", "message_id": key + 1},
                                             {"text": "if ur good", "message_id": key + 2}]}),
            offer_list_cents=1500, offer_media_json=json.dumps({"locked": [711], "previews": [701]}),
            offer_item_ref=json.dumps({"ref": "v:711", "subject": "lingerie", "format": "photo", "lane": "chat",
                                       "kind": "tease"}))
        s.add(r)
        await s.flush()
        rid = r.id
    await _msg(aid, fan, key, "in", "u got pics?", at - timedelta(minutes=1))
    for n, text in ((1, "maybe"), (2, "if ur good")):
        await _msg(aid, fan, key + n, "out", text, at, automation_kind="full_ai_chat")
    return rid


async def _next_tease(aid: str, fan: int, mid: int):
    await _msg(aid, fan, mid, "in", "so?", NOW())
    facts = await full_ai_live.load(aid, fan, None)
    assert facts is not None
    return facts.tease


async def case_c_tease_survives_details():
    aid, fan = "fa_od_tease", 821
    await seed_live(aid, {})
    tease = await _tease(aid, fan, 8210)
    await dm_turn(aid, fan, 8220, "is it a pic or a vid?", jev=FakeJev((ASKS, 1.0)))
    row = (await live_rows(aid, fan))[-1]
    parts = reply(row)["parts"]
    assert (row.route, row.route_row, row.status) == ("chat", "offer_details", "sent"), row.route_row
    assert parts and all("ppv" not in p and p.get("message_id") for p in parts), parts
    assert reply(row)["held_tease"] == tease and row.offer_item_ref is None, reply(row)
    got = await _next_tease(aid, fan, 8230)
    assert got is not None and got.row_id == tease, got


async def case_c_human_out_ends_tease():
    aid, fan = "fa_od_human", 822
    await seed_live(aid, {})
    await _tease(aid, fan, 8310)
    await her_reply(aid, fan, 8315, "brb babe")
    await dm_turn(aid, fan, 8320, "is it a pic or a vid?", jev=FakeJev((ASKS, 1.0)))
    row = (await live_rows(aid, fan))[-1]
    assert (row.route_row, row.status) == ("offer_details", "sent"), (row.route_row, row.status)
    assert "held_tease" not in reply(row), reply(row)
    assert await _next_tease(aid, fan, 8330) is None


async def case_c_overtaken_keeps_tease():
    aid, fan, mid = "fa_od_over", 823, 8420
    await seed_live(aid, {})
    tease = await _tease(aid, fan, 8410)

    async def he_writes_again(*_a, **_k):
        if not wrote:
            wrote.append(1)
            await _msg(aid, fan, mid + 1, "in", "and how many?", NOW())
    wrote: list[int] = []
    real = full_ai_live.hold_with_typing
    full_ai_live.hold_with_typing = he_writes_again
    try:
        await dm_turn(aid, fan, mid, "is it a pic or a vid?", jev=FakeJev((ASKS, 1.0)))
    finally:
        full_ai_live.hold_with_typing = real
    row = (await live_rows(aid, fan))[-1]
    assert (row.route_row, row.status) == ("offer_details", "no_send"), (row.route_row, row.status)
    assert reply(row)["stood_down"]["check"] == "overtaken", reply(row)
    got = await _next_tease(aid, fan, mid + 2)
    assert got is not None and got.row_id == tease, got


if __name__ == "__main__":
    _harness.run()
