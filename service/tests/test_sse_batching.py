#!/usr/bin/env python3
"""Load-adaptive SSE batching (events.py "Load-adaptive batching").

  • A quiet stream gets one frame per event, at once.
  • A hot one gets `event: batch` frames: every event arrives, in order, none
    later than one window after it was sent; the batch frame's id is its
    last member's, so a reconnect from it replays exactly what came after.
  • Within a batch the newest `chat_typing` per fan and `chat_queue_update`
    per queue replace older ones; DMs, money and unread never coalesce.
  • The stream drops back to single frames once its rate falls.
  • A stream-ending state event closes its batch at once, and nothing after
    it reaches that stream.
  • The queue counts batches: a burst far past _QUEUE_MAX events rides
    through a small queue without a resync.

Run:  ./venv/bin/python service/tests/test_sse_batching.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import events  # noqa: E402

A = "9301"
OWNER = "owner-b"


class _Req:
    headers: dict = {}

    async def is_disconnected(self) -> bool:
        return False


def _parse(raw: bytes) -> dict:
    out: dict = {}
    for line in raw.decode().split("\n"):
        if line and not line.startswith(":"):
            k, _, v = line.partition(": ")
            out[k] = v
    return out


def _stream(last: str | None = None):
    return events.sse_stream(_Req(), "all", accounts=frozenset({A}),
                             agencies=frozenset({OWNER}), last_event_id=last)


async def _next(gen, timeout: float = 3.0) -> dict:
    return _parse(await asyncio.wait_for(gen.__anext__(), timeout))


async def _open(last: str | None = None):
    gen = _stream(last)
    hello, head = await _next(gen), await _next(gen)
    assert hello == {} and set(head) == {"id"}, (hello, head)
    return gen


def _members(frame: dict) -> list[tuple[str, str, dict]]:
    """(id, type, event) per event a frame carries."""
    if frame.get("event") == "batch":
        return [(m["id"], m["type"], m["data"]) for m in json.loads(frame["data"])]
    return [(frame["id"], frame["event"], json.loads(frame["data"]))]


def _dm(mid: int, fan: int = 1) -> dict:
    return {"api2_chat_message": {"id": mid, "fromUser": {"id": fan}, "t": time.monotonic()},
            "__account_id": A}


def _mid(event: dict) -> int:
    return event["api2_chat_message"]["id"]


@contextmanager
def _knobs(**kw):
    old = {k: getattr(events, k) for k in kw}
    for k, v in kw.items():
        setattr(events, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(events, k, v)


def _reset() -> None:
    events._subs.clear()
    events._ring = events.ed.Rings(events._EPOCH)


async def case_quiet_stream_is_one_frame_per_event():
    _reset()
    gen = await _open()
    for mid in (1, 2, 3):
        t0 = time.monotonic()
        await events.broadcast(_dm(mid))
        f = await _next(gen)
        assert f["event"] == "api2_chat_message" and _mid(json.loads(f["data"])) == mid, f
        assert time.monotonic() - t0 < 0.05, "a quiet stream waits for no window"
        await asyncio.sleep(0.3)
    assert events.sse_stats()["streams"][0]["mode"] == "immediate"
    await gen.aclose()


async def case_hot_stream_batches_within_the_window():
    _reset()
    gen = await _open()
    sent: list[int] = []
    got: list[tuple[int, float]] = []
    frames: list[dict] = []

    async def read():
        while len(got) < 100:
            f = await _next(gen)
            frames.append(f)
            now = time.monotonic()
            got.extend((_mid(e), now - e["api2_chat_message"]["t"]) for _, _, e in _members(f))

    reader = asyncio.create_task(read())
    for mid in range(100, 200):  # ~170 events/s for ~0.55 s
        await events.broadcast(_dm(mid))
        sent.append(mid)
        await asyncio.sleep(0.005)
    stats = events.sse_stats()["streams"][0]
    await asyncio.wait_for(reader, 3)

    assert [m for m, _ in got] == sent, "every event arrives once, in order"
    batches = [f for f in frames if f["event"] == "batch"]
    assert batches and len(frames) < len(sent) / 3, (len(frames), len(batches))
    assert stats["mode"] == "batch" and stats["window_ms"] == events.SSE_BATCH_MAX_WINDOW_MS, stats
    worst = max(lag for _, lag in got)
    assert worst < events.SSE_BATCH_MAX_WINDOW_MS / 1000 + 0.08, f"worst lag {worst:.3f}s"
    for f in batches:
        assert f["id"] == _members(f)[-1][0], "a batch's id is its last member's"
    await gen.aclose()


async def case_reconnect_from_a_batch_id_replays_what_came_after():
    _reset()
    with _knobs(SSE_BATCH_MIN_RATE=0):
        gen = await _open()
        for mid in range(200, 210):
            await events.broadcast(_dm(mid))
        f = await _next(gen)
        assert f["event"] == "batch", f
        assert [_mid(e) for _, _, e in _members(f)] == list(range(200, 210)), f
        await gen.aclose()

        for mid in range(210, 215):
            await events.broadcast(_dm(mid))
        gen = _stream(f["id"])
        assert await _next(gen) == {}
        replay = await _next(gen)
        assert [_mid(e) for _, _, e in _members(replay)] == list(range(210, 215)), \
            "a reconnect from the batch id replays exactly what came after the batch"
        assert set(await _next(gen)) == {"id"}
        await gen.aclose()


async def case_typing_and_progress_coalesce_dms_money_unread_never():
    _reset()
    with _knobs(SSE_BATCH_MIN_RATE=0):
        gen = await _open()
        seq = [
            {"chat_typing": {"fan_id": 1}, "__account_id": A},
            {"chat_typing": {"fan_id": 2}, "__account_id": A},
            _dm(300, fan=1), _dm(300, fan=1), _dm(301, fan=1),
            {"chat_queue_update": {"id": 7, "pending": 9}, "__account_id": A},
            {"transaction_recorded": {"fan_id": 1}, "__account_id": A},
            {"transaction_recorded": {"fan_id": 1}, "__account_id": A},
            {"agency_notifications": {"unread": 3}, "__agency": OWNER},
            {"agency_notifications": {"unread": 3}, "__agency": OWNER},
            {"chat_typing": {"fan_id": 1}, "__account_id": A},
            {"chat_queue_update": {"id": 7, "pending": 2}, "__account_id": A},
        ]
        for ev in seq:
            await events.broadcast(ev)
        f = await _next(gen)
        got = [(t, e[t]) for _, t, e in _members(f)]
        assert [t for t, _ in got] == [
            "chat_typing", "api2_chat_message", "api2_chat_message", "api2_chat_message",
            "transaction_recorded", "transaction_recorded",
            "agency_notifications", "agency_notifications",
            "chat_typing", "chat_queue_update",
        ], got
        assert got[0][1] == {"fan_id": 2} and got[-2][1] == {"fan_id": 1}
        assert got[-1][1]["pending"] == 2, "the newest progress frame is the one kept"
        assert events.sse_stats()["streams"][0]["coalesced"] == 2
        await gen.aclose()


async def case_drops_back_to_single_frames_when_the_rate_falls():
    _reset()
    gen = await _open()
    for mid in range(400, 440):
        await events.broadcast(_dm(mid))
    n = 0
    while n < 40:
        n += len(_members(await _next(gen)))
    assert events.sse_stats()["streams"][0]["mode"] == "batch"
    await asyncio.sleep(2.5)  # 40/s decays under 5/s in ~2.1 s
    assert events.sse_stats()["streams"][0]["mode"] == "immediate"
    t0 = time.monotonic()
    await events.broadcast(_dm(440))
    f = await _next(gen)
    assert f["event"] == "api2_chat_message" and time.monotonic() - t0 < 0.05, f
    await gen.aclose()


async def case_stream_ending_event_closes_its_batch_at_once():
    _reset()
    with _knobs(SSE_BATCH_MIN_RATE=0):
        gen = await _open()
        t0 = time.monotonic()
        await events.broadcast(_dm(500))
        events.publish_state("assignment_changed", agency=OWNER)
        await events.broadcast(_dm(501))
        f = await _next(gen)
        assert time.monotonic() - t0 < 0.05, "the ending event does not wait out the window"
        assert [t for _, t, _ in _members(f)] == ["api2_chat_message", "assignment_changed"], f
        try:
            await _next(gen, 0.5)
            raise AssertionError("the stream should have ended")
        except StopAsyncIteration:
            pass


async def case_queue_counts_batches_not_events():
    _reset()
    with _knobs(SSE_BATCH_MIN_RATE=0, _QUEUE_MAX=3):
        gen = await _open()
        for mid in range(1000, 1500):  # 500 events, one tick: 3 batches
            await events.broadcast(_dm(mid))
        seen: list[int] = []
        while len(seen) < 500:
            f = await _next(gen)
            assert f.get("event") != "resync", "nothing was dropped"
            seen += [_mid(e) for _, _, e in _members(f)]
        assert seen == list(range(1000, 1500))
        await gen.aclose()


async def case_batching_off_is_the_old_wire():
    _reset()
    with _knobs(SSE_BATCH_WINDOW_MS=0):
        gen = await _open()
        for mid in range(600, 620):
            await events.broadcast(_dm(mid))
        got = [await _next(gen) for _ in range(20)]
        assert {f["event"] for f in got} == {"api2_chat_message"}
        assert [_mid(json.loads(f["data"])) for f in got] == list(range(600, 620))
        await gen.aclose()


async def case_one_encode_per_event():
    _reset()
    with _knobs(SSE_BATCH_MIN_RATE=1e9):
        gens = [await _open() for _ in range(5)]
        calls = 0
        real = json.dumps

        def counting(*a, **kw):
            nonlocal calls
            calls += 1
            return real(*a, **kw)

        events.json.dumps = counting
        try:
            await events.broadcast(_dm(700))
            got = [await _next(g) for g in gens]
        finally:
            events.json.dumps = real
        assert len({f["data"] for f in got}) == 1 and calls == 1, calls
        for g in gens:
            await g.aclose()


_harness.run()
