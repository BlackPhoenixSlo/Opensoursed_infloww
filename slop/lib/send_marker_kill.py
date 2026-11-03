"""The send-once KILL phase's driver (service/automations/send_marker_decide.py), shared by
the scenarios that kill a sender mid-step; each keeps its seeding, OF modes and checks.

  k = Kill(ctx, keys, hang, tick)   keys: the (account, fan) watched; hang: {account: fan}
                                    the step that must hang; tick(http, account) -> dict
  await k.crash(fans_cfg, ...)      OF modes on, ticks until every hang fan's text is taken
                                    and unanswered (stable), SIGKILL, OF answers, relay back
  k.expire_leases(con)              the dead holder's fan leases, as if their TTL had passed
  await k.tick_all()                one tick per account, concurrent
  await k.unconfirmed()             GET /admin/unconfirmed-sends per account
  await k.retry(con, bodies)        POST .../retry per fan, then its send rest off
  k.took(), k.pre_retry()           OnlyFans' `accepted` count per (account, fan, text)

OnlyFans' side is lib/send_once_relay.py (its journal outlives the SIGKILL). Bypasses,
declared: the lease expiry and the send-rest nulling are SQL.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from slop.lib.client import Recorder
from slop.lib.send_once_relay import read_journal
from slop.seed import ts


class Kill:
    def __init__(self, ctx, keys: set, hang: dict, tick: Callable[..., Awaitable[dict]],
                 hang_s: float) -> None:
        self.ctx, self.keys, self.hang, self.tick, self.hang_s = ctx, keys, hang, tick, hang_s
        self.aids = sorted(hang)
        self.tmp = ctx.stack.tmp
        self.rec = Recorder()   # the KILL ticks: they die with the relay
        self.tick_http = self.owner = None
        self.t_kill = self.t_retry = None

    def _cfg(self, fans: dict) -> None:
        (self.tmp / "of-send-once.json").write_text(
            json.dumps({"fans": fans, "hang_s": self.hang_s, "first_key": "fan_text"}))

    def journal(self) -> list[dict]:
        return [r for r in read_journal(self.tmp) if (r["account_id"], int(r["fan_id"])) in self.keys]

    def hung(self) -> dict:
        """hang fan -> the text OF took and has not answered."""
        rows, fans = self.journal(), set(self.hang.items())
        back = {(r["account_id"], int(r["fan_id"]), r["text"]) for r in rows if r["op"] == "returned"}
        return {(r["account_id"], int(r["fan_id"])): r["text"] for r in rows if r["op"] == "accepted"
                and (r["account_id"], int(r["fan_id"])) in fans
                and (r["account_id"], int(r["fan_id"]), r["text"]) not in back}

    async def crash(self, fans_cfg: dict, timeout_s: float, stable_s: float) -> tuple[bool, dict, float]:
        """-> (every hang fan hung and stable at the kill, what each had hung on, waited s)."""
        self._cfg(fans_cfg)
        want = set(self.hang.items())
        tick_http = self.ctx.owner.share(rec=self.rec, limits=8)
        tasks = {a: asyncio.create_task(self.tick(tick_http, a)) for a in self.aids}
        t0, hit, seen, since = time.monotonic(), False, None, 0.0
        while time.monotonic() - t0 < timeout_s:
            now = self.hung()
            if seen is None or set(now) != set(seen):
                seen, since = now, time.monotonic()
            elif set(now) == want and time.monotonic() - since >= stable_s:
                hit = True
                break
            for a, t in tasks.items():   # a run that ended before its fan hung: tick again
                if t.done() and (a, self.hang[a]) not in now:
                    tasks[a] = asyncio.create_task(self.tick(tick_http, a))
            await asyncio.sleep(0.1)
        waited = round(time.monotonic() - t0, 1)
        self.t_kill = self.ctx.stack.crash_relay()
        for t in tasks.values():
            t.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        await tick_http.aclose()
        self._cfg({})   # OF answers now
        await asyncio.to_thread(self.ctx.stack.start_relay)
        self.owner = self.ctx.owner.share(limits=8)   # the relay's pools died with it
        self.tick_http = self.ctx.owner.share(rec=self.rec, limits=8)
        return hit, dict(seen or {}), waited

    def expire_leases(self, con) -> None:
        with con:   # declared
            con.executemany("UPDATE fan_lease SET leased_until=? WHERE account_id=? AND fan_id=?",
                            [(ts(datetime.utcnow() - timedelta(seconds=1)), a, f) for a, f in sorted(self.keys)])

    async def tick_all(self) -> list[dict]:
        return list(await asyncio.gather(*(self.tick(self.tick_http, a) for a in self.aids)))

    async def unconfirmed(self) -> tuple[dict, list[int]]:
        """-> ({(account, fan): listed row}, each GET's status)."""
        listed, status = {}, []
        for a in self.aids:
            r = await self.owner.get("/admin/unconfirmed-sends", params={"account_id": a})
            status.append(r.status_code)
            if r.status_code == 200:
                for row in r.json()["rows"]:
                    listed[(a, int(row["fan_id"]))] = row
        return listed, status

    async def retry(self, con, bodies: dict) -> dict:
        """bodies {(account, fan): retry json} -> {(account, fan): (status, body status)}."""
        self.t_retry = time.time()
        out = {}
        for (a, f), body in bodies.items():
            r = await self.owner.post("/admin/unconfirmed-sends/retry", params={"account_id": a}, json=body)
            out[(a, f)] = (r.status_code, (r.json() if r.status_code == 200 else {}).get("status"))
        with con:   # the retried fans' send rest (declared)
            con.executemany("UPDATE fans SET automation_paused_until=NULL WHERE account_id=? AND fan_id=?",
                            sorted(bodies))
        return out

    def took(self) -> Counter:
        return Counter((r["account_id"], int(r["fan_id"]), r["text"]) for r in self.journal()
                       if r["op"] == "accepted")

    def pre_retry(self) -> Counter:
        return Counter((r["account_id"], int(r["fan_id"]), r["text"]) for r in self.journal()
                       if r["op"] == "accepted" and r["t"] < self.t_retry)

    async def close(self) -> None:
        for h in (self.tick_http, self.owner):
            if h is not None:
                await h.aclose()
