"""The agency manager watching the inbox: an SSE listener on GET /events (the
browser's realtime channel) and inbox reads on the local-DB endpoints the
Fan List and Thread seed from (/admin/chats/recent, /admin/messages/...)."""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter


def chat_messages(obj) -> list[dict]:
    """Every api2_chat_message payload in one SSE `data:` (a frame, or any
    batch/list shape that wraps frames)."""
    out: list[dict] = []
    if isinstance(obj, dict):
        m = obj.get("api2_chat_message")
        if isinstance(m, dict):
            out.append(m)
        for k, v in obj.items():
            if k != "api2_chat_message" and isinstance(v, (dict, list)):
                out += chat_messages(v)
    elif isinstance(obj, list):
        for v in obj:
            out += chat_messages(v)
    return out


class SseListener:
    """Collects every api2_chat_message frame the session's /events stream delivers,
    in arrival order, with its arrival time (epoch ms) and every event name's count
    (`resync` = the relay's per-subscriber queue overflowed)."""

    def __init__(self, http, scope: str = "all"):
        self.http, self.scope = http, scope
        self.message_ids: list[int] = []
        self.received_at: dict[int, float] = {}
        self.events: Counter = Counter()
        self.frames = 0
        self.connected = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        async with self.http.c.stream("GET", f"/events?scope={self.scope}", timeout=None) as r:
            self.http.rec.add("GET /events (status)", r.status_code, 0.0)
            self.connected.set()
            event = None
            async for line in r.aiter_lines():
                if not line:
                    event = None  # a blank line ends the SSE event
                elif line.startswith("event:"):
                    event = line[6:].strip()
                    self.events[event] += 1
                elif line.startswith("data:") and event not in (None, "ping"):
                    now = time.time() * 1000
                    try:
                        msgs = chat_messages(json.loads(line[5:]))
                    except ValueError:
                        continue
                    for m in msgs:
                        self.frames += 1
                        try:
                            mid = int(m["id"])
                        except (KeyError, ValueError, TypeError):
                            continue
                        self.message_ids.append(mid)
                        self.received_at.setdefault(mid, now)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self.connected.wait(), 15)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


async def recent_chats(http, account_id: str, limit: int = 100) -> list[dict]:
    r = await http.get(f"/admin/chats/recent?account_id={account_id}&limit={limit}")
    r.raise_for_status()
    return r.json()["list"]


async def thread_messages(http, account_id: str, fan_id: int, limit: int = 200) -> list[dict]:
    r = await http.get(f"/admin/messages/{account_id}/{fan_id}?limit={limit}")
    r.raise_for_status()
    return r.json()["messages"]


async def quiesce(http, timeout: float = 120) -> dict:
    """Wait until the relay has run transcode() on every frame it received
    (`processed`; `transcoded` counts only the ones that wrote without error)."""
    t0 = asyncio.get_running_loop().time()
    while True:
        s = (await http.get("/__slop/stats")).json()
        if s["processed"] >= s["received"] and not s.get("queue_depth"):
            return s
        if asyncio.get_running_loop().time() - t0 > timeout:
            return {**s, "timed_out": True}
        await asyncio.sleep(0.25)
