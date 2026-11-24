"""
The Unread total's decision (docs/spec/watched-creator-refresher/phase-02-unread-total-first-paint.md, ADR-0043):
pure (stdlib only), no clock, no I/O; times are passed (epoch ms, Relay clock). Its shell is unread_total.py; tables
in tests/test_unread_total_decide.py.

The Unread total of a Creator is OF's own whole-inbox counter, `/users/me` `chatMessagesCount`, as OF returned it.
ASSUMPTION (spec, parked check C): it counts unread chats (muted included) and drops on a read made on OF web.

  State(n, at, base, adj, rec, due, seen, cut, ws_at): the held total (`n` None: no confirmation yet), `at`, the
      ask time of the OF read that last confirmed it, the adjustments made since (`adj`, in the order they were made,
      each stamped) on top of `base`, OF's number they started from (None while `adj` is empty: then `n` is it),
      `rec`, the Relay's own per-fan record (fan -> (unread, stamp)) of what our flips, replies and DMs set, kept
      one Cycle: until the second confirmation after it (a record stamped at or before the previous confirmation's
      ask is dropped), and `due`, the ask time of the confirmation that found a downward drift no window read has
      served yet (None: none),
      `seen`, the ask time of the newest `/users/me` answer taken, with a counter or without: the one watermark both
      kinds order by (kept while the total is unknown); an answer asked before it is older and changes nothing;
      `cut`, the pre-write `at` of the last mark all read (None: none), `ws_at`, the receipt time of the newest Unread
      counter frame taken (None: none since start), `poll_at`, the ask time of the newest socket-down poll taken
      (creator-badges 0C; None: none since start).
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
        `Reply(fan, prior, at)` ordered by the pre-send stamp (fallback `now`): read 0, unread -1, unknown 0 slack +1; record read. ASSUMPTION (spec): a
          reply makes an unread chat read on OF.
      An event older than the fan's record (a mark read asked before a DM it never saw, a DM transcoded after our
      later read or reply) changes nothing: the newer one stands, as in the tabs.
      Any move whose own time (a DM's `createdAt`, a flip's pre-write `at`, a reply's `now`) is at or before `ws_at`
      is recorded but moves nothing: the frame received after it counts it already (a mark read's frame lands
      ≈0.23 s after the call, often before the write returns).
      No total yet: `n` stays None (the moves are still kept, for the first confirmation).
  slack(state) -> int: the unknown-prior moves held (since the last mark all) that could leave OF's number lower.
  expected(state, at) -> int | None: the held value at `at`: `base` plus the adjustments landed at or before it.
  reconcile(state, observed, asked_at, now) -> (state', actions): a confirming read adopts OF's number plus only the
      adjustments that landed after `asked_at` (still held, slack included, for the next one: a read asked while
      our write was in flight may predate it; the rest and their slack dropped); an unchanged `n` moves `at` alone;
      publishing is the shell's (`badge_version`);
      `LOG_DRIFT` when OF's number is below `expected` at `asked_at` minus the slack held then (down: a read made
      elsewhere), or above it (up); none on a first confirmation; `WINDOW_READ` on a down drift when none is pending
      (`due` set to `asked_at`): a second drift before the read asks no second one (the refresher reads at most one
      window per Creator per Cycle, whatever asked; a drift still due waits for its next Cycle). A read asked before
      `seen` (landed late) changes nothing.
  reconcile(..., via="ws"): an Unread counter frame (`chat_messages`, creator-badges 0B) received at `asked_at`:
      the same confirmation and watermark, but never `LOG_DRIFT` or `WINDOW_READ` and `due` left as it was
      (attributing a drop is Phase C's; a window read per elsewhere-read would add OF calls).
  reconcile(..., via="poll"): a Complete socket-down Unread list poll asked at `asked_at` (creator-badges 0C): as
      a frame, but stamps `poll_at` instead of `ws_at`. `via="me"` (default): a `/users/me` answer.
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
  grey_reason(state, r, up_since, now, cause) -> reason | None: why the slot draws grey, the first matching cause in the spec's
      list order (creator-badges 0B): `unseeded` (no total held), `socket_down` (`up_since`, the epoch ms the Live
      connection came up, is None, or the held confirmation is older than it: a reconnect alone never un-greys an old
      number), `r_unknown` (`r` None); else None. Phase C (`now` epoch ms, `cause` the shell's held cause):
      `dead` / `proxy_down` first (the root cause outranks no value and the socket it takes down); socket down with
      a poll of this outage (`poll_at` after the newest frame) is not `socket_down`, whatever `/users/me` landed
      since; `stale` last: that poll older than `STALE_MS`.
  slot(state, r, up_since, now, cause) -> {n, at, grey}: `values.unread_total` (always an object with the Knob on).
      `n` is the Red circle: OF's number minus `r` (Restricted unread), floored at 0; None before the first confirmation or while
      `r` is unknown, so OF's raw number is never published (owner amendment #2); `grey` is `grey_reason`.
  overlay(rows, events, asked_at, me) -> rows': the page-0 window as of now for the Amber fold (creator-badges 0F):
      `events` per Fan the newest arrival of each kind (`ECHO` a Creator reply from any client, `DM` an inbound DM,
      `READ` / `UNREAD` a landed read flip), applied in time order (same ms: read, unread, echo, DM) when after
      `asked_at` (the window's ask; None: none): echo -> read, last sender `me`; DM -> unread (count kept, at least 1), last sender the Fan; read ->
      read; unread -> unread. A Fan not in `rows` adds no row; `rows` is not mutated.
  amber_slot(held) -> {amber, amber_at}: the Amber circle's keys in that slot (creator-badges 0F): `held` the
      last fold `(count, window fetched-at epoch ms)`, None before any window since restart; `amber` None only then.
      It never ages out: events keep it, and a stale Creator greys red, which hides amber (one grey circle).
  badge_version(prev, nxt, v) -> v': `v` + 1 when any key of the published slot changed, never on `at` or
      `amber_at` alone.
  excluded_from_badges(fan_id, row, restricted_ids) -> bool: the one Restricted-for-counting rule (creator-badges
      phase 0B, owner amendments #2, #3): the fan is in our `of_restricted` registry or the row's `canSendMessage` is
      False (any reason); absent counts as sendable; OF's own `isRestricted` plays no part.
  of_counts(row) -> bool: OF's counter counts the row: unread, not Muted, sendable, `only_friends` or Restricted
      (`canNotSendReason` "muted").
  amber_count(rows, me, restricted_ids, unread_fans) -> int: the Owe reply (Amber circle) fold over the page-0 window
      (first WINDOW Fans, one row per Fan): read, a last sender not `me`, `isMutedNotifications` exactly False (muting
      marks read on OF: unknown never owes), not `excluded_from_badges`, not in `unread_fans` (Phase C's latest Unread
      set; None: no set held, the guard passes).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import AbstractSet, Any, Literal, NamedTuple

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
    ws_at: int | None = None
    poll_at: int | None = None


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
        a = None if _framed(state, event.at) else Adj(
            stamp=now, set_to=sum(1 for unread, t in rec.values() if unread and t > event.at))
        rec = {f: (v if v[1] > event.at else (False, event.at)) for f, v in rec.items()}
        cut = event.at if cut is None else max(cut, event.at)
    else:
        if isinstance(event, DmIn):
            kind, order, unread = "dm", now if event.at is None else event.at, True
            landed = order
            if cut is not None and order <= cut:
                return state            # made before the last mark all: it read this one too
        elif isinstance(event, Reply):
            kind, order, landed, unread = "reply", now if event.at is None else event.at, now, False
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
                due=asked_at if down else state.due,   # a later drift outlives a window read asked before it
                seen=asked_at, cut=state.cut, ws_at=asked_at if via == "ws" else state.ws_at,
                poll_at=asked_at if via == "poll" else state.poll_at)
    return nxt, ((LOG_DRIFT,) if drift else ()) + ((WINDOW_READ,) if ask else ())


def _stale(state: State, asked_at: int) -> bool:
    """Asked before the newest answer taken (`seen`)."""
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
_TIE = {READ: 0, UNREAD: 1, ECHO: 2, DM: 3}   # same ms: the Fan's DM applies last


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
