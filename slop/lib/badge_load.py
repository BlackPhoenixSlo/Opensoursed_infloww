from __future__ import annotations

import asyncio
import contextlib
import time
from collections import Counter

from slop.actors.badge_tab import BadgeTab, classify
from slop.actors.manager import events_of
from slop.lib.badge_wire import BadgeWire, chat_plan

CHATS = 24
ONLY_FRIENDS = 2
RESTRICTED = 1
PLAIN = CHATS - ONLY_FRIENDS - RESTRICTED - 1
PLAIN_UNREAD = 5
PLAIN_HIGH = 7
SLOT_S = 1.5
PATTERN = ("read", "dm", "reply", "dm", "read", "dm", "reply", "unread")
PUMP_UP_S = 30.0


def plan(fans: list[dict]) -> list[dict]:
    return chat_plan(fans, [("only_friends", ONLY_FRIENDS, True), ("restricted", RESTRICTED, True),
                            ("muted", 1, True), ("plain", PLAIN_UNREAD, True), ("plain", PLAIN - PLAIN_UNREAD, False)])


def phase_b(slot) -> bool:
    return isinstance(slot, dict) and "v" in slot and "grey" in slot


class DotTab(BadgeTab):

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.dots: dict[str, list[tuple[float, int, int]]] = {aid: [] for aid in self.aids}

    def _keep_states(self, obj) -> None:
        t = time.time()
        for ev in events_of(obj):
            aid = str(ev.get("__account_id"))
            if aid not in self.dots:
                continue
            c, m = ev.get("chat_read_changed"), ev.get("api2_chat_message")
            with contextlib.suppress(KeyError, TypeError, ValueError):
                if isinstance(c, dict):
                    self.dots[aid].append((t, int(c["fan_id"]), int(c["unread"])))
                elif isinstance(m, dict) and str((m.get("fromUser") or {}).get("id", aid)) != aid:
                    self.dots[aid].append((t, int(m["fromUser"]["id"]), 1))
        super()._keep_states(obj)


class Driver:

    def __init__(self, wire: BadgeWire, plain: dict[str, list[int]]) -> None:
        self.wire, self.plain = wire, plain
        self.truth: list[tuple[float, str, int, int, str]] = []
        self.moved = {(a, f): 0.0 for a, fs in plain.items() for f in fs}
        self.done: Counter = Counter()
        self.skipped: Counter = Counter()
        self.high = PLAIN_HIGH

    def unread(self, aid: str) -> list[int]:
        u = self.wire.truth_unread(aid)
        return [f for f in self.plain[aid] if f in u]

    def pick(self, aid: str, unread: bool) -> int | None:
        u = set(self.unread(aid))
        if not unread and len(u) >= self.high:
            return None
        return min((f for f in self.plain[aid] if (f in u) == unread), key=lambda f: self.moved[(aid, f)],
                   default=None)

    def act(self, aid: str, kind: str) -> int | None:
        fan = self.pick(aid, kind in ("read", "reply"))
        if fan is None:
            self.skipped[kind] += 1
            return None
        self.apply(aid, kind, fan, kind)
        return fan

    def apply(self, aid: str, kind: str, fan: int, cause: str) -> float:
        w = self.wire
        if kind == "read":
            w.read_elsewhere(aid, fan)
        elif kind == "reply":
            w.reply_elsewhere(aid, fan, echo=False)
        elif kind == "unread":
            w.mark_unread_elsewhere(aid, fan)
        else:
            w.push_dm(aid, {"id": fan})
        t = time.time()
        self.moved[(aid, fan)] = t
        self.done[kind] += 1
        self.truth.append((t, aid, fan, int(kind in ("unread", "dm")), cause))
        return t

    async def run(self, aid: str, t0: float, t1: float) -> None:
        k = 0
        while (due := t0 + k * SLOT_S) < t1:
            await asyncio.sleep(max(0.0, due - time.time()))
            self.act(aid, PATTERN[k % len(PATTERN)])
            k += 1


async def pumps(ctx, fake, creators: list[str], leg: str) -> None:
    t = time.time()
    (await ctx.owner.share().post("/__slop/pump-supervise")).raise_for_status()
    up: set = set()
    while time.time() - t < PUMP_UP_S and len(up) < len(creators):
        await asyncio.sleep(0.25)
        with fake.lock:
            up = {c["account"] for c in fake.ws_connects if c["t"] >= t}
    ctx.metric(f"pumps_up_{leg}", {"connected": len(up), "creators": len(creators),
                                   "seconds": round(time.time() - t, 1)})


async def dot_tabs(ctx, creators: list[str], ts, leg: str) -> list[DotTab]:
    tabs = [DotTab(ctx, f"{a}-{leg}", [a], ts) for a in creators]
    await asyncio.gather(*(t.start() for t in tabs))
    return tabs


async def close_tabs(tabs: list[DotTab], ts) -> None:
    await asyncio.gather(*(t.stop() for t in tabs), return_exceptions=True)
    await classify(tabs, ts)
