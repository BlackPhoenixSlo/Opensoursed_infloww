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


def events_of(obj) -> list[dict]:
    """Every event dict in one SSE `data:` (the event itself, or the members'
    `data` of an `event: batch`): the dicts that carry `__account_id` or a chat message."""
    out: list[dict] = []
    if isinstance(obj, dict):
        if "__account_id" in obj or "api2_chat_message" in obj:
            out.append(obj)
        else:
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    out += events_of(v)
    elif isinstance(obj, list):
        for v in obj:
            out += events_of(v)
    return out


class SseListener:
    """Collects every api2_chat_message frame the session's /events stream delivers,
    in arrival order, with its arrival time (epoch ms) and every event name's count
    (`resync` = the relay's per-subscriber queue overflowed). `accounts` counts the
    `__account_id` of every event the stream carried (any type); `meta[id]` is a chat
    message's (account id, fan id) as its event named them.

    `resume=True` is the browser's EventSource: when the relay ends the stream (it does after
    an `assignment_changed` or `sessions_revoked`, events.py sse_stream) it reconnects after
    `retry_s` (Chromium's default 3 s) with `Last-Event-ID` = the last `id:` it saw, and the
    relay replays what it missed; `reconnects` counts them. Off, a closed stream is `ended`.

    `states=("agency_notifications", ...)`: every event of those types (alone or in a
    batch) is kept in `state_events` as (type, its fields, its `__account_id`), in order."""

    def __init__(self, http, scope: str = "all", *, resume: bool = False, retry_s: float = 3.0,
                 states: tuple[str, ...] = ()):
        self.http, self.scope, self.resume, self.retry_s = http, scope, resume, retry_s
        self.states = tuple(states)
        self.state_events: list[tuple[str, dict, str | None]] = []
        self.last_id: str | None = None
        self.reconnects = 0
        self.message_ids: list[int] = []
        self.received_at: dict[int, float] = {}
        self.events: Counter = Counter()
        self.accounts: Counter = Counter()
        self.meta: dict[int, tuple[str, int | None]] = {}
        self.frames = 0
        self.status: int | None = None
        self.connected_ms: float | None = None  # epoch ms of the stream's first body line
        self.ended: str | None = None  # why the stream stopped before stop(), if it did
        self.connected = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        try:
            while True:
                await self._stream()
                if not (self.resume and self.status == 200 and self.last_id):
                    break
                await asyncio.sleep(self.retry_s)
                self.reconnects += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a stream that died is a finding (`ended`), not a crash
            self.ended = f"{type(e).__name__}: {e}"[:200]
        else:
            self.ended = self.ended or "stream closed by the relay"
        finally:
            self.connected.set()  # never leave start() waiting on a stream that is gone

    async def _stream(self) -> None:
        hdr = {"Last-Event-ID": self.last_id} if self.reconnects and self.last_id else {}
        async with self.http.c.stream("GET", f"/events?scope={self.scope}", headers=hdr, timeout=None) as r:
            self.http.rec.add("GET /events (status)", r.status_code, 0.0)
            self.status = r.status_code
            if r.status_code != 200:
                self.connected.set()
            event = None
            async for line in r.aiter_lines():
                if not self.connected.is_set():
                    # the relay registers the subscriber before it yields `: connected` (events.py
                    # sse_stream); the headers alone come before that, so they prove nothing
                    self.connected_ms = time.time() * 1000
                    self.connected.set()
                if not line:
                    event = None  # a blank line ends the SSE event
                elif line.startswith("id:"):
                    self.last_id = line[3:].strip() or self.last_id
                elif line.startswith("event:"):
                    event = line[6:].strip()
                    self.events[event] += 1
                elif line.startswith("data:") and event not in (None, "ping"):
                    now = time.time() * 1000
                    try:
                        obj = json.loads(line[5:])
                    except ValueError:
                        continue
                    msgs = chat_messages(obj)
                    if self.states:
                        self._keep_states(obj)
                    for ev in events_of(obj):
                        acct = ev.get("__account_id")
                        if acct is None:
                            continue
                        self.accounts[str(acct)] += 1
                        m = ev.get("api2_chat_message")
                        if isinstance(m, dict):
                            try:
                                fan = (m.get("fromUser") or {}).get("id")
                                self.meta.setdefault(int(m["id"]), (str(acct), int(fan) if fan is not None else None))
                            except (KeyError, ValueError, TypeError):
                                pass
                    for m in msgs:
                        self.frames += 1
                        try:
                            mid = int(m["id"])
                        except (KeyError, ValueError, TypeError):
                            continue
                        self.message_ids.append(mid)
                        self.received_at.setdefault(mid, now)

    def _keep_states(self, obj) -> None:
        if isinstance(obj, dict):
            hit = next((t for t in self.states if isinstance(obj.get(t), dict)), None)
            if hit is not None:
                acct = obj.get("__account_id")
                self.state_events.append((hit, obj[hit], str(acct) if acct is not None else None))
                return
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    self._keep_states(v)
        elif isinstance(obj, list):
            for v in obj:
                self._keep_states(v)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self.connected.wait(), 15)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


class OwnerTab:
    """The Agency owner's dashboard tab in its default All scope (no account filter):
    the tab-open reads (UserContext /auth/me, useAccounts /admin/accounts, appliedSettings,
    useRosterCounts, ErrorBadge), ONE `/events?scope=all` stream, the All-scope inbox head
    (`/admin/chats/recent?limit=25`, useRecentChatsLocal.ts) and the 60 s polls
    (roster-counts; /admin/accounts has a 60 s staleTime). The real tab reads the inbox head
    at open and on every scope switch (5 min stale cache, no interval); this one re-reads it
    every `inbox_s` (the owner flicking back to All), so each stage has samples.
    `inbox`: (end epoch s, ms, status) per head read; `rows_seen`: every row's account."""

    TAB_OPEN = ("/auth/me", "/admin/accounts", "/admin/settings/applied", "/admin/accounts/roster-counts",
                "/admin/errors?since_hours=24&limit=50")
    POLL_60S = ("/admin/accounts/roster-counts", "/admin/accounts")

    def __init__(self, http, rng, *, inbox_s: float = 10.0, poll_s: float = 60.0, head: int = 25):
        self.http, self.rng, self.inbox_s, self.poll_s, self.head = http, rng, inbox_s, poll_s, head
        self.lis = SseListener(http, resume=True)
        self.inbox: list[tuple[float, float, int]] = []
        self.rows_seen: set[str] = set()
        self.errors: list[str] = []
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def _get(self, path: str):
        try:
            return await self.http.get(path)
        except Exception as e:  # noqa: BLE001 — recorded by the client (599)
            self.errors.append(f"GET {path}: {type(e).__name__}")
            return None

    async def _wait(self, s: float) -> bool:
        try:
            await asyncio.wait_for(self._stop.wait(), max(0.0, s))
            return True
        except asyncio.TimeoutError:
            return False

    async def _head(self) -> None:
        t0 = time.perf_counter()
        r = await self._get(f"/admin/chats/recent?limit={self.head}")
        self.inbox.append((time.time(), (time.perf_counter() - t0) * 1000, r.status_code if r is not None else 599))
        if r is not None and r.status_code == 200:
            for x in r.json().get("list") or []:
                self.rows_seen.add(str(x.get("__accountId") or ""))

    async def _inbox(self) -> None:
        while not await self._wait(self.inbox_s):
            await self._head()

    async def _polls(self) -> None:
        if await self._wait(self.rng.uniform(0, self.poll_s)):
            return
        while True:
            await asyncio.gather(*(self._get(p) for p in self.POLL_60S))
            if await self._wait(self.poll_s):
                return

    async def start(self) -> None:
        """Open the tab: the stream first (as lib/events.ts on mount), then the reads."""
        await self.lis.start()
        await asyncio.gather(*(self._get(p) for p in self.TAB_OPEN), self._head())
        self._tasks = [asyncio.create_task(self._inbox()), asyncio.create_task(self._polls())]

    async def stop(self) -> None:
        """End the reads; the stream keeps listening until close()."""
        self._stop.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def close(self) -> None:
        await self.stop()
        await self.lis.stop()


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
