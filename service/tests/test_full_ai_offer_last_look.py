#!/usr/bin/env python3
"""test_full_ai_offer_last_look — the last look drops a PPV he came to own, or a second Offer
behind an unconfirmed one (phase 05 ticket 89, full_ai_live `offer_valid`).

The live Turn through `full_ai_live.run` (OF faked, Jev + Writers faked, temp DB). Every Turn rides
a Pick on its last bubble; a `ppv` bubble sender over `full_ai_ppv.send_priced` stands in for
ticket 90's. His purchases land through the fake OF's send hook (between bubbles).

  case_owned_after_bubble_1    he buys the Pick's media from another lane's PPV after bubble 1: the PPV is not
                               sent, Offer columns NULL, offer_dropped owned, exactly one OF send
  case_unrelated_purchase      he buys other media: the PPV is sent
  case_preview_owned           a preview id of the Pick becomes owned: dropped owned
  case_unconfirmed_100s        an unconfirmed priced row 100 s old: the PPV dropped unconfirmed, the text
                               bubbles before it sent
  case_unconfirmed_1000s       1000 s old: the PPV is sent
  case_unconfirmed_lands       its message lands first (settle links it): not blocking, PPV sent, its
                               media in `sent`
  case_free_item               a Free item: never blocked by unconfirmed; dropped by owned
  case_next_turn_clean         after a drop: the next Turn has no open Offer, Pending offer "none"
  case_ppv_only_loader         the loader reads nothing for a text bubble (0 settle pulls)

Run: ./venv/bin/python service/tests/test_full_ai_offer_last_look.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import dataclasses  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from _full_ai_live_fixtures import LiveOF, clear_pause, dm, live_rows, payload, seed_live, world  # noqa: E402
from automations import full_ai_live, full_ai_owned, full_ai_ppv, full_ai_settle, full_ai_test  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Message  # noqa: E402

os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")
OFFER_COLS = ("offer_price_cents", "offer_list_cents", "offer_media_json", "offer_item_ref")
LOCKED, PREVIEW = (8811, 8812), 8801
PICK = Pick(ref=8811, media=LOCKED, previews=(PREVIEW,), price_cents=1500, list_cents=1500,
            subject="any", format="photo", lane="paid", facts={})
FREE = dataclasses.replace(PICK, price_cents=0)
_ids = iter(range(9_300_000_000_000, 10**15))


@contextlib.contextmanager
def _patched(obj, name, value):
    real = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield real
    finally:
        setattr(obj, name, real)


async def _send_ppv(client, look) -> dict:
    """Ticket 90's stand-in: the priced bubble through `send_priced` (it writes its own row)."""
    b = look.bubble
    got = await full_ai_ppv.send_priced(client, row_id=look.row["id"], account_id=look.account_id,
                                        fan_id=look.fan_id, text=b["text"], ppv=b["ppv"],
                                        send_purpose=full_ai_live.SEND_PURPOSE,
                                        min_gap_s=full_ai_live.WRITE_GAP_S)
    return {"id": got.message_id, "attributed": True, "offer_dropped": got.dropped,
            "unknown": got.outcome == full_ai_ppv.UNCONFIRMED}


@contextlib.contextmanager
def _selling(pick: Pick = PICK, n: int = 2):
    """Every Turn: her last `n` bubbles, the last carrying `pick`; the `ppv` sender registered."""
    real = full_ai_test.send

    def send(row, parts, _pick=None, **kw):
        row["route"] = "sell_now"
        return real(row, parts[-n:], pick, **kw)
    with _patched(full_ai_live.full_ai_test, "send", send), \
            _patched(full_ai_live, "BUBBLE_SENDERS", {**full_ai_live.BUBBLE_SENDERS, "ppv": _send_ppv}):
        yield


async def _turn(aid, fan, mid, *, of=None, pick=PICK, n=2, rid=None):
    rid = rid or await seed_live(aid)
    await dm(aid, fan, mid)
    with _selling(pick, n), world(of) as w:
        res = await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)
    rows = await live_rows(aid, fan)
    return res, w, rows[-1]


def _reply(row) -> dict:
    return json.loads(row.reply_json)


async def _bought(aid, fan, media) -> None:
    """Another lane's PPV he paid for (a paid outbound with its media)."""
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=next(_ids), direction="out", body="funnel ppv",
                      created_at=datetime.utcnow() - timedelta(minutes=1), price_cents=2000, is_paid=True,
                      purchased_at=datetime.utcnow(), media_ids=json.dumps(list(media)),
                      automation_kind="reply_mass_funnel"))


def _buys_after_first(aid, fan, media) -> LiveOF:
    loop = asyncio.get_running_loop()

    def after(n, _text):
        if n == 1:              # OF's send runs in a worker thread: write on the test's loop
            asyncio.run_coroutine_threadsafe(_bought(aid, fan, media), loop).result()
    return LiveOF(after=after)


def _dropped(row, w, why: str, sends: int) -> None:
    reply = _reply(row)
    assert "message_id" not in reply["parts"][-1] and "ppv" in reply["parts"][-1], reply["parts"]
    assert reply.get("offer_dropped") == why, reply
    assert reply["cut"]["check"] == "offer_valid" and reply["cut"]["reason"] == why, reply["cut"]
    assert all(getattr(row, c) is None for c in OFFER_COLS), [getattr(row, c) for c in OFFER_COLS]
    assert (row.status, w.of.calls) == ("sent", sends), (row.status, w.of.calls)
    assert not any("price" in s for s in w.of.sent), w.of.sent


def _sent(row, w) -> None:
    reply = _reply(row)
    assert reply["parts"][-1].get("message_id") and "offer_dropped" not in reply, reply
    assert row.offer_message_id == reply["parts"][-1]["message_id"] and row.offer_price_cents == PICK.price_cents
    assert w.of.calls == len(reply["parts"]) and w.of.sent[-1].get("price") == PICK.price_cents / 100, w.of.sent


async def case_owned_after_bubble_1():
    aid, fan, mid = "fa_ol_own", 1101, 11101
    _res, w, row = await _turn(aid, fan, mid, of=_buys_after_first(aid, fan, LOCKED[:1]))
    _dropped(row, w, "owned", 1)


async def case_unrelated_purchase():
    aid, fan, mid = "fa_ol_other", 1102, 11201
    _res, w, row = await _turn(aid, fan, mid, of=_buys_after_first(aid, fan, (4242,)))
    _sent(row, w)


async def case_preview_owned():
    aid, fan, mid = "fa_ol_prev", 1103, 11301
    _res, w, row = await _turn(aid, fan, mid, of=_buys_after_first(aid, fan, (PREVIEW,)))
    _dropped(row, w, "owned", 1)


async def _unconfirmed(aid, fan, age_s: float, *, price=900) -> int:
    """A priced Offer row of ours with no OF id yet (sent maybe), `age_s` old."""
    async with get_session() as s:
        r = AiDecision(account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=f"u{fan}",
                       created_at=datetime.utcnow() - timedelta(seconds=age_s), route="sell_now", heat=2,
                       route_row="x", question_version="q", status="unconfirmed", jev_json="{}",
                       reply_json=json.dumps({"parts": [{"text": "just for u", "ppv": {}}]}),
                       offer_price_cents=price, offer_list_cents=price,
                       offer_media_json=json.dumps({"locked": [7701], "previews": []}),
                       offer_item_ref=json.dumps({"ref": 7701, "subject": "anything", "format": "photo", "kind": "offer"}))
        s.add(r)
        await s.flush()
        return r.id


async def case_unconfirmed_100s():
    aid, fan, mid = "fa_ol_unc", 1104, 11401
    rid = await seed_live(aid)
    await _unconfirmed(aid, fan, 100)
    _res, w, row = await _turn(aid, fan, mid, n=3, rid=rid)
    _dropped(row, w, "unconfirmed", len(_reply(row)["parts"]) - 1)
    assert w.of.calls >= 1


async def case_unconfirmed_1000s():
    aid, fan, mid = "fa_ol_unc_old", 1105, 11501
    rid = await seed_live(aid)
    await _unconfirmed(aid, fan, 1000)
    _res, w, row = await _turn(aid, fan, mid, rid=rid)
    _sent(row, w)


async def case_unconfirmed_lands():
    aid, fan, mid = "fa_ol_unc_land", 1106, 11601
    rid = await seed_live(aid)
    uid = await _unconfirmed(aid, fan, 100)
    landed = next(_ids)
    # its PPV, as the scrape finds it on OF: ours, same price and media (W30 F3: settle links an exact
    # media match only), no tag
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=landed, direction="out", body="just for u",
                      created_at=datetime.utcnow() - timedelta(seconds=95), price_cents=900,
                      media_ids=json.dumps([7701]), media_count=1))
    _res, w, row = await _turn(aid, fan, mid, rid=rid)
    _sent(row, w)
    rows = await live_rows(aid, fan)
    assert next(r for r in rows if r.id == uid).offer_message_id == landed
    sold = await full_ai_owned.load_sold(aid, fan)
    assert 7701 in full_ai_owned.sent_live(rows, sold.vault_media)


async def case_free_item():
    aid, fan, mid = "fa_ol_free", 1107, 11701
    rid = await seed_live(aid)
    await _unconfirmed(aid, fan, 100)
    _res, w, row = await _turn(aid, fan, mid, pick=FREE, rid=rid)
    reply = _reply(row)
    assert reply["parts"][-1].get("message_id") and "offer_dropped" not in reply, reply
    assert w.of.calls == len(reply["parts"]), w.of.calls
    aid, fan, mid = "fa_ol_free_own", 1108, 11801
    _res, w, row = await _turn(aid, fan, mid, pick=FREE, of=_buys_after_first(aid, fan, LOCKED[1:]))
    _dropped(row, w, "owned", 1)


async def case_next_turn_clean():
    aid, fan, mid = "fa_ol_next", 1109, 11901
    _res, w, row = await _turn(aid, fan, mid, of=_buys_after_first(aid, fan, LOCKED))
    _dropped(row, w, "owned", 1)
    assert full_ai_owned.open_offer_live(await live_rows(aid, fan), datetime.utcnow()) is None
    await clear_pause(aid, fan)
    await dm(aid, fan, mid + 1, "ok what now", ago_s=0)
    # A new line: the first Turn's, sent again, is her own line repeated (floor `repeat`).
    with world(line="ok:mm nothing much babe, just lying in bed thinking about u") as w2:
        res = await full_ai_live.run(aid, payload(fan, mid + 1, await full_ai_live.live_rule(aid)), run_id=0)
    assert res.get("row_status") == "sent", res
    state = w2.jev.calls[0]["state"]
    pending = [v for k, v in state.items() if "pending" in k.lower()]
    assert pending == ["none"], state


async def case_ppv_only_loader():
    aid, fan, mid = "fa_ol_text", 1110, 12001
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    pulls = []

    async def pull(*a, **k):
        pulls.append(a)
        return 0
    with _patched(full_ai_settle, "settle_pull", pull), world() as w:
        await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)
    (row,) = await live_rows(aid)
    assert row.status == "sent" and pulls == [(aid, fan)], pulls      # Turn start only (90)
    pulls.clear()
    with _patched(full_ai_settle, "settle_pull", pull):
        await _turn("fa_ol_text2", 1111, 12101)
    assert len(pulls) == 2, pulls                                       # Turn start + the ppv loader


_harness.run()
