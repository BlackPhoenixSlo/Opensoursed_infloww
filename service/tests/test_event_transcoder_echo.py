#!/usr/bin/env python3
"""
event_transcoder — a Creator echo (OF web/app/Infloww send: no `fromUser`, `chatUserId` = the Fan).

  new echo        one out `messages` row, the `chats` preview advanced (unread 0), the cached page-0
                  window moved/updated without an unread bump, the outbound hook fired, that get_chat dropped
  already stored  (our send handler first) the row's attribution untouched, no hook, no preview move
  isFromQueue     no row (a mass copy is its placeholder's)
  relay send in flight  no row (its handler writes it tagged); once it ended, a new echo is stored
  echo first      write_outbound_attribution's rowcount-0 path still rests the Fan (W7 hard yield)

Run: ./venv/bin/python service/tests/test_event_transcoder_echo.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import itertools  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import attribution  # noqa: E402
import employees  # noqa: E402
import event_transcoder as et  # noqa: E402
import relay_cache  # noqa: E402
import relay_hooks  # noqa: E402
import sends_inflight  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Employee, Fan, Message  # noqa: E402
from sqlalchemy import select  # noqa: E402

_AID = "8826101"
_ids = itertools.count(2_610_000_001)
_fans = itertools.count(778_000)
_hooked: list[tuple] = []
relay_hooks.outbound_sent.append(lambda *a: _hooked.append(a))


async def _seed() -> None:
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID))


def _echo(fan: int, mid: int, **kw) -> dict:
    m = {"id": mid, "text": "<p>on it</p>", "price": 0, "isTip": False, "isFromQueue": False,
         "chatUserId": fan, "toUser": {"id": fan}, "createdAt": "2026-11-23T07:19:09+00:00"}
    m.update(kw)
    return {"api2_chat_message": m, "__account_id": _AID}


async def _row(fan: int, mid: int):
    async with get_session() as s:
        return (await s.execute(select(Message).where(
            Message.account_id == _AID, Message.fan_id == fan, Message.message_id == mid))).scalar_one_or_none()


async def _chat(fan: int):
    async with get_session() as s:
        return await s.get(Chat, (_AID, fan))


def _window(fan: int, other: int, last_id: int) -> dict:
    return {"list": [{"withUser": {"id": other}, "lastMessage": {"id": 1}},
                     {"withUser": {"id": fan}, "lastMessage": {"id": last_id},
                      "hasUnread": True, "unreadMessagesCount": 2}]}


async def case_new_echo_stores_and_updates_everything():
    await _seed()
    fan, other, mid = next(_fans), next(_fans), next(_ids)
    async with get_session() as s:
        s.add(Chat(account_id=_AID, fan_id=fan, last_message_id=mid - 1,
                   last_message_at=datetime(2026, 11, 23, 7, 0), last_message_preview="hi", unread_count=2))
    extras = (20, 0, "recent")
    relay_cache.invalidate("list_chats", _AID)
    await relay_cache.get_or_fetch("list_chats", _AID, extras, 300.0, lambda: _window(fan, other, mid - 1))
    await relay_cache.get_or_fetch("get_chat", _AID, (fan,), 300.0, lambda: {"warm": True})
    _hooked.clear()

    await et.transcode(_echo(fan, mid))

    row = await _row(fan, mid)
    assert row is not None and row.direction == "out" and row.body == "<p>on it</p>", row
    assert row.sent_by_employee_id is None and row.automation_kind is None and row.raw_json
    chat = await _chat(fan)
    assert (chat.last_message_id, chat.last_message_preview, chat.unread_count) == (mid, "on it", 0), chat
    win = relay_cache.peek("list_chats", _AID, extras)
    top = win["list"][0]
    assert top["withUser"]["id"] == fan and top["lastMessage"]["id"] == mid, top
    assert top["lastMessage"]["fromUser"] == {"id": int(_AID)}, "reads as the Creator's"
    assert top["unreadMessagesCount"] == 2 and top["hasUnread"] is True, "no unread bump (badge_reads owns read)"
    assert [a[1:3] for a in _hooked] == [(fan, mid)], _hooked
    assert relay_cache.peek("get_chat", _AID, (fan,)) is None


async def case_stored_row_keeps_attribution():
    await _seed()
    fan, mid = next(_fans), next(_ids)
    async with get_session() as s:
        s.add(Message(account_id=_AID, fan_id=fan, message_id=mid, direction="out", body="ours",
                      sender_name="", media_ids="[]", media_count=0, price_cents=0, is_tip=False,
                      automation_kind="followup", sent_by_employee_id=None,
                      created_at=datetime(2026, 11, 23, 7, 19, 9)))
    _hooked.clear()
    await et.transcode(_echo(fan, mid, text="<p>OF text</p>"))
    row = await _row(fan, mid)
    assert row.automation_kind == "followup" and row.body == "ours", row
    assert await _chat(fan) is None, "no preview move"
    assert _hooked == []


async def case_queue_copy_writes_nothing():
    await _seed()
    fan, mid = next(_fans), next(_ids)
    _hooked.clear()
    await et.transcode(_echo(fan, mid, isFromQueue=True))
    assert await _row(fan, mid) is None and _hooked == []


async def case_inflight_preserves_distinct_echo_and_deduplicates_own():
    await _seed()
    fan, own, distinct = next(_fans), next(_ids), next(_ids)
    send = sends_inflight.begin(_AID, fan)
    _hooked.clear()
    await et.transcode(_echo(fan, own))
    await et.transcode(_echo(fan, distinct))
    assert await _row(fan, distinct) is None
    sends_inflight.post_finished(_AID, fan, send, own)
    await attribution.write_outbound_attribution(
        account_id=_AID, fan_id=fan, message_id=own, sent_by_employee_id=None, body="relay body",
        price_cents=0, created_at=datetime(2026, 11, 23, 7, 19, 9))
    async with asyncio.timeout(2):
        while await _row(fan, distinct) is None:
            await asyncio.sleep(0.01)
    assert (await _row(fan, own)).body == "relay body"
    assert [a[1:3] for a in _hooked].count((fan, own)) == 1


async def case_deferred_echo_uses_receipt_time_without_created_at():
    await _seed()
    fan, mid = next(_fans), next(_ids)
    send = sends_inflight.begin(_AID, fan)
    before = datetime.utcnow()
    try:
        await et.transcode(_echo(fan, mid, createdAt=None))
        assert await _row(fan, mid) is None
    finally:
        released_at = datetime.utcnow()
        sends_inflight.post_finished(_AID, fan, send)
    async with asyncio.timeout(2):
        while (row := await _row(fan, mid)) is None:
            await asyncio.sleep(0.01)
    assert before <= row.created_at <= released_at, row.created_at


async def case_deferred_echo_keeps_same_timestamp_newer_inbound_and_unread():
    await _seed()
    fan, other, mid, inbound_id = next(_fans), next(_fans), next(_ids), next(_ids)
    extras = (20, 0, "recent")
    relay_cache.invalidate("list_chats", _AID)
    window = _window(fan, other, mid - 1)
    window["list"][1].update(hasUnread=False, unreadMessagesCount=0)
    await relay_cache.get_or_fetch("list_chats", _AID, extras, 300.0, lambda: window)
    echo = _echo(fan, mid)
    send = sends_inflight.begin(_AID, fan)
    try:
        await et.transcode(echo)
        assert await _row(fan, mid) is None
        incoming = {"id": inbound_id, "fromUser": {"id": fan}, "text": "reply",
                    "createdAt": echo["api2_chat_message"]["createdAt"]}
        await et.transcode({"api2_chat_message": incoming, "__account_id": _AID})
        assert (await _chat(fan)).unread_count == 1
    finally:
        sends_inflight.post_finished(_AID, fan, send)
    await asyncio.wait_for(asyncio.gather(*et._deferred_echoes), timeout=2)

    assert await _row(fan, mid) is not None
    chat = await _chat(fan)
    assert (chat.last_message_id, chat.unread_count) == (inbound_id, 1), (chat.last_message_id, chat.unread_count)
    top = relay_cache.peek("list_chats", _AID, extras)["list"][0]
    assert top["lastMessage"]["id"] == inbound_id, top
    assert top["hasUnread"] and top["unreadMessagesCount"] == 1, top


async def case_deferred_echo_advances_a_synthetic_preview_without_clearing_unread():
    await _seed()
    fan, other, mid = next(_fans), next(_fans), next(_ids)
    placeholder = attribution._MASS_PLACEHOLDER_BASE + 1
    at = datetime(2026, 11, 23, 7, 19, 9)
    async with get_session() as s:
        s.add(Chat(account_id=_AID, fan_id=fan, last_message_id=placeholder,
                   last_message_at=at, unread_count=2))
    extras = (20, 0, "recent")
    relay_cache.invalidate("list_chats", _AID)
    window = _window(fan, other, placeholder)
    window["list"][1]["lastMessage"]["createdAt"] = at.isoformat()
    await relay_cache.get_or_fetch("list_chats", _AID, extras, 300.0, lambda: window)
    send = sends_inflight.begin(_AID, fan)
    try:
        await et.transcode(_echo(fan, mid))
        assert await _row(fan, mid) is None
    finally:
        sends_inflight.post_finished(_AID, fan, send)
    await asyncio.wait_for(asyncio.gather(*et._deferred_echoes), timeout=2)

    chat = await _chat(fan)
    assert (chat.last_message_id, chat.unread_count) == (mid, 2), (chat.last_message_id, chat.unread_count)
    top = relay_cache.peek("list_chats", _AID, extras)["list"][0]
    assert top["lastMessage"]["id"] == mid, top
    assert top["hasUnread"] and top["unreadMessagesCount"] == 2, top


async def case_failed_dm_post_releases_inflight_and_echo_stores():
    from of_sends import SendsMixin

    class Refuses(SendsMixin):
        account_id = _AID

        def post_json(self, path, *, json_body):
            raise RuntimeError("wire failure")

    await _seed()
    fan, mid = next(_fans), next(_ids)
    try:
        Refuses().send_message(fan, "relay body", auto_tag=False)
    except RuntimeError as e:
        assert str(e) == "wire failure"
    else:
        raise AssertionError("POST should fail")
    assert not sends_inflight.pending(_AID, fan)
    await et.transcode(_echo(fan, mid))
    assert await _row(fan, mid) is not None


def case_inflight_counts_and_expires_without_extending_the_window():
    first = sends_inflight.begin("1", 2)
    started = first.started
    second = sends_inflight.begin("1", 2)
    assert first is second and second.started == started
    sends_inflight.post_finished("1", 2, first)
    assert sends_inflight.pending("1", 2)
    sends_inflight.post_finished("1", 2, second, 3)
    assert sends_inflight.pending("1", 2)
    second.started = time.monotonic() - sends_inflight.TTL_S - 1
    assert not sends_inflight.pending("1", 2)
    new = sends_inflight.begin("1", 2)
    sends_inflight.post_finished("1", 2, second)
    assert sends_inflight.pending("1", 2)
    sends_inflight.post_finished("1", 2, new)
    assert not sends_inflight.pending("1", 2)


async def case_unrelated_attribution_does_not_release_an_open_send():
    from of_sends import SendsMixin

    class Sends(SendsMixin):
        account_id = _AID

        def post_json(self, path, *, json_body):
            return {"id": 81}

    await _seed()
    fan = next(_fans)
    Sends().send_message(fan, "relay body", auto_tag=False)
    for mid, pending in ((82, True), (81, False)):
        await attribution.write_outbound_attribution(
            account_id=_AID, fan_id=fan, message_id=mid, sent_by_employee_id=None,
            body="relay body", price_cents=0, created_at=datetime.utcnow())
        assert sends_inflight.pending(_AID, fan) is pending


async def case_echo_first_still_rests_the_fan():
    await _seed()
    fan, mid = next(_fans), next(_ids)
    await et.transcode(_echo(fan, mid))
    async with get_session() as s:
        auto, person = Employee(display_name="Automation"), Employee(display_name="chatter-echo")
        s.add_all([auto, person])
        await s.flush()
        auto_id, person_id = auto.id, person.id

    async def _auto():
        return auto_id
    orig = employees.get_automation_employee_id
    employees.get_automation_employee_id = _auto
    try:
        await attribution.write_outbound_attribution(
            account_id=_AID, fan_id=fan, message_id=mid, sent_by_employee_id=person_id, body="on it",
            price_cents=0, created_at=datetime(2026, 11, 23, 7, 19, 9))
    finally:
        employees.get_automation_employee_id = orig
    assert (await _row(fan, mid)).sent_by_employee_id == person_id, "backfilled"
    async with get_session() as s:
        f = await s.get(Fan, (_AID, fan))
    assert f is not None and f.automation_paused_until and f.automation_paused_until > datetime.utcnow(), f


_harness.run()
