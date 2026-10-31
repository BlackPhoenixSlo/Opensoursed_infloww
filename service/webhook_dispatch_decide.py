"""
W7 webhook dispatch's decisions as pure functions (the shell: webhook_dispatch.py,
load -> plan -> apply). No DB, no clock, no loop: the shell reads, passes `now`,
and performs what comes back.

  when(paused_until, delay_s, now) -> (run_at, wait_s, deferred)
      A fan on a per-fan cooldown is deferred to its end; the response delay
      goes on top either way.
  dedup_within_s(paused_until, delay_s, now)
      The window the shell's pending-job read spans: the full wait plus
      DEDUP_WINDOW_S, so a second DM during the rest finds the deferred job.
  plan(kind, rule_id, fan_id, paused_until, delay_s, dup, now) -> Action
      Skip("terminal")       no automation owns the fan (kind None)
      Skip("cooldown_far")   cooldown ends more than MAX_DEFER_S out
      WakeOnly()             a job for this fan is already pending (dup)
      Enqueue(payload, run_at, wait_s, deferred)
  targets_fan(payload, fid)
      Does a job's payload name this fan (only_fan_ids / test_fan / fan_id)?
  blast_claim(claims, key, now_mono, dedup_s, max_n) -> (claimed, claims')
      The post-blast scrape's in-process claim; claims' is a new dict only
      when claimed (pruned of stale claims past max_n). The caller checks and
      stores it with no await in between.

Importable without side effects (stdlib only).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Union

# Skip enqueue if a pending job for this fan is due within the wait + this many s.
DEDUP_WINDOW_S = 5
# A cooldown further out than this (the 30-min welcome/followup rest) is too long
# to park a chat reply on: the periodic sweep catches that rare case.
MAX_DEFER_S = 300


@dataclass(frozen=True)
class Skip:
    reason: Literal["terminal", "cooldown_far"]


@dataclass(frozen=True)
class WakeOnly:
    """A job for this fan is already pending: wake so it drains, enqueue nothing."""


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
    # Fan-scope the run: reply_mass_funnel takes `test_fan`, the chat engines
    # `only_fan_ids`.
    payload: dict = ({"test_fan": fan_id} if kind == "reply_mass_funnel"
                     else {"only_fan_ids": [fan_id]})
    if rule_id is not None:
        payload["_rule_id"] = rule_id
    return Enqueue(payload, run_at, wait_s, deferred)


def targets_fan(payload: dict, fid: int) -> bool:
    # The producers name the fan differently: the chat engines take a LIST
    # (`only_fan_ids`), the funnel takes `test_fan`, a single-fan job a bare `fan_id`.
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
