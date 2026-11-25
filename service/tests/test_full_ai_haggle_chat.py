#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_sell_helpers import (  # noqa: E402
    A, NANO, OWNER_A, PICS, PRICED, TURN, _body, _guarded, _hot, _picks, _ppvs, _put_draft, _reply,
    _rows, _system, _vault,
)
import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402

from _full_ai_fixtures import QUIET, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
from automations import _voice, full_ai_sell, full_ai_test, full_ai_writers as w  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402

SETTLE = "/admin/full-ai/test/settle"
TWENTY = "would you do $20?"
OK_TEXT = "ok just for u babe"


def _turn(body: dict, script: dict | str, verdict):
    script = {NANO: script} if isinstance(script, str) else script
    fw = FakeWriterHTTP({NANO: "ok:hii", **script})
    fj = FakeJev(verdict)
    with _guarded(), _picks() as picks, fw.on(), _fake_jev(fj):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return r.json(), fw, picks, fj


def _settle(pair: str, row_id: int, outcome: str):
    with _guarded():
        return OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "draft",
                                          "row_id": row_id, "outcome": outcome})


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


def _haggling():
    return _draft(sell_on=True, draft_questions=True)


def _texts(parts: list[dict]) -> list[str]:
    return [p["text"] for p in parts if "text" in p]


def _offer_50(pair: str) -> dict:
    got, _, _, _ = _turn(_body(pair, PICS), "ok:mm i have something for u", (_hot(wants_content=0.9), 2.0))
    assert got["offer"]["ref"] == 202 and got["offer"]["price_cents"] == 5000, got["offer"]
    return got


def _haggle_checks(got: dict, pair: str, n: int, price: int) -> None:
    assert (got["route"], got["route_row"], got["status"]) == ("sell_now", "haggle", "sent"), got
    assert got["offer"]["kind"] == "offer" and got["offer"]["ref"] == 202, got["offer"]
    assert (got["offer"]["price_cents"], got["offer"]["list_cents"]) == (price, 5000), got["offer"]
    ppv = _ppvs(got["parts"])
    assert ppv == [len(got["parts"]) - 1] and got["parts"][-1]["ppv"]["price_cents"] == price, got["parts"]
    row = _rows(pair)[n - 1]
    assert (row.route_row, row.offer_price_cents, row.offer_list_cents) == ("haggle", price, 5000), row
    item = json.loads(row.offer_item_ref)
    assert item["ref"] == 202 and row.outcome is None, item
    offers = [r for r in _rows(pair)[:n - 1] if r.offer_price_cents]
    assert item.get("over") == (offers[-1].id if offers else None), item



def case_haggle_reoffers_at_clamped_quote():
    cases = (("floor", TWENTY, 3400, True), ("above", "how about $60", 5000, False),
             ("none", "can u do it cheaper", 3400, True), ("mid", "$40?", 4000, True),
             ("two", "$20 or $25?", 3400, True), ("tip", "I'll tip you 20 bucks", 3400, True))
    with _haggling(), _vault(PRICED):
        for tag, line, price, was in cases:
            pair = f"h-{tag}"
            _offer_50(pair)
            got, fw, picks, fj = _turn(_body(pair, line, n=2), f"ok:{OK_TEXT}",
                                       (_hot(counter_offer=0.9), 2.0))
            _haggle_checks(got, pair, 2, price)
            assert picks == [], (tag, picks)                    # the same piece, never a fresh pick
            system = _system(fw)
            px = full_ai_sell._money(price)
            assert f"{px} to unlock" in system, (tag, system)
            was_block = w.WAS_PRICE_BLOCK.format(was="$50", px=px)
            assert (was_block in system) is was, (tag, system)
            assert (w.PRICE_BLOCK.format(px=px) in system) is not was, (tag, system)
            assert w.CONTENT_ASK.format(close=w.CLOSE_BY_ID) in system, tag
            assert fj.calls[0]["state"]["pending_offer"] != "none", fj.calls[0]["state"]
            assert _reply(_rows(pair)[1])["caption_fallback"] is False, tag


def case_haggle_draft_off_drops():
    pair = "h-draft-off"
    with _draft(sell_on=True, draft_questions=False), _vault(PRICED):
        _offer_50(pair)
        got, fw, picks, _ = _turn(_body(pair, TWENTY, n=2), "ok:hehe its worth it babe",
                                  (_hot(counter_offer=0.9), 2.0))
    assert (got["route"], got["route_row"], got["dropped"]) == ("chat", "otherwise", ["counter_offer"]), got
    assert got["offer"] is None and picks == [] and _ppvs(got["parts"]) == [], got
    assert w.SELL_OFF_LINE not in _system(fw)


def case_haggle_needs_an_open_offer():
    pair = "h-no-offer"
    with _haggling(), _vault(PRICED):
        got, _, picks, _ = _turn(_body(pair, TWENTY), "ok:hehe for what babe", (_hot(counter_offer=0.9), 2.0))
    assert (got["route"], got["route_row"], got["dropped"]) == ("chat", "otherwise", []), got
    assert got["offer"] is None and picks == [], got
    (row,) = _rows(pair)
    assert row.offer_price_cents is None and row.offer_list_cents is None


def case_haggle_on_a_pending_tease():
    pair = "h-tease"
    with _haggling(), _vault(PRICED):
        tease, _, _, _ = _turn(_body(pair, "how much?"), "ok:mm its a cute one babe", (_hot(price=0.9), 2.0))
        assert tease["offer"]["kind"] == "tease" and tease["offer"]["ref"] == 202, tease["offer"]
        got, fw, picks, _ = _turn(_body(pair, TWENTY, n=2), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))
    _haggle_checks(got, pair, 2, 3400)
    system = _system(fw)
    assert picks == [] and "already saw" not in system and w.PRICE_BLOCK.format(px="$34") in system, picks


def case_haggle_offer_beats_tease():
    """An open Offer (202, $50) and a newer Pending tease (Heat 2: 101) -> the haggle re-offers the
    open Offer's piece (ticket 47: "the open Offer's piece, else the Pending tease's")."""
    pair = "h-both"
    with _haggling(), _vault(PRICED):
        _offer_50(pair)
        tease, _, _, _ = _turn(_body(pair, "how much for another?", n=2), "ok:mm a cute one babe",
                               (_hot(price=0.9), 1.0))
        assert tease["offer"]["kind"] == "tease" and tease["offer"]["ref"] == 101, tease["offer"]
        got, fw, picks, _ = _turn(_body(pair, TWENTY, n=3), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))
    _haggle_checks(got, pair, 3, 3400)
    assert picks == [] and w.WAS_PRICE_BLOCK.format(was="$50", px="$34") in _system(fw)


def case_haggle_repick_capped_at_list():
    for tag, vault, want in (("cheaper", {101: "$10", 303: "$100"}, 101), ("none", {303: "$100"}, None)):
        pair = f"h-repick-{tag}"
        with _haggling():
            with _vault(PRICED):
                _offer_50(pair)
            with _vault(vault):
                got, fw, picks, _ = _turn(_body(pair, TWENTY, n=2), "ok:hmm let me see babe",
                                          (_hot(counter_offer=0.9), 3.0))
        assert (got["route"], got["route_row"], got["heat"]) == ("sell_now", "haggle", 4), (tag, got)
        system = _system(fw)
        assert "already saw" not in system, (tag, system)
        if want is None:
            assert got["offer"] is None and _ppvs(got["parts"]) == [] and w.FILMING_MORE in system, (tag, got)
            assert _reply(_rows(pair)[1])["refusal"] == "no_match", tag
            continue
        assert [p.ref for p in picks] == [101], (tag, picks)
        assert (got["offer"]["ref"], got["offer"]["price_cents"], got["offer"]["list_cents"]) == (101, 1000, 1000)
        assert w.PRICE_BLOCK.format(px="$10") in system and _ppvs(got["parts"]), (tag, system)
        assert _settle(pair, got["row_id"], "declined").status_code == 200   # the $50 Offer stays superseded
        with _haggling(), _vault(vault):
            _, _, _, fj = _turn(_body(pair, "ok nvm", n=3), "ok:no worries babe", (QUIET, 1.0))
        assert fj.calls[0]["state"]["pending_offer"] == "none", fj.calls[0]["state"]


def case_haggle_again_clamps_against_list():
    pair = "h-again"
    with _haggling(), _vault(PRICED):
        _offer_50(pair)
        first, _, _, _ = _turn(_body(pair, TWENTY, n=2), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))
        _haggle_checks(first, pair, 2, 3400)
        again, fw, _, fj = _turn(_body(pair, "still too much, $20?", n=3), f"ok:{OK_TEXT}",
                                 (_hot(counter_offer=0.9), 2.0))
    _haggle_checks(again, pair, 3, 3400)                    # against $34 the floor would be $23
    assert "$34" in fj.calls[0]["state"]["pending_offer"], fj.calls[0]["state"]   # the newest Offer
    assert w.WAS_PRICE_BLOCK.format(was="$50", px="$34") in _system(fw)


def case_buy_after_haggle():
    pair = "h-buy"
    with _haggling(), _vault(PRICED):
        _offer_50(pair)
        got, _, _, _ = _turn(_body(pair, TWENTY, n=2), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))
        assert _settle(pair, got["row_id"], "bought").status_code == 200
        chat, fw, _, fj = _turn(_body(pair, "mm thanks babe", n=3), "ok:hope u liked it", (QUIET, 1.0))
        assert fj.calls[0]["state"]["pending_offer"] == "none", fj.calls[0]["state"]
        assert "$34 total" in fw.requests[0]["body"]["messages"][1]["content"]
        sold, _, _, _ = _turn(_body(pair, PICS, n=4), "ok:mm i have something for u",
                              (_hot(wants_content=0.9), 2.0))
    rows = _rows(pair)
    assert (rows[1].outcome, rows[1].offer_price_cents) == ("bought", 3400), rows[1]
    assert rows[0].outcome is None, rows[0]
    assert sold["offer"]["ref"] == 101, sold["offer"]
    pair = "h-buy-superseded"
    with _haggling(), _vault(PRICED):
        first = _offer_50(pair)
        _turn(_body(pair, TWENTY, n=2), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))
        assert _settle(pair, first["row_id"], "bought").status_code == 200
        again = _settle(pair, _rows(pair)[1].id, "bought")
        assert (again.status_code, again.json()) == (422, {"detail": "already_owned"}), again.text
        _, _, _, fj = _turn(_body(pair, "mm thanks babe", n=3), "ok:hope u liked it", (QUIET, 1.0))
        assert fj.calls[0]["state"]["pending_offer"] == "none", fj.calls[0]["state"]
        sold, _, _, _ = _turn(_body(pair, PICS, n=4), "ok:mm i have something for u",
                              (_hot(wants_content=0.9), 2.0))
    assert sold["offer"]["ref"] == 101 and _rows(pair)[1].outcome is None, sold["offer"]


def case_concurrent_buys_settle_once():
    pair = "h-buy-race"
    with _haggling(), _vault(PRICED):
        first = _offer_50(pair)
        hag, _, _, _ = _turn(_body(pair, TWENTY, n=2), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))

    real = full_ai_test.get_session

    @contextlib.asynccontextmanager
    async def slow_reads():
        async with real() as s:
            execute = s.execute

            async def slow(*a, **k):
                res = await execute(*a, **k)
                await asyncio.sleep(0.05)
                return res
            s.execute = slow
            yield s

    async def both():
        return await asyncio.gather(*(full_ai_test.settle(A, pair, "draft", rid, "bought")
                                      for rid in (first["row_id"], hag["row_id"])),
                                    return_exceptions=True)
    full_ai_test.get_session = slow_reads
    try:
        with _guarded():
            got = asyncio.run(both())
    finally:
        full_ai_test.get_session = real
    refused = [getattr(g, "reason", repr(g)) for g in got if g is not None]
    assert [r.outcome for r in _rows(pair)].count("bought") == 1, [r.outcome for r in _rows(pair)]
    assert got.count(None) == 1 and refused == ["already_owned"], got


def case_haggle_audit_holds_the_quote():
    pair = "h-audit"
    with _haggling(), _vault(PRICED):
        _offer_50(pair)
        got, fw, _, _ = _turn(_body(pair, TWENTY, n=2),
                              {NANO: ["ok:it was $50 babe", "ok:ok $34 just for u"]},
                              (_hot(counter_offer=0.9), 2.0))
        shipped = " ".join(_texts(got["parts"]))       # the typo throttle may slip a letter
        assert len(fw.requests) == 2 and "$34" in shipped and "$50" not in shipped, got["parts"]
        assert _reply(_rows(pair)[1])["caption_fallback"] is False
        _offer_50(pair2 := "h-audit-2")
        got2, _, _, _ = _turn(_body(pair2, TWENTY, n=2),
                              {NANO: ["ok:it was $50 babe", "ok:still $50 babe"]},
                              (_hot(counter_offer=0.9), 2.0))
    assert _texts(got2["parts"]) == ["1 pic, $34 to unlock"], got2["parts"]
    assert _reply(_rows(pair2)[1])["caption_fallback"] is True
    _haggle_checks(got2, pair2, 2, 3400)



def case_offer_moment_sells():
    """`chat_tease` off: the pitched unasked offer (test Mode: ESCALATION_TEST). The Chat tease (flag
    on) is test_full_ai_ride.py's."""
    pair = "m-sell"
    with _draft(sell_on=True, draft_questions=True, chat_tease=False), _vault(PRICED):
        got, fw, (pick,), _ = _turn(_body(pair, "u look so good today"), "ok:mm wanna see more?",
                                    (_hot(offer_moment=0.9), 2.0))
    assert (got["route"], got["route_row"]) == ("sell_now", "offer_moment"), got
    assert got["offer"]["ref"] == pick.ref == 202 and got["offer"]["price_cents"] == 5000, got["offer"]
    assert _ppvs(got["parts"]) == [len(got["parts"]) - 1], got["parts"]
    system = _system(fw)
    assert w.ESCALATION_TEST.format(close=w.CLOSE_BY_ID) in system, system
    assert w.ESCALATION[:40] not in system, system
    assert w.CONTENT_ASK.format(close=w.CLOSE_BY_ID) not in system and w.SELL_STEP_TEST[:20] not in system
    assert w.PRICE_BLOCK.format(px="$50") in system and "already saw" not in system


def case_hot_sell_gets_step_4():
    # test Mode: the _TEST twins; a hot offer_moment is no Chat tease (`tease_turn`), flag on or off.
    # SELL_STEP_TEST carries no example caption (owner 2026-11-14 "Yes, drop the example line").
    step = w.SEXT_HOT_TEST + w.SELL_STEP_TEST.format(close=w.CLOSE_BY_ID, example=_voice.HER.sell_caption_example)
    for tag, answers, row in (("moment", _hot(offer_moment=0.9, sexual_now=0.9), "offer_moment"),
                              ("ask", _hot(wants_content=0.9, sexual_now=0.9), "sell")):
        pair = f"m-hot-{tag}"
        with _haggling(), _vault(PRICED):
            got, fw, _, _ = _turn(_body(pair, "fuck im so hard"), "ok:mm watch me babe", (answers, 2.0))
        assert (got["route"], got["route_row"]) == ("sell_now", row), (tag, got)
        system = _system(fw)
        assert step in system and _voice.HER.sell_caption_example not in system, (tag, system)
        assert w.ESCALATION_TEST.format(close=w.CLOSE_BY_ID) not in system, tag
        assert w.SEXT_HEAT.format(heat=got["heat"]) not in system, tag
        assert got["offer"]["ref"] == 202 and _ppvs(got["parts"]), (tag, got)
    with _draft(sell_on=True, draft_questions=True, sext_on=False, chat_tease=False), _vault(PRICED):
        got, fw, _, _ = _turn(_body("m-hot-sext-off", "fuck im so hard"), "ok:mm wanna see babe",
                              (_hot(offer_moment=0.9, sexual_now=0.9), 2.0))
    assert (got["route"], got["route_row"]) == ("sell_now", "offer_moment"), got
    system = _system(fw)
    assert w.SELL_STEP_TEST[:20] not in system and w.ESCALATION_TEST.format(close=w.CLOSE_BY_ID) in system, system


def case_offer_moment_gated():
    cases = (("sell-off", dict(draft_questions=True), _hot(offer_moment=0.9),
              ("chat", "otherwise", ["offer_moment"])),
             ("sell-off-hot", dict(draft_questions=True), _hot(offer_moment=0.9, sexual_now=0.9),
              ("sext", "sexual_now", ["offer_moment"])),
             ("draft-off", dict(sell_on=True, draft_questions=False), _hot(offer_moment=0.9), ("chat", "otherwise", ["offer_moment"])))
    for tag, cfg, answers, want in cases:
        pair = f"m-gate-{tag}"
        with _draft(**cfg), _vault(PRICED):
            got, fw, picks, _ = _turn(_body(pair, "u look so good today"), "ok:hehe thank u babe",
                                      (answers, 2.0))
        assert (got["route"], got["route_row"], got["dropped"]) == want, (tag, got)
        assert got["offer"] is None and picks == [] and _ppvs(got["parts"]) == [], (tag, got)
        system = _system(fw)
        # Selling off in test Mode never promises a piece (NO_SELL_OFFERS only with selling on).
        line = {"sell-off": w.SELL_OFF_LINE, "sell-off-hot": w.SELL_OFF_LINE,   # sext Route, no scene (sext_scene off here)
                "draft-off": w.NO_SELL_OFFERS}[tag]
        others = {w.SELL_OFF_LINE, w.SELL_OFF_SCENE, w.NO_SELL_OFFERS} - {line}
        assert line in system and not any(o in system for o in others), (tag, system)


if __name__ == "__main__":
    _harness.run()
