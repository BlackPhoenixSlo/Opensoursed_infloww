from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import time  # noqa: E402

import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402
import of_ws  # noqa: E402
from of_ws_decide import DEAD_RETRIES  # noqa: E402
from of_client import OFAPIError  # noqa: E402

_harness.make_client()
import server  # noqa: E402

DEAD, LIVE = "acc_ws_dead", "acc_ws_live"
account_registry.get_account = lambda aid: {"id": aid, "nickname": aid}
account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in (DEAD, LIVE)]
account_registry.get_platform = lambda aid: "onlyfans"

OTP_BODY = ('{"error":{"code":101,"message":"Confirm it is you","payload":{"otpState":'
            '{"appOtp":true},"strong":false}}}')
OTP_ERR = f"400 for https://onlyfans.com/api2/v2/users/me\n{OTP_BODY}"

STARTED: list[str] = []
_REAL_START = server._start_account_pump
server._start_account_pump = STARTED.append


class _Client:
    proxy_url = None
    user_agent = "ua"

    def __init__(self, account_id: str, err: Exception | None):
        self.account_id, self.err, self.me_calls = account_id, err, 0

    def me(self) -> dict:
        self.me_calls += 1
        if self.err is not None:
            raise self.err
        return {"wsUrl": "ws://127.0.0.1:9/ws3/1", "wsAuthToken": "t"}


async def case_events_gives_up_on_a_dead_session() -> None:
    c = _Client(DEAD, OFAPIError(OTP_ERR))
    ws = of_ws.OFWebSocket(lambda: c, session_dead=account_health.is_session_dead_error)
    t0 = time.monotonic()
    try:
        async for _ in ws.events():
            raise AssertionError("no event can arrive")
        raise AssertionError("events() ended without raising")
    except of_ws.SessionDead as e:
        assert e.reason == "otp_required", e.reason
    assert DEAD_RETRIES == 3
    assert c.me_calls == 4, f"/users/me called {c.me_calls}x, want 4 (1 + 3 retries)"
    took = time.monotonic() - t0
    assert 6.9 <= took < 7.9, f"{took:.1f} s: want the 1 + 2 + 4 s retries, then no wait"

    other = _Client(LIVE, OFAPIError("500 for https://onlyfans.com/api2/v2/users/me\n{}"))
    ws = of_ws.OFWebSocket(lambda: other, session_dead=account_health.is_session_dead_error)

    async def _drain():
        async for _ in ws.events():
            pass
    task = asyncio.create_task(_drain())
    await asyncio.sleep(1.4)
    ws.stop()
    await asyncio.wait_for(task, 3)
    assert other.me_calls == 2, other.me_calls


async def case_the_pump_flags_the_account_and_exits() -> None:
    await account_health.clear_session_dead(DEAD)
    clients: list[_Client] = []
    orig = server._load_client
    server._load_client = lambda aid: clients.append(_Client(aid, OFAPIError(OTP_ERR))) or clients[-1]
    try:
        parked = await asyncio.wait_for(server._ws_pump_for_account(DEAD), timeout=10)
    finally:
        server._load_client = orig
    assert parked is True, "a parked exit tells the supervisor's backoff it parked"
    assert [c.me_calls for c in clients] == [1] * 4, [c.me_calls for c in clients]
    stamp = (await account_health.dead_session_map()).get(DEAD)
    assert stamp is not None and stamp.reason == "otp_required", stamp
    assert DEAD not in of_ws._LIVE_PUMPS


async def case_the_supervisor_parks_a_dead_account_until_it_recovers() -> None:
    await account_health.mark_session_dead(DEAD, "otp_required")
    loop = asyncio.get_running_loop()
    exited = loop.create_future()
    exited.set_result(None)
    server._account_pumps[DEAD] = exited
    server._pump_runs[DEAD] = server._PumpRun(0.0, due=0.0)
    STARTED.clear()
    try:
        await server._reconcile_pumps()
        assert DEAD not in STARTED and LIVE in STARTED, f"started: {STARTED}"
        assert server._account_pumps.get(DEAD) is exited, "the parked pump was restarted"

        await account_health.clear_session_dead(DEAD)
        STARTED.clear()
        await server._reconcile_pumps()
        assert DEAD in STARTED, f"the recovered account's pump did not start: {STARTED}"
    finally:
        for aid in (DEAD, LIVE):
            server._account_pumps.pop(aid, None)
            server._pump_runs.pop(aid, None)


async def case_restart_backoff_holds_and_a_stop_resets_it() -> None:
    async def crash(_aid: str) -> bool:
        return False

    async def exited() -> asyncio.Task:
        task = server._account_pumps[LIVE]
        await task
        await asyncio.sleep(0)
        return task

    real_pump, real_list = server._ws_pump_for_account, account_registry.list_accounts
    server._ws_pump_for_account, server._start_account_pump = crash, _REAL_START
    account_registry.list_accounts = lambda: [{"id": LIVE, "has_session": True}]
    try:
        server._do_start_account_pump(LIVE)
        await exited()
        assert server._pump_runs[LIVE].restarts == 0, server._pump_runs[LIVE]

        await server._reconcile_pumps()
        second = await exited()
        assert server._pump_runs[LIVE].restarts == 1, server._pump_runs[LIVE]
        run = server._pump_runs[LIVE]
        assert run.due - time.monotonic() > 14, run

        await server._reconcile_pumps()
        assert server._account_pumps[LIVE] is second, "the held Restart ran"

        server._do_stop_account_pump(LIVE)
        assert LIVE not in server._pump_runs, "the stop kept the backoff record"
        server._do_start_account_pump(LIVE)
        await exited()
        run = server._pump_runs[LIVE]
        assert run.restarts == 0 and run.due <= time.monotonic(), run
    finally:
        server._ws_pump_for_account, account_registry.list_accounts = real_pump, real_list
        server._start_account_pump = STARTED.append
        server._account_pumps.pop(LIVE, None)
        server._pump_runs.pop(LIVE, None)


async def case_a_cancelled_pump_leaves_no_orphaned_read() -> None:
    import gc

    import websockets

    async def serve(conn) -> None:
        await conn.recv()
        await conn.send('{"connected":true,"v":"5.4.0"}')
        await asyncio.sleep(30)

    srv = await websockets.serve(serve, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]

    class _Live(_Client):
        def me(self) -> dict:
            self.me_calls += 1
            return {"wsUrl": f"ws://127.0.0.1:{port}/ws3/1", "wsAuthToken": "t"}

    loop = asyncio.get_running_loop()
    orphans: list[dict] = []
    loop.set_exception_handler(lambda _l, ctx: orphans.append(ctx))
    live = _Live(LIVE, None)
    ws = of_ws.OFWebSocket(lambda: live, session_dead=account_health.is_session_dead_error)
    got: list[dict] = []

    async def consume() -> None:
        async for ev in ws.events():
            got.append(ev)
    task = asyncio.create_task(consume())
    try:
        for _ in range(60):
            if got:
                break
            await asyncio.sleep(0.05)
        assert got, "the pump never connected"
        await asyncio.sleep(0.2)
# a restart cancels the pump; its pending socket read must go too, else asyncio logs "Task exception was never retrieved"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        del task
        for _ in range(5):
            await asyncio.sleep(0.2)
            gc.collect()
        srv.close()
        await srv.wait_closed()
    finally:
        loop.set_exception_handler(None)
    left = [str(c.get("exception") or c.get("message")) for c in orphans]
    assert not left, f"orphaned socket reads: {left}"


_harness.run()
