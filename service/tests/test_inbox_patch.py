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
            "lastMessage": {"id": last_id, "fromUser": {"id": fan_id}, "text": "old"}}


def _dm(fan_id: int, msg_id: int, *, tip: bool = False) -> dict:
    return {"id": msg_id, "fromUser": {"id": fan_id}, "text": "hey", "isTip": tip}


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
    assert fn(_WINDOW, value) is None, "fan outside the window must drop"
    value9 = {"list": [_row(9)], "hasMore": False}
    assert fn((25, 25, "recent", None, None, None), value9) is None, "deeper page must drop"
    assert fn((25, 0, "oldest", None, None, None), value9) is None, "other order must drop"
    assert fn(_WINDOW, value9) is not None


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
