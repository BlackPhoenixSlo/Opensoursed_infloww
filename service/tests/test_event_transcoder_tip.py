#!/usr/bin/env python3
"""
event_transcoder — WS tip-detection path (regression for the dropped-tip bug).

An OF inbound tip arrives as an `api2_chat_message` with isTip=true but
**price=0**; the dollar value is in the top-level `tipAmount` field (DOLLARS),
the fan's note is in `tipText`. The transcoder used to read `price` for the tip
amount and gate both the transaction write AND the on_inbound_tip dispatch on
`price_cents > 0` — so every real tip was silently dropped (no source='ws' tx,
no tip dispatch). These cases pin the fix.

  case_tip_records_ws_tx_and_dispatches:
      isTip + price=0 + tipAmount=10 → Transaction(kind='tip', 1000c, source='ws')
      AND on_inbound_tip dispatched with tip_cents=1000.
  case_tip_amount_fallback_to_price:
      isTip + tipAmount absent + price=5.0 → falls back to 500c (defensive).
  case_non_tip_priced_message_no_tip_dispatch:
      isTip=false + price=9.99 (a PPV-priced inbound) → NO tip tx, NO tip dispatch.
  case_zero_tip_no_dispatch:
      isTip + tipAmount=0 + price=0 → nothing recorded, nothing dispatched.
  case_media_dm_does_not_fire_on_inbound_message / case_gif_dm_...:
      a non-tip media or gif DM routes its WORDS through the image hook only —
      the transcoder firing both is what made her text reply photo-blind.
  case_text_dm_still_fires_on_inbound_message / case_tip_dm_...:
      the controls: a plain text DM and a tip still fire the words hook.
  case_private_helpers_are_the_decide_ones:
      `_parse_iso` & co. are event_transcode_decide's functions, not copies.

Run: ./venv/bin/python service/tests/test_event_transcoder_tip.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

import event_transcoder as et  # noqa: E402
import webhook_dispatch  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Transaction  # noqa: E402

_AID = "9999001"


# ── dispatch capture ──────────────────────────────────────────────────
# transcode() does `from webhook_dispatch import on_inbound_tip` at call time,
# so patching the module attribute intercepts the real-time dispatch. We also
# stub on_inbound_message (the W7 reply hook) to a no-op so its fire-and-forget
# task can't do DB work / raise during the test.

_dispatched: list[dict] = []


async def _fake_on_inbound_tip(account_id, fan_id, message_id, tip_cents):
    _dispatched.append({"account_id": account_id, "fan_id": fan_id,
                        "message_id": message_id, "tip_cents": tip_cents})


# The W7 words hook. It used to be a no-op stub here; it is a RECORDER now,
# because which inbounds fire it is the thing under test: a media DM must NOT
# (the image hook owns its words — see webhook_dispatch.on_inbound_image), a
# plain text DM must.
_words_dispatched: list[dict] = []


async def _fake_on_inbound_message(account_id, fan_id, message_id, **kw):
    _words_dispatched.append({"account_id": account_id, "fan_id": fan_id,
                              "message_id": message_id, **kw})


# Inbound-IMAGE dispatch (a fan-sent photo = buying signal) — capture it the same
# way as the tip hook so we can pin the tip-vs-image routing split.
_image_dispatched: list[dict] = []


async def _fake_on_inbound_image(account_id, fan_id, message_id, has_media=True):
    _image_dispatched.append({"account_id": account_id, "fan_id": fan_id,
                              "message_id": message_id, "has_media": has_media})


webhook_dispatch.on_inbound_tip = _fake_on_inbound_tip          # type: ignore[assignment]
webhook_dispatch.on_inbound_message = _fake_on_inbound_message  # type: ignore[assignment]
webhook_dispatch.on_inbound_image = _fake_on_inbound_image      # type: ignore[assignment]


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID))


def _tip_event(*, fan_id: int, message_id: int, is_tip: bool,
               price, tip_amount=None, text="I sent you a tip", media=None,
               giphy_id=None) -> dict:
    """A minimal api2_chat_message event in the shape OF actually sends. `media`
    (a list of ids) makes it a media-bearing DM (a fan-sent photo)."""
    m: dict = {
        "id": message_id,
        "text": text,
        "price": price,
        "isTip": is_tip,
        "fromUser": {"id": fan_id},
        "createdAt": "2026-06-13T03:30:28+00:00",
        "responseType": "message",
    }
    if media is not None:
        m["media"] = [{"id": int(x)} for x in media]
        m["mediaCount"] = len(media)
    if giphy_id is not None:
        # OF sends a Giphy DM as a BARE top-level id — no media, mediaCount 0.
        m["giphyId"] = giphy_id
    if tip_amount is not None:
        m["tipAmount"] = tip_amount
        m["tipText"] = "<p>Does baby want to slide her panties off?</p>"
    return {"api2_chat_message": m, "__account_id": _AID}


async def _drain_tasks() -> None:
    """Let the fire-and-forget dispatch task(s) created by transcode() finish."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _tip_tx(message_id: int) -> Transaction | None:
    async with get_session() as s:
        return (await s.execute(
            select(Transaction).where(Transaction.account_id == _AID,
                                      Transaction.message_id == message_id,
                                      Transaction.kind == "tip")
        )).scalars().first()


# ── the real-tip shape: price=0, $ in tipAmount ───────────────────────

async def case_tip_records_ws_tx_and_dispatches():
    await _seed_account()
    _dispatched.clear()
    mid = 10001090338389
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=True, price=0, tip_amount=10,
                                  text="I sent you a $10.00 tip "))
    await _drain_tasks()

    tx = await _tip_tx(mid)
    assert tx is not None, "tip must record a transaction even with price=0"
    assert tx.amount_cents == 1000, ("tipAmount 10 → 1000c", tx.amount_cents)
    assert tx.source == "ws", ("WS-path tx defaults to source='ws'", tx.source)
    # The frame lives on the messages row; copying it here widened every tx row.
    assert tx.raw_json is None, ("WS tx stores no raw_json", len(tx.raw_json or ""))

    hits = [d for d in _dispatched if d["message_id"] == mid]
    assert len(hits) == 1, ("on_inbound_tip dispatched exactly once", _dispatched)
    assert hits[0]["tip_cents"] == 1000, ("dispatched with tipAmount cents", hits[0])


# ── defensive fallback: isTip but no tipAmount → use price ─────────────

async def case_tip_amount_fallback_to_price():
    await _seed_account()
    _dispatched.clear()
    mid = 10001090300001
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=True, price=5.0, tip_amount=None))
    await _drain_tasks()

    tx = await _tip_tx(mid)
    assert tx is not None and tx.amount_cents == 500, ("falls back to price 5.0", tx)
    hits = [d for d in _dispatched if d["message_id"] == mid]
    assert len(hits) == 1 and hits[0]["tip_cents"] == 500, _dispatched


# ── a non-tip priced inbound (PPV) must NOT take the tip path ──────────

async def case_non_tip_priced_message_no_tip_dispatch():
    await _seed_account()
    _dispatched.clear()
    mid = 10001090300002
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=9.99))
    await _drain_tasks()

    assert await _tip_tx(mid) is None, "non-tip priced message is not a tip tx"
    assert [d for d in _dispatched if d["message_id"] == mid] == [], _dispatched


# ── a $0 tip records/dispatches nothing ───────────────────────────────

async def case_zero_tip_no_dispatch():
    await _seed_account()
    _dispatched.clear()
    mid = 10001090300003
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=True, price=0, tip_amount=0))
    await _drain_tasks()

    assert await _tip_tx(mid) is None, "a $0 tip records no transaction"
    assert [d for d in _dispatched if d["message_id"] == mid] == [], _dispatched


# ── inbound IMAGE routing (a fan-sent photo = buying signal) ──────────

async def case_inbound_image_dispatches():
    await _seed_account()
    _image_dispatched.clear()
    _dispatched.clear()
    mid = 10001090300010
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=0, media=[7001],
                                  text="took this for you 🙈"))
    await _drain_tasks()

    hits = [d for d in _image_dispatched if d["message_id"] == mid]
    assert len(hits) == 1, ("a fan-sent photo fires on_inbound_image once", _image_dispatched)
    assert hits[0]["fan_id"] == 354841559, hits[0]
    assert [d for d in _dispatched if d["message_id"] == mid] == [], "not a tip"


async def case_giphy_dm_dispatches_without_media():
    """A Giphy DM has no media at all, so the old `media_ids` gate left it a blank
    turn (no text, no picture) for the AI. It now rides the same hook, reported as
    has_media=False — which is what tells the hook to suppress the buying-signal
    reactions (a laughing gif is a joke, not a nude)."""
    await _seed_account()
    _image_dispatched.clear()
    mid = 10001090300012
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=0, text="",
                                  giphy_id="Q9WDZTdraX9E4"))
    await _drain_tasks()

    hits = [d for d in _image_dispatched if d["message_id"] == mid]
    assert len(hits) == 1, ("a giphy DM fires on_inbound_image once", _image_dispatched)
    assert hits[0]["has_media"] is False, ("a gif carries no media", hits[0])


async def case_photo_dispatch_reports_media():
    """The photo lane reports has_media=True and keeps its buying-signal lane."""
    await _seed_account()
    _image_dispatched.clear()
    mid = 10001090300013
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=0, media=[7002], text=""))
    await _drain_tasks()
    hits = [d for d in _image_dispatched if d["message_id"] == mid]
    assert len(hits) == 1 and hits[0]["has_media"] is True, hits


async def case_text_only_no_image_dispatch():
    await _seed_account()
    _image_dispatched.clear()
    mid = 10001090300011
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=0, text="just saying hi"))
    await _drain_tasks()
    assert [d for d in _image_dispatched if d["message_id"] == mid] == [], \
        "a text-only DM is not an image buying signal"


async def case_zero_tip_with_media_not_image_dispatch():
    # A degenerate isTip frame (tipAmount 0) with media: words hook only (td.dm_plan).
    await _seed_account()
    _image_dispatched.clear()
    _dispatched.clear()
    _words_dispatched.clear()
    mid = 10001090300012
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=True, price=0, tip_amount=0, media=[7002]))
    await _drain_tasks()
    assert [d for d in _image_dispatched if d["message_id"] == mid] == [], \
        "a zero-amount tip with media must not hit the image path"
    assert [d for d in _dispatched if d["message_id"] == mid] == [], \
        "and a $0 tip dispatches no tip either"
    assert len([d for d in _words_dispatched if d["message_id"] == mid]) == 1, \
        ("its words still reach the words hook once", _words_dispatched)


# ── who fires the WORDS hook (the photo-blind fix) ───────────────────
# The transcoder used to fire on_inbound_message for EVERY inbound, including a
# media DM. The image hook owns a media DM's words now and hands them off itself.
# These three cases pin the routing split.

async def case_media_dm_does_not_fire_on_inbound_message():
    await _seed_account()
    _words_dispatched.clear()
    _image_dispatched.clear()
    mid = 10001090300020
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=0, media=[7010],
                                  text="look what I did"))
    await _drain_tasks()

    assert [d for d in _words_dispatched if d["message_id"] == mid] == [], \
        ("a media DM's words belong to the image hook",
         _words_dispatched)
    assert len([d for d in _image_dispatched if d["message_id"] == mid]) == 1, \
        ("and the image hook still fires exactly once", _image_dispatched)


async def case_gif_dm_does_not_fire_on_inbound_message():
    """A Giphy DM carries no media but rides the same hook (of_shapes.giphy_dm_id),
    and the hook hands its words back immediately (a gif earns no freebie). Firing
    the words here TOO would give it two racing jobs."""
    await _seed_account()
    _words_dispatched.clear()
    _image_dispatched.clear()
    mid = 10001090300021
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=0, text="",
                                  giphy_id="Q9WDZTdraX9E4"))
    await _drain_tasks()

    assert [d for d in _words_dispatched if d["message_id"] == mid] == [], \
        ("a gif DM's words belong to the image hook too", _words_dispatched)
    hits = [d for d in _image_dispatched if d["message_id"] == mid]
    assert len(hits) == 1 and hits[0]["has_media"] is False, \
        ("the gif is not stranded — the image hook still gets it", _image_dispatched)


async def case_text_dm_still_fires_on_inbound_message():
    """The control: a plain text DM is untouched by the split."""
    await _seed_account()
    _words_dispatched.clear()
    _image_dispatched.clear()
    mid = 10001090300022
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=False, price=0, text="hey you up"))
    await _drain_tasks()

    hits = [d for d in _words_dispatched if d["message_id"] == mid]
    assert len(hits) == 1, ("a text DM still fires the words hook once",
                            _words_dispatched)
    assert hits[0]["fan_id"] == 354841559, hits[0]
    assert [d for d in _image_dispatched if d["message_id"] == mid] == [], \
        "and no image hook for a text DM"


async def case_tip_dm_still_fires_on_inbound_message():
    """A TIP is not a media DM: Stage 2 leaves the tip lane's words alone (the tip
    hand-off is Stage 5). A regression here would silence every tipper."""
    await _seed_account()
    _words_dispatched.clear()
    mid = 10001090300023
    await et.transcode(_tip_event(fan_id=354841559, message_id=mid,
                                  is_tip=True, price=0, tip_amount=10))
    await _drain_tasks()

    assert len([d for d in _words_dispatched if d["message_id"] == mid]) == 1, \
        ("a tip still fires the words hook", _words_dispatched)


def case_private_helpers_are_the_decide_ones():
    import event_transcode_decide as td
    for private, public in ((et._parse_iso, td.parse_iso), (et._to_cents, td.to_cents),
                            (et._media_ids, td.media_ids), (et._strip_html, td.strip_html)):
        assert private is public, (private, public)


_harness.run(
    case_tip_records_ws_tx_and_dispatches,
    case_tip_amount_fallback_to_price,
    case_non_tip_priced_message_no_tip_dispatch,
    case_zero_tip_no_dispatch,
    case_inbound_image_dispatches,
    case_giphy_dm_dispatches_without_media,
    case_photo_dispatch_reports_media,
    case_text_only_no_image_dispatch,
    case_zero_tip_with_media_not_image_dispatch,
    case_media_dm_does_not_fire_on_inbound_message,
    case_gif_dm_does_not_fire_on_inbound_message,
    case_text_dm_still_fires_on_inbound_message,
    case_tip_dm_still_fires_on_inbound_message,
    case_private_helpers_are_the_decide_ones,
)
