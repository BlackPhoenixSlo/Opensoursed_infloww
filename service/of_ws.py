from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator, Callable

import websockets

import of_ws_decide
from of_client import OFClient

log = logging.getLogger("of-ws")

PING_INTERVAL_S = 25


class SessionDead(Exception):

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class OFWebSocket:

    def __init__(self, client_source: Callable[[], OFClient],
                 session_dead: Callable[[BaseException], str | None] | None = None,
                 *, account_id: str | None = None,
                 on_reconnect: Callable[[], None] | None = None):
        self._client_source = client_source
        self.account_id = account_id
        self._session_dead = session_dead
        self._on_reconnect = on_reconnect
        self._ws_url: str | None = None
        self._token: str | None = None
        self._stop = asyncio.Event()
        self._live_ws = None
        self.connected_at: float | None = None

    async def send_typing(self, fan_id: int) -> bool:
        # OF auto-clears the indicator after a few seconds; callers re-emit every ~2-3 s.
        ws = self._live_ws
        if ws is None:
            return False
        try:
            await ws.send(json.dumps({"act": "typing", "typing_to": int(fan_id)}))
            return True
        except Exception:
            log.debug("send_typing failed (fan=%s)", fan_id, exc_info=True)
            return False

    @classmethod
    def from_latest_session(cls) -> "OFWebSocket":
        return cls(OFClient.from_latest_session)

    def _refresh_auth(self, client: OFClient) -> None:
        me = client.me()
        self._ws_url = me["wsUrl"]
        self._token = me["wsAuthToken"]

    async def events(self) -> AsyncIterator[dict]:
        # Tunnel through the account's proxy like REST: else OF sees one user-id from two IPs at once (shared-session anomaly).
        state = of_ws_decide.Pump()
        opened = False
        while not self._stop.is_set():
            connected_at: float | None = None
            client: OFClient | None = None
            try:
                # Blocking GET /users/me: off the event loop so a reconnect does not freeze every pump and HTTP handler.
                client = await asyncio.to_thread(self._client_source)
                # Blocking GET /users/me off the loop: a reconnect froze every account's pump (observed loop stall).
                await asyncio.to_thread(self._refresh_auth, client)
                assert self._ws_url and self._token
                proxy_url = getattr(client, "proxy_url", None) or None
                if proxy_url:
                    log.info("connecting account=%s %s via proxy %s",
                             self._account_id(client), self._ws_url, self._proxy_desc(client))
                else:
                    log.info("connecting account=%s %s (direct — no proxy assigned)",
                             self._account_id(client), self._ws_url)
                async with websockets.connect(
                    self._ws_url,
                    origin="https://onlyfans.com",
                    user_agent_header=client.user_agent,
                    additional_headers={
                        "Accept-Language": "sl-SI,sl;q=0.9",
                    },
                    max_size=8 * 1024 * 1024,
                    open_timeout=15,
                    close_timeout=5,
                    # websockets 16 defaults proxy=True and reads HTTPS_PROXY env; pass the account's proxy or None explicitly.
                    proxy=proxy_url,
                ) as ws:
                    await ws.send(json.dumps({"act": "connect", "token": self._token}))
                    connected_at = time.monotonic()
                    log.info("connected account=%s proxy=%s", self._account_id(client), self._proxy_desc(client))
                    if opened and self._on_reconnect is not None:
                        try:
                            self._on_reconnect()
                        except Exception:  # noqa: BLE001 — a hook never costs the socket
                            log.warning("on_reconnect failed account=%s", self._account_id(client), exc_info=True)
                    opened = True
                    self._live_ws = ws
                    self.connected_at = time.monotonic()
                    pinger = asyncio.create_task(_pinger(ws, self._stop))
                    stop_waiter = asyncio.create_task(self._stop.wait())
                    recv_task = None
                    try:
                        while not self._stop.is_set():
                            recv_task = asyncio.create_task(ws.recv())
                            done, pending = await asyncio.wait(
                                {recv_task, stop_waiter},
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if stop_waiter in done:
                                recv_task.cancel()
                                break
                            raw = recv_task.result()
                            if isinstance(raw, bytes):
                                try:
                                    raw = raw.decode("utf-8")
                                except Exception:
                                    continue
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                log.warning("non-JSON frame: %r", raw[:200])
                                continue
                            yield msg
                    finally:
                        self._live_ws = None
                        self.connected_at = None
                        pinger.cancel()
                        if not stop_waiter.done():
                            stop_waiter.cancel()
                        if recv_task is not None and not recv_task.done():
                            recv_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                ev = of_ws_decide.Failed(
                    self._session_dead(e) if self._session_dead else None,
                    up_s=time.monotonic() - connected_at if connected_at is not None else None)
                state, eff = of_ws_decide.decide(state, ev)
                if isinstance(eff, of_ws_decide.GiveUp):
                    log.warning("ws session dead account=%s reason=%s — not reconnecting",
                                self._account_id(client), eff.reason)
                    raise SessionDead(eff.reason) from e
                if eff.retry:
                    log.warning("ws session dead account=%s reason=%s — retry %d/%d in %ds",
                                self._account_id(client), ev.dead_reason, eff.retry, of_ws_decide.DEAD_RETRIES, eff.s)
                else:
                    log.warning("ws error account=%s proxy=%s type=%s up=%s err=%s — reconnecting in %ds",
                                self._account_id(client), self._proxy_desc(client), type(e).__name__,
                                f"{time.monotonic() - connected_at:.0f}s" if connected_at else "-",
                                self._scrub(str(e), client)[:200], eff.s)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=eff.s)
                    return
                except asyncio.TimeoutError:
                    pass

    def _account_id(self, client: OFClient | None) -> str:
        return str(self.account_id or getattr(client, "account_id", None) or "?")

    @staticmethod
    def _proxy_desc(client: OFClient | None) -> str:
        if not getattr(client, "proxy_url", None):
            return "direct"
        return f"{getattr(client, 'proxy_label', None) or '—'}({client._proxy_ip()})"

    @classmethod
    def _scrub(cls, text: str, client: OFClient | None) -> str:
        url = getattr(client, "proxy_url", None)
        return text.replace(url, cls._proxy_desc(client)) if url else text

    def stop(self) -> None:
        self._stop.set()


# Lets the automation layer reach the open socket (typing indicator) without a second WS.
_LIVE_PUMPS: dict[str, "OFWebSocket"] = {}


def register_pump(account_id: str, ws: "OFWebSocket") -> None:
    _LIVE_PUMPS[str(account_id)] = ws


def unregister_pump(account_id: str, ws: "OFWebSocket | None" = None) -> None:
    cur = _LIVE_PUMPS.get(str(account_id))
    if ws is None or cur is ws:
        _LIVE_PUMPS.pop(str(account_id), None)


def connected_since(account_id: str) -> float | None:
    return getattr(_LIVE_PUMPS.get(str(account_id)), "connected_at", None)


async def emit_typing(account_id: str, fan_id: int) -> bool:
    ws = _LIVE_PUMPS.get(str(account_id))
    if ws is None:
        return False
    return await ws.send_typing(fan_id)


async def _pinger(ws, stop: asyncio.Event) -> None:
    # OF accepts unknown acts silently; get_onlines keeps the connection alive through NAT timeouts.
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=PING_INTERVAL_S)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await ws.send(json.dumps({"act": "get_onlines"}))
        except Exception:
            return



async def _tail(pretty: bool = True) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ws = OFWebSocket.from_latest_session()
    print("[*] tailing OF events — Ctrl-C to stop")
    n = 0
    try:
        async for event in ws.events():
            n += 1
            key = next(iter(event)) if isinstance(event, dict) and event else "?"
            if pretty and isinstance(event, dict):
                print(f"\n[{n}] {key}")
                preview = json.dumps(event, indent=2)
                if len(preview) > 1500:
                    preview = preview[:1500] + "…"
                print(preview)
            else:
                print(f"[{n}] {event}")
    except KeyboardInterrupt:
        ws.stop()
        print(f"\n[*] stopped after {n} events")


if __name__ == "__main__":
    asyncio.run(_tail())
