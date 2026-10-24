"""service/dm_rate.py — one account's outbound DM rate, automation capped (ADR 0025 fix 9).

At most `OF_DM_PER_MIN` (default 23; env, then the Concurrency panel) DMs in
any 60 s on one account, counting every DM the relay sends there:

- AUTOMATION queues for it: before its send, an automation DM awaits `turn()`,
  which reserves a place in the account's window, waiting (`asyncio.sleep`:
  no worker thread parked) while the window is full. A sender whose send is
  where its typing holds already hand the run's slot back (`release_budget_s`
  given: the chat replies, autoreply, reply_mass_funnel, send_welcome's
  bursts) waits the same way, through `run_slot.released()`: a capped account
  does not sit on a fleet slot. Through `of_write_paced` (`dm=True`) the wait
  is a plain wait that keeps the slot, because a caller there can be under a
  lock others wait on (send_mass_message's `broadcast_lock`), and a run never
  hands its slot back while holding one.
- An OPERATOR's DM (the app's composer, an operator's run) never waits: it
  only counts, so automation leaves room for it the next minute.
- `release()` gives a turn's place back when its DM is dropped before the
  send (a stop, a chatter's pick, the fan's reply).
- `record()`, in `OFClient.send_message` (every DM's one way out), counts each
  DM: the one a `turn()` reserved is not counted twice (its place is moved
  to the send's own time: a turn can wait on its way to the POST); a second POST on the
  same turn (a refused attachment's text-only resend, a transient retry) counts
  as a DM of its own, not as an unguarded one. It keeps the account's
  peak (most DMs in any 60 s) and logs a new peak, a window past the limit
  (operators' sends can take it there) and an automation DM that reached OF
  without a turn (a sender not wired to this module).

A place frees `SLACK_S` (1 s) after the oldest DM leaves the 60 s, not on
the dot: a waiter woken at the boundary would land on OF's clock a few ms
inside the window it just left (measured: 7 in 60 s at a limit of 6 on the
fake, soak-runs/20261024-063234-drive-dm-rate). The slack is a guess at the
jitter between this clock and OF's receipt.

`snapshot()` is the counters, per account.
"""
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
SLACK_S = 1.0                  # a place frees this long after a DM leaves the window


def limit() -> int:
    """DMs one account may send in any 60 s; read at every send, so a panel
    save applies at once (recorded live: the panel shows no restart pending)."""
    return lane_config.resolve_live(KNOB, DEFAULT_PER_MIN)


limit()                                             # on the panel from boot


class _Ticket:
    """A place `turn()` reserved in an account's window, for the next DM of
    this task (its context reaches the send's worker thread)."""

    __slots__ = ("account", "used", "task", "place")

    def __init__(self, account: str, place: list) -> None:
        self.account, self.used, self.place = account, False, place
        self.task = asyncio.current_task()     # a child task inherits the var, not the turn


_TICKET: contextvars.ContextVar[_Ticket | None] = contextvars.ContextVar("dm_rate_ticket", default=None)


@dataclass
class Window:
    """One account's recent DMs (each a one-item list, its send time) and
    its counters."""
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
        """0 when a DM fits now (fewer than `cap` in the last window plus the
        slack), else how long until one more does."""
        self._prune(now)
        times = sorted(p[0] for p in self.sent)
        if len(times) < cap:
            return 0.0
        return max(0.0, times[len(times) - cap] + WINDOW_S + SLACK_S - now)


_lock = threading.Lock()               # record() runs in worker threads
_windows: dict[str, Window] = {}


def _window(account: str) -> Window:
    w = _windows.get(account)
    if w is None:
        w = _windows[account] = Window()
    return w


def _automation() -> bool:
    """This task works for an automation run (not an operator's): the run
    itself, a borrower, or any task it spawned."""
    r = run_slot.run_of_task()
    return r is not None and not r.operator


async def turn(account_id: str | None, *, operator: bool | None = None,
               release_budget_s: float | None = None) -> float:
    """Before an automation DM: wait for a place in the account's window and
    reserve it. An operator's DM (None: the current run's tier) passes at once
    and reserves nothing (`record` counts it). `release_budget_s`: wait
    through `run_slot.released` (that take-back budget; it may raise
    `run_slot.SlotLost` after the wait, nothing reserved); never under a lock
    another run may wait for. None = a plain wait, the slot kept. A task
    holding an unused turn for the account gets 0 at once: a sender takes its
    turn where it handles SlotLost, and a helper's turn under it is a no-op.
    Returns the seconds waited."""
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
        return 0.0                     # this task's DM already has its place
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
    """A sender that took its turn and then drops the DM (a stop, a chatter's
    pick, the fan's reply, an error before the send) gives the place back at
    once, not 61 s later. Only this task's unused turn for the account; else
    nothing."""
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
    """In the send: count this DM, unless this task's `turn()` reserved it."""
    if account_id is None:
        return
    account = str(account_id)
    t = _TICKET.get()
    mine = t is not None and t.account == account
    cap = limit()
    if mine and not t.used:
        t.used = True
        with _lock:                    # the place moves to the send's own time
            w = _window(account)
            now = w.clock()
            t.place[0] = max(t.place[0], now)
            if not any(p is t.place for p in w.sent):
                w.sent.append(t.place)     # pruned while its turn waited on the way (the 11 s gate)
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
    """Per account: DMs in the last 60 s, the peak, automation waits, unguarded
    automation DMs, second POSTs on one turn and sends past the limit."""
    with _lock:
        out = {}
        for account, w in _windows.items():
            w._prune(w.clock())
            out[account] = {"now": w._in_window(w.clock()), "peak": w.peak, "waits": w.waits,
                            "waited_s": round(w.waited_s, 1), "unguarded": w.unguarded,
                            "retries": w.retries, "over": w.over}
        return out


def _reset() -> None:
    """Tests: forget every window."""
    with _lock:
        _windows.clear()
