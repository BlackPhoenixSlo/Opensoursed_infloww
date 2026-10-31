"""
The OnlyFans WebSocket pump's reconnect rules as ONE pure transition
(docs/reducer-scan.md, Non-React #10):

    decide(state, Failed(dead_reason)) -> (state', effect)

No I/O, no clock, no logging, stdlib only. OFWebSocket.events() (of_ws.py) is the
shell: each pass of its loop refreshes the ticket (/users/me), opens the socket,
says `{"act":"connect","token":…}` and yields frames. When a pass raises, its
`except` builds Failed, calls decide() and performs the one effect; every backoff /
give-up rule lives here.

A pass that ends without raising does so only after .stop() broke the read loop,
and the loop's `while` then ends events(): no rule applies. A socket OF closes is a
Failed (recv raises ConnectionClosed), so a pump's backoff never resets while it
lives (measured 2026-10-30: gaps 1, 2, 4, 8 s on a socket that connects and is then
closed, each time).

Event:
  Failed(dead_reason)   the pass raised: before the socket opened (/users/me, proxy
                        CONNECT, TLS) or while it was open. `dead_reason` is the
                        caller's session_dead classifier's answer for the error
                        (server.py: account_health.is_session_dead_error); None:
                        transient, or no classifier.

Effect (exactly one):
  Wait(s)               log the error, wait s seconds (a .stop() during it ends
                        events() cleanly), then reconnect
  GiveUp(reason)        raise SessionDead(reason): no reconnect can succeed until a
                        human signs in again; server.py's pump flags the account
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

RECONNECT_MIN_S = 1   # the first failure's wait
RECONNECT_MAX_S = 30  # the doubling stops here


@dataclass(frozen=True)
class Pump:
    backoff: int = RECONNECT_MIN_S  # the next transient failure's wait (s)


@dataclass(frozen=True)
class Failed:
    dead_reason: Optional[str] = None


@dataclass(frozen=True)
class Wait:
    s: int


@dataclass(frozen=True)
class GiveUp:
    reason: str


Effect = Union[Wait, GiveUp]


def decide(state: Pump, ev: Failed) -> tuple[Pump, Effect]:
    if ev.dead_reason:
        return state, GiveUp(ev.dead_reason)
    # Wait the current backoff; the next failure waits double, up to the cap.
    return Pump(min(state.backoff * 2, RECONNECT_MAX_S)), Wait(state.backoff)
