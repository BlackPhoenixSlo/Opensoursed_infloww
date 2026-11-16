#!/usr/bin/env python3
"""test_full_ai_offer_resolver — the Offer resolver (spec docs/spec/phase-01-full-ai-offer-details.md › B,
ADR-0038), pure tables over fake Offer rows (SimpleNamespace), plus the OF reply id reader and the
Open Offers list helper.

  case_quote_reply_older_card       Quote-reply to an older card with a newer one open -> the older
                                    card, step quote_reply, by message id (live) and by row id (test)
  case_price_*                      "the $20 one" -> that row; same price x2 -> none, unless a media
                                    cue narrows it; no price match: one open -> it, two open -> none
  case_media_*                      the one holding the kind (newest open on a tie); an older bought
                                    video wins "the video"; no video -> the open one; previews ignored
  case_no_cue_newest_open_and_no_candidates   newest open; nothing open / no rows -> none
  case_pending_tease_is_open_candidate        open, price NULL ("no price named yet")
  case_lookback_bounds              11th newest and 8-day-old rows out; a 30 h one named by price in
  case_quoted_price_is_rows_not_folder        the row's offer_price_cents
  case_live_drops_unconfirmed_priced_rows     live: priced + no offer_message_id never a candidate
  case_open_offers_list_matches_single_fold   open_offers_of's last == open_offer_of, every row set
  case_live_open_ids                <= 24 h, priced only with an OF message id
  case_reply_to_id                  replyToMessage.id, replyToMessageId, neither, non-dict
  case_check_*                      ticket 04 (D): `offer_answer_ok` tables (counts beside previews,
                                    media nouns, durations, dollars incl. spelled, "free", none)
  case_fallback_*                   `offer_fallback`: the fact clause, a tease, a Free item, a clip,
                                    missing media ("can't confirm" with no price), none ("which one?");
                                    each worded one passes #808's Writer floor and `copied`

Run: ./venv/bin/python service/tests/test_full_ai_offer_resolver.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import json  # noqa: E402
from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from automations.full_ai_offer_details import (  # noqa: E402
    OfferFacts, build_ask, live_open_ids, offer_answer_ok, offer_fallback, resolve_offer,
)
from automations import full_ai_writers as wr  # noqa: E402
from automations.full_ai_test import open_offer_of, open_offers_of  # noqa: E402
from of_shapes import reply_to_id  # noqa: E402

NOW = datetime(2026, 11, 16, 12, 0)


def _row(rid: int, *, price: int | None = 2000, kinds=("photo",), ago_h: float = 1, omid: int | None = None,
         outcome: str | None = None, status: str = "sent", tease: bool = False, previews=()):
    """A Full AI Decision row carrying one Offer (a tease: price NULL, item kind `tease`)."""
    locked = [rid * 10 + i for i in range(len(kinds))]
    prev = [rid * 10 + 5 + i for i in range(len(previews))]
    items = [{"id": m, "kind": k, "seconds": 30 if k == "video" else None}
             for m, k in zip(locked + prev, list(kinds) + list(previews))]
    at = NOW - timedelta(hours=ago_h)
    return SimpleNamespace(
        id=rid, created_at=at, status=status, mode="test", route="tease" if tease else "sell_now",
        route_row="sell", offer_price_cents=None if tease else price, offer_list_cents=price or 2000,
        offer_message_id=omid, outcome=outcome, outcome_at=(at + timedelta(minutes=5)) if outcome else None,
        offer_media_json=json.dumps({"locked": locked, "previews": prev, "items": items}),
        offer_item_ref=json.dumps({"ref": rid, "subject": "lingerie", "format": kinds[0], "lane": "chat",
                                   "kind": "tease" if tease else "offer"}),
        reply_json=json.dumps({"parts": [{"text": "for u"}]}))


def _resolve(rows, text: str, *, open_ids=(), live: bool = False, tease=None, **quote):
    ask = build_ask(rows, NOW, frozenset(open_ids), tease, text, live=live, **quote)
    got = resolve_offer(ask)
    return (got.row.id if got.row is not None else None), got.step


def case_quote_reply_older_card():
    old, new = _row(1, price=2000, ago_h=3, omid=501), _row(2, price=3000, ago_h=1, omid=502)
    rows = [old, new]
    assert _resolve(rows, "this one?", open_ids={1, 2}, live=True, quote_message_id=501) == (1, "quote_reply")
    t_old, t_new = _row(1, price=2000, ago_h=3), _row(2, price=3000, ago_h=1)
    assert _resolve([t_old, t_new], "this one?", open_ids={1, 2}, quote_row_id=1) == (1, "quote_reply")


def case_price_unique():
    rows = [_row(1, price=2000, ago_h=3), _row(2, price=3000, ago_h=1)]
    assert _resolve(rows, "the $20 one", open_ids={1, 2}) == (1, "price")
    assert _resolve(rows, "the $30 one", open_ids={1, 2}) == (2, "price")


def case_price_tie_is_none():
    rows = [_row(1, price=2000, ago_h=3), _row(2, price=2000, ago_h=1)]
    assert _resolve(rows, "the $20 one", open_ids={1, 2}) == (None, "none")


def case_price_tie_narrowed_by_media():
    rows = [_row(1, price=2000, kinds=("video",), ago_h=3), _row(2, price=2000, ago_h=1)]
    assert _resolve(rows, "the $20 video", open_ids={1, 2}) == (1, "price")


def case_price_zero_matches():
    one = [_row(1, price=2500, ago_h=1)]
    assert _resolve(one, "is it $20?", open_ids={1}) == (1, "open_offer")
    two = [_row(1, price=2500, ago_h=3), _row(2, price=3000, ago_h=1)]
    assert _resolve(two, "is it $20?", open_ids={1, 2}) == (None, "none")


def case_media_tie_between_open():
    rows = [_row(1, price=2000, kinds=("video",), ago_h=3), _row(2, price=3000, ago_h=1)]
    assert _resolve(rows, "the video one?", open_ids={1, 2}) == (1, "media")
    rows = [_row(1, price=2000, kinds=("video",), ago_h=3), _row(2, price=3000, kinds=("video",), ago_h=1),
            _row(3, price=1500, ago_h=0.5)]
    assert _resolve(rows, "the video?", open_ids={1, 2, 3}) == (2, "media")
    assert _resolve(rows, "the video?", open_ids={3}) == (None, "none")


def case_media_older_bought_video():
    rows = [_row(1, price=2000, kinds=("video",), ago_h=30, outcome="bought"), _row(2, price=3000, ago_h=1)]
    assert _resolve(rows, "the video", open_ids={2}) == (1, "media")


def case_media_no_match_falls_to_open():
    rows = [_row(1, price=2000, ago_h=1)]
    assert _resolve(rows, "is it a video?", open_ids={1}) == (1, "open_offer")


def case_media_free_preview_does_not_count():
    rows = [_row(1, price=2000, previews=("video",), ago_h=3), _row(2, price=3000, ago_h=1)]
    assert _resolve(rows, "the video?", open_ids={1, 2}) == (2, "open_offer")


def case_no_cue_newest_open_and_no_candidates():
    rows = [_row(1, price=2000, ago_h=3), _row(2, price=3000, ago_h=1), _row(3, price=1000, ago_h=0.5)]
    assert _resolve(rows, "what is in it", open_ids={1, 2}) == (2, "open_offer")
    assert _resolve([], "what is in it") == (None, "none")
    assert _resolve(rows, "what is in it", open_ids=()) == (None, "none")


def case_pending_tease_is_open_candidate():
    tease = _row(2, tease=True, ago_h=0.1)
    rows = [_row(1, price=2000, ago_h=3, outcome="bought")]
    ask = build_ask(rows + [tease], NOW, frozenset(), tease, "what is it?")
    assert [r.id for r in ask.candidates] == [1, 2] and ask.open_ids == {2}
    got = resolve_offer(ask)
    assert (got.row.id, got.step, got.row.offer_price_cents) == (2, "open_offer", None)


def case_lookback_bounds():
    rows = [_row(i, price=1000 + i * 100, ago_h=1 + (11 - i)) for i in range(1, 12)]
    ask = build_ask(rows, NOW, frozenset(), None, "")
    assert [r.id for r in ask.candidates] == list(range(2, 12))
    assert _resolve(rows, "the $11 one") == (None, "none")       # row 1 is the 11th newest
    old = [_row(1, price=2000, ago_h=8 * 24), _row(2, price=3000, ago_h=30)]
    assert [r.id for r in build_ask(old, NOW, frozenset(), None, "").candidates] == [2]
    assert _resolve(old, "the $20 one") == (None, "none")         # 8 days old
    assert _resolve(old, "the $30 one") == (2, "price")           # > 24 h, not open, still named
    assert _resolve(old, "what is in it") == (None, "none")


def case_quoted_price_is_rows_not_folder():
    r = _row(1, price=1500, ago_h=1)
    r.offer_list_cents = 2500
    got = resolve_offer(build_ask([r], NOW, frozenset({1}), None, "the $15 one"))
    assert (got.row.offer_price_cents, got.step) == (1500, "price")


def case_live_drops_unconfirmed_priced_rows():
    rows = [_row(1, price=2000, ago_h=3, omid=None), _row(2, price=0, ago_h=2, omid=None),
            _row(3, price=3000, ago_h=1, omid=503), _row(4, price=2500, ago_h=0.5, status="failed", omid=504)]
    assert [r.id for r in build_ask(rows, NOW, frozenset(), None, "", live=True).candidates] == [2, 3]
    assert [r.id for r in build_ask(rows, NOW, frozenset(), None, "").candidates] == [1, 2, 3]
    assert _resolve(rows, "the $20 one", live=True) == (None, "none")


def case_open_offers_list_matches_single_fold():
    over = _row(3, price=1800, ago_h=0.5)
    over.offer_item_ref = json.dumps({**json.loads(over.offer_item_ref), "over": 2})
    owns = _row(5, price=2200, ago_h=0.2)
    owns.offer_media_json = _row(4).offer_media_json       # same locked ids as bought row 4
    table = [
        ([], [], None),
        ([_row(1)], [1], 1),
        ([_row(1, ago_h=3), _row(2, ago_h=1)], [1, 2], 2),
        ([_row(1, ago_h=3), _row(2, ago_h=1, outcome="bought")], [1], 1),
        ([_row(1, ago_h=3), _row(2, price=0, ago_h=1)], [1], 1),
        ([_row(1, ago_h=3), _row(2, ago_h=1), over], [1, 3], 3),
        ([_row(1, ago_h=3), _row(4, ago_h=1, outcome="bought"), owns], [1], 1),
        ([_row(1, ago_h=3, outcome="declined")], [], None),
    ]
    for rows, ids, newest in table:
        got = open_offers_of(rows)
        assert [r.id for r in got] == ids, (ids, [r.id for r in got])
        one = open_offer_of(rows)
        assert (one.id if one else None) == newest
        assert (got[-1] if got else None) is one


def case_live_open_ids():
    rows = [_row(1, ago_h=30, omid=501), _row(2, ago_h=3, omid=None), _row(3, ago_h=2, omid=503),
            _row(4, ago_h=1, omid=504, outcome="bought")]
    assert live_open_ids(rows, NOW) == {3}


def case_reply_to_id():
    assert reply_to_id({"replyToMessage": {"id": 77, "text": "x"}, "replyToMessageId": 99}) == 77
    assert reply_to_id({"replyToMessageId": "88"}) == 88
    assert reply_to_id({"replyToMessage": None, "replyToMessageId": None}) is None
    assert reply_to_id({"id": 5, "text": "hi"}) is None
    assert reply_to_id(None) is None
    assert reply_to_id([1, 2]) is None
    assert reply_to_id("x") is None


# ── Offer answer check + fallback (ticket 04, D) ──────────────────────

# 3 locked photos + 1 free preview photo at a $25 Quoted price.
PHOTOS = OfferFacts(locked_kinds={"photo": 3}, locked=3, preview_kinds={"photo": 1}, previews=1, seconds=(),
                    descriptions=("her on the bed",), quoted_cents=2500, sent_at=NOW, bought=False,
                    same_as_first=None, missing=frozenset())
# One 83 s clip, no previews, $25.
CLIP = replace(PHOTOS, locked_kinds={"video": 1}, locked=1, preview_kinds={}, previews=0, seconds=(83,))
SHORT = replace(CLIP, seconds=(2,))
TEASE = replace(PHOTOS, quoted_cents=None)
FREE = replace(PHOTOS, quoted_cents=0)
NO_MEDIA = replace(PHOTOS, locked_kinds={}, preview_kinds={}, missing=frozenset({"media"}))


def _check_table(table):
    for text, of, want in table:
        assert offer_answer_ok(text, of) == want, (text, offer_answer_ok(text, of), want)


def case_check_counts_beside_previews():
    _check_table([
        ("3 pics + 1 free preview", PHOTOS, ()),
        ("its 3 pics and 1 free pic babe", PHOTOS, ()),
        ("3 pics, and 1 pic as a preview", PHOTOS, ()),
        ("4 pics", PHOTOS, ("count",)),
        ("1 pic", PHOTOS, ("count",)),
        ("1 paid pic", PHOTOS, ("count",)),
        ("1 pic + 1 free preview", PHOTOS, ("count",)),     # the reach stops at the next count
        ("1 pic and 1 free pic", PHOTOS, ("count",)),
        ("1 paid pic and 1 free pic", PHOTOS, ("count",)),
        ("the 2nd pic is my fav", PHOTOS, ()),             # an ordinal is no count
        ("my 1st vid", CLIP, ()),
        ("three hot pics", PHOTOS, ()),
        ("a pic of me", PHOTOS, ()),                 # "a" is no count
        ("3 vids total", CLIP, ("count",)),
        ("1 vid", CLIP, ()),
    ])


def case_check_media_nouns():
    _check_table([
        ("its a video babe", PHOTOS, ("media",)),
        ("its a pic", CLIP, ("media",)),
        ("1 video and 1 free pic", replace(CLIP, preview_kinds={"photo": 1}, previews=1), ()),
    ])


def case_check_durations():
    _check_table([
        ("its 80 secs long", CLIP, ()),
        ("88 seconds", CLIP, ()),
        ("40 seconds", CLIP, ("duration",)),
        ("1 min", CLIP, ()),
        ("2 minutes", CLIP, ()),
        ("3 mins", CLIP, ("duration",)),
        ("1 minute", SHORT, ("duration",)),
        ("2 sec", SHORT, ()),
        ("30 sec", PHOTOS, ("duration",)),
    ])


def case_check_dollars_and_free():
    _check_table([
        ("its $25", CLIP, ()),
        ("25 dollars", CLIP, ()),
        ("twenty five bucks", CLIP, ()),
        ("$30", CLIP, ("dollars",)),
        ("thirty bucks", CLIP, ("dollars",)),
        ("a hundred bucks", CLIP, ("dollars",)),
        ("3 pics for $25 + 1 free preview", PHOTOS, ()),
        ("its free", PHOTOS, ("free",)),
        ("feel free to unlock", PHOTOS, ("free",)),
        ("its free", CLIP, ("free",)),               # a free preview needs a preview
        ("its free", TEASE, ("free",)),
        ("$25", TEASE, ("dollars",)),
        ("its free babe", FREE, ()),
        ("$25", FREE, ("dollars",)),
    ])


def case_check_none_resolved_and_missing_media():
    _check_table([
        ("which one babe?", None, ()),
        ("its 3 pics", None, ("none",)),
        ("the video?", None, ("none",)),
        ("its 30 sec", None, ("none",)),
        ("$25", None, ("none",)),
        ("3 pics", NO_MEDIA, ("none",)),
        ("hmm i cant say babe", NO_MEDIA, ()),
        ("its $25", NO_MEDIA, ()),                   # the price is the row's fact, not the media's
        ("$30", NO_MEDIA, ("none",)),
        ("$25", replace(NO_MEDIA, quoted_cents=None), ("none",)),
    ])


def case_fallback_fact_clause():
    table = [
        (PHOTOS, "3 pics + 1 free preview, $25"),
        (TEASE, "3 pics + 1 preview"),                  # no price named yet, never "free"
        (FREE, "3 pics + 1 preview, free"),
        (replace(CLIP, preview_kinds={"photo": 1}, previews=1), "1 vid + 1 free preview, 83 sec, $25"),
        (NO_MEDIA, "$25"),                              # no counts, no kinds
        (replace(NO_MEDIA, quoted_cents=None), "can't confirm what's in it"),   # named, nothing to state
    ]
    for of, want in table:
        assert offer_fallback(of) == want, (of, offer_fallback(of), want)
    for of in (PHOTOS, TEASE, FREE, CLIP, SHORT, NO_MEDIA, replace(NO_MEDIA, quoted_cents=None),
               replace(NO_MEDIA, quoted_cents=0)):     # every fact clause passes its own check
        assert offer_answer_ok(offer_fallback(of), of) == (), (of, offer_fallback(of))
    assert "free" not in offer_fallback(TEASE) and "$" not in offer_fallback(TEASE)


def case_fallback_none_is_which_one():
    assert offer_fallback(None) == "which one?"
    assert offer_answer_ok(offer_fallback(None), None) == ()


def case_fallback_passes_writer_floor():
    """#808's Writer floor never runs on the fallback (it goes through the reply chain only), but
    every worded fallback would pass it: no label / quote strip changes it, `reject` passes it and
    it copies no run of its own facts block. "$25" (no media) has no letters: the chain ships it
    (case_d_missing_media_fallback_no_counts), the Writer floor would say `no_letters`."""
    pieces = lambda of: wr.prompt_pieces(wr.offer_facts_block(of))        # noqa: E731
    for of in (PHOTOS, TEASE, FREE, CLIP, SHORT, replace(NO_MEDIA, quoted_cents=None),
               replace(NO_MEDIA, quoted_cents=0), None):
        fb = offer_fallback(of)
        assert wr.strip_quotes(wr.strip_labels(fb)) == fb, (of, fb)
        assert wr.reject(fb, "en", False) is None, (of, fb, wr.reject(fb, "en", False))
        assert wr.copied(fb, pieces(of), []) is None, (of, fb)
    assert wr.reject(offer_fallback(NO_MEDIA), "en", False) == "no_letters"


if __name__ == "__main__":
    _harness.run()
