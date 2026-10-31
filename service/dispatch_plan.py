"""
The automation dispatch rules as pure functions (docs/reducer-scan.md "Non-React" 8). No DB,
no loop, no clock: automation_executor reads the facts and calls these.

    trigger_of(trigger) -> Interval | Clock | None     what a rule fires on (pure, quiet)
    parse_trigger(trigger) -> the same, for the materializer (logs a bad zone once)
    tz_offset(raw) -> int | None                        a stored tz_offset_minutes, None = bad
    interval_due(every, last_fired, now, poked) -> bool
    clock_due(now, times, tz_offset_minutes, last_job_at) -> bool
    next_due(trig, last_fired, now, run_count=) -> datetime | None  when it next fires
    in_quiet_hours(quiet_hours_json, tz_off_min, now) -> bool
    plan_rule(trig, busy=, poked=, last_fired=, run_count=, quiet_hours_json=, now=)
        -> Enqueue | Skip | Repoke | Disable | CheckQuiet
    quiet_plan(band, tz_off_min, now) -> Enqueue | Skip
    plan_dispatch(pairs, inflight, last_served, rank, bulk_kinds) -> [Spawn]

plan_rule is the materializer's (`_materialize_due_rules`) gates for one rule, in their order
(busy, run limit, due), over the facts the shell read (the one-job-per-(account, kind) gate's
status is a DB read there). A due rule with a quiet band comes back as CheckQuiet: only then
does the shell read the account's clock, and quiet_plan is the last gate. The helpers above
are their due / quiet-hours rules.
plan_dispatch is the supervisor pass's spawn order. Importable without side effects (stdlib only).
next_due is the same due math as one instant, for the rules API's `next_due_at` (one voice:
the shown next fire is when plan_rule's due gate turns true).
Not all pure, said plainly: parse_trigger (the materializer's) logs a bad `tz_offset_minutes`
once per distinct raw value, kept in a module-level set; trigger_of is its quiet, pure twin.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AbstractSet, Callable, Iterable, Literal, Mapping, NamedTuple, Union, assert_never

log = logging.getLogger("of-relay.automation.dispatch_plan")

# A poke fires an interval rule only once its last job is at least min(every_seconds,
# POKE_FLOOR_S) old (automation_executor.poke_rule has the why).
POKE_FLOOR_S = 60


def _positive_number(v) -> bool:
    """A finite number > 0 (not a bool): a stored Infinity / 1e400 / NaN is not one, so int()
    of it can never raise OverflowError here."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


@dataclass(frozen=True)
class Interval:
    every: int | float               # `every_seconds` (> 0)
    max_runs: int | None             # int(`max_runs`) when > 0: disable once the pair ran that often


@dataclass(frozen=True)
class Clock:
    times: tuple                     # the non-empty `daily_at` list ("HH:MM", creator-local)
    tz_off_min: int                  # int(`tz_offset_minutes`), 0 when absent: the slots' zone
    max_runs: int | None


Trigger = Union[Interval, Clock]

# `tz_offset_minutes`' range (UTC-12..UTC+14): automation_rules_api._validate_trigger 422s
# outside it, and a stored value outside it is bad here (tz_offset).
TZ_MIN, TZ_MAX = -720, 840


def tz_offset(raw) -> int | None:
    """A stored `tz_offset_minutes` -> int minutes, or None when it is bad. Absent / null is 0
    (UTC), the API's default. Good: a number (not a bool) in [TZ_MIN, TZ_MAX], truncated to
    int as the API stores it. Bad: anything else ("x", "", "60", "1.5", True, NaN, 9999),
    each of which the API 422s, so only a hand-edited or raw-SQL row can hold one."""
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not TZ_MIN <= raw <= TZ_MAX:
        return None
    return int(raw)


@dataclass(frozen=True)
class _BadTz:
    raw: object                      # a clock trigger's bad `tz_offset_minutes`, as stored


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
    """A rule's decoded `trigger_json` -> what it fires on: an interval wins over a clock;
    None when neither (nothing to do), or a clock whose `tz_offset_minutes` is bad
    (tz_offset): its slots have no zone, so it is never guessed at UTC. Pure and quiet:
    the read for a display (the rules API's next_due_at)."""
    t = _read(trigger)
    return None if isinstance(t, _BadTz) else t


def parse_trigger(trigger: dict) -> Trigger | None:
    """trigger_of for the materializer, which skips a None: a bad `tz_offset_minutes` never
    raises out of its pass (one bad row would stop every rule), it goes to `_bad_tz`."""
    t = _read(trigger)
    if isinstance(t, _BadTz):
        _bad_tz(t.raw)
        return None
    return t


_BAD_TZ_WARNED: set[str] = set()     # repr of each bad raw value already logged


def _bad_tz(raw) -> None:
    """The materializer's side of a clock rule with a bad zone: one warning per distinct raw
    value per process (the pass runs every 30 s; the rule id is the caller's, not known here)."""
    if repr(raw) in _BAD_TZ_WARNED:
        return
    _BAD_TZ_WARNED.add(repr(raw))
    log.warning("automation_rule_bad_tz_offset raw=%r: a clock rule with this tz_offset_minutes "
                "is not scheduled (want a number of minutes in [%d, %d]); logged once per value",
                raw, TZ_MIN, TZ_MAX)


def interval_due(every: int | float, last_fired: datetime | None, now: datetime,
                 poked: bool) -> bool:
    """An interval rule is due once its own last job (`last_fired`, the cadence anchor) is
    `every` seconds old, or never fired. A poke only shortens the wait down to
    min(every, POKE_FLOOR_S); one landing sooner is spent and the cadence picks it up."""
    if last_fired is None:
        return True
    age = (now - last_fired).total_seconds()
    return age >= every or (poked and age >= min(every, POKE_FLOOR_S))


def _slot_targets(now: datetime, times: Iterable, tz_offset_minutes: int) -> list[datetime]:
    """Today's (creator-local day) target of each valid "HH:MM" in `times`, as a UTC instant
    (target_utc = local - offset). Malformed or out-of-range entries are dropped."""
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
        # today's local target, as a UTC instant
        local_today = (now + off).replace(hour=hh, minute=mm, second=0, microsecond=0)
        out.append(local_today - off)
    return out


def _owed(target_utc: datetime, now: datetime, last_job_at: datetime | None) -> bool:
    """A slot is owed once its target has passed and this rule has not enqueued since."""
    return now >= target_utc and (last_job_at is None or last_job_at < target_utc)


def clock_due(
    now: datetime, times: Iterable, tz_offset_minutes: int, last_job_at: datetime | None
) -> bool:
    """Clock-time ("cron") trigger: given `times` like ["09:00","20:30"] expressed
    in the user's local zone (`tz_offset_minutes` = minutes to add to UTC for
    local), is a slot DUE — i.e. its target instant today has passed AND THIS
    RULE hasn't already enqueued a job since then?

    `now`/`last_job_at` are UTC (datetime.utcnow). `last_job_at` is the rule's OWN
    last job-enqueue time (NOT the last run of the kind): anchoring on the kind's
    last *run* let a one-shot / manual run of the same kind mark today's slot
    "done" and starve the scheduled rule — the same footgun the interval path
    avoids. For each "HH:MM" we build today's local target, convert to UTC
    (target_utc = local - offset), and treat it as due when now ≥ target_utc and
    last_job_at < target_utc."""
    return any(_owed(t, now, last_job_at) for t in _slot_targets(now, times, tz_offset_minutes))


def next_due(trig: Trigger, last_fired: datetime | None, now: datetime, *,
             run_count: int | None = None) -> datetime | None:
    """When the rule next fires by its trigger: the instant plan_rule's due gate turns true
    (<= now: due now, on the next pass). Interval: `last_fired` + every, or `now` when it
    never fired (interval_due). Clock: the earliest slot still owed today (clock_due), else
    the next slot later today or tomorrow, in the trigger's offset. None: a clock with no
    valid slot, or `run_count` (the pair's runs, as plan_rule counts them) at or past
    `max_runs` (the next pass disables the rule). `run_count` is required when
    `trig.max_runs` is set (plan_rule's contract). Busy, pokes and quiet hours are not in
    it: an estimate for display."""
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


def in_quiet_hours(quiet_hours_json: str | None, tz_off_min: int | None,
                   now: datetime) -> bool:
    """Rule-level quiet hours. OPT-IN: a NULL/empty/malformed `quiet_hours_json`
    (every rule's default) returns False → the rule fires 24/7, unchanged. When set
    to `[start, end]` (creator-LOCAL hours, same convention as nudge_online), return
    True when the creator's local hour falls in the band so the materializer holds
    the job until the band ends. `start == end` disables it. The band [start, end)
    wraps midnight when start > end (e.g. [22, 6] = 10pm–6am).

    `tz_off_min` is the creator-local offset in MINUTES, resolved by the ONE clock
    (`rhythm.tz_offset_for`) like every other engine. It used to be the raw
    `utc_offset` COLUMN, read straight out of the row — a second clock, and for any
    account that also had an IANA zone it was a different one: quiet hours held (or
    released) jobs on the legacy number while every message the fan read used the
    zone. Minutes, not hours, so a half-hour zone (Kolkata +5:30) lands on the right
    hour instead of being truncated. None means the account has NO clock, and a
    creator-local band cannot be evaluated without one — so it does not apply, and
    the rule fires 24/7 (the caller warns once). Inventing UTC there is what the
    raw-column read did, and a server clock sold as hers is the bug, not the
    fallback. A `{"start": s, "end": e}` object form is accepted too, for the UI."""
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
    if start == end:                      # disabled (incl. [0, 0])
        return False
    if tz_off_min is None:                # no clock → no local band to be inside
        return False
    hour = ((now.hour * 60 + now.minute + int(tz_off_min)) // 60) % 24
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end     # wraps past midnight


# ── the materializer's gates for one rule ──
Busy = Literal["pending", "running"]


@dataclass(frozen=True)
class Enqueue:
    """Make the rule's job now. `no_clock`: it has a quiet band, but the account has no clock,
    so the band does not apply (the shell warns once per account)."""
    no_clock: bool


@dataclass(frozen=True)
class Skip:
    """Not this pass: a due job of the pair is open, the rule is not due, or it is due inside
    its quiet band (it materializes on the first pass after the band ends)."""
    reason: Literal["busy", "not_due", "quiet_hours"]


@dataclass(frozen=True)
class Repoke:
    """A poked pair's job is running: that run may predate the event, so keep the poke for
    the pass after it (and skip this one)."""


@dataclass(frozen=True)
class Disable:
    """The pair ran `runs` times, at or past the rule's `limit` (max_runs): turn the rule
    off; it stops cleanly."""
    runs: int
    limit: int


@dataclass(frozen=True)
class CheckQuiet:
    """Due, and the rule has a quiet band (`quiet_hours_json`): read the account's clock and
    let quiet_plan decide."""
    band: str


RulePlan = Union[Enqueue, Skip, Repoke, Disable, CheckQuiet]
QuietPlan = Union[Enqueue, Skip]


def plan_rule(trig: Trigger, *, busy: Busy | None, poked: bool, last_fired: datetime | None,
              run_count: int | None, quiet_hours_json: str | None, now: datetime) -> RulePlan:
    """One rule's step this pass. `busy`: the status of a due pending/running job of its
    (account, kind), or None; `poked`: an event poked the pair; `last_fired`: the rule's own
    last job (the cadence anchor); `run_count`: the pair's runs, required when
    `trig.max_runs` is set (None otherwise). Gate order: busy, run limit, due; then a set
    band is CheckQuiet, else Enqueue."""
    if busy is not None:
        return Repoke() if busy == "running" and poked else Skip("busy")
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
        return Skip("not_due")
    if quiet_hours_json:
        return CheckQuiet(quiet_hours_json)
    return Enqueue(no_clock=False)


def quiet_plan(band: str, tz_off_min: int | None, now: datetime) -> QuietPlan:
    """The last gate of a due rule with a band: hold it inside the band; else enqueue.
    `tz_off_min`: the creator-local offset, None = no clock (the band cannot apply, so the
    rule fires and Enqueue says no_clock)."""
    if in_quiet_hours(band, tz_off_min, now):
        return Skip("quiet_hours")
    return Enqueue(no_clock=tz_off_min is None)


# ── the supervisor pass ──
class Pair(NamedTuple):
    """A due (account, kind) of `_due_job_pairs`."""
    account_id: str
    kind: str
    operator: bool                  # an operator started one of its due jobs


@dataclass(frozen=True)
class Spawn:
    account_id: str
    kind: str
    operator: bool                  # the run takes the operator tier of the run slots
    bulk: bool                      # the run takes the bulk lane, not the senders'


def plan_dispatch(pairs: Iterable[Pair], inflight: AbstractSet[tuple[str, str]],
                  last_served: Mapping[str, float], rank: Callable[[str], int],
                  bulk_kinds: AbstractSet[str]) -> list[Spawn]:
    """The runs to spawn, in spawn order: operator runs first, then kind priority (`rank`),
    then the account served longest ago, account id breaking a tie. A pair already in
    flight is not spawned again (no stacking over a slow run). `bulk`: the bulk lane."""
    order = sorted(pairs, key=lambda p: (not p.operator, rank(p.kind),
                                         last_served.get(p.account_id, 0.0), p.account_id))
    taken = set(inflight)
    out: list[Spawn] = []
    for p in order:
        if (p.account_id, p.kind) in taken:
            continue
        taken.add((p.account_id, p.kind))
        out.append(Spawn(p.account_id, p.kind, p.operator, p.kind in bulk_kinds))
    return out
