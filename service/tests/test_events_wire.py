#!/usr/bin/env python3
"""events_wire: the SSE bytes of service/events.py as byte-exact tables. Pure: no queue, no clock.

Pins: a single frame is `id:` (when it has one) + `event: <type>` + `data: <json>`; a frame with no
type is `event: event`; several frames are one `event: batch` whose data is `[{id, type, data}, ...]`
and whose id is the last member's; a frame that cannot serialize becomes
`{"error": "serialize_failed", "type": ...}`; a Frame is encoded once however many tabs get it (the
shell's end of it: test_sse_batching.case_one_encode_per_event); resync / head / ping / connected
bytes.

Runs under pytest (parametrized tables) or as a script (the repo's convention, no pytest needed):
    ./venv/bin/python service/tests/test_events_wire.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import events_wire as ew  # noqa: E402

try:
    import pytest
    table = pytest.mark.parametrize
except ImportError:  # script mode: the runner below calls each row
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark


def frame(event: dict, eid: str | None = None) -> ew.Frame:
    f = ew.Frame(event)
    if eid is not None:
        f.eid = eid
    return f


DM = {"api2_chat_message": {"id": 7, "text": "hi"}, "__account_id": "9101"}
DM_JSON = '{"api2_chat_message": {"id": 7, "text": "hi"}, "__account_id": "9101"}'


@table("frames, wire", [
    ([frame(DM, "e1.5")],
     b'id: e1.5\nevent: api2_chat_message\ndata: ' + DM_JSON.encode() + b'\n\n'),
    ([frame(DM)],                                                     # no id: no id line
     b'event: api2_chat_message\ndata: ' + DM_JSON.encode() + b'\n\n'),
    ([{"toasts": {"n": 1}}],                                          # a plain dict, no id
     b'event: toasts\ndata: {"toasts": {"n": 1}}\n\n'),
    ([frame({"__account_id": "9101"}, "e1.6")],                       # no type
     b'id: e1.6\nevent: event\ndata: {"__account_id": "9101"}\n\n'),
    ([frame({"toasts": {"t": "é"}}, "e1.7")],                         # utf-8 (json escapes it)
     b'id: e1.7\nevent: toasts\ndata: {"toasts": {"t": "\\u00e9"}}\n\n'),
    ([frame(DM, "e1.5"), frame({"chat_typing": {"fan_id": 3}}, "e1.9")],   # batch: id = last member's
     b'id: e1.9\nevent: batch\ndata: [{"id":"e1.5","type":"api2_chat_message","data":' + DM_JSON.encode()
     + b'},{"id":"e1.9","type":"chat_typing","data":{"chat_typing": {"fan_id": 3}}}]\n\n'),
])
def test_sse_out(frames, wire):
    assert ew.sse_out(frames) == wire


def test_single_frame_is_sse_frame():
    f = frame(DM, "e1.5")
    assert ew.sse_out([f]) == ew.sse_frame(f)


def test_batch_without_a_last_id_has_no_id_line():
    a, b = frame({"toasts": {}}, "e1.1"), frame({"toasts": {}})
    b.eid = None
    assert ew.sse_out([a, b]).startswith(b"event: batch\ndata: [")


class _Unserializable:
    def __str__(self):
        raise RuntimeError("no str")


def test_serialize_fail_fallback():
    f = frame({"toasts": {"x": _Unserializable()}}, "e1.8")
    assert ew.sse_frame(f) == b'id: e1.8\nevent: toasts\ndata: {"error": "serialize_failed", "type": "toasts"}\n\n'
    assert ew.frame_json({"x": _Unserializable()}, "event") == '{"error": "serialize_failed", "type": "event"}'


def test_one_encode_per_frame_across_tabs():
    f = frame(DM, "e1.5")
    calls = 0
    real = json.dumps

    def counting(*a, **kw):
        nonlocal calls
        calls += 1
        return real(*a, **kw)

    json.dumps = counting
    try:
        tabs = [ew.sse_out([f]) for _ in range(5)] + [ew.sse_out([f, frame(DM, "e1.6")])]
    finally:
        json.dumps = real
    assert calls == 2, calls                      # f once, the second batch member once
    assert len(set(tabs[:5])) == 1 and f.json == DM_JSON


def test_a_plain_dict_is_not_cached():
    d = dict(DM)
    assert ew.frame_json(d, "api2_chat_message") == DM_JSON and not hasattr(d, "json")


@table("got, wire", [
    (ew.RESYNC, b"event: resync\ndata: {}\n\n"),
    (ew.CONNECTED, b": connected\n\n"),
    (ew.head("e1.42"), b"id: e1.42\n\n"),
    (ew.ping(1700000000.5), b': ping\n\nevent: ping\ndata: {"ts": 1700000000.5}\n\n'),
])
def test_fixed_frames(got, wire):
    assert got == wire


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
