from __future__ import annotations

import json

import events_decide as ed

CONNECTED = b": connected\n\n"
RESYNC = b"event: resync\ndata: {}\n\n"


class Frame(dict):
    __slots__ = ("eid", "json", "t")


def frame_json(frame: dict, event_type: str) -> str:
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
    if len(frames) == 1:
        return sse_frame(frames[0])
    members = []
    for f in frames:
        # Type is on the SSE_TYPES allow-list and id is `<hex epoch>.<seq>`: plain tokens, no JSON escaping needed.
        event_type = ed.first_key(f) or "event"
        members.append(f'{{"id":"{f.eid}","type":"{event_type}",'
                       f'"data":{frame_json(f, event_type)}}}')
    last = getattr(frames[-1], "eid", None)
    return f"{_id_line(last)}event: batch\ndata: [{','.join(members)}]\n\n".encode("utf-8")


def head(eid: str) -> bytes:
    return f"{_id_line(eid)}\n".encode("utf-8")


def ping(ts: float, fresh: dict[str, int] | None = None, badge: dict[str, int] | None = None) -> bytes:
    data: dict = {"ts": ts}
    if fresh is not None:
        data["fresh"] = fresh
    if badge is not None:
        data["badge"] = badge
    return b": ping\n\n" + f"event: ping\ndata: {json.dumps(data)}\n\n".encode("utf-8")
