"""
The Shared refresher's scheduling decision (docs/spec/watched-creator-refresher/phase-01-shared-refresher.md,
"Interfaces"): pure (stdlib and purchase_poll_decide's ladder), no clock, no I/O. Its shell is shared_refresher.py; tables in
tests/test_shared_refresher_decide.py.

  cycle_s(leased, aid, knobs) -> float: the Creator's Cycle, its own period `max(FLOOR_S, tier x (1 - SPREAD x
      h(aid)))`: 0.9-1.0 x its tier, stable per Creator, so slots drift apart. Tier = the lease cycle when it holds a
      View lease, else the tab cycle; both clamped to FLOOR_S, the tab cycle never below the lease cycle. A lease gain
      or loss changes it, so the view changes and the Creator is published.
  h(aid) -> float in [0, 1): a stable per-Creator hash.
  due_at(last, cycle, aid, first_seen): `last + cycle`; never read (`last` None): `first_seen + h(aid) x FLOOR_S`, so
      a restart's (or a new tab's) first reads spread over the first minute.
  plan(state, inputs, knobs) -> (state', effects): per tracked Creator, `Publish(aid)` when it entered `tracked` or
      its published view changed, and `Read(aid)` when it is readable, not in flight, not warm-pending, not held and
      `now >= due_at(...)`. One Read per Creator whatever the subscriber count (`tracked` is a set). A Creator leaving
      `tracked` keeps its Last refresh: re-entering publishes once and reads at its slot, no burst.
  after_read(state, aid, ok, asked) -> state': ok (landed, write-back kept) writes Last refresh = `asked` (the read's
      ask time) and clears the ladder; a failure (a 429 or any other, or a discarded write-back) keeps it and holds
      the Creator `max(FLOOR_S, purchase_poll_decide.ladder_s(n))` from `asked`, n = failures in a row (60, 60, 120 ..
      900 s), so attempts are never under FLOOR_S apart. A 429's asked wait holds the exit, not here (the shell).
  window_due(window_at, ws_since, asked) -> bool: the Cycle re-reads the chats window (asked after `/users/me`
      landed): the Live connection is down now (`ws_since` None), or connected after the window's own last read
      (`window_at`, the same monotonic clock; connected at the read itself is kept, as roster-counts' `ws_kept`), or
      a contributor asked. No window held (`window_at` None) is never due: an open reads page 0 itself.
  live_of(aid, ws_since, dead, pumped) -> "up" | "down" | "dead" | None (P1 Contract 2): "dead" while in the
      Dead-session map; None when no OF socket is expected (`pumped` False: deactivated, no session, not OF), never
      "down"; else "up" while the Live connection's stamp is set, "down" when not.
  view / changed: the published part of a Creator's snapshot ({cycle_s, live, values}; `cycle_s` None when not
      readable; `values` = `inputs.values[aid]`, the contributors' slots) and whether it moved (P1 Contract 3:
      `cycle_s`, `live` or a slot compared without its own `at`; `at` alone is no change). A `live` flip is a
      change: published with no Read. `State.live_since` (the `now` the tick first saw `live` take its current
      value; absent while `live` is None) restarts on each change.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, NamedTuple

import purchase_poll_decide as poll_decide

FLOOR_S = 60.0          # no Creator is read more often than this, whatever the Knobs say
SPREAD = 0.1            # a Creator's Cycle is (1 - SPREAD x h) x its tier


@dataclass(frozen=True, slots=True)
class Knobs:
    lease_cycle_s: float = 120.0    # SHARED_REFRESHER_LEASE_CYCLE_S
    tab_cycle_s: float = 600.0      # SHARED_REFRESHER_TAB_CYCLE_S


@dataclass(frozen=True, slots=True)
class Inputs:
    now: float                                       # monotonic, the clock of `last`
    tracked: frozenset[str]                          # Open-tab Creators (events.open_tab_accounts)
    readable: frozenset[str] = frozenset()           # tracked ∩ live (transaction_ingest.live_account_ids), OF only
    warm_pending: frozenset[str] = frozenset()       # app_open_warm.pending
    in_flight: frozenset[str] = frozenset()          # a refresher job reading now
    leased: frozenset[str] = frozenset()             # holding a View lease (view_lease.leased_ids): the lease tier
    ws_since: Mapping[str, float | None] = field(default_factory=dict)  # of_ws.connected_since; None/absent: down
    dead: frozenset[str] = frozenset()               # in the Dead-session map (account_health.dead_session_map)
    values: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # Creator -> {name: contributor snapshot}


@dataclass(frozen=True, slots=True)
class State:
    last: Mapping[str, float] = field(default_factory=dict)        # Last refresh (monotonic), kept across untrack
    held: Mapping[str, float] = field(default_factory=dict)        # no attempt before this (a failed one)
    step: Mapping[str, int] = field(default_factory=dict)          # failures in a row: the Backoff ladder's rung
    first_seen: Mapping[str, float] = field(default_factory=dict)  # tracked Creators: when this stint began
    shown: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # tracked Creators: last published view
    live_since: Mapping[str, float] = field(default_factory=dict)  # tracked, `live` not None: when it took its value


class Read(NamedTuple):
    account_id: str


class Publish(NamedTuple):
    account_id: str


def h(aid: str) -> float:
    return zlib.crc32(str(aid).encode()) / 2 ** 32


def cycle_s(leased: bool, aid: str, knobs: Knobs) -> float:
    lease = max(FLOOR_S, knobs.lease_cycle_s)
    tier = lease if leased else max(lease, knobs.tab_cycle_s)
    return max(FLOOR_S, tier * (1.0 - SPREAD * h(aid)))


def due_at(last: float | None, cycle: float, aid: str, first_seen: float) -> float:
    return first_seen + h(aid) * FLOOR_S if last is None else last + cycle


def live_of(aid: str, ws_since: Mapping[str, float | None], dead: frozenset[str], pumped: bool) -> str | None:
    if aid in dead:
        return "dead"
    if not pumped:
        return None
    return "up" if ws_since.get(aid) is not None else "down"


def window_due(window_at: float | None, ws_since: float | None, asked: bool) -> bool:
    if window_at is None:
        return False                    # no window held: an open reads page 0 itself (a cache miss, as today)
    return ws_since is None or ws_since > window_at or asked


def _readable(aid: str, inputs: Inputs) -> bool:
    return aid in inputs.readable and aid not in inputs.dead      # a Dead session is never read, whatever raced


def view(aid: str, inputs: Inputs, knobs: Knobs) -> dict[str, Any]:
    readable = _readable(aid, inputs)
    c = cycle_s(aid in inputs.leased, aid, knobs) if readable else None
    return {"cycle_s": c, "live": live_of(aid, inputs.ws_since, inputs.dead, readable),
            "values": dict(inputs.values.get(aid) or {})}


def _compared(v: Mapping[str, Any]) -> tuple:
    """What `changed` compares: `cycle_s`, `live` and each slot without its own `at` (never the snapshot's `at`)."""
    slots = {k: {f: x for f, x in s.items() if f != "at"} if isinstance(s, Mapping) else s
             for k, s in (v.get("values") or {}).items()}
    return v.get("cycle_s"), v.get("live"), slots


def changed(prev: Mapping[str, Any] | None, nxt: Mapping[str, Any]) -> bool:
    return prev is None or _compared(prev) != _compared(nxt)


def plan(state: State, inputs: Inputs, knobs: Knobs) -> tuple[State, list[Read | Publish]]:
    first_seen = {a: t for a, t in state.first_seen.items() if a in inputs.tracked}
    shown = {a: v for a, v in state.shown.items() if a in inputs.tracked}
    live_since = {a: t for a, t in state.live_since.items() if a in inputs.tracked}
    effects: list[Read | Publish] = []
    for aid in sorted(inputs.tracked):
        first_seen.setdefault(aid, inputs.now)
        v = view(aid, inputs, knobs)
        prev = shown.get(aid)
        if prev is None or prev["live"] != v["live"]:
            live_since.pop(aid, None)
            if v["live"] is not None:
                live_since[aid] = inputs.now
        if changed(prev, v):
            shown[aid] = v
            effects.append(Publish(aid))
        if (_readable(aid, inputs) and aid not in inputs.in_flight and aid not in inputs.warm_pending
                and inputs.now >= state.held.get(aid, float("-inf"))
                and inputs.now >= due_at(state.last.get(aid), v["cycle_s"], aid, first_seen[aid])):
            effects.append(Read(aid))
    return replace(state, first_seen=first_seen, shown=shown, live_since=live_since), effects


def after_read(state: State, aid: str, ok: bool, asked: float) -> State:
    held, step = dict(state.held), dict(state.step)
    if ok:
        held.pop(aid, None)
        step.pop(aid, None)
        last = max(asked, state.last.get(aid, asked))   # never back: a warm's newer note_refresh stays
        return replace(state, last={**state.last, aid: last}, held=held, step=step)
    step[aid] = step.get(aid, 0) + 1
    held[aid] = asked + max(FLOOR_S, poll_decide.ladder_s(step[aid]))
    return replace(state, held=held, step=step)
