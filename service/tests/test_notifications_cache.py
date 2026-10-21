#!/usr/bin/env python3
"""
GET /api/of/v2/users/notifications — TTL cache + in-flight coalescing, and the
invalidation half that keeps a MONEY feed honest.

`of_notifications` was the only member of its family with no cache: `init`,
`labels`, `my_settings` and its own next-door neighbour
`/users/notifications/count` all go through `relay_cache` + `relay_coalesce`,
while this one was a bare `_proxy`. It is also the most fanned-out of them —
`MoneyRail` asks for 2 money types x N accounts on every hard load and the bell
repeats the same keys — so one page load cost N x 2 live OF round-trips at
~630 ms each.

Caching a money feed is only safe with the other half. `NotificationToaster` is
SSE-driven, not polled: it drops its `["notif-list", aid]` query on every money
event it hears (a `toasts` frame, an inbound `api2_chat_message`, a
`purchase_notified`). A server-side TTL with no matching server-side
invalidation would make that client refetch return the SAME stale body — the
toast fires instantly and the list behind it lags a whole TTL. So each of those
three client triggers has a server-side counterpart, via
`relay_cache.invalidate_money_feeds` — which drops the FEED, its badge counts
and `init` together, because OF serves all three off one upstream state.

Covered — the cache half:
  case_hit_is_served_without_a_second_of_call
  case_money_types_do_not_share_an_entry      (type=tip vs type=purchases)
  case_untyped_and_paged_reads_do_not_collide
  case_concurrent_identical_calls_coalesce
  case_refresh_bypasses_the_cache
…and the invalidation half, one case per money lane:
  case_inbound_tip_drops_the_entry            (api2_chat_message)
  case_ppv_unlock_event_drops_the_entry       (paidMessage/messageUnlock/purchase)
  case_purchase_notification_drops_the_entry  (purchase_notified — the LIVE lane)
  case_toast_drops_the_entry                  (toasts)
  case_typing_event_does_not_drop_the_entry   (over-invalidation guard)
  case_a_purchase_busts_the_badge_too (the whole set, not just the feed)
  case_invalidation_is_account_scoped

Run: ./venv/bin/python service/tests/test_notifications_cache.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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

# ── fire-and-forget dispatch hooks: no-op so transcode()'s background tasks
#    can't do DB work or raise while a case is asserting.
async def _noop(*_a, **_k):
    return None


webhook_dispatch.on_inbound_message = _noop  # type: ignore[assignment]
webhook_dispatch.on_inbound_tip = _noop      # type: ignore[assignment]
webhook_dispatch.on_inbound_image = _noop    # type: ignore[assignment]


class _FakeOF:
    """Counts live OF round-trips and echoes the request back, so a cached
    body can be told apart from a fresh one."""

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
    """Serve the next calls as `aid`. Beats reassigning a module global at each
    step: the case reads as "this account, then that one", and the id is
    restored even if an assert fires mid-block."""
    global _current_aid
    prev = _current_aid
    _current_aid = aid
    try:
        yield
    finally:
        _current_aid = prev

# The endpoint resolves the account twice (once for the cache key, once inside
# _proxy) and `_get_client` resolves it again — patch the single choke point.
server._resolve_account_id = lambda _req=None: _current_aid  # type: ignore[assignment]
server._load_client = lambda _aid: _fake                     # type: ignore[assignment]


async def _call(*, limit: int = 20, offset: int = 0, type=None, refresh: bool = False):
    """Invoke the handler directly — no TestClient, so the coalescing case can
    hold five callers in flight at once."""
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
    """Let transcode()'s fire-and-forget tasks settle."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ── the cache half ────────────────────────────────────────────────────

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
    # And each is independently cached afterwards.
    assert await _call(type="tip") == tip
    assert await _call(type="purchases") == purchases
    assert len(_fake.calls) == 2, f"second round refetched: {_fake.calls}"


async def case_untyped_and_paged_reads_do_not_collide():
    _reset()
    await _call(type=None)          # the bell's "all" filter
    await _call(type="tip")
    await _call(type="tip", offset=20)
    await _call(type="tip", limit=10)
    assert len(_fake.calls) == 4, f"key extras collided: {_fake.calls}"


async def case_concurrent_identical_calls_coalesce():
    _reset()
    # threading.Event, not asyncio.Event: the fetcher runs in a worker
    # thread (asyncio.to_thread), where awaiting is not an option.
    slow = threading.Event()
    real = _fake.notifications

    def _slow(**kw):
        # Block in the worker thread until the test releases it, so all five
        # callers are genuinely in flight together.
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
    # The forced fetch must WRITE BACK, so the next plain caller sees it.
    again = await _call(type="tip")
    assert again == forced, f"refresh did not write back: {again} != {forced}"
    assert len(_fake.calls) == 2, f"write-back missing: {_fake.calls}"


# ── the invalidation half ─────────────────────────────────────────────

async def _assert_dropped(fire, label: str) -> None:
    """Warm the entry, fire a money event, assert the next read goes upstream."""
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
    """Over-invalidation guard. EVERY OF WS frame reaches `transcode` — typing
    and online frames are the highest-volume of them by far. Busting on the
    generic fall-through branch would keep this cache permanently cold and
    hand back the 630 ms round-trip we just removed."""
    _reset()
    await _seed_accounts()
    warm = await _call(type="tip")
    await et.transcode({"typing": {"user": {"id": 777005}}, "__account_id": _AID})
    await _drain()
    again = await _call(type="tip")
    assert len(_fake.calls) == 1, f"a typing frame busted the cache: {_fake.calls}"
    assert again == warm


async def case_a_purchase_busts_the_badge_too():
    """The regression that named `invalidate_money_feeds`.

    OF serves the feed and its per-category badge (`notifications_count`) off
    one upstream state, so a sale changes both. Spelling the set out by hand at
    each event path is how the purchase lane — the ONLY one that fires in
    production — ended up busting the feed alone: the badge lagged 30s behind a
    real sale, with the toast already on screen. Pin the whole set, not just
    the feed.
    """
    _reset()
    ttl = 300.0
    # Spelled out, NOT read from relay_cache._MONEY_FEED_NAMESPACES: a test
    # that sources the set from the code under test cannot catch the set
    # itself being wrong, which is the exact bug this case exists for.
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


async def case_invalidation_is_account_scoped():
    """A tip landing on one model must not cost the other model its entry."""
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


_harness.run()
