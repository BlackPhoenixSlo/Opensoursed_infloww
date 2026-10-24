"""
SSE broadcaster + event_inbox writer.

This module sits BETWEEN the existing `_broadcast_event` in server.py and
the new browser app. Two responsibilities:

  1. Every event that flows through the OF-WS pump → write a row to
     `event_inbox` (idempotent on `provider_event_id` when present). This
     gives us a durable, queryable record of every OF event for replay,
     debugging, and the phase B canonical-table writer.

  2. Maintain a pool of SSE-style asyncio queues keyed by `scope`. When a
     subscriber connects to `GET /events?scope=...`, they get a queue;
     when an event arrives, it's pushed to every matching queue. Scopes:
       • "all"               — every event of every account the session sees
       • "model:<account_id>" — only that account's events
     Each subscriber carries the session's Creators (`accounts`) and
     Agencies; an event outside them never reaches it (see `_wants`).

  3. Replay. Every pushed event gets an SSE `id:` (`<boot epoch>.<seq>`) and
     a slot in a bounded per-account RAM ring. A reconnect that sends
     `Last-Event-ID` gets what it missed from the rings; when the rings no
     longer reach back that far (overflow, or a relay restart) it gets a
     `resync` frame instead, and the browser refetches.

The original `_broadcast_event` already handles browser WebSocket
delivery via `_event_subscribers`. We add SSE in parallel because:
  • SSE is one-way + native to fetch — simpler client code.
  • SSE survives proxies/CDNs that mangle WebSocket upgrades.
  • EventSource + Last-Event-ID gives reliable replay-on-reconnect that
    we'd otherwise hand-roll on top of WS.

Both transports stay live during the migration; phase B picks one to keep.

API:
    register_with(server_broadcast_fn):
        Wire this module's `handle_event` into the relay's existing
        broadcast pipeline. Called once at startup.

    subscribe(scope) -> Queue:
        Get an asyncio.Queue that yields every matching event.
        Caller MUST also call `unsubscribe(scope, queue)` on disconnect.

    sse_stream(request, scope, ...) -> AsyncIterator[bytes]:
        Convenience generator for FastAPI's StreamingResponse. Handles
        the queue lifecycle, replay, heartbeats, and graceful shutdown.

    publish_state(type, ...) / on_commit(session, type, ...):
        Push an account-state event (`STATE_TYPES`) from any thread, or
        once a DB session commits.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from collections import deque
from datetime import datetime, timedelta
from typing import AsyncIterator, Awaitable, Callable

from fastapi import Request

from db import of_writer, write_telemetry
from db.repo import insert_events

log = logging.getLogger("of-relay.events")

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
# A quiet tab gets every event as its own frame, at once, as always. A tab
# whose own stream runs hotter than SSE_BATCH_MIN_RATE events/s (a decaying
# average over ~1 s, per subscriber) gets them grouped: the first event opens a
# window, everything the tab is sent until it closes rides in ONE `event:
# batch` frame (data: [{id, type, data}, ...], oldest first; the frame's `id:`
# is its last member's, so Last-Event-ID resumes after the whole batch), and
# the browser applies it in one render pass. The window is
# SSE_BATCH_WINDOW_MS, or SSE_BATCH_MAX_WINDOW_MS once the rate passes 10x the
# threshold, so no event waits longer than one window; the stream drops back
# to single frames as soon as the average falls under the threshold again.
# Inside a batch only frames a newer one fully supersedes are dropped (see
# _COALESCE); DMs, money, unread and state events never are. The subscriber
# queue holds batches, not events, so `_QUEUE_MAX` bounds how many windows a
# stalled tab may fall behind before it is sent `resync`.
# SSE_BATCH_WINDOW_MS=0 turns batching off; SSE_BATCH_MIN_RATE=0 forces it on.
SSE_BATCH_MIN_RATE = _env_float("SSE_BATCH_MIN_RATE", 5.0)
SSE_BATCH_WINDOW_MS = _env_float("SSE_BATCH_WINDOW_MS", 100.0)
SSE_BATCH_MAX_WINDOW_MS = _env_float("SSE_BATCH_MAX_WINDOW_MS", 250.0)
# Most events one batch frame carries; a fuller window closes early.
_BATCH_MAX = 200
# Time constant of the per-subscriber rate average, seconds.
_RATE_TAU_S = 1.0
# Per type, the body field that names what a frame is about: within one batch
# only the newest frame per (type, account, that field) is kept. `chat_typing`
# is a "still typing" ping and `chat_queue_update` a mass message's progress,
# so the newest says everything the older ones did.
_COALESCE = {"chat_typing": "fan_id", "chat_queue_update": "id"}


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
    queue always gets single frames); `rate`/`rate_at` are its decaying
    events/s, `open` the batch still taking events, `batches`/`coalesced`
    counters for /admin/events/stats."""
    __slots__ = ("q", "scope", "accounts", "agencies", "lost", "batching",
                 "rate", "rate_at", "open", "batches", "coalesced")

    def __init__(self, scope: str, accounts: frozenset[str] | None,
                 agencies: frozenset[str]):
        self.q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self.scope = scope
        self.accounts = accounts
        self.agencies = agencies
        self.lost = False
        self.batching = False
        self.rate = 0.0
        self.rate_at = time.monotonic()
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
# Every event that passes the allow-list gets the next `_seq` and a slot in
# its account's ring ("" holds the Agency-wide ones). 256 per account covers
# a laptop sleep or a dropped socket on a busy Creator; anything older is
# answered with `resync` (the browser refetches), and so is an id from before
# a relay restart (`_EPOCH` differs). RAM only: a deploy loses the rings,
# which `resync` covers.
_RING_MAX = 256
_EPOCH = format(int(time.time() * 1000), "x")
_seq = 0
_rings: dict[str, deque] = {}
# Per ring, the highest seq it has dropped: a reconnect from below it missed
# something the ring can no longer replay.
_evicted: dict[str, int] = {}


class _Frame(dict):
    """An event as fanned out: the event dict itself (what the browser gets
    as `data:`) plus its SSE id, so queue consumers still read a dict.
    `json` caches its encoding: one encode however many tabs it goes to.
    `t`: monotonic time of the fan-out (write_telemetry's SSE lag)."""
    __slots__ = ("eid", "json", "t")


# ── Persist worker (bounded backpressure) ────────────────────────────
#
# SQLite is single-writer, so spawning one `asyncio.create_task` per event
# for the event_inbox insert AND the transcoder upserts means under a burst
# the pending-task list can balloon faster than the WAL can drain. That's
# the actual failure mode at high WS ingest rates — not the DB itself, but
# unbounded create_task piling up.
#
# Solution: one bounded queue, one consumer task that drains it in order,
# one event_inbox commit per batch of whatever is queued.
# Producers (handle_event) push and never block; on overflow we drop the
# oldest item so freshness wins over completeness. SSE fan-out stays inline
# below so realtime UI is unaffected — only DB writes get queued.
_PERSIST_QUEUE_MAX = 2000
# Most event_inbox rows one commit may carry. The worker drains whatever is
# already queued, up to this, so an idle relay still writes each event at once
# and a busy one (20 feeds) amortizes one commit over everything that arrived
# while the previous one was writing.
_PERSIST_BATCH_MAX = 200
# How long shutdown waits for the queue to be written before it gives up on it.
_STOP_DRAIN_S = 5.0
# OF frames worth delivering live but not worth a row: `typing` repeats every
# ~2-3 s per typing fan and nothing reads it back from event_inbox.
_UNPERSISTED_TYPES = frozenset({"typing"})
_persist_queue: asyncio.Queue | None = None
_persist_worker_task: asyncio.Task | None = None
_persist_drops = 0
_persist_inflight = 0   # events the worker has taken and not finished transcoding


# ── What reaches a browser ───────────────────────────────────────────
#
# The SSE allow-list: the event types a browser tab listens for
# (`eventBus.on(...)` in app/). Every other OF frame — `chat_messages`
# counters, `stories`, `connected`, ... — is still persisted to event_inbox
# but is not serialized and pushed to every open tab. Add a type here when a
# UI listener for it lands. (`ping` is minted inside sse_stream, not here.)
#
# Account-state events (STATE_TYPES) are minted by the relay where the state
# changes, through `publish_state` / `on_commit`:
#   session_dead         {dead, reason}     account_health mark/clear
#   account_active       {active}           account_health deactivate/activate
#   proxy_switched       {proxied}          proxies.save, per account whose egress changed;
#                        {proxied, down}    proxy_health, per account on a proxy gone down / back up
#   rule_run_finished    {run_id, kind, status, rule_id}  automation_executor._finalize_run,
#                                           after the run's job is written too
#   scheduled_send_changed {job_id}         a scheduled send queued, cancelled,
#                                           claimed or finished
#   permissions_changed  {}  (Agency-wide)  a roles blob write
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
_ENDS_STREAM = frozenset({"assignment_changed", "sessions_revoked"})
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
    "chat_responded",
}) | STATE_TYPES

# OF's home-feed frames. On a creator account that follows other creators
# they are ~82% of all WS traffic (2 days, one account: 8,451 of 10,308
# event_inbox rows), nothing reads them, and the expire/updated frames carry
# only a bare post id. Dropped before persist and fan-out; a
# `post_published` of the account's OWN post is kept.
_FEED_POST_TYPES = frozenset({
    "post_published", "post_expire", "post_updated", "post_fundraising_updated",
})


def is_feed_noise(event: object, account_id: object) -> bool:
    event_type = _first_real_key(event)
    if event_type not in _FEED_POST_TYPES:
        return False
    payload = event.get(event_type)  # type: ignore[union-attr]
    if isinstance(payload, dict) and account_id is not None \
            and str(payload.get("user_id")) == str(account_id):
        return False
    return True


# Inbound "fan is typing" (OF frame `{"typing": {"id": <fan id>}}`), forwarded
# to the browser as `chat_typing` at most once per fan per _TYPING_THROTTLE_S.
# OF re-sends the frame every ~2-3 s while the fan types and the UI hint lasts
# a few seconds, so one push per window is all a tab needs.
_TYPING_THROTTLE_S = 3.0
_typing_last: dict[tuple[str, int], float] = {}
_typing_shape_logged = False


def _typing_fan_id(payload: object) -> int | None:
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


async def _forward_typing(account_id: object, payload: object) -> None:
    global _typing_shape_logged
    if not _typing_shape_logged:
        # We have never captured one of these on the pump; log the first so the
        # shape can be confirmed against a real frame.
        _typing_shape_logged = True
        log.info("first inbound typing frame: %s", json.dumps(payload, default=str)[:300])
    fan_id = _typing_fan_id(payload)
    if account_id is None or fan_id is None:
        return
    key = (str(account_id), fan_id)
    now = time.monotonic()
    if now - _typing_last.get(key, float("-inf")) < _TYPING_THROTTLE_S:
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


def _sees_account(sub: _Sub, account_id: str) -> bool:
    if sub.scope != "all" and sub.scope != f"model:{account_id}":
        return False
    return sub.accounts is None or account_id in sub.accounts


def _wants(sub: _Sub, event: dict) -> bool:
    """Whether `event` may reach `sub`. An Agency-wide event (`__agency`)
    goes to that Agency's sessions whatever their scope; an account event
    to sessions that see the account in their scope; an event with neither
    only to an unclamped "all" subscriber."""
    agency = event.get("__agency")
    if agency is not None:
        return str(agency) in sub.agencies
    account_id = event.get("__account_id")
    if account_id is None:
        return sub.scope == "all" and sub.accounts is None
    return _sees_account(sub, str(account_id))


def _replay_since(sub: _Sub, last_event_id: str | None) -> tuple[list[_Frame], bool]:
    """What `sub` missed after `last_event_id`, oldest first, and whether
    it must `resync` (the rings no longer reach back that far, or the id
    is from another relay process). No id: a fresh connect, nothing."""
    if not last_event_id:
        return [], False
    epoch, _, n = last_event_id.partition(".")
    try:
        since = int(n)
    except ValueError:
        return [], True
    if epoch != _EPOCH or since > _seq:
        return [], True
    gap = False
    missed: list[tuple[int, _Frame]] = []
    for key, ring in _rings.items():
        if key and not _sees_account(sub, key):
            continue
        if _evicted.get(key, 0) > since:
            gap = True
        missed.extend((seq, f) for seq, f in ring if seq > since and _wants(sub, f))
    missed.sort(key=lambda t: t[0])
    return [f for _, f in missed], gap


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
    event_type = _first_real_key(event)
    write_telemetry.frame(account_id, event_type, event)

    if is_feed_noise(event, account_id):
        return
    if event_type == "typing":
        # Forwarded as `chat_typing`, then down the normal path minus the
        # event_inbox row (_UNPERSISTED_TYPES): the persist worker's transcode
        # still touches the Fan row from the frame
        # (event_transcoder._touch_fan_from_event), and the raw `typing` frame
        # itself is not an SSE type, so broadcast() below drops it.
        await _forward_typing(account_id, event.get("typing"))

    # Strip sentinels for the persisted payload — it's already inferable
    # from `account_id`, no need to duplicate.
    persistable = {k: v for k, v in event.items() if not k.startswith("__")} if isinstance(event, dict) else {}

    # Enqueue for the persist worker. Bounded queue gives backpressure;
    # on overflow we drop the oldest so a slow disk loses history, not
    # the freshest events. Before the worker is started (race at startup
    # between the first event and `start_persist_worker`), we fall back
    # to the old fire-and-forget create_task path so we don't lose data.
    global _persist_drops
    if _persist_queue is not None:
        item = (account_id, event_type, persistable, event)
        try:
            _persist_queue.put_nowait(item)
        except asyncio.QueueFull:
            _persist_drops += 1
            write_telemetry.drop("queue_full")
            with _suppress_queue_empty(_persist_queue):
                _persist_queue.get_nowait()
                write_telemetry.dequeued()
            try:
                _persist_queue.put_nowait(item)
            except Exception:
                pass
            if _persist_drops % 100 == 1:
                log.warning(
                    "persist queue at capacity — %d events displaced so far "
                    "(SQLite writer can't keep up; check disk / batch size)",
                    _persist_drops,
                )
        write_telemetry.enqueued(_persist_queue.qsize())
    else:
        # Pre-startup path: keep the old behavior so no event is lost.
        from event_transcoder import transcode as _transcode  # local import to avoid cycles
        if event_type not in _UNPERSISTED_TYPES:
            asyncio.create_task(_persist_event_safe(
                account_id=account_id,
                event_type=event_type or "unknown",
                payload=persistable,
            ))
        asyncio.create_task(_transcode(event))

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
    thread through call_soon_threadsafe. Allow-list, id, ring, delivery."""
    global _seq
    if _first_real_key(event) not in SSE_TYPES:
        return 0
    _seq += 1
    frame = _Frame(event)
    frame.eid = f"{_EPOCH}.{_seq}"
    frame.t = time.monotonic()
    key = "" if event.get("__agency") is not None else str(event.get("__account_id") or "")
    ring = _rings.get(key)
    if ring is None:
        ring = _rings[key] = deque(maxlen=_RING_MAX)
    if len(ring) == _RING_MAX:
        _evicted[key] = ring[0][0]
    ring.append((_seq, frame))

    delivered = 0
    for sub in list(_subs.values()):
        if not _wants(sub, frame):
            continue
        delivered += 1
        _deliver(sub, frame)
    return delivered


def _note_rate(sub: _Sub, now: float, n: int) -> float:
    """`sub`'s events/s, decayed to `now`, after `n` more events."""
    sub.rate = sub.rate * math.exp((sub.rate_at - now) / _RATE_TAU_S) + n / _RATE_TAU_S
    sub.rate_at = now
    return sub.rate


def _window_s(rate: float) -> float:
    """How long a batch opened at `rate` stays open; 0: send at once."""
    if SSE_BATCH_WINDOW_MS <= 0 or rate <= SSE_BATCH_MIN_RATE:
        return 0.0
    if rate > 10 * SSE_BATCH_MIN_RATE:
        return max(SSE_BATCH_WINDOW_MS, SSE_BATCH_MAX_WINDOW_MS) / 1000
    return SSE_BATCH_WINDOW_MS / 1000


def _deliver(sub: _Sub, frame: _Frame) -> None:
    """Hand `frame` to `sub`: into its open batch, as a new batch when its
    rate calls for one, else on its own (see "Load-adaptive batching")."""
    if not sub.batching:
        _put(sub, frame)
        return
    now = time.monotonic()
    rate = _note_rate(sub, now, 1)
    ends = _first_real_key(frame) in _ENDS_STREAM
    b = sub.open
    if b is not None and len(b) < _BATCH_MAX and now < b.deadline:
        b.append(frame)
        if ends:
            # Nothing may follow it into this session's stream: close it now.
            b.deadline = 0.0
            sub.open = None
        return
    sub.open = None
    window = _window_s(rate)
    if window <= 0 or ends:
        _put(sub, frame)
        return
    b = _Batch((frame,))
    b.deadline = now + window
    sub.open = b
    _put(sub, b)


def _put(sub: _Sub, item: _Frame | _Batch) -> None:
    try:
        sub.q.put_nowait(item)
    except asyncio.QueueFull:
        # Drop oldest, push new — slow tab loses history, not freshness;
        # `lost` makes its stream send `resync` so it refetches.
        sub.lost = True
        with _suppress_queue_empty(sub.q):
            if sub.q.get_nowait() is sub.open:
                sub.open = None
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


def _inbox_row(account_id: str | None, event_type: str | None, payload: dict) -> dict:
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


async def _persist_batch(rows: list[dict]) -> None:
    """Write `rows` to event_inbox in one transaction; if that fails, row by
    row, so one bad payload costs only its own row. Never raises."""
    if not rows:
        return
    try:
        await insert_events(rows)
        return
    except Exception:
        if len(rows) == 1:
            log.exception("persist event failed (type=%s)", rows[0]["event_type"])
            write_telemetry.drop("persist_error")
            return
        log.warning("persist batch of %d failed; retrying row by row", len(rows),
                    exc_info=True)
    for row in rows:
        try:
            await insert_events([row])
        except Exception:
            log.exception("persist event failed (type=%s)", row["event_type"])
            write_telemetry.drop("persist_error")


async def _persist_event_safe(
    *, account_id: str | None, event_type: str, payload: dict,
) -> None:
    """One frame's event_inbox write (the pre-startup path). Never raises."""
    await _persist_batch([_inbox_row(account_id, event_type, payload)])


def _drain_batch(first: tuple) -> list[tuple]:
    """`first` plus whatever is already queued, up to _PERSIST_BATCH_MAX, in
    queue order. Never waits: an idle relay writes each event at once."""
    batch = [first]
    while len(batch) < _PERSIST_BATCH_MAX:
        try:
            batch.append(_persist_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    write_telemetry.dequeued(len(batch))
    write_telemetry.batch(len(batch))
    return batch


async def _persist_worker_loop() -> None:
    """Singleton consumer that drains `_persist_queue`.

    Takes everything already queued (up to _PERSIST_BATCH_MAX) and hands its
    event_inbox rows, then each event's `transcode`, to the OF-cache writer
    together (db/of_writer): the transcodes run concurrently, but each queues
    its write before its first await, so the writer gets them in queue order,
    inbox rows first, and commits them in one transaction. One consumer, FIFO,
    so each account's events keep their order. SQLite is single-writer: the
    writes go through the one writer instead of fighting over `busy_timeout`.
    """
    global _persist_inflight
    assert _persist_queue is not None
    from event_transcoder import transcode as _transcode  # local import to avoid cycles
    while True:
        try:
            first = await _persist_queue.get()
        except asyncio.CancelledError:
            return
        batch = _drain_batch(first)
        # Taken off the queue, not yet transcoded: what a shutdown cancel loses.
        _persist_inflight = len(batch)
        rows = [_inbox_row(account_id, event_type, persistable)
                for account_id, event_type, persistable, _event in batch
                if event_type not in _UNPERSISTED_TYPES]

        async def _one(event) -> None:
            global _persist_inflight
            try:
                await _transcode(event)
            except Exception:
                log.exception("persist worker: transcode failed")
                write_telemetry.drop("transcode_exception")
            _persist_inflight -= 1

        with write_telemetry.writer("persist"):
            await asyncio.gather(_persist_batch(rows), *(_one(ev) for *_x, ev in batch))


def start_persist_worker() -> None:
    """Start the singleton persist worker. Idempotent.

    Must be called from inside the running event loop (e.g. FastAPI's
    `@app.on_event("startup")`), after `init_db()` but before any WS pump
    spawns — otherwise the first burst of events takes the pre-startup
    fallback path in `handle_event`.
    """
    global _persist_queue, _persist_worker_task, _loop
    if _persist_worker_task is not None and not _persist_worker_task.done():
        return
    _loop = asyncio.get_running_loop()   # where `publish` hands other threads' events
    _persist_queue = asyncio.Queue(maxsize=_PERSIST_QUEUE_MAX)
    _persist_worker_task = asyncio.create_task(
        _persist_worker_loop(), name="event-persist-worker",
    )
    log.info("persist worker started (queue maxsize=%d)", _PERSIST_QUEUE_MAX)
    of_writer.start()
    write_telemetry.start()


async def stop_persist_worker() -> None:
    """Drain, then cancel the worker — call from shutdown only, after the OF
    pumps are cancelled (no live producer). Best-effort: what is queued gets
    up to _STOP_DRAIN_S to be written (the OF-cache writer then flushes what
    it holds); whatever is left after that is lost and counted."""
    global _persist_worker_task
    if _persist_worker_task is None:
        return
    deadline = time.monotonic() + _STOP_DRAIN_S
    while ((_persist_queue is not None and _persist_queue.qsize()) or _persist_inflight) \
            and not _persist_worker_task.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    # Counted before the cancel: the queued events and the worker's batch in hand
    # (its event_inbox rows may be written; their transcodes are not).
    write_telemetry.drop("shutdown_queued", _persist_queue.qsize() if _persist_queue is not None else 0)
    write_telemetry.drop("shutdown_inflight", _persist_inflight)
    _persist_worker_task.cancel()
    try:
        await _persist_worker_task
    except (asyncio.CancelledError, Exception):
        pass
    _persist_worker_task = None
    await of_writer.stop()
    await write_telemetry.stop()


def _first_real_key(event: dict | object) -> str | None:
    """Pick the first top-level key that isn't a `__`-prefixed sentinel."""
    if not isinstance(event, dict):
        return None
    for k in event:
        if not k.startswith("__"):
            return k
    return None


class _suppress_queue_empty:
    """Context manager: swallow asyncio.QueueEmpty. Tiny helper to keep
    the producer side branch-free."""
    def __init__(self, q: asyncio.Queue):
        self.q = q
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        return exc_type is asyncio.QueueEmpty


# ── SSE generator (FastAPI StreamingResponse body) ──────────────────

def _frame_json(frame: dict, event_type: str) -> str:
    """`frame`'s JSON, encoded once per _Frame however many tabs get it."""
    data = getattr(frame, "json", None)
    if data is not None:
        return data
    try:
        data = json.dumps(frame, default=str)
    except Exception:
        data = json.dumps({"error": "serialize_failed", "type": event_type})
    if isinstance(frame, _Frame):
        frame.json = data
    return data


def _sse_frame(frame: dict) -> bytes:
    event_type = _first_real_key(frame) or "event"
    data = _frame_json(frame, event_type)
    eid = getattr(frame, "eid", None)
    head = f"id: {eid}\n" if eid else ""
    return f"{head}event: {event_type}\ndata: {data}\n\n".encode("utf-8")


def _coalesce_key(frame: dict) -> tuple | None:
    event_type = _first_real_key(frame)
    field = _COALESCE.get(event_type)  # type: ignore[arg-type]
    body = frame.get(event_type) if field else None
    if not isinstance(body, dict) or body.get(field) is None:
        return None
    return event_type, frame.get("__account_id"), body[field]


def _coalesce(frames: list) -> list:
    """`frames` minus every one a newer frame in it supersedes (_COALESCE),
    order kept. The last frame is always kept, so the batch id is unchanged."""
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


def _sse_out(frames: list) -> bytes:
    """One frame as itself; several as one `event: batch` frame whose data is
    `[{id, type, data}, ...]` and whose id is the last member's."""
    if len(frames) == 1:
        return _sse_frame(frames[0])
    members = []
    for f in frames:
        # Both are plain tokens: the type is on the SSE_TYPES allow-list and
        # the id is `<hex epoch>.<seq>` — no JSON escaping needed.
        event_type = _first_real_key(f) or "event"
        members.append(f'{{"id":"{f.eid}","type":"{event_type}",'
                       f'"data":{_frame_json(f, event_type)}}}')
    last = getattr(frames[-1], "eid", None)
    head = f"id: {last}\n" if last else ""
    return f"{head}event: batch\ndata: [{','.join(members)}]\n\n".encode("utf-8")


def sse_stats() -> dict:
    """Per open stream: its mode right now, decayed rate, window, queue depth
    and counters — for /admin/events/stats. No scopes or account ids."""
    now = time.monotonic()
    streams = []
    for sub in list(_subs.values()):
        rate = sub.rate * math.exp((sub.rate_at - now) / _RATE_TAU_S)
        window = _window_s(rate) if sub.batching else 0.0
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


# Tells the tab it may have missed events the rings cannot replay: refetch.
_RESYNC = b"event: resync\ndata: {}\n\n"


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

    `accounts` / `agencies`: see `subscribe`.

    SSE wire format (one frame):
        id: <epoch>.<seq>\\n
        event: <event_type>\\n
        data: <json>\\n
        \\n
    """
    # Register and read the rings in one synchronous step: every event up to
    # `head` is in the rings, every later one lands in the queue.
    sub = _register(scope, accounts, agencies)
    sub.batching = True
    head = f"{_EPOCH}.{_seq}"
    missed, gap = _replay_since(sub, last_event_id)
    q = sub.q
    try:
        yield b": connected\n\n"
        if gap:
            yield _RESYNC
        # A replay is a burst by definition: batched whenever batching is on,
        # so a tab waking from idle applies it in one pass, not hundreds.
        step = _BATCH_MAX if SSE_BATCH_WINDOW_MS > 0 else 1
        for i in range(0, len(missed), step):
            yield _sse_out(_coalesce(missed[i:i + step]))
        yield f"id: {head}\n\n".encode("utf-8")
        last_beat = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            if sub.lost:
                sub.lost = False
                yield _RESYNC
            try:
                event = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if time.monotonic() - last_beat >= _HEARTBEAT_S:
                    # `: ping` keeps proxies' idle timers warm; the named
                    # `event: ping` lets the browser bump its lastEventAt
                    # so isConnected() degrades when the OF-WS pump stalls
                    # while the SSE socket itself stays open. Intentionally
                    # not logged — fires every 20 s per subscriber.
                    ts = json.dumps({"ts": time.time()})
                    yield (
                        b": ping\n\n"
                        + f"event: ping\ndata: {ts}\n\n".encode("utf-8")
                    )
                    last_beat = time.monotonic()
                continue

            if isinstance(event, _Batch):
                # Still open: let it collect until its window closes.
                delay = event.deadline - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                if sub.open is event:
                    sub.open = None
                frames = _coalesce(event)
                sub.coalesced += len(event) - len(frames)
                sub.batches += 1
            else:
                frames = [event]
            yield _sse_out(frames)
            last_beat = time.monotonic()
            if write_telemetry.ENABLED:
                for f in frames:
                    if "api2_chat_message" in f:
                        write_telemetry.sse_sent((last_beat - getattr(f, "t", last_beat)) * 1000)
            if _first_real_key(frames[-1]) in _ENDS_STREAM:
                return
    finally:
        await unsubscribe(scope, q)


# ── Hook installation ───────────────────────────────────────────────

def register_with(
    install: Callable[[Callable[[dict], Awaitable[None]]], None],
) -> None:
    """Called once at startup. Hands `handle_event` to the caller's
    install hook so the relay's existing `_broadcast_event` can fan
    events into us in addition to the legacy WS subscribers.

    Decoupled like this so this module has zero imports from server.py
    — server.py wires the connection at startup.
    """
    install(handle_event)
