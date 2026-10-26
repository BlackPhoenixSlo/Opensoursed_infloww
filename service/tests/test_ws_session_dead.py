"""
The OF WebSocket pump on a dead session (service/of_ws.py + server.py's pump
and its supervisor). Before each (re)connect the pump reads /users/me for a
fresh wsUrl + token; when OF answers that with a dead-session signature
(account_health.is_session_dead_error: 101 otpState, "Wrong user.") retrying
every few seconds cannot succeed, so:

  case_events_gives_up_on_a_dead_session:
      OFWebSocket.events() raises SessionDead (with the reason) on the first
      such answer instead of reconnecting; any other error still reconnects.
  case_the_pump_flags_the_account_and_exits:
      _ws_pump_for_account marks the account session-dead (reason
      otp_required, the owner's one notification) and returns after ONE
      /users/me, instead of looping.
  case_the_supervisor_parks_a_dead_account_until_it_recovers:
      a supervisor pass starts no pump for a session-dead account and does not
      restart its exited pump; once the flag clears (a re-login, the probe) the
      next pass starts it again, and the new pump loads a fresh client.

No network: the registry, the OF client and pump starts are stubbed.

Run: ./venv/bin/python service/tests/test_ws_session_dead.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import time  # noqa: E402

import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402
import of_ws  # noqa: E402
from of_client import OFAPIError  # noqa: E402

_harness.make_client()  # neutralises the startup spawns before `server` serves
import server  # noqa: E402

DEAD, LIVE = "acc_ws_dead", "acc_ws_live"
account_registry.get_account = lambda aid: {"id": aid, "nickname": aid}
account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in (DEAD, LIVE)]
account_registry.get_platform = lambda aid: "onlyfans"

OTP_BODY = ('{"error":{"code":101,"message":"Confirm it is you","payload":{"otpState":'
            '{"appOtp":true},"strong":false}}}')
OTP_ERR = f"400 for https://onlyfans.com/api2/v2/users/me\n{OTP_BODY}"

STARTED: list[str] = []
server._start_account_pump = STARTED.append


class _Client:
    """An OFClient whose /users/me answers `err` (or a ws ticket when None)."""
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
    ws = of_ws.OFWebSocket(c, session_dead=account_health.is_session_dead_error)
    t0 = time.monotonic()
    try:
        async for _ in ws.events():
            raise AssertionError("no event can arrive")
        raise AssertionError("events() ended without raising")
    except of_ws.SessionDead as e:
        assert e.reason == "otp_required", e.reason
    assert c.me_calls == 1, f"/users/me called {c.me_calls}x: it kept reconnecting"
    assert time.monotonic() - t0 < 0.9, "it waited a backoff before giving up"

    # Any other failure still reconnects with backoff (1 s, then 2 s).
    other = _Client(LIVE, OFAPIError("500 for https://onlyfans.com/api2/v2/users/me\n{}"))
    ws = of_ws.OFWebSocket(other, session_dead=account_health.is_session_dead_error)

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
        await asyncio.wait_for(server._ws_pump_for_account(DEAD), timeout=3)
    finally:
        server._load_client = orig
    assert [c.me_calls for c in clients] == [1], [c.me_calls for c in clients]
    stamp = (await account_health.dead_session_map()).get(DEAD)
    assert stamp is not None and stamp.reason == "otp_required", stamp
    assert DEAD not in of_ws._LIVE_PUMPS


async def case_the_supervisor_parks_a_dead_account_until_it_recovers() -> None:
    await account_health.mark_session_dead(DEAD, "otp_required")
    loop = asyncio.get_running_loop()
    exited = loop.create_future()
    exited.set_result(None)  # its pump returned after flagging the account
    server._account_pumps[DEAD] = exited
    STARTED.clear()
    try:
        await server._reconcile_pumps()
        assert DEAD not in STARTED and LIVE in STARTED, f"started: {STARTED}"
        assert server._account_pumps.get(DEAD) is exited, "the parked pump was restarted"

        await account_health.clear_session_dead(DEAD)  # a re-login or the probe
        STARTED.clear()
        await server._reconcile_pumps()
        assert DEAD in STARTED, f"the recovered account's pump did not start: {STARTED}"
    finally:
        server._account_pumps.pop(DEAD, None)
        server._account_pumps.pop(LIVE, None)


async def case_a_cancelled_pump_leaves_no_orphaned_read() -> None:
    # A pump is cancelled on every restart (a re-capture, a proxy switch, a parked
    # account's resume). Its pending socket read must go with it: left behind, it
    # ends with ConnectionClosed once the socket closes and asyncio logs it as a
    # "Task exception was never retrieved" traceback.
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
    ws = of_ws.OFWebSocket(_Live(LIVE, None), session_dead=account_health.is_session_dead_error)
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
        await asyncio.sleep(0.2)  # parked in its next socket read
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        del task  # as the supervisor drops a restarted pump's task
        for _ in range(5):  # the socket's close handshake ends the read; then it is collected
            await asyncio.sleep(0.2)
            gc.collect()
        srv.close()
        await srv.wait_closed()
    finally:
        loop.set_exception_handler(None)
    left = [str(c.get("exception") or c.get("message")) for c in orphans]
    assert not left, f"orphaned socket reads: {left}"


_harness.run()
