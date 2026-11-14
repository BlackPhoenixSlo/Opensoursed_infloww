#!/usr/bin/env python3
"""test_full_ai_settle_chat — fake Buy / Decline in the Test chat (phase 03b, ticket 44).

`POST /admin/full-ai/test/settle` and `POST /admin/full-ai/test/turn` over `_harness.make_client()`
with real owner session cookies (the two-Agency fixture), a seeded vault, and the fakes at the
network edges only (Jev at `_router_jev._client`, the Writers at `llm_client.httpx.AsyncClient`).
Every request runs inside `_full_ai_sell_helpers._guarded` (03a's invariant list + content_offers;
`ownership.stamp_media_owned` patched to raise, never hit).

Pure (the session folds and the PPV thread mapping):
  case_folds_table                     owned_of / sent_media_of / bought_of / open_offer_of /
                                       pending_offer_text over hand-built test rows
  case_test_thread_ppv_equals_the_db   test_thread + the folds through build_state = the DB read
                                       (`full_ai_chat._read`) for the same exchange; the real Router
                                       `_ppv` note: "he bought it" / "he has not bought it"
Via the API:
  case_buy_then_same_ask               Buy → same ask → another Pick (Jev thread shows the unlock,
                                       `last_purchase` set, the Writer's spend line); Buy that one
                                       too → `all_owned` with the "filming more soon" line
  case_decline_reoffers                Decline → `pending_offer` "none", the same item picked again
  case_settle_refusals                 second settle 409; chat row 422; Free item row 422; another
                                       session's row 404; another owner's account 403; an older
                                       unsettled Offer can be settled
  case_each_window_owns_its_own        a checkpoint-side Buy leaves the draft side's owned set empty
  case_dupes_unreadable_after_buy      dupe groups raising after a Buy → inventory_unknown, no PPV

Run: ./venv/bin/python service/tests/test_full_ai_settle_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    A, IDS, OWNER_A, PICS, _body, _db, _guarded, _no_offer, _post, _ppvs, _put_draft, _reply, _rows,
    _sell_draft, _system, _vault,
)
import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from _full_ai_fixtures import QUIET  # noqa: E402
import vault_dupes  # noqa: E402
from automations import _router_jev as router  # noqa: E402
from automations import full_ai_chat, full_ai_sell, full_ai_test, full_ai_writers  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Message, Transaction  # noqa: E402

SETTLE, SAVE = "/admin/full-ai/test/settle", "/admin/full-ai/config/save"
T0 = datetime(2026, 11, 10, 18, 0)


def _settle(pair: str, row_id: int, outcome: str, *, side: str = "draft", account: str = A):
    with _guarded():
        return OWNER_A.post(SETTLE, json={"account_id": account, "pair": pair, "side": side,
                                          "row_id": row_id, "outcome": outcome})


def _state(row: AiDecision) -> dict:
    return json.loads(row.jev_json)["state"]


def _user(fw, i: int = 0) -> str:
    return fw.requests[i]["body"]["messages"][1]["content"]


# ── Pure: folds + the PPV thread mapping ─────────────────────────────

def _row(rid: int, n: int, at: datetime, his: str, parts: list[dict], *, price=None, media=(), previews=(),
         ref=None, outcome=None, outcome_at=None) -> AiDecision:
    """A test row as `send` + `settle` leave it (never added to a session)."""
    offer = {}
    if price is not None:
        offer = dict(offer_price_cents=price, offer_list_cents=price,
                     offer_media_json=json.dumps({"locked": list(media), "previews": list(previews)}),
                     offer_item_ref=json.dumps({"ref": ref, "subject": "anything", "format": "photo",
                                                "lane": "L1", "kind": "offer"}))
    return AiDecision(id=rid, account_id=A, fan_id=-1, mode="test", trigger_kind="test",
                      trigger_key=f"test:p-L:{n}", created_at=at, route="sell_now", heat=2,
                      route_row="sell", question_version="v", status="sent",
                      jev_json=json.dumps({"state": {"fan_new_messages": [his]}}),
                      reply_json=json.dumps({"parts": parts}), outcome=outcome, outcome_at=outcome_at,
                      join_src="test" if outcome else None, **offer)


def _ppv_part(text: str, ref: int, price: int, media: list[int], previews: list[int]) -> dict:
    return {"text": text, "ppv": {"ref": ref, "price_cents": price, "media": media, "previews": previews}}


def _exchange() -> list[AiDecision]:
    """Chat, a bought $10 Offer, a declined $20 one, a Free item, an unsettled $50 one."""
    bought_at = T0 - timedelta(hours=3, minutes=30)
    return [
        _row(1, 1, T0 - timedelta(hours=5), "hey you", [{"text": "heyy"}]),
        _row(2, 2, T0 - timedelta(hours=4), "send me pics",
             [{"text": "mm ok"}, _ppv_part("just for u", 101, 1000, [11, 12], [13])],
             price=1000, media=[11, 12], previews=[13], ref=101, outcome="bought", outcome_at=bought_at),
        _row(3, 3, T0 - timedelta(hours=3), "more", [_ppv_part("this one", 202, 2000, [21], [])],
             price=2000, media=[21], ref=202, outcome="declined", outcome_at=T0 - timedelta(hours=2, minutes=50)),
        _row(4, 4, T0 - timedelta(hours=2), "that was bad", [_ppv_part("sorry babe", 303, 0, [31], [])],
             price=0, media=[31], ref=303),
        _row(5, 5, T0 - timedelta(hours=1), "anything else", [_ppv_part("u will love it", 404, 5000, [41], [42])],
             price=5000, media=[41], previews=[42], ref=404),
    ]


def case_folds_table():
    rows = _exchange()
    t = full_ai_test
    assert t.owned_of(rows) == {11, 12, 31}, t.owned_of(rows)                 # bought ∪ Free item
    assert t.sent_media_of(rows) == {11, 12, 13, 21, 31, 41, 42}, t.sent_media_of(rows)
    assert [(b.kind, b.amount_cents, b.occurred_at) for b in t.bought_of(rows)] == [
        ("ppv_message", 1000, rows[1].outcome_at)], t.bought_of(rows)
    assert t.open_offer_of(rows) is rows[4], t.open_offer_of(rows)
    assert t.pending_offer_text(rows) == "locked $50 message: u will love it", t.pending_offer_text(rows)
    # Bought or declined only (the open one settled, the Free item unpriced): "none".
    settled = rows[:4] + [_row(5, 5, rows[4].created_at, "x", json.loads(rows[4].reply_json)["parts"],
                               price=5000, media=[41], ref=404, outcome="declined", outcome_at=T0)]
    assert t.open_offer_of(settled) is None and t.pending_offer_text(settled) == "none"
    assert t.owned_of(settled) == {11, 12, 31}, t.owned_of(settled)           # a decline owns nothing
    # An older unsettled Offer under a newer settled one is still the open Offer.
    older = rows[:3] + [_row(3, 3, rows[2].created_at, "more", json.loads(rows[2].reply_json)["parts"],
                             price=2000, media=[21], ref=202)] + settled[4:]
    assert t.open_offer_of(older).id == 3 and t.pending_offer_text(older) == "locked $20 message: this one"
    # No rows, chat only: nothing.
    for rs in ([], rows[:1]):
        assert (t.owned_of(rs), t.sent_media_of(rs), t.bought_of(rs), t.open_offer_of(rs),
                t.pending_offer_text(rs)) == (set(), set(), [], None, "none"), rs


def case_test_thread_ppv_equals_the_db():
    """The exchange's PPV bubbles map to priced outbound rows: the Turn after them reads the same
    Jev state as the DB path for the same messages + purchase, through the real Router."""
    rows = _exchange()
    lines = full_ai_test.test_thread(rows)
    priced = [(m.body, m.price_cents, m.media_count, m.is_paid, m.purchased_at) for m in lines if m.price_cents]
    assert priced == [("just for u", 1000, 2, True, rows[1].outcome_at), ("this one", 2000, 1, False, None),
                      ("u will love it", 5000, 1, False, None)], priced
    # The real Router PPV note on the mapped rows (no attribute error).
    notes = [router._ppv(m) for m in lines if m.price_cents]
    assert notes == ["locked $10 message, he bought it", "locked $20 message, he has not bought it",
                     "locked $50 message, he has not bought it"], notes
    fan = 7_440
    anchor_id = len(lines) + 1
    (bought,) = full_ai_test.bought_of(rows)

    async def db_state():
        async with get_session() as s:
            for m in lines:
                s.add(Message(account_id=A, fan_id=fan, message_id=m.message_id, direction=m.direction,
                              body=m.body, created_at=m.created_at, price_cents=m.price_cents,
                              media_count=m.media_count, is_paid=m.is_paid, purchased_at=m.purchased_at))
            s.add(Message(account_id=A, fan_id=fan, message_id=anchor_id, direction="in",
                          body="what are you up to", created_at=T0))
            s.add(Transaction(account_id=A, fan_id=fan, kind=bought.kind, amount_cents=bought.amount_cents,
                              occurred_at=bought.occurred_at))
        try:
            return await full_ai_chat._read(A, fan, anchor_id)
        finally:
            async with get_session() as s:
                await s.execute(Message.__table__.delete().where(Message.fan_id == fan))
                await s.execute(Transaction.__table__.delete().where(Transaction.fan_id == fan))
    ((_anchor, db_st, db_offer),) = _db(db_state)
    turn = [full_ai_test._line("in", "what are you up to", T0, anchor_id)]
    st, has_offer = full_ai_chat.build_state(turn, lines[-router.THREAD_LINES:], bought,
                                             full_ai_test.offer_line(full_ai_test.open_offer_of(rows)))
    assert (st, has_offer) == (db_st, db_offer), (st, db_st)
    assert st["pending_offer"] == full_ai_test.pending_offer_text(rows), st
    assert st["last_purchase"] != "none in the last 7 days", st
    assert [e.get("ppv") for e in st["thread"] if e.get("ppv")] == notes, st["thread"]


# ── Via the API ───────────────────────────────────────────────────────

def case_buy_then_same_ask():
    pair, vault = "s-buy", {101: "$10", 202: "$50"}
    w = full_ai_writers
    with _sell_draft(), _vault(vault):
        r1, fw1, (p1,) = _post(_body(pair), "ok:mm ok i have something for u")
        g1 = r1.json()
        assert "he's spent" not in _user(fw1), _user(fw1)
        s = _settle(pair, g1["row_id"], "bought")
        assert s.status_code == 200 and s.json() == {"row_id": g1["row_id"], "outcome": "bought"}, s.text
        (row1,) = _rows(pair)
        assert (row1.outcome, row1.join_src) == ("bought", "test") and row1.outcome_at is not None, row1.outcome
        assert row1.offer_price_cents == g1["offer"]["price_cents"], row1.offer_price_cents
        r2, fw2, (p2,) = _post(_body(pair, n=2), "ok:mm ok here is another one")
    assert isinstance(p1, full_ai_sell.Pick) and isinstance(p2, full_ai_sell.Pick), (p1, p2)
    assert p2.ref != p1.ref and not set(p2.media) & set(p1.media), (p1, p2)
    assert _ppvs(r2.json()["parts"]) == [len(r2.json()["parts"]) - 1], r2.json()
    # The next Turn's Jev state: the unlock on her PPV line, his purchase, no Pending offer.
    st = _state(_rows(pair)[1])
    price = p1.price_cents // 100
    assert any(e.get("ppv") == f"locked ${price} message, he bought it" for e in st["thread"]), st["thread"]
    assert st["last_purchase"].startswith(f"he bought a locked message for ${price}, "), st
    assert st["pending_offer"] == "none", st
    # The Writer saw OLD-AIC-22's spend line in the facts block.
    spend = (f"- he's spent: unlocked 1 PPV (${price} total, biggest ${price}) — talk like you remember it, "
             "never like he's never paid.")
    assert spend in _user(fw2), _user(fw2)
    # Buy the second one too: nothing left → all_owned, the "filming more soon" line, no PPV.
    with _sell_draft(), _vault(vault):
        assert _settle(pair, r2.json()["row_id"], "bought").status_code == 200
        r3, fw3, picks3 = _post(_body(pair, n=3), "ok:not right now babe, wbu")
    g3 = r3.json()
    assert picks3 == [] and _ppvs(g3["parts"]) == [] and g3["offer"] is None, g3
    assert w.FILMING_MORE in _system(fw3) and w.CONTRACT_OFFER not in _system(fw3), _system(fw3)
    row3 = _rows(pair)[2]
    assert _reply(row3)["refusal"] == "all_owned", _reply(row3)
    _no_offer(row3)
    total, big = (p1.price_cents + p2.price_cents) // 100, max(p1.price_cents, p2.price_cents) // 100
    assert f"- he's spent: unlocked 2 PPVs (${total} total, biggest ${big})" in _user(fw3), _user(fw3)


def case_decline_reoffers():
    pair = "s-decline"
    with _sell_draft(), _vault({101: "$10"}):
        r1, _, (p1,) = _post(_body(pair), "ok:mm ok i have something for u")
        assert p1.ref == 101, p1
        s = _settle(pair, r1.json()["row_id"], "declined")
        assert s.status_code == 200 and s.json() == {"row_id": r1.json()["row_id"], "outcome": "declined"}, s.text
        r2, fw2, (p2,) = _post(_body(pair, n=2), "ok:mm ok try this one")
    row1, row2 = _rows(pair)
    assert (row1.outcome, row1.join_src) == ("declined", "test"), row1.outcome
    st = _state(row2)
    assert st["pending_offer"] == "none" and st["last_purchase"] == "none in the last 7 days", st
    assert any(e.get("ppv") == "locked $10 message, he has not bought it" for e in st["thread"]), st["thread"]
    assert p2.ref == 101 and r2.json()["offer"]["ref"] == 101, (p2, r2.json())      # re-offerable
    assert "he's spent" not in _user(fw2), _user(fw2)


def case_settle_refusals():
    pair = "s-ref"
    with _sell_draft(), _vault({101: "$10", 202: "$50"}):
        chat, _, _ = _post(_body(pair, "hey whats up"), "ok:heyy not much u", jev=(QUIET, 1.0))
        o1, _, _ = _post(_body(pair, n=2), "ok:mm ok i have something for u")
        o2, _, _ = _post(_body(pair, n=3), "ok:mm ok here is another")
    chat_id, o1_id, o2_id = chat.json()["row_id"], o1.json()["row_id"], o2.json()["row_id"]
    assert o1.json()["offer"] and o2.json()["offer"], (o1.json(), o2.json())
    # An older unsettled Offer can be settled, not only the newest; then the newest.
    assert _settle(pair, o1_id, "bought").status_code == 200
    assert _settle(pair, o2_id, "declined").status_code == 200
    # Second settle: 409 with the stored outcome; never flipped.
    r = _settle(pair, o1_id, "declined")
    assert r.status_code == 409 and r.json() == {"detail": "already_settled", "outcome": "bought"}, r.text
    # A chat row: 422.
    r = _settle(pair, chat_id, "bought")
    assert r.status_code == 422 and r.json() == {"detail": "not_a_priced_offer"}, r.text
    # A Free item row (price 0): 422.
    free_id = _db(lambda: _free_item_row(pair))
    r = _settle(pair, free_id, "bought")
    assert r.status_code == 422 and r.json() == {"detail": "not_a_priced_offer"}, r.text
    # Another session's row: the other side, another pair, an unknown id: 404.
    for p, side, rid in ((pair, "checkpoint", o2_id), ("s-other", "draft", o2_id), (pair, "draft", 999_999)):
        r = _settle(p, rid, "bought", side=side)
        assert r.status_code == 404 and r.json() == {"detail": "not_this_session"}, (p, side, r.text)
    # Another owner's account: 403 before any read.
    r = _settle(pair, o2_id, "bought", account=IDS["creator_b"])
    assert r.status_code == 403, r.text
    # A bad outcome is refused by the body model.
    with _guarded():
        r = OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "draft", "row_id": o2_id,
                                       "outcome": "refunded"})
    assert r.status_code == 422, r.text
    rows = {x.id: x for x in _rows(pair)}
    assert (rows[o1_id].outcome, rows[o2_id].outcome, rows[chat_id].outcome, rows[free_id].outcome) == (
        "bought", "declined", None, None), rows
    assert rows[chat_id].join_src is None and rows[free_id].join_src is None


async def _free_item_row(pair: str) -> int:
    """A Free item (make_right, price 0) as the draft session's next row."""
    n = len(await full_ai_test.session_rows(A, pair, "draft")) + 1
    async with get_session() as s:
        row = AiDecision(account_id=A, fan_id=full_ai_test.test_fan_id(pair), mode="test", trigger_kind="test",
                         trigger_key=full_ai_test.trigger_key(full_ai_test.session_key(pair, "draft"), n),
                         route="make_right", heat=1, route_row="make_right", question_version="v",
                         status="sent", jev_json=json.dumps({"state": {"fan_new_messages": ["that sucked"]}}),
                         reply_json=json.dumps({"side": "draft", "parts": [{"text": "sorry babe, here"}]}),
                         offer_price_cents=0, offer_list_cents=1000,
                         offer_media_json=json.dumps({"locked": [303], "previews": []}),
                         offer_item_ref=json.dumps({"ref": 303, "subject": "anything", "format": "photo",
                                                    "lane": "L1", "kind": "offer"}))
        s.add(row)
        await s.flush()
        return row.id


@contextlib.contextmanager
def _sell_both():
    """Both windows sell: the draft with `sell_on`, saved as the checkpoint; then DEFAULTS saved back."""
    rev = _put_draft({**DEFAULTS, "sell_on": True})
    r = OWNER_A.post(SAVE, json={"account_id": A, "rev": rev})
    assert r.status_code == 200, r.text
    try:
        yield
    finally:
        rev = _put_draft(dict(DEFAULTS))
        r = OWNER_A.post(SAVE, json={"account_id": A, "rev": rev})
        assert r.status_code == 200, r.text


def case_each_window_owns_its_own():
    pair = "s-sides"
    with _sell_both(), _vault({101: "$10"}):
        left, _, (pl,) = _post(_body(pair, side="checkpoint"), "ok:mm ok i have something for u")
        assert pl.ref == 101, pl
        assert _settle(pair, left.json()["row_id"], "bought", side="checkpoint").status_code == 200
        right, _, (pr,) = _post(_body(pair, side="draft"), "ok:mm ok i have something for u")
        left2, _, picks2 = _post(_body(pair, side="checkpoint", n=2), "ok:not right now babe")
    # The draft session owns nothing: the same item is offered there; the checkpoint owns it.
    assert pr.ref == 101 and right.json()["offer"]["ref"] == 101, (pr, right.json())
    assert picks2 == [] and left2.json()["offer"] is None, left2.json()
    left_rows = [x for x in _rows(pair) if x.trigger_key.startswith("test:" + full_ai_test.session_key(pair, "checkpoint"))]
    assert _reply(left_rows[-1])["refusal"] == "all_owned", _reply(left_rows[-1])
    draft_rows = [x for x in _rows(pair) if x.trigger_key.startswith("test:" + full_ai_test.session_key(pair, "draft"))]
    assert full_ai_test.owned_of(draft_rows) == set(), draft_rows
    assert _state(draft_rows[0])["last_purchase"] == "none in the last 7 days"


def case_dupes_unreadable_after_buy():
    pair = "s-dupes"
    real = vault_dupes.find_duplicates

    async def boom(*_a, **_k):
        raise RuntimeError("dupe hashes unreadable")
    with _sell_draft(), _vault({101: "$10", 202: "$50"}):
        r1, _, (p1,) = _post(_body(pair), "ok:mm ok i have something for u")
        assert _settle(pair, r1.json()["row_id"], "bought").status_code == 200
        vault_dupes.find_duplicates = boom
        try:
            r2, fw2, picks2 = _post(_body(pair, PICS, n=2), "ok:not right now babe, wbu")
        finally:
            vault_dupes.find_duplicates = real
    g2 = r2.json()
    assert (g2["route"], g2["status"]) == ("sell_now", "sent"), g2
    assert picks2 == [] and _ppvs(g2["parts"]) == [] and g2["offer"] is None, g2
    row2 = _rows(pair)[1]
    assert _reply(row2)["refusal"] == "inventory_unknown", _reply(row2)
    _no_offer(row2)
    assert full_ai_writers.FILMING_MORE not in _system(fw2), _system(fw2)


_harness.run()
