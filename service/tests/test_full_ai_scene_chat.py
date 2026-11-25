#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_sell_helpers import (  # noqa: E402
    A, OWNER_A, _body, _db, _guarded, _post, _put_draft, _reply, _rows, _system, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import QUIET_SCENE, QUIET_TEST  # noqa: E402
from automations import _price_jev, full_ai_writers as wr  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision  # noqa: E402

SETTLE = "/admin/full-ai/test/settle"


class FakePriceJev:

    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    async def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": list(questions)})
        v = self.verdicts.pop(0)
        if isinstance(v, Exception):
            raise v
        return SimpleNamespace(scores={"price": SimpleNamespace(score=v, probabilities={1: .5, 2: .5})})


@contextlib.contextmanager
def _price(fake):
    real = _price_jev._client
    _price_jev._client = lambda key: fake
    try:
        yield fake
    finally:
        _price_jev._client = real


@contextlib.contextmanager
def _draft(scene: bool, **extra):
    _put_draft({**DEFAULTS, "sell_on": True, "sext_scene": scene, **extra})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


def _turn(pair, n, text, answers, choices, writer, price=None):
    with _price(price or FakePriceJev()) as pf:
        r, fw, picks = _post(_body(pair, text, n=n), writer, jev=({**QUIET_SCENE, **answers}, 3.0, choices))
    return r.json(), fw, picks, pf


def _settle(pair, row_id, outcome):
    with _guarded():
        r = OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "draft",
                                       "row_id": row_id, "outcome": outcome})
    assert r.status_code == 200, r.text


def case_scene_walk():
    pair = "sc-walk"
    with _draft(True), _vault({101: "$10", 202: "$50", 303: "$100"}):
        g1, fw1, picks1, pf1 = _turn(pair, 1, "ur making me so hard rn", {"sexual_now": .9},
                                     {"scene_stage": "opening"}, "ok:mm good.. im in bed rn")
        row1 = _rows(pair)[0]
        assert row1.route == "sext" and picks1 == [] and pf1.calls == [], (row1.route, picks1)
        assert _reply(row1)["scene"] == {"n": 1, "stage": "opening", "heat": 4}, _reply(row1)
        s1 = _system(fw1)
        assert f"{wr.SEXT_SCENE}\n{wr.SCENE_STAGE['opening']}\n{wr.SEXT_HEAT.format(heat=4)}" in s1
        assert wr.EXPLICIT_EARLY not in s1 and "STICKER:" not in s1, s1
        asked = rj.SCENE <= set(json.loads(row1.jev_json)["answers"]) | set(json.loads(row1.jev_json)["choices"])
        assert asked, row1.jev_json
        st1 = json.loads(row1.jev_json)["state"]
        assert st1["scene"] == "none" and st1["purchases"] == [], st1
        g2, fw2, _, _ = _turn(pair, 2, "omg I love it", {"scene_on": .9}, {"scene_stage": "building"},
                              "ok:sliding my fingers in rn")
        row2 = _rows(pair)[1]
        assert (row2.route, row2.route_row) == ("sext", "scene_on"), row2.route_row
        assert _reply(row2)["scene"] == {"n": 2, "stage": "building", "heat": 4}, _reply(row2)
        st2 = json.loads(row2.jev_json)["state"]
        assert st2["scene"] == "sexting for 1 of her messages so far, stage: opening", st2
        assert wr.SCENE_STAGE["building"] in _system(fw2)
        g3, fw3, (p3,), pf3 = _turn(pair, 3, "fuck yes keep going", {"scene_on": .9, "scene_offer": .9},
                                    {"scene_stage": "opening", "offer_level": "soft"},
                                    "ok:i filmed this for u", FakePriceJev(1.5))
        row3 = _rows(pair)[2]
        rp3 = _reply(row3)
        assert row3.route == "sell_now" and row3.route_row == "scene_offer"
        assert p3.lane == "$10" and rp3["level"] == "soft", (p3, rp3)
        assert rp3["scene"] == {"n": 3, "stage": "building", "heat": 4}, rp3
        assert rp3["price"]["list_cents"] == 1000 and rp3["price"]["jev_cents"] == 3000, rp3["price"]
        assert rp3["price"]["error"] is None and rp3["price"]["version"] == _price_jev.PRICE_VERSION
        assert row3.offer_price_cents == 3000 == g3["offer"]["price_cents"], (row3.offer_price_cents, g3)
        assert g3["scene"] == rp3["scene"] and g3["price"] == rp3["price"], g3
        (call,) = pf3.calls
        assert call["questions"] == ["price"] and call["state"]["offer"]["level"] == "$10", call
        assert call["state"]["offer"]["list_price"] == "$10", call
        assert wr.SCENE_SELL.split("{close}")[0] in _system(fw3), _system(fw3)
        assert json.loads(row3.offer_item_ref).get("desc"), row3.offer_item_ref
        _settle(pair, row3.id, "bought")
        g4, _, (p4,), pf4 = _turn(pair, 4, "more pls", {"scene_on": .9, "scene_offer": .9},
                                  {"scene_stage": "peak", "offer_level": "nude"},
                                  "ok:this one is even better", FakePriceJev(RuntimeError("boom")))
        row4 = _rows(pair)[3]
        rp4 = _reply(row4)
        assert p4.lane == "$50" and p4.ref != p3.ref and rp4["level"] == "nude", (p4, rp4)
        assert rp4["price"]["jev_cents"] is None and "boom" in rp4["price"]["error"], rp4["price"]
        assert row4.offer_price_cents == 5000, row4.offer_price_cents
        st4 = json.loads(row4.jev_json)["state"]
        assert st4["purchases"] and st4["purchases"][0].startswith("bought 1 photo for $30 (lane $10)"), st4
        assert pf4.calls[0]["state"]["purchases"] == st4["purchases"], pf4.calls


def _age(row_id: int, minutes: float) -> None:
    async def q():
        async with get_session() as s:
            row = await s.get(AiDecision, row_id)
            row.created_at = row.created_at - timedelta(minutes=minutes)
            await s.commit()
    _db(q)


def _building(pair):
    _turn(pair, 1, "ur making me so hard rn", {"sexual_now": .9}, {"scene_stage": "opening"}, "ok:mm im in bed")
    _turn(pair, 2, "omg I love it", {"scene_on": .9}, {"scene_stage": "building"}, "ok:sliding my fingers in")
    assert _reply(_rows(pair)[1])["scene"] == {"n": 2, "stage": "building", "heat": 4}, _reply(_rows(pair)[1])


def case_sitting_ends_scene():
    pair = "sc-sitting"
    with _draft(True), _vault({101: "$10"}):
        _building(pair)
        _age(_rows(pair)[1].id, 121)
        _, fw, _, _ = _turn(pair, 3, "keep going", {"scene_on": .9}, {"scene_stage": "opening"},
                            "ok:mm where were we")
    row = _rows(pair)[2]
    assert json.loads(row.jev_json)["state"]["scene"] == "none", row.jev_json
    assert _reply(row)["scene"] == {"n": 1, "stage": "opening", "heat": 4}, _reply(row)
    s = _system(fw)
    assert wr.SCENE_STAGE["opening"] in s and wr.SCENE_STAGE["building"] not in s, s


def case_under_18_ends_scene():
    pair = "sc-u18"
    with _draft(True), _vault({101: "$10"}):
        _building(pair)
        _, fw, _, _ = _turn(pair, 3, "im 16 btw", {"scene_on": .9, "says_under_18": .9}, {}, "ok:never sent")
        row = _rows(pair)[2]
        assert row.status == "no_send" and fw.requests == [], (row.status, fw.requests)
        assert "scene" in _reply(row) and _reply(row)["scene"] is None, _reply(row)
        _turn(pair, 4, "ur so hot", {"sexual_now": .9}, {}, "ok:mm")
    row4 = _rows(pair)[3]
    assert json.loads(row4.jev_json)["state"]["scene"] == "none", row4.jev_json
    assert _reply(row4)["scene"]["n"] == 1, _reply(row4)


def case_flag_off_asks_none():
    pair = "sc-off"
    with _draft(False), _vault({101: "$10"}):
        with _price(FakePriceJev()) as pf:
            r, fw, picks = _post(_body(pair, "send me pics"), "ok:i have something",
                                 jev=({**QUIET_TEST, "wants_content": .9}, 3.0))
        row = _rows(pair)[0]
    j = json.loads(row.jev_json)
    assert not rj.SCENE & (set(j["answers"]) | set(j.get("choices") or {})), j
    assert "scene" not in j["state"] and "purchases" not in j["state"], j["state"]
    rp = _reply(row)
    assert "scene" not in r.json() and "price" not in r.json(), r.json()
    assert pf.calls == [] and "scene" not in rp and "price" not in rp and "level" not in rp, rp
    assert wr.SEXT_SCENE not in _system(fw)
    assert "desc" not in json.loads(row.offer_item_ref), row.offer_item_ref


def _signals(fake):
    (call,) = fake.calls
    return call["state"]["he_asked"], call["state"]["bought_before"]


def case_price_he_asked():
    with _draft(True, draft_questions=True, chat_tease=False), _vault({101: "$10", 202: "$50", 303: "$100"}):
        _, _, _, pf = _turn("pa-sell", 1, "send me pics", {"wants_content": .9}, {},
                               "ok:i have something", FakePriceJev(1.0))
        row = _rows("pa-sell")[0]
        assert row.route_row == "sell" and _signals(pf) == ("yes", "no"), (row.route_row, pf.calls)
        rp = _reply(row)["price"]
        assert (rp["he_asked"], rp["bought_before"], rp["jev_cents"]) == ("yes", "no", 2000), rp
        _, _, _, pf = _turn("pa-moment", 1, "u look so good today", {"offer_moment": .9}, {},
                               "ok:wanna see more?", FakePriceJev(1.0))
        row = _rows("pa-moment")[0]
        assert row.route_row == "offer_moment" and _signals(pf) == ("no", "no"), (row.route_row, pf.calls)
        rp = _reply(row)["price"]
        assert (rp["he_asked"], rp["bought_before"]) == ("no", "no"), rp


def case_price_bought_before():
    pair = "pb-order"
    with _draft(True, draft_questions=True), _vault({101: "$10", 202: "$50", 303: "$100"}):
        _, _, _, pf1 = _turn(pair, 1, "send me pics", {"wants_content": .9}, {"offer_level": "soft"},
                             "ok:here", FakePriceJev(1.0))
        _, _, _, pf2 = _turn(pair, 2, "more pls", {"wants_content": .9}, {"offer_level": "explicit"},
                             "ok:here", FakePriceJev(3.0))
        r1, r2 = _rows(pair)
        assert (r1.offer_price_cents, r2.offer_price_cents) == (2000, 5000), (r1.offer_price_cents, r2.offer_price_cents)
        assert _signals(pf1)[1] == "no" and _signals(pf2)[1] == "no", (pf1.calls, pf2.calls)
        _settle(pair, r2.id, "bought")
        _settle(pair, r1.id, "bought")
        _, _, _, pf3 = _turn(pair, 3, "send me another", {"wants_content": .9}, {}, "ok:here", FakePriceJev(4.0))
        assert _signals(pf3) == ("yes", "yes"), pf3.calls
        buys = pf3.calls[0]["state"]["purchases"]
        assert len(buys) == 2 and buys[-1].startswith("bought ") and " for $20 " in buys[-1], buys
        assert " for $50 " in buys[0], buys
        assert _reply(_rows(pair)[2])["price"]["bought_before"] == "yes"


def case_haggle_no_price_jev():
    pair = "ph-haggle"
    with _draft(True, draft_questions=True), _vault({101: "$10", 202: "$50", 303: "$100"}):
        _turn(pair, 1, "send me pics", {"wants_content": .9}, {}, "ok:here", FakePriceJev(3.0))
        _, _, _, pf = _turn(pair, 2, "$20?", {"counter_offer": .9}, {}, "ok:deal babe", FakePriceJev())
        row = _rows(pair)[1]
    assert row.route_row == "haggle" and row.offer_price_cents, (row.route_row, row.offer_price_cents)
    assert pf.calls == [] and "price" not in _reply(row), (pf.calls, _reply(row).get("price"))


def case_tease_resell_keeps_price():
    pair = "pt-resell"
    with _draft(True, draft_questions=True, chat_tease=False), _vault({101: "$10", 202: "$50", 303: "$100"}):
        _, _, _, pf1 = _turn(pair, 1, "how much are ur pics", {"price": .9}, {}, "ok:mm i have a cute set", FakePriceJev())
        r1 = _rows(pair)[0]
        assert r1.route == "tease" and pf1.calls == [], (r1.route, pf1.calls)
        g2, _, picks, pf2 = _turn(pair, 2, "ok send it", {"says_yes_to_offer": .9}, {}, "ok:here u go", FakePriceJev(3.0))
        r2 = _rows(pair)[1]
    assert (r2.route, r2.route_row) == ("sell_now", "sell"), (r2.route, r2.route_row)
    assert pf2.calls == [] and "price" not in _reply(r2), (pf2.calls, _reply(r2).get("price"))
    assert picks == [] and g2["offer"]["media"] == json.loads(r1.offer_media_json)["locked"], (picks, g2)
    assert r2.offer_price_cents == r1.offer_list_cents == g2["offer"]["price_cents"], (r2.offer_price_cents, g2)


def case_price_jev_at_deadline():
    import asyncio

    from automations import full_ai_turn

    class Hang(FakePriceJev):
        async def system_one(self, state, questions, model=None):
            await asyncio.sleep(5)

    pair, real = "pd-deadline", full_ai_turn.turn_bound_s
    full_ai_turn.turn_bound_s = lambda cfg: 1.5
    try:
        with _draft(True, chat_tease=False), _vault({101: "$10", 202: "$50"}):
            g, _, _, _ = _turn(pair, 1, "send me pics", {"wants_content": .9}, {"offer_level": "soft"},
                               "ok:here", Hang())
            row = _rows(pair)[0]
    finally:
        full_ai_turn.turn_bound_s = real
    rp = _reply(row)
    assert "refusal" not in rp and rp["price"]["error"].startswith("TimeoutError"), rp
    assert g["status"] == "sent" and g["offer"]["price_cents"] == 1000 == row.offer_price_cents, g


_harness.run()
