"""
The SSE wire encoding of service/events.py: the bytes a browser tab's `/events` stream gets.

    sse_frame(frame)   one event:   `id: <epoch>.<seq>\\n` (when it has one) `event: <type>\\n` `data: <json>\\n\\n`
    sse_out(frames)    one frame as itself; several as one `event: batch` frame whose data is
                       `[{id, type, data}, ...]` and whose id is the last member's
    CONNECTED          first bytes of every stream (a comment line)
    RESYNC             the tab may have missed what the rings cannot replay: refetch
    head(eid)          an id-only frame: a drop before the next event resumes from there
    ping(ts)           heartbeat: `: ping` (proxies' idle timers) + `event: ping` (the browser's lastEventAt)

`Frame` is an event as fanned out; `frame_json` encodes it once however many tabs get it (a
serialize failure becomes `{"error": "serialize_failed", "type": ...}`).

Importable without side effects (stdlib + events_decide).
"""
from __future__ import annotations

import json

import events_decide as ed

CONNECTED = b": connected\n\n"
RESYNC = b"event: resync\ndata: {}\n\n"


class Frame(dict):
    """An event as fanned out: the event dict itself (what the browser gets
    as `data:`) plus its SSE id, so queue consumers still read a dict.
    `json` caches its encoding: one encode however many tabs it goes to.
    `t`: monotonic time of the fan-out (write_telemetry's SSE lag)."""
    __slots__ = ("eid", "json", "t")


def frame_json(frame: dict, event_type: str) -> str:
    """`frame`'s JSON, encoded once per Frame however many tabs get it."""
    data = getattr(frame, "json", None)
    if data is not None:
        return data
    try:
        data = json.dumps(frame, default=str)
    except Exception:
        data = json.dumps({"error": "serialize_failed", "type": event_type})
    if isinstance(frame, Frame):
        frame.json = data
    return data


def _id_line(eid: str | None) -> str:
    return f"id: {eid}\n" if eid else ""


def sse_frame(frame: dict) -> bytes:
    event_type = ed.first_key(frame) or "event"
    data = frame_json(frame, event_type)
    return f"{_id_line(getattr(frame, 'eid', None))}event: {event_type}\ndata: {data}\n\n".encode("utf-8")


def sse_out(frames: list) -> bytes:
    """One frame as itself; several as one `event: batch` frame whose data is
    `[{id, type, data}, ...]` and whose id is the last member's."""
    if len(frames) == 1:
        return sse_frame(frames[0])
    members = []
    for f in frames:
        # Both are plain tokens: the type is on the SSE_TYPES allow-list and
        # the id is `<hex epoch>.<seq>` — no JSON escaping needed.
        event_type = ed.first_key(f) or "event"
        members.append(f'{{"id":"{f.eid}","type":"{event_type}",'
                       f'"data":{frame_json(f, event_type)}}}')
    last = getattr(frames[-1], "eid", None)
    return f"{_id_line(last)}event: batch\ndata: [{','.join(members)}]\n\n".encode("utf-8")


def head(eid: str) -> bytes:
    return f"{_id_line(eid)}\n".encode("utf-8")


def ping(ts: float) -> bytes:
    return b": ping\n\n" + f"event: ping\ndata: {json.dumps({'ts': ts})}\n\n".encode("utf-8")
