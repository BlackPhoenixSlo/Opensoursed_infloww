#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from starlette.requests import Request  # noqa: E402

import relay_cache  # noqa: E402
import relay_coalesce  # noqa: E402
import server  # noqa: E402
from bg_lane import BgLane, BgLease  # noqa: E402

TIMEOUT_S = 5.0
OF_S = 0.1


class _Client:

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.now = self.peak = 0
        self._lock = threading.Lock()

    def notifications(self, limit=10, offset=0, type=None, **_k):
        with self._lock:
            self.calls.append(type)
            self.now += 1
            self.peak = max(self.peak, self.now)
        time.sleep(OF_S)
        with self._lock:
            self.now -= 1
        return {"list": [{"type": type}], "hasMore": False}


def _bg_request(aid: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/of/v2/users/notifications/money",
                    "query_string": b"", "headers": [(b"x-priority", b"background"),
                                                      (b"x-account-id", aid.encode())]})


async def _money(aid: str, name: str, gate: asyncio.Event):
    req = _bg_request(aid)
    server._request_ctx.set(req)
    async with server._bg_admission(req):
        await gate.wait()
        if name == "R2":
            await asyncio.sleep(0.01)
        return await server.of_notifications_money(types="tip,purchases", limit=20, offset=0)


def _run_pair(aid: str, client: _Client):
    async def main():
        gate = asyncio.Event()
        tasks = [asyncio.create_task(_money(aid, n, gate)) for n in ("R1", "R2")]
        await asyncio.sleep(0.05)
        gate.set()
        done, pending = await asyncio.wait(tasks, timeout=TIMEOUT_S)
        for t in pending:
            t.cancel()
        await asyncio.wait(tasks, timeout=TIMEOUT_S)
        bg = server._lanes_for(aid)[1]
        return len(pending), [t.result() for t in done], bg.held, len(bg._waiters)

    orig = (server._get_client, server._resolve_account_id)
    server._get_client = lambda *_a, **_k: client
    server._resolve_account_id = lambda *_a, **_k: aid
    relay_cache._cache.clear()
    relay_coalesce.reset_for_tests()
    try:
        return asyncio.run(main())
    finally:
        server._get_client, server._resolve_account_id = orig


def test_two_cold_background_money_requests_do_not_deadlock_the_lane():
    assert server._ACCOUNT_LANE_BACKGROUND == 2
    client = _Client()
    pending, bodies, held, waiters = _run_pair("acct-money-deadlock", client)
    assert pending == 0, f"{pending} money request(s) hung on the background lane (deadlock)"
    assert all(set(b) == {"tip", "purchases"} for b in bodies), bodies
    assert sorted(client.calls) == ["purchases", "tip"], f"one OF read per list, coalesced: {client.calls}"
    assert client.peak <= server._ACCOUNT_LANE_BACKGROUND, f"lane cap exceeded: {client.peak}"
    assert held == 0 and waiters == 0, f"lane not whole after: held={held} waiters={waiters}"



def _lease() -> tuple[BgLane, BgLease]:
    lane = BgLane(1)
    assert lane.acquire(blocking=False)
    return lane, BgLease("a", lane, 0.0)


def test_waiting_borrow_gets_the_lease_when_the_sibling_gives_it_back():
    _lane, lease = _lease()
    assert lease.borrow("a")
    got = []
    t = threading.Thread(target=lambda: got.append(lease.borrow("a", wait=True)), daemon=True)
    t.start()
    t.join(0.1)
    assert t.is_alive() and not got, "a sibling must wait for the lease, not take a second slot"
    lease.give_back()
    t.join(TIMEOUT_S)
    assert got == [True], got


def test_waiting_borrow_gives_up_when_the_request_left():
    lane, lease = _lease()
    assert lease.borrow("a")
    got = []
    t = threading.Thread(target=lambda: got.append(lease.borrow("a", wait=True)), daemon=True)
    t.start()
    t.join(0.1)
    lease.close()
    t.join(TIMEOUT_S)
    assert got == [False] and lane.held == 1, (got, lane.held)
    lease.give_back()
    assert lane.held == 0


def test_waiting_borrow_never_waits_on_itself_or_another_creator():
    _lane, lease = _lease()
    assert lease.borrow("a")
    assert lease.borrow("a", wait=True) is False
    assert lease.borrow("b", wait=True) is False



def _view_lease_request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/admin/view-lease",
                    "query_string": b"", "headers": []})


def test_warm_waiting_for_a_slot_leads_no_flight_a_slot_holder_could_join():
    import accounts_admin_api
    import app_open_warm
    import shared_refresher

    aid = "acct-warm-deadlock"
    client = _Client()
    client.notifications_count = lambda: {"all": 0}

    async def no_roster(_aid):
        return {}

    async def main():
        gate = asyncio.Event()
        reqs = [asyncio.create_task(_money(aid, n, gate)) for n in ("R1", "R2")]
        await asyncio.sleep(0.05)
        async def view_lease():
            server._request_ctx.set(_view_lease_request())
            app_open_warm._enqueue(aid, app_open_warm._Job(False, None))
        await asyncio.create_task(view_lease())
        await asyncio.sleep(0.05)
        gate.set()
        done, pending = await asyncio.wait(reqs, timeout=TIMEOUT_S)
        for t in pending:
            t.cancel()
        await asyncio.wait(reqs, timeout=TIMEOUT_S)
        end = time.monotonic() + TIMEOUT_S
        while aid not in app_open_warm._warmed_at and aid not in app_open_warm._failed_at \
                and time.monotonic() < end:
            await asyncio.sleep(0.01)
        bg = server._lanes_for(aid)[1]
        return len(pending), aid in app_open_warm._warmed_at, bg.held, len(bg._waiters)

    orig = (server._get_client, server._load_client, server._resolve_account_id,
            accounts_admin_api.rewarm_roster_count, shared_refresher.ENABLED)
    server._get_client = lambda *_a, **_k: client
    server._load_client = lambda *_a, **_k: client
    server._resolve_account_id = lambda *_a, **_k: aid
    accounts_admin_api.rewarm_roster_count = no_roster
    shared_refresher.ENABLED = False
    relay_cache._cache.clear()
    relay_coalesce.reset_for_tests()
    try:
        pending, warm_ok, held, waiters = asyncio.run(main())
    finally:
        (server._get_client, server._load_client, server._resolve_account_id,
         accounts_admin_api.rewarm_roster_count, shared_refresher.ENABLED) = orig
    assert pending == 0, f"{pending} money request(s) hung behind the warm's flight (lane deadlock)"
    assert warm_ok, "warm did not finish once the slots were free"
    assert held == 0 and waiters == 0, f"lane not whole after: held={held} waiters={waiters}"


def test_gate_jobs_run_without_the_callers_request():
    import app_open_warm

    seen = []

    async def run(_aid):
        seen.append(server._request_ctx.get())

    async def wanted(_aid):
        return True

    async def main():
        server._request_ctx.set(_view_lease_request())
        app_open_warm.refresh("acct-gate-ctx", run, wanted=wanted)
        end = time.monotonic() + TIMEOUT_S
        while not seen and time.monotonic() < end:
            await asyncio.sleep(0.01)
    asyncio.run(main())
    assert seen == [None], f"the gate's job saw the caller's request: {seen}"


def test_detached_swr_refresh_waits_for_its_slot_before_the_key_lock():
    aid = "acct-swr-deadlock"
    extras = (20, 0, "recent")
    reads = []

    def of_read():
        time.sleep(OF_S)
        reads.append(1)
        return {"list": [len(reads)]}

    async def fetcher():
        return await relay_coalesce.coalesce(("list_chats", aid) + extras, lambda: asyncio.to_thread(of_read))

    async def read(name: str, bypass: bool, admitted: asyncio.Event | None = None, go: asyncio.Event | None = None):
        req = _bg_request(aid)
        server._request_ctx.set(req)
        async with server._bg_admission(req):
            if admitted is not None:
                admitted.set()
            if go is not None:
                await go.wait()
            return await relay_cache.get_or_fetch("list_chats", aid, extras, ttl_seconds=0.01, fetcher=fetcher,
                                                  bypass=bypass, stale_while_revalidate=600.0)

    async def main():
        relay_cache._cache[("list_chats", aid, extras)] = ({"list": ["stale"]}, time.monotonic() - 1)
        go, a1 = asyncio.Event(), asyncio.Event()
        h1 = asyncio.create_task(read("H1", True, a1, go))
        await a1.wait()
        r0 = asyncio.create_task(read("R0", False))
        h2 = asyncio.create_task(read("H2", True, None, go))
        assert (await r0) == {"list": ["stale"]}
        await asyncio.sleep(0.05)
        go.set()
        done, pending = await asyncio.wait({h1, h2}, timeout=TIMEOUT_S)
        for t in pending:
            t.cancel()
        await asyncio.wait({h1, h2}, timeout=TIMEOUT_S)
        end = time.monotonic() + TIMEOUT_S
        while relay_cache._revalidating and time.monotonic() < end:
            await asyncio.sleep(0.01)
        bg = server._lanes_for(aid)[1]
        return len(pending), bg.held, len(bg._waiters)

    orig = server._resolve_account_id
    server._resolve_account_id = lambda *_a, **_k: aid
    relay_cache._cache.clear()
    relay_coalesce.reset_for_tests()
    try:
        pending, held, waiters = asyncio.run(main())
    finally:
        server._resolve_account_id = orig
    assert pending == 0, f"{pending} background read(s) hung behind the detached refresh's key lock"
    assert held == 0 and waiters == 0, f"lane not whole after: held={held} waiters={waiters}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
