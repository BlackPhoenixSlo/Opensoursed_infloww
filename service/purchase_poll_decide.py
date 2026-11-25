from __future__ import annotations

import zlib
from dataclasses import dataclass, replace
from typing import Literal

from env_knob import env_float

Tier = Literal["fast", "slow"]

_DEFAULT_FAST_S = 30.0
_DEFAULT_SLOW_S = 300.0
_MIN_FAST_S = 5.0


FAST_S = env_float("PURCHASES_POLL_FAST_S", _DEFAULT_FAST_S, _MIN_FAST_S)
SLOW_S = max(FAST_S, env_float("PURCHASES_POLL_SLOW_S", _DEFAULT_SLOW_S, _MIN_FAST_S))
BACKOFF_BASE_S = env_float("PURCHASES_BACKOFF_BASE_S", 30.0, 1.0)
BACKOFF_MAX_S = max(BACKOFF_BASE_S, env_float("PURCHASES_BACKOFF_MAX_S", 900.0, 1.0))
BACKOFF_DEMAND_MAX_S = env_float("PURCHASES_BACKOFF_DEMAND_MAX_S", 120.0, 1.0)
CATCHUP_MAX_PAGES = int(env_float("PURCHASES_CATCHUP_MAX_PAGES", 3.0, 1.0))
SELECT_MIN_AGE_S = FAST_S / 6

OutcomeKind = Literal["ok", "rate_limited", "unauthorized", "dead", "error"]


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    retry_after_s: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PollState:
    last_s: float | None = None
    last_ok_s: float | None = None
    step: int = 0
    held_at: float | None = None
    hold_s: float = 0.0
    last_started_s: float | None = None


def tier(leased: bool, seller: bool) -> Tier:
    return "fast" if leased or seller else "slow"


def interval_s(t: Tier) -> float:
    return FAST_S if t == "fast" else SLOW_S


def hold_s(state: PollState, t: Tier) -> float:
    return min(state.hold_s, BACKOFF_DEMAND_MAX_S) if t == "fast" else state.hold_s


def held(state: PollState | None, t: Tier, now: float, ahead: float) -> bool:
    if state is None or state.held_at is None:
        return False
    if now >= state.held_at + hold_s(state, t):
        return False
    return t != "fast" or now + ahead <= state.held_at + BACKOFF_DEMAND_MAX_S


def due(state: PollState | None, t: Tier, now: float) -> bool:
    if held(state, t, now, FAST_S):
        return False
    if state is None or state.last_s is None:
        return True
    return now - state.last_s >= interval_s(t) - FAST_S / 2


def ladder_s(step: int) -> float:
    return min(BACKOFF_BASE_S * 2 ** min(max(0, step - 1), 60), BACKOFF_MAX_S)


def after(state: PollState | None, outcome: Outcome, started: float, answered: float) -> PollState:
    s = state or PollState()
    if outcome.kind == "ok":
        return replace(s, last_ok_s=started, step=0, held_at=None, hold_s=0.0)
    if outcome.kind in ("rate_limited", "unauthorized"):
        step = s.step + 1
        ra = outcome.retry_after_s if outcome.kind == "rate_limited" else None
        hold = max(ladder_s(step), 0.0 if ra is None else ra)
        return replace(s, step=step, held_at=answered, hold_s=hold)
    if outcome.kind == "dead":
        return replace(s, step=0, held_at=None, hold_s=0.0)
    return s


def catch_up(state: PollState | None, now: float) -> bool:
    return state is None or state.last_ok_s is None or now - state.last_ok_s > 2 * FAST_S


def started(state: PollState | None, now: float) -> PollState:
    return replace(state or PollState(), last_started_s=now)


def polled(state: PollState | None, now: float) -> PollState:
    return replace(state or PollState(), last_s=now)


def first_idle_state(account_id: str, now: float, state: PollState | None) -> PollState:
    slots = max(1, round(SLOW_S / FAST_S))
    return replace(state or PollState(), last_s=now - SLOW_S + (zlib.crc32(account_id.encode()) % slots) * FAST_S)

