#!/usr/bin/env python3
"""test_full_ai_tease_folds — the Pending tease fold and the tease-first Pending offer (phase 03b,
ticket 46 phase A). Pure: hand-built test rows, never added to a session.

  case_pending_tease_window            newest row a sent test tease: held at 899 s and 900 s, gone at
                                       901 s
  case_pending_tease_ends              an outcome since (bought or declined), another sent row since,
                                       a failed / non-test / Pick-less tease row: no Pending tease;
                                       an outcome before the tease or a newer failed / no_send row
                                       (nothing sent) keeps it
  case_pending_offer_text_tease_first  a Pending tease's text over an open priced Offer; expired →
                                       the Offer's "locked $N message: …"; nothing → "none"
  case_open_offer_superseded           ticket 47: a haggle row (same piece or a re-pick) supersedes
                                       the Offer its `over` names, settled or not; a plain sell does
                                       not; an owned piece's Offer is not open; settling a superseded
                                       Offer never hides an older one; `teased_of` carries the row's
                                       list price and id

Run: ./venv/bin/python service/tests/test_full_ai_tease_folds.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from automations import full_ai_test as t  # noqa: E402
from db.models import AiDecision  # noqa: E402

T0 = datetime(2026, 11, 14, 20, 0)          # his reply (the Turn's `now`)


def _row(rid: int, at: datetime, parts: list[str], *, route="chat", kind=None, price=None,
         status="sent", mode="test", outcome=None, outcome_at=None) -> AiDecision:
    """A session row as `send` (+ `settle`) leaves it. `kind` "tease" = a tease row: its Pick in
    the item ref, price NULL (ticket 07 r3 / spec 03b › Data); "offer" = a priced Offer."""
    offer = {}
    if kind:
        offer = dict(offer_price_cents=price, offer_list_cents=price if price is not None else 2500,
                     offer_media_json=json.dumps({"locked": [rid * 10], "previews": []}),
                     offer_item_ref=json.dumps({"ref": rid * 10, "subject": "feet", "format": "photo",
                                                "lane": "$25", "kind": kind}))
    return AiDecision(id=rid, account_id="a", fan_id=-1, mode=mode, trigger_kind="test",
                      trigger_key=f"test:p-R:{rid}", created_at=at, route=route, heat=2,
                      route_row="x", question_version="v", status=status,
                      jev_json=json.dumps({"state": {"fan_new_messages": ["hi"]}}),
                      reply_json=json.dumps({"parts": _parts(parts, rid, price)}),
                      outcome=outcome, outcome_at=outcome_at, join_src="test" if outcome else None,
                      **offer)


def _parts(texts: list[str], rid: int, price) -> list[dict]:
    """Her bubbles; a priced Offer's PPV rides the last one (`send`)."""
    out = [{"text": x} for x in texts]
    if price:
        out[-1]["ppv"] = {"ref": rid * 10, "price_cents": price, "media": [rid * 10], "previews": []}
    return out


def _tease(rid: int, age_s: float, **kw) -> AiDecision:
    return _row(rid, T0 - timedelta(seconds=age_s), ["mm u wanna see my feet", "its so cute"],
                route="tease", kind="tease", **kw)


def _offer(rid: int, at: datetime, **kw) -> AiDecision:
    return _row(rid, at, ["just for u"], route="sell_now", kind="offer", price=5000, **kw)


def case_pending_tease_window():
    chat = _row(1, T0 - timedelta(hours=1), ["heyy"])
    for age, held in ((0, True), (899, True), (900, True), (901, False), (3600, False)):
        tease = _tease(2, age)
        got = t.pending_tease_of([chat, tease], T0)
        assert (got is tease) is held and (got is None) is (not held), (age, got)
    assert t.TEASE_TTL_S == 900
    assert t.pending_tease_of([_tease(2, 1000)], T0, ttl_s=1200) is not None   # the window is a knob
    assert t.pending_tease_of([], T0) is None


def case_pending_tease_ends():
    tease_at = T0 - timedelta(seconds=300)
    for outcome in ("bought", "declined"):
        # An earlier Offer settled after the tease: an outcome since.
        since = _offer(1, T0 - timedelta(hours=1), outcome=outcome, outcome_at=tease_at + timedelta(seconds=1))
        assert t.pending_tease_of([since, _tease(2, 300)], T0) is None, outcome
        # Settled before the tease: the tease holds.
        before = _offer(1, T0 - timedelta(hours=1), outcome=outcome, outcome_at=tease_at - timedelta(seconds=1))
        assert t.pending_tease_of([before, _tease(2, 300)], T0) is not None, outcome
    # Another outbound since: a newer sent row (any Route) is the newest sent, so no tease is.
    for later in (_row(3, T0 - timedelta(seconds=60), ["haha"]),
                  _offer(3, T0 - timedelta(seconds=60))):
        assert t.pending_tease_of([_tease(2, 300), later], T0) is None, later.route
    # A newer row that sent nothing (failed / no_send, any Route) is no outbound: the tease holds.
    for later in (_tease(3, 60, status="failed"), _row(3, T0 - timedelta(seconds=60), [], status="failed"),
                  _row(3, T0 - timedelta(seconds=60), [], route="no_send", status="no_send")):
        tease = _tease(2, 300)
        assert t.pending_tease_of([tease, later], T0) is tease, (later.route, later.status)
    # Not a sent test tease carrying a Pick.
    for row in (_tease(2, 300, status="failed"), _tease(2, 300, mode="shadow"),
                _row(2, tease_at, ["mm"], route="tease"),                     # tease Route, no Pick
                _offer(2, tease_at)):                                        # a priced Offer
        assert t.pending_tease_of([row], T0) is None, (row.status, row.mode, row.offer_item_ref)


def case_pending_offer_text_tease_first():
    open_offer = _offer(1, T0 - timedelta(hours=1))
    priced = "locked $50 message: just for u"
    assert t.pending_offer_text([open_offer], T0) == priced
    # A Pending tease goes first: its text (every bubble of the tease row).
    assert t.pending_offer_text([open_offer, _tease(2, 899)], T0) == "mm u wanna see my feet its so cute"
    # Expired tease: the open Offer again; no Offer either: "none".
    assert t.pending_offer_text([open_offer, _tease(2, 901)], T0) == priced
    assert t.pending_offer_text([_tease(2, 901)], T0) == "none"
    assert t.pending_offer_text([], T0) == "none"


def _haggle(rid: int, ref: int, at: datetime, price: int, *, over: int = 1, **kw) -> AiDecision:
    """A haggle row offering piece `ref` (locked [ref], list 5000) at `price`, re-offering row `over`."""
    r = _offer(rid, at, **kw)
    r.route_row, r.offer_price_cents, r.offer_list_cents = "haggle", price, 5000
    r.offer_item_ref = json.dumps({**json.loads(r.offer_item_ref), "ref": ref, "over": over})
    r.offer_media_json = json.dumps({"locked": [ref], "previews": []})
    return r


def case_open_offer_superseded():
    first = _offer(1, T0 - timedelta(minutes=9))                    # piece 10 at $50
    at, later = T0 - timedelta(minutes=8), T0 - timedelta(minutes=7)
    for ref in (10, 30):                                             # same piece, or a re-pick
        hag = _haggle(2, ref, at, 3400)
        assert t.open_offer_of([first, hag]) is hag, ref
        for outcome in ("bought", "declined"):                      # $50 superseded, never open again
            done = _haggle(2, ref, at, 3400, outcome=outcome, outcome_at=T0)
            assert t.open_offer_of([first, done]) is None, (ref, outcome)
    again = _haggle(3, 10, later, 3400, over=2)                      # a haggle on the haggle row
    assert t.open_offer_of([first, _haggle(2, 10, at, 3400), again]) is again
    assert t.open_offer_of([first, _haggle(2, 10, at, 3400), _haggle(3, 10, later, 3400, over=2,
                                                                       outcome="declined", outcome_at=T0)]) is None
    sold = _offer(3, later, outcome="bought", outcome_at=T0)        # a plain sell: no supersede
    assert t.open_offer_of([first, sold]) is first
    bought_first = _offer(1, T0 - timedelta(minutes=9), outcome="bought", outcome_at=T0)
    assert t.open_offer_of([bought_first, _haggle(2, 10, at, 3400)]) is None   # he owns piece 10
    # Offer A open, Offer B, a haggle of B; B settled: A is open again, never hidden by B's haggle.
    b_offer = _offer(2, at)
    for outcome in ("bought", "declined"):
        b_done = _offer(2, at, outcome=outcome, outcome_at=T0)
        hag_b = _haggle(3, 20, later, 3400, over=2)
        want = first if outcome == "bought" else hag_b               # bought B: he owns piece 20
        assert t.open_offer_of([first, b_done, hag_b]) is want, outcome
        assert t.open_offer_of([first, b_done, _haggle(3, 20, later, 3400, over=2, outcome="declined",
                                                       outcome_at=T0)]) is first, outcome
    assert t.open_offer_of([first, b_offer, _haggle(3, 20, later, 3400, over=2)]).id == 3
    assert t.open_offer_of([first]) is first and t.open_offer_of([]) is None
    piece = t.teased_of(_haggle(2, 10, at, 3400))
    assert (piece.locked, piece.list_cents, piece.row_id) == ((10,), 5000, 2), piece
    assert t.teased_of(_tease(4, 10)).list_cents == 2500


_harness.run()
