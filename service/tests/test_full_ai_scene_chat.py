#!/usr/bin/env python3
"""test_full_ai_scene_chat — the sext scene walked through the Test chat API (config `sext_scene`).

`POST /admin/full-ai/test/turn` + `/settle` with the owner's cookies, a seeded vault, Jev faked at
`_router_jev._client` and `_price_jev._client`, the Writers at their wire; every request inside
`_full_ai_sell_helpers._guarded`.

  case_scene_walk          sext opening -> "omg I love it" (scene_on alone) stays sext, the stage
                           climbs -> scene_offer + offer_level soft -> sell_now on the $10 lane
                           priced by the price Jev ($30) -> Buy -> next scene_offer at "nude" on
                           the $50 lane; the price Jev's error keeps the list price, recorded
  case_flag_off_asks_none  the same Turn with `sext_scene` off: no scene question, no price Jev,
                           no scene on the row

Run: ./venv/bin/python service/tests/test_full_ai_scene_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    A, OWNER_A, _body, _guarded, _post, _put_draft, _reply, _rows, _system, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_fixtures import QUIET_SCENE, QUIET_TEST  # noqa: E402
from automations import _price_jev, full_ai_writers as wr  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402

SETTLE = "/admin/full-ai/test/settle"


class FakePriceJev:
    """`_price_jev._client`: pops a score (or an exception) per call, records the state."""

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
def _draft(scene: bool):
    _put_draft({**DEFAULTS, "sell_on": True, "sext_scene": scene})
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
        # 1. He turns it sexual: Route sext, a new scene at Jev's stage.
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
        # 2. "omg I love it": only scene_on fires, still sext (row scene_on); Jev's stage climbs.
        g2, fw2, _, _ = _turn(pair, 2, "omg I love it", {"scene_on": .9}, {"scene_stage": "building"},
                              "ok:sliding my fingers in rn")
        row2 = _rows(pair)[1]
        assert (row2.route, row2.route_row) == ("sext", "scene_on"), row2.route_row
        assert _reply(row2)["scene"] == {"n": 2, "stage": "building", "heat": 4}, _reply(row2)
        st2 = json.loads(row2.jev_json)["state"]
        assert st2["scene"] == "sexting for 1 of her messages so far, stage: opening", st2
        assert wr.SCENE_STAGE["building"] in _system(fw2)
        # 3. scene_offer at "soft": sell_now on the $10 lane, priced by the price Jev at $30.
        g3, fw3, (p3,), pf3 = _turn(pair, 3, "fuck yes keep going", {"scene_on": .9, "scene_offer": .9},
                                    {"scene_stage": "opening", "offer_level": "soft"},
                                    "ok:i filmed this for u", FakePriceJev(1.5))
        row3 = _rows(pair)[2]
        rp3 = _reply(row3)
        assert row3.route == "sell_now" and row3.route_row == "scene_offer"
        assert p3.lane == "$10" and rp3["level"] == "soft", (p3, rp3)
        assert rp3["scene"] == {"n": 3, "stage": "building", "heat": 4}, rp3      # never backwards
        assert rp3["price"]["list_cents"] == 1000 and rp3["price"]["jev_cents"] == 3000, rp3["price"]
        assert rp3["price"]["error"] is None and rp3["price"]["version"] == _price_jev.PRICE_VERSION
        assert row3.offer_price_cents == 3000 == g3["offer"]["price_cents"], (row3.offer_price_cents, g3)
        assert g3["scene"] == rp3["scene"] and g3["price"] == rp3["price"], g3      # the Turn answer
        (call,) = pf3.calls
        assert call["questions"] == ["price"] and call["state"]["offer"]["level"] == "$10", call
        assert call["state"]["offer"]["list_price"] == "$10", call
        assert wr.SCENE_SELL.split("{close}")[0] in _system(fw3), _system(fw3)
        assert json.loads(row3.offer_item_ref).get("desc"), row3.offer_item_ref
        _settle(pair, row3.id, "bought")
        # 4. Next scene_offer at "nude" -> the $50 lane; the price Jev fails -> the list price stays.
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


_harness.run()
