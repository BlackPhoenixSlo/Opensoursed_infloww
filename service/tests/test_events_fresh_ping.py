#!/usr/bin/env python3
"""The `fresh` ping (phase-01 Contract 7, ticket 09): with the Knob on every stream `ping` carries
`fresh: {aid: at}` (the Last refresh, epoch ms) for the tracked (Open-tab) Creators in that subscriber's clamp that
have one, on its own heartbeat timer, frames or not; with it off the ping is today's, byte for byte, and fires only
after a heartbeat with no frame. No ring entry either way.

Time is scaled 1:50 (heartbeat 20 s -> 0.4 s, a frame every 5 s -> 0.1 s, 60 s -> 1.2 s) through the module's own
`_HEARTBEAT_S`; the real `events` registry and `sse_stream`.

Run: ./venv/bin/python service/tests/test_events_fresh_ping.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import accounts  # noqa: E402
import events  # noqa: E402
import events_wire as ew  # noqa: E402
import shared_refresher  # noqa: E402

A, B, C, D = "9501", "9502", "9503", "9504"
OWNER = "owner-f"
HB = 0.4            # the heartbeat, scaled from 20 s
STEP = 0.1          # a frame every 5 s, scaled
SPAN = 1.2          # 60 s, scaled


class _Req:
    headers: dict = {}

    async def is_disconnected(self) -> bool:
        return False


@contextmanager
def _setup(on: bool, at_ms: dict[str, int]):
    old = (events._HEARTBEAT_S, shared_refresher.ENABLED, dict(shared_refresher._at_ms), accounts.is_watcher)
    events._HEARTBEAT_S = HB
    shared_refresher.ENABLED = on
    shared_refresher._at_ms.clear()
    shared_refresher._at_ms.update(at_ms)
    accounts.is_watcher = lambda aid: False
    events._subs.clear()
    events._ring = events.ed.Rings(events._EPOCH)
    try:
        yield
    finally:
        events._HEARTBEAT_S, shared_refresher.ENABLED, at, accounts.is_watcher = old
        shared_refresher._at_ms.clear()
        shared_refresher._at_ms.update(at)
        events._subs.clear()


def _pings(chunks: list[bytes]) -> list[dict]:
    """Each ping's `data`, decoded."""
    out = []
    for raw in chunks:
        if raw.startswith(b": ping\n\n"):
            line = raw.split(b"\n")[3]
            assert line.startswith(b"data: "), raw
            out.append(json.loads(line[len(b"data: "):]))
    return out


async def _drive(on: bool, *, tab: bool = True, clamp=frozenset({A, B}), frames: bool = True, span: float = SPAN,
                 other_tab=frozenset({C})) -> list[tuple[float, bytes]]:
    """One stream for `span` s (a frame for A every STEP when `frames`), beside another tab on `other_tab`;
    every chunk it yielded after `: connected` and the head, with its time since connect."""
    other = await events.subscribe("all", accounts=other_tab, tab=True)
    gen = events.sse_stream(_Req(), "all", accounts=clamp, agencies=frozenset({OWNER}), tab=tab)
    assert await gen.__anext__() == ew.CONNECTED
    assert (await gen.__anext__()).startswith(b"id: ")
    t0 = time.monotonic()
    got: list[tuple[float, bytes]] = []

    async def read():
        while True:
            chunk = await gen.__anext__()
            got.append((time.monotonic() - t0, chunk))

    reader = asyncio.create_task(read())
    n = 0
    while time.monotonic() - t0 < span:
        if frames:
            n += 1
            await events.broadcast({"api2_chat_message": {"id": n, "fromUser": {"id": 1}}, "__account_id": A})
        await asyncio.sleep(STEP)
    reader.cancel()
    try:
        await reader
    except asyncio.CancelledError:
        pass
    await gen.aclose()
    await events.unsubscribe("all", other)
    return got


async def case_on_busy_stream_still_pings_with_fresh():
    with _setup(True, {A: 111, C: 333, D: 444}):
        got = await _drive(True)
        pings = _pings([c for _, c in got])
        assert sum(1 for c in got if not c[1].startswith(b": ping")) >= 8, "frames flowed all along"
        assert len(pings) >= 2, (len(pings), got)
        assert all("fresh" in p for p in pings), pings
        # In the clamp and tracked: A (B is tracked but has no Last refresh yet); C is outside the clamp, D untracked.
        assert all(p["fresh"] == {A: 111} for p in pings), pings
        assert all(set(p) == {"ts", "fresh"} for p in pings), pings


async def case_off_busy_stream_pings_as_today():
    """Today's rule: a heartbeat with no frame; a frame every STEP never leaves one, so no ping at all."""
    with _setup(False, {A: 111}):
        got = await _drive(False)
        assert sum(1 for c in got if not c[1].startswith(b": ping")) >= 8, "frames flowed all along"
        assert _pings([c for _, c in got]) == [], got


async def case_off_quiet_stream_ping_is_todays_bytes():
    with _setup(False, {A: 111}):
        got = await _drive(False, frames=False, span=2.5)
        pings = [(t, c) for t, c in got if c.startswith(b": ping")]
        assert pings, got
        for t, c in pings:
            ts = _pings([c])[0]["ts"]
            assert c == ew.ping(ts), c
            assert c == b': ping\n\nevent: ping\ndata: ' + json.dumps({"ts": ts}).encode() + b'\n\n', c
        assert pings[0][0] >= HB, "never before a heartbeat of silence"


async def case_on_quiet_stream_pings_with_fresh():
    with _setup(True, {A: 111, B: 222}):
        got = await _drive(True, frames=False, span=2.5)
        pings = _pings([c for _, c in got])
        assert pings and all(p["fresh"] == {A: 111, B: 222} for p in pings), pings


async def case_fresh_holds_only_tracked_creators_in_the_clamp():
    """A stream not marked as a tab still gets the field, but only for its Creators some tab tracks."""
    with _setup(True, {A: 111, B: 222, C: 333, D: 444}):
        got = await _drive(True, tab=False, clamp=frozenset({A, D}), other_tab=frozenset({A, C}), frames=False,
                           span=1.5)
        pings = _pings([c for _, c in got])
        assert pings and all(p["fresh"] == {A: 111} for p in pings), pings


async def case_on_with_nothing_confirmed_carries_empty_fresh():
    with _setup(True, {}):
        got = await _drive(True, frames=False, span=1.5)
        pings = _pings([c for _, c in got])
        assert pings and all(p["fresh"] == {} for p in pings), pings


async def case_ping_writes_no_ring_entry():
    with _setup(True, {A: 111}):
        ring = events._ring
        got = await _drive(True, frames=False, span=1.5)
        assert _pings([c for _, c in got]), got
        assert events._ring is ring and ring.seq == 0 and not ring.rings, "a ping is no event"


def case_wire_ping():
    assert ew.ping(1700000000.5) == b': ping\n\nevent: ping\ndata: {"ts": 1700000000.5}\n\n'
    assert ew.ping(1700000000.5, {A: 111}) == (
        b': ping\n\nevent: ping\ndata: {"ts": 1700000000.5, "fresh": {"9501": 111}}\n\n')
    assert ew.ping(1.0, {}) == b': ping\n\nevent: ping\ndata: {"ts": 1.0, "fresh": {}}\n\n'


_harness.run()
