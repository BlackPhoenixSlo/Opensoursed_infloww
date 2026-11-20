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
