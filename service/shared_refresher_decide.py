from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, NamedTuple

import purchase_poll_decide as poll_decide

FLOOR_S = 60.0
SPREAD = 0.1


@dataclass(frozen=True, slots=True)
class Knobs:
    lease_cycle_s: float = 120.0
    tab_cycle_s: float = 600.0


@dataclass(frozen=True, slots=True)
class Inputs:
    now: float
    tracked: frozenset[str]
    readable: frozenset[str] = frozenset()
    warm_pending: frozenset[str] = frozenset()
    in_flight: frozenset[str] = frozenset()
    leased: frozenset[str] = frozenset()
    ws_since: Mapping[str, float | None] = field(default_factory=dict)
    dead: frozenset[str] = frozenset()
    values: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class State:
    last: Mapping[str, float] = field(default_factory=dict)
    held: Mapping[str, float] = field(default_factory=dict)
    step: Mapping[str, int] = field(default_factory=dict)
    first_seen: Mapping[str, float] = field(default_factory=dict)
    shown: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    live_since: Mapping[str, float] = field(default_factory=dict)


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


def window_due(window_at: float | None, ws_since: float | None, asked: bool, first: bool) -> bool:
    if window_at is None:
        return asked and first
    return ws_since is None or ws_since > window_at or asked


def _readable(aid: str, inputs: Inputs) -> bool:
    return aid in inputs.readable and aid not in inputs.dead


def view(aid: str, inputs: Inputs, knobs: Knobs) -> dict[str, Any]:
    readable = _readable(aid, inputs)
    c = cycle_s(aid in inputs.leased, aid, knobs) if readable else None
    return {"cycle_s": c, "live": live_of(aid, inputs.ws_since, inputs.dead, readable),
            "values": dict(inputs.values.get(aid) or {})}


def _compared(v: Mapping[str, Any]) -> tuple:
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
        last = max(asked, state.last.get(aid, asked))
        return replace(state, last={**state.last, aid: last}, held=held, step=step)
    step[aid] = step.get(aid, 0) + 1
    held[aid] = asked + max(FLOOR_S, poll_decide.ladder_s(step[aid]))
    return replace(state, held=held, step=step)
