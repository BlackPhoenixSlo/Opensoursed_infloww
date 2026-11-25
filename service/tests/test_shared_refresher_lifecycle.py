#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import importlib  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import server  # noqa: E402
import accounts  # noqa: E402
import app_open_warm  # noqa: E402
import events  # noqa: E402
import of_call_counter  # noqa: E402
import relay_cache  # noqa: E402
import shared_refresher  # noqa: E402
import transaction_ingest  # noqa: E402
import view_lease  # noqa: E402

A = "9501"
TICK = 0.05
DEADLINE_S = 10.0
TICKS = [0]
ME = {"id": 9501, "chatMessagesCount": 3, "notificationsCount": 2}


class _Client:
    def __init__(self) -> None:
        self.seen: list[dict] = []

    def me(self):
        total, bg = server._lanes_for(A)
        self.seen.append({"caller": of_call_counter.caller_kind(), "priority": server._current_priority(),
                          "bg_held": bg.held})
        return dict(ME)


@contextlib.contextmanager
def _refresher(on: bool):
    clock = [1000.0]
    client = _Client()

    async def _live():
        return [A]

    saved = [(transaction_ingest, "live_account_ids", _live), (accounts, "is_watcher", lambda _a: False),
             (accounts, "get_platform", lambda _a: "onlyfans"), (server, "_load_client", lambda *_a, **_k: client),
             (app_open_warm, "GAP_S", 0.0)]
    old = [(m, k, getattr(m, k)) for m, k, _ in saved]
    env = os.environ.get("SHARED_REFRESHER")
    if on:
        os.environ["SHARED_REFRESHER"] = "1"
    else:
        os.environ.pop("SHARED_REFRESHER", None)
    mod = importlib.reload(shared_refresher)
    mod.TICK_S, mod._clock = TICK, lambda: clock[0]
    real_tick, TICKS[0] = mod.tick, 0

    async def _counted_tick():
        await real_tick()
        TICKS[0] += 1
    mod.tick = _counted_tick
    for m, k, v in saved:
        setattr(m, k, v)
    relay_cache._cache.clear()
    app_open_warm._exits.clear()
    try:
        yield mod, clock, client
    finally:
        for m, k, v in old:
            setattr(m, k, v)
        if env is None:
            os.environ.pop("SHARED_REFRESHER", None)
        else:
            os.environ["SHARED_REFRESHER"] = env
        importlib.reload(shared_refresher)


async def _until(cond) -> None:
    end = time.monotonic() + DEADLINE_S
    while not cond() and time.monotonic() < end:
        await asyncio.sleep(TICK / 5)


async def _ticks(n: int) -> None:
    start = TICKS[0]
    await _until(lambda: TICKS[0] >= start + n)


def _drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(dict(q.get_nowait()))
    return out


async def case_one_read_and_one_event_within_two_ticks():
    with _refresher(True) as (mod, clock, client):
        assert mod.ENABLED
        q = await events.subscribe("all", accounts=frozenset({A}), tab=True)
        q2 = await events.subscribe("all", accounts=frozenset({A}), tab=True)
        await relay_cache.get_or_fetch("users_me", A, ("users_me",), 60.0, lambda: {"stale": True})
        try:
            task = mod.start()
            assert task is not None and mod.start() is task, "one loop"
            await _until(lambda: not q.empty())
            await _ticks(1)
            got = _drain(q)
            assert [list(e) for e in got] == [["creator_refreshed", "__account_id"]], got
            snap = got[0]["creator_refreshed"]
            assert got[0]["__account_id"] == A and snap["account_id"] == A, got
            assert set(snap) == {"account_id", "boot", "seq", "now", "at", "cycle_s", "live", "live_since",
                                 "values"}, snap
            assert (snap["seq"], snap["at"], snap["live"], snap["values"]) == (1, None, "down", {}), \
                ("readable, no Live connection stamp: down", snap)
            assert snap["boot"] <= snap["live_since"] <= snap["now"], snap
            assert 540 <= snap["cycle_s"] <= 600, "the tab cycle, 0.9-1.0 x 600"
            assert client.seen == [], "not due before its first slot (inside FLOOR_S)"
            clock[0] += 61.0
            await _until(lambda: mod._at_ms.get(A) is not None)
            await _ticks(1)
            assert client.seen == [{"caller": "walk:shared_refresher", "priority": "background", "bg_held": 1}], \
                client.seen
            assert relay_cache.peek_fresh("users_me", A, ("users_me",)) == ME, "the route's entry, re-read"
            assert mod._at_ms.get(A) is not None, "the landed read set Last refresh"
            assert _drain(q) == [], "`at` alone is no change: no event"
            assert len(_drain(q2)) == 1, "the second tab got the one event"
        finally:
            await mod.stop()
            await events.unsubscribe("all", q)
            await events.unsubscribe("all", q2)
        assert task.done(), "stop() ends the task"
        assert mod._task is None


async def case_lease_gain_publishes_and_reads_within_lease_cycle():
    holder = ("employee", "e1", "tab-1")
    with _refresher(True) as (mod, clock, client):
        q = await events.subscribe("all", accounts=frozenset({A}), tab=True)
        try:
            mod.start()
            await _until(lambda: not q.empty())
            clock[0] += 61.0
            await _until(lambda: mod._at_ms.get(A) is not None)
            await _ticks(1)
            assert len(client.seen) == 1, client.seen
            asked = clock[0]
            assert len(_drain(q)) == 1, "entered `tracked`: one event"
            view_lease.renew(holder, [A], None)
            await _until(lambda: not q.empty())
            await _ticks(1)
            got = _drain(q)
            assert len(got) == 1, ("a lease gain publishes once", got)
            snap = got[0]["creator_refreshed"]
            assert 108 <= snap["cycle_s"] <= 120 and snap["seq"] == 2, snap
            assert len(client.seen) == 1, "a lease gain is no burst read"
            clock[0] = asked + 107.0
            await _ticks(2)
            assert len(client.seen) == 1, client.seen
            clock[0] = asked + 120.0
            await _until(lambda: len(client.seen) >= 2)
            await _ticks(1)
            assert len(client.seen) == 2, ("next due within its lease cycle", client.seen)
            assert _drain(q) == [], "the read moved `at` only"
        finally:
            view_lease.renew(holder, [], None)
            await mod.stop()
            await events.unsubscribe("all", q)


async def case_last_tab_leaves_no_job_after_next_tick():
    with _refresher(True) as (mod, clock, client):
        enqueued: list[str] = []
        real_refresh = app_open_warm.refresh

        def _counted(aid, run, *, wanted):
            enqueued.append(aid)
            return real_refresh(aid, run, wanted=wanted)

        app_open_warm.refresh = _counted
        q = await events.subscribe("all", accounts=frozenset({A}), tab=True)
        try:
            mod.start()
            await _until(lambda: not q.empty())
            app_open_warm.hold(A, TICK * 8)
            clock[0] += 61.0
            await _until(lambda: bool(enqueued))
            assert enqueued, "due while the tab is open: queued"
            await events.unsubscribe("all", q)
            n = len(enqueued)
            clock[0] += 3600.0
            _, ex = app_open_warm._gate(A)
            await _until(lambda: not ex.jobs and ex.task is None)
            await _ticks(2)
            assert enqueued[n:] == [], ("no job enqueued after the last tab left", enqueued[n:])
            assert client.seen == [], ("the queued job is dropped unread at its turn", client.seen)
            assert mod._in_flight == set() and mod._at_ms.get(A) is None
        finally:
            app_open_warm.refresh = real_refresh
            await mod.stop()
            await events.unsubscribe("all", q)


async def case_knob_off_starts_nothing():
    with _refresher(False) as (mod, clock, client):
        assert not mod.ENABLED
        q = await events.subscribe("all", accounts=frozenset({A}), tab=True)
        try:
            assert mod.start() is None, "the startup hook's call starts nothing"
            clock[0] += 3600.0
            await asyncio.sleep(TICK * 3)
            assert _drain(q) == [] and client.seen == [], "no event, no read"
        finally:
            await mod.stop()
            await events.unsubscribe("all", q)


_harness.run()
