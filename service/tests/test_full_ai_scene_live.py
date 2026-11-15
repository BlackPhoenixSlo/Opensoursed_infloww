#!/usr/bin/env python3
"""test_full_ai_scene_live — the live sext scene proof (06 ticket 98): test = live for sext.

A scripted live session through the job body (`full_ai_live.run`: 04a's loader and sender), OF
faked (`_of_fixtures.VaultOF`), the Router / info Jev / price Jev / Heat check and the Writers faked
at their clients, the purchases feed through the real `poll_purchases`; rows read back from the
temp DB. No paid call, no real OF call.

  case_walk                4 live sext Turns (opening, building, peak, peak): rows live / sext,
                           scene n 1..4 at Jev's stage, heat never down; the Router's state `scene`
                           on Turn k = scene_words(row k-1); the Writer's system holds the stage line
  case_scene_sell_and_purchases  scene_offer .9 + a vault Piece -> sell_now row with an Offer; the
                           fake OF send carries the PPV; item ref has the Piece's desc; the price
                           request's state holds the scene words; bought via the feed -> next Turn's
                           state `purchases` names it, "bought"
  case_sitting_end         newest live row 121 min back -> state scene "none", row n 1
  case_under_18            says_under_18 mid-scene -> no_send, 0 Writer requests, 0 OF sends, scene null
  case_empty               every Writer empty on a sext Turn -> failed, dropped_reason unset/empty, 0 OF sends
  case_heat_check_live     Heat 3, score 4.0 then 3.0 -> the second text sent, regen_ok;
                           the heat client raising -> sent, outcome error
  case_mode_isolation      Shadow / test rows newer than the live rows never reach saved_scene
  case_flags_off           sext_scene off -> no scene question, no scene key, still sext;
                           sext_on off -> no sext row

Run: ./venv/bin/python service/tests/test_full_ai_scene_live.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from _full_ai_sell_helpers import A, FakePriceJev, _vault  # noqa: E402  (two-Agency world, vault of A)
import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import update  # noqa: E402

from _full_ai_fixtures import QUIET_SCENE  # noqa: E402
from _full_ai_live_helpers import NANO, dm_turn, live_rows, reply, seed_live  # noqa: E402
from _of_fixtures import VaultOF  # noqa: E402
import purchase_notifications as pn  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_writers as wr  # noqa: E402
from automations.full_ai_scene import scene_words  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision  # noqa: E402

SCENE_CFG = {"sext_scene": True, "floor_on": True}
HOT = {"sexual_now": .9}
ON = {"scene_on": .9}


class FakeHeatJev:
    """`_heat_jev._client`: pops a score (or an exception) per call; none left -> raises."""

    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    async def system_one(self, state, questions, model=None):
        self.calls.append(state)
        if not self.verdicts:
            raise AssertionError("unscripted heat request")
        v = self.verdicts.pop(0)
        if isinstance(v, Exception):
            raise v
        return SimpleNamespace(scores={"reply_level": SimpleNamespace(
            score=v, probabilities={0: .1, 1: .1, 2: .2, 3: .4, 4: .2})})


def _sys(fw) -> str:
    return "\n".join(x["body"]["messages"][0]["content"] for x in fw.requests if x["host"] == NANO)


async def _turn(aid, fan, mid, text, answers, choices=None, *, intensity=3.0, writer="ok:mm keep going baby",
                heat=None, fake=None, price=None):
    """One live Turn: his DM, the job. (result, fake OF, FakeJev, FakeWriterHTTP, newest row)."""
    res, of, jev, _info, fw = await dm_turn(
        aid, fan, mid, text, jev=({**QUIET_SCENE, **answers}, intensity, choices or {}),
        writers={NANO: writer}, heat=heat, fake=fake, price=price)
    return res, of, jev, fw, (await live_rows(aid, fan))[-1]


async def _age_newest(aid: str, fan: int, minutes: float) -> None:
    row = (await live_rows(aid, fan))[-1]
    async with get_session() as s:
        await s.execute(update(AiDecision).where(AiDecision.id == row.id).values(
            created_at=row.created_at - timedelta(minutes=minutes)))


async def _walk2(aid: str, fan: int, base: int) -> None:
    """Two sext Turns: the scene saved at building, n 2."""
    await _turn(aid, fan, base, "ur making me so hard rn", HOT, {"scene_stage": "opening"})
    await _turn(aid, fan, base + 1, "omg I love it", ON, {"scene_stage": "building"})
    assert reply((await live_rows(aid, fan))[-1])["scene"]["n"] == 2


async def case_walk():
    aid, fan = "fa_scene_walk", 901
    await seed_live(aid, SCENE_CFG)
    steps = [("ur making me so hard rn", HOT, "opening"), ("omg I love it", ON, "building"),
             ("fuck yes", ON, "peak"), ("dont stop", ON, "peak")]
    prev = None
    for k, (text, answers, stage) in enumerate(steps, start=1):
        res, of, jev, fw, row = await _turn(aid, fan, 9010 + k, text, answers, {"scene_stage": stage})
        assert res["row_status"] == "sent" and of.sent, res
        assert (row.mode, row.route, row.status) == ("live", "sext", "sent"), (row.mode, row.route, row.status)
        sc = reply(row)["scene"]
        assert sc["n"] == k and sc["stage"] == stage, sc
        assert prev is None or sc["heat"] >= prev["heat"], (prev, sc)
        st = json.loads(row.jev_json)["state"]
        assert st["scene"] == scene_words(prev), (k, st["scene"], prev)
        assert jev.calls[0]["state"]["scene"] == st["scene"]
        assert wr.SCENE_STAGE[stage] in _sys(fw), (k, stage)
        prev = sc


class _Feed:
    """OF's purchases notifications: one paid-message buy of `mid` by `fan`."""

    def __init__(self, fan, mid, cents):
        self.item = {"id": 910_000_098, "type": "paided_message", "subType": "subscriber_pay_for_chat_message",
                     "createdAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                     "replacePairs": {"{NAME}": "D", "{AMOUNT}": f"${cents / 100:.2f}",
                                      "{MESSAGE_LINK}": f"/chats/chat/{fan}?firstId={mid}"}}

    def get_json(self, path):
        assert "type=purchases" in path, path
        return {"list": [self.item]}


def case_scene_sell_and_purchases():
    R, fan = asyncio.run, 908
    R(seed_live(A, {**SCENE_CFG, "sell_on": True}, exists=True))
    pf = FakePriceJev(1.5)
    with _vault({101: "$10", 202: "$50"}):
        R(_walk2(A, fan, 9080))
        res, of, _j, _fw, row = R(_turn(A, fan, 9083, "fuck yes keep going", {**ON, "scene_offer": .9},
                                        {"scene_stage": "building", "offer_level": "soft"},
                                        writer="ok:i filmed this for u", fake=VaultOF(), price=pf))
        assert (row.mode, row.route, row.route_row, row.status) == ("live", "sell_now", "scene_offer", "sent"), (
            row.route, row.route_row, row.status, reply(row))
        (ppv,) = [m for m in of.sent if "price" in m]
        locked = json.loads(row.offer_media_json)["locked"]
        assert ppv["price"] == row.offer_price_cents / 100 and set(locked) <= set(ppv["media_files"]), (ppv, locked)
        assert row.offer_message_id is not None, row.offer_message_id
        desc = json.loads(row.offer_item_ref).get("desc")
        assert desc, row.offer_item_ref
        (call,) = pf.calls
        # The scene this Turn saves (`facts.scene_now`, as the Test chat): n 3, never a stale "none".
        assert call["scene"] == scene_words(reply(row)["scene"]) == "sexting for 3 of her messages so far, stage: building", call["scene"]
        R(pn.poll_purchases(A, _Feed(fan, row.offer_message_id, row.offer_price_cents)))
        _res, _of, _j, _fw, nxt = R(_turn(A, fan, 9084, "omg that was so hot", ON, {"scene_stage": "peak"}))
    row = R(live_rows(A, fan))[-2]
    assert row.outcome == "bought", row.outcome
    (line,) = json.loads(nxt.jev_json)["state"]["purchases"]
    assert line.startswith("bought ") and desc in line, line


async def case_sitting_end():
    aid, fan = "fa_scene_sitting", 902
    await seed_live(aid, SCENE_CFG)
    await _walk2(aid, fan, 9020)
    await _age_newest(aid, fan, 121)
    _res, _of, _j, fw, row = await _turn(aid, fan, 9029, "keep going", ON, {"scene_stage": "opening"})
    assert json.loads(row.jev_json)["state"]["scene"] == "none", row.jev_json
    assert reply(row)["scene"]["n"] == 1, reply(row)
    assert wr.SCENE_STAGE["opening"] in _sys(fw)


async def case_under_18():
    aid, fan = "fa_scene_u18", 903
    await seed_live(aid, SCENE_CFG)
    await _walk2(aid, fan, 9030)
    res, of, _j, fw, row = await _turn(aid, fan, 9039, "im 16 btw", {**ON, "says_under_18": .9})
    assert row.status == "no_send" and res["row_status"] == "no_send", (row.status, res)
    assert [x for x in fw.requests if x["host"] == NANO] == [] and of.sent == [], (fw.requests, of.sent)
    assert "scene" in reply(row) and reply(row)["scene"] is None, reply(row)


async def case_empty():
    aid, fan = "fa_scene_empty", 904
    await seed_live(aid, SCENE_CFG)
    res, of, _j, fw, row = await dm_turn_all_empty(aid, fan, 9041)
    assert row.status == "failed" and row.route == "sext", (row.status, row.route)
    assert reply(row).get("dropped_reason") in (None, "empty"), reply(row)
    assert of.sent == [], of.sent


async def dm_turn_all_empty(aid, fan, mid):
    from _full_ai_live_helpers import HOSTS
    res, of, jev, _info, fw = await dm_turn(
        aid, fan, mid, "ur so hot", jev=({**QUIET_SCENE, **HOT}, 3.0, {"scene_stage": "opening"}),
        writers=dict.fromkeys(HOSTS, "empty"))
    return res, of, jev, fw, (await live_rows(aid, fan))[-1]


FIRST, SECOND = "ok:i want u so bad right now", "ok:mm come here baby"


async def case_heat_check_live():
    aid, fan = "fa_scene_heat", 905
    await seed_live(aid, {"sext_scene": False, "floor_on": True})
    hf = FakeHeatJev(4.0, 3.0)
    res, of, _j, fw, row = await _turn(aid, fan, 9051, "ur making me so hard", HOT, intensity=2.0,
                                       writer=[FIRST, SECOND], heat=hf)
    parts = reply(row)["parts"]
    assert row.heat == 3 and row.status == "sent" and len(hf.calls) == 2, (row.heat, row.status, hf.calls)
    assert [t for _f, t in _texts(of)] == [p["text"] for p in parts], (of.sent, parts)
    assert "baby" in " ".join(p["text"] for p in parts).lower() and "bad" not in " ".join(
        p["text"] for p in parts).lower(), parts
    assert reply(row)["heat_check"]["outcome"] == "regen_ok", reply(row)["heat_check"]
    aid2 = "fa_scene_heat_err"
    await seed_live(aid2, {"sext_scene": False, "floor_on": True})
    res, of, _j, fw, row = await _turn(aid2, fan, 9052, "ur making me so hard", HOT, intensity=2.0,
                                       writer=FIRST, heat=FakeHeatJev(RuntimeError("jev down")))
    assert row.status == "sent" and len(_texts(of)) == len(reply(row)["parts"]) >= 1, (row.status, of.sent)
    assert reply(row)["heat_check"]["outcome"] == "error", reply(row)["heat_check"]


def _texts(of) -> list[tuple[int, str]]:
    return [(m["fan_id"], m["text"]) for m in of.sent]


async def case_mode_isolation():
    aid, fan = "fa_scene_modes", 906
    await seed_live(aid, SCENE_CFG)
    await _walk2(aid, fan, 9060)
    async with get_session() as s:
        for mode, kind, key in (("shadow", "inbound", "s-1"), ("test", "test", "test:x-L:1")):
            s.add(AiDecision(account_id=aid, fan_id=fan, mode=mode, trigger_kind=kind, trigger_key=key,
                             route="sext", heat=4, route_row="sext", question_version="v", status="sent",
                             reply_json=json.dumps({"scene": {"n": 9, "stage": "peak", "heat": 4}}),
                             jev_json="{}", created_at=datetime.utcnow()))
    _res, _of, _j, _fw, row = await _turn(aid, fan, 9069, "more", ON, {"scene_stage": "building"})
    st = json.loads(row.jev_json)["state"]
    assert st["scene"] == "sexting for 2 of her messages so far, stage: building", st["scene"]
    assert reply(row)["scene"]["n"] == 3, reply(row)


async def case_flags_off():
    aid, fan = "fa_scene_flag_off", 907
    await seed_live(aid, {"sext_scene": False})
    _res, _of, jev, _fw, row = await _turn(aid, fan, 9071, "ur making me so hard", HOT)
    assert not rj.SCENE & set(jev.calls[0]["questions"]), list(jev.calls[0]["questions"])
    assert row.route == "sext" and "scene" not in reply(row), (row.route, reply(row).keys())
    assert "scene" not in json.loads(row.jev_json)["state"]
    aid2 = "fa_scene_sext_off"
    await seed_live(aid2, {"sext_on": False})
    _res, _of, _j, _fw, row = await _turn(aid2, fan, 9072, "ur making me so hard", HOT)
    assert row.route != "sext", row.route


_harness.run()
