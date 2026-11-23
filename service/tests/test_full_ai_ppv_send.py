#!/usr/bin/env python3
"""test_full_ai_ppv_send — the live priced bubble (phase 05, ticket 86): `full_ai_ppv.send_priced`
lands a reserved row SENT, CLEAR or UNCONFIRMED and records the media it delivered.

Rows are reserved the live way: `full_ai_test.send` builds the Offer columns and the `ppv` dict, the
row is committed `status='sending'`. OF = `_of_fixtures.FakeOF` / `PpvFailOF` (+ small subclasses);
no network, no LLM.

  case_send_outcome_table          the pure table: id; id-less ± read-back id; media reject;
                                   unreachable fan; timeout ± read-back id; read-back raised
  case_priced_sent                 FakeOF, 1500: one call (price 15.0, locked + previews, previews);
                                   `offer_message_id`; `messages` row out / full_ai_chat / 1500;
                                   `vault_sends` = locked ids, `was_purchased` NULL
  case_purchase_stamp_owns         `is_paid` flip + `ownership.try_stamp_message`: the vault rows read
                                   purchased, `owned_or_seen_media` = locked (mutation target)
  case_media_rejected_clears       `mediaFiles` reject: one OF call, Offer NULL, dropped media, no
                                   vault row, out of `sent_media_of` / `open_offer_of`; locked +
                                   preview ids re-checked by id, a 404 leaves the mirror
  case_unreachable_clears          "Cannot send message": CLEAR send, the fan skip-listed
  case_timeout_read_back           timeout + read-back finds it: SENT with that id; finds nothing /
                                   read-back raises: UNCONFIRMED, row kept, `full_ai_ppv_unconfirmed`
  case_free_item                   price 0: unlocked, vault price 0 / NULL, `stamp_media_owned` never;
                                   refused media: text lands, Offer NULL, dropped media
  case_haggle_unsends_old          `over_message_id` → one unsend(old, fan); a raising unsend keeps SENT
  case_cancel_after_of_call        CancelledError between the OF call and the write: row reserved
  case_second_call_sends_nothing   a row with `offer_message_id` makes no OF call
  case_send_purpose                reaches the audit before the OF call; missing → no call

Run: ./venv/bin/python service/tests/test_full_ai_ppv_send.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402
from itertools import count  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

from _of_fixtures import FakeOF, PpvFailOF  # noqa: E402
import audience_include  # noqa: E402
import ownership  # noqa: E402
from automations import _send_failure, full_ai_ppv, full_ai_test  # noqa: E402
from automations.full_ai_ppv import CLEAR, SENT, UNCONFIRMED, send_outcome, send_priced  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AiDecision, Message, SkipList, VaultItem, VaultSend  # noqa: E402
from of_client import OFAPIError  # noqa: E402

A = "86000001"
LOCKED, PREVIEWS = (8601, 8602), (8603,)
_fans, _keys = count(8_600_001), count(1)


class _Resp:
    def __init__(self, status_code: int, payload):
        self.status_code, self._payload = status_code, payload

    def json(self):
        return self._payload


def _media_reject() -> OFAPIError:
    body = {"errors": {"mediaFiles": ["Something wrong with attached media"]}}
    return OFAPIError("400 " + json.dumps(body), response=_Resp(400, body))


_UNREACHABLE = RuntimeError("400 Cannot send message to this user")
_TIMEOUT = TimeoutError("The read operation timed out")


class UnsendOF(FakeOF):
    """FakeOF that records unsends; `fail` makes each one raise."""

    def __init__(self, fail: bool = False):
        super().__init__()
        self.unsent: list[tuple[int, int]] = []
        self.unsend_fail = fail

    def unsend_message(self, message_id, with_user_id=None):
        self.unsent.append((int(message_id), int(with_user_id)))
        if self.unsend_fail:
            raise RuntimeError("unsend window closed")
        return {"success": True}


class MediaRejectOF(FakeOF):
    """Refuses any send carrying media (OF's `mediaFiles` 400); text alone lands."""

    def send_message(self, chat_id, text, **kw):
        if kw.get("media_files"):
            self.sent.append({"fan_id": int(chat_id), "text": text, "rejected": True, **kw})
            raise _media_reject()
        return super().send_message(chat_id, text, **kw)


class GoneMediaOF(PpvFailOF):
    """PpvFailOF whose by-id vault read 404s every id (the creator deleted them on OF)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.byid: list[int] = []

    def vault_media_by_id(self, media_id):
        self.byid.append(int(media_id))
        raise OFAPIError("404 not found", response=_Resp(404, {}))


class ReadFailOF(PpvFailOF):
    def get_messages(self, chat_id, **kw):
        raise RuntimeError("read failed too")


class SlowOF(FakeOF):
    """OF takes the PPV, then the answer is slow: the run is cancelled while it waits."""

    def __init__(self):
        super().__init__()
        self.called = threading.Event()

    def send_message(self, chat_id, text, **kw):
        out = super().send_message(chat_id, text, **kw)
        self.called.set()
        time.sleep(0.3)
        return out


def _pick(cents: int = 1500, media=LOCKED, previews=PREVIEWS) -> Pick:
    return Pick(ref=media[0], media=tuple(media), previews=tuple(previews), price_cents=cents,
                list_cents=cents or 1500, subject="shower", format="photo", lane="L1", facts={})


async def _reserve(pick: Pick, *, route: str = "sell_now") -> tuple[int, int, dict]:
    """A live row reserved as 04a's sender leaves it: Offer columns by `full_ai_test.send`,
    `status='sending'`, committed. Returns (row id, fan id, the last bubble's `ppv`)."""
    async with get_session() as s:
        if await s.get(Account, A) is None:
            s.add(Account(id=A, nickname="acct86"))
    fan = next(_fans)
    row = dict(account_id=A, fan_id=fan, mode="live", trigger_kind="inbound",
               trigger_key=str(next(_keys)), route=route, heat=2, route_row="sell",
               question_version="v", reply_json={}, jev_json={})
    full_ai_test.send(row, ["hey you", "this one is just for u"], pick)
    ppv = row["reply_json"]["parts"][-1]["ppv"]
    values = dict(row, status="sending", reply_json=json.dumps(row["reply_json"]),
                  jev_json=json.dumps(row["jev_json"]))
    async with get_session() as s:
        obj = AiDecision(**values)
        s.add(obj)
        await s.flush()
        return obj.id, fan, ppv


async def _send(fake, rid: int, fan: int, ppv: dict, **kw):
    kw.setdefault("send_purpose", "gated")
    kw.setdefault("min_gap_s", 2.0)        # full_ai_live.WRITE_GAP_S's default (its env knob unset)
    return await send_priced(fake, row_id=rid, account_id=A, fan_id=fan,
                             text="this one is just for u", ppv=ppv, **kw)


async def _row(rid: int) -> AiDecision:
    async with get_session() as s:
        return (await s.execute(select(AiDecision).where(AiDecision.id == rid))).scalar_one()


async def _vault(fan: int) -> list[VaultSend]:
    async with get_session() as s:
        return list((await s.execute(select(VaultSend).where(
            VaultSend.account_id == A, VaultSend.fan_id == fan).order_by(VaultSend.media_id))).scalars())


async def _msgs(fan: int) -> list[Message]:
    async with get_session() as s:
        return list((await s.execute(select(Message).where(
            Message.account_id == A, Message.fan_id == fan))).scalars())


def _reserved(r: AiDecision) -> bool:
    return r.offer_item_ref is not None and r.offer_price_cents is not None and r.offer_message_id is None


def _cleared(r: AiDecision) -> bool:
    return (r.offer_price_cents, r.offer_list_cents, r.offer_media_json, r.offer_item_ref,
            r.offer_message_id) == (None,) * 5


@contextlib.contextmanager
def _logs():
    lines: list[str] = []

    class _H(logging.Handler):
        def emit(self, rec):
            lines.append(rec.getMessage())
    h, lg = _H(), logging.getLogger(full_ai_ppv.__name__)
    lg.addHandler(h)
    try:
        yield lines
    finally:
        lg.removeHandler(h)


# ── Pure ─────────────────────────────────────────────────────────────

def case_send_outcome_table():
    table = [
        ("id", (9001, None, None), (SENT, None)),
        ("id-less + read-back id", (None, None, 9002), (SENT, None)),
        ("id-less + no read-back", (None, None, None), (UNCONFIRMED, None)),
        ("media-rejected raise", (None, _media_reject(), None), (CLEAR, "media")),
        ("unreachable-fan raise", (None, _UNREACHABLE, None), (CLEAR, "send")),
        ("timeout + read-back id", (None, _TIMEOUT, 9003), (SENT, None)),
        ("timeout + no read-back", (None, _TIMEOUT, None), (UNCONFIRMED, None)),
        ("read-back itself raised (no id)", (None, RuntimeError("boom"), None), (UNCONFIRMED, None)),
    ]
    for name, args, want in table:
        assert send_outcome(*args) == want, (name, send_outcome(*args), want)


# ── send_priced ──────────────────────────────────────────────────────

async def _sent_case() -> tuple[int, int, int, FakeOF]:
    rid, fan, ppv = await _reserve(_pick())
    fake = FakeOF()
    out = await _send(fake, rid, fan, ppv)
    assert out.outcome == SENT and out.dropped is None and out.message_id, out
    return rid, fan, out.message_id, fake


async def case_priced_sent():
    rid, fan, mid, fake = await _sent_case()
    assert fake.sent == [{"fan_id": fan, "text": "this one is just for u", "price": 15.0,
                          "media_files": [*LOCKED, *PREVIEWS], "previews": list(PREVIEWS)}], fake.sent
    assert (await _row(rid)).offer_message_id == mid
    msgs = await _msgs(fan)
    assert [(m.message_id, m.direction, m.automation_kind, m.price_cents) for m in msgs] == \
        [(mid, "out", "full_ai_chat", 1500)], msgs
    vs = await _vault(fan)
    assert [(v.media_id, v.message_id, v.price_cents, v.was_purchased) for v in vs] == \
        [(m, mid, 1500, None) for m in LOCKED], vs


async def case_purchase_stamp_owns():
    rid, fan, mid, _ = await _sent_case()
    async with get_session() as s:
        await s.execute(update(Message).where(Message.account_id == A, Message.fan_id == fan,
                                              Message.message_id == mid).values(is_paid=True))
    await ownership.try_stamp_message(A, fan, mid, price_cents=1500, context="test")
    vs = await _vault(fan)
    assert vs and all(v.was_purchased is True for v in vs), [(v.media_id, v.was_purchased) for v in vs]
    owned = await ownership.owned_or_seen_media(A, fan)
    assert owned == set(LOCKED), owned


async def case_media_rejected_clears():
    rid, fan, ppv = await _reserve(_pick())
    async with get_session() as s:
        for mid in LOCKED + PREVIEWS:
            if await s.get(VaultItem, (A, mid)) is None:
                s.add(VaultItem(account_id=A, media_id=mid, kind="photo", created_at=datetime.utcnow()))
    fake = GoneMediaOF(_media_reject(), taken=False)
    out = await _send(fake, rid, fan, ppv)
    await asyncio.gather(*list(_send_failure._RECHECK_TASKS))   # the re-check runs detached
    assert sorted(fake.byid) == sorted(LOCKED + PREVIEWS), fake.byid
    async with get_session() as s:
        for mid in LOCKED + PREVIEWS:
            assert (await s.get(VaultItem, (A, mid))).removed_at is not None, mid
    assert out == (CLEAR, None, "media"), out
    assert len(fake.attempts) == 1 and fake.sent == [], (fake.attempts, fake.sent)
    r = await _row(rid)
    assert _cleared(r), r.__dict__
    assert await _vault(fan) == [] and await _msgs(fan) == []
    assert full_ai_test.sent_media_of([r]) == set() and full_ai_test.open_offer_of([r]) is None


async def case_unreachable_clears():
    rid, fan, ppv = await _reserve(_pick())
    fake = PpvFailOF(_UNREACHABLE, taken=False)
    out = await _send(fake, rid, fan, ppv)
    assert out == (CLEAR, None, "send"), out
    assert len(fake.attempts) == 1 and _cleared(await _row(rid))
    async with get_session() as s:
        skip = await s.get(SkipList, (A, fan))
    assert skip is not None and skip.reason == "unreachable", skip


async def case_timeout_read_back():
    # OF took it: the read-back finds it at that price → SENT with its id.
    rid, fan, ppv = await _reserve(_pick())
    fake = PpvFailOF(_TIMEOUT, taken=True)
    out = await _send(fake, rid, fan, ppv)
    listed = fake.listed[0]["id"]
    assert out == (SENT, listed, None) and len(fake.attempts) == 1, out
    assert [kw.get("peek") for kw in fake.read_kw] == [True], fake.read_kw
    assert (await _row(rid)).offer_message_id == listed
    assert [(m.message_id, m.price_cents) for m in await _msgs(fan)] == [(listed, 1500)]
    assert [v.media_id for v in await _vault(fan)] == list(LOCKED)
    # Nothing found, or the read-back raising: UNCONFIRMED, the row as reserved, one log line.
    for of in (PpvFailOF(_TIMEOUT, taken=False), ReadFailOF(_TIMEOUT, taken=False)):
        rid, fan, ppv = await _reserve(_pick())
        with _logs() as lines:
            out = await _send(of, rid, fan, ppv)
        assert out == (UNCONFIRMED, None, None), (type(of).__name__, out)
        r = await _row(rid)
        assert _reserved(r) and r.offer_price_cents == 1500, r.__dict__
        assert await _vault(fan) == [] and await _msgs(fan) == []
        hits = [x for x in lines if x.startswith("full_ai_ppv_unconfirmed")]
        assert len(hits) == 1 and f"fan={fan} row={rid}" in hits[0], lines


async def case_free_item():
    def _never(*a, **k):
        raise AssertionError("stamp_media_owned called for a Free item")
    saved, ownership.stamp_media_owned = ownership.stamp_media_owned, _never
    try:
        rid, fan, ppv = await _reserve(_pick(0, media=(8611,), previews=()), route="make_right")
        fake = FakeOF()
        out = await _send(fake, rid, fan, ppv)
        assert out.outcome == SENT and out.message_id, out
        assert fake.sent == [{"fan_id": fan, "text": "this one is just for u",
                              "media_files": [8611]}], fake.sent       # unlocked: no price
        vs = await _vault(fan)
        assert [(v.media_id, v.price_cents, v.was_purchased) for v in vs] == [(8611, 0, None)], vs
        assert [(m.price_cents, m.automation_kind) for m in await _msgs(fan)] == [(0, "full_ai_chat")]
        assert (await _row(rid)).offer_message_id == out.message_id
        # OF refuses the media: the text lands alone, no Offer stands.
        rid, fan, ppv = await _reserve(_pick(0, media=(8612,), previews=()), route="make_right")
        fake = MediaRejectOF()
        out = await _send(fake, rid, fan, ppv)
        assert out.outcome == CLEAR and out.dropped == "media" and out.message_id, out
        assert [x.get("media_files") for x in fake.sent] == [[8612], []], fake.sent
        assert _cleared(await _row(rid)) and await _vault(fan) == []
        assert [(m.message_id, m.price_cents) for m in await _msgs(fan)] == [(out.message_id, 0)]
        # A Free send that raises: no read-back (price 0 would match any free message of ours).
        class _TimeoutFree(FakeOF):
            def send_message(self, chat_id, text, **kw):
                raise TimeoutError("read timed out")
            reads = 0
            def get_messages(self, chat_id, **kw):
                self.reads += 1
                return {"list": []}
        rid, fan, ppv = await _reserve(_pick(0, media=(8613,), previews=()), route="make_right")
        fake = _TimeoutFree()
        out = await _send(fake, rid, fan, ppv)
        assert out.outcome == UNCONFIRMED and _reserved(await _row(rid)) and fake.reads == 0, (out, fake.reads)
    finally:
        ownership.stamp_media_owned = saved


async def case_haggle_unsends_old():
    for fail in (False, True):
        rid, fan, ppv = await _reserve(_pick())
        old = await _send(FakeOF(), rid, fan, ppv)
        rid2, _, ppv2 = await _reserve(_pick(1200))
        async with get_session() as s:     # the haggle row to the same fan
            await s.execute(update(AiDecision).where(AiDecision.id == rid2).values(fan_id=fan))
        fake = UnsendOF(fail=fail)
        out = await _send(fake, rid2, fan, ppv2, over_message_id=old.message_id)
        assert out.outcome == SENT and out.message_id != old.message_id, out
        assert fake.unsent == [(old.message_id, fan)], fake.unsent
        assert (await _row(rid2)).offer_message_id == out.message_id
        assert len([v for v in await _vault(fan) if v.message_id == out.message_id]) == len(LOCKED)


async def case_cancel_after_of_call():
    rid, fan, ppv = await _reserve(_pick())
    fake = SlowOF()
    task = asyncio.create_task(_send(fake, rid, fan, ppv))
    while not fake.called.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
        raise AssertionError("send_priced finished after a cancel")
    except asyncio.CancelledError:
        pass
    assert len(fake.sent) == 1
    r = await _row(rid)
    assert _reserved(r) and r.outcome is None, r.__dict__     # 05's unconfirmed Offer: 85 links it
    assert await _vault(fan) == [] and await _msgs(fan) == []


async def case_second_call_sends_nothing():
    rid, fan, mid, _ = await _sent_case()
    fake = FakeOF()
    ppv = {"ref": LOCKED[0], "price_cents": 1500, "media": list(LOCKED), "previews": list(PREVIEWS)}
    out = await _send(fake, rid, fan, ppv)
    assert out == (SENT, mid, None) and fake.sent == [], (out, fake.sent)
    assert len(await _vault(fan)) == len(LOCKED)


async def case_send_purpose():
    assert audience_include.AUDIENCE_SENDER_CLASSIFICATION["full_ai_ppv"] == "gated"
    seen: list[tuple] = []
    real = audience_include.audit_send_purpose

    def _audit(purpose, *, where="send"):
        seen.append((purpose, where))
        real(purpose, where=where)
    audience_include.audit_send_purpose = _audit
    try:
        rid, fan, ppv = await _reserve(_pick())
        await _send(FakeOF(), rid, fan, ppv)
        # W30 F8 / S8: the POST goes through the write seam, which audits it (once).
        assert seen == [("gated", "of_write_paced")], seen
        seen.clear()
        rid, fan, ppv = await _reserve(_pick(0, media=(8621,), previews=()), route="make_right")
        await _send(FakeOF(), rid, fan, ppv)
        assert seen == [("gated", "of_write_paced"), ("gated", "send_dropping_bad_media")], seen
        # Untagged: the harness's test mode raises before any OF call; the row stays reserved.
        rid, fan, ppv = await _reserve(_pick())
        fake = FakeOF()
        try:
            await _send(fake, rid, fan, ppv, send_purpose=None)
            raise AssertionError("untagged send went through")
        except AssertionError as e:
            assert "send_purpose" in str(e), e
        assert fake.sent == [] and _reserved(await _row(rid))
    finally:
        audience_include.audit_send_purpose = real


_harness.run()
