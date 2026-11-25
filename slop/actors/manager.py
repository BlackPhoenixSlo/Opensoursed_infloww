from __future__ import annotations

import asyncio
import json
import time
from collections import Counter


def chat_messages(obj) -> list[dict]:
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

    def __init__(self, http, scope: str = "all", *, resume: bool = False, retry_s: float = 3.0,
                 states: tuple[str, ...] = (), last_id: str | None = None, lease: bool = False):
        self.http, self.scope, self.resume, self.retry_s = http, scope, resume, retry_s
        self.lease = lease
        self._resume_from = last_id
        self.states = tuple(states)
        self.state_events: list[tuple[str, dict, str | None]] = []
        self.last_id: str | None = last_id
        self.reconnects = 0
        self.message_ids: list[int] = []
        self.received_at: dict[int, float] = {}
        self.events: Counter = Counter()
        self.accounts: Counter = Counter()
        self.meta: dict[int, tuple[str, int | None]] = {}
        self.frames = 0
        self.status: int | None = None
        self.connected_ms: float | None = None
        self.ended: str | None = None
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
            self.connected.set()

    async def _stream(self) -> None:
        hdr = {"Last-Event-ID": self.last_id} if (self.reconnects or self._resume_from) and self.last_id else {}
        url = f"/events?scope={self.scope}" + ("&lease=1" if self.lease else "")
        async with self.http.c.stream("GET", url, headers=hdr, timeout=None) as r:
            self.http.rec.add("GET /events (status)", r.status_code, 0.0)
            self.status = r.status_code
            if r.status_code != 200:
                self.connected.set()
            event = None
            async for line in r.aiter_lines():
                # the relay registers the subscriber before it yields `: connected`; headers alone prove nothing
                if not self.connected.is_set():
                    self.connected_ms = time.time() * 1000
                    self.connected.set()
                if not line:
                    event = None
                elif line.startswith("id:"):
                    self.last_id = line[3:].strip() or self.last_id
                elif line.startswith("event:"):
                    event = line[6:].strip()
                    self.events[event] += 1
                elif line.startswith("data:") and event == "ping":
                    self._ping(line[5:])
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

    def _ping(self, data: str) -> None:
        pass

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

    TAB_OPEN = ("/auth/me", "/admin/accounts", "/admin/settings/applied", "/admin/accounts/roster-counts",
                "/admin/errors?since_hours=24&limit=50")
    POLL_60S = ("/admin/accounts",)

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
        await self.lis.start()
        await asyncio.gather(*(self._get(p) for p in self.TAB_OPEN), self._head())
        self._tasks = [asyncio.create_task(self._inbox()), asyncio.create_task(self._polls())]

    async def stop(self) -> None:
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
    t0 = asyncio.get_running_loop().time()
    while True:
        s = (await http.get("/__slop/stats")).json()
        if s["processed"] >= s["received"] and not s.get("queue_depth"):
            return s
        if asyncio.get_running_loop().time() - t0 > timeout:
            return {**s, "timed_out": True}
        await asyncio.sleep(0.25)
