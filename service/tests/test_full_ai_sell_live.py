#!/usr/bin/env python3
"""test_full_ai_sell_live — the live sell tracer (05 ticket 90): he asks, one PPV goes out, he
buys, his next Turn knows it; the fast purchases poll covers live Creators.

Creator A of the two-Agency world (`_full_ai_sell_helpers`) with a live rule and a seeded vault;
the job body (`full_ai_live.run`) per Turn; OF faked (`LiveOF`: vault folders, unsend, PPV kwargs
recorded), purchases fed through the real `purchase_notifications.poll_purchases`; Router, price
Jev and Writers faked at their clients. Temp DB, no paid call, no real OF call.

  case_buy_then_next_turn_knows   Turn 1 sell_now: text bubbles then one PPV at the row's price with
                                  the Pick's media; offer_message_id; vault_sends. Feed the buy ->
                                  Turn 2: row bought (notice), pending_offer none, last_purchase set,
                                  the media not picked again, spend line in the Writer prompt
  case_no_buy_pending_then_yes    Turn 2 a minute later: the Pending offer names the PPV; a yes never
                                  re-sends the same piece
  case_pending_expires_late_buy_settles  24 h + 1 min: no Pending offer; a late buy still settles
  case_haggle_unsends_old         the lower copy goes out, the old PPV is unsent, the old row stays
                                  unsettled and no longer open
  case_tease_follow_through       the live Pending tease; the follow-through PPV is the teased piece
  case_free_item_owned_not_sale   make_right Free item unlocked; next Turn Owned; nothing reads a sale
  case_mass_bought_media_skipped   a paid mass PPV of the Pick's media: never offered again
  case_media_refused              OF refuses the media: no Offer on the row, no Pending offer next
  case_raise_after_send_keeps_offer  send_priced raises after the OF send: unknown, Offer kept, still open
  case_row_diff_vs_test_chat      the same 2-Turn script live vs `/admin/full-ai/test/turn` + fake Buy
  case_fast_poll_live_only        `_seller_account_ids` (fast tier) has the live Creator only; a Shadow rule
                                  makes no OF call and no priced row

Run: ./venv/bin/python service/tests/test_full_ai_sell_live.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    A, OWNER_A, PICS, FakePriceJev, _body, _db, _vault,
)
import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import purchase_notifications as pn  # noqa: E402
import transaction_ingest as ti  # noqa: E402
from _full_ai_fixtures import QUIET  # noqa: E402
from _full_ai_live_helpers import NANO, dm_turn, live_rows, reply, seed_live  # noqa: E402
from _of_fixtures import VaultOF  # noqa: E402
from automations import full_ai_live, full_ai_owned, full_ai_test  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AiDecision, AutomationRule, Message, VaultSend  # noqa: E402

TURN, SETTLE = "/admin/full-ai/test/turn", "/admin/full-ai/test/settle"
CFG = {"sell_on": True, "sext_scene": False, "chat_tease": False, "floor_on": False}
SELL_TEXT = "ok:omg ur so sweet. i have something for u"   # a text bubble, then the captioned PPV
R = asyncio.run


class LiveOF(VaultOF):
    """VaultOF that records unsends."""

    def __init__(self, fail=None):
        super().__init__(fail)
        self.unsent: list[tuple[int, int]] = []

    def unsend_message(self, message_id, with_user_id=None):
        self.unsent.append((int(message_id), int(with_user_id)))
        return {"success": True}


class MediaRejectOF(LiveOF):
    """Refuses any send carrying media (OF's `mediaFiles` 400); text alone lands."""

    def send_message(self, chat_id, text, **kw):
        if kw.get("media_files"):
            from of_client import OFAPIError
            body = {"errors": {"mediaFiles": ["Something wrong with attached media"]}}

            class _Resp:
                status_code = 400

                def json(self):
                    return body
            self.sent.append({"fan_id": int(chat_id), "text": text, "rejected": True, **kw})
            raise OFAPIError("400 " + json.dumps(body), response=_Resp())
        return super().send_message(chat_id, text, **kw)


# ── The purchases feed (test_full_ai_settle_live's twin of test_purchase_notifications) ──

class _Feed:
    def __init__(self, items): self.items = items

    def get_json(self, path):
        assert "type=purchases" in path, path
        return {"list": self.items}


_NID = iter(range(910_000_000, 999_999_999))


def _buy(fan: int, mid: int, cents: int, at: datetime | None = None) -> dict:
    return R(pn.poll_purchases(A, _Feed([{
        "id": next(_NID), "type": "paided_message", "subType": "subscriber_pay_for_chat_message",
        "createdAt": (at or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "replacePairs": {"{NAME}": "D", "{AMOUNT}": f"${cents / 100:.2f}",
                         "{MESSAGE_LINK}": f"/chats/chat/{fan}?firstId={mid}"}}])))


# ── One live Turn ─────────────────────────────────────────────────────

def _turn(fan: int, mid: int, text: str, answers: dict, *, intensity=2.0, choices=None, writer=SELL_TEXT,
          fake=None, price=None):
    """(job result, fake OF, FakeJev, FakeWriterHTTP, newest row)."""
    res, of, jev, _info, fw = R(dm_turn(A, fan, mid, text, jev=({**QUIET, **answers}, intensity, choices or {}),
                                        writers={NANO: writer}, fake=fake or LiveOF(),
                                        price=price or FakePriceJev(None)))
    return res, of, jev, fw, R(live_rows(A, fan))[-1]


def _ppv_sends(of) -> list[dict]:
    return [m for m in of.sent if "price" in m and not m.get("rejected")]


def _texts(of) -> list[dict]:
    return [m for m in of.sent if "price" not in m and not m.get("media_files")]


def _writer_prompt(fw) -> str:
    return json.dumps([x["body"]["messages"] for x in fw.requests if x["host"] == NANO])


async def _vault_sends(fan: int) -> list[VaultSend]:
    async with get_session() as s:
        return list((await s.execute(select(VaultSend).where(
            VaultSend.account_id == A, VaultSend.fan_id == fan).order_by(VaultSend.id))).scalars())


async def _age_fan(fan: int, minutes: float) -> None:
    """Move every live row and chat line of the Fan `minutes` back."""
    async with get_session() as s:
        for r in (await s.execute(select(AiDecision).where(AiDecision.account_id == A, AiDecision.fan_id == fan))).scalars():
            r.created_at -= timedelta(minutes=minutes)
        for m in (await s.execute(select(Message).where(Message.account_id == A, Message.fan_id == fan))).scalars():
            m.created_at -= timedelta(minutes=minutes)


_LIVE = {"rule": None}


def _live_on():
    if _LIVE["rule"] is None:
        _LIVE["rule"] = R(seed_live(A, CFG, exists=True))


def _sell1(fan: int, mid: int, **kw):
    """Turn 1: "send me pics" (wants_content .9) -> sell_now with one PPV."""
    res, of, jev, fw, row = _turn(fan, mid, PICS, {"wants_content": .9}, **kw)
    assert res["row_status"] == "sent" and row.route == "sell_now", (res, row.route, reply(row))
    return res, of, jev, fw, row


# ── Cases ─────────────────────────────────────────────────────────────

def case_buy_then_next_turn_knows():
    _live_on()
    fan = 951
    with _vault({101: "$10", 202: "$50"}):
        _res, of, _j, _fw, r1 = _sell1(fan, 95101)
        (ppv,) = _ppv_sends(of)
        assert of.sent[-1] is ppv and _texts(of) == of.sent[:-1] and len(of.sent) == 2, of.sent   # a text bubble, then the PPV (captioned)
        locked = json.loads(r1.offer_media_json)["locked"]
        assert ppv["price"] == r1.offer_price_cents / 100 and set(locked) <= set(ppv["media_files"]), (ppv, r1.offer_media_json)
        assert r1.offer_message_id is not None and r1.outcome is None, r1.offer_message_id
        vs = R(_vault_sends(fan))
        assert sorted(v.media_id for v in vs) == sorted(locked) and {v.message_id for v in vs} == {r1.offer_message_id}
        _buy(fan, r1.offer_message_id, r1.offer_price_cents)
        # Turn 2 chats: the spend line rides only beside no Pick (full_ai_writers `bare`, rwl fa3 S3).
        _res, _of2, _j2, fw2, r2 = _turn(fan, 95102, "omg ur so hot", {}, writer="ok:mm u like that")
        _res, of3, _j3, _fw3, r3 = _turn(fan, 95103, "more?", {"wants_content": .9})
    r1 = R(live_rows(A, fan))[0]
    assert (r1.outcome, r1.join_src) == ("bought", "notice"), (r1.outcome, r1.join_src)
    st = json.loads(r2.jev_json)["state"]
    assert r2.route == "chat" and st["pending_offer"] == "none", (r2.route, st)
    assert st["last_purchase"] != "none in the last 7 days", st
    assert "unlocked 1 PPV" in _writer_prompt(fw2), _writer_prompt(fw2)
    assert r3.route == "sell_now" and not any(set(locked) & set(m.get("media_files") or []) for m in _ppv_sends(of3)), (r3.route, of3.sent)


def case_no_buy_pending_then_yes():
    _live_on()
    fan = 952
    with _vault({101: "$10", 202: "$50"}):
        _res, of, _j, _fw, r1 = _sell1(fan, 95201)
        locked = set(json.loads(r1.offer_media_json)["locked"])
        R(_age_fan(fan, 1))
        _res, of2, jev2, _fw2, r2 = _turn(fan, 95202, "ok yes send it", {"says_yes_to_offer": .9})
    st = jev2.calls[0]["state"]
    assert st["pending_offer"].startswith(f"locked ${r1.offer_price_cents // 100} message"), st["pending_offer"]
    (ppv2,) = _ppv_sends(of2)                                  # a yes sells: another piece
    assert r2.route == "sell_now" and not locked & set(ppv2["media_files"]), (r2.route, of2.sent, locked)


def case_pending_expires_late_buy_settles():
    _live_on()
    fan = 953
    with _vault({101: "$10", 202: "$50"}):
        _res, _of, _j, _fw, r1 = _sell1(fan, 95301)
        R(_age_fan(fan, 24 * 60 + 1))
        _res, _of2, jev2, _fw2, _r2 = _turn(fan, 95302, "hey again", {})
    assert jev2.calls[0]["state"]["pending_offer"] == "none", jev2.calls[0]["state"]
    _buy(fan, r1.offer_message_id, r1.offer_price_cents)
    R(full_ai_live.run(A, {}, run_id=0))                       # the rule's tick: the sweep settles
    r1 = R(live_rows(A, fan))[0]
    assert r1.outcome == "bought", r1.outcome


def case_haggle_unsends_old():
    _live_on()
    fan = 954
    of = LiveOF()
    with _vault({101: "$10", 202: "$50"}):
        _res, _of, _j, _fw, r1 = _sell1(fan, 95401, fake=of)
        _res, of2, _j2, _fw2, r2 = _turn(fan, 95402, "can u do it for less", {"counter_offer": .9}, fake=of)
    r1 = R(live_rows(A, fan))[0]
    assert r2.route_row == "haggle" and r2.offer_price_cents < r1.offer_price_cents, (r2.route_row, r2.offer_price_cents)
    assert json.loads(r2.offer_item_ref)["over"] == r1.id, r2.offer_item_ref
    assert (r1.offer_message_id, fan) in of2.unsent, of2.unsent
    assert _ppv_sends(of2)[-1]["price"] == r2.offer_price_cents / 100, of2.sent   # the lower copy went out
    assert r1.outcome is None
    rows = R(live_rows(A, fan))
    assert full_ai_owned.open_offer_live(rows, datetime.utcnow()).id == r2.id


def case_tease_follow_through():
    _live_on()
    fan = 955
    with _vault({101: "$10", 202: "$50"}):
        _res, of, _j, _fw, r1 = _turn(fan, 95501, "how much?", {"price": .9}, intensity=1.0,
                                      writer="ok:mm its a cute one babe")
        assert r1.route == "tease" and _ppv_sends(of) == [], (r1.route, of.sent)
        teased = json.loads(r1.offer_media_json)["locked"]
        facts = R(_peek(fan, 95502, "ok"))
        assert facts.tease is not None and list(facts.tease.locked) == sorted(teased), facts.tease
        _res, of2, jev2, _fw2, r2 = _turn(fan, 95502, "ok", {}, writer="ok:here u go babe")
    assert jev2.calls[0]["state"]["pending_offer"] != "none"
    assert r2.route == "sell_now" and json.loads(r2.offer_media_json)["locked"] == teased, (r2.route, r2.offer_media_json)
    (ppv,) = _ppv_sends(of2)
    assert set(teased) <= set(ppv["media_files"]), ppv


async def _peek(fan: int, mid: int, text: str):
    """`load` for his next line without running the Turn (the line is removed after)."""
    from _full_ai_fixtures import _msg
    await _msg(A, fan, mid, "in", text, datetime.utcnow())
    try:
        return await full_ai_live.load(A, fan, None)
    finally:
        async with get_session() as s:
            await s.execute(Message.__table__.delete().where(Message.account_id == A, Message.fan_id == fan,
                                                             Message.message_id == mid))


def case_free_item_owned_not_sale():
    _live_on()
    fan = 956
    _paid_mass(fan, 95600, [999])              # he has bought before: make_right picks a Free item
    with _vault({101: "$10", 202: "$50", 303: "$10"}):
        _res, of, _j, _fw, r1 = _turn(fan, 95601, "this is a scam, nothing came", {"complains_now": .9}, intensity=1.0,
                                      writer="ok:omg sorry babe, here's something on me")
    assert r1.route == "make_right" and r1.offer_price_cents == 0, (r1.route, r1.offer_price_cents, reply(r1))
    free = [m for m in of.sent if m.get("media_files")]
    assert free and all(not m.get("price") for m in free), of.sent
    locked = set(json.loads(r1.offer_media_json)["locked"])
    facts = R(_peek(fan, 95602, "thanks"))
    assert locked <= facts.owned, (locked, facts.owned)
    rows = R(live_rows(A, fan))
    assert all(r.outcome is None for r in rows) and facts.spent and len(facts.spent) == 1, facts.spent


def _paid_mass(fan: int, mid: int, media: list[int]) -> None:
    from _full_ai_fixtures import _msg
    R(_msg(A, fan, mid, "out", "just for u", datetime.utcnow() - timedelta(hours=5), price_cents=1500, is_paid=True,
           purchased_at=datetime.utcnow() - timedelta(hours=4), media_ids=json.dumps(media),
           automation_kind="reply_mass_funnel"))


def case_mass_bought_media_skipped():
    _live_on()
    fan = 957
    _paid_mass(fan, 95700, [101])
    with _vault({101: "$10", 202: "$50"}):
        res, of, _j, _fw, r1 = _turn(fan, 95701, PICS, {"wants_content": .9})
    sends = [m for m in of.sent if m.get("media_files")]
    assert not any(101 in m["media_files"] for m in sends), sends
    assert r1.offer_media_json is None or 101 not in json.loads(r1.offer_media_json)["locked"], r1.offer_media_json
    assert sends or reply(r1).get("refusal") == "no_fresh_media", reply(r1)


def case_media_refused():
    _live_on()
    fan = 958
    with _vault({101: "$10", 202: "$50"}):
        _res, of, _j, _fw, r1 = _turn(fan, 95801, PICS, {"wants_content": .9}, fake=MediaRejectOF())
        assert any(m.get("rejected") for m in of.sent) and _ppv_sends(of) == [], of.sent
        assert r1.offer_item_ref is None and r1.offer_price_cents is None, r1.offer_item_ref
        assert reply(r1).get("offer_dropped") == "media", reply(r1)
        assert len(_texts(of)) == len(reply(r1)["parts"]) - 1 >= 1, (of.sent, reply(r1)["parts"])
        _res, _of2, jev2, _fw2, _r2 = _turn(fan, 95802, "hello?", {})
    assert jev2.calls[0]["state"]["pending_offer"] == "none", jev2.calls[0]["state"]


def case_raise_after_send_keeps_offer():
    """send_priced raises after OF took the PPV (its attribution write): unknown, never a drop —
    the Offer columns stay, the row is linked, the next Turn reads it as the Pending offer."""
    _live_on()
    fan = 962
    from automations import full_ai_ppv
    real = full_ai_ppv.write_outbound_attribution

    async def boom(**kw):
        if kw.get("price_cents"):
            raise RuntimeError("db locked")
        return await real(**kw)
    full_ai_ppv.write_outbound_attribution = boom
    try:
        with _vault({101: "$10", 202: "$50"}):
            _res, of, _j, _fw, r1 = _turn(fan, 96201, PICS, {"wants_content": .9})
    finally:
        full_ai_ppv.write_outbound_attribution = real
    assert len(_ppv_sends(of)) == 1, of.sent
    assert r1.offer_price_cents and r1.offer_message_id is not None, (r1.offer_price_cents, r1.offer_message_id)
    assert "offer_dropped" not in reply(r1) and reply(r1)["cut"]["reason"] == "ppv_unconfirmed", reply(r1)
    assert full_ai_owned.open_offer_live(R(live_rows(A, fan)), datetime.utcnow()).id == r1.id


def _cols(r) -> tuple:
    item = json.loads(r.offer_item_ref) if r.offer_item_ref else None
    return (r.route, r.route_row, r.offer_price_cents, r.offer_list_cents, r.offer_media_json, item, r.outcome)


def case_row_diff_vs_test_chat():
    _live_on()
    fan, pair = 959, "sl-diff"
    jev1 = ({**QUIET, "wants_content": .9}, 2.0)
    with _vault({101: "$10"}):
        _res, _of, _j, _fw, r1 = _sell1(fan, 95901)
        _buy(fan, r1.offer_message_id, r1.offer_price_cents)
        _turn(fan, 95902, "love it", {})
        from _full_ai_fixtures import FakeJev, FakeWriterHTTP, _fake_jev
        from _full_ai_sell_helpers import _price
        for n, (text, jev) in enumerate(((PICS, jev1), ("love it", (QUIET, 2.0))), start=1):
            with FakeWriterHTTP({NANO: SELL_TEXT, "openrouter.ai": SELL_TEXT}).on(), _fake_jev(FakeJev(jev)), \
                    _price(FakePriceJev(None)):
                r = OWNER_A.post(TURN, json=_body(pair, text, side="checkpoint", n=n))
            assert r.status_code == 200, r.text
            if n == 1:
                s = OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "checkpoint",
                                               "row_id": r.json()["row_id"], "outcome": "bought"})
                assert s.status_code == 200, s.text
    live = R(live_rows(A, fan))
    test = _db(lambda: full_ai_test.session_rows(A, pair, "checkpoint"))
    assert [_cols(x) for x in live] == [_cols(x) for x in test], ([_cols(x) for x in live], [_cols(x) for x in test])
    folds = (full_ai_test.owned_of, full_ai_test.sent_media_of, full_ai_test.purchases_of,
             lambda rows: [b.amount_cents for b in full_ai_test.bought_of(rows)])
    assert [f(live) for f in folds] == [f(test) for f in folds]
    assert (live[0].join_src, test[0].join_src) == ("notice", "test")


def case_fast_poll_live_only():
    async def go():
        await seed_live("fa_poll_live", {})
        async with get_session() as s:        # its live full_ai_chat rule only (no selling kind)
            await s.execute(delete(AutomationRule).where(AutomationRule.account_id == "fa_poll_live",
                                                         AutomationRule.kind != "full_ai_chat"))
        async with get_session() as s:        # only a full_ai_chat rule, no `mode`: Shadow
            s.add_all([Account(id="fa_poll_shadow"), Account(id="fa_poll_none")])
            await s.flush()
            s.add(AutomationRule(account_id="fa_poll_shadow", name="Full AI Chat", kind="full_ai_chat",
                                 trigger_json=json.dumps({"every_seconds": 300}), steps_json="{}", is_enabled=True))
        return await ti._seller_account_ids()
    got = R(go())
    assert "fa_poll_live" in got and not {"fa_poll_shadow", "fa_poll_none"} & got, got
    assert R(full_ai_live.live_accounts()) >= {"fa_poll_live"}
    # A Shadow rule: no OF call, no priced row.
    import automation_executor as ax
    import webhook_dispatch as wd
    from _full_ai_fixtures import FakeJev, _fake_jev, _msg, _rows
    made = []
    real_make = ax._make_client
    ax._make_client = lambda aid: made.append(aid)

    async def shadow():
        await _msg("fa_poll_shadow", 960, 96001, "in", PICS, datetime.utcnow())
        with _fake_jev(FakeJev(({**QUIET, "wants_content": .9}, 2.0))):
            await wd.on_inbound_message("fa_poll_shadow", 960, 96001)
            from automation_executor import run_once
            await run_once("fa_poll_shadow", "full_ai_chat")
        return await _rows("fa_poll_shadow")
    try:
        rows = R(shadow())
    finally:
        ax._make_client = real_make
    assert made == [] and rows and all(r.mode == "shadow" and r.offer_item_ref is None for r in rows), rows


_harness.run()
