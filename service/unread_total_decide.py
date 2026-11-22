"""
The Unread total's decision (docs/spec/watched-creator-refresher/phase-02-unread-total-first-paint.md, ADR-0043):
pure (stdlib only), no clock, no I/O; times are passed (epoch ms, Relay clock). Its shell is unread_total.py; tables
in tests/test_unread_total_decide.py.

The Unread total of a Creator is OF's own whole-inbox counter, `/users/me` `chatMessagesCount`, as OF returned it.
ASSUMPTION (spec, parked check C): it counts unread chats (muted included) and drops on a read made on OF web.

  State(n, at, base, adj, rec, due, seen, cut): the held total (`n` None: no confirmation yet), `at`, the ask time of the OF
      read that last confirmed it, the adjustments made since (`adj`, in the order they were made, each stamped) on
      top of `base`, OF's number they started from (None while `adj` is empty: then `n` is it), `rec`, the Relay's
      own per-fan record (fan -> (unread, stamp)) of what our flips, replies and DMs set, kept one Cycle: until the
      second confirmation after it (a record stamped at or before the previous confirmation's ask is dropped), and
      `due`, the ask time of the confirmation that found a downward drift no window read has served yet (None: none),
      `seen`, the ask time of the newest `/users/me` answer taken, with a counter or without: the one watermark both
      kinds order by (kept while the total is unknown); an answer asked before it is older and changes nothing;
      `cut`, the pre-write `at` of the last mark all read (None: none).
  count(me_body) -> int | None: OF's number from a `/users/me` body: an int >= 0 (not a bool), else None.
  prior_of(state, fan, window_row) -> UNREAD | READ | UNKNOWN: the chat's state before an event: our own record
      first, then the held page-0 row (`hasUnread` or `unreadMessagesCount` > 0, as the app), else UNKNOWN.
  adjust(state, event, now) -> state': a between-Cycle move at 0 OF calls (the spec's adjustment table), clamped at
      0, kept until a confirmation asked after it landed on OF (the adjustment's stamp); the fan's record set,
      stamped with the event's own time (its order against the fan's other events):
        `DmIn(fan, prior, at)`: `at` the message's `createdAt` (OF had it then; None: `now`), both stamps: read +1,
          unread 0, unknown +1 slack +1; record unread. A DM at or before the held confirmation's ask is in OF's
          number already (transcoded late): record only, no move. Its order is OF's clock, every other stamp the
          Relay's (`now`, a flip's pre-write `at`): no skew correction, so a DM within that skew of a flip or reply
          for the same fan may order either way (OF and the Relay both run NTP; inferred sub-second). A DM at or
          before `cut` (made before the last mark all, transcoded after it) was read by it: no move, no record.
        `ReadFlip(fan, 0, at, prior)` (mark read), landed `now`, recorded at its pre-write `at`: read 0, unread -1,
          unknown -1 (OF is only asked when a tab saw it unread); record read.
        `ReadFlip(fan, 1, at, prior)` (mark unread): read +1, unread 0, unknown +1 slack +1; record unread.
        `ReadFlip(None, 0, at, _)` (mark all read), landed `now`: `n` = the chats our record holds unread from a move
          recorded after `at` (the DMs that landed after the write was asked; ASSUMPTION: a mark unread after it
          counts too); every older record becomes read.
        `Reply(fan, prior)` at `now`: read 0, unread -1, unknown 0 slack +1; record read. ASSUMPTION (spec): a
          reply makes an unread chat read on OF.
      An event older than the fan's record (a mark read asked before a DM it never saw, a DM transcoded after our
      later read or reply) changes nothing: the newer one stands, as in the tabs.
      No total yet: `n` stays None (the moves are still kept, for the first confirmation).
  slack(state) -> int: the unknown-prior moves held (since the last mark all) that could leave OF's number lower.
  expected(state, at) -> int | None: the held value at `at`: `base` plus the adjustments landed at or before it.
  reconcile(state, observed, asked_at, now) -> (state', actions): a confirming read adopts OF's number plus only the
      adjustments that landed after `asked_at` (still held, slack included, for the next one: a read asked while
      our write was in flight may predate it; the rest and their slack dropped); `PUBLISH` when `n` changed (an unchanged `n` moves `at` alone, published by nothing, P1 C3);
      `LOG_DRIFT` when OF's number is below `expected` at `asked_at` minus the slack held then (down: a read made
      elsewhere), or above it (up); none on a first confirmation; `WINDOW_READ` on a down drift when none is pending
      (`due` set to `asked_at`): a second drift before the read asks no second one (the refresher reads at most one
      window per Creator per Cycle, whatever asked; a drift still due waits for its next Cycle). A read asked before
      `seen` (landed late) changes nothing.
  unconfirmed(state, asked_at) -> state': a `/users/me` answer without a counter, asked at `asked_at`: it confirms
      nothing, so the total goes (`n`, `at`, `base`; records, adjustments and `due` stay) and `seen` moves to it; one
      asked before `seen` changes nothing.
  read_window(state, asked_at) -> state': a page-0 window read asked at `asked_at` landed: a drift found by a
      confirmation asked at or before it is served (`due` cleared); one asked later stays due.
  flips(old_rows | None, new_rows, asked_at, drift_down) -> [(fan, unread)]: the window read's `chat_read_changed`s,
      in `new_rows` order: with old rows held, each fan in both whose unread state (as `prior_of` reads a row)
      flipped; no old rows, on a drift read (`drift_down`), `(fan, 0)` per read row, on a routine read none (a
      restart's `resync` refetches the tabs' lists). Never `(fan, 0)` for a row whose `lastMessage.createdAt` is
      newer than `asked_at` (undated: not newer). A row new to or gone from the window: none (the head poll).
  slot(state) -> {n, at} | None: `values.unread_total` (P2 Contracts); None before the first confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

PUBLISH = "publish"
LOG_DRIFT = "log_drift"
WINDOW_READ = "window_read"

UNREAD, READ, UNKNOWN = "unread", "read", "unknown"

MAX_ADJ = 256       # adjustments held without a confirmation; the oldest folds into `base` (a Creator nobody reads)
MAX_REC = 2048      # per-fan records held; the oldest go first


@dataclass(frozen=True)
class Adj:
    stamp: int                      # when it landed on OF: a confirmation asked after this has it
    delta: int = 0
    slack: int = 0
    set_to: int | None = None       # a mark all read: `n` becomes this


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


@dataclass(frozen=True)
class DmIn:
    fan: int
    prior: str
    at: int | None = None   # the message's createdAt, epoch ms (None: unknown, the move's `now`)


@dataclass(frozen=True)
class ReadFlip:
    fan: int | None         # None: mark all read
    unread: int             # 0: mark read, 1: mark unread
    at: int                 # pre-write epoch ms
    prior: str


@dataclass(frozen=True)
class Reply:
    fan: int
    prior: str


def count(me_body: Any) -> int | None:
    v = me_body.get("chatMessagesCount") if isinstance(me_body, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _row_unread(row: dict) -> bool:
    """Unread as the app reads a row (app/lib/chatUnread.ts `isUnreadChat`): the flag or a count."""
    return bool(row.get("hasUnread")) or int(row.get("unreadMessagesCount") or 0) > 0


def prior_of(state: State, fan: int | None, window_row: Any) -> str:
    own = state.rec.get(fan) if fan is not None else None
    if own is not None:
        return UNREAD if own[0] else READ
    if not isinstance(window_row, dict):
        return UNKNOWN
    return UNREAD if _row_unread(window_row) else READ


# (event kind, prior) -> (delta, slack); the record each kind sets: DM / mark unread unread, mark read / reply read.
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
        a = Adj(stamp=now, set_to=sum(1 for unread, t in rec.values() if unread and t > event.at))
        rec = {f: (v if v[1] > event.at else (False, event.at)) for f, v in rec.items()}
        cut = event.at if cut is None else max(cut, event.at)
    else:
        if isinstance(event, DmIn):
            kind, order, unread = "dm", now if event.at is None else event.at, True
            landed = order
            if cut is not None and order <= cut:
                return state            # made before the last mark all: it read this one too
        elif isinstance(event, Reply):
            kind, order, landed, unread = "reply", now, now, False
        elif isinstance(event, ReadFlip):
            kind, order, landed, unread = ("unread" if event.unread else "read"), event.at, now, bool(event.unread)
        else:
            return state
        own = rec.get(event.fan)
        if own is not None and own[1] > order:
            return state                # older than what we hold for the fan: the newer event stands
        delta, slack = _TABLE[(kind, event.prior)]
        rec[event.fan] = (unread, order)
        # A DM at or before the held confirmation's ask is in its number already (transcoded late).
        counted = kind == "dm" and state.at is not None and landed <= state.at
        a = Adj(stamp=landed, delta=delta, slack=slack) if (delta or slack) and not counted else None
    base, adj = _base(state), state.adj + ((a,) if a is not None else ())
    if len(adj) > MAX_ADJ:
        base, adj = _fold(base, adj[:1]), adj[1:]
    return State(n=_fold(base, adj), at=state.at, base=base if adj else None, adj=adj, rec=_cap(rec), due=state.due,
                 seen=state.seen, cut=cut)


def slack(state: State) -> int:
    return _slack(state.adj)


def expected(state: State, at: int) -> int | None:
    return _fold(_base(state), [a for a in state.adj if a.stamp <= at])


def reconcile(state: State, observed: int, asked_at: int, now: int) -> tuple[State, tuple[str, ...]]:
    if _stale(state, asked_at):
        return state, ()
    done = [a for a in state.adj if a.stamp <= asked_at]
    keep = tuple(a for a in state.adj if a.stamp > asked_at)
    want = expected(state, asked_at)
    down = want is not None and observed < want - _slack(done)
    drift = down or (want is not None and observed > want)
    ask = down and state.due is None
    rec = state.rec if state.at is None else {f: v for f, v in state.rec.items() if v[1] > state.at}
    nxt = State(n=_fold(observed, keep), at=asked_at, base=observed if keep else None, adj=keep, rec=rec,
                due=asked_at if down else state.due,   # a later drift outlives a window read asked before it
                seen=asked_at, cut=state.cut)
    return nxt, (((PUBLISH,) if nxt.n != state.n else ()) + ((LOG_DRIFT,) if drift else ())
                 + ((WINDOW_READ,) if ask else ()))


def _stale(state: State, asked_at: int) -> bool:
    """Asked before the newest answer taken (`seen`)."""
    return state.seen is not None and asked_at < state.seen


def unconfirmed(state: State, asked_at: int) -> State:
    if _stale(state, asked_at):
        return state
    return replace(state, n=None, at=None, base=None, seen=asked_at)


def read_window(state: State, asked_at: int) -> State:
    return replace(state, due=None) if state.due is not None and state.due <= asked_at else state


def _fan(row: Any) -> int | None:
    fan = (row.get("withUser") or {}).get("id") if isinstance(row, dict) else None
    try:
        return None if fan is None or isinstance(fan, bool) else int(fan)
    except (TypeError, ValueError):
        return None


def _newer(row: dict, asked_at: int) -> bool:
    created = (row.get("lastMessage") or {}).get("createdAt")
    try:
        return int(datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp() * 1000) > asked_at
    except (TypeError, ValueError):
        return False


def flips(old_rows: list | None, new_rows: list, asked_at: int, drift_down: bool) -> list[tuple[int, int]]:
    old = None if old_rows is None else {f: _row_unread(r) for r in old_rows if (f := _fan(r)) is not None}
    out: list[tuple[int, int]] = []
    for row in new_rows or ():
        fan = _fan(row)
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


def slot(state: State) -> dict[str, int] | None:
    return None if state.n is None else {"n": state.n, "at": state.at}
