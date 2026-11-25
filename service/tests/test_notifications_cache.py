#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import threading  # noqa: E402

import event_transcoder as et  # noqa: E402
import purchase_notifications as pn  # noqa: E402
import relay_cache  # noqa: E402
import relay_coalesce  # noqa: E402
import server  # noqa: E402
import webhook_dispatch  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402

_AID = "8801001"
_OTHER_AID = "8801002"

async def _noop(*_a, **_k):
    return None


webhook_dispatch.on_inbound_message = _noop  # type: ignore[assignment]
webhook_dispatch.on_inbound_tip = _noop      # type: ignore[assignment]
webhook_dispatch.on_inbound_image = _noop    # type: ignore[assignment]


class _FakeOF:

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str | None]] = []
        self.gen = 0

    def notifications(self, *, limit: int = 10, offset: int = 0,
                      type: str | None = None) -> dict:
        self.calls.append((limit, offset, type))
        self.gen += 1
        return {"list": [{"id": f"n{self.gen}", "type": type}], "gen": self.gen}


_fake = _FakeOF()
_current_aid = _AID


@contextlib.contextmanager
def _as_account(aid: str):
    global _current_aid
    prev = _current_aid
    _current_aid = aid
    try:
        yield
    finally:
        _current_aid = prev

server._resolve_account_id = lambda _req=None: _current_aid  # type: ignore[assignment]
server._load_client = lambda _aid: _fake                     # type: ignore[assignment]


async def _call(*, limit: int = 20, offset: int = 0, type=None, refresh: bool = False):
    return await server.of_notifications(limit=limit, offset=offset, type=type,
                                         related_user=None, refresh=refresh)


def _reset(aid: str = _AID) -> None:
    global _current_aid
    _current_aid = aid
    _fake.calls.clear()
    _fake.gen = 0
    relay_coalesce.reset_for_tests()
    for a in (_AID, _OTHER_AID):
        relay_cache.invalidate_money_feeds(a)


async def _seed_accounts() -> None:
    async with get_session() as s:
        for aid in (_AID, _OTHER_AID):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))


async def _drain() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)



async def case_hit_is_served_without_a_second_of_call():
    _reset()
    a = await _call(type="tip")
    b = await _call(type="tip")
    assert len(_fake.calls) == 1, f"expected 1 OF call, got {_fake.calls}"
    assert a == b, f"cached body differs: {a} != {b}"


async def case_money_types_do_not_share_an_entry():
    _reset()
    tip = await _call(type="tip")
    purchases = await _call(type="purchases")
    assert len(_fake.calls) == 2, f"types collided: {_fake.calls}"
    assert tip != purchases, "tip and purchases served the same body"
    assert await _call(type="tip") == tip
    assert await _call(type="purchases") == purchases
    assert len(_fake.calls) == 2, f"second round refetched: {_fake.calls}"


async def case_untyped_and_paged_reads_do_not_collide():
    _reset()
    await _call(type=None)
    await _call(type="tip")
    await _call(type="tip", offset=20)
    await _call(type="tip", limit=10)
    assert len(_fake.calls) == 4, f"key extras collided: {_fake.calls}"


async def case_concurrent_identical_calls_coalesce():
    _reset()
    slow = threading.Event()
    real = _fake.notifications

    def _slow(**kw):
        slow.wait()
        return real(**kw)

    _fake.notifications = _slow  # type: ignore[assignment]
    try:
        task = asyncio.gather(*[_call(type="tip") for _ in range(5)])
        await asyncio.sleep(0.05)
        slow.set()
        results = await task
    finally:
        _fake.notifications = real  # type: ignore[assignment]
    assert len(_fake.calls) == 1, f"expected 1 coalesced OF call, got {_fake.calls}"
    assert all(r == results[0] for r in results), f"waiters disagreed: {results}"


async def case_refresh_bypasses_the_cache():
    _reset()
    first = await _call(type="tip")
    forced = await _call(type="tip", refresh=True)
    assert len(_fake.calls) == 2, f"refresh=1 was served from cache: {_fake.calls}"
    assert forced != first, "refresh=1 returned the stale body"
    again = await _call(type="tip")
    assert again == forced, f"refresh did not write back: {again} != {forced}"
    assert len(_fake.calls) == 2, f"write-back missing: {_fake.calls}"



async def _assert_dropped(fire, label: str) -> None:
    _reset()
    await _seed_accounts()
    warm = await _call(type="tip")
    assert len(_fake.calls) == 1, f"{label}: warm-up: {_fake.calls}"
    await fire()
    await _drain()
    after = await _call(type="tip")
    assert len(_fake.calls) == 2, (
        f"{label}: entry survived the event — the toast fires but the feed "
        f"behind it is stale ({_fake.calls})"
    )
    assert after != warm, f"{label}: refetch returned the stale body"


async def case_inbound_tip_drops_the_entry():
    async def fire():
        await et.transcode({
            "api2_chat_message": {
                "id": 4242424242,
                "text": "here you go",
                "price": 0,
                "isTip": True,
                "tipAmount": 25,
                "fromUser": {"id": 777001},
                "createdAt": "2026-08-25T10:00:00+00:00",
                "responseType": "message",
            },
            "__account_id": _AID,
        })
    await _assert_dropped(fire, "inbound tip")


async def case_ppv_unlock_event_drops_the_entry():
    async def fire():
        await et.transcode({
            "messageUnlock": {
                "message": {"id": 5353535353, "price": 12.0,
                            "fromUser": {"id": 777002}},
                "openedAt": "2026-08-25T10:05:00+00:00",
            },
            "__account_id": _AID,
        })
    await _assert_dropped(fire, "ppv unlock")


async def case_purchase_notification_drops_the_entry():
    async def fire():
        await pn._broadcast_purchase(_AID, {
            "notif_id": "117301756206",
            "fan_id": 777003,
            "message_id": 10491720677794,
            "amount_cents": 600,
            "created_at": "2026-08-25T10:06:00+00:00",
            "name": "Daniel",
        })
    await _assert_dropped(fire, "purchase notification")


async def case_toast_drops_the_entry():
    async def fire():
        await et.transcode({
            "toasts": {
                "type": "subscribed",
                "data": {"relatedUser": {"id": 777004, "name": "Joe"}},
            },
            "__account_id": _AID,
        })
    await _assert_dropped(fire, "toast")


async def case_typing_event_does_not_drop_the_entry():
    _reset()
    await _seed_accounts()
    warm = await _call(type="tip")
    await et.transcode({"typing": {"user": {"id": 777005}}, "__account_id": _AID})
    await _drain()
    again = await _call(type="tip")
    assert len(_fake.calls) == 1, f"a typing frame busted the cache: {_fake.calls}"
    assert again == warm


async def case_a_purchase_busts_the_badge_too():
    _reset()
    ttl = 300.0
    money = ("notifications", "notifications_count")
    for ns in money:
        await relay_cache.get_or_fetch(ns, _AID, (), ttl, lambda: {"warm": True})
    await pn._broadcast_purchase(_AID, {
        "notif_id": "117301756207", "fan_id": 777007,
        "message_id": 10491720677795, "amount_cents": 900,
        "created_at": "2026-08-25T10:08:00+00:00", "name": "Daniel",
    })
    live = [ns for ns in money
            if await relay_cache.get_or_fetch(ns, _AID, (), ttl,
                                              lambda: {"warm": False}) == {"warm": True}]
    assert not live, f"a sale left these serving pre-sale bodies: {live}"


async def case_a_purchase_drops_the_cached_pins():
    _reset()
    for chat in (777008, 777009):
        await relay_cache.get_or_fetch("chat_pinned", _AID, (chat,), 300.0, lambda: {"warm": True})
    await relay_cache.get_or_fetch("chat_pinned", _OTHER_AID, (777008,), 300.0, lambda: {"warm": True})
    await pn._broadcast_purchase(_AID, {
        "notif_id": "117301756208", "fan_id": 777008,
        "message_id": 10491720677796, "amount_cents": 900,
        "created_at": "2026-08-25T10:09:00+00:00", "name": "Daniel",
    })
    for chat in (777008, 777009):
        got = await relay_cache.get_or_fetch("chat_pinned", _AID, (chat,), 300.0, lambda: {"warm": False})
        assert got == {"warm": False}, f"a sale left chat {chat}'s pins cached"
    other = await relay_cache.get_or_fetch("chat_pinned", _OTHER_AID, (777008,), 300.0, lambda: {"warm": False})
    assert other == {"warm": True}, "a sale on one model dropped another model's pins"
    relay_cache.invalidate("chat_pinned", _OTHER_AID)


async def case_a_purchase_drops_the_cached_ledger():
    _reset()
    key = ("of_transactions", ("limit", 20))
    await relay_cache.get_or_fetch("payouts", _AID, key, 900.0, lambda: {"warm": True})
    await relay_cache.get_or_fetch("payouts", _OTHER_AID, key, 900.0, lambda: {"warm": True})
    await pn._broadcast_purchase(_AID, {
        "notif_id": "117301756209", "fan_id": 777010,
        "message_id": 10491720677797, "amount_cents": 900,
        "created_at": "2026-08-25T10:10:00+00:00", "name": "Daniel",
    })
    got = await relay_cache.get_or_fetch("payouts", _AID, key, 900.0, lambda: {"warm": False})
    assert got == {"warm": False}, "a sale left the ledger cached"
    other = await relay_cache.get_or_fetch("payouts", _OTHER_AID, key, 900.0, lambda: {"warm": False})
    assert other == {"warm": True}, "a sale on one model dropped another model's ledger"
    relay_cache.invalidate("payouts", _OTHER_AID)


async def case_invalidation_is_account_scoped():
    _reset()
    await _seed_accounts()
    warm_a = await _call(type="tip")
    with _as_account(_OTHER_AID):
        warm_b = await _call(type="tip")
    assert len(_fake.calls) == 2, f"accounts shared an entry: {_fake.calls}"

    await et.transcode({
        "api2_chat_message": {
            "id": 6464646464, "text": "tip", "price": 0, "isTip": True,
            "tipAmount": 5, "fromUser": {"id": 777006},
            "createdAt": "2026-08-25T10:07:00+00:00", "responseType": "message",
        },
        "__account_id": _AID,
    })
    await _drain()

    with _as_account(_OTHER_AID):
        assert await _call(type="tip") == warm_b, "the other account's entry was dropped"
        assert len(_fake.calls) == 2, f"cross-account bust: {_fake.calls}"

    assert await _call(type="tip") != warm_a, "this account's entry survived"
    assert len(_fake.calls) == 3, f"expected a refetch for {_AID}: {_fake.calls}"



async def _money(types: str = "purchases,tip"):
    return await server.of_notifications_money(types=types, limit=20, offset=0)


async def case_money_cold_reads_each_type_once():
    _reset()
    got = await _money()
    assert sorted(_fake.calls) == [(20, 0, "purchases"), (20, 0, "tip")], _fake.calls
    assert got["tip"] == await _call(type="tip") and got["purchases"] == await _call(type="purchases")
    assert len(_fake.calls) == 2, f"the per-type route missed the combined read's entries: {_fake.calls}"


async def case_money_both_cached_costs_of_nothing():
    _reset()
    tip, purchases = await _call(type="tip"), await _call(type="purchases")
    got = await _money()
    assert len(_fake.calls) == 2, f"a cached list was read again: {_fake.calls}"
    assert got == {"purchases": purchases, "tip": tip}, got


async def case_money_one_cached_reads_only_the_other():
    _reset()
    tip = await _call(type="tip")
    got = await _money()
    assert _fake.calls == [(20, 0, "tip"), (20, 0, "purchases")], _fake.calls
    assert got["tip"] == tip


async def case_money_reads_only_the_asked_types():
    _reset()
    got = await _money("tip")
    assert _fake.calls == [(20, 0, "tip")] and set(got) == {"tip"}, (_fake.calls, got)


async def case_money_coalesces_with_a_per_type_read_in_flight():
    _reset()
    relay_cache._locks.clear()
    relay_cache._registry_lock = asyncio.Lock()
    slow = threading.Event()
    real = _fake.notifications

    def _slow(**kw):
        slow.wait()
        return real(**kw)

    _fake.notifications = _slow  # type: ignore[assignment]
    try:
        task = asyncio.gather(_call(type="tip"), _money())
        await asyncio.sleep(0.05)
        slow.set()
        single, combined = await task
    finally:
        _fake.notifications = real  # type: ignore[assignment]
    assert sorted(_fake.calls) == [(20, 0, "purchases"), (20, 0, "tip")], _fake.calls
    assert combined["tip"] == single


async def case_money_one_failed_type_answers_the_other():
    _reset()
    real = _fake.notifications

    def _tip_fails(**kw):
        if kw.get("type") == "tip":
            raise server.HTTPException(status_code=429, detail="slow down")
        return real(**kw)

    _fake.notifications = _tip_fails  # type: ignore[assignment]
    try:
        server._proxy = _proxy_passthrough(server._proxy)
        got = await _money()
        both_failed = None
        try:
            await _money("tip")
        except server.HTTPException as e:
            both_failed = e.status_code
    finally:
        _fake.notifications = real  # type: ignore[assignment]
        server._proxy = server._proxy.__wrapped__  # type: ignore[attr-defined]
    assert "purchases" in got and got["errors"] == {"tip": {"status": 429, "detail": "slow down"}}, got
    assert both_failed == 429, both_failed


def _proxy_passthrough(real):
    def proxy(fn, *a, **kw):
        try:
            return real(fn, *a, **kw)
        except server.HTTPException:
            raise
    proxy.__wrapped__ = real  # type: ignore[attr-defined]
    return proxy


async def case_money_rejects_other_types():
    _reset()
    for bad in ("", "all", "tip,message"):
        try:
            await _money(bad)
        except server.HTTPException as e:
            assert e.status_code == 422
        else:
            raise AssertionError(f"types={bad!r} was read")
    assert _fake.calls == []


_harness.run()
