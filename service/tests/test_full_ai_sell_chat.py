#!/usr/bin/env python3
"""test_full_ai_sell_chat — the first sale in the Test chat, through the Relay API (phase 03b, ticket 42).

`POST /admin/full-ai/test/turn` over `_harness.make_client()` with real owner session cookies (the
two-Agency fixture), a seeded vault, and the fakes of test_full_ai_test_chat.py at the two network
edges only (Jev at `_router_jev._client`, the Writers at `llm_client.httpx.AsyncClient`). Every
Turn runs inside `_guarded`: full-row snapshots of messages, transactions, vault_sends,
content_offers, fan_lease and fans equal before and after, no `automation_runs` row, every send
path plus `ownership.stamp_media_owned` patched to raise and never hit.

  case_sell_turn_via_api            sell on (draft), "send me pics": row `sell`, the Offer columns
                                    (price = list, message id / outcome / join NULL), the PPV on the
                                    last part only, response `offer` = the row's, the sell prompt
  case_left_sell_off_right_ppv      same line: checkpoint sell-off line, draft a PPV
  case_one_pick_per_turn            every Route reachable (chat, sext, ai_dare, make_right, no_send,
                                    sell_now, R10 rows): `full_ai_sell.pick` called ≤ 1 per Turn,
                                    only on sell_now and tease (ticket 46; make_right here has no
                                    Buy); ≤ 1 PPV part, none on a tease
  case_refusals                     empty vault no_match, all unpriced no_priced_items (both the
                                    "filming more soon" need-line), rows read raising
                                    inventory_unknown, the pool raising the same (plain chat): no PPV,
                                    `offer` null
  case_leak_drops_the_ppv           a phone number: the deflection, no PPV, no Offer, offer_dropped leak
  case_shape_drop_drops_the_ppv     a chain drop: failed, no PPV, no Offer, offer_dropped shape; every
                                    Writer failing: failed, no offer_dropped
  case_offer_marker                 `>>OFFER <ref>` stripped from the parts; `>>OFFER 999` is
                                    floor:offer_ref and the next Writer answers
  case_shadow_row_has_no_offer      a Shadow Turn's row: every Offer column NULL, no Pick

Run: ./venv/bin/python service/tests/test_full_ai_sell_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    NANO, OPENROUTER, PRICED, _body, _db, _hot, _no_offer, _picks, _post, _ppvs,
    _reply, _rows, _sell_draft, _system, _vault,
)
import json  # noqa: E402

import _full_ai_fixtures as ffx  # noqa: E402
from _full_ai_fixtures import QUIET  # noqa: E402
import vault_scripts  # noqa: E402
from automations import full_ai_sell, full_ai_test, full_ai_writers  # noqa: E402


# ── The sale ──────────────────────────────────────────────────────────

def case_sell_turn_via_api():
    pair = "p-sell"
    with _sell_draft(), _vault(PRICED):
        r, fw, picks = _post(_body(pair), "ok:mm ok i have something for u. its a cute one")
    got = r.json()
    assert (got["status"], got["route"], got["route_row"]) == ("sent", "sell_now", "sell"), got
    (pick,) = picks
    assert isinstance(pick, full_ai_sell.Pick) and pick.ref in PRICED, pick
    # The PPV on the last part only.
    assert len(got["parts"]) >= 1 and _ppvs(got["parts"]) == [len(got["parts"]) - 1], got["parts"]
    ppv = got["parts"][-1]["ppv"]
    assert ppv == {"ref": pick.ref, "price_cents": pick.price_cents, "media": list(pick.media),
                   "previews": list(pick.previews)}, ppv
    (row,) = _rows(pair)
    assert (row.route, row.route_row, row.status) == ("sell_now", "sell", "sent"), row.route
    want_list = {101: 1000, 202: 5000}[pick.ref]
    assert (row.offer_price_cents, row.offer_list_cents) == (want_list, want_list), (
        row.offer_price_cents, row.offer_list_cents)
    assert (row.offer_message_id, row.outcome, row.outcome_at, row.join_src) == (None, None, None, None)
    assert json.loads(row.offer_media_json) == {"locked": list(pick.media), "previews": list(pick.previews)}
    assert json.loads(row.offer_item_ref) == {"ref": pick.ref, "subject": pick.subject, "format": pick.format,
                                              "lane": pick.lane, "kind": "offer"}, row.offer_item_ref
    # The response's `offer` is the row's; the session read carries the same.
    assert got["offer"] == full_ai_test.offer_of(row) and got["offer"]["price_cents"] == want_list, got["offer"]
    assert got["offer"]["refusal"] is None and got["offer"]["kind"] == "offer", got["offer"]
    assert _reply(row)["parts"] == got["parts"] and "refusal" not in _reply(row), _reply(row)
    # The Writer got the content-ask sell prompt: the beat, the item line and price block, the
    # contract with the >>OFFER exception.
    system = _system(fw)
    w = full_ai_writers
    assert w.CONTENT_ASK.format(close=w.CLOSE_BY_ID) in system and w.INTRO_BY_ID in system, system
    assert f"[id {pick.ref}]" in system and f"${want_list // 100} to unlock" in system, system
    assert "a mirror selfie in jeans" in system and w.CONTRACT_OFFER in system, system
    assert w.NO_SELL_OFFERS not in system and w.SELL_OFF_LINE not in system, system


def case_left_sell_off_right_ppv():
    pair = "p-lr"
    with _sell_draft(), _vault(PRICED):
        left, lw, lp = _post(_body(pair, side="checkpoint"), "ok:its all on my page babe")
        right, rw, rp = _post(_body(pair, side="draft"), "ok:mm ok i have something for u")
    lg, rg = left.json(), right.json()
    # Left: 03a's R10 unchanged — chat, sell_off, the sell-off line, no Pick, no PPV.
    assert (lg["route"], lg["route_row"], lg["dropped"]) == ("chat", "sell_off", ["sell"]), lg
    assert full_ai_writers.SELL_OFF_LINE in _system(lw) and lp == [], lp
    assert _ppvs(lg["parts"]) == [] and lg["offer"] is None, lg
    # Right: the PPV.
    assert (rg["route"], rg["route_row"]) == ("sell_now", "sell"), rg
    assert len(rp) == 1 and _ppvs(rg["parts"]) == [len(rg["parts"]) - 1] and rg["offer"], rg
    left_row, right_row = _rows(pair)
    _no_offer(left_row)
    assert right_row.offer_price_cents == rg["offer"]["price_cents"], right_row.offer_price_cents


def case_one_pick_per_turn():
    """Every Route reachable through the Test chat: a Pick only on sell_now and tease (make_right
    here has no Buy, so no Free item), never more than one per Turn, never more than one PPV part,
    none on a tease (its Pick on the row, priceless)."""
    cases = [
        ("chat", QUIET, "draft"),
        ("sext", _hot(sexual_now=0.9), "draft"),
        ("dare", _hot(asks_if_ai=0.9), "draft"),
        ("right", _hot(complains_now=0.9), "draft"),
        ("promo", _hot(promo=0.9), "draft"),
        ("u18", _hot(says_under_18=0.9), "draft"),
        ("sell", _hot(wants_content=0.9), "draft"),
        ("both", _hot(wants_content=0.9, sexual_now=0.9), "draft"),
        ("price", _hot(price=0.9), "draft"),
        ("ck-sell", _hot(wants_content=0.9), "checkpoint"),
        ("ck-price", _hot(price=0.9), "checkpoint"),
    ]
    seen = set()
    with _sell_draft(), _vault(PRICED):
        for tag, answers, side in cases:
            pair = f"p-one-{tag}"
            r, _, picks = _post(_body(pair, side=side), "ok:mm ok babe", jev=(answers, 1.0))
            got = r.json()
            seen.add(got["route"])
            assert len(picks) <= 1, (tag, picks)
            assert (len(picks) == 1) is (got["route"] in ("sell_now", "tease")), (tag, got["route"], picks)
            assert len(_ppvs(got["parts"])) <= (got["route"] == "sell_now"), (tag, got["parts"])
            (row,) = _rows(pair)
            if got["route"] == "tease":
                assert (got["offer"]["kind"], got["offer"]["price_cents"]) == ("tease", None), (tag, got)
            elif got["route"] != "sell_now":
                _no_offer(row)
                assert got["offer"] is None, (tag, got)    # null off sell_now / tease
    assert {"chat", "sext", "ai_dare", "make_right", "no_send", "sell_now", "tease"} <= seen, seen


def case_refusals():
    w = full_ai_writers
    filming = w.FILMING_MORE

    def boom(*_a, **_k):
        raise RuntimeError("vault read down")

    real_load, real_pool = vault_scripts._load_rows, full_ai_sell.pool
    # (tag, vault, what raises: None | "rows" | "pool", reason, need-line or None)
    # ASSUMPTION: an empty vault is no_match (ticket 41's pool contract: nothing chosen -> no_match),
    # not the ticket's no_priced_items; both carry the same need-line.
    table = [
        ("empty", {}, None, "no_match", filming),
        ("unpriced", {301: "review", 302: "review"}, None, "no_priced_items", filming),
        ("raise", PRICED, "rows", "inventory_unknown", None),
        ("pool-raise", PRICED, "pool", "inventory_unknown", None),   # past load_rows: fails closed too
    ]
    with _sell_draft():
        for tag, items, raising, reason, need in table:
            pair = f"p-ref-{tag}"
            with _vault(items):
                if raising == "rows":
                    vault_scripts._load_rows = boom
                elif raising == "pool":
                    full_ai_sell.pool = boom
                try:
                    r, fw, picks = _post(_body(pair), "ok:not right now babe, wbu")
                finally:
                    vault_scripts._load_rows, full_ai_sell.pool = real_load, real_pool
            got = r.json()
            assert (got["status"], got["route"], got["route_row"]) == ("sent", "sell_now", "sell"), (tag, got)
            assert picks == [], (tag, picks)
            assert _ppvs(got["parts"]) == [] and got["offer"] is None, (tag, got)
            system = _system(fw)
            assert (filming in system) is (need is not None), (tag, system)
            assert w.CONTENT_ASK.format(close=w.CLOSE_BY_ID) not in system, tag
            assert w.CONTRACT_OFFER not in system and w.CONTRACT in system, tag
            (row,) = _rows(pair)
            _no_offer(row)
            assert _reply(row)["refusal"] == reason, (tag, _reply(row))


def case_leak_drops_the_ppv():
    pair = "p-leak"
    with _sell_draft(), _vault(PRICED):
        r, _, picks = _post(_body(pair), "ok:text me on 555-123-4567 and ill send u more")
    got = r.json()
    assert len(picks) == 1 and isinstance(picks[0], full_ai_sell.Pick), picks
    assert got["status"] == "sent" and got["parts"], got
    assert "555" not in json.dumps(got["parts"]), got["parts"]
    assert _ppvs(got["parts"]) == [] and got["offer"] is None, got
    (row,) = _rows(pair)
    _no_offer(row)
    reply = _reply(row)
    assert reply["leak"] and reply["offer_dropped"] == "leak", reply


def case_shape_drop_drops_the_ppv():
    pair, his = "p-shape", "send me some pics of you right now babe"
    with _sell_draft(), _vault(PRICED), ffx._shape_drop("banned"):
        r, _, picks = _post(_body(pair, his), "ok:hii")
    got = r.json()
    assert len(picks) == 1, picks
    assert (got["status"], got["parts"], got["offer"]) == ("failed", [], None), got
    (row,) = _rows(pair)
    _no_offer(row)
    reply = _reply(row)
    assert (reply["dropped_reason"], reply["offer_dropped"]) == ("banned", "shape"), reply
    # Every Writer failing is not a shape drop: failed, no PPV, no offer_dropped.
    with _sell_draft(), _vault(PRICED):
        r, _, picks = _post(_body("p-allfail"), {NANO: "503", OPENROUTER: "503"})
    got = r.json()
    assert len(picks) == 1 and (got["status"], got["parts"], got["offer"]) == ("failed", [], None), got
    (row,) = _rows("p-allfail")
    _no_offer(row)
    assert "offer_dropped" not in _reply(row), _reply(row)


def case_offer_marker():
    pair = "p-marker"
    with _sell_draft(), _vault(PRICED):
        r, fw, picks = _post(_body(pair), {NANO: "ok:mm ok i have something for u\n>>OFFER 999"})
        (pick,) = picks
        good = f"ok:mm ok here u go babe\n>>OFFER {pick.ref}"
        # A fresh pair (its own seed): the right ref is stripped; asserted to be the same Pick.
        pair2 = "p-marker-2"
        r2, fw2, picks2 = _post(_body(pair2), {NANO: good})
    assert [p.ref for p in picks2] == [pick.ref], (picks2, pick)
    got = r.json()
    # >>OFFER 999 is not the Pick: floor:offer_ref, the next Writer answers (no marker: still a PPV).
    assert [a["outcome"] for a in got["attempts"]][0] == "floor:offer_ref", got["attempts"]
    assert got["status"] == "sent" and len(fw.requests) == 2, got
    assert _reply(_rows(pair)[0])["floor_reason"] == "offer_ref"
    assert _ppvs(got["parts"]) == [len(got["parts"]) - 1], got["parts"]
    g2 = r2.json()
    assert g2["status"] == "sent" and [a["outcome"] for a in g2["attempts"]] == ["ok"], g2
    assert ">>" not in json.dumps(g2["parts"]) and "OFFER" not in json.dumps(g2["parts"]), g2["parts"]
    assert _ppvs(g2["parts"]) == [len(g2["parts"]) - 1] and len(picks2) == 1, g2["parts"]


def case_shadow_row_has_no_offer():
    """A Shadow Turn (the executor run, not the Test chat) on a wants-content line: its row carries
    no Offer column and no Pick is made."""
    aid = "creator-shadow-42"
    with _picks() as picks:
        _res, row = _db(lambda: ffx._one_turn(aid, 9100, (_hot(wants_content=0.9), 1.0)))
    assert picks == [], picks
    _no_offer(row)


_harness.run()
