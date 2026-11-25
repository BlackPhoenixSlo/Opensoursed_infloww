from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ._funnel_routing import resolve_next

DEFAULT_INTERVALS = [2, 4, 10]
FALLBACK_CHECK_MIN = 10



@dataclass(frozen=True)
class Entry:
    current_step: int = 0
    next_check_at: datetime | None = None
    check_count: int = 0
    status: str = "pending"
    last_error: str | None = None
    last_ppv_sent_at: datetime | None = None
    hops: int | None = 0
    last_sent_step: int | None = None
    confirmed_sent_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> "Entry":
        return cls(current_step=row.current_step, next_check_at=row.next_check_at,
                   check_count=row.check_count, status=row.status,
                   last_error=row.last_error, last_ppv_sent_at=row.last_ppv_sent_at,
                   hops=row.hops, last_sent_step=row.last_sent_step,
                   confirmed_sent_at=row.confirmed_sent_at)


@dataclass(frozen=True)
class Script:
    steps: list
    num_to_idx: dict
    max_hops: int


@dataclass(frozen=True)
class Facts:
    replied: bool = False
    bought: bool = False
    substantive: bool = False
    reply_text: str | None = None



@dataclass(frozen=True)
class Due:
    now: datetime


@dataclass(frozen=True)
class Checked:
    now: datetime
    facts: Facts


@dataclass(frozen=True)
class Blocked:
    now: datetime
    problems: tuple


@dataclass(frozen=True)
class Unreachable:
    now: datetime


@dataclass(frozen=True)
class Sent:
    now: datetime
    facts: Facts


Event = Due | Checked | Blocked | Unreachable | Sent



@dataclass(frozen=True)
class Save:
    pass


@dataclass(frozen=True)
class Complete:
    pass


@dataclass(frozen=True)
class Convert:
    pass


@dataclass(frozen=True)
class Branch:
    pass


@dataclass(frozen=True)
class Wait:
    pass


@dataclass(frozen=True)
class Block:
    pass


@dataclass(frozen=True)
class Generate:
    pass


Effect = Save | Complete | Convert | Branch | Wait | Block | Generate



def step_intervals(steps: list[dict], idx: int) -> list[int]:
    if 0 <= idx < len(steps):
        iv = steps[idx].get("check_intervals_min")
        if isinstance(iv, list) and iv and all(isinstance(x, (int, float)) for x in iv):
            return [int(x) for x in iv]
    return list(DEFAULT_INTERVALS)


def sent_step_intervals(e: Entry, steps: list[dict]) -> list[int]:
    idx = e.last_sent_step if e.last_sent_step is not None else max(e.current_step - 1, 0)
    return step_intervals(steps, idx)


def offer_since(e: Entry, started_at: datetime | None) -> datetime | None:
    return e.last_ppv_sent_at or started_at


def wait_minutes(intervals: list[int], check_count: int) -> int:
    if 0 <= check_count < len(intervals):
        return int(intervals[check_count])
    return FALLBACK_CHECK_MIN


def _route(e: Entry, tgt: int, n_steps: int, now: datetime, *,
           wait_min: int, guard: bool, max_hops: int) -> Entry:
    # A `next` map may point backward: count hops and halt at max_hops instead of looping.
    if guard:
        e = replace(e, hops=(e.hops or 0) + 1)
        if e.hops >= max_hops:
            return replace(e, status="done", last_error="loop_guard")
    if tgt >= n_steps:
        return replace(e, current_step=tgt, status="done")
    return replace(e, current_step=tgt, check_count=0,
                   next_check_at=now + timedelta(minutes=wait_min))


def _branch_now(e: Entry, step: dict, facts: Facts, c: int, s: Script,
                now: datetime) -> tuple[Entry, list[Effect]]:
    e = _route(e, resolve_next(step, facts, s.num_to_idx, c), len(s.steps), now,
               wait_min=0, guard=True, max_hops=s.max_hops)
    return e, [Save(), *([Complete()] if e.status == "done" else []), Branch()]



DEFAULT_PPV_PRICE = 24


def step_number(step: dict) -> int | None:
    try:
        return int(step.get("step"))
    except (TypeError, ValueError):
        return None


def ppv_send_kwargs(step: dict, media: list[int], previews: list[int]) -> dict:
    price = step.get("price")
    try:
        price = int(price) if price is not None else DEFAULT_PPV_PRICE
    except (TypeError, ValueError):
        price = DEFAULT_PPV_PRICE
    # The pitch text stays readable unless the step opts in; only the media is paywalled.
    kw: dict = {"price": price, "locked_text": bool(step.get("locked_text", False))}
    if media:
        kw["media_files"] = list(media)
        pv = [m for m in previews if m in media]
        if pv:
            kw["previews"] = pv
    return kw



def decide(e: Entry, ev: Event, s: Script) -> tuple[Entry, list[Effect]]:
    now = ev.now
    c = e.current_step

    if c >= len(s.steps):
        return replace(e, status="done"), [Save(), Complete()]
    if isinstance(ev, Due):
        return e, []

    # A broken step will not fix itself per tick: back off, stay pending so an operator's fix resumes it.
    if isinstance(ev, Blocked):
        return replace(e, last_error="blocked:" + ",".join(ev.problems),
                       check_count=e.check_count + 1,
                       next_check_at=now + timedelta(minutes=FALLBACK_CHECK_MIN)
                       ), [Save(), Block()]

    if isinstance(ev, Unreachable):
        return replace(e, status="done"), [Save(), Complete()]

    step = s.steps[c]
    is_ppv = step.get("type") == "paid_ppv"
    branch = step.get("next") if isinstance(step.get("next"), dict) else None

    if isinstance(ev, Sent):
        e = replace(e, last_sent_step=c)
        if is_ppv:
            e = replace(e, last_ppv_sent_at=now)
        if is_ppv and branch is None:
            return replace(e, current_step=c + 1, status="done"), [Save(), Complete()]
        e = _route(e, resolve_next(step, ev.facts, s.num_to_idx, c), len(s.steps),
                   now, wait_min=wait_minutes(step_intervals(s.steps, c), 0),
                   guard=branch is not None, max_hops=s.max_hops)
        return e, [Save(), *([Complete()] if e.status == "done" else [])]

    f = ev.facts
    # An offer taken beats the reply gate, so a silent buyer also stops the nudges.
    if f.bought:
        if branch is not None and branch.get("bought") is not None:
            return _branch_now(replace(e, last_ppv_sent_at=now), step, f, c, s, now)
        return replace(e, status="done", last_error="offer_taken"), [Save(), Convert()]

    if not f.replied:
        intervals = sent_step_intervals(e, s.steps)
        # `next.ignored` fires only once the window is spent: the last interval's check found no reply.
        if (branch is not None and branch.get("ignored") is not None
                and e.check_count >= len(intervals) - 1):
            return _branch_now(e, step, f, c, s, now)
        n = e.check_count + 1
        return replace(e, check_count=n,
                       next_check_at=now + timedelta(minutes=wait_minutes(intervals, n))
                       ), [Save(), Wait()]

    return e, [Generate()]
