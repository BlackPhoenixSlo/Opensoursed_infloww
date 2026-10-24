"""Chatters working the inbox, on the endpoints the Messages Pro screens use:
the chat list head page from the local DB (GET /admin/chats/recent, what the Fan
List seeds from), the thread (GET /admin/messages/{account}/{fan}), the local
read marker the inbox fires on every chat open (POST .../mark-read) and a reply
(POST /api/of/v2/chats/{fan}/messages with X-Account-Id, whose OnlyFans hop
lib/relay.py answers). Each chatter loops: pick a Creator (by weight), open the
head page, open an unread thread (else any), mark it read, think, reply, think.

`touched[(account_id, fan_id)]` is the epoch-ms start of the FIRST read/reply a
chatter sent on that thread (from then on its unread count is the chatters'
doing, not only the fans'); `last[...]` the end of the LAST one: every fan DM
injected after it must still be counted unread."""
from __future__ import annotations

import asyncio
import time


class Chatters:
    def __init__(self, sessions: dict[str, object], weights: dict[str, float], rng, *,
                 think_s=(2.0, 6.0), head=25, avoid: set[tuple] = frozenset()):
        """`sessions`: Creator id -> the signed-in Http of the Agency that owns it."""
        self.sessions, self.weights, self.rng = sessions, weights, rng
        self.think_s, self.head, self.avoid = think_s, head, avoid
        self.touched: dict[tuple, float] = {}
        self.last: dict[tuple, float] = {}
        self.actions = {"head": 0, "thread": 0, "read": 0, "reply": 0, "errors": 0}
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def _think(self, lo: float | None = None) -> bool:
        """Sleep a think time; True once the run is stopping."""
        try:
            await asyncio.wait_for(self._stop.wait(), self.rng.uniform(self.think_s[0] if lo is None else lo,
                                                                        self.think_s[1]))
            return True
        except asyncio.TimeoutError:
            return False

    async def _one(self, n: int) -> None:
        aids, w = list(self.weights), list(self.weights.values())
        if await self._think(0):  # stagger the starts
            return
        while not self._stop.is_set():
            aid = self.rng.choices(aids, w)[0]
            http = self.sessions[aid]
            try:
                r = await http.get(f"/admin/chats/recent?account_id={aid}&limit={self.head}")
                self.actions["head"] += 1
                rows = (r.json().get("list") or []) if r.status_code < 300 else []
                rows = [x for x in rows if (aid, x["withUser"]["id"]) not in self.avoid]
                if not rows:
                    if await self._think():
                        return
                    continue
                unread = [x for x in rows if x.get("unreadMessagesCount")]
                fan = self.rng.choice(unread or rows)["withUser"]["id"]
                key = (aid, fan)
                await http.get(f"/admin/messages/{aid}/{fan}?limit=50")
                self.actions["thread"] += 1
                self.touched.setdefault(key, time.time() * 1000)
                await http.post(f"/admin/messages/{aid}/{fan}/mark-read")
                self.last[key] = time.time() * 1000
                self.actions["read"] += 1
                if await self._think():
                    return
                await http.post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                json={"text": f"slop reply from chatter {n}"})
                self.last[key] = time.time() * 1000
                self.actions["reply"] += 1
            except Exception:
                self.actions["errors"] += 1
            if await self._think():
                return

    def start(self, users: int) -> None:
        self._tasks = [asyncio.create_task(self._one(i)) for i in range(users)]

    async def stop(self) -> None:
        self._stop.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)
