"""Badge reads' decision (creator-badges phase 0C, ADR-0051): pure, stdlib only, times passed in epoch ms.
`newer_than_ask` is the one ordering fence; Phase E's fence-off fault patches it by name."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import AbstractSet, Any, Iterable, Literal, Union

import unread_total_decide as utd
from unread_total_decide import _fan, _row_unread, created_ms, of_counts

DM_WINDOW_MS = 500
ECHO_WINDOW_MS = 1500
DECIDE_AFTER_MS = 1500
GAP_MS = {"full": 5000, "lean": 15000}
CAP_PER_HOUR = 120
HOUR_MS = 3_600_000
HOVER_COOLDOWN_MS = 30_000
INTENT_TAIL_MS = 1500
INTENT_MAX_MS = 5000
FRAME_LAG_MS = 1000


@dataclass(frozen=True)
class UnreadSet:
    at: int                                                                 # the read's ask time
    entries: dict[int, tuple[dict | None, int]] = field(default_factory=dict)   # fan -> (row | None: 0-call, stamp)
    gone: dict[int, int] = field(default_factory=dict)                      # fan -> removal stamp since the ask
    cut: int | None = None                                                  # a mark all read since the ask

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
    fan: int | None         # None: mark all read
    at: int


@dataclass(frozen=True)
class UnreadDone:
    fan: int
    at: int


@dataclass(frozen=True)
class Echo:
    fan: int
    at: int


SetEvent = Union[DmIn, ReadDone, UnreadDone, Echo]


@dataclass(frozen=True)
class Intent:
    id: int
    fan: int | None         # None: mark all read
    created: int
    responded: int | None = None
    retired: bool = False
    used: bool = False


@dataclass(frozen=True)
class Gate:
    in_flight: bool = False
    last_start: int | None = None
    starts: tuple[int, ...] = ()
    pending: bool = False


@dataclass(frozen=True)
class Start:
    pass


@dataclass(frozen=True)
class Wait:
    until: int | None       # None: after the read in flight


@dataclass(frozen=True)
class Capped:
    pass


def admit(gate: Gate, now: int, gap_ms: int, cap: int, held_s: float) -> tuple[Gate, Start | Wait | Capped]:
    if gate.in_flight:
        return replace(gate, pending=True), Wait(None)
    if held_s > 0:
        return replace(gate, pending=True), Wait(now + math.ceil(held_s * 1000))
    if gate.last_start is not None and now - gate.last_start < gap_ms:
        return replace(gate, pending=True), Wait(gate.last_start + gap_ms)
    recent = tuple(t for t in gate.starts if t > now - HOUR_MS)
    if len(recent) >= cap:
        return replace(gate, starts=recent, pending=True), Capped()
    return Gate(in_flight=True, last_start=now, starts=recent + (now,), pending=False), Start()


def done(gate: Gate, sent_at: int | None = None) -> Gate:
    """`sent_at`: page 1's answer, so at or after OF saw it (the per-Creator pacer or a lane can hold it past the
    admit); the gap counts from it, so OF never sees two starts closer than the gap."""
    if sent_at is None or gate.last_start is None or sent_at <= gate.last_start:
        return replace(gate, in_flight=False)
    return replace(gate, in_flight=False, last_start=sent_at)


def intent_end(i: Intent) -> int:
    hard = i.created + INTENT_MAX_MS
    return hard if i.responded is None else min(hard, i.responded + INTENT_TAIL_MS)


def intent_live(i: Intent, at: int) -> bool:
    return not i.retired and not i.used and i.created <= at <= intent_end(i)


def explained(frame_at: int, dms: Iterable[int], echoes: Iterable[int], intents: Iterable[Intent]) -> bool:
    return (any(abs(frame_at - t) <= DM_WINDOW_MS for t in dms)
            or any(abs(frame_at - t) <= ECHO_WINDOW_MS for t in echoes)
            or any(intent_live(i, frame_at) for i in intents))


def explain(frame_at: int, dms: Iterable[int], echoes: Iterable[int],
            intents: Iterable[Intent]) -> tuple[bool, tuple[Intent, ...]]:
    intents = tuple(intents)
    if explained(frame_at, dms, echoes, ()):
        return True, intents
    live = [k for k, i in enumerate(intents) if intent_live(i, frame_at)]
    if not live:
        return False, intents
    if any(intents[k].fan is None for k in live):
        return True, intents
    k = min(live, key=lambda k: intents[k].created)
    return True, intents[:k] + (replace(intents[k], used=True),) + intents[k + 1:]


def respond(intents: Iterable[Intent], intent_id: int, at: int) -> tuple[Intent, ...]:
    return tuple(replace(i, responded=at) if i.id == intent_id and i.responded is None and not i.retired else i
                 for i in intents)


def retire(intents: Iterable[Intent], intent_id: int) -> tuple[Intent, ...]:
    return tuple(replace(i, retired=True) if i.id == intent_id else i for i in intents)


def prune(intents: Iterable[Intent], now: int) -> tuple[Intent, ...]:
    return tuple(i for i in intents if not i.retired and not i.used and intent_end(i) + DECIDE_AFTER_MS >= now)


def should_record(only_if_unread: bool, held_row: dict | None) -> bool:
    return not only_if_unread or held_row is None or _row_unread(held_row)


def _counted(rows: list) -> int:
    return sum(1 for r in rows if of_counts(r))


def _judgeable(calls: int, has_more: bool, counter: int | None, frames_since_ask: int) -> bool:
    """One counter frame since the ask still judges a one-page list: its change is in the list (counts match) or not
    (off by one). Two frames can cancel out, and two pages can drop a row."""
    return frames_since_ask == 0 or (frames_since_ask == 1 and calls == 1 and not has_more and counter is not None)


def complete(rows: list, has_more: bool, partial: bool, counter: int | None, frames_since_ask: int, calls: int) -> bool:
    if partial or not _judgeable(calls, has_more, counter, frames_since_ask):
        return False
    return not has_more if counter is None else _counted(rows) == counter


def mismatch(rows: list, has_more: bool, partial: bool, counter: int | None, frames_since_ask: int, calls: int) -> bool:
    return (not partial and not has_more and counter is not None
            and _judgeable(calls, has_more, counter, frames_since_ask) and _counted(rows) != counter)


def settles(calls: int, mismatched: bool) -> bool:
    """A one-page list below or above the counter waits up to FRAME_LAG_MS for the next counter frame and is judged by
    it: OF's frame trails the list it describes (measured 0.8 s after a click, 0.85 s after a reply). Never two pages:
    a removal between them shifts page 2 past a row, and the mismatch is what guards that."""
    return mismatched and calls == 1


def settled(counted: int, counter: int | None, frame_at: int | None, asked_at: int) -> bool:
    """The waited-for frame completes the read only if it matches and came after the ask."""
    return counter == counted and newer_than_ask(frame_at, asked_at)


def hover(last_start: int | None, in_flight: bool, now: int, off: bool,
          counter_on: bool) -> Literal["read", "join", "held", "direct"]:
    """A `?bust=` rewarm, shared by every Employee: a read in flight is joined even past the cooldown, so one
    Creator's window never has two. Without the counter path (UNREAD_TOTAL off) every bust reads, as before."""
    if off:
        return "held"
    if not counter_on:
        return "direct"
    if in_flight:
        return "join"
    return "read" if last_start is None or now - last_start >= HOVER_COOLDOWN_MS else "held"


def newer_than_ask(at: int | None, asked_at: int) -> bool:
    return at is not None and at > asked_at


def _fans(rows: Iterable[Any]) -> list[int]:
    return [f for r in rows or () if (f := _fan(r)) is not None]


def diff(window_rows: list | None, prev: UnreadSet | None, unread_rows: list, complete: bool,
         asked_at: int) -> list[tuple[int, int]]:
    listed = _fans(unread_rows)
    in_list = set(listed)
    out: list[tuple[int, int]] = []
    held: set[int] = set()
    for row in window_rows or ():
        fan = _fan(row)
        if fan is None or fan in held:
            continue
        held.add(fan)
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
                if not newer_than_ask(prev.entries[f][1], asked_at)]
    seen: set[int] = set()
    for f in listed:
        if f not in prev.fans and f not in held and f not in seen:
            seen.add(f)
            out.append((f, 1))
    return out


def _held_stamp(s: UnreadSet, fan: int) -> int | None:
    own = s.entries.get(fan)
    return own[1] if own is not None else s.gone.get(fan)


def apply(s: UnreadSet | None, event: SetEvent) -> UnreadSet | None:
    if s is None or not newer_than_ask(event.at, s.at):
        return s
    if event.fan is None:
        return replace(s, entries={}, gone={**s.gone, **{f: event.at for f in s.entries}},
                       cut=event.at if s.cut is None else max(s.cut, event.at))
    own = _held_stamp(s, event.fan)
    if own is not None and own > event.at:
        return s
    entries, gone = dict(s.entries), dict(s.gone)
    if isinstance(event, (DmIn, UnreadDone)):
        if isinstance(event, DmIn) and event.muted:
            return s
        entries[event.fan] = ((entries.get(event.fan) or (None, 0))[0], event.at)
        gone.pop(event.fan, None)
    else:
        entries.pop(event.fan, None)
        gone[event.fan] = event.at
    return replace(s, entries=entries, gone=gone)


def replace_set(prev: UnreadSet | None, unread_rows: list, asked_at: int, complete: bool) -> UnreadSet:
    listed = {f: (r, asked_at) for r in unread_rows or () if (f := _fan(r)) is not None}
    if prev is None:
        return UnreadSet(at=asked_at, entries=listed)
    cut = prev.cut if newer_than_ask(prev.cut, asked_at) else None
    entries = {} if cut is not None else dict(listed)
    if not complete:
        entries = {**{f: e for f, e in prev.entries.items() if f not in listed}, **entries}
    for f, (row, stamp) in prev.entries.items():
        if newer_than_ask(stamp, asked_at):
            entries[f] = (row if row is not None else (listed.get(f) or (None, 0))[0], stamp)
    gone = {f: t for f, t in prev.gone.items() if newer_than_ask(t, asked_at)}
    for f in gone:
        entries.pop(f, None)
    return UnreadSet(at=asked_at, entries=entries, gone=gone, cut=cut)


def refresh_rows(s: UnreadSet, window_rows: list[dict], as_of: int) -> UnreadSet:
    fresh = {f: r for r in window_rows if (f := _fan(r)) is not None}
    entries = {f: (fresh[f], t) if f in fresh and newer_than_ask(as_of, t) else (row, t)
               for f, (row, t) in s.entries.items()}
    return replace(s, entries=entries)


def restricted_unread(s: UnreadSet, restricted_ids: AbstractSet[int]) -> int:
    return sum(1 for fan, (row, _stamp) in s.entries.items()
               if (row is None or of_counts(row)) and utd.excluded_from_badges(fan, row, restricted_ids))
