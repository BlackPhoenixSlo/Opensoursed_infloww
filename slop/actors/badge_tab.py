"""A headless Creator tab (docs/spec/creator-badges/phase-0E-slop-and-fake-of-realism.md, "One headless tab actor"):
an open app tab on its Creators. It follows `/events?lease=1`, renews its View lease on them (so roster-counts reads
their windows and folds their Restricted unread), seeds from `GET /admin/accounts`, polls
`GET /admin/accounts/roster-counts` only to record served numbers, and refetches the accounts answer when a ping's
`badge` says it is behind (Phase B's one-behind-ping refetch).

The tab holds no copy of the app's client logic: its Freshness store is the app's own `creatorFreshnessReducer`, the
behind decision the app's `badgeBehind` (app/lib/creatorFreshness.ts), and `classify` the app's `redCircle`
(app/components/chat/redCircle.ts), all run in node through lib/app_ts.py (`open_ts`, lib/badge_tab_ts.mjs), one
action at a time in arrival order, as the app's hooks dispatch them. Seeds and events are kept to the tab's Creators
before they go in (the reducer is per Creator, so this is the app's store seen through the tab's Creators).

`slots[aid]`: every change of the held `values.unread_total`, `(t, slot)`; `served`: every badge number the tab was
served, `(t, aid, n, source)` with `t` the value's own time (the slot's `at`, roster-counts' `as_of`; arrival when it
has none) and source sse | accounts | roster. `observed[aid]`: `(t, kind, n)` per Red/Grey/Amber change (kind red |
grey | amber; red 0 when the circle draws none), filled by `classify`. Times are epoch seconds."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from slop.actors.manager import SseListener

BADGE_TAB_TS = Path(__file__).resolve().parents[1] / "lib" / "badge_tab_ts.mjs"


async def open_ts(ctx, n: int = 1) -> list:
    """`n` node sessions running lib/badge_tab_ts.mjs; tabs share them (`ts=`), the caller closes them."""
    from slop.lib import app_ts
    return [await app_ts.session(ctx, BADGE_TAB_TS) for _ in range(n)]


def _ms(t: float) -> int:
    return int(t * 1000)


class BadgeTab(SseListener):
    def __init__(self, ctx, name: str, account_ids, ts, *, http=None, lease_s: float = 30.0, roster_s: float = 60.0):
        super().__init__(http or ctx.owner.share(limits=4), resume=True, states=("creator_refreshed",), lease=True)
        self.name, self.aids, self.ts = name, [str(a) for a in account_ids], ts
        self.lease_s, self.roster_s = lease_s, roster_s
        self.state: dict = {}
        self.slots: dict[str, list[tuple[float, dict | None]]] = {a: [] for a in self.aids}
        self.served: list[tuple[float, str, int, str]] = []
        self.observed: dict[str, list[tuple[float, str, int | None]]] = {a: [] for a in self.aids}
        self.pings = 0
        self.behind_pings = 0
        self.refetches = 0
        self.errors: list[str] = []
        self._q: asyncio.Queue = asyncio.Queue()
        self._refetching: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._halt = asyncio.Event()

    def held(self, aid: str):
        """The `values.unread_total` the tab holds for `aid`, or None."""
        return ((self.state.get(aid) or {}).get("values") or {}).get("unread_total")

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._work())]
        await super().start()
        await self._lease()
        await self.refetch()
        await self.roster()
        self._tasks += [asyncio.create_task(self._every(self.lease_s, self._lease)),
                        asyncio.create_task(self._every(self.roster_s, self.roster))]

    async def stop(self) -> None:
        self._halt.set()
        await super().stop()
        if self._refetching:
            await asyncio.gather(self._refetching, return_exceptions=True)
        await self._q.join()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _every(self, s: float, fn) -> None:
        while True:
            try:
                await asyncio.wait_for(self._halt.wait(), s)
                return
            except asyncio.TimeoutError:
                await fn()

    async def _get(self, path: str):
        try:
            r = await self.http.get(path)
        except Exception as e:  # noqa: BLE001 — a failed read is a finding, the tab keeps going
            self.errors.append(f"GET {path}: {type(e).__name__}"[:200])
            return None
        if r.status_code != 200:
            self.errors.append(f"GET {path}: {r.status_code}")
            return None
        return r.json()

    async def _lease(self) -> None:
        try:
            await self.http.post("/admin/view-lease", json={"tab": f"slop-badge-{self.name}", "account_ids": self.aids})
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"POST /admin/view-lease: {type(e).__name__}"[:200])

    def _serve(self, t: float, aid: str, slot, source: str) -> None:
        if isinstance(slot, dict) and isinstance(slot.get("n"), int):
            at = slot.get("at")
            self.served.append((at / 1000 if isinstance(at, (int, float)) else t, aid, slot["n"], source))

    def _put(self, t: float, action: dict | None, badge=None) -> asyncio.Future:
        done = asyncio.get_running_loop().create_future()
        self._q.put_nowait((t, action, badge, done))
        return done

    async def _work(self) -> None:
        while True:
            t, action, badge, done = await self._q.get()
            try:
                out = await self.ts.call({"state": self.state, "actions": [action] if action else [], "badge": badge})
                before = {aid: self.held(aid) for aid in self.aids}
                self.state = out["state"]
                for aid in self.aids:
                    if self.held(aid) != before[aid]:
                        self.slots[aid].append((t, self.held(aid)))
                if out["behind"]:
                    self.behind_pings += 1
                    if self._refetching is None or self._refetching.done():
                        self.refetches += 1
                        self._refetching = asyncio.create_task(self.refetch())
            except Exception as e:  # noqa: BLE001 — a failed step is a finding, the tab keeps going
                self.errors.append(f"{(action or {}).get('type', 'ping')}: {type(e).__name__}: {e}"[:200])
            finally:
                done.set_result(None)
                self._q.task_done()

    async def refetch(self) -> None:
        body = await self._get("/admin/accounts")
        if body is None:
            return
        t = time.time()
        rows = [{"id": str(a.get("id")), "freshness": a.get("freshness")}
                for a in body.get("accounts") or [] if str(a.get("id")) in self.slots]
        for r in rows:
            self._serve(t, r["id"], ((r["freshness"] or {}).get("values") or {}).get("unread_total"), "accounts")
        await self._put(t, {"type": "seeded", "rows": rows, "receivedAt": _ms(t)})

    async def roster(self) -> None:
        body = await self._get("/admin/accounts/roster-counts")
        t = time.time()
        for aid, c in ((body or {}).get("counts") or {}).items():
            if aid in self.slots and isinstance(c, dict) and isinstance(c.get("unread"), int):
                as_of = c.get("as_of")
                self.served.append((as_of / 1000 if isinstance(as_of, (int, float)) and as_of > 0 else t, aid,
                                    c["unread"], "roster"))

    def _keep_states(self, obj) -> None:
        n0 = len(self.state_events)
        super()._keep_states(obj)
        t = time.time()
        for _, body, _ in self.state_events[n0:]:
            aid = str(body.get("account_id"))
            if aid in self.slots:
                self._serve(t, aid, (body.get("values") or {}).get("unread_total"), "sse")
                self._put(t, {"type": "refreshed", "body": body, "receivedAt": _ms(t)})
        del self.state_events[:]

    def _ping(self, data: str) -> None:
        try:
            obj = json.loads(data)
        except ValueError:
            return
        if not isinstance(obj, dict):
            return
        t = time.time()
        self.pings += 1
        now = round(obj["ts"] * 1000) if isinstance(obj.get("ts"), (int, float)) else None
        self._put(t, {"type": "confirmed", "fresh": obj.get("fresh"), "now": now, "receivedAt": _ms(t)},
                  obj.get("badge"))

    def red(self, aid: str) -> list[tuple[float, int | str]]:
        """The Red circle as this tab drew it, `(t, n)`, grey as "grey" (never a number)."""
        return [(t, n if kind == "red" else "grey") for t, kind, n in self.observed.get(aid, ()) if kind != "amber"]

    def fill(self, circle_of) -> None:
        """`observed` from the held slots: `circle_of(slot)` is the app's redCircle on it."""
        for aid, changes in self.slots.items():
            out: list[tuple[float, str, int | None]] = []
            last_red, last_amber = None, None
            for t, slot in changes:
                c = circle_of(slot)
                red = ("grey", None) if c["kind"] == "grey" else ("red", c["n"] if c["kind"] == "count" else 0)
                if red != last_red:
                    out.append((t, *red))
                    last_red = red
                amber = (slot or {}).get("amber")
                if isinstance(amber, int) and amber != last_amber:
                    out.append((t, "amber", amber))
                    last_amber = amber
            self.observed[aid] = out


async def classify(tabs: list[BadgeTab], ts) -> None:
    """Every tab's `observed`, from one node call of the app's redCircle over every distinct slot the tabs held."""
    keys = sorted({json.dumps(s, sort_keys=True) for tab in tabs for ch in tab.slots.values() for _, s in ch})
    circles = (await ts.call({"op": "circles", "slots": [json.loads(k) for k in keys]}))["circles"] if keys else []
    by = dict(zip(keys, circles))
    for tab in tabs:
        tab.fill(lambda s: by[json.dumps(s, sort_keys=True)])
