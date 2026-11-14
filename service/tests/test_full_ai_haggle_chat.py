#!/usr/bin/env python3
"""test_full_ai_haggle_chat — haggle and the unasked offer at the Test chat API (phase 03b,
ticket 47 phase B2): the DRAFT `counter_offer` / `offer_moment` count only in a `draft_questions`
window of the test Mode.

`POST /admin/full-ai/test/turn` and `POST /admin/full-ai/test/settle` over the shared selling
helpers (`_full_ai_sell_helpers`: two-Agency fixture, owner session cookies, a seeded vault) and
fakes at the network edges only (Jev at `_router_jev._client` / `_info_jev._client`, the Writers at
`llm_client.httpx.AsyncClient`). Every request runs inside `_guarded`. Vault `PRICED`: Heat 3 sells
the $50 photo 202 (list 5000, the haggle floor $34 = ceil(0.67 x $50)).

Haggle:
  case_haggle_reoffers_at_clamped_quote  open Offer 202 at $50 + counter_offer -> row `haggle`, the
                                         same piece (no fresh pick) at clamp_quote(list, his amount):
                                         $20 -> $34 (floor, OLD-CORE-33 `was_cents` block), $60 ->
                                         $50 (plain block), no amount / two amounts / tip -> $34,
                                         $40 -> $40; `offer_list_cents` 5000, PPV at the quote
  case_haggle_draft_off_drops            draft_questions off -> `counter_offer` in `dropped`, chat
  case_haggle_needs_an_open_offer        no open Offer, no Pending tease -> no haggle, no pick
  case_haggle_on_a_pending_tease         tease 202 then "$20?" -> the teased piece at $34, plain
                                         price block (the tease named no price)
  case_haggle_offer_beats_tease          open Offer 202 + a newer tease of 101 -> the Offer's piece
  case_haggle_repick_capped_at_list      202 gone -> a re-pick at or under $50 (never Heat 4's $100),
                                         at its own list, plain block, declining it leaves no open
                                         Offer (the $50 stays superseded); nothing under $50 -> Refusal
  case_haggle_again_clamps_against_list  a haggle on the haggle row: "$20" -> $34 again (list, never
                                         the $34 quote's own floor $23)
  case_buy_after_haggle                  Buy the haggle row -> settles at $34; next Turn: spend line
                                         $34, `pending_offer` none (the $50 Offer is superseded),
                                         202 never sold again; Buy the superseded $50 row instead ->
                                         the haggle row (an owned piece) is not open either
  case_concurrent_buys_settle_once       Buy on the $50 Offer and its haggle row at once -> one
                                         settles, the other `already_owned`
  case_haggle_audit_holds_the_quote      a caption naming the list $50 fails the price check ->
                                         rewrite; twice -> fallback caption at $34

Unasked offer (offer_moment):
  case_offer_moment_sells                offer_moment -> sell_now row `offer_moment`, OLD-AIC-05 beat
  case_hot_sell_gets_step_4              sexual_now beside offer_moment or wants_content -> OLD-AIC-08
                                         + its step 4 as the beat; with sext off -> the plain beat
  case_offer_moment_gated                sell off -> chat, no sell-off line, no PPV (with sexual_now:
                                         sext); draft_questions off -> `offer_moment` in `dropped`

Shadow: test_full_ai_shadow.py and the router golden stay untouched (Shadow's `fired` passes no
Mode, its `draft_on` is false).

Run: ./venv/bin/python service/tests/test_full_ai_haggle_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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
    """One test turn under the invariants: (response json, Writer fake, Pick results, Router fake)."""
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
    """A's draft side with `cfg` over DEFAULTS (through the config API), DEFAULTS again after."""
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
    """Turn 1: he asks, Heat 3 sells the $50 photo 202."""
    got, _, _, _ = _turn(_body(pair, PICS), "ok:mm i have something for u", (_hot(wants_content=0.9), 2.0))
    assert got["offer"]["ref"] == 202 and got["offer"]["price_cents"] == 5000, got["offer"]
    return got


def _haggle_checks(got: dict, pair: str, n: int, price: int) -> None:
    """Row `n` is a haggle re-offer of 202 at `price`, list 5000, its PPV at `price`."""
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
    assert item.get("over") == (offers[-1].id if offers else None), item     # the Offer it re-offers


# ── Haggle ────────────────────────────────────────────────────────────

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
    with _draft(sell_on=True), _vault(PRICED):
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
    """The tease (Heat 3: 202, priceless) then "$20?" -> the teased piece at $34, list 5000, the
    plain price block (`was_cents_of`: he never saw a price on a tease)."""
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
    """202 left the vault: the haggle re-picks the same subject and format at Heat 4 but only from
    pieces listed at or under the haggled $50, so 101 ($10) not 303 ($100), at min(own list, $34)
    with its own list and the plain block (a piece he never saw); only 303 left -> Refusal."""
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
        assert fj.calls[0]["state"]["pending_offer"] == "none", fj.calls[0]["state"]   # $50 superseded
        assert "$34 total" in fw.requests[0]["body"]["messages"][1]["content"]
        sold, _, _, _ = _turn(_body(pair, PICS, n=4), "ok:mm i have something for u",
                              (_hot(wants_content=0.9), 2.0))
    rows = _rows(pair)
    assert (rows[1].outcome, rows[1].offer_price_cents) == ("bought", 3400), rows[1]
    assert rows[0].outcome is None, rows[0]                 # the superseded $50 Offer stays unsettled
    assert sold["offer"]["ref"] == 101, sold["offer"]       # 202 is Owned: the next piece sells
    pair = "h-buy-superseded"                               # Buy the superseded $50 row instead
    with _haggling(), _vault(PRICED):
        first = _offer_50(pair)
        _turn(_body(pair, TWENTY, n=2), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))
        assert _settle(pair, first["row_id"], "bought").status_code == 200
        again = _settle(pair, _rows(pair)[1].id, "bought")       # the haggle row holds the same piece
        assert (again.status_code, again.json()) == (422, {"detail": "already_owned"}), again.text
        _, _, _, fj = _turn(_body(pair, "mm thanks babe", n=3), "ok:hope u liked it", (QUIET, 1.0))
        assert fj.calls[0]["state"]["pending_offer"] == "none", fj.calls[0]["state"]   # he owns 202
        sold, _, _, _ = _turn(_body(pair, PICS, n=4), "ok:mm i have something for u",
                              (_hot(wants_content=0.9), 2.0))
    assert sold["offer"]["ref"] == 101 and _rows(pair)[1].outcome is None, sold["offer"]


def case_concurrent_buys_settle_once():
    """Buy on the $50 Offer and on its haggle re-offer (the same piece 202) at once: one settles,
    the other is `already_owned`; one bought row."""
    pair = "h-buy-race"
    with _haggling(), _vault(PRICED):
        first = _offer_50(pair)
        hag, _, _, _ = _turn(_body(pair, TWENTY, n=2), f"ok:{OK_TEXT}", (_hot(counter_offer=0.9), 2.0))

    real = full_ai_test.get_session

    @contextlib.asynccontextmanager
    async def slow_reads():
        """Each settle's reads take a moment, so both Buys read before either writes."""
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
    """The prompt allows exactly the quote: a caption naming the list $50 fails the price check."""
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


# ── Unasked offer (offer_moment) ──────────────────────────────────────

def case_offer_moment_sells():
    pair = "m-sell"
    with _haggling(), _vault(PRICED):
        got, fw, (pick,), _ = _turn(_body(pair, "u look so good today"), "ok:mm wanna see more?",
                                    (_hot(offer_moment=0.9), 2.0))
    assert (got["route"], got["route_row"]) == ("sell_now", "offer_moment"), got
    assert got["offer"]["ref"] == pick.ref == 202 and got["offer"]["price_cents"] == 5000, got["offer"]
    assert _ppvs(got["parts"]) == [len(got["parts"]) - 1], got["parts"]
    system = _system(fw)
    assert w.ESCALATION.format(close=w.CLOSE_BY_ID) in system, system
    assert w.CONTENT_ASK.format(close=w.CLOSE_BY_ID) not in system and w.SELL_STEP[:20] not in system
    assert w.PRICE_BLOCK.format(px="$50") in system and "already saw" not in system


def case_hot_sell_gets_step_4():
    step = w.SEXT_HOT + w.SELL_STEP.format(close=w.CLOSE_BY_ID, example=_voice.HER.sell_caption_example)
    for tag, answers, row in (("moment", _hot(offer_moment=0.9, sexual_now=0.9), "offer_moment"),
                              ("ask", _hot(wants_content=0.9, sexual_now=0.9), "sell")):
        pair = f"m-hot-{tag}"
        with _haggling(), _vault(PRICED):
            got, fw, _, _ = _turn(_body(pair, "fuck im so hard"), "ok:mm watch me babe", (answers, 2.0))
        assert (got["route"], got["route_row"]) == ("sell_now", row), (tag, got)
        system = _system(fw)
        assert step in system and _voice.HER.sell_caption_example in system, (tag, system)
        assert w.ESCALATION.format(close=w.CLOSE_BY_ID) not in system, tag
        assert w.SEXT_HEAT.format(heat=got["heat"]) not in system, tag
        assert got["offer"]["ref"] == 202 and _ppvs(got["parts"]), (tag, got)
    with _draft(sell_on=True, draft_questions=True, sext_on=False), _vault(PRICED):
        got, fw, _, _ = _turn(_body("m-hot-sext-off", "fuck im so hard"), "ok:mm wanna see babe",
                              (_hot(offer_moment=0.9, sexual_now=0.9), 2.0))
    assert (got["route"], got["route_row"]) == ("sell_now", "offer_moment"), got
    system = _system(fw)
    assert w.SELL_STEP[:20] not in system and w.ESCALATION.format(close=w.CLOSE_BY_ID) in system, system


def case_offer_moment_gated():
    cases = (("sell-off", dict(draft_questions=True), _hot(offer_moment=0.9),
              ("chat", "otherwise", ["offer_moment"])),
             ("sell-off-hot", dict(draft_questions=True), _hot(offer_moment=0.9, sexual_now=0.9),
              ("sext", "sexual_now", ["offer_moment"])),
             ("draft-off", dict(sell_on=True), _hot(offer_moment=0.9), ("chat", "otherwise", ["offer_moment"])))
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
