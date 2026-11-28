from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from collections import deque
from typing import Any, AsyncIterator, Callable

import websockets

log = logging.getLogger("fansly-ws")

WS_URL = "wss://wsv3.fansly.com/?v=3"

# measured OUT-`p` gaps are 20-45s (idle timer); 18s unconditional is inside every observed window
PING_INTERVAL_S = 18
RECONNECT_MIN_S = 1
RECONNECT_MAX_S = 30

T_AUTH = 1
T_PONG = 2
T_EVENT = 10000

SVC_MESSAGE = 5

_DEDUPE_MAX = 512

TYPING_SLOT_S = 5.0


class FanslyWebSocket:

    def __init__(self, client: Any, *, clock: Callable[[], float] = time.monotonic):
        self.client = client
        self._clock = clock
        self._typing_lock = threading.Lock()
        self._typing_slots: dict[str, float] = {}
        self._typing_misses: dict[str, float] = {}
        self._stop = asyncio.Event()
        self._live_ws = None
        # duplicate frames arrive adjacent, so a bounded ring suffices; an unbounded set on a weeks-long pump leaks
        self._seen: set[tuple] = set()
        self._seen_order: deque[tuple] = deque()
        self._down_since: float | None = None


    # re-read per connect: the token can rotate, and me() returns an OF-user shape with no token
    def _read_token(self) -> str:
        session = getattr(self.client, "session", None)
        token = getattr(session, "token", None) if session is not None else None
        if not token:
            raise RuntimeError("fansly session has no token — cannot auth the socket")
        return str(token)


    async def send_typing(self, fan_id: int | str) -> bool:
        try:
            return await asyncio.to_thread(self._send_typing, str(fan_id))
        except Exception:
            log.debug("send_typing failed (fan=%s)", fan_id, exc_info=True)
            return False

    def _send_typing(self, fan_id: str) -> bool:
        group_id = self._resolve_group(fan_id)
        if not group_id:
            return False
        with self._typing_lock:
            now = self._clock()
            last = self._typing_slots.get(group_id)
            if last is not None and now - last < TYPING_SLOT_S:
                return True
            self._typing_slots[group_id] = now
        try:
            self.client.typing(group_id)
        except Exception:
            with self._typing_lock:
                if self._typing_slots.get(group_id) == now:
                    del self._typing_slots[group_id]
            raise
        return True

    def _resolve_group(self, fan_id: str) -> str | None:
        lookup = self.client._group_or_none
        cached = lookup(fan_id, scan=False)
        if cached:
            return cached
        with self._typing_lock:
            now = self._clock()
            last = self._typing_misses.get(fan_id)
            self._typing_misses[fan_id] = now
            if last is not None and now - last < TYPING_SLOT_S:
                return None
        found = lookup(fan_id)
        if found:
            with self._typing_lock:
                self._typing_misses.pop(fan_id, None)
        return found


    def _dedupe(self, key: tuple) -> bool:
        if key in self._seen:
            return False
        self._seen.add(key)
        self._seen_order.append(key)
        if len(self._seen_order) > _DEDUPE_MAX:
            self._seen.discard(self._seen_order.popleft())
        return True

    def _translate(self, frame: dict) -> dict | None:
        t = frame.get("t")
        if t != T_EVENT:
            return None

        try:
            envelope = json.loads(frame.get("d") or "{}")
            service_id = envelope.get("serviceId")
            event = json.loads(envelope.get("event") or "{}")
        except (json.JSONDecodeError, TypeError):
            log.debug("undecodable t:10000 envelope")
            return None
        if not isinstance(event, dict):
            return None

        event_type = event.get("type")
        if service_id == SVC_MESSAGE and event_type == 1:
            return self._translate_message(event.get("message"))
        if service_id == SVC_MESSAGE and event_type == 10:
            return self._translate_delete(event.get("message"))

        return None

    def _translate_delete(self, message: Any) -> dict | None:
        if not isinstance(message, dict):
            return None
        message_id = message.get("id")
        if not message_id:
            return None
        sender = str(message.get("senderId") or "")
        if sender and sender != str(self.client.account_id):
            fan_id = sender
        else:
            fan_id = str(self.client._group_to_fan.get(str(message.get("groupId") or "")) or "")
        if not fan_id:
            log.debug("dropping unsend frame %s: no fan", message_id)
            return None
        if not self._dedupe((SVC_MESSAGE, 10, str(message_id))):
            return None
        log.info("ws-pump unsend frame id=%s", message_id)
        return {"chat_message_deleted": {"id": str(message_id), "fan_id": fan_id}}

    def _translate_message(self, message: Any) -> dict | None:
        if not isinstance(message, dict):
            return None
        message_id = message.get("id")
        if not message_id:
            return None
        if not self._dedupe((SVC_MESSAGE, 1, str(message_id))):
            log.debug("dropping duplicate message frame %s", message_id)
            return None
        log.info("ws-pump inbound message frame id=%s", message_id)

        from fansly_shim import of_message
        account_id = str(getattr(self.client, "account_id", "") or "")
        of_msg = of_message(message, account_id=account_id)
        return {"api2_chat_message": of_msg}


    async def events(self) -> AsyncIterator[dict]:
        backoff = RECONNECT_MIN_S
        while not self._stop.is_set():
            try:
                token = await asyncio.to_thread(self._read_token)
                proxy_url = getattr(self.client, "proxy_url", None) or None
                log.info("connecting %s%s", WS_URL,
                         " via proxy" if proxy_url else " (direct — no proxy assigned)")
                # never log token or the t:1 frame body (relay log is not gitignored). ping_interval stays at the library default: it detects a half-open TCP, the in-band `p` is only Fansly's app keepalive
                async with websockets.connect(
                    WS_URL,
                    origin="https://fansly.com",
                    user_agent_header=getattr(self.client, "user_agent", None)
                    or getattr(getattr(self.client, "session", None), "user_agent", None),
                    max_size=8 * 1024 * 1024,
                    open_timeout=15,
                    close_timeout=5,
                    proxy=proxy_url,
                ) as ws:
                    await ws.send(json.dumps(
                        {"t": T_AUTH, "d": json.dumps({"token": token, "v": 3})}
                    ))
                    self._live_ws = ws
                    if self._down_since is not None:
                        log.info("reconnected after %.1fs of realtime downtime",
                                 time.monotonic() - self._down_since)
                        self._down_since = None
                    pinger = asyncio.create_task(_pinger(ws, self._stop))
                    stop_waiter = asyncio.create_task(self._stop.wait())
                    recv_task: asyncio.Task | None = None
                    try:
                        while not self._stop.is_set():
                            recv_task = asyncio.create_task(ws.recv())
                            done, _ = await asyncio.wait(
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
                                frame = json.loads(raw)
                            except json.JSONDecodeError:
                                if raw.strip() not in ("p", "pong", ""):
                                    log.warning("non-JSON frame: %r", raw[:200])
                                continue
                            if not isinstance(frame, dict):
                                continue
                            event = self._translate(frame)
                            if event is not None:
                                yield event
                    finally:
                        self._live_ws = None
                        pinger.cancel()
                        if not stop_waiter.done():
                            stop_waiter.cancel()
                        if recv_task is not None and not recv_task.done():
                            recv_task.cancel()
                backoff = RECONNECT_MIN_S
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._down_since is None:
                    self._down_since = time.monotonic()
                delay = backoff * (0.5 + random.random())
                log.warning("ws error %s — reconnecting in %.1fs", e, delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    return
                except asyncio.TimeoutError:
                    pass
                backoff = min(int(backoff * 2) or 1, RECONNECT_MAX_S)

    def stop(self) -> None:
        self._stop.set()


async def _pinger(ws, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=PING_INTERVAL_S)
            return
        except asyncio.TimeoutError:
            pass
        try:
            # bare literal `p`, not JSON; wsv3 does not understand the OF {"act":...} shape
            await ws.send("p")
        except Exception:
            return
