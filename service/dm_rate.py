from __future__ import annotations

import asyncio
import collections
import contextvars
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import lane_config
import run_slot

log = logging.getLogger("dm_rate")

KNOB = "OF_DM_PER_MIN"
DEFAULT_PER_MIN = 23
WINDOW_S = 60.0
# A waiter woken on the boundary lands inside OF's window (measured 7 in 60 s at limit 6); the 1 s is a guess at clock jitter
SLACK_S = 1.0


def limit() -> int:
    return lane_config.resolve_live(KNOB, DEFAULT_PER_MIN)


limit()


class _Ticket:

    __slots__ = ("account", "used", "task", "place")

    def __init__(self, account: str, place: list) -> None:
        self.account, self.used, self.place = account, False, place
        self.task = asyncio.current_task()


_TICKET: contextvars.ContextVar[_Ticket | None] = contextvars.ContextVar("dm_rate_ticket", default=None)


@dataclass
class Window:
    clock: Callable[[], float] = time.monotonic
    sent: collections.deque = field(default_factory=collections.deque)
    peak: int = 0
    waits: int = 0
    waited_s: float = 0.0
    unguarded: int = 0
    retries: int = 0
    over: int = 0
    _over_logged: float = -1e18

    def _prune(self, now: float) -> None:
        keep = now - WINDOW_S - SLACK_S
        if any(p[0] <= keep for p in self.sent):
            self.sent = collections.deque(p for p in self.sent if p[0] > keep)

    def _in_window(self, now: float) -> int:
        return sum(1 for p in self.sent if p[0] > now - WINDOW_S)

    def _add(self, now: float, account: str, cap: int) -> list:
        place = [now]
        self.sent.append(place)
        self._tally(now, account, cap)
        return place

    def _tally(self, now: float, account: str, cap: int) -> None:
        n = self._in_window(now)
        if n > self.peak:
            self.peak = n
            log.info("dm_rate account=%s peak %d DMs/min (limit %d)", account, n, cap)
        if n > cap:
            self.over += 1
            if now - self._over_logged >= WINDOW_S:
                self._over_logged = now
                log.warning("dm_rate account=%s %d DMs in 60 s, past the limit %d "
                            "(operator sends are never held)", account, n, cap)

    def wait_for(self, now: float, cap: int) -> float:
        self._prune(now)
        times = sorted(p[0] for p in self.sent)
        if len(times) < cap:
            return 0.0
        return max(0.0, times[len(times) - cap] + WINDOW_S + SLACK_S - now)


_lock = threading.Lock()
_windows: dict[str, Window] = {}


def _window(account: str) -> Window:
    w = _windows.get(account)
    if w is None:
        w = _windows[account] = Window()
    return w


def _automation() -> bool:
    r = run_slot.run_of_task()
    return r is not None and not r.operator


# Operator DMs never wait, only count; release_budget_s must not be used under a lock others wait on (a run never hands its slot back while holding one)
async def turn(account_id: str | None, *, operator: bool | None = None,
               release_budget_s: float | None = None) -> float:
    if account_id is None:
        return 0.0
    if operator is None:
        operator = not _automation()
    if operator:
        _TICKET.set(None)
        return 0.0
    account = str(account_id)
    t = _TICKET.get()
    if t is not None and not t.used and t.account == account and t.task is asyncio.current_task():
        return 0.0
    waited = 0.0
    while True:
        cap = limit()
        with _lock:
            w = _window(account)
            now = w.clock()
            gap = w.wait_for(now, cap)
            if gap <= 0:
                place = w._add(now, account, cap)
                if waited:
                    w.waits += 1
                    w.waited_s += waited
                _TICKET.set(_Ticket(account, place))
                break
        if release_budget_s is None:
            await asyncio.sleep(gap)
        else:
            async with run_slot.released(gap, budget_s=release_budget_s):
                await asyncio.sleep(gap)
        waited += gap
    if waited:
        log.info("dm_rate account=%s automation DM waited %.1fs (limit %d/min)", account, waited, cap)
    return waited


def release(account_id: str | None) -> None:
    if account_id is None:
        return
    t = _TICKET.get()
    if t is None or t.used or t.account != str(account_id) or t.task is not asyncio.current_task():
        return
    t.used = True
    _TICKET.set(None)
    with _lock:
        w = _window(t.account)
        if any(p is t.place for p in w.sent):
            w.sent = collections.deque(p for p in w.sent if p is not t.place)


def record(account_id: str | None) -> None:
    if account_id is None:
        return
    account = str(account_id)
    t = _TICKET.get()
    mine = t is not None and t.account == account
    cap = limit()
    if mine and not t.used:
        t.used = True
        with _lock:
            w = _window(account)
            now = w.clock()
            t.place[0] = max(t.place[0], now)
            if not any(p is t.place for p in w.sent):
                w.sent.append(t.place)
            w._tally(now, account, cap)
        return
    with _lock:
        w = _window(account)
        now = w.clock()
        w._prune(now)
        if mine:
            w.retries += 1
        elif _automation():
            w.unguarded += 1
            log.warning("dm_rate account=%s an automation DM reached OF without a turn "
                        "(a sender not wired to dm_rate)", account)
        w._add(now, account, cap)


def snapshot() -> dict[str, dict]:
    with _lock:
        out = {}
        for account, w in _windows.items():
            w._prune(w.clock())
            out[account] = {"now": w._in_window(w.clock()), "peak": w.peak, "waits": w.waits,
                            "waited_s": round(w.waited_s, 1), "unguarded": w.unguarded,
                            "retries": w.retries, "over": w.over}
        return out


def _reset() -> None:
    with _lock:
        _windows.clear()
