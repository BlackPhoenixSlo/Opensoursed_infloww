from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import AbstractSet, Any, Iterable, Literal, Mapping, Union

import unread_total_decide as utd
from unread_total_decide import window_fan_id, _row_unread, created_ms, of_counts

DM_WINDOW_MS = 500
ECHO_WINDOW_MS = 1500
DECIDE_AFTER_MS = 1500
GAP_MS = {"full": 5000, "lean": 15000}
HOVER_COOLDOWN_MS = 30_000
INTENT_TAIL_MS = 1500
INTENT_MAX_MS = 5000
FRAME_LAG_MS = 1000


@dataclass(frozen=True)
class UnreadSet:
    at: int
    entries: dict[int, tuple[dict | None, int]] = field(default_factory=dict)
    gone: dict[int, int] = field(default_factory=dict)
    cut: int | None = None

    @property
    def fans(self) -> frozenset[int]:
        return frozenset(self.entries)

    @property
    def as_of(self) -> int:
        return max((self.at, self.cut or 0, *(t for _r, t in self.entries.values()), *self.gone.values()))


@dataclass(frozen=True)
class DmIn:
    fan: int
    at: int
    muted: bool


@dataclass(frozen=True)
class ReadDone:
    fan: int | None
    at: int
    landed: int | None = None


@dataclass(frozen=True)
class UnreadDone:
    fan: int
    at: int
    landed: int | None = None


@dataclass(frozen=True)
class Echo:
    fan: int
    at: int


SetEvent = Union[DmIn, ReadDone, UnreadDone, Echo]


@dataclass(frozen=True)
class Intent:
    id: int
    fan: int | None
    created: int
    responded: int | None = None
    retired: bool = False
    used: bool = False


@dataclass(frozen=True)
class Gate:
    in_flight: bool = False
    last_start: int | None = None
    pending: bool = False
    queue_next: bool = False


@dataclass(frozen=True)
class Start:
    queue: bool = False


@dataclass(frozen=True)
class Wait:
    until: int | None


def admit(gate: Gate, now: int, gap_ms: int, held_s: float, *,
          attribution: bool = True, queued: bool = False) -> tuple[Gate, Start | Wait]:
    pending = gate.pending or attribution
    if gate.in_flight:
        return replace(gate, pending=pending), Wait(None)
    if held_s > 0:
        return replace(gate, pending=pending), Wait(now + math.ceil(held_s * 1000))
    if gate.last_start is not None and now - gate.last_start < gap_ms:
        return replace(gate, pending=pending), Wait(gate.last_start + gap_ms)
    queue = queued and (gate.queue_next or not pending)
    return Gate(in_flight=True, last_start=now, pending=pending and queue,
                queue_next=queued and not queue), Start(queue)


# sent_at: gap counts from page 1's answer so OF never sees two starts closer than the gap.
def done(gate: Gate, sent_at: int | None = None) -> Gate:
    if sent_at is None or gate.last_start is None or sent_at <= gate.last_start:
        return replace(gate, in_flight=False)
    return replace(gate, in_flight=False, last_start=sent_at)


def intent_end(i: Intent) -> int:
    hard = i.created + INTENT_MAX_MS
    return hard if i.responded is None else min(hard, i.responded + INTENT_TAIL_MS)


def intent_live(i: Intent, at: int) -> bool:
    return not i.retired and not i.used and i.created <= at <= intent_end(i)


@dataclass(frozen=True)
class CounterFrame:
    at: int
    delta: int | None


@dataclass(frozen=True)
class Activity:
    at: int
    fan: int | None
    delta: int | None
    used: bool = False


def activity_explains(frame: CounterFrame, activity: Activity, window: int) -> bool:
    return (not activity.used and abs(frame.at - activity.at) <= window
            and (frame.delta is None or activity.delta is None or frame.delta == activity.delta))


def explain(frame: CounterFrame, dms: Iterable[Activity], echoes: Iterable[Activity],
            intents: Iterable[Intent]) -> tuple[bool, tuple[Activity, ...], tuple[Activity, ...], tuple[Intent, ...]]:
    dms, echoes, intents = tuple(dms), tuple(echoes), tuple(intents)
    held = [(a.delta is None, abs(frame.at - a.at), n, k)
            for n, (acts, window) in enumerate(((dms, DM_WINDOW_MS), (echoes, ECHO_WINDOW_MS)))
            for k, a in enumerate(acts) if activity_explains(frame, a, window)]
    if held:
        _unknown, _dt, n, k = min(held)
        acts = (dms, echoes)[n]
        spent = acts[:k] + (replace(acts[k], used=True),) + acts[k + 1:]
        return (True, spent, echoes, intents) if n == 0 else (True, dms, spent, intents)
    frame_at = frame.at
    live = [k for k, i in enumerate(intents) if intent_live(i, frame_at)]
    if not live:
        return False, dms, echoes, intents
    if any(intents[k].fan is None for k in live):
        return True, dms, echoes, intents
    k = min(live, key=lambda k: intents[k].created)
    return True, dms, echoes, intents[:k] + (replace(intents[k], used=True),) + intents[k + 1:]


def respond(intents: Iterable[Intent], intent_id: int, at: int) -> tuple[Intent, ...]:
    return tuple(replace(i, responded=at) if i.id == intent_id and i.responded is None and not i.retired else i
                 for i in intents)


def retire(intents: Iterable[Intent], intent_id: int) -> tuple[Intent, ...]:
    return tuple(replace(i, retired=True) if i.id == intent_id else i for i in intents)


def prune(intents: Iterable[Intent], now: int) -> tuple[Intent, ...]:
    return tuple(i for i in intents if not i.retired and not i.used and intent_end(i) + DECIDE_AFTER_MS >= now)


def prior_unread(held: UnreadSet | None, fan: int, row: dict | None) -> bool | None:
    if held is not None and fan in held.entries:
        return True
    if held is not None and fan in held.gone:
        return False
    return None if row is None else _row_unread(row)


def echo_prior(held: UnreadSet | None, fan: int, row: dict | None, replied: tuple[bool | None, int] | None,
               now: int) -> bool | None:
    if replied is not None and now - replied[1] <= ECHO_WINDOW_MS:
        return replied[0]
    return prior_unread(held, fan, row)


def reply_prior(held: tuple[bool | None, int] | None, prior: bool | None, now: int) -> tuple[bool | None, int]:
    return held if held is not None and now - held[1] <= ECHO_WINDOW_MS else (prior, now)


def expected_delta(kind: Literal["dm", "echo"], muted: bool, prior: bool | None) -> int | None:
    if kind == "dm" and muted:
        return 0
    if prior is None:
        return None
    return int(not prior) if kind == "dm" else -int(prior)


def should_record(only_if_unread: bool, held_row: dict | None) -> bool:
    return not only_if_unread or held_row is None or _row_unread(held_row)


def _counted(rows: list) -> int:
    return sum(1 for r in rows if of_counts(r))


# Two frames can cancel out and two pages can drop a row; one frame on a one-page list still judges.
def _judgeable(calls: int, has_more: bool, counter: int | None, frames_since_ask: int) -> bool:
    return frames_since_ask == 0 or (frames_since_ask == 1 and calls == 1 and not has_more and counter is not None)


def complete(rows: list, has_more: bool, partial: bool, counter: int | None, frames_since_ask: int, calls: int) -> bool:
    if partial or not _judgeable(calls, has_more, counter, frames_since_ask):
        return False
    return not has_more if counter is None else _counted(rows) == counter


def mismatch(rows: list, has_more: bool, partial: bool, counter: int | None, frames_since_ask: int, calls: int) -> bool:
    return (not partial and not has_more and counter is not None
            and _judgeable(calls, has_more, counter, frames_since_ask) and _counted(rows) != counter)


# OF's counter frame trails the list it describes (measured 0.8 s after a click, 0.85 s after a reply).
def settles(calls: int, mismatched: bool) -> bool:
    return mismatched and calls == 1


def settle_outcome(counted: int, counter: int | None, frame_at: int | None, asked_at: int,
                   frames_since_ask: int) -> tuple[bool, bool]:
    if not _judgeable(1, False, counter, frames_since_ask):
        return False, False
    matches = counter == counted and newer_than_ask(frame_at, asked_at)
    return matches, not matches


def hover(last_start: int | None, in_flight: bool, now: int, off: bool,
          counter_on: bool) -> Literal["read", "join", "held", "direct"]:
    if not counter_on:
        return "direct"
    if off:
        return "held"
    if in_flight:
        return "join"
    return "read" if last_start is None or now - last_start >= HOVER_COOLDOWN_MS else "held"


def echo_is_stale(at: int, row_at: int | None, latest_message_at: int | None) -> bool:
    return newer_than_ask(row_at, at) or newer_than_ask(latest_message_at, at)


def newer_than_ask(at: int | None, asked_at: int) -> bool:
    return at is not None and at > asked_at


def _fans(rows: Iterable[Any]) -> list[int]:
    return [f for r in rows or () if (f := window_fan_id(r)) is not None]


def diff(window_rows: list | None, prev: UnreadSet | None, unread_rows: list, complete: bool,
         asked_at: int, window_at: int | None = None, *, fence: UnreadSet | None = None) -> list[tuple[int, int]]:
    def fenced(fan: int) -> bool:
        return fence is not None and (newer_than_ask(fence.cut, asked_at)
                                      or newer_than_ask(_held_stamp(fence, fan), asked_at))

    listed = _fans(unread_rows)
    in_list = set(listed)
    out: list[tuple[int, int]] = []
    held: set[int] = set()
    for row in window_rows or ():
        fan = window_fan_id(row)
        if fan is None or fan in held:
            continue
        held.add(fan)
        if newer_than_ask(window_at, asked_at) or fenced(fan):
            continue
        unread = _row_unread(row)
        if not unread and fan in in_list:
            out.append((fan, 1))
        elif (unread and fan not in in_list and complete and row.get("isMutedNotifications") is False
              and not newer_than_ask(created_ms(row), asked_at)):
            out.append((fan, 0))
    if prev is None:
        return out
    if complete:
        out += [(f, 0) for f in sorted(prev.fans - in_list - held)
                if not fenced(f)]
    seen: set[int] = set()
    for f in listed:
        if f not in prev.fans and f not in held and f not in seen and not fenced(f):
            seen.add(f)
            out.append((f, 1))
    return out


# OF sends no event for a mute made elsewhere, so a listed row's isMutedNotifications is the signal.
def mute_changes(window_rows: list | None, window_at: int | None, unread_rows: list,
                 held: Mapping[int, tuple[bool, int]], asked_at: int) -> dict[int, bool]:
    window: dict[int, Any] = {}
    for r in window_rows or ():
        f = window_fan_id(r)
        if f is not None and f not in window:
            window[f] = r.get("isMutedNotifications")
    out: dict[int, bool] = {}
    for r in unread_rows or ():
        f, m = window_fan_id(r), r.get("isMutedNotifications")
        if f is None or not isinstance(m, bool) or f in out:
            continue
        own = held.get(f)
        if newer_than_ask(own and own[1], asked_at) or (f in window and newer_than_ask(window_at, asked_at)):
            continue
        if (own is not None and own[0] != m) or (f in window and window[f] is not m):
            out[f] = m
    return out


def _held_stamp(s: UnreadSet, fan: int) -> int | None:
    own = s.entries.get(fan)
    return own[1] if own is not None else s.gone.get(fan)


# A write of ours holds from its landing: OF may run it after a list asked before then.
def _stamp(event: SetEvent) -> int:
    landed = event.landed if isinstance(event, (ReadDone, UnreadDone)) else None
    return event.at if landed is None else landed


def apply(s: UnreadSet | None, event: SetEvent) -> UnreadSet | None:
    if s is None or not newer_than_ask(event.at if event.fan is None else _stamp(event), s.at):
        return s
    if event.fan is None:
        removed = {f: event.at for f, (_, stamp) in s.entries.items() if stamp <= event.at}
        return replace(s, entries={f: entry for f, entry in s.entries.items() if f not in removed},
                       gone={**s.gone, **removed},
                       cut=event.at if s.cut is None else max(s.cut, event.at))
    own = _held_stamp(s, event.fan)
    if newer_than_ask(own, max(event.at, s.at)) or (s.cut is not None and event.at <= s.cut):
        return s
    stamp = _stamp(event)
    entries, gone = dict(s.entries), dict(s.gone)
    if isinstance(event, (DmIn, UnreadDone)):
        if isinstance(event, DmIn) and event.muted:
            return s
        entries[event.fan] = ((entries.get(event.fan) or (None, 0))[0], stamp)
        gone.pop(event.fan, None)
    else:
        entries.pop(event.fan, None)
        gone[event.fan] = stamp
    return replace(s, entries=entries, gone=gone)


def replace_set(prev: UnreadSet | None, unread_rows: list, asked_at: int, complete: bool,
                window: list | None = None, window_at: int | None = None) -> UnreadSet:
    listed = {f: (r, asked_at) for r in unread_rows or () if (f := window_fan_id(r)) is not None}
    if prev is None:
        prev = UnreadSet(at=asked_at)
    if newer_than_ask(window_at, asked_at):
        for row in window or ():
            fan = window_fan_id(row)
            if fan is None:
                continue
            if _row_unread(row):
                updated = apply(prev, UnreadDone(fan, window_at))
                if updated is not prev:
                    prev = replace(updated, entries={**updated.entries, fan: (row, window_at)})
            else:
                prev = apply(prev, ReadDone(fan, window_at))
    cut = prev.cut if newer_than_ask(prev.cut, asked_at) else None
    entries = {} if cut is not None else dict(listed)
    if not complete:
        entries = {**{f: e for f, e in prev.entries.items() if f not in listed and (cut is None or e[1] > cut)}, **entries}
    for f, (row, stamp) in prev.entries.items():
        if newer_than_ask(stamp, asked_at):
            entries[f] = (row if row is not None else (listed.get(f) or (None, 0))[0], stamp)
    gone = {f: t for f, t in prev.gone.items() if newer_than_ask(t, asked_at)}
    for f in gone:
        entries.pop(f, None)
    return UnreadSet(at=asked_at, entries=entries, gone=gone, cut=cut)


def refresh_rows(s: UnreadSet, window_rows: list[dict], as_of: int) -> UnreadSet:
    fresh = {f: r for r in window_rows if (f := window_fan_id(r)) is not None}
    entries = {f: (fresh[f], t) if f in fresh and newer_than_ask(as_of, t) else (row, t)
               for f, (row, t) in s.entries.items()}
    return replace(s, entries=entries)


def restricted_unread(s: UnreadSet, restricted_ids: AbstractSet[int],
                      mutes: Mapping[int, tuple[bool, int]] | None = None) -> utd.Restricted:
    restricted, uncertain, floor = 0, False, 0
    for fan, (row, stamp) in s.entries.items():
        mute = mutes.get(fan) if mutes is not None else None
        if mute is not None and mute[1] >= stamp:
            if mute[0]:
                continue
            if row is not None and row.get("isMutedNotifications") is True:
                row = {**row, "isMutedNotifications": False}
        if row is not None and not of_counts(row):
            continue
        if utd.excluded_from_badges(fan, row, restricted_ids):
            restricted += 1
            uncertain |= stamp < s.at
        elif row is not None and stamp == s.at:
            floor += 1
    return utd.Restricted(restricted, uncertain, floor)
