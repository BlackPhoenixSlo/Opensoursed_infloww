from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import AbstractSet, Any, Literal, NamedTuple

LOG_DRIFT = "log_drift"
WINDOW_READ = "window_read"

UNREAD, READ, UNKNOWN = "unread", "read", "unknown"

MAX_ADJ = 256
MAX_REC = 2048


@dataclass(frozen=True)
class Adj:
    stamp: int
    delta: int = 0
    slack: int = 0
    set_to: int | None = None


@dataclass(frozen=True)
class State:
    n: int | None = None
    at: int | None = None
    base: int | None = None
    adj: tuple[Adj, ...] = ()
    rec: dict[int, tuple[bool, int]] = field(default_factory=dict)
    due: int | None = None
    seen: int | None = None
    cut: int | None = None
    ws_at: int | None = None
    poll_at: int | None = None


@dataclass(frozen=True)
class DmIn:
    fan: int
    prior: str
    at: int | None = None


@dataclass(frozen=True)
class ReadFlip:
    fan: int | None
    unread: int
    at: int
    prior: str


@dataclass(frozen=True)
class Reply:
    fan: int
    prior: str
    at: int | None = None


def count(me_body: Any) -> int | None:
    v = me_body.get("chatMessagesCount") if isinstance(me_body, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


RED_DISPLAY_CAP = 9


class Restricted(NamedTuple):
    n: int
    uncertain: bool
    floor: int


def window_rows(value: dict) -> list:
    return value.get("list") or value.get("chats") or []


def _row_unread(row: dict) -> bool:
    return bool(row.get("hasUnread")) or int(row.get("unreadMessagesCount") or 0) > 0


def prior_of(state: State, fan: int | None, window_row: Any) -> str:
    own = state.rec.get(fan) if fan is not None else None
    if own is not None:
        return UNREAD if own[0] else READ
    if not isinstance(window_row, dict):
        return UNKNOWN
    return UNREAD if _row_unread(window_row) else READ


_TABLE = {
    ("dm", READ): (1, 0), ("dm", UNREAD): (0, 0), ("dm", UNKNOWN): (1, 1),
    ("read", READ): (0, 0), ("read", UNREAD): (-1, 0), ("read", UNKNOWN): (-1, 0),
    ("unread", READ): (1, 0), ("unread", UNREAD): (0, 0), ("unread", UNKNOWN): (1, 1),
    ("reply", READ): (0, 0), ("reply", UNREAD): (-1, 0), ("reply", UNKNOWN): (0, 1),
}


def _fold(n: int | None, adj: tuple[Adj, ...] | list[Adj]) -> int | None:
    if n is None:
        return None
    for a in adj:
        n = a.set_to if a.set_to is not None else max(0, n + a.delta)
    return n


def _slack(adj: tuple[Adj, ...] | list[Adj]) -> int:
    s = 0
    for a in adj:
        s = 0 if a.set_to is not None else s + a.slack
    return s


def _base(state: State) -> int | None:
    return state.base if state.adj else state.n


def _cap(rec: dict[int, tuple[bool, int]]) -> dict[int, tuple[bool, int]]:
    if len(rec) <= MAX_REC:
        return rec
    return dict(sorted(rec.items(), key=lambda kv: kv[1][1])[-MAX_REC:])


def adjust(state: State, event: Any, now: int) -> State:
    rec, cut = dict(state.rec), state.cut
    if isinstance(event, ReadFlip) and event.fan is None:
        a = None if _framed(state, event.at) else Adj(
            stamp=now, set_to=sum(1 for unread, t in rec.values() if unread and t > event.at))
        rec = {f: (v if v[1] > event.at else (False, event.at)) for f, v in rec.items()}
        cut = event.at if cut is None else max(cut, event.at)
    else:
        if isinstance(event, DmIn):
            kind, order, unread = "dm", now if event.at is None else event.at, True
            landed = order
            if cut is not None and order <= cut:
                return state
        elif isinstance(event, Reply):
            kind, order, landed, unread = "reply", now if event.at is None else event.at, now, False
        elif isinstance(event, ReadFlip):
            kind, order, landed, unread = ("unread" if event.unread else "read"), event.at, now, bool(event.unread)
        else:
            return state
        own = rec.get(event.fan)
        if own is not None and own[1] > order:
            return state
        delta, slack = _TABLE[(kind, event.prior)]
        rec[event.fan] = (unread, order)
        counted = (kind == "dm" and state.at is not None and landed <= state.at) or _framed(state, order)
        a = Adj(stamp=landed, delta=delta, slack=slack) if (delta or slack) and not counted else None
    base, adj = _base(state), state.adj + ((a,) if a is not None else ())
    if len(adj) > MAX_ADJ:
        base, adj = _fold(base, adj[:1]), adj[1:]
    return replace(state, n=_fold(base, adj), base=base if adj else None, adj=adj, rec=_cap(rec), cut=cut)


def _framed(state: State, own: int) -> bool:
    return state.ws_at is not None and own <= state.ws_at


def slack(state: State) -> int:
    return _slack(state.adj)


def expected(state: State, at: int) -> int | None:
    return _fold(_base(state), [a for a in state.adj if a.stamp <= at])


Via = Literal["me", "ws", "poll"]


def reconcile(state: State, observed: int, asked_at: int, now: int,
              via: Via = "me") -> tuple[State, tuple[str, ...]]:
    if _stale(state, asked_at):
        return state, ()
    done = [a for a in state.adj if a.stamp <= asked_at]
    keep = tuple(a for a in state.adj if a.stamp > asked_at)
    want = expected(state, asked_at) if via == "me" else None
    down = want is not None and observed < want - _slack(done)
    drift = down or (want is not None and observed > want)
    ask = down and state.due is None
    rec = state.rec if state.at is None else {f: v for f, v in state.rec.items() if v[1] > state.at}
    nxt = State(n=_fold(observed, keep), at=asked_at, base=observed if keep else None, adj=keep, rec=rec,
                due=asked_at if down else state.due,
                seen=asked_at, cut=state.cut, ws_at=asked_at if via == "ws" else state.ws_at,
                poll_at=asked_at if via == "poll" else state.poll_at)
    return nxt, ((LOG_DRIFT,) if drift else ()) + ((WINDOW_READ,) if ask else ())


def _stale(state: State, asked_at: int) -> bool:
    return state.seen is not None and asked_at < state.seen


def unconfirmed(state: State, asked_at: int) -> State:
    if _stale(state, asked_at):
        return state
    return replace(state, n=None, at=None, base=None, seen=asked_at)


def read_window(state: State, asked_at: int) -> State:
    return replace(state, due=None) if state.due is not None and state.due <= asked_at else state


def window_fan_id(row: Any) -> int | None:
    fan = (row.get("withUser") or {}).get("id") if isinstance(row, dict) else None
    try:
        return None if fan is None or isinstance(fan, bool) else int(fan)
    except (TypeError, ValueError):
        return None


def created_ms(row: dict) -> int | None:
    created = (row.get("lastMessage") or {}).get("createdAt")
    try:
        return int(datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _newer(row: dict, asked_at: int) -> bool:
    at = created_ms(row)
    return at is not None and at > asked_at


def flips(old_rows: list | None, new_rows: list, asked_at: int, drift_down: bool) -> list[tuple[int, int]]:
    old = None if old_rows is None else {f: _row_unread(r) for r in old_rows if (f := window_fan_id(r)) is not None}
    out: list[tuple[int, int]] = []
    for row in new_rows or ():
        fan = window_fan_id(row)
        if fan is None:
            continue
        unread = _row_unread(row)
        if old is None:
            flipped = drift_down and not unread
        else:
            flipped = fan in old and old[fan] != unread
        if flipped and (unread or not _newer(row, asked_at)):
            out.append((fan, int(unread)))
    return out


UNSEEDED, SOCKET_DOWN, R_UNKNOWN = "unseeded", "socket_down", "r_unknown"
DEAD, PROXY_DOWN, STALE = "dead", "proxy_down", "stale"
Cause = Literal["dead", "proxy_down"]
STALE_MS = 45_000


def grey_reason(state: State, r: int | None, up_since: int | None, now: int,
                cause: Cause | None = None) -> str | None:
    if cause in (DEAD, PROXY_DOWN):
        return cause
    if state.n is None:
        return UNSEEDED
    polled = up_since is None and state.poll_at is not None and (state.ws_at is None or state.ws_at < state.poll_at)
    if not polled and (up_since is None or state.at is None or state.at < up_since):
        return SOCKET_DOWN
    if r is None:
        return R_UNKNOWN
    if polled and now - state.poll_at > STALE_MS:
        return STALE
    return None


def slot(state: State, r: Restricted | None, up_since: int | None, now: int,
         cause: Cause | None = None) -> dict[str, Any]:
    n = None
    if state.n is not None and r is not None:
        if r.uncertain:
            floor = min(state.n, r.floor)
            if floor >= RED_DISPLAY_CAP:
                n = floor
            else:
                r = None
        else:
            n = max(0, state.n - r.n)
    return {"n": n, "at": state.at, "grey": grey_reason(state, r.n if r is not None else None, up_since, now, cause)}


ECHO, DM, READ, UNREAD = "echo", "dm", "read", "unread"
_TIE = {READ: 0, UNREAD: 1, ECHO: 2, DM: 3}


def arrival_order(event: tuple[str, int]) -> tuple[int, int]:
    kind, at = event
    return at, _TIE[kind]


def unread_row(row: dict, unread: int) -> dict:
    n = max(1, int(row.get("unreadMessagesCount") or 0)) if unread else 0
    return {**row, "hasUnread": bool(unread), "unreadMessagesCount": n}


def reply_row(row: dict, me: Any, at: int) -> dict:
    last = row.get("lastMessage") or {}
    sent = created_ms(row)
    if sent is not None and sent >= at and str((last.get("fromUser") or {}).get("id")) != str(me):
        return row
    return {**row, "hasUnread": False, "unreadMessagesCount": 0, "lastMessage": {**last, "fromUser": {"id": me}}}


def overlay(rows: Any, events: Any, asked_at: int | None, me: Any) -> list:
    if asked_at is None or not events:
        return list(rows or ())
    out = []
    for row in rows or ():
        fan = window_fan_id(row)
        late = sorted(((kind, at) for kind, at in ((events.get(fan) if fan is not None else None) or {}).items()
                       if at > asked_at), key=arrival_order)
        for kind, at in late:
            last = row.get("lastMessage") or {}
            if kind == ECHO:
                row = reply_row(row, me, at)
            elif kind == READ:
                row = unread_row(row, 0)
            else:
                row = unread_row(row, 1)
                if kind == DM:
                    row["lastMessage"] = {**last, "fromUser": {"id": fan}}
        out.append(row)
    return out


def amber_slot(held: tuple[int, int | None] | None) -> dict[str, int | None]:
    if held is None:
        return {"amber": None, "amber_at": None}
    n, at = held
    return {"amber": None if at is None else n, "amber_at": at}


def badge_version(prev: dict | None, nxt: dict | None, v: int) -> int:
    def keys(s: dict | None):
        return None if s is None else {k: x for k, x in s.items() if k not in ("at", "amber_at")}
    return v if keys(prev) == keys(nxt) else v + 1


def excluded_from_badges(fan_id: Any, row: Any, restricted_ids: AbstractSet[int]) -> bool:
    try:
        member = int(fan_id) in restricted_ids
    except (TypeError, ValueError):
        member = False
    return member or (isinstance(row, dict) and row.get("canSendMessage") is False)


WINDOW = 25


def amber_count(rows: Any, me: Any, restricted_ids: AbstractSet[int], unread_fans: AbstractSet[int] | None) -> int:
    n, seen = 0, set()
    for row in rows or ():
        fan = window_fan_id(row)
        if fan is None or fan in seen:
            continue
        seen.add(fan)
        if len(seen) > WINDOW:
            break
        sender = ((row.get("lastMessage") or {}).get("fromUser") or {}).get("id")
        if (int(row.get("unreadMessagesCount") or 0) == 0 and sender is not None and str(sender) != str(me)
                and row.get("isMutedNotifications") is False
                and not excluded_from_badges(fan, row, restricted_ids)
                and (unread_fans is None or fan not in unread_fans)):
            n += 1
    return n


# OF names a Restricted chat's reason "muted" (not notification mute), and its counter counts it.
_COUNTED_UNSENDABLE = frozenset({"only_friends", "muted"})


def of_counts(row: Any) -> bool:
    if not isinstance(row, dict) or not _row_unread(row) or row.get("isMutedNotifications") is True:
        return False
    return row.get("canSendMessage") is not False or row.get("canNotSendReason") in _COUNTED_UNSENDABLE
