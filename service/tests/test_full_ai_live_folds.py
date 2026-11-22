#!/usr/bin/env python3
"""test_full_ai_live_folds — live sell / scene folds (04a ticket 70, `full_ai_live.load`).

  case_parity_test_vs_live      one row set seeded as a test session and as live rows: equal
                                owned, sent, purchases, offer_piece, Spacing, Chat tease, scene keys
  case_spend_any_lane           a paid PPV of another Lane (no ai_decisions row) in `spent`; a tip
                                in `tips`, not `spent`; `bought` = the newest; the Writer's spend line
  case_pending_tease            10 min + her newest outbound its bubble -> tease + pending_offer;
                                16 min / another Lane's outbound since / an outcome since -> None
  case_open_offer               priced + offer_message_id -> offer_piece (list price) + pending line;
                                no message id / 24 h + 1 min -> None; bought -> None, media Owned
  case_spacing_one_line_per_turn  Piece row then two live rows -> his lines since = 3
  case_scene                    saved_scene over live rows; unconfirmed newest counts; 121 min -> None
  case_no_live_rows             every fold empty, the Turn runs and sends
  case_null_json_rows           NULL reply_json / jev_json rows (retention) never raise

Run: ./venv/bin/python service/tests/test_full_ai_live_folds.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from _full_ai_fixtures import _msg  # noqa: E402
from _full_ai_live_helpers import NANO, dm_turn, live_rows, seed_live  # noqa: E402
from automations import _router_jev as router  # noqa: E402
from automations import full_ai_live, full_ai_test  # noqa: E402
from automations.full_ai_config import merged  # noqa: E402
from automations.full_ai_writers import spend_line  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Transaction  # noqa: E402

FOLDS = {"sell_spacing": True, "chat_tease": True, "sext_scene": True}
NOW = datetime.utcnow


def _offer(price, locked, previews=(), *, kind="offer", subject="lingerie", fmt="photo", desc=None,
           list_cents=None):
    return {"price": price, "list": list_cents if list_cents is not None else (price or 1000),
            "locked": list(locked), "previews": list(previews),
            "ref": {"ref": f"v:{locked[0] if locked else 0}", "subject": subject, "format": fmt,
                    "lane": "chat", "kind": kind, **({"desc": desc} if desc else {})}}


async def _rows_in(aid: str, fan: int, mode: str, specs: list[dict], *, pair: str | None = None) -> list[int]:
    """Seed `specs` (oldest first) as `mode` rows: each {ago (min), his, parts, route, route_row,
    status, offer, outcome, outcome_ago, omid, scene, part_ids}. Returns the row ids."""
    ids = []
    async with get_session() as s:
        for n, sp in enumerate(specs, start=1):
            at = NOW() - timedelta(minutes=sp.get("ago", 5))
            parts = [{"text": t} for t in sp.get("parts", ["mm ok"])]
            for p, mid in zip(parts, sp.get("part_ids") or []):
                p["message_id"] = mid
            o = sp.get("offer")
            if o and o["ref"]["kind"] != "tease":
                parts[-1]["ppv"] = {"ref": o["ref"]["ref"], "price_cents": o["price"], "media": o["locked"],
                                    "previews": o["previews"]}
            reply = {"parts": parts, **({"scene": sp["scene"]} if "scene" in sp else {})}
            key = (full_ai_test.trigger_key(full_ai_test.session_key(pair, "checkpoint"), n) if mode == "test"
                   else str(sp.get("key", 900_000 + n + abs(hash(aid)) % 10_000 * 100)))
            out_at = (NOW() - timedelta(minutes=sp["outcome_ago"])) if "outcome_ago" in sp else (
                at + timedelta(minutes=1) if sp.get("outcome") else None)
            r = AiDecision(
                account_id=aid, fan_id=full_ai_test.test_fan_id(pair) if mode == "test" else fan, mode=mode,
                trigger_kind="test" if mode == "test" else "inbound", trigger_key=key,
                route=sp.get("route", "chat"), heat=1, route_row=sp.get("route_row", sp.get("route", "chat")),
                question_version="v", status=sp.get("status", "sent"), created_at=at,
                jev_json=json.dumps({"state": {"fan_new_messages": [sp.get("his", "hey")]}}),
                reply_json=json.dumps(reply),
                outcome=sp.get("outcome"), outcome_at=out_at,
                offer_message_id=sp.get("omid") if mode != "test" else None,
                **({"offer_price_cents": o["price"], "offer_list_cents": o["list"],
                    "offer_media_json": json.dumps({"locked": o["locked"], "previews": o["previews"]}),
                    "offer_item_ref": json.dumps(o["ref"])} if o else {}))
            s.add(r)
            await s.flush()
            ids.append(r.id)
    return ids


async def _load(aid: str, fan: int, mid: int, *, at: datetime | None = None):
    await _msg(aid, fan, mid, "in", "so what now", at or NOW())
    return await full_ai_live.load(aid, fan, None)


def _piece(t):
    return None if t is None else replace(t, row_id=None)


SPECS = [
    {"ago": 60, "his": "show me", "route": "sell_now", "route_row": "sell", "offer": _offer(1500, [711, 712], [701]),
     "outcome": "bought", "omid": 81, "scene": {"n": 1, "stage": "opening", "heat": 2}},
    {"ago": 50, "his": "omg", "scene": {"n": 2, "stage": "building", "heat": 3}},
    {"ago": 40, "his": "more", "route": "sell_now", "route_row": "chat_tease",
     # A live Free item is Owned only once OF gave its id (W30 F12: a reaped id-less one was never sent).
     "offer": _offer(0, [713], kind="free"), "omid": 84, "scene": {"n": 3, "stage": "building", "heat": 3}},
    {"ago": 30, "his": "hmm", "route": "sell_now", "route_row": "scene_offer",
     "offer": _offer(2500, [721], [702], fmt="video", desc="her in the shower"), "outcome": "declined", "omid": 82},
    {"ago": 10, "his": "and now?", "route": "sell_now", "route_row": "sell", "offer": _offer(2000, [722]),
     "omid": 83, "scene": {"n": 4, "stage": "peak", "heat": 4}},
]


async def case_parity_test_vs_live():
    aid, fan, pair = "fa_folds_parity", 701, "p-folds-parity"
    await seed_live(aid, FOLDS)
    await _rows_in(aid, fan, "test", SPECS, pair=pair)
    await _rows_in(aid, fan, "live", SPECS)
    cfg = merged({"checkpoint": FOLDS})["checkpoint"]
    t = await full_ai_test.fetch(aid, pair, "checkpoint", "so what now", cfg)
    lv = await _load(aid, fan, 7011)
    assert lv is not None
    for k in ("owned", "sent", "purchases", "scene"):
        assert getattr(t, k) == getattr(lv, k), (k, getattr(t, k), getattr(lv, k))
    assert t.owned == {711, 712, 713} and len(t.purchases) == 2, (t.owned, t.purchases)
    assert _piece(t.offer_piece) == _piece(lv.offer_piece) and lv.offer_piece.list_cents == 2000, lv.offer_piece
    keys = (*router.SPACING_STATE_KEYS, *router.TEASE_STATE_KEYS, "purchases", "scene", "pending_offer")
    assert {k: t.state[k] for k in keys} == {k: lv.state[k] for k in keys}, (
        {k: t.state[k] for k in keys}, {k: lv.state[k] for k in keys})
    assert [b.amount_cents for b in t.spent] == [1500]
    # Live spend comes from `messages` / `transactions` (05), not the rows: none seeded here.
    assert lv.spent == [] and lv.tips == [] and lv.bought is None


async def case_spend_any_lane():
    aid, fan = "fa_folds_spend", 702
    await seed_live(aid, {})
    await _msg(aid, fan, 7020, "out", "for u", NOW() - timedelta(hours=3), price_cents=1500, is_paid=True,
               purchased_at=NOW() - timedelta(hours=2), automation_kind="reply_mass_funnel")
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fan, kind="tip", amount_cents=500, status="cleared",
                          occurred_at=NOW() - timedelta(hours=1)))
    lv = await _load(aid, fan, 7021)
    assert [(b.kind, b.amount_cents) for b in lv.spent] == [("ppv_message", 1500)], lv.spent
    assert lv.tips == [500] and lv.bought.kind == "tip", (lv.tips, lv.bought)
    assert "minutes" in lv.state["last_purchase"] or "hour" in lv.state["last_purchase"], lv.state
    line = spend_line(lv.spent, lv.tips)
    assert line and "unlocked 1 PPV ($15 total" in line and "tipped $5" in line, line
    # On the real path the Writer's request carries it.
    _res, _f, _j, _i, fw = await dm_turn(aid, fan, 7022, "hey again")
    w = json.dumps([x["body"]["messages"] for x in fw.requests if x["host"] == NANO])
    assert "unlocked 1 PPV" in w and "tipped $5" in w, w


TEASE = {"ago": 10, "his": "u got pics?", "route": "tease", "route_row": "tease", "parts": ["maybe", "if ur good"],
         "offer": _offer(None, [711], [701], kind="tease", list_cents=1500), "part_ids": [8101, 8102]}


async def _tease_case(aid: str, fan: int, spec: dict, *, other_out: bool = False, outcome_row: bool = False):
    await seed_live(aid, {})
    await _rows_in(aid, fan, "live", [spec])
    at = NOW() - timedelta(minutes=spec["ago"])
    await _msg(aid, fan, 8101, "out", "maybe", at, automation_kind="full_ai_chat")
    await _msg(aid, fan, 8102, "out", "if ur good", at, automation_kind="full_ai_chat")
    if other_out:
        await _msg(aid, fan, 8103, "out", "hey hun", at + timedelta(minutes=2), automation_kind="reply_mass_funnel")
    if outcome_row:
        await _rows_in(aid, fan, "live", [{"ago": 30, "status": "no_send", "key": 8199,
                                           "offer": _offer(900, [799]), "outcome": "bought", "outcome_ago": 2,
                                           "omid": 89}])
    return await _load(aid, fan, 8110)


async def case_pending_tease():
    lv = await _tease_case("fa_folds_tease", 703, TEASE)
    assert lv.tease is not None and lv.tease.locked == (711,), lv.tease
    assert lv.state["pending_offer"] == "maybe if ur good", lv.state["pending_offer"]
    lv = await _tease_case("fa_folds_tease16", 704, {**TEASE, "ago": 16})
    assert lv.tease is None and lv.state["pending_offer"] == "none", lv.state
    lv = await _tease_case("fa_folds_tease_lane", 705, TEASE, other_out=True)
    assert lv.tease is None and lv.state["pending_offer"] == "none", lv.state
    lv = await _tease_case("fa_folds_tease_out", 706, TEASE, outcome_row=True)
    assert lv.tease is None, lv.tease
    # Test sessions unchanged: a test tease row still reads (test_full_ai_tease_folds.py unedited).
    assert full_ai_test.pending_tease_of([], NOW()) is None


async def case_open_offer():
    aid, fan = "fa_folds_offer", 707
    await seed_live(aid, {})
    await _rows_in(aid, fan, "live", [{"ago": 20, "route": "sell_now", "route_row": "sell",
                                       "parts": ["here u go"], "offer": _offer(1800, [711], list_cents=2400),
                                       "omid": 91}])
    lv = await _load(aid, fan, 7071)
    assert lv.offer_piece is not None and lv.offer_piece.list_cents == 2400, lv.offer_piece
    assert lv.state["pending_offer"] == "locked $18 message: here u go", lv.state["pending_offer"]
    assert lv.offer is not None and lv.offer.price_cents == 1800
    for n, spec in enumerate(({"ago": 20}, {"ago": 24 * 60 + 1, "omid": 92}), start=1):
        a = f"fa_folds_offer_none{n}"
        await seed_live(a, {})
        await _rows_in(a, fan, "live", [{"route": "sell_now", "route_row": "sell",
                                         "offer": _offer(1800, [711]), **spec}])
        lv = await _load(a, fan, 7072)
        assert lv.offer_piece is None and lv.offer is None and lv.state["pending_offer"] == "none", (n, lv.state)
    a = "fa_folds_offer_bought"
    await seed_live(a, {})
    await _rows_in(a, fan, "live", [{"ago": 20, "route": "sell_now", "route_row": "sell",
                                     "offer": _offer(1800, [711, 712]), "omid": 93, "outcome": "bought"}])
    lv = await _load(a, fan, 7073)
    assert lv.offer_piece is None and {711, 712} <= lv.owned, (lv.offer_piece, lv.owned)


async def case_spacing_one_line_per_turn():
    aid, fan = "fa_folds_spacing", 708
    await seed_live(aid, {"sell_spacing": True})
    await _rows_in(aid, fan, "live", [
        {"ago": 30, "route": "sell_now", "route_row": "sell", "offer": _offer(1500, [711]), "omid": 94},
        {"ago": 20, "his": "nice"}, {"ago": 10, "his": "u there?"}])
    lv = await _load(aid, fan, 7081)
    assert lv.state["his_lines_since_last_piece"] == 3, lv.state
    assert lv.state["pieces_this_sitting"] == 1, lv.state


async def case_scene():
    aid, fan = "fa_folds_scene", 709
    await seed_live(aid, {"sext_scene": True})
    sc = {"n": 2, "stage": "building", "heat": 3}
    await _rows_in(aid, fan, "live", [{"ago": 20, "scene": {"n": 1, "stage": "opening", "heat": 2}},
                                      {"ago": 10, "scene": sc, "status": "unconfirmed"}])
    lv = await _load(aid, fan, 7091)
    assert lv.scene == sc and lv.state["scene"] == "sexting for 2 of her messages so far, stage: building", lv.state
    a = "fa_folds_scene_old"
    await seed_live(a, {"sext_scene": True})
    await _rows_in(a, fan, "live", [{"ago": 121, "scene": sc}])
    lv = await _load(a, fan, 7092)
    assert lv.scene is None and lv.state["scene"] == "none", lv.state


async def case_no_live_rows():
    aid, fan = "fa_folds_empty", 710
    await seed_live(aid, FOLDS)
    lv = await _load(aid, fan, 7100)
    assert (lv.owned, lv.sent, lv.spent, lv.tips, lv.tease, lv.offer_piece, lv.scene, lv.purchases, lv.bought) == (
        set(), set(), [], [], None, None, None, [], None), lv
    assert lv.state["pending_offer"] == "none" and lv.state["his_lines_since_last_piece"] == "no piece yet"
    res, fake, *_ = await dm_turn(aid, fan, 7101, "hey there")
    assert res["row_status"] == "sent" and fake.sent, res


async def case_null_json_rows():
    aid, fan = "fa_folds_null", 711
    await seed_live(aid, FOLDS)
    ids = await _rows_in(aid, fan, "live", SPECS)
    from sqlalchemy import update
    async with get_session() as s:
        await s.execute(update(AiDecision).where(AiDecision.id.in_(ids)).values(reply_json=None, jev_json=None))
    lv = await _load(aid, fan, 7111)
    assert lv is not None and lv.scene is None and lv.asked == {}, lv
    assert lv.owned == {711, 712, 713}, lv.owned        # Offer columns survive retention


_harness.run()
