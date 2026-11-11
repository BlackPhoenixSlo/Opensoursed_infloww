"""
The OF WebSocket pump after client_pool.evict (service/of_ws.py + server.py's
pump). Eviction (a new OF x_of_rev in sign_rules, a session probe, a proxy
edit) retires the old OFClient's signed sessions; every later signed call on it
raises "signed session retired". The pump used to keep the OFClient it was
built with, so each reconnect's GET /users/me failed on the retired handle
forever (AE 2026-11-10: 40 finals/account/20 min until a container restart).

  case_reconnect_after_evict_uses_the_pooled_client:
      a pump connected through the real pool; evict mid-pump and drop the
      socket; the next reconnect reads /users/me on the FRESH pooled client and
      connects again, the retired one is never asked again.

No network beyond a loopback websockets server; OFClient.from_account is stubbed.

Run: ./venv/bin/python service/tests/test_ws_pump_evict.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402

import accounts as account_registry  # noqa: E402
import client_pool  # noqa: E402
from of_client import OFSessionRetired  # noqa: E402

_harness.make_client()  # neutralises the startup spawns before `server` serves
import server  # noqa: E402

AID = "acc_ws_evict"
account_registry.get_account = lambda aid: {"id": aid, "nickname": aid}
account_registry.get_platform = lambda aid: "onlyfans"


async def case_reconnect_after_evict_uses_the_pooled_client() -> None:
    import websockets

    conns: list[int] = []
    drop_first = asyncio.Event()

    async def serve(conn) -> None:
        await conn.recv()  # {"act":"connect",...}
        conns.append(len(conns) + 1)
        n = conns[-1]
        await conn.send(f'{{"conn":{n}}}')
        if n == 1:
            await drop_first.wait()
            await conn.close()
            return
        await conn.wait_closed()

    srv = await websockets.serve(serve, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]

    built: list["_Fake"] = []

    class _Fake:
        """An OFClient as the pool sees it: retirable, /users/me signed."""
        proxy_url = None
        user_agent = "ua"
        user_id = 1
        x_of_rev = "rev"

        def __init__(self) -> None:
            self.account_id, self.retired, self.me_calls = AID, False, 0

        def me(self) -> dict:
            self.me_calls += 1
            if self.retired:
                raise OFSessionRetired("signed session retired; retry with current account session")
            return {"wsUrl": f"ws://127.0.0.1:{port}/ws3/1", "wsAuthToken": "t"}

        def close_signed_sessions(self) -> None:
            self.retired = True

    orig_build = client_pool.OFClient.from_account
    client_pool.OFClient.from_account = staticmethod(lambda aid: built.append(_Fake()) or built[-1])
    client_pool.evict(AID)
    got: list[dict] = []

    async def consume() -> None:
        await server._ws_pump_for_account(AID)

    orig_broadcast = server._broadcast_event

    async def capture(ev) -> None:
        got.append(ev)
    server._broadcast_event = capture
    task = asyncio.create_task(consume())
    try:
        for _ in range(60):
            if got:
                break
            await asyncio.sleep(0.05)
        assert got and got[0].get("conn") == 1, got
        client_pool.evict(AID)  # e.g. sign_rules saw a new x_of_rev
        assert built[0].retired
        drop_first.set()
        for _ in range(100):  # reconnect backoff is 1 s
            if len(got) >= 2:
                break
            await asyncio.sleep(0.05)
        assert len(got) >= 2 and got[1].get("conn") == 2, (
            f"no reconnect after evict: events={got} me_calls={[c.me_calls for c in built]}")
        assert len(built) == 2, len(built)
        assert built[0].me_calls == 1, f"retired client asked again: {built[0].me_calls}"
        assert built[1].me_calls == 1, built[1].me_calls
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server._broadcast_event = orig_broadcast
        client_pool.OFClient.from_account = orig_build
        client_pool.evict(AID)
        srv.close()
        await srv.wait_closed()


_harness.run()
