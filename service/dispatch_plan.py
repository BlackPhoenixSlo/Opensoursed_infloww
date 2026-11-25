from __future__ import annotations

import collections
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AbstractSet, Callable, Iterable, Literal, Mapping, NamedTuple, Union, assert_never

log = logging.getLogger("of-relay.automation.dispatch_plan")

POKE_FLOOR_S = 60

# A poke under the floor is kept for kinds where each poke may be the one event that owes a run; others spend it.
REPOKE_KINDS = frozenset({"promo_reactivate", "purchase_followup"})


# Rejects Infinity/NaN so int() of a stored value can never raise OverflowError.
def _positive_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


@dataclass(frozen=True)
class Interval:
    every: int | float
    max_runs: int | None


@dataclass(frozen=True)
class Clock:
    times: tuple
    tz_off_min: int
    max_runs: int | None


Trigger = Union[Interval, Clock]

# UTC-12..UTC+14: the rules API 422s outside it.
TZ_MIN, TZ_MAX = -720, 840


def tz_offset(raw) -> int | None:
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not TZ_MIN <= raw <= TZ_MAX:
        return None
    return int(raw)


@dataclass(frozen=True)
class _BadTz:
    raw: object


def _read(trigger: dict) -> Trigger | _BadTz | None:
    every = trigger.get("every_seconds")
    daily_at = trigger.get("daily_at")
    max_runs = trigger.get("max_runs")
    max_runs = int(max_runs) if _positive_number(max_runs) else None
    if _positive_number(every):
        return Interval(every, max_runs)
    if isinstance(daily_at, list) and daily_at:
        raw = trigger.get("tz_offset_minutes")
        off = tz_offset(raw)
        return _BadTz(raw) if off is None else Clock(tuple(daily_at), off, max_runs)
    return None


def trigger_of(trigger: dict) -> Trigger | None:
    t = _read(trigger)
    return None if isinstance(t, _BadTz) else t


# A bad tz never raises out of the materializer pass: one bad row would stop every rule.
def parse_trigger(trigger: dict) -> Trigger | None:
    t = _read(trigger)
    if isinstance(t, _BadTz):
        _bad_tz(t.raw)
        return None
    return t


_BAD_TZ_WARNED: set[str] = set()


def _bad_tz(raw) -> None:
    if repr(raw) in _BAD_TZ_WARNED:
        return
    _BAD_TZ_WARNED.add(repr(raw))
    log.warning("automation_rule_bad_tz_offset raw=%r: a clock rule with this tz_offset_minutes "
                "is not scheduled (want a number of minutes in [%d, %d]); logged once per value",
                raw, TZ_MIN, TZ_MAX)


def interval_due(every: int | float, last_fired: datetime | None, now: datetime,
                 poked: bool) -> bool:
    if last_fired is None:
        return True
    age = (now - last_fired).total_seconds()
    return age >= every or (poked and age >= min(every, POKE_FLOOR_S))


def _slot_targets(now: datetime, times: Iterable, tz_offset_minutes: int) -> list[datetime]:
    off = timedelta(minutes=tz_offset_minutes)
    out: list[datetime] = []
    for raw in times:
        if not isinstance(raw, str) or ":" not in raw:
            continue
        try:
            hh, mm = (int(x) for x in raw.split(":", 1))
        except ValueError:
            continue
        if not (0 <= hh < 24 and 0 <= mm < 60):
            continue
        local_today = (now + off).replace(hour=hh, minute=mm, second=0, microsecond=0)
        out.append(local_today - off)
    return out


def _owed(target_utc: datetime, now: datetime, last_job_at: datetime | None) -> bool:
    return now >= target_utc and (last_job_at is None or last_job_at < target_utc)


# last_job_at is the rule's OWN last enqueue: anchoring on the kind's last run let a manual run mark the slot done and starve the rule.
def clock_due(
    now: datetime, times: Iterable, tz_offset_minutes: int, last_job_at: datetime | None
) -> bool:
    return any(_owed(t, now, last_job_at) for t in _slot_targets(now, times, tz_offset_minutes))


def next_due(trig: Trigger, last_fired: datetime | None, now: datetime, *,
             run_count: int | None = None) -> datetime | None:
    if trig.max_runs is not None:
        if run_count is None:
            raise ValueError("next_due: run_count is required when max_runs is set")
        if run_count >= trig.max_runs:
            return None
    match trig:
        case Interval(every=every):
            return now if last_fired is None else last_fired + timedelta(seconds=every)
        case Clock(times=times, tz_off_min=off):
            today = _slot_targets(now, times, off)
            owed = [t for t in today if _owed(t, now, last_fired)]
            if owed:
                return min(owed)
            later = [t for t in today if t > now] + [t + timedelta(days=1) for t in today]
            return min(later) if later else None
        case _:
            assert_never(trig)


# tz_off_min is from the one clock (rhythm.tz_offset_for), in minutes so Kolkata +5:30 lands right.
# None = account has no clock: the band does not apply (never invent UTC).
def in_quiet_hours(quiet_hours_json: str | None, tz_off_min: int | None,
                   now: datetime) -> bool:
    if not quiet_hours_json:
        return False
    try:
        qh = json.loads(quiet_hours_json)
    except Exception:
        return False
    if isinstance(qh, dict):
        qh = [qh.get("start"), qh.get("end")]
    if not isinstance(qh, (list, tuple)) or len(qh) != 2:
        return False
    try:
        start, end = int(qh[0]), int(qh[1])
    except (TypeError, ValueError):
        return False
    if start == end:
        return False
    if tz_off_min is None:
        return False
    hour = ((now.hour * 60 + now.minute + int(tz_off_min)) // 60) % 24
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


Busy = Literal["pending", "running"]


@dataclass(frozen=True)
class Enqueue:
    no_clock: bool


@dataclass(frozen=True)
class Skip:
    reason: Literal["busy", "not_due", "quiet_hours"]


@dataclass(frozen=True)
class Repoke:
    pass


@dataclass(frozen=True)
class Disable:
    runs: int
    limit: int


@dataclass(frozen=True)
class CheckQuiet:
    band: str


RulePlan = Union[Enqueue, Skip, Repoke, Disable, CheckQuiet]
QuietPlan = Union[Enqueue, Skip]


def plan_rule(trig: Trigger, *, busy: Busy | None, poked: bool, last_fired: datetime | None,
              run_count: int | None, quiet_hours_json: str | None, now: datetime,
              kind: str) -> RulePlan:
    if busy is not None:
        return Repoke() if busy == "running" and poked and kind in REPOKE_KINDS else Skip("busy")
    if trig.max_runs is not None:
        if run_count is None:
            raise ValueError("plan_rule: run_count is required when max_runs is set")
        if run_count >= trig.max_runs:
            return Disable(run_count, trig.max_runs)
    match trig:
        case Interval(every=every):
            due = interval_due(every, last_fired, now, poked)
        case Clock(times=times, tz_off_min=off):
            due = clock_due(now, times, off, last_fired)
        case _:
            assert_never(trig)
    if not due:
        keep = poked and isinstance(trig, Interval) and kind in REPOKE_KINDS
        return Repoke() if keep else Skip("not_due")
    if quiet_hours_json:
        return CheckQuiet(quiet_hours_json)
    return Enqueue(no_clock=False)


def quiet_plan(band: str, tz_off_min: int | None, now: datetime) -> QuietPlan:
    if in_quiet_hours(band, tz_off_min, now):
        return Skip("quiet_hours")
    return Enqueue(no_clock=tz_off_min is None)


class Pair(NamedTuple):
    account_id: str
    kind: str
    operator: bool
    due_at: float = 0.0
    fan: int | None = None


@dataclass(frozen=True)
class Spawn:
    account_id: str
    kind: str
    operator: bool
    bulk: bool
    fan: int | None = None


def run_key(account_id: str, kind: str, fan: int | None, per_fan: AbstractSet[str] | Mapping[str, int]) -> tuple:
    return (account_id, kind, fan) if kind in per_fan else (account_id, kind)


# Bulk pairs go by oldest due job: last_served is process-local and a restart would repeat account-id order.
# Per-fan pairs round-robin by place in their account, so one Creator's Fans never fill the run slots.
def plan_dispatch(pairs: Iterable[Pair], inflight: AbstractSet[tuple],
                  last_served: Mapping[str, float], rank: Callable[[str], int],
                  bulk_kinds: AbstractSet[str], per_fan: Mapping[str, int] | None = None) -> list[Spawn]:
    per_fan = per_fan or {}
    pairs = list(pairs)
    taken = set(inflight)
    running = collections.Counter(k[:2] for k in taken if k[1] in per_fan)
    place: dict[tuple, int] = {}
    queued = running.copy()
    for p in sorted((p for p in pairs if p.kind in per_fan),
                    key=lambda p: (p.due_at, -1 if p.fan is None else p.fan)):
        rk = run_key(p.account_id, p.kind, p.fan, per_fan)
        if rk not in place and rk not in taken:
            place[rk] = queued[rk[:2]]
            queued[rk[:2]] += 1

    def key(p: Pair):
        bulk = p.kind in bulk_kinds
        return (not p.operator, place.get(run_key(p.account_id, p.kind, p.fan, per_fan), 0),
                rank(p.kind), bulk, p.due_at if bulk else last_served.get(p.account_id, 0.0),
                p.account_id, p.due_at if p.kind in per_fan else 0.0)
    order = sorted(pairs, key=key)
    out: list[Spawn] = []
    for p in order:
        rk = run_key(p.account_id, p.kind, p.fan, per_fan)
        if rk in taken:
            continue
        if p.kind in per_fan:
            if running[rk[:2]] >= per_fan[p.kind]:
                continue
            running[rk[:2]] += 1
        taken.add(rk)
        out.append(Spawn(p.account_id, p.kind, p.operator, p.kind in bulk_kinds, p.fan))
    return out
