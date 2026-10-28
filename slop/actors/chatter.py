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


# ── Employee mode: chatters as their own logins, each one a Messages Pro tab ──
# The relay requests one signed-in chatter tab makes (measured in Chromium,
# .scratch/fleet-sharding/18-chatter-crowd.md §1, with app/ file:line cites).
# OnlyFans-live reads (/api/of/v2/chats, users, vault, notifications ...) are NOT
# sent: a slop run cannot reach OnlyFans (declared bypass); the chat send is, and
# lib/relay.py answers its OnlyFans hop.
TAB_OPEN = ("/auth/me", "/chatter/me", "/chatter/me/accounts", "/admin/settings/applied",
            "/admin/shifts/clock-status", "/admin/shifts/me", "/admin/accounts/roster-counts",
            "/admin/errors?since_hours=24&limit=50")
POLL_60S = ("/admin/shifts/clock-status", "/admin/shifts/me", "/admin/accounts/roster-counts")


def chat_open(aid: str, fan: int) -> tuple[str, ...]:
    """GETs a chat open fires together (ChatSurface, useFanInsights, sensitiveWords ...)."""
    return ("/admin/settings/applied", f"/admin/vault/fan-history?account_id={aid}&fan_id={fan}",
            f"/admin/saved-replies?account_id={aid}", f"/admin/sensitive-words?account_id={aid}",
            f"/admin/fans/{aid}/{fan}", f"/admin/fans/{aid}/{fan}/ppv-history?limit=12",
            f"/admin/fans/{aid}/{fan}/insights", f"/admin/messages/{aid}/{fan}/attribution")


class Member:
    """One chatter: who it is, where it works, what it saw and did."""

    def __init__(self, rec: dict):
        self.username, self.password = rec["username"], rec["password"]
        self.url, self.shard, self.agency = rec["url"], rec["shard"], rec["owner"]
        self.assigned: frozenset[str] = frozenset(rec["account_ids"])
        self.chatter_id = rec.get("chatter_id")
        self.probes: list[dict] = list(rec.get("probes") or [])  # direct reads to be refused (the scenario's plan)
        self.probes_out: list[dict] = []
        self.stage: str | None = None
        self.http = None
        self.lis = None
        self.login: dict = {}
        self.connected_ms: float | None = None
        self.accounts_listed: set[str] | None = None
        self.rows_seen: set[str] = set()
        self.head: list[tuple[str, int]] = []  # the sign-in inbox head's rows of assigned Creators
        self.head_status: int | None = None
        self.replies: list[dict] = []
        self.opens = 0
        self.errors: list[str] = []
        self._read = 0  # index into lis.message_ids already turned into pending work
        self.pending: dict[tuple[str, int], int] = {}


class Crowd:
    """Chatters signing in with their own logins (POST /chatter/login: own cookie),
    each with its own /events stream and the tab's request pattern, human-paced,
    working only the Creators assigned to it. `join()` adds chatters (a ladder
    stage); `stop()` ends the work (streams keep listening); `close()` ends the
    streams."""

    def __init__(self, rec, rng, *, read_s=(5.0, 15.0), next_s=(5.0, 15.0), poll_s=60.0, perflog_s=10.0,
                 head=25, limits=8):
        from slop.lib.client import Http  # lazy: actors stay importable without httpx
        self._Http = Http
        self.rec, self.rng = rec, rng
        self.read_s, self.next_s, self.poll_s, self.perflog_s, self.head, self.limits = (
            read_s, next_s, poll_s, perflog_s, head, limits)
        self.members: list[Member] = []
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def _wait(self, s: float) -> bool:
        """Sleep s seconds; True once the run is stopping."""
        try:
            await asyncio.wait_for(self._stop.wait(), max(0.0, s))
            return True
        except asyncio.TimeoutError:
            return False

    async def _get(self, m: Member, path: str):
        try:
            return await m.http.get(path)
        except Exception as e:  # noqa: BLE001 — recorded by the client (599)
            m.errors.append(f"GET {path}: {type(e).__name__}")
            return None

    def join(self, recs: list[dict], stage: str, ramp_s: float) -> list[Member]:
        new = [Member(r) for r in recs]
        for m in new:
            m.stage = stage
            self.members.append(m)
            self._tasks.append(asyncio.create_task(self._one(m, self.rng.uniform(0, ramp_s))))
        return new

    async def _one(self, m: Member, delay: float) -> None:
        if await self._wait(delay):
            return
        # the client after the wait: each httpx client loads certifi's CA bundle (sync, ~3 ms)
        m.http = self._Http(m.url, self.rec, limits=self.limits)
        t0 = time.time()
        try:
            r = await m.http.post("/chatter/login", json={"username": m.username, "password": m.password})
            m.login = {"status": r.status_code, "t": t0 * 1000}
        except Exception as e:  # noqa: BLE001
            m.login = {"status": 599, "t": t0 * 1000, "error": type(e).__name__}
            return
        if r.status_code != 200:
            return
        from slop.actors.manager import SseListener
        m.lis = SseListener(m.http)
        try:
            await m.lis.start()
        except Exception as e:  # noqa: BLE001
            m.errors.append(f"SSE did not open: {type(e).__name__}")
            return
        if m.lis.status != 200 or m.lis.connected_ms is None:
            m.errors.append(f"SSE did not open: status {m.lis.status}, {m.lis.ended}")
            return
        m.connected_ms = m.lis.connected_ms
        rs = await asyncio.gather(*(self._get(m, p) for p in TAB_OPEN))
        me, accts = rs[1], rs[2]
        m.login["me"] = (me.json() or {}).get("username") if me is not None and me.status_code == 200 else None
        if accts is not None and accts.status_code == 200:
            body = accts.json()
            items = body if isinstance(body, list) else (body.get("accounts") or body.get("list") or [])
            m.accounts_listed = {str(x.get("account_id") or x.get("id") if isinstance(x, dict) else x) for x in items}
        head = await self._get(m, f"/admin/chats/recent?limit={self.head}")
        m.head_status = head.status_code if head is not None else None
        if head is not None and head.status_code == 200:
            for x in head.json().get("list") or []:
                aid = str(x.get("__accountId") or "")
                m.rows_seen.add(aid)
                if aid in m.assigned:
                    m.head.append((aid, int(x["withUser"]["id"])))
        side = [asyncio.create_task(self._polls(m)), asyncio.create_task(self._perflog(m))]
        try:
            await self._work(m)
        finally:
            for t in side:
                t.cancel()
            await asyncio.gather(*side, return_exceptions=True)

    async def _polls(self, m: Member) -> None:
        if await self._wait(self.rng.uniform(0, self.poll_s)):
            return
        while True:
            await asyncio.gather(*(self._get(m, p) for p in POLL_60S))
            if await self._wait(self.poll_s):
                return

    async def _perflog(self, m: Member) -> None:
        tab, n = f"slop-{m.username}", 0
        if await self._wait(self.rng.uniform(0, self.perflog_s)):
            return
        while True:
            n += 1
            try:
                await m.http.post("/admin/perflog/ingest", json={"tabId": tab, "events": [
                    {"opId": f"{tab}-{n}", "kind": "chat.open", "phase": "done", "ts": time.time() * 1000,
                     "tabId": tab, "meta": {"opens": m.opens}}]})
            except Exception as e:  # noqa: BLE001
                m.errors.append(f"perflog: {type(e).__name__}")
            if await self._wait(self.perflog_s):
                return

    def _pick(self, m: Member) -> tuple[str, int] | None:
        """The fan to answer: one of the newest DMs this chatter's own stream brought
        for its Creators, else a row of its inbox head page."""
        ids = m.lis.message_ids
        while m._read < len(ids):
            mid = ids[m._read]
            m._read += 1
            acct, fan = m.lis.meta.get(mid, (None, None))
            if acct in m.assigned and fan is not None and mid < OF_SENT_MIN:
                m.pending[(acct, fan)] = mid
        if m.pending:
            newest = sorted(m.pending, key=m.pending.get)[-10:]
            key = self.rng.choice(newest)
            del m.pending[key]
            return key
        return self.rng.choice(m.head) if m.head else None

    async def _work(self, m: Member) -> None:
        while not self._stop.is_set():
            key = self._pick(m)
            if key is None:
                if await self._wait(self.rng.uniform(1.0, 3.0)):
                    return
                continue
            aid, fan = key
            m.opens += 1
            msgs = m.http.get(f"/admin/messages/{aid}/{fan}?limit=30")
            # the browser trace shows mark-read (and the OF reads) twice: `next dev` runs React's
            # StrictMode, which mounts effects twice; a production build fires them once
            read = m.http.post(f"/admin/messages/{aid}/{fan}/mark-read")
            rs = await asyncio.gather(msgs, read, *(self._get(m, p) for p in chat_open(aid, fan)),
                                      return_exceptions=True)
            top = None
            if not isinstance(rs[0], Exception) and rs[0].status_code == 200:
                ids = [x.get("id") for x in rs[0].json().get("messages") or [] if isinstance(x, dict)]
                top = max((int(i) for i in ids if i is not None), default=None)
            await asyncio.gather(self._get(m, f"/admin/do-not-mass?account_id={aid}&fan_id={fan}&kind=dm"),
                                 self._get(m, f"/admin/messages/{aid}/{fan}/attribution"
                                              + (f"?since_id={top}" if top else "")))
            if await self._wait(self.rng.uniform(*self.read_s)):  # reading the thread, typing (no relay call)
                return
            t0 = time.time()
            try:
                r = await m.http.post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                      json={"text": f"slop crowd reply {m.username} #{len(m.replies) + 1}"})
                body = r.json() if r.status_code < 300 else {}
                m.replies.append({"account_id": aid, "fan_id": fan, "status": r.status_code,
                                  "id": body.get("id") if isinstance(body, dict) else None,
                                  "t0": t0 * 1000, "t1": time.time() * 1000})
            except Exception as e:  # noqa: BLE001 — recorded by the client (599)
                m.replies.append({"account_id": aid, "fan_id": fan, "status": 599, "id": None,
                                  "t0": t0 * 1000, "t1": time.time() * 1000, "error": type(e).__name__})
            if await self._wait(self.rng.uniform(*self.next_s)):
                return

    async def stop(self) -> None:
        """End the work loops and polls; the /events streams keep listening (close())."""
        self._stop.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def close(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for m in self.members:
            if m.lis is not None:
                await m.lis.stop()
            if m.http is not None:
                await m.http.aclose()


OF_SENT_MIN = 9_700_000_000_000  # lib/relay.py OF_SEND_ID_BASE: a chatter's own sent message, not a fan's DM
