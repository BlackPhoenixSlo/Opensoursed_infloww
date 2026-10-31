"""service/automations/funnel_decide.py — reply_mass_funnel's per-fan funnel status
machine as ONE pure transition (docs/reducer-scan.md, Non-React #9):

    decide(entry, ev, script) -> (entry', effects)

No I/O and no service imports beyond the pure `_funnel_routing` (keyword/bought/
ignored/default precedence), so it loads and tests without a DB. reply_mass_funnel.run()
is the shell: it gathers the facts, builds the event, calls decide() and performs the
effects in the order given. Every status rule of the walk lives here and nowhere else,
the purchase baseline of the `bought` fact too (`offer_since`).

A fan's funnel_state: `pending` on step `current_step` (an INDEX into the script),
polled at `next_check_at`, until `done` (`last_error` says why when it is not the
plain end of the script: `offer_taken`, `loop_guard`; `blocked:<why>` marks a step
that could not be sent and stays pending).

Events (what run() saw, in the order it sees them for one due fan):
  Due(now)                  picked up; before the audience/cooldown/lease gates
  Checked(now, facts)       the lease is his; `facts` = replied / bought /
                            substantive / reply_text since our last funnel message
  Blocked(now, problems)    the pre-send guard refused the step's texts
  Unreachable(now)          the send raised a permanent (deleted/blocked) error
  Sent(now, facts)          the step went out (OF returned it, all or part)

Effects (what run() does, in list order; run() counts each by value):
  Save()       persist entry' (run()'s `_save`: a dry run persists nothing)
  Complete()   the walk ended (`completed`)
  Convert()    the fan bought, no `next.bought` route: handed to chatters (`converted`)
  Branch()     re-routed by the step's `next` map, no send (`branched`)
  Wait()       no reply yet: rescheduled on the interval list (`waiting`)
  Block()      the step's texts were refused: backed off, still pending (`blocked`)
  Generate()   he replied: compose and send step `current_step` (run() feeds
               Blocked / Unreachable / Sent back in)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ._funnel_routing import resolve_next

DEFAULT_INTERVALS = [2, 4, 10]  # minutes between reply-checks (spec default)
FALLBACK_CHECK_MIN = 10         # after the interval list is exhausted, re-poll forever


# ── State ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entry:
    """The state-machine columns of one funnel_state row. Never mutated: decide()
    returns a new one; run() copies it back onto the row object it saves."""
    current_step: int = 0
    next_check_at: datetime | None = None
    check_count: int = 0
    status: str = "pending"
    last_error: str | None = None
    last_ppv_sent_at: datetime | None = None
    hops: int | None = 0
    # INDEX of the step last sent: its `check_intervals_min` paces the reply-wait,
    # also after a `next` jump. None (a row from before the column) = c - 1.
    last_sent_step: int | None = None

    @classmethod
    def from_row(cls, row) -> "Entry":
        """From a FunnelState row (duck-typed: no ORM import)."""
        return cls(current_step=row.current_step, next_check_at=row.next_check_at,
                   check_count=row.check_count, status=row.status,
                   last_error=row.last_error, last_ppv_sent_at=row.last_ppv_sent_at,
                   hops=row.hops, last_sent_step=row.last_sent_step)


@dataclass(frozen=True)
class Script:
    """The funnel being walked: its steps (in order), each step NUMBER's index (the
    `next` targets are numbers) and the loop guard's hop cap."""
    steps: list
    num_to_idx: dict
    max_hops: int


@dataclass(frozen=True)
class Facts:
    replied: bool = False
    bought: bool = False
    substantive: bool = False
    reply_text: str | None = None


# ── Events ────────────────────────────────────────────────────────────

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


# ── Effects ───────────────────────────────────────────────────────────

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


# ── Schedule ──────────────────────────────────────────────────────────

def step_intervals(steps: list[dict], idx: int) -> list[int]:
    """The `check_intervals_min` of the step at `idx` (the one we just sent), or
    the spec default [2,4,10] when missing/malformed."""
    if 0 <= idx < len(steps):
        iv = steps[idx].get("check_intervals_min")
        if isinstance(iv, list) and iv and all(isinstance(x, (int, float)) for x in iv):
            return [int(x) for x in iv]
    return list(DEFAULT_INTERVALS)


def sent_step_intervals(e: Entry, steps: list[dict]) -> list[int]:
    """The interval list the reply-wait walks: the step last SENT (after a `next`
    jump that is not c - 1); a legacy row (None) keeps the old c - 1 rule."""
    idx = e.last_sent_step if e.last_sent_step is not None else max(e.current_step - 1, 0)
    return step_intervals(steps, idx)


def offer_since(e: Entry, started_at: datetime | None) -> datetime | None:
    """Since when a PPV unlock counts as "offer taken" (the `bought` fact): our own
    last funnel PPV, else the broadcast; None (no baseline) means run() reads no
    purchase at all."""
    return e.last_ppv_sent_at or started_at


def wait_minutes(intervals: list[int], check_count: int) -> int:
    """Minutes until the next reply-check: intervals[check_count], then the
    10-minute fallback once the list is exhausted (spec: re-poll forever)."""
    if 0 <= check_count < len(intervals):
        return int(intervals[check_count])
    return FALLBACK_CHECK_MIN


def _route(e: Entry, tgt: int, n_steps: int, now: datetime, *,
           wait_min: int, guard: bool, max_hops: int) -> Entry:
    """Move to step INDEX `tgt`, (re)scheduled in `wait_min` minutes. When `guard`
    (the step carried a `next` map, which may point backward) the hop counter
    bumps first and the walk HALTS `done/loop_guard` at `max_hops` instead of
    routing. A hop off the end of the script ends the walk `done`."""
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
    """Take the step's `next` route IMMEDIATELY (no reply-wait), guard armed: the
    buyer (`next.bought`) and the non-replier whose window is spent (`next.ignored`)."""
    e = _route(e, resolve_next(step, facts, s.num_to_idx, c), len(s.steps), now,
               wait_min=0, guard=True, max_hops=s.max_hops)
    return e, [Save(), *([Complete()] if e.status == "done" else []), Branch()]


# ── Send shape (pure: what run() hands OF for a Generate) ─────────────

DEFAULT_PPV_PRICE = 24   # spec default for a paid_ppv step with no (or a bad) price


def step_number(step: dict) -> int | None:
    """The step's declared NUMBER (the outbound row's `funnel_step`), or None."""
    try:
        return int(step.get("step"))
    except (TypeError, ValueError):
        return None


def ppv_send_kwargs(step: dict, media: list[int], previews: list[int]) -> dict:
    """The OF send kwargs for a paid_ppv step's FIRST line: the step's price
    (DEFAULT_PPV_PRICE when absent or not a number) and the per-account vault
    `media`, its leading `previews` sent unlocked (clamped to `media`). The TEXT
    is the pitch and stays readable (`locked_text` False) unless the step opts in
    with `"locked_text": true`; only the media is paywalled."""
    price = step.get("price")
    try:
        price = int(price) if price is not None else DEFAULT_PPV_PRICE
    except (TypeError, ValueError):
        price = DEFAULT_PPV_PRICE
    kw: dict = {"price": price, "locked_text": bool(step.get("locked_text", False))}
    if media:
        kw["media_files"] = list(media)
        pv = [m for m in previews if m in media]
        if pv:
            kw["previews"] = pv
    return kw


# ── The transition ────────────────────────────────────────────────────

def decide(e: Entry, ev: Event, s: Script) -> tuple[Entry, list[Effect]]:
    now = ev.now
    c = e.current_step

    # Past the script's end (a shortened funnel), whatever the event: done. Due
    # is this guard alone, before run() reads any facts.
    if c >= len(s.steps):
        return replace(e, status="done"), [Save(), Complete()]
    if isinstance(ev, Due):
        return e, []              # go on: the gates, then the facts

    if isinstance(ev, Blocked):
        # A broken step won't fix itself per tick: back off to the fallback poll,
        # stay pending so an operator's media/copy fix resumes it.
        return replace(e, last_error="blocked:" + ",".join(ev.problems),
                       check_count=e.check_count + 1,
                       next_check_at=now + timedelta(minutes=FALLBACK_CHECK_MIN)
                       ), [Save(), Block()]

    if isinstance(ev, Unreachable):
        # Permanent: ended, or it stays due forever regenerating the step.
        return replace(e, status="done"), [Save(), Complete()]

    step = s.steps[c]
    is_ppv = step.get("type") == "paid_ppv"
    branch = step.get("next") if isinstance(step.get("next"), dict) else None

    if isinstance(ev, Sent):
        e = replace(e, last_sent_step=c)
        if is_ppv:
            # Our own offer's time: the baseline of the next tick's "offer taken".
            e = replace(e, last_ppv_sent_at=now)
        if is_ppv and branch is None:
            # A paid_ppv step with no routing is terminal: hand off to chatters.
            return replace(e, current_step=c + 1, status="done"), [Save(), Complete()]
        # The step just sent (index c) picks the next one; no `next` map is the
        # linear c + 1. The first reply-check lands at its intervals[0].
        e = _route(e, resolve_next(step, ev.facts, s.num_to_idx, c), len(s.steps),
                   now, wait_min=wait_minutes(step_intervals(s.steps, c), 0),
                   guard=branch is not None, max_hops=s.max_hops)
        return e, [Save(), *([Complete()] if e.status == "done" else [])]

    # Checked. Offer taken (a PPV unlocked since the baseline) beats the reply
    # gate, so a SILENT buyer also stops the nudges.
    f = ev.facts
    if f.bought:
        if branch is not None and branch.get("bought") is not None:
            # Stamp the purchase's baseline so it can't re-fire the branch.
            return _branch_now(replace(e, last_ppv_sent_at=now), step, f, c, s, now)
        return replace(e, status="done", last_error="offer_taken"), [Save(), Convert()]

    if not f.replied:
        # `check_count` = checks made since the last send, whose own schedule
        # was intervals[0]; this miss moves on to intervals[check_count + 1]
        # (for [2,4,10]: +2, +6, +16 after the send, then every fallback).
        intervals = sent_step_intervals(e, s.steps)
        # `next.ignored` fires only once the window is spent: the check at the
        # end of the last interval found no reply.
        if (branch is not None and branch.get("ignored") is not None
                and e.check_count >= len(intervals) - 1):
            return _branch_now(e, step, f, c, s, now)
        n = e.check_count + 1
        return replace(e, check_count=n,
                       next_check_at=now + timedelta(minutes=wait_minutes(intervals, n))
                       ), [Save(), Wait()]

    return e, [Generate()]
