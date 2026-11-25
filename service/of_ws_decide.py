from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

RECONNECT_MIN_S = 1
RECONNECT_MAX_S = 30
RESET_AFTER_S = 60
DEAD_RETRIES = 3


@dataclass(frozen=True)
class Pump:
    backoff: int = RECONNECT_MIN_S
    dead: int = 0


@dataclass(frozen=True)
class Failed:
    dead_reason: Optional[str] = None
    up_s: Optional[float] = None


@dataclass(frozen=True)
class Wait:
    s: int
    retry: int = 0


@dataclass(frozen=True)
class GiveUp:
    reason: str


Effect = Union[Wait, GiveUp]


def decide(state: Pump, ev: Failed) -> tuple[Pump, Effect]:
    if ev.up_s is not None and ev.up_s >= RESET_AFTER_S:
        state = Pump()
    dead = state.dead
    if ev.dead_reason:
        if dead >= DEAD_RETRIES:
            return state, GiveUp(ev.dead_reason)
        dead += 1
    return (Pump(min(state.backoff * 2, RECONNECT_MAX_S), dead),
            Wait(state.backoff, dead if ev.dead_reason else 0))
