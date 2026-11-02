"""Chatters on the Clock (service/clock_api.py, under `/admin/shifts`): each with its own login
(POST /chatter/login: its own cookie, as actors/chatter.py's `Crowd` signs in; `Member` is reused for
who it is), human-paced.

  storm(members, k)  every chatter fires `k` concurrent `POST /admin/shifts/clock-in {account_id}` at
                     once (a double-click, two tabs, a retrying client), all chatters together.
  work(m)            the top bar's day: clock-status, then `beats` heartbeats (`POST
                     /admin/shifts/clock-heartbeat`, what the app sends after real input) with think time,
                     clock-out of the open event; then clock-in again, heartbeats, clock-out.

The plan (how many beats, which Creator) comes from the seed, never from an answer, so a fault does not
change the load: the event a clock-out names is the one clock-in or clock-status answered, and a chatter
with none still sends its clock-out (`clock_event_id` 0: a 404).

`writes`: every clock write answered, (kind, member username, status, clock_event_id or None).
"""
from __future__ import annotations

import asyncio

from slop.actors.chatter import Member


class Clock:
    def __init__(self, rec, rng, *, think_s=(0.5, 2.0), beats=(2, 4), limits=8):
        from slop.lib.client import Http  # lazy: actors stay importable without httpx
        self._Http = Http
        self.rec, self.rng, self.think_s, self.beats, self.limits = rec, rng, think_s, beats, limits
        self.writes: list[tuple[str, str, int, int | None]] = []
        self.plans: dict[str, list[int]] = {}

    def member(self, rec: dict, url: str) -> Member:
        m = Member({**rec, "url": url, "shard": 0})
        self.plans[m.username] = [self.rng.randint(*self.beats), self.rng.randint(*self.beats)]
        return m

    async def login(self, m: Member) -> bool:
        """actors/chatter.py `Crowd`'s sign-in: POST /chatter/login on a fresh client, its cookie kept."""
        m.http = self._Http(m.url, self.rec, limits=self.limits)
        try:
            r = await m.http.post("/chatter/login", json={"username": m.username, "password": m.password})
            m.login = {"status": r.status_code}
        except Exception as e:  # noqa: BLE001
            m.login = {"status": 599, "error": type(e).__name__}
        return m.login["status"] == 200

    async def _clock_in(self, m: Member) -> int | None:
        aid = sorted(m.assigned)[0]
        try:
            r = await m.http.post("/admin/shifts/clock-in", json={"account_id": aid})
        except Exception:  # noqa: BLE001 — a transport error is the stock check's
            self.writes.append(("in", m.username, 599, None))
            return None
        eid = r.json().get("clock_event_id") if r.status_code == 200 else None
        self.writes.append(("in", m.username, r.status_code, eid))
        return eid

    async def _clock_out(self, m: Member, eid: int | None) -> None:
        try:
            r = await m.http.post("/admin/shifts/clock-out", json={"clock_event_id": eid or 0})
        except Exception:  # noqa: BLE001
            self.writes.append(("out", m.username, 599, eid))
            return
        self.writes.append(("out", m.username, r.status_code, eid if r.status_code == 200 else None))

    async def storm(self, members: list[Member], k: int) -> None:
        await asyncio.gather(*(self._clock_in(m) for m in members for _ in range(k)))

    async def _think(self) -> None:
        await asyncio.sleep(self.rng.uniform(*self.think_s))

    async def _status_open(self, m: Member) -> int | None:
        try:
            r = await m.http.get("/admin/shifts/clock-status")
            return ((r.json().get("open") or {}).get("clock_event_id")) if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            return None

    async def _beats(self, m: Member, n: int) -> None:
        for _ in range(n):
            await self._think()
            try:
                await m.http.post("/admin/shifts/clock-heartbeat")
            except Exception:  # noqa: BLE001
                pass

    async def work(self, m: Member) -> None:
        first, second = self.plans[m.username]
        await self._think()
        eid = await self._status_open(m)
        await self._beats(m, first)
        await self._clock_out(m, eid)
        await self._think()
        eid = await self._clock_in(m)
        await self._beats(m, second)
        await self._status_open(m)
        await self._clock_out(m, eid)

    async def close(self, members: list[Member]) -> None:
        await asyncio.gather(*(m.http.aclose() for m in members if m.http is not None), return_exceptions=True)
