#!/usr/bin/env python3
"""Inbox cache patched in place on a DM, and stale-while-revalidate (backend 1.1).

An inbound DM used to `invalidate("list_chats")`, so the next inbox load (and
the next badge fold) re-read OF: a 3-call page assembly, p50 ~2 s, on ~24% of
loads. Now `_inbox_patcher` rewrites the cached page-0 windows instead. These
cases pin:

  • relay_cache.patch — keeps/rewrites, drops on None or a raising fn, keeps
    the expiry, and bumps the pair generation (a fetch in flight cannot write
    its pre-DM snapshot over the patched entry).
  • relay_cache.get_or_fetch(stale_while_revalidate=) — an expired entry is
    served at once and ONE background fetch refreshes it.
  • _inbox_patcher — fan re-topped, lastMessage/unread/hasUnreadTips set; a
    frame not newer than the row's lastMessage (replay, or already in the
    window) leaves the window untouched; deeper pages / other orders / a fan
    outside the window / a frame without an id are dropped.
  • list_chats reconciles the local `chats` mirror from a fresh OF read only,
    never from a cached (stale or WS-patched) window.
  • the measurement: OF fetches over a burst of DMs + inbox polls, invalidate
    vs patch.

Run:  ./venv/bin/python service/tests/test_inbox_patch.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import time  # noqa: E402

import relay_cache  # noqa: E402
from event_transcoder import _inbox_patcher  # noqa: E402

_WINDOW = (25, 0, "recent", None, None, None)


def _row(fan_id: int, *, unread: int = 0, last_id: int = 1) -> dict:
    return {"withUser": {"id": fan_id}, "unreadMessagesCount": unread,
            "hasUnread": unread > 0,
            "lastMessage": {"id": last_id, "fromUser": {"id": fan_id}, "text": "old",
                            "createdAt": "2026-06-21T19:00:00Z"}}


def _dm(fan_id: int, msg_id: int, *, tip: bool = False) -> dict:
    return {"id": msg_id, "fromUser": {"id": fan_id}, "text": "hey", "isTip": tip,
            "createdAt": "2026-06-21T19:00:01Z"}


async def _seed(aid: str, extras: tuple, value) -> None:
    relay_cache.invalidate("list_chats", aid)

    async def _f():
        return value
    await relay_cache.get_or_fetch("list_chats", aid, extras, ttl_seconds=600.0, fetcher=_f)


def case_patcher_retops_and_counts():
    fn = _inbox_patcher(3, _dm(3, 50, tip=True))
    value = {"list": [_row(1), _row(2), _row(3, unread=1)], "hasMore": True}
    out = fn(_WINDOW, value)
    ids = [r["withUser"]["id"] for r in out["list"]]
    assert ids == [3, 1, 2], ids
    top = out["list"][0]
    assert top["lastMessage"]["id"] == 50 and top["unreadMessagesCount"] == 2, top
    assert top["hasUnread"] is True and top["hasUnreadTips"] is True, top
    assert out["hasMore"] is True
    assert value["list"][2]["unreadMessagesCount"] == 1, "patcher mutated the cached value"
    # The same WS frame again (replay): the window is left exactly as it is.
    assert fn(_WINDOW, out) is out, "a replayed frame must not touch the window"


def case_patcher_ignores_frames_not_newer_than_the_row():
    value = {"list": [_row(1), _row(2, unread=1, last_id=45)], "hasMore": False}
    for mid in (45, 40):
        out = _inbox_patcher(2, _dm(2, mid))(_WINDOW, value)
        assert out is value, f"frame {mid} <= lastMessage 45 must leave the window unchanged"
    newer = _inbox_patcher(2, _dm(2, 46))(_WINDOW, value)
    assert newer["list"][0]["unreadMessagesCount"] == 2, newer["list"][0]
    no_id = {"fromUser": {"id": 2}, "text": "?"}
    assert _inbox_patcher(2, no_id)(_WINDOW, value) is None, "an id-less frame cannot be placed"


def case_patcher_drops_what_it_cannot_place():
    fn = _inbox_patcher(9, _dm(9, 51))
    value = {"list": [_row(1), _row(2)], "hasMore": False}
    for extras in ((25, 0, "recent", "priority", None, None), (25, 0, "recent", None, "l1", None),
                   (25, 0, "recent", None, None, "ann")):
        assert fn(extras, value) is None, f"fan outside a filtered/folder/search window must drop: {extras}"
    value9 = {"list": [_row(9)], "hasMore": False}
    assert fn((25, 25, "recent", None, None, None), value9) is None, "deeper page must drop"
    assert fn((25, 0, "oldest", None, None, None), value9) is None, "other order must drop"
    assert fn(_WINDOW, value9) is not None


def case_patcher_stubs_new_fan_on_top():
    fn = _inbox_patcher(9, _dm(9, 51, tip=True))
    value = {"list": [_row(1), _row(2)], "hasMore": False, "asked_at": 5}
    for extras, has_more in (((3, 0, "recent", None, None, None), False),
                             ((2, 0, "recent", "unread", None, None), True)):
        out = fn(extras, value)
        assert isinstance(out, relay_cache.Expired), out
        rows = out.value["list"]
        assert [r["withUser"]["id"] for r in rows] == [9, 1, 2][:extras[0]], rows
        assert rows[0]["unreadMessagesCount"] == 1 and rows[0]["hasUnreadTips"] is True, rows[0]
        assert out.value["hasMore"] is has_more and out.value["asked_at"] == 5, out.value
    assert len(value["list"]) == 2, "patcher mutated the cached value"
    # The worker's later patch with the same frame: the stub is there, nothing moves.
    stubbed = fn(_WINDOW, value).value
    assert fn(_WINDOW, stubbed) is stubbed


def case_stale_dm_cannot_stub_new_fan():
    tail = _row(1)
    value = {"list": [tail]}
    stale = {**_dm(9, 51), "createdAt": 1_782_068_399_000}
    assert _inbox_patcher(9, stale)(_WINDOW, value) is None
    fresh = {**stale, "createdAt": "2026-06-21T19:00:01Z"}
    assert isinstance(_inbox_patcher(9, fresh)(_WINDOW, value), relay_cache.Expired)


def case_empty_unread_window_only_stubs_messages_after_fetch():
    value = {"list": [], "hasMore": False, "asked_at": 1_782_068_400_000}
    unread = (25, 0, "recent", "unread", None, None)
    for created_at in ("2026-06-21T18:59:59Z", "2026-06-21T19:00:00Z"):
        replay = {**_dm(9, 51), "createdAt": created_at}
        assert _inbox_patcher(9, replay)(unread, value) is value
    assert isinstance(_inbox_patcher(9, _dm(9, 51))(unread, value), relay_cache.Expired)


def case_mixed_fan_id_updates_existing_row():
    value = {"list": [_row(9, unread=4)]}
    out = _inbox_patcher("9", _dm("9", 51))(_WINDOW, value)
    assert len(out["list"]) == 1 and out["list"][0]["unreadMessagesCount"] == 5


async def case_stub_expires_entry_and_swr_rereads():
    aid = "acct-stub-1"
    await _seed(aid, _WINDOW, {"list": [_row(1)], "hasMore": False})
    relay_cache.patch("list_chats", aid, _inbox_patcher(9, _dm(9, 80)))
    key = ("list_chats", aid, _WINDOW)
    value, exp = relay_cache._cache[key]
    assert exp <= time.monotonic() and value["list"][0]["withUser"]["id"] == 9, "stub kept, entry expired"
    reads = []

    async def _f():
        reads.append(1)
        return {"list": [_row(9, unread=1, last_id=80), _row(1)], "hasMore": False}
    got = await relay_cache.get_or_fetch("list_chats", aid, _WINDOW, ttl_seconds=600.0, fetcher=_f,
                                         stale_while_revalidate=600.0)
    assert got["list"][0]["withUser"]["id"] == 9 and got is value, "stale stub served at once"
    await asyncio.sleep(0.02)
    assert reads == [1], "one background OF re-read"
    assert relay_cache._cache[key][1] > time.monotonic(), "refreshed entry fresh again"
    relay_cache.invalidate("list_chats", aid)


async def case_receipt_patch_before_broadcast():
    """handle_event patches the cached window before SSE fan-out, hands the prior row to the
    worker, and the worker neither re-patches nor double counts the Unread total."""
    import server  # noqa: F401 — accounts_admin_api must be imported through it
    import events
    import events_persist
    import event_transcoder
    import unread_total
    aid = "acct-receipt-1"
    win = __import__("accounts_admin_api")._ROSTER_WINDOW_KEY
    await _seed(aid, win, {"list": [_row(1), _row(2)], "hasMore": False})
    seen, enq, dm_in, patches = [], [], [], []
    frame = {"__account_id": aid, "api2_chat_message": _dm(2, 90)}

    async def _bcast(ev):
        seen.append(relay_cache.peek("list_chats", aid, win)["list"][0]["withUser"]["id"])
        return 0
    orig = (events.broadcast, events_persist.enqueue, unread_total.on_dm_in, relay_cache.patch,
            event_transcoder.of_writer.write)
    events.broadcast = _bcast
    events_persist.enqueue = lambda *a: enq.append(a)
    unread_total.on_dm_in = lambda *a: dm_in.append(a)
    try:
        await events.handle_event(frame)
        assert seen == [2], f"broadcast must see the patched window: {seen}"
        prior = enq[0][4]
        assert prior["withUser"]["id"] == 2 and prior["unreadMessagesCount"] == 0, prior
        relay_cache.patch = lambda *a: patches.append(a)

        async def _new_row(*_a, **_k):
            return True
        event_transcoder.of_writer.write = _new_row
        await event_transcoder._transcode_chat_message(aid, frame["api2_chat_message"], prior)
        assert dm_in and dm_in[0][3] is prior, dm_in
        assert patches == [], "the worker must not re-patch (its gen bump would void the SWR refresh)"
    finally:
        (events.broadcast, events_persist.enqueue, unread_total.on_dm_in, relay_cache.patch,
         event_transcoder.of_writer.write) = orig
        relay_cache.invalidate("list_chats", aid)


def case_on_dm_in_uses_prior_row():
    import unread_total
    aid = "acct-prior-1"
    calls = []
    orig = (unread_total.ENABLED, unread_total.peek_window_row, unread_total._moved)
    unread_total.ENABLED = True
    unread_total.peek_window_row = lambda *_a: {"withUser": {"id": 5}, "unreadMessagesCount": 3, "hasUnread": True}
    unread_total._moved = lambda _a: False
    real = unread_total.decide.adjust
    unread_total.decide.adjust = lambda st, ev, now: (calls.append(ev), st)[1]
    try:
        unread_total.on_dm_in(aid, 5, 1, {"withUser": {"id": 5}, "unreadMessagesCount": 0})
        unread_total.on_dm_in(aid, 5, 1)
    finally:
        unread_total.ENABLED, unread_total.peek_window_row, unread_total._moved = orig
        unread_total.decide.adjust = real
    assert [c.prior for c in calls] == [unread_total.decide.READ, unread_total.decide.UNREAD], calls


async def case_patch_keeps_expiry_and_drops():
    aid = "acct-patch-1"
    await _seed(aid, _WINDOW, {"list": [_row(1), _row(2)]})
    await _seed_more(aid)
    before = relay_cache._cache[("list_chats", aid, _WINDOW)][1]
    relay_cache.patch("list_chats", aid, _inbox_patcher(2, _dm(2, 60)))
    value, after = relay_cache._cache[("list_chats", aid, _WINDOW)]
    assert after == before, "patch must keep the entry's expiry"
    assert value["list"][0]["withUser"]["id"] == 2
    assert ("list_chats", aid, (25, 25, "recent", None, None, None)) not in relay_cache._cache

    def _boom(_extras, _value):
        raise RuntimeError("bad patcher")
    relay_cache.patch("list_chats", aid, _boom)
    assert ("list_chats", aid, _WINDOW) not in relay_cache._cache, "a raising fn drops"
    relay_cache.invalidate("list_chats", aid)


async def _seed_more(aid: str) -> None:
    async def _f():
        return {"list": [_row(7)]}
    await relay_cache.get_or_fetch("list_chats", aid, (25, 25, "recent", None, None, None),
                                   ttl_seconds=600.0, fetcher=_f)


async def case_patch_blocks_zombie_write_back():
    aid = "acct-patch-2"
    await _seed(aid, _WINDOW, {"list": [_row(1)]})
    relay_cache._cache.pop(("list_chats", aid, _WINDOW))
    started, release = asyncio.Event(), asyncio.Event()

    async def _slow():
        started.set()
        await release.wait()
        return {"list": [_row(1)], "pre_dm": True}
    task = asyncio.create_task(relay_cache.get_or_fetch(
        "list_chats", aid, _WINDOW, ttl_seconds=600.0, fetcher=_slow))
    await started.wait()
    relay_cache.patch("list_chats", aid, _inbox_patcher(1, _dm(1, 70)))
    release.set()
    await task
    assert ("list_chats", aid, _WINDOW) not in relay_cache._cache, \
        "a fetch that read OF before the DM must not be cached"
    relay_cache.invalidate("list_chats", aid)


async def case_stale_while_revalidate():
    ns, aid = "swr", "acct-swr"
    relay_cache.invalidate(ns, aid)
    calls = []

    async def _f():
        calls.append(1)
        await asyncio.sleep(0.01)
        return f"v{len(calls)}"
    first = await relay_cache.get_or_fetch(ns, aid, ("k",), ttl_seconds=60.0, fetcher=_f)
    assert first == "v1"
    # Age the entry past its TTL.
    key = (ns, aid, ("k",))
    relay_cache._cache[key] = (relay_cache._cache[key][0], time.monotonic() - 1)
    stale = await asyncio.gather(*[
        relay_cache.get_or_fetch(ns, aid, ("k",), ttl_seconds=60.0, fetcher=_f,
                                 stale_while_revalidate=600.0)
        for _ in range(5)])
    assert stale == ["v1"] * 5, f"stale reads must answer from RAM: {stale}"
    await asyncio.sleep(0.05)
    assert len(calls) == 2, f"one background refresh, not one per reader: {calls}"
    fresh = await relay_cache.get_or_fetch(ns, aid, ("k",), ttl_seconds=60.0, fetcher=_f,
                                           stale_while_revalidate=600.0)
    assert fresh == "v2", fresh
    # Without SWR an expired entry is still a plain miss.
    relay_cache._cache[key] = (relay_cache._cache[key][0], time.monotonic() - 1)
    assert await relay_cache.get_or_fetch(ns, aid, ("k",), ttl_seconds=60.0, fetcher=_f) == "v3"
    relay_cache.invalidate(ns, aid)


async def case_list_chats_reconciles_only_fresh_reads():
    import messages
    import server
    aid = "acct-reconcile-fresh"
    reconciled, reads = [], []

    def _assemble(_client, **_kw):
        reads.append(1)
        return {"list": [_row(1), _row(2)], "hasMore": False}

    async def _reconcile(account_id, chats):
        reconciled.append((account_id, len(chats)))
        return 0
    orig = (server._resolve_account_id, server._get_client,
            server._assemble_chats_page, messages.reconcile_chats_from_of)
    server._resolve_account_id = lambda _req: aid
    server._get_client = lambda *_a: None
    server._assemble_chats_page = _assemble
    messages.reconcile_chats_from_of = _reconcile
    relay_cache.invalidate("list_chats", aid)
    kw = dict(limit=25, offset=0, order="recent", filter=None, list_id=None,
              query=None, search=None)
    try:
        await server.list_chats(refresh=False, **kw)        # miss: fresh OF read
        await asyncio.sleep(0)
        assert reads == [1] and reconciled == [(aid, 2)], (reads, reconciled)
        await server.list_chats(refresh=False, **kw)        # hit: no reconcile
        relay_cache.patch("list_chats", aid, _inbox_patcher(2, _dm(2, 99)))
        await server.list_chats(refresh=False, **kw)        # WS-patched hit
        key = ("list_chats", aid, (25, 0, "recent", None, None, None))
        relay_cache._cache[key] = (relay_cache._cache[key][0], time.monotonic() - 1)
        reads_before = len(reads)
        await server.list_chats(refresh=False, **kw)        # stale (SWR) answer
        await asyncio.sleep(0.05)                           # ...its background refresh
        assert len(reads) == reads_before + 1, reads
        assert len(reconciled) == 2, f"only the two fresh reads reconcile: {reconciled}"
        await server.list_chats(refresh=True, **kw)         # ?refresh=1: fresh
        await asyncio.sleep(0)
        assert len(reconciled) == 3, reconciled
    finally:
        (server._resolve_account_id, server._get_client,
         server._assemble_chats_page, messages.reconcile_chats_from_of) = orig
        relay_cache.invalidate("list_chats", aid)


async def case_measure_of_reads_invalidate_vs_patch():
    """20 inbound DMs from fans already in the window, an inbox poll after each:
    invalidating re-read OF 20 times, patching reads it zero times."""
    async def _run(on_dm) -> int:
        aid = f"acct-measure-{on_dm.__name__}"
        relay_cache.invalidate("list_chats", aid)
        reads = []

        async def _fetch():
            reads.append(1)
            return {"list": [_row(f) for f in range(1, 26)], "hasMore": True}
        await relay_cache.get_or_fetch("list_chats", aid, _WINDOW, ttl_seconds=600.0, fetcher=_fetch)
        reads.clear()
        for i in range(20):
            on_dm(aid, 1 + i % 25, 1000 + i)
            await relay_cache.get_or_fetch("list_chats", aid, _WINDOW, ttl_seconds=600.0, fetcher=_fetch)
        relay_cache.invalidate("list_chats", aid)
        return len(reads)

    def invalidate(aid, _fan, _mid):
        relay_cache.invalidate("list_chats", aid)

    def patch(aid, fan, mid):
        relay_cache.patch("list_chats", aid, _inbox_patcher(fan, _dm(fan, mid)))

    before, after = await _run(invalidate), await _run(patch)
    print(f"  [measure] OF page reads over 20 DMs + 20 inbox polls: "
          f"invalidate={before} patch={after}")
    assert before == 20 and after == 0, (before, after)


_harness.run()
