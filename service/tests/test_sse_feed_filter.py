#!/usr/bin/env python3
"""WS feed noise filter, SSE type allow-list and inbound typing (backend 1.7, 1.3).

  • Other creators' home-feed frames (post_published / post_expire /
    post_updated / post_fundraising_updated: ~82% of one account's WS traffic)
    are dropped before persist AND fan-out; the account's OWN post_published
    is kept.
  • broadcast() only pushes the types a browser listens for (SSE_TYPES);
    anything else is persisted but not serialized to every tab.
  • An inbound OF `typing` frame becomes ONE `chat_typing {fan_id}` SSE event
    per fan per 3 s, and still goes down the persist/transcode path (which
    touches the Fan row) like every other frame; the raw frame is not pushed.

Run:  ./venv/bin/python service/tests/test_sse_feed_filter.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402

import events  # noqa: E402

AID = "4242"


async def _with_queues(fn):
    """Run `fn(sub, persisted)` with a live persist queue and one SSE subscriber."""
    events._subs_lock = asyncio.Lock()   # bind to this case's loop
    persisted: asyncio.Queue = asyncio.Queue()
    events._persist_queue = persisted
    sub = await events.subscribe(f"model:{AID}")
    try:
        await fn(sub, persisted)
    finally:
        await events.unsubscribe(f"model:{AID}", sub)
        events._persist_queue = None


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def case_is_feed_noise():
    assert events.is_feed_noise({"post_published": {"id": 1, "user_id": 77}}, AID)
    assert events.is_feed_noise({"post_expire": {"id": 1}}, AID)
    assert events.is_feed_noise({"post_updated": {"id": 1}, "__account_id": AID}, AID)
    assert not events.is_feed_noise({"post_published": {"id": 1, "user_id": int(AID)}}, AID), \
        "the account's own post must be kept"
    assert not events.is_feed_noise({"api2_chat_message": {"id": 1}}, AID)


async def case_feed_noise_neither_persisted_nor_pushed():
    async def _go(sub, persisted):
        await events.handle_event({"__account_id": AID, "post_published": {"id": 1, "user_id": 9}})
        await events.handle_event({"__account_id": AID, "post_expire": {"id": 2}})
        assert _drain(persisted) == [] and _drain(sub) == []
        await events.handle_event({"__account_id": AID, "post_published": {"id": 3, "user_id": AID}})
        assert len(_drain(persisted)) == 1, "own post must still persist"
    await _with_queues(_go)


async def case_sse_allow_list():
    async def _go(sub, persisted):
        await events.handle_event({"__account_id": AID, "stories": [{"id": 1}]})
        await events.handle_event({"__account_id": AID, "chat_messages": {"count": 3}})
        assert len(_drain(persisted)) == 2, "non-UI frames are still persisted"
        assert _drain(sub) == [], "non-UI frames must not reach a tab"
        await events.handle_event({"__account_id": AID, "api2_chat_message": {"id": 5}})
        got = _drain(sub)
        assert [events._first_real_key(e) for e in got] == ["api2_chat_message"], got
        n = await events.broadcast({"__account_id": AID, "transaction_recorded": {"fan_id": 1}})
        assert n == 1, n
    await _with_queues(_go)


async def case_mass_queue_frames_reach_only_their_accounts_tabs():
    other = await events.subscribe("model:9999")

    async def _go(sub, persisted):
        update = {"__account_id": AID, "chat_queue_update": {"id": 46605849959, "total": -1, "pending": 23}}
        finish = {"__account_id": AID, "chat_queue_finish": {"id": 46605849959, "total": 23, "pending": 0,
                                                             "isDone": True}}
        await events.handle_event(update)
        await events.handle_event(finish)
        assert len(_drain(persisted)) == 2, "queue frames still persist (and feed the transcoder's ring)"
        got = _drain(sub)
        assert [events._first_real_key(e) for e in got] == ["chat_queue_update", "chat_queue_finish"], got
        assert got[1]["chat_queue_finish"]["total"] == 23 and got[1]["__account_id"] == AID, got
        assert _drain(other) == [], "another Creator's tab must not see the queue"
    try:
        await _with_queues(_go)
    finally:
        await events.unsubscribe("model:9999", other)


async def case_typing_forwarded_and_throttled():
    events._typing_last.clear()

    async def _go(sub, persisted):
        for _ in range(4):
            await events.handle_event({"__account_id": AID, "typing": {"id": 501}})
        await events.handle_event({"__account_id": AID, "typing": {"id": 502}})
        assert len(_drain(persisted)) == 5, "typing still reaches the persist/transcode worker"
        got = _drain(sub)
        assert [e["chat_typing"]["fan_id"] for e in got] == [501, 502], got
        assert all(e["__account_id"] == AID for e in got)
        # The window passes → the next frame for 501 goes out again.
        events._typing_last[(AID, 501)] -= events._TYPING_THROTTLE_S
        await events.handle_event({"__account_id": AID, "typing": {"id": 501}})
        assert len(_drain(sub)) == 1
        # A frame with no fan id is ignored.
        await events.handle_event({"__account_id": AID, "typing": {}})
        assert _drain(sub) == [], "neither chat_typing nor the raw frame is pushed"
    await _with_queues(_go)


_harness.run()
