"""
The SSE replay rings and the load-adaptive batching of service/events.py as two
pure transitions and a pure read of the rings (docs/reducer-scan.md "Non-React" 7):

    decide_ring(rings, Published)              -> rings'     one state per relay process
    decide_stream(stream, Deliver)             -> (stream', effect)   one state per SSE stream
    replay(rings, last_id, sees, wants, knobs) -> effects    what a (re)connect is sent first
    persist_plan(batch)                        -> rows               what the persist worker writes

plus the pure reads the shell routes and filters with: `sees` / `wants` / `any_scope` (which
subscriber an event may reach), `is_feed_noise`, `typing_fan_id` / `typing_due`, and the type sets
(SSE_TYPES, STATE_TYPES, ENDS_STREAM, FEED_POST_TYPES, ANY_SCOPE_TYPES).

No clock, no queue, no I/O here: events.py is the shell. It reads the time,
builds the event, calls decide, keeps the new state, and performs the effect
(replay's effects in order). Everything runs on the event loop's thread (other threads reach it
through `publish` / call_soon_threadsafe), so a decide call is never
interleaved with another.

Rings. Every event that passes the SSE allow-list is `Published`: it takes
the next seq (its SSE id is `<epoch>.<seq>`) and a slot in its account's ring
("" holds the Agency-wide ones and those with no account). A ring keeps the
newest RING_MAX; `evicted[key]` is the highest seq it has dropped, so a
reconnect from below it missed something no ring can replay. The frame's SSE
id is then `head_id(rings')`. `replay` is a stream opening with
`Last-Event-ID` (or none), a read of the rings:
  Resync           when the rings no longer reach back that far (eviction in a
                   ring the stream sees), or the id is garbage, from another
                   relay process (epoch differs) or from the future
  Emit(frames)...  what it missed after that id, oldest first, filtered to what
                   it may see, in chunks of BATCH_MAX (1 when batching is off),
                   each chunk coalesced
  Head(eid)        the id of the newest event at connect: a drop before the
                   next event resumes from there
A fresh connect (no id) gets only the Head.

Streams. A stream's rate is a decaying events/s average (time constant
RATE_TAU_S). `Deliver` is one frame bound for the stream; the shell passes the
open batch's size and deadline (the batch itself is the queue item and stays
in the shell). Its one effect, the first that applies:
  Append(close)    the frame joins the open batch (not full, window not over);
                   a stream-ending frame then closes it at once (`close`:
                   deadline 0, the batch is let go)
  Send             otherwise, below the rate threshold or for a stream-ending
                   frame: on its own (any open batch is let go)
  Open(deadline)   otherwise: a new batch, queued now, open until the window
                   (WINDOW_MS, MAX_WINDOW_MS above 10x the threshold) ends
`coalesce` is what a batch keeps when the stream sends it.

Routing. A subscriber is (scope, accounts, agencies): scope "all" or "model:<account_id>";
`accounts` the Creators its session may see (None: unclamped, the anonymous escape hatch and
tests); `agencies` the audiences (owner user ids, `owner:` / `sessions:` keys) whose Agency-wide
events it gets. `wants`: an Agency-wide event (`__agency`) reaches its audience whatever the
scope; an account event (`__account_id`) the subscribers that `sees` that account (scope match,
then the clamp); an event with neither only an unclamped "all" subscriber. Ids compare as str.
Any-scope (`ANY_SCOPE_TYPES`, phase-01 1b): the warm event, the chat-list patches (read flip, reply) and the
rail's money events also reach a model-scoped subscriber for any Creator in its clamp (its accessible set, resolved at
subscribe for owners and chatters), so a tab scoped to one Creator still fills its rail with
another's sale; never past the clamp (another Agency), never for an unclamped subscriber.
Replay (a reconnect) reads the same: the rings its scope sees, plus (`sees_any`) its other clamped
Creators' rings for their any-scope frames only; an evicted any-scope frame there resyncs it
(`evicted_any`), an evicted frame it could never get does not.

Persist. events_persist.py's worker drains its queue of PersistItems in batches and
transcodes every item's `event`; `persist_plan` is the event_inbox rows one batch
writes (`inbox_row`; none for UNPERSISTED_TYPES), in queue order. An item tagged `inbound_dm`
(a Fan's DM) is kept over the rest on overflow and taken first at a stop (events_persist._Lanes).

Importable without side effects (stdlib only).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, NamedTuple, Optional, Union

RING_MAX = 256      # per account: a laptop sleep or a dropped socket on a busy Creator
BATCH_MAX = 200     # most events one batch frame carries; a fuller window closes early
RATE_TAU_S = 1.0    # time constant of a stream's rate average, seconds
# Per type, the body field that names what a frame is about: within one batch
# only the newest frame per (type, account, that field) is kept. `chat_typing`
# is a "still typing" ping and `chat_queue_update` a mass message's progress,
# so the newest says everything the older ones did; `creator_refreshed` is a
# Creator's whole snapshot, so the newest per Creator replaces the rest.
COALESCE = {"chat_typing": "fan_id", "chat_queue_update": "id", "creator_refreshed": "account_id"}


# ── state ──
@dataclass(frozen=True, slots=True)
class Rings:
    epoch: str                     # this relay process's boot id (hex ms); an id from another one resyncs
    seq: int = 0                   # the last seq handed out
    rings: Mapping[str, tuple[tuple[int, Any], ...]] = field(default_factory=dict)   # key -> ((seq, frame), ...)
    evicted: Mapping[str, int] = field(default_factory=dict)                         # key -> highest seq dropped
    evicted_any: Mapping[str, int] = field(default_factory=dict)                     # key -> highest any-scope seq dropped


@dataclass(frozen=True, slots=True)
class Stream:
    rate: float = 0.0              # events/s at `rate_at`
    rate_at: float = 0.0           # monotonic


@dataclass(frozen=True, slots=True)
class Knobs:
    min_rate: float                # SSE_BATCH_MIN_RATE: at or under it, frames go out one by one
    window_ms: float               # SSE_BATCH_WINDOW_MS; <= 0 turns batching off
    max_window_ms: float           # SSE_BATCH_MAX_WINDOW_MS, above 10x min_rate


# ── events ──
@dataclass(frozen=True, slots=True)
class Published:
    frame: Any                     # the event as fanned out (a dict; `__agency` / `__account_id` route it)


@dataclass(frozen=True, slots=True)
class Deliver:
    now: float                     # monotonic
    ends: bool                     # a stream-ending frame (assignment_changed, sessions_revoked)
    open_n: int                    # frames in the stream's open batch; 0: none open
    open_deadline: float           # when that batch closes (0: as soon as the stream reaches it)
    knobs: Knobs


# ── effects ──
@dataclass(frozen=True, slots=True)
class Resync:
    pass


@dataclass(frozen=True, slots=True)
class Emit:
    frames: tuple                  # one SSE frame: a single event, or an `event: batch` of several


@dataclass(frozen=True, slots=True)
class Head:
    eid: str


@dataclass(frozen=True, slots=True)
class Send:
    pass


@dataclass(frozen=True, slots=True)
class Open:
    deadline: float


@dataclass(frozen=True, slots=True)
class Append:
    close: bool = False            # a stream-ending frame: the batch closes at once (deadline 0) and is let go


RingEffect = Union[Resync, Emit, Head]
StreamEffect = Union[Send, Open, Append]


# ── pure helpers (the shell shares them) ──
def first_key(event: Any) -> Optional[str]:
    """An event's type: its first top-level key that isn't a `__`-prefixed sentinel."""
    if not isinstance(event, dict):
        return None
    for k in event:
        if not k.startswith("__"):
            return k
    return None


def ring_key(frame: Mapping) -> str:
    """The ring an event lands in: "" for an Agency-wide one (or one with no account), else its account."""
    return "" if frame.get("__agency") is not None else str(frame.get("__account_id") or "")


def head_id(st: Rings) -> str:
    return f"{st.epoch}.{st.seq}"


def rate_now(st: Stream, now: float) -> float:
    """The stream's events/s decayed to `now`."""
    return st.rate * math.exp((st.rate_at - now) / RATE_TAU_S)


def batching_on(knobs: Knobs) -> bool:
    """SSE_BATCH_WINDOW_MS <= 0 turns batching off: live frames and replays alike go one by one."""
    return knobs.window_ms > 0


def window_s(rate: float, knobs: Knobs) -> float:
    """How long a batch opened at `rate` stays open; 0: send at once."""
    if not batching_on(knobs) or rate <= knobs.min_rate:
        return 0.0
    if rate > 10 * knobs.min_rate:
        return max(knobs.window_ms, knobs.max_window_ms) / 1000
    return knobs.window_ms / 1000


def _coalesce_key(frame: Mapping) -> Optional[tuple]:
    event_type = first_key(frame)
    fld = COALESCE.get(event_type)  # type: ignore[arg-type]
    body = frame.get(event_type) if fld else None
    if not isinstance(body, dict) or body.get(fld) is None:
        return None
    return event_type, frame.get("__account_id"), body[fld]


def coalesce(frames) -> list:
    """`frames` minus every one a newer frame in it supersedes (COALESCE), order
    kept. The last frame is always kept, so a batch's id is unchanged."""
    seen: set = set()
    kept = []
    for f in reversed(frames):
        key = _coalesce_key(f)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        kept.append(f)
    kept.reverse()
    return kept


# ── what reaches a browser ──
# Account-state events, minted by the relay where the state changes (events.publish_state /
# on_commit):
#   session_dead         {dead, reason}     account_health mark/clear
#   account_active       {active}           account_health deactivate/activate
#   proxy_switched       {proxied}          proxies.save, per account whose egress changed;
#                        {proxied, down}    proxy_health, per account on a proxy gone down / back up
#   rule_run_finished    {run_id, kind, status, rule_id}  automation_executor._finalize_run,
#                                           after the run's job is written too
#   scheduled_send_changed {job_id}         a scheduled send queued, cancelled,
#                                           claimed or finished
#   permissions_changed  {}  (Agency-wide)  a roles blob write; the stream
#                                           ends after it so the browser
#                                           reconnects under the new role (a
#                                           stream's chat-history grant,
#                                           `readable`, is read at connect)
#   assignment_changed   {}  (Agency-wide)  Creator grants of the Agency's
#                                           owner or its chatters changed; the
#                                           stream ends after it so the browser
#                                           reconnects under fresh grants
#   agency_notifications {unread}  (the owner's sessions only, `owner_audience`)
#                                           an agency notification filed or read
#                                           (notifications_api)
#   sessions_revoked     {}  (one sign-in's sessions, `sessions_audience`)
#                                           its cookies were revoked
#                                           (account_security); the stream ends
#                                           after it, so a revoked cookie's
#                                           reconnect is refused
STATE_TYPES = frozenset({
    "session_dead",
    "account_active",
    "proxy_switched",
    "rule_run_finished",
    "scheduled_send_changed",
    "permissions_changed",
    "assignment_changed",
    "agency_notifications",
    "sessions_revoked",
})
# The state events a stream ends after: its browser reconnects, and the
# reconnect reads the session afresh.
ENDS_STREAM = frozenset({"permissions_changed", "assignment_changed", "sessions_revoked"})

# The SSE allow-list: the event types a browser tab listens for
# (`eventBus.on(...)` in app/). Every other OF frame (`chat_messages`
# counters, `stories`, `connected`, ...) is still persisted to event_inbox
# but is not serialized and pushed to every open tab. Add a type here when a
# UI listener for it lands. (`ping` is minted by events_wire.ping, not here.)
SSE_TYPES = frozenset({
    "api2_chat_message",
    "toasts",
    "transaction_recorded",
    "purchase_notified",
    "chat_typing",
    # A mass message's OF queue progress, as OF sends it (`{id, total,
    # pending, isDone, isCanceled, ...}`, id = the broadcast's queue id): the
    # Mass messages list shows "Sending…" and refreshes on the finish frame.
    # Only the finish frame's `total` is trustworthy (event_transcoder).
    "chat_queue_update",
    "chat_queue_finish",
    # A person's DM through the relay (server._record_fan_send; any-scope): the bell's "<by> has responded",
    # and other tabs move the fan's row in their cached chat lists (app hooks/useInboxRealtime.ts).
    "chat_responded",
    # The App-open warm read a Creator (app_open_warm; any-scope): the tab writes the roster and
    # notif counts it carries and re-reads the notif lists it read before the warm.
    "creator_warmed",
    # The Shared refresher's per-Creator snapshot changed (shared_refresher; any-scope, coalesced per Creator).
    "creator_refreshed",
    # A chatter's read flip through the relay (server._publish_read_flip; any-scope): other tabs flip the row's unread
    # flags in their cached chat lists (app hooks/useAccountStateEvents.ts).
    "chat_read_changed",
}) | STATE_TYPES

# Account events that reach a model-scoped subscriber for every Creator in its clamp, not only
# the one its scope names (`wants`): `creator_warmed`, `creator_refreshed`, `chat_read_changed`, `chat_responded` (a tab's
# cached All Models lists hold every Creator) and what the Money Rail and the bell seed from: `transaction_recorded`, `purchase_notified`, and a `toasts` frame holding a tip or
# purchase toast (`is_money_toast`; any other toast routes by scope).
ANY_SCOPE_TYPES = frozenset({"creator_warmed", "creator_refreshed", "chat_read_changed", "chat_responded",
                             "transaction_recorded", "purchase_notified", "toasts"})
# OF's toast types the app reads as money (app/lib/notifSettings.ts mapOfTypeToKey: tip, purchases).
MONEY_TOAST_TYPES = frozenset({"tip", "tips", "purchase", "purchases", "paided_message"})

# OF's home-feed frames. On a creator account that follows other creators
# they are ~82% of all WS traffic (2 days, one account: 8,451 of 10,308
# event_inbox rows), nothing reads them, and the expire/updated frames carry
# only a bare post id. Dropped before persist and fan-out; a
# `post_published` of the account's OWN post is kept.
FEED_POST_TYPES = frozenset({
    "post_published", "post_expire", "post_updated", "post_fundraising_updated",
})


def is_feed_noise(event: Any, account_id: Any) -> bool:
    """Another creator's home-feed frame (FEED_POST_TYPES): dropped before persist and fan-out."""
    event_type = first_key(event)
    if event_type not in FEED_POST_TYPES:
        return False
    payload = event.get(event_type)
    if isinstance(payload, dict) and account_id is not None \
            and str(payload.get("user_id")) == str(account_id):
        return False
    return True


def typing_fan_id(payload: Any) -> Optional[int]:
    """The fan of an inbound OF `typing` frame: the first int-able of id / user_id / fromUser.id /
    user.id; None when there is none."""
    if not isinstance(payload, dict):
        return None
    for v in (payload.get("id"), payload.get("user_id"),
              (payload.get("fromUser") or {}).get("id") if isinstance(payload.get("fromUser"), dict) else None,
              (payload.get("user") or {}).get("id") if isinstance(payload.get("user"), dict) else None):
        try:
            if v is not None:
                return int(v)
        except (TypeError, ValueError):
            continue
    return None


def typing_due(last_at: Optional[float], now: float, throttle: float) -> bool:
    """Whether a fan's typing frame goes out as `chat_typing`: none sent yet (`last_at` None), or
    `throttle` seconds or more since the last one."""
    return last_at is None or now - last_at >= throttle


# ── routing ──
def sees(scope: str, accounts: Optional[frozenset], account_id: Any, any_scope: bool = False) -> bool:
    """A subscriber of `scope` clamped to `accounts` (None: unclamped) sees `account_id`'s events;
    `any_scope` (an ANY_SCOPE event): a model-scoped one sees every Creator in its clamp."""
    aid = str(account_id)
    if scope != "all" and scope != f"model:{aid}":
        if not (any_scope and scope.startswith("model:") and accounts is not None):
            return False
    return accounts is None or aid in accounts


def is_money_toast(event: Mapping) -> bool:
    """A `toasts` frame (OF's list of toasts) holding a tip or purchase toast."""
    items = event.get("toasts")
    return isinstance(items, list) and any(
        isinstance(t, dict) and str(t.get("type") or "").lower() in MONEY_TOAST_TYPES for t in items)


def any_scope(event: Mapping) -> bool:
    """`event` routes any-scope (ANY_SCOPE_TYPES; a `toasts` frame only when it holds money)."""
    kind = first_key(event)
    return kind in ANY_SCOPE_TYPES and (kind != "toasts" or is_money_toast(event))


def wants(scope: str, accounts: Optional[frozenset], agencies: frozenset, event: Mapping) -> bool:
    """Whether `event` may reach a subscriber (see "Routing")."""
    agency = event.get("__agency")
    if agency is not None:
        return str(agency) in agencies
    account_id = event.get("__account_id")
    if account_id is None:
        return scope == "all" and accounts is None
    return sees(scope, accounts, account_id, any_scope(event))


def strips_message(readable: Optional[frozenset], event: Mapping) -> bool:
    """`event` is a `chat_responded` carrying `message` (reply text, price) for a Creator outside `readable`, the
    Creators whose chats the subscriber's role may read (None: every one): it reaches that subscriber without it."""
    body = event.get("chat_responded")
    return (readable is not None and isinstance(body, dict) and "message" in body
            and str(event.get("__account_id")) not in readable)


# ── the rings ──
def _missed(st: Rings, last_id: Optional[str], sees: Callable[[str], bool],
            wants: Callable[[Any], bool], sees_any: Optional[Callable[[str], bool]] = None) -> tuple[list, bool]:
    """What the stream missed after `last_id`, oldest first, and whether it must resync. A ring the
    stream does not `sees` but `sees_any` (a model-scoped stream's other clamped Creators) is read
    too, `wants` keeping only its any-scope frames, and resyncs only when one of those was evicted."""
    if not last_id:
        return [], False
    epoch, _, n = last_id.partition(".")
    try:
        since = int(n)
    except ValueError:
        return [], True
    if epoch != st.epoch or since > st.seq:
        return [], True
    gap = False
    missed: list[tuple[int, Any]] = []
    for key, ring in st.rings.items():
        if not key or sees(key):
            evicted = st.evicted
        elif sees_any is not None and sees_any(key):
            evicted = st.evicted_any
        else:
            continue
        if evicted.get(key, 0) > since:
            gap = True
        missed.extend((seq, f) for seq, f in ring if seq > since and wants(f))
    missed.sort(key=lambda t: t[0])
    return [f for _, f in missed], gap


def decide_ring(st: Rings, ev: Published) -> Rings:
    """The rings after `ev.frame` takes the next seq; its SSE id is `head_id` of them."""
    seq = st.seq + 1
    key = ring_key(ev.frame)
    ring = st.rings.get(key, ())
    evicted, evicted_any = st.evicted, st.evicted_any
    if len(ring) == RING_MAX:
        dropped, frame = ring[0]
        evicted = {**evicted, key: dropped}
        if isinstance(frame, Mapping) and any_scope(frame):
            evicted_any = {**evicted_any, key: dropped}
        ring = ring[1:]
    return Rings(st.epoch, seq, {**st.rings, key: ring + ((seq, ev.frame),)}, evicted, evicted_any)


def ended_since(st: Rings, since: int, wants: Callable[[Any], bool]) -> bool:
    """Whether a stream-ending frame `wants` admits took a seq after `since`: a grant read at `since` (server
    .sse_events' `readable`) may predate it, so the stream must end before it emits anything. Fails closed when
    the Agency-wide ring (where every ENDS_STREAM frame lands) evicted past `since`."""
    if st.evicted.get("", 0) > since:
        return True
    for ring in st.rings.values():
        for seq, f in reversed(ring):
            if seq <= since:
                break
            if first_key(f) in ENDS_STREAM and wants(f):
                return True
    return False


def replay(st: Rings, last_id: Optional[str], sees: Callable[[str], bool], wants: Callable[[Any], bool],
           knobs: Knobs, sees_any: Optional[Callable[[str], bool]] = None) -> tuple[RingEffect, ...]:
    """What a stream opening with `last_id` is sent before its live events: Resync?, Emit per chunk
    (BATCH_MAX when batching is on, else 1; each coalesced), Head. `sees(key)`: the stream sees that
    account's ring; `sees_any(key)`: it gets that account's any-scope events (ANY_SCOPE_TYPES);
    `wants(frame)`: that frame may reach it."""
    missed, gap = _missed(st, last_id, sees, wants, sees_any)
    effects: list[RingEffect] = [Resync()] if gap else []
    step = BATCH_MAX if batching_on(knobs) else 1
    effects.extend(Emit(tuple(coalesce(missed[i:i + step]))) for i in range(0, len(missed), step))
    effects.append(Head(head_id(st)))
    return tuple(effects)


# ── a stream's batching ──
def decide_stream(st: Stream, ev: Deliver) -> tuple[Stream, StreamEffect]:
    rate = rate_now(st, ev.now) + 1 / RATE_TAU_S
    nxt = Stream(rate, ev.now)
    if ev.open_n and ev.open_n < BATCH_MAX and ev.now < ev.open_deadline:
        # Nothing may follow a stream-ending frame into this session's stream: it closes the batch.
        return nxt, Append(close=ev.ends)
    window = window_s(rate, ev.knobs)
    if window <= 0 or ev.ends:
        return nxt, Send()
    return nxt, Open(ev.now + window)


# ── the persist worker's batch ──
# OF frames worth delivering live but not worth a row: `typing` repeats every
# ~2-3 s per typing fan and nothing reads it back from event_inbox.
UNPERSISTED_TYPES = frozenset({"typing"})


def inbox_row(account_id: Optional[str], event_type: Optional[str], payload: Any) -> dict:
    """One `insert_events` row for an OF frame."""
    event_type = event_type or "unknown"
    # OF events sometimes carry an `id` field at top level — use it as the
    # dedup key when present so re-deliveries (reconnect replays) don't
    # double-write.
    provider_id = None
    if isinstance(payload, dict):
        for k in ("id", "messageId", "eventId"):
            v = payload.get(k)
            if v is not None:
                provider_id = f"{event_type}:{v}"
                break
    return {"account_id": account_id, "source": "of_ws", "event_type": event_type,
            "payload": payload, "provider_event_id": provider_id}


class PersistItem(NamedTuple):
    """One OF frame on the persist worker's queue."""
    account_id: Optional[str]
    event_type: Optional[str]
    persistable: dict      # the frame minus its `__` sentinels: the event_inbox payload
    event: dict            # the frame as received: what the worker transcodes
    inbound_dm: bool = False   # a Fan's DM (event_transcode_decide.is_inbound_dm): kept over the rest


def persist_plan(batch: list[PersistItem]) -> list[dict]:
    """One drained batch -> its event_inbox rows, in queue order; an UNPERSISTED_TYPES item
    gets none (it is still transcoded)."""
    return [inbox_row(it.account_id, it.event_type, it.persistable)
            for it in batch if it.event_type not in UNPERSISTED_TYPES]
