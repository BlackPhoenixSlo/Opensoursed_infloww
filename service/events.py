from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import Request

import chatter_identity_cache
import event_transcode_decide as td
import events_decide as ed
import events_persist
import events_wire as ew
import event_transcoder
import relay_hooks
import push_send
import split_inbox
from db import write_telemetry

log = logging.getLogger("of-relay.events")

_Frame = ew.Frame
STATE_TYPES = ed.STATE_TYPES
SSE_TYPES = ed.SSE_TYPES
_ENDS_STREAM = ed.ENDS_STREAM
is_feed_noise = ed.is_feed_noise
_frame_json = ew.frame_json
_sse_frame = ew.sse_frame
_sse_out = ew.sse_out
_RESYNC = ew.RESYNC

# a 100 events/s spike rides through; a wedged tab is evicted within seconds
_QUEUE_MAX = 256

# two missed pings before the frontend's 45 s STALE_MS trips; also under proxies' ~60 s idle close
_HEARTBEAT_S = 20


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, os.environ.get(name), default)
        return default


SSE_BATCH_MIN_RATE = _env_float("SSE_BATCH_MIN_RATE", 5.0)
SSE_BATCH_WINDOW_MS = _env_float("SSE_BATCH_WINDOW_MS", 100.0)
SSE_BATCH_MAX_WINDOW_MS = _env_float("SSE_BATCH_MAX_WINDOW_MS", 250.0)


def _knobs() -> ed.Knobs:
    return ed.Knobs(SSE_BATCH_MIN_RATE, SSE_BATCH_WINDOW_MS, SSE_BATCH_MAX_WINDOW_MS)


class _Batch(list):
    __slots__ = ("deadline",)


class _Sub:
    __slots__ = ("q", "scope", "accounts", "agencies", "lost", "batching",
                 "st", "open", "batches", "coalesced", "tab", "readable", "ended", "chatter", "cut")

    def __init__(self, scope: str, accounts: frozenset[str] | None,
                 agencies: frozenset[str], tab: bool = False,
                 readable: frozenset[str] | None = None, chatter: str | None = None):
        self.q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self.scope = scope
        self.accounts = accounts
        self.agencies = agencies
        self.tab = tab
        self.readable = readable
        self.chatter = chatter
        self.lost = False
        self.ended = False
        self.cut = False
        self.batching = False
        self.st = ed.Stream(rate_at=time.monotonic())
        self.open: _Batch | None = None
        self.batches = 0
        self.coalesced = 0


# Event-loop thread only, never across an await: no lock; other threads go through publish
_subs: dict[asyncio.Queue, _Sub] = {}
_loop: asyncio.AbstractEventLoop | None = None


# RAM only: a deploy loses the rings and a new epoch makes every old id resync
_EPOCH = format(int(time.time() * 1000), "x")
_ring = ed.Rings(_EPOCH)



# Set on SIGTERM so open streams end and uvicorn's graceful wait finishes
_closing = False


def close_streams() -> None:
    global _closing
    _closing = True


def cut_streams() -> None:
    for sub in list(_subs.values()):
        sub.cut = True


# OF re-sends typing every ~2-3 s; one push per window is enough
_TYPING_THROTTLE_S = 3.0
_typing_last: dict[tuple[str, int], float] = {}
_typing_shape_logged = False


async def _forward_typing(account_id: object, payload: object) -> None:
    global _typing_shape_logged
    if not _typing_shape_logged:
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



async def subscribe(
    scope: str, *, accounts: frozenset[str] | None = None,
    agencies: frozenset[str] = frozenset(), tab: bool = False,
) -> asyncio.Queue:
    return _register(scope, accounts, agencies, tab).q


def _register(scope: str, accounts: frozenset[str] | None,
              agencies: frozenset[str], tab: bool = False,
              readable: frozenset[str] | None = None, chatter: str | None = None) -> _Sub:
    global _loop
    _loop = asyncio.get_running_loop()
    sub = _Sub(scope, accounts, agencies, tab, readable, chatter)
    _subs[sub.q] = sub
    return sub


def is_app_tab(lease: str | None, referer: str | None) -> bool:
    return lease is not None or bool(referer)


def open_tab_accounts() -> frozenset[str]:
    import accounts
    return frozenset(a for a in _tab_clamps() if not accounts.is_watcher(a))


def _tab_clamps() -> set[str]:
    return {a for s in list(_subs.values()) if s.tab and s.accounts is not None for a in s.accounts}


def _ping(sub: _Sub, shared_refresher) -> bytes:
    import unread_total  # noqa: PLC0415 — lazy: unread_total → shared_refresher → events
    ids = _tab_clamps()
    ids = frozenset(ids if sub.accounts is None else ids & sub.accounts)
    return ew.ping(time.time(), shared_refresher.fresh_at(ids), unread_total.badge_versions(ids) or None)


async def unsubscribe(scope: str, q: asyncio.Queue) -> None:
    _subs.pop(q, None)


def ring_seq() -> int:
    return _ring.seq


def subscriber_count(scope: str | None = None) -> int:
    return sum(1 for s in list(_subs.values()) if scope is None or s.scope == scope)


def _wants(sub: _Sub, frame: dict) -> bool:
    return ed.wants(sub.scope, sub.accounts, sub.agencies, frame)


def _for(sub: _Sub, frame: ew.Frame) -> ew.Frame | None:
    narrowed = split_inbox.narrow(sub.chatter, frame)
    if narrowed is None:
        return None
    strip = ed.strips_message(sub.readable, frame)
    if narrowed is frame and not strip:
        return frame
    out = ew.Frame(narrowed)
    if strip:
        out["chat_responded"] = {k: v for k, v in frame["chat_responded"].items() if k != "message"}
    out.eid = getattr(frame, "eid", None)
    out.t = getattr(frame, "t", time.monotonic())
    return out



async def handle_event(event: dict) -> None:
    account_id = event.get("__account_id") if isinstance(event, dict) else None
    event_type = ed.first_key(event)
    write_telemetry.frame(account_id, event_type, event)

    if ed.is_feed_noise(event, account_id):
        return
    counter = td.counter_of(event)
    if counter is not None and account_id is not None:
        import unread_total  # noqa: PLC0415 — lazy: unread_total → shared_refresher → events
        unread_total.observe_counter(account_id, counter, int(time.time() * 1000))
    if event_type == "typing":
        await _forward_typing(account_id, event.get("typing"))

    persistable = {k: v for k, v in event.items() if not k.startswith("__")} if isinstance(event, dict) else {}

    # Update message readers before fan-out so a refetch sees the event
    relay_hooks.fire_inbound_message(account_id, event_type, event)
    prior = event_transcoder.patch_inbox_at_receipt(account_id, event)

    events_persist.enqueue(account_id, event_type, persistable, event, prior)

    await broadcast(event)


async def broadcast(event: dict) -> int:
    return _fanout(event)


# A cold backfill inserts hundreds of ancient sales nobody has open
_ANNOUNCE_MAX_AGE = timedelta(hours=48)
_JS_SAFE_INT = 2 ** 53 - 1


def js_safe_id(fid: int) -> int | str:
    return fid if abs(fid) <= _JS_SAFE_INT else str(fid)


# Call after the writer's commit. Never put an amount in `fields`: every session of the Creator gets it, chatters whose role hides revenue too.
async def announce_transaction(
    account_id: object, fan_id: int, *, occurred_at: datetime | None = None, capped: bool = False,
    **fields: object,
) -> None:
    if capped and (occurred_at is None or occurred_at < datetime.utcnow() - _ANNOUNCE_MAX_AGE):
        return
    try:
        fid = int(fan_id)
        await broadcast({
            "transaction_recorded": {"fan_id": js_safe_id(fid), **fields},
            "__account_id": str(account_id),
        })
    except Exception:
        log.debug("transaction_recorded broadcast failed", exc_info=True)


def _cell_stamp() -> dict | None:
    if not os.environ.get("OI_CELL_MAP"):
        return None
    import cell_mode
    return {"cell": os.environ.get("OI_CELL_ID", ""), "data_gen": cell_mode.data_gen()}


def _resync(sub: _Sub) -> bytes:
    cell = _cell_stamp()
    if cell is None:
        return ew.RESYNC
    import cell_mode
    owned = cell_mode.read_scope(sub.accounts)
    one = sub.scope[len("model:"):] if sub.scope.startswith("model:") else None
    return ew.resync(cell, [one] if one is not None and one in owned else sorted(owned))


def _fanout(event: dict) -> int:
    global _ring
    if ed.first_key(event) not in ed.SSE_TYPES:
        return 0
    frame = ew.Frame(event)
    if cell := _cell_stamp():
        frame.update(cell)
    frame.t = time.monotonic()
    _ring = ed.decide_ring(_ring, ed.Published(frame))
    frame.eid = ed.head_id(_ring)
    push_send.offer(frame)

    knobs = _knobs()
    ends = ed.first_key(frame) in ed.ENDS_STREAM
    delivered = 0
    for sub in list(_subs.values()):
        if sub.ended or not _wants(sub, frame):
            continue
        outgoing = _for(sub, frame)
        if outgoing is None:
            continue
        delivered += 1
        _deliver(sub, outgoing, ends, knobs)
        # Synchronous: a reply published after a revocation never reaches this stream
        sub.ended = ends and sub.batching
    return delivered


def _deliver(sub: _Sub, frame: ew.Frame, ends: bool, knobs: ed.Knobs) -> None:
    if not sub.batching:
        _put(sub, frame)
        return
    b = sub.open
    sub.st, e = ed.decide_stream(sub.st, ed.Deliver(
        time.monotonic(), ends, len(b) if b is not None else 0, b.deadline if b is not None else 0.0, knobs))
    if isinstance(e, ed.Append):
        assert b is not None
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
        # Slow tab loses history, not freshness; lost makes its stream send resync
        sub.lost = True
        with contextlib.suppress(asyncio.QueueEmpty):
            sub.q.get_nowait()
        try:
            sub.q.put_nowait(item)
        except Exception:
            pass


def publish(event: dict) -> None:
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
    return f"owner:{user_id}"


def sessions_audience(kind: str, principal_id: object) -> str:
    return f"sessions:{kind}:{principal_id}"


def publish_state(
    event_type: str, *, account_id: object = None, agency: object = None, **fields: object,
) -> None:
    if event_type in ed.ENDS_STREAM:
        # Before the event goes out: a reconnect reads the new grants
        chatter_identity_cache.invalidate()
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
    try:
        try:
            of_uid: object = int(account_id)
        except (TypeError, ValueError):
            of_uid = account_id
        # Naive datetimes are UTC: tag 'Z' so consumers don't render them in the viewer's zone
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
            "__fan_id": int(fan_id),
        }
        await broadcast(event)
    except Exception:
        log.exception("publish_db_message failed (account=%s fan=%s msg=%s)",
                      account_id, fan_id, message_id)


async def publish_chat_responded(
    *, account_id: str, fan_id: int, employee_id: int | None,
    message: Any = None, at: int | None = None,
) -> None:
    try:
        by = ""
        if employee_id is not None:
            from db.engine import get_session
            from db.models import Employee
            async with get_session() as s:
                e = await s.get(Employee, int(employee_id))
            by = e.display_name if e is not None else ""
        body: dict[str, Any] = {"fan_id": int(fan_id), "by": by,
                                "at": at if at is not None else int(time.time() * 1000)}
        if isinstance(message, dict) and message.get("id") is not None:
            body["message"] = {
                "id": message.get("id"),
                "text": str(message.get("text") or ""),
                "createdAt": message.get("createdAt"),
                "mediaCount": int(message.get("mediaCount") or len(message.get("media") or [])),
                "price": float(message.get("price") or 0),
            }
        publish({"chat_responded": body, "__account_id": str(account_id)})
    except Exception:
        log.exception("publish_chat_responded failed (account=%s fan=%s)", account_id, fan_id)


def start_persist_worker() -> None:
    global _loop
    if events_persist.start_persist_worker():
        _loop = asyncio.get_running_loop()



def sse_stats() -> dict:
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
        "push": push_send.stats(),
    }


async def sse_stream(
    request: Request, scope: str, *, accounts: frozenset[str] | None = None,
    agencies: frozenset[str] = frozenset(), last_event_id: str | None = None, tab: bool = False,
    readable: frozenset[str] | None = None, granted_at: int | None = None, chatter: str | None = None,
    expires_at: int | None = None,
) -> AsyncIterator[bytes]:
    import shared_refresher
    fresh_on = shared_refresher.ENABLED
    sub = _register(scope, accounts, agencies, tab, readable, chatter)
    sub.batching = True
    replay = ed.replay(_ring, last_event_id, lambda key: ed.sees(sub.scope, sub.accounts, key),
                       lambda f: _wants(sub, f), _knobs(),
                       sees_any=lambda key: ed.sees(sub.scope, sub.accounts, key, any_scope=True),
                       project=lambda frame: _for(sub, frame))
    q = sub.q

    def expired() -> bool:
        return expires_at is not None and time.time() >= expires_at

    try:
        if expired():
            return
        if granted_at is not None and ed.ended_since(_ring, granted_at, lambda f: _wants(sub, f)):
            return
        yield ew.CONNECTED
        if fresh_on:
            yield _ping(sub, shared_refresher)
        for e in replay:
            if expired():
                return
            if isinstance(e, ed.Resync):
                yield _resync(sub)
            elif isinstance(e, ed.Emit):
                yield ew.sse_out(e.frames)
            elif isinstance(e, ed.Head):
                yield ew.head(e.eid)
        last_beat = time.monotonic()
        while True:
            if expired() or _closing or sub.cut or await request.is_disconnected() or (sub.ended and q.empty()):
                return
            if sub.lost:
                sub.lost = False
                yield _resync(sub)
            if fresh_on and time.monotonic() - last_beat >= _HEARTBEAT_S:
                yield _ping(sub, shared_refresher)
                last_beat = time.monotonic()
            try:
                event = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if not fresh_on and time.monotonic() - last_beat >= _HEARTBEAT_S:
                    yield ew.ping(time.time())
                    last_beat = time.monotonic()
                continue

            if isinstance(event, _Batch):
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
            if expired():
                return
            yield ew.sse_out(frames)
            sent = time.monotonic()
            if not fresh_on:
                last_beat = sent
            if write_telemetry.ENABLED:
                for f in frames:
                    if "api2_chat_message" in f:
                        write_telemetry.sse_sent((sent - getattr(f, "t", sent)) * 1000)
            if ed.first_key(frames[-1]) in ed.ENDS_STREAM:
                return
    finally:
        await unsubscribe(scope, q)



def register_with(
    install: Callable[[Callable[[dict], Awaitable[None]]], None],
) -> None:
    install(handle_event)
