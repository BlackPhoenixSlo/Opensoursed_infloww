"""
The relay's SSE fan-out (`GET /events`): the shell. Module map:

  events.py          this shell: the subscriber registry (`_subs`), the replay
                     ring state (`_ring`), `handle_event` (server._broadcast_event's
                     hook for every OF-WS frame), `broadcast` / `publish` /
                     `publish_state` / `on_commit`, `sse_stream` (the
                     StreamingResponse body) and typing's throttle state. It reads
                     the clock, keeps state and performs effects; everything runs
                     on the event loop's thread (other threads via `publish`).
  events_decide.py   pure: routing (`sees` / `wants`), the type sets and feed /
                     typing classifiers, the replay rings, load-adaptive batching,
                     the persist plan. Called as `ed.<name>` at call time.
  events_wire.py     pure: the SSE bytes (frames, batch frames, resync, head, ping).
  events_persist.py  the event_inbox queue and its worker (enqueue, transcode).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import AsyncIterator, Awaitable, Callable

from fastapi import Request

import chatter_identity_cache
import events_decide as ed
import events_persist
import events_wire as ew
from db import write_telemetry

log = logging.getLogger("of-relay.events")

# Owner contract: old names kept for importers/tests; new code uses ed./ew.
_Frame = ew.Frame
STATE_TYPES = ed.STATE_TYPES
SSE_TYPES = ed.SSE_TYPES
_ENDS_STREAM = ed.ENDS_STREAM
is_feed_noise = ed.is_feed_noise
_frame_json = ew.frame_json
_sse_frame = ew.sse_frame
_sse_out = ew.sse_out
_RESYNC = ew.RESYNC

# Maximum queued events per subscriber. Tuned for "bursty inbound + slow
# browser" — at 256, a 100 events/sec spike rides through without drops,
# but a wedged tab (laptop sleeping) gets evicted within seconds rather
# than ballooning memory.
_QUEUE_MAX = 256

# Heartbeat interval. Two pings fly on this cadence:
#   1. `: ping\n\n` — SSE comment, keeps proxies/CDNs from idle-closing
#      the TCP socket (their ~60 s threshold).
#   2. `event: ping\ndata: {...}\n\n` — named event the browser bumps
#      `lastEventAt` on, so the frontend's `isConnected()` can degrade
#      when the upstream OF-WS pump stalls but the socket stays open.
# 20 s gives the frontend two missed pings before its 45 s STALE_MS
# boundary trips — robust without being slow.
_HEARTBEAT_S = 20


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, os.environ.get(name), default)
        return default


# ── Load-adaptive batching (relay → browser) ─────────────────────────
#
# A tab whose stream runs hot gets its events grouped into `event: batch`
# frames (`ew.sse_out`), which the browser applies in one render pass. The rules
# (rate threshold, windows, batch size, coalescing) are `events_decide`'s
# docstring and `decide_stream`, a pure function (tables:
# tests/test_events_decide.py); `_deliver` is its shell. The subscriber
# queue holds batches, not events, so `_QUEUE_MAX` bounds how many windows a
# stalled tab may fall behind before it is sent `resync`.
# SSE_BATCH_WINDOW_MS=0 turns batching off; SSE_BATCH_MIN_RATE=0 forces it on.
SSE_BATCH_MIN_RATE = _env_float("SSE_BATCH_MIN_RATE", 5.0)
SSE_BATCH_WINDOW_MS = _env_float("SSE_BATCH_WINDOW_MS", 100.0)
SSE_BATCH_MAX_WINDOW_MS = _env_float("SSE_BATCH_MAX_WINDOW_MS", 250.0)


def _knobs() -> ed.Knobs:
    return ed.Knobs(SSE_BATCH_MIN_RATE, SSE_BATCH_WINDOW_MS, SSE_BATCH_MAX_WINDOW_MS)


class _Batch(list):
    """Frames bound for one `event: batch` frame, oldest first. It sits in the
    subscriber's queue while still open; `deadline` (monotonic) is when it
    closes, 0 when it must go out as soon as the stream reaches it."""
    __slots__ = ("deadline",)


class _Sub:
    """One SSE subscriber: its queue, scope, and what its session may see.
    `accounts` None is unclamped (the anonymous escape hatch, tests);
    `agencies` are the owner user ids whose Agency-wide events it gets.
    `lost` is set when the queue overflowed, so the stream sends `resync`.
    `batching` is set for sse_stream's subscribers (a bare `subscribe()`
    queue always gets single frames); `st` is its decaying events/s
    (ed.Stream), `open` the batch still taking events, `batches`/`coalesced`
    counters for /admin/events/stats."""
    __slots__ = ("q", "scope", "accounts", "agencies", "lost", "batching",
                 "st", "open", "batches", "coalesced")

    def __init__(self, scope: str, accounts: frozenset[str] | None,
                 agencies: frozenset[str]):
        self.q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self.scope = scope
        self.accounts = accounts
        self.agencies = agencies
        self.lost = False
        self.batching = False
        self.st = ed.Stream(rate_at=time.monotonic())
        self.open: _Batch | None = None
        self.batches = 0
        self.coalesced = 0


# Subscriber registry, by queue. Only touched on the event loop's thread and
# never across an await, so it needs no lock; other threads reach the fan-out
# through `publish` (call_soon_threadsafe).
_subs: dict[asyncio.Queue, _Sub] = {}
_loop: asyncio.AbstractEventLoop | None = None


# ── Replay ring (Last-Event-ID) ──────────────────────────────────────
#
# Ids, ring size, eviction and what a reconnect replays (or answers with
# `resync`, the browser refetches) are `events_decide.decide_ring` / `replay`,
# pure functions; `_ring` is their state, touched only on the event loop's
# thread. RAM only: a deploy loses the rings, and a new `_EPOCH` makes every
# old id resync.
_EPOCH = format(int(time.time() * 1000), "x")
_ring = ed.Rings(_EPOCH)


# ── Shutdown ─────────────────────────────────────────────────────────

# Set on SIGTERM (server._close_streams_on_term): every open stream ends within
# one queue poll, so uvicorn's graceful wait finishes instead of cancelling each
# stream mid-await (one "Exception in ASGI application" traceback apiece) and
# the shutdown hook — the automation drain — runs in the stop budget.
_closing = False


def close_streams() -> None:
    global _closing
    _closing = True


# Inbound "fan is typing" (OF frame `{"typing": {"id": <fan id>}}`), forwarded
# to the browser as `chat_typing` at most once per fan per _TYPING_THROTTLE_S.
# OF re-sends the frame every ~2-3 s while the fan types and the UI hint lasts
# a few seconds, so one push per window is all a tab needs.
_TYPING_THROTTLE_S = 3.0
_typing_last: dict[tuple[str, int], float] = {}
_typing_shape_logged = False


async def _forward_typing(account_id: object, payload: object) -> None:
    global _typing_shape_logged
    if not _typing_shape_logged:
        # We have never captured one of these on the pump; log the first so the
        # shape can be confirmed against a real frame.
        _typing_shape_logged = True
        log.info("first inbound typing frame: %s", json.dumps(payload, default=str)[:300])
    fan_id = ed.typing_fan_id(payload)
    if account_id is None or fan_id is None:
        return
    key = (str(account_id), fan_id)
    now = time.monotonic()
    if not ed.typing_due(_typing_last.get(key), now, _TYPING_THROTTLE_S):
        return
    if len(_typing_last) > 10_000:
        _typing_last.clear()
    _typing_last[key] = now
    await broadcast({"chat_typing": {"fan_id": fan_id}, "__account_id": str(account_id)})


# ── Subscriber lifecycle ─────────────────────────────────────────────

async def subscribe(
    scope: str, *, accounts: frozenset[str] | None = None,
    agencies: frozenset[str] = frozenset(),
) -> asyncio.Queue:
    """Return a fresh queue subscribed to `scope`. Caller MUST unsubscribe.

    Scope grammar:
      • "all"               — every event the session sees
      • "model:<account_id>" — events tagged with that __account_id

    `accounts` are the Creators the session may see (None: unclamped) and
    `agencies` the owner user ids whose Agency-wide events it gets.

    Unknown scopes are accepted (registered but never matched), so the
    browser doesn't 500 on a typo — it just sees no traffic and reconnects.
    """
    return _register(scope, accounts, agencies).q


def _register(scope: str, accounts: frozenset[str] | None,
              agencies: frozenset[str]) -> _Sub:
    global _loop
    _loop = asyncio.get_running_loop()
    sub = _Sub(scope, accounts, agencies)
    _subs[sub.q] = sub
    return sub


async def unsubscribe(scope: str, q: asyncio.Queue) -> None:
    _subs.pop(q, None)


def subscriber_count(scope: str | None = None) -> int:
    """For health / debug."""
    return sum(1 for s in list(_subs.values()) if scope is None or s.scope == scope)


def _wants(sub: _Sub, event: dict) -> bool:
    """Whether `event` may reach `sub` (events_decide "Routing")."""
    return ed.wants(sub.scope, sub.accounts, sub.agencies, event)


# ── Event ingest ────────────────────────────────────────────────────

async def handle_event(event: dict) -> None:
    """Called by server.py's `_broadcast_event` for every OF event.

    Responsibilities:
      1. Persist to event_inbox (async fire-and-forget — never blocks the
         WS pump on a slow SQL write).
      2. Push to every matching subscriber queue.

    The event dict carries the relay's `__account_id` / `__account_name`
    /  `__account_color` sentinel keys plus the OF-native top-level event
    name(s). We strip `__`-prefixed keys before persisting (they're our
    metadata, not OF's), but they stay in the SSE payload so the browser
    knows which model an event belongs to.
    """
    account_id = event.get("__account_id") if isinstance(event, dict) else None
    # Pick the first non-sentinel key as the event_type (OF puts the type
    # at the top level — e.g. `{"newMessage": {...}}`).
    event_type = ed.first_key(event)
    write_telemetry.frame(account_id, event_type, event)

    if ed.is_feed_noise(event, account_id):
        return
    if event_type == "typing":
        # Forwarded as `chat_typing`, then down the normal path minus the
        # event_inbox row (events_decide.UNPERSISTED_TYPES): the persist worker's transcode
        # still touches the Fan row from the frame
        # (event_transcoder._touch_fan_from_event), and the raw `typing` frame
        # itself is not an SSE type, so broadcast() below drops it.
        await _forward_typing(account_id, event.get("typing"))

    # Strip sentinels for the persisted payload — it's already inferable
    # from `account_id`, no need to duplicate.
    persistable = {k: v for k, v in event.items() if not k.startswith("__")} if isinstance(event, dict) else {}

    # Enqueue for the persist worker (events_persist: bounded, drops the
    # oldest on overflow; before the worker starts, the old fire-and-forget path).
    events_persist.enqueue(account_id, event_type, persistable, event)

    # Fan out to subscribers — scope "all" + scope-by-account.
    await broadcast(event)


async def broadcast(event: dict) -> int:
    """Fan ONE event out to every matching SSE subscriber queue — and nothing
    else (no event_inbox persist, no transcode). `handle_event` uses this for
    OF-WS events after it persists; `publish_db_message` uses it directly for
    a worker-written row that's ALREADY in the DB (re-persisting/transcoding
    would double-write the canonical message row).

    Routing: `_wants` — the subscriber's scope, Creators and Agencies.

    Returns how many subscriber queues the event was handed to. SSE has no
    mailbox — with nobody subscribed this is a silent no-op, not a delivery —
    so a caller sending a ONE-SHOT announcement can tell whether to remember it
    as sent or offer it again later (see
    `purchase_notifications._broadcast_purchase`). Reading the count off the
    fan-out itself, rather than asking a second routing-aware helper, is what
    keeps "who would receive this" from drifting away from who actually did.
    (The replay ring does not count: it only serves a tab that was connected
    and dropped.)
    """
    return _fanout(event)


# A sale this old announces nothing when its writer caps it: a cold backfill
# inserts hundreds of ancient rows nobody has open.
_ANNOUNCE_MAX_AGE = timedelta(hours=48)
_JS_SAFE_INT = 2 ** 53 - 1


async def announce_transaction(
    account_id: object, fan_id: int, *, occurred_at: datetime | None = None, capped: bool = False,
    **fields: object,
) -> None:
    """`transaction_recorded {fan_id, **fields}` for a ledger write, sent by
    its writer AFTER the commit so the browser's refetch reads the row: the
    fan drawer's revenue caches (useInboxRealtime) and the open reports
    (useAccountStateEvents) refetch on it. `capped`: a sale whose
    `occurred_at` is unknown or older than 48h announces nothing. The fan id
    travels as the browser keys its caches (app/lib/fanId.ts
    `fanIdFromParam`): a number while JS holds it exactly, else the string (a
    Fansly snowflake). No amount: every session of the Creator gets it,
    chatters whose role hides revenue too, and the refetch reads it anyway.
    Best-effort: the write already happened."""
    if capped and (occurred_at is None or occurred_at < datetime.utcnow() - _ANNOUNCE_MAX_AGE):
        return
    try:
        fid = int(fan_id)
        await broadcast({
            "transaction_recorded": {"fan_id": fid if abs(fid) <= _JS_SAFE_INT else str(fid), **fields},
            "__account_id": str(account_id),
        })
    except Exception:
        log.debug("transaction_recorded broadcast failed", exc_info=True)


def _fanout(event: dict) -> int:
    """`broadcast`'s body, synchronous so `publish` can run it from another
    thread through call_soon_threadsafe. Allow-list, id + ring
    (ed.decide_ring), delivery."""
    global _ring
    if ed.first_key(event) not in ed.SSE_TYPES:
        return 0
    frame = ew.Frame(event)
    frame.t = time.monotonic()
    _ring = ed.decide_ring(_ring, ed.Published(frame))
    frame.eid = ed.head_id(_ring)

    knobs = _knobs()
    ends = ed.first_key(frame) in ed.ENDS_STREAM
    delivered = 0
    for sub in list(_subs.values()):
        if not _wants(sub, frame):
            continue
        delivered += 1
        _deliver(sub, frame, ends, knobs)
    return delivered


def _deliver(sub: _Sub, frame: ew.Frame, ends: bool, knobs: ed.Knobs) -> None:
    """Hand `frame` to `sub` as ed.decide_stream says: into its open batch, as
    a new batch when its rate calls for one, else on its own (see
    "Load-adaptive batching"). The open batch is the queue item itself."""
    if not sub.batching:
        _put(sub, frame)
        return
    b = sub.open
    sub.st, e = ed.decide_stream(sub.st, ed.Deliver(
        time.monotonic(), ends, len(b) if b is not None else 0, b.deadline if b is not None else 0.0, knobs))
    if isinstance(e, ed.Append):
        assert b is not None  # decide appends only to an open batch
        b.append(frame)
        if e.close:
            b.deadline = 0.0
            sub.open = None
    elif isinstance(e, ed.Send):
        sub.open = None
        _put(sub, frame)
    elif isinstance(e, ed.Open):
        nb = _Batch((frame,))
        nb.deadline = e.deadline
        sub.open = nb
        _put(sub, nb)


def _put(sub: _Sub, item: ew.Frame | _Batch) -> None:
    try:
        sub.q.put_nowait(item)
    except asyncio.QueueFull:
        # Drop oldest, push new — slow tab loses history, not freshness;
        # `lost` makes its stream send `resync` so it refetches. (What is
        # dropped is never the open batch: `_deliver` lets that go or
        # replaces it before every put.)
        sub.lost = True
        with contextlib.suppress(asyncio.QueueEmpty):
            sub.q.get_nowait()
        try:
            sub.q.put_nowait(item)
        except Exception:
            # Truly dead — let the SSE generator notice on its next get().
            pass


def publish(event: dict) -> None:
    """Fan a relay-minted event out from any thread (a sync route runs in the
    threadpool). On the loop's thread, or before any loop is known, inline;
    elsewhere handed to the loop, so the registry and rings are only ever
    touched there."""
    try:
        asyncio.get_running_loop()
        inline = True
    except RuntimeError:
        inline = _loop is None or _loop.is_closed()
    if inline:
        _fanout(event)
    else:
        _loop.call_soon_threadsafe(_fanout, event)  # type: ignore[union-attr]


def owner_audience(user_id: object) -> str:
    """The `agency` of an event for the Agency owner's own sessions, not its
    chatters': an owner's stream subscribes to it beside its Agency id
    (server.sse_events), a chatter's never does."""
    return f"owner:{user_id}"


def sessions_audience(kind: str, principal_id: object) -> str:
    """The `agency` of `sessions_revoked` for one sign-in (`kind` "user" or
    "chatter"): every stream it opens subscribes to it (server.sse_events)."""
    return f"sessions:{kind}:{principal_id}"


def publish_state(
    event_type: str, *, account_id: object = None, agency: object = None, **fields: object,
) -> None:
    """Push one account-state event (STATE_TYPES): for `account_id`'s
    sessions, or Agency-wide for `agency` (an owner user id). Best-effort:
    a fan-out hiccup must never fail the change it reports."""
    if event_type in ed.ENDS_STREAM:
        chatter_identity_cache.invalidate()  # before the event goes out: a reconnect reads the new grants
    event: dict = {event_type: fields}
    if account_id is not None:
        event["__account_id"] = str(account_id)
    if agency is not None:
        event["__agency"] = str(agency)
    try:
        publish(event)
    except Exception:
        log.exception("publish_state failed (type=%s)", event_type)


def on_commit(session, event_type: str, **kw: object) -> None:
    """`publish_state(event_type, **kw)` once `session` (an AsyncSession)
    commits, and never if it rolls back, so a browser that refetches on the
    event reads the new state."""
    from sqlalchemy import event as sa_event
    sa_event.listen(session.sync_session, "after_commit",
                    lambda _s: publish_state(event_type, **kw), once=True)


async def publish_db_message(
    *,
    account_id: str,
    fan_id: int,
    message_id: int,
    body: str = "",
    created_at: object | None = None,
    price_cents: int = 0,
    media: list | None = None,
    media_count: int = 0,
    sender_name: str = "",
) -> None:
    """WORKER→SSE BRIDGE. Emit a synthetic `api2_chat_message` event for an
    OUTBOUND `messages` row a background worker just wrote, so an open chat
    updates live instead of only on the next refetch.

    Why this is needed: the OF-WS pump deliberately skips outbound events, so a
    worker write (welcome / AI reply / follow-up / mass / funnel) has no live
    path. We mint the same `api2_chat_message` envelope the frontend already
    consumes — BUT OF's native outbound event omits the recipient, so we also
    carry `__fan_id` (the open chat the patcher must target). `fromUser.id`
    equals `account_id` (the creator's OF user id), which is how the frontend
    marks the bubble outbound (event_transcoder §direction / useInboxRealtime).

    Fan-out ONLY — the row is already persisted; this never touches the DB.
    Best-effort: a broadcast hiccup must never fail the worker's send.
    """
    try:
        try:
            of_uid: object = int(account_id)
        except (TypeError, ValueError):
            of_uid = account_id
        # Naive datetimes are UTC wall-clock in this codebase (datetime.utcnow /
        # _parse_iso strips tzinfo) — tag them 'Z' so SSE consumers don't render
        # them in the VIEWER's local zone (this is what made live worker bubbles
        # show the wrong time + sort out of order). An aware datetime already
        # carries its offset; a plain string is passed through untouched.
        if hasattr(created_at, "isoformat"):
            created = created_at.isoformat()
            if getattr(created_at, "tzinfo", None) is None:
                created += "Z"
        else:
            created = created_at or None
        event = {
            "api2_chat_message": {
                "id": int(message_id),
                "text": body or "",
                "fromUser": {"id": of_uid, "name": sender_name or ""},
                "toUser": {"id": int(fan_id)},
                "createdAt": created,
                "mediaCount": int(media_count or 0),
                "media": media or [],
                "price": (price_cents or 0) / 100.0,
            },
            "__account_id": str(account_id),
            "__fan_id": int(fan_id),  # OF omits the recipient on outbound — carry it
        }
        await broadcast(event)
    except Exception:
        log.exception("publish_db_message failed (account=%s fan=%s msg=%s)",
                      account_id, fan_id, message_id)


async def publish_chat_responded(
    *, account_id: str, fan_id: int, employee_id: int | None,
) -> None:
    """`chat_responded {fan_id, by}` for `account_id`'s sessions once a person
    sends a fan a DM through the relay (server._record_fan_send), so a
    teammate's bell shows "<by> has responded" on that fan's message rows.
    Its own type, not an `api2_chat_message`: the sender's tab already holds
    the bubble (see test_sse_bridge's human path). Best-effort."""
    try:
        by = ""
        if employee_id is not None:
            from db.engine import get_session
            from db.models import Employee
            async with get_session() as s:
                e = await s.get(Employee, int(employee_id))
            by = e.display_name if e is not None else ""
        publish({"chat_responded": {"fan_id": int(fan_id), "by": by},
                 "__account_id": str(account_id)})
    except Exception:
        log.exception("publish_chat_responded failed (account=%s fan=%s)", account_id, fan_id)


def start_persist_worker() -> None:
    """Start the singleton persist worker (events_persist). Idempotent.

    Must be called from inside the running event loop (e.g. FastAPI's
    `@app.on_event("startup")`), after `init_db()` but before any WS pump
    spawns — otherwise the first burst of events takes the pre-startup
    fallback path in `events_persist.enqueue`.
    """
    global _loop
    if events_persist.start_persist_worker():
        _loop = asyncio.get_running_loop()   # where `publish` hands other threads' events


# ── SSE generator (FastAPI StreamingResponse body) ──────────────────

def sse_stats() -> dict:
    """Per open stream: its mode right now, decayed rate, window, queue depth
    and counters — for /admin/events/stats. No scopes or account ids."""
    now = time.monotonic()
    knobs = _knobs()
    streams = []
    for sub in list(_subs.values()):
        rate = ed.rate_now(sub.st, now)
        window = ed.window_s(rate, knobs) if sub.batching else 0.0
        streams.append({
            "mode": "batch" if window else "immediate" if sub.batching else "queue",
            "rate": round(rate, 2),
            "window_ms": round(window * 1000),
            "queued": sub.q.qsize(),
            "batches": sub.batches,
            "coalesced": sub.coalesced,
        })
    return {
        "knobs": {"SSE_BATCH_MIN_RATE": SSE_BATCH_MIN_RATE,
                  "SSE_BATCH_WINDOW_MS": SSE_BATCH_WINDOW_MS,
                  "SSE_BATCH_MAX_WINDOW_MS": SSE_BATCH_MAX_WINDOW_MS},
        "batching": sum(1 for st in streams if st["mode"] == "batch"),
        "streams": streams,
    }


async def sse_stream(
    request: Request, scope: str, *, accounts: frozenset[str] | None = None,
    agencies: frozenset[str] = frozenset(), last_event_id: str | None = None,
) -> AsyncIterator[bytes]:
    """Yield SSE-formatted bytes for one subscriber. Handles:
      • Initial `: connected` comment so the browser's onopen fires.
      • Last-Event-ID resumption: what the rings hold after that id for
        this subscriber, oldest first, after a `resync` frame when they no
        longer reach back that far; then an id-only frame naming the head
        at connect, so a drop before the next event resumes from there.
      • Heartbeat comments every _HEARTBEAT_S seconds.
      • JSON-encoded events with `event:` line set to the OF event type, or
        grouped into `event: batch` frames while the stream runs hot (see
        "Load-adaptive batching").
      • `resync` when this subscriber's queue overflowed.
      • Ending after an `assignment_changed` it was sent: its Creators may
        have changed, and the browser's reconnect reads them afresh. The
        same after a `sessions_revoked`: a revoked cookie's reconnect is 401.
      • Graceful unsubscribe when the client disconnects.

    `accounts` / `agencies`: see `subscribe`. The bytes: events_wire.
    """
    # Register and read the rings in one synchronous step: every event up to
    # the head is in the rings, every later one lands in the queue.
    sub = _register(scope, accounts, agencies)
    sub.batching = True
    # A replay is a burst by definition: batched whenever batching is on,
    # so a tab waking from idle applies it in one pass, not hundreds.
    replay = ed.replay(_ring, last_event_id, lambda key: ed.sees(sub.scope, sub.accounts, key),
                       lambda f: _wants(sub, f), _knobs())
    q = sub.q
    try:
        yield ew.CONNECTED
        for e in replay:
            if isinstance(e, ed.Resync):
                yield ew.RESYNC
            elif isinstance(e, ed.Emit):
                yield ew.sse_out(e.frames)
            elif isinstance(e, ed.Head):
                yield ew.head(e.eid)
        last_beat = time.monotonic()
        while True:
            if _closing or await request.is_disconnected():
                return
            if sub.lost:
                sub.lost = False
                yield ew.RESYNC
            try:
                event = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if time.monotonic() - last_beat >= _HEARTBEAT_S:
                    yield ew.ping(time.time())
                    last_beat = time.monotonic()
                continue

            if isinstance(event, _Batch):
                # Still open: let it collect until its window closes.
                delay = event.deadline - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                if sub.open is event:
                    sub.open = None
                frames = ed.coalesce(event)
                sub.coalesced += len(event) - len(frames)
                sub.batches += 1
            else:
                frames = [event]
            yield ew.sse_out(frames)
            last_beat = time.monotonic()
            if write_telemetry.ENABLED:
                for f in frames:
                    if "api2_chat_message" in f:
                        write_telemetry.sse_sent((last_beat - getattr(f, "t", last_beat)) * 1000)
            if ed.first_key(frames[-1]) in ed.ENDS_STREAM:
                return
    finally:
        await unsubscribe(scope, q)


# ── Hook installation ───────────────────────────────────────────────

def register_with(
    install: Callable[[Callable[[dict], Awaitable[None]]], None],
) -> None:
    """Called once at startup. Hands `handle_event` to the caller's
    install hook so the relay's `_broadcast_event` fans every OF-WS
    event into it.

    Decoupled like this so this module has zero imports from server.py
    — server.py wires the connection at startup.
    """
    install(handle_event)
