#!/usr/bin/env python3
"""test_full_ai_owned_live — what a live Fan owns, was sent and spent across every lane, and the
24 h open Offer (phase 05, ticket 87). Pure tables over hand-built rows, then a seeded temp DB.

  case_pure_tables              owned_live / sent_live / open_offer_live over a Free item, a cleared
                                row, an unconfirmed row and a superseded Offer
  case_age_bounds               open_offer_live at 24 h -/+ 1 min and with no offer_message_id;
                                unconfirmed_of at 899 / 901 s and `but`
  case_offer_still_valid        owned preview / locked id, another unconfirmed row at 100 / 1000 s,
                                a price-0 ppv ignores the unconfirmed rule
  case_purchases_live_pure      a paid PPV + its late ledger row count once; refunded tip absent,
                                pending tip present; oldest first
  case_full_ai_to_other_lanes   a bought Full AI PPV (ticket 86's rows + the purchase stamp) is in
                                owned_or_seen_media, owners_of_media; resale_verdict refuses it
  case_other_lanes_to_full_ai   a paid mass-funnel message, a purchased vault send, a delivered ContentOffer
                                each land in owned_live; an unbought vault send only in sent_live
  case_purchases_live_db        the same rule through load_sold
  case_free_item_lane_local     a Full AI Free item: Owned for Full AI, no vault_sends row flipped,
                                not in owned_or_seen_media
  case_scrape_fill              scrape_chats._upsert_message fills '[]' media_ids, never overwrites
                                stored ids, leaves '[]' on a media-less scrape

Run: ./venv/bin/python service/tests/test_full_ai_owned_live.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import ownership  # noqa: E402
from automations import full_ai_owned as o  # noqa: E402
from automations import scrape_chats  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (Account, AiDecision, CatalogItem, ContentOffer, Message,  # noqa: E402
                       Transaction, VaultItem, VaultSend)

T0 = datetime(2026, 11, 15, 20, 0)          # the Turn's `now`
ACC = "acc87"
OWN = "9000"                                # the Creator's OF user id (scrape direction)


def _row(rid: int, age_s: float, *, price=5000, locked=(), previews=(), msg_id=None, outcome=None,
         over=None, kind="offer", cleared=False, fan=1, at=None) -> AiDecision:
    """A live row as the sender leaves it: Offer columns (reserved), `offer_message_id` once SENT;
    `cleared`: Offer columns NULL + `reply_json.offer_dropped` (spec › One row, three states)."""
    reply = {"parts": [{"text": "just for u"}]}
    offer = {}
    if cleared:
        reply["offer_dropped"] = "media"
    else:
        ref = {"ref": rid * 10, "subject": "feet", "format": "photo", "lane": "$50", "kind": kind,
               **({"over": over} if over is not None else {})}
        offer = dict(offer_price_cents=price, offer_list_cents=price or 5000,
                     offer_media_json=json.dumps({"locked": list(locked), "previews": list(previews)}),
                     offer_item_ref=json.dumps(ref), offer_message_id=msg_id)
    return AiDecision(id=rid, account_id=ACC, fan_id=fan, mode="live", trigger_kind="message",
                      trigger_key=f"live:{fan}:{rid}", created_at=at or T0 - timedelta(seconds=age_s),
                      route="sell_now", heat=2, route_row="x", question_version="v", status="sent",
                      jev_json="{}", reply_json=json.dumps(reply), outcome=outcome,
                      outcome_at=T0 if outcome else None, join_src="notice" if outcome else None,
                      **offer)


def case_pure_tables():
    free = _row(1, 3600, price=0, locked=[11], kind="free")
    cleared = _row(2, 3000, cleared=True)
    unconf = _row(3, 600, locked=[31], previews=[32])
    bought = _row(4, 500, locked=[41], msg_id=401, outcome="bought")
    rows = [free, cleared, unconf, bought]
    assert o.owned_live(rows, set()) == {11, 41}                 # Free item via owned_of; bought
    assert o.owned_live(rows, {77}) == {11, 41, 77}              # | cross
    assert o.sent_live(rows, set()) == {11, 31, 32, 41}          # unconfirmed: sent, not Owned
    assert o.sent_live(rows, {88}) == {11, 31, 32, 41, 88}       # | vault_media
    assert o.owned_live([cleared], set()) == set() == o.sent_live([cleared], set())
    assert o.open_offer_live(rows, T0) is None                   # newest priced open is unconfirmed
    first = _row(5, 900, locked=[51], msg_id=501)
    hag = _row(6, 300, price=3400, locked=[51], msg_id=601, over=5)
    assert o.open_offer_live([first, hag], T0) is hag            # superseded: never open again
    assert o.open_offer_live([first, _row(6, 300, price=3400, locked=[51], over=5)], T0) is None
    assert o.sent_live([first, hag], set()) == {51}
    assert o.owned_live([first, hag], set()) == set()
    assert o.open_offer_live([first], T0) is first and o.open_offer_live([], T0) is None
    assert o.OFFER_OPEN_S == 86400 and o.UNCONFIRMED_S == 900


def case_age_bounds():
    day = o.OFFER_OPEN_S
    young = _row(1, day - 60, locked=[1], msg_id=101)
    old = _row(1, day + 60, locked=[1], msg_id=101)
    assert o.open_offer_live([young], T0) is young
    assert o.open_offer_live([old], T0) is None
    assert o.open_offer_live([_row(1, 60, locked=[1])], T0) is None   # priced, never confirmed
    for age, held in ((0, True), (899, True), (900, True), (901, False)):
        r = _row(2, age, locked=[2])
        assert (o.unconfirmed_of([r], T0, None) is r) is held, age
    r = _row(2, 100, locked=[2])
    assert o.unconfirmed_of([r], T0, but=2) is None                   # the Turn's own row
    other = _row(1, 200, locked=[1])
    assert o.unconfirmed_of([other, r], T0, but=2) is other
    assert o.unconfirmed_of([other, r], T0, but=None) is r            # newest
    for skip in (_row(3, 10, locked=[3], msg_id=301),                 # confirmed
                 _row(3, 10, locked=[3], outcome="bought"),           # settled
                 _row(3, 10, price=0, locked=[3], kind="free"),       # not priced
                 _row(3, 10, cleared=True)):                          # cleared
        assert o.unconfirmed_of([skip], T0, None) is None, skip.id


def case_offer_still_valid():
    ppv = {"ref": 70, "price_cents": 5000, "media": [71, 72], "previews": [73]}
    assert o.offer_still_valid(ppv, {73}, [], T0, 9) == "owned"
    assert o.offer_still_valid(ppv, {72}, [], T0, 9) == "owned"
    assert o.offer_still_valid(ppv, {99}, [], T0, 9) is None
    mine = _row(9, 5, locked=[71, 72], previews=[73])                 # the Turn's reserved row
    pending = _row(8, 100, locked=[81])
    assert o.offer_still_valid(ppv, set(), [pending, mine], T0, 9) == "unconfirmed"
    assert o.offer_still_valid(ppv, set(), [_row(8, 1000, locked=[81]), mine], T0, 9) is None
    assert o.offer_still_valid(ppv, set(), [mine], T0, 9) is None     # its own row never blocks
    free = {**ppv, "price_cents": 0}
    assert o.offer_still_valid(free, set(), [pending, mine], T0, 9) is None
    assert o.offer_still_valid(free, {71}, [pending, mine], T0, 9) == "owned"


def _msg(price, paid, at, bought_at=None):
    return NS(price_cents=price, is_paid=paid, created_at=at, purchased_at=bought_at)


def _tx(kind, cents, at, status="cleared"):
    return NS(kind=kind, amount_cents=cents, occurred_at=at, status=status)


def case_purchases_live_pure():
    sent = T0 - timedelta(hours=5)
    msgs = [_msg(5000, True, sent, T0 - timedelta(hours=4)), _msg(3000, True, sent - timedelta(hours=9))]
    txs = [_tx("ppv_message", 5000, T0),                             # the PPV's late ledger row
           _tx("tip", 1000, T0 - timedelta(hours=3), "refunded"),
           _tx("tip", 2000, T0 - timedelta(hours=2), "pending"),
           _tx("tip", 700, T0 - timedelta(hours=1)),
           _tx("ppv_post", 900, T0 - timedelta(hours=6)),
           _tx("subscription", 999, T0 - timedelta(hours=7))]
    got = [(p.kind, p.amount_cents) for p in o.purchases_live(msgs, txs)]
    assert got == [("ppv_message", 3000), ("ppv_post", 900), ("ppv_message", 5000), ("tip", 2000),
                   ("tip", 700)], got
    assert o.purchases_live([_msg(5000, False, sent), _msg(0, True, sent)], []) == []
    assert o.purchases_live([], []) == []


# ── DB: a seeded temp DB, one account, a Fan per case ──

async def _seed_account():
    async with get_session() as s:
        s.add(Account(id=ACC))
        await s.commit()


async def _add(*objs):
    async with get_session() as s:
        s.add_all(objs)
        await s.commit()


def _out(fan, mid, *, price, media="[]", paid=None, kind=None, at=None):
    return Message(account_id=ACC, fan_id=fan, message_id=mid, direction="out", body="x",
                   media_ids=media, price_cents=price, is_paid=paid, automation_kind=kind,
                   created_at=at or T0 - timedelta(hours=1))


async def _vault_rows(fan, media):
    async with get_session() as s:
        return (await s.execute(select(VaultSend).where(
            VaultSend.account_id == ACC, VaultSend.fan_id == fan,
            VaultSend.media_id == media))).scalars().all()


async def _rows(fan):
    async with get_session() as s:
        return (await s.execute(select(AiDecision).where(
            AiDecision.account_id == ACC, AiDecision.fan_id == fan).order_by(AiDecision.id))).scalars().all()


async def _full_ai_to_other_lanes():
    await _seed_account()
    fan, mid, locked, prev = 101, 5001, [1011, 1012], [1013]
    row = _row(0, 600, locked=locked, previews=prev, msg_id=mid, fan=fan)
    row.id = None
    # Ticket 86 at SENT: the attribution row (media_ids '[]'), one VaultSend per locked media.
    await _add(row, _out(fan, mid, price=5000, paid=False, kind="full_ai_chat"),
               *[VaultSend(account_id=ACC, fan_id=fan, media_id=m, message_id=mid, price_cents=5000,
                           was_purchased=None) for m in locked],
               VaultItem(account_id=ACC, media_id=1011, kind="video", created_at=T0),
               VaultItem(account_id=ACC, media_id=1012, kind="photo", created_at=T0))
    assert not (set(locked) & await ownership.owned_or_seen_media(ACC, fan))   # sent, not bought
    assert fan not in await ownership.owners_of_media(ACC, locked)
    # The purchase stamp (purchase_notifications / transaction_ingest: flip is_paid, then stamp).
    async with get_session() as s:
        await s.execute(update(Message).where(Message.account_id == ACC, Message.fan_id == fan,
                                              Message.message_id == mid).values(is_paid=True))
        await s.commit()
    assert await ownership.try_stamp_message(ACC, fan, mid, price_cents=5000, context="t87") == 2
    assert set(locked) <= await ownership.owned_or_seen_media(ACC, fan)
    assert fan in await ownership.owners_of_media(ACC, [1011])
    assert fan in await ownership.owners_of_media(ACC, [1012])
    v = await ownership.resale_verdict(ACC, fan, locked + [2000], previews=prev)
    assert v.blocked and v.reason == ownership.RESALE_OWNED_VIDEO, v
    # Full AI itself sees it before its row settles (outcome NULL): through `cross`.
    sold = await o.load_sold(ACC, fan)
    rows = await _rows(fan)
    assert rows[0].outcome is None and set(locked) <= o.owned_live(rows, sold.cross)
    assert [(p.kind, p.amount_cents) for p in o.purchases_live(sold.paid_msgs, sold.txs)] == [
        ("ppv_message", 5000)]


def case_full_ai_to_other_lanes():
    asyncio.run(_full_ai_to_other_lanes())


async def _other_lanes_to_full_ai():
    fan = 102
    item = CatalogItem(account_id=ACC, kind="video", media_ids=json.dumps([2031, 2032]))
    await _add(item)
    await _add(_out(fan, 6001, price=2500, media=json.dumps([2011]), paid=True, kind="reply_mass_funnel"),
               VaultSend(account_id=ACC, fan_id=fan, media_id=2021, message_id=6002, price_cents=1500,
                         was_purchased=True),
               ContentOffer(account_id=ACC, fan_id=fan, item_id=item.id, status="delivered",
                            resolved_by="tip"),
               # Sent, unbought, another lane: sent only.
               VaultSend(account_id=ACC, fan_id=fan, media_id=2041, message_id=6004, price_cents=3000,
                         was_purchased=None),
               # A free teaser delivery is never Owned.
               ContentOffer(account_id=ACC, fan_id=fan, item_id=item.id, status="delivered",
                            resolved_by="free"))
    sold = await o.load_sold(ACC, fan)
    rows = [_row(1, 60, locked=[2051], msg_id=6005, fan=fan)]
    owned, sent = o.owned_live(rows, sold.cross), o.sent_live(rows, sold.vault_media)
    for m in (2011, 2021, 2031, 2032):
        assert m in owned, (m, owned)
    assert 2041 in sent and 2041 not in owned, (sent, owned)
    assert 2051 in sent and 2051 not in owned
    assert sold.vault_media == {2021, 2041}


def case_other_lanes_to_full_ai():
    asyncio.run(_other_lanes_to_full_ai())


async def _purchases_live_db():
    fan = 103
    sent = T0 - timedelta(hours=5)
    paid = _out(fan, 7001, price=5000, paid=True, kind="full_ai_chat", at=sent)
    paid.purchased_at = T0 - timedelta(hours=4)
    tx = lambda kind, cents, h, status="cleared": Transaction(  # noqa: E731
        account_id=ACC, fan_id=fan, kind=kind, message_id=7001 if kind == "ppv_message" else None,
        amount_cents=cents, occurred_at=T0 - timedelta(hours=h), status=status)
    await _add(paid, _out(fan, 7002, price=4000, paid=False, at=sent),             # unbought
               Message(account_id=ACC, fan_id=fan, message_id=7003, direction="in", body="",
                       price_cents=900, is_paid=True, created_at=sent),           # his, not ours
               tx("ppv_message", 5000, 0), tx("tip", 1000, 3, "refunded"), tx("tip", 2000, 2, "pending"),
               tx("tip", 700, 1), tx("ppv_post", 900, 6), tx("chargeback", -5000, 0.5),
               Transaction(account_id=ACC, fan_id=999, kind="tip", amount_cents=4242,
                           occurred_at=T0))                                        # another Fan
    sold = await o.load_sold(ACC, fan)
    got = [(p.kind, p.amount_cents) for p in o.purchases_live(sold.paid_msgs, sold.txs)]
    assert got == [("ppv_post", 900), ("ppv_message", 5000), ("tip", 2000), ("tip", 700)], got


def case_purchases_live_db():
    asyncio.run(_purchases_live_db())


async def _free_item_lane_local():
    fan, media = 104, 3011
    # Another lane sent this media earlier, unbought.
    earlier = VaultSend(account_id=ACC, fan_id=fan, media_id=media, message_id=8001, price_cents=2000,
                        was_purchased=None)
    free = _row(0, 60, price=0, locked=[media], msg_id=8002, kind="free", fan=fan)
    free.id = None
    await _add(earlier, free, _out(fan, 8002, price=0, kind="full_ai_chat"),
               VaultSend(account_id=ACC, fan_id=fan, media_id=media, message_id=8002, price_cents=0,
                         was_purchased=None))
    sold = await o.load_sold(ACC, fan)
    rows = await _rows(fan)
    assert media in o.owned_live(rows, sold.cross)                 # Owned for Full AI (owned_of)
    assert media not in sold.cross                                 # lane-local (spec ASSUMPTION)
    assert media not in await ownership.owned_or_seen_media(ACC, fan)
    assert fan not in await ownership.owners_of_media(ACC, [media])
    vs = await _vault_rows(fan, media)
    assert len(vs) == 2 and all(v.was_purchased is None for v in vs), [v.was_purchased for v in vs]
    assert o.purchases_live(sold.paid_msgs, sold.txs) == []        # never a sale


def case_free_item_lane_local():
    asyncio.run(_free_item_lane_local())


def _of(mid, *, media=(), price=50.0, opened=True):
    return {"id": mid, "fromUser": {"id": int(OWN)}, "createdAt": "2026-11-15T19:00:00+00:00",
            "price": price, "media": [{"id": m} for m in media], "mediaCount": len(media),
            "isOpened": opened, "text": "just for u"}


async def _scrape(fan, m):
    async with get_session() as s:
        await scrape_chats._upsert_message(s, ACC, fan, OWN, m)
        await s.commit()


async def _stored(fan, mid):
    async with get_session() as s:
        return (await s.execute(select(Message).where(
            Message.account_id == ACC, Message.fan_id == fan, Message.message_id == mid))).scalar_one()


async def _scrape_fill():
    fan = 105
    # An attribution-written row (mass funnel / wcfi / Full AI: media_ids '[]'), bought, then re-scraped.
    await _add(_out(fan, 9001, price=5000, paid=False, kind="reply_mass_funnel"),
               _out(fan, 9002, price=5000, media=json.dumps([4021]), paid=False),
               _out(fan, 9003, price=5000, paid=False, kind="full_ai_chat"))
    await _scrape(fan, _of(9001, media=[4011, 4012]))
    got = await _stored(fan, 9001)
    assert json.loads(got.media_ids) == [4011, 4012] and got.is_paid is True, got.media_ids
    assert {4011, 4012} <= await ownership.owned_or_seen_media(ACC, fan)   # paid-message leg
    await _scrape(fan, _of(9002, media=[4099]))                            # stored ids win
    assert json.loads((await _stored(fan, 9002)).media_ids) == [4021]
    await _scrape(fan, _of(9003, opened=False))                            # no media: stays '[]'
    assert (await _stored(fan, 9003)).media_ids == "[]"
    await _scrape(fan, _of(9001, media=[4077]))                            # filled once, then kept
    assert json.loads((await _stored(fan, 9001)).media_ids) == [4011, 4012]
    await _scrape(fan, _of(9004, media=[4041]))                            # fresh insert unchanged
    assert json.loads((await _stored(fan, 9004)).media_ids) == [4041]


def case_scrape_fill():
    asyncio.run(_scrape_fill())


_harness.run()
