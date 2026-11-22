#!/usr/bin/env python3
"""Background lane: a request's parallel reads never queue on the lane for a second slot.

Two background `GET /users/notifications/money` for one Creator, both lists cold: each request
holds one of the lane's 2 slots (`_bg_admission`) and gathers tip + purchases. Before the fix one
read borrowed the request's lease and the other queued on the lane for a third slot: both
requests waited forever (relay restart). Real `_bg_admission`, money route, relay_cache,
relay_coalesce, `_proxy` and BgLane/BgLease; only the OF client and account resolution are faked.
A regression fails within TIMEOUT_S (the stuck requests are cancelled, which frees their slots).

Run: venv/bin/python -m pytest service/tests/test_bg_lane_money_deadlock.py -q
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
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
    """OF: each notifications read takes OF_S; records calls and the most reads in flight at once."""

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
    """One background money request: admitted on the loop like `_bg_admission_route`, then the route."""
    req = _bg_request(aid)
    server._request_ctx.set(req)
    async with server._bg_admission(req):
        await gate.wait()                      # both admitted (lane full) before either reads
        if name == "R2":
            await asyncio.sleep(0.01)          # R1 leads both keys, R2 joins its flights
        return await server.of_notifications_money(types="tip,purchases", limit=20, offset=0)


def _run_pair(aid: str, client: _Client):
    async def main():
        gate = asyncio.Event()
        tasks = [asyncio.create_task(_money(aid, n, gate)) for n in ("R1", "R2")]
        await asyncio.sleep(0.05)
        gate.set()
        done, pending = await asyncio.wait(tasks, timeout=TIMEOUT_S)
        for t in pending:
            t.cancel()                         # closes their leases: the blocked read gets a slot and ends
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
    assert server._ACCOUNT_LANE_BACKGROUND == 2   # the cap the deadlock needs; a change here re-checks this test
    client = _Client()
    pending, bodies, held, waiters = _run_pair("acct-money-deadlock", client)
    assert pending == 0, f"{pending} money request(s) hung on the background lane (deadlock)"
    assert all(set(b) == {"tip", "purchases"} for b in bodies), bodies
    assert sorted(client.calls) == ["purchases", "tip"], f"one OF read per list, coalesced: {client.calls}"
    assert client.peak <= server._ACCOUNT_LANE_BACKGROUND, f"lane cap exceeded: {client.peak}"
    assert held == 0 and waiters == 0, f"lane not whole after: held={held} waiters={waiters}"


# ── BgLease.borrow(wait=True), the sharing rule itself ──────────────────────

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
    lease.close()                               # the slot stays with the running borrower
    t.join(TIMEOUT_S)
    assert got == [False] and lane.held == 1, (got, lane.held)
    lease.give_back()
    assert lane.held == 0


def test_waiting_borrow_never_waits_on_itself_or_another_creator():
    _lane, lease = _lease()
    assert lease.borrow("a")
    assert lease.borrow("a", wait=True) is False   # same thread, nested lane: no self-wait
    assert lease.borrow("b", wait=True) is False


# ── A requestless warm leader takes its slot before it leads a flight (W30 #2) ──

def _view_lease_request() -> Request:
    """The request the real warm is started from (`POST /admin/view-lease`, user priority, no account)."""
    return Request({"type": "http", "method": "POST", "path": "/admin/view-lease",
                    "query_string": b"", "headers": []})


def test_warm_waiting_for_a_slot_leads_no_flight_a_slot_holder_could_join():
    """Both slots held by background money requests; the App-open warm then starts its rail reads, queued
    through its gate from the view-lease request (as the route does). Before the fix the warm led the tip
    flight (relay_cache lock + coalesce) and only then waited for a third slot in its worker; R1 joined that
    flight, R2 queued on R1's tip lock: nobody freed a slot (hang). W30 #2 r2: the warm inherited the
    view-lease request's context, so its walk-level admission was skipped."""
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
        await asyncio.sleep(0.05)               # both admitted: lane full
        async def view_lease():
            server._request_ctx.set(_view_lease_request())
            app_open_warm._enqueue(aid, app_open_warm._Job(False, None))   # the warm, feed already read
        await asyncio.create_task(view_lease())
        await asyncio.sleep(0.05)               # warm blocked on the slot
        gate.set()
        done, pending = await asyncio.wait(reqs, timeout=TIMEOUT_S)
        for t in pending:
            t.cancel()                          # frees their slots: the warm then ends too
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
    """W30 #2 r2: the gate's worker (warm and Shared refresher jobs alike) runs in a fresh context, not the
    request that happened to start it: a requestless walk, so `_background_reads` decides its lane."""
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
    """W30 #31: a background request serves a stale `/chats` window; its SWR refresh runs detached with the
    request's lease, which closes when the request returns. Before the fix the refresh took the key's lock, then
    waited for a fresh slot in its flight while H1 + H2 held both slots queued on that lock (hang). The refresh
    now gets its own slot before it takes the lock."""
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
        await a1.wait()                                # H1 holds slot 1
        r0 = asyncio.create_task(read("R0", False))    # slot 2: serves stale, spawns the refresh, leaves
        h2 = asyncio.create_task(read("H2", True, None, go))   # queued on the lane: gets R0's slot
        assert (await r0) == {"list": ["stale"]}
        await asyncio.sleep(0.05)                      # the refresh runs, H2 admitted
        go.set()                                       # H1 + H2 (both slots) now read the key
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


if __name__ == "__main__":   # scripts/run-tests.sh runs service tests as plain scripts
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
