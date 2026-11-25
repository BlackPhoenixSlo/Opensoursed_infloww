from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Union

DEDUP_WINDOW_S = 5
MAX_DEFER_S = 300


@dataclass(frozen=True)
class Skip:
    reason: Literal["terminal", "cooldown_far"]


@dataclass(frozen=True)
class WakeOnly:
    pass


@dataclass(frozen=True)
class Enqueue:
    payload: dict
    run_at: datetime
    wait_s: float
    deferred: bool


Action = Union[Skip, WakeOnly, Enqueue]


def when(paused_until: datetime | None, delay_s: float, now: datetime) -> tuple[datetime, float, bool]:
    deferred = paused_until is not None and paused_until > now
    run_at = (paused_until if deferred else now) + timedelta(seconds=delay_s)
    return run_at, max(0.0, (run_at - now).total_seconds()), deferred


def dedup_within_s(paused_until: datetime | None, delay_s: float, now: datetime) -> float:
    return when(paused_until, delay_s, now)[1] + DEDUP_WINDOW_S


def plan(kind: str | None, rule_id: int | None, fan_id: int, paused_until: datetime | None,
         delay_s: float, dup: bool, now: datetime) -> Action:
    if kind is None:
        return Skip("terminal")
    run_at, wait_s, deferred = when(paused_until, delay_s, now)
    if deferred and (paused_until - now).total_seconds() > MAX_DEFER_S:
        return Skip("cooldown_far")
    if dup:
        return WakeOnly()
    payload: dict = ({"test_fan": fan_id} if kind == "reply_mass_funnel"
                     else {"only_fan_ids": [fan_id]})
    if rule_id is not None:
        payload["_rule_id"] = rule_id
    return Enqueue(payload, run_at, wait_s, deferred)


def targets_fan(payload: dict, fid: int) -> bool:
    return (fid in (payload.get("only_fan_ids") or [])
            or payload.get("test_fan") == fid
            or payload.get("fan_id") == fid)


def blast_claim(claims: dict, key, now_mono: float, dedup_s: float,
                max_n: int) -> tuple[bool, dict]:
    at = claims.get(key)
    if at is not None and now_mono - at < dedup_s:
        return False, claims
    out = {**claims, key: now_mono}
    if len(out) > max_n:
        stale = now_mono - dedup_s
        out = {k: t for k, t in out.items() if t >= stale}
    return True, out
