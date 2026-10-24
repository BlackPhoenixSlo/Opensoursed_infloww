"""Break-it-once: named product faults the relay wrapper can inject.

`slop/run <scenario> --break` runs a green baseline, then the same run with the
scenario's FAULT applied. CAUGHT means every check the fault declares in
`targets` went PASS -> FAIL; any other check that changed is reported as noise
and catches nothing. If a targeted check stays green, the mutation is NOT
caught: the invariants are blind to it.

A fault patches a real product function inside the throwaway relay process
(never the repo files). Add one per bug class a scenario claims to catch, and
name in `targets` the exact check names (ctx.check) that must see it.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable


def _transcoder_drops_1_in_10() -> None:
    """The WS transcoder silently loses every 10th chat message (persist-path bug class)."""
    import event_transcoder
    real = event_transcoder.transcode
    n = itertools.count(1)

    async def lossy(event):
        if isinstance(event, dict) and "api2_chat_message" in event and next(n) % 10 == 0:
            return None
        return await real(event)

    event_transcoder.transcode = lossy


def _sse_fanout_reorders_within_thread() -> None:
    """SSE fan-out delivers a fan's DM AFTER that fan's next DM: every 5th chat
    frame is held and released behind the same thread's next one (or after 3 s
    if none comes). Nothing is lost and the DB is untouched, so only a per-thread
    ordering check on what the stream delivered can see it (the bug class of a
    fan-out batcher/coalescer that regroups frames)."""
    import asyncio

    import events
    real = events.broadcast
    held: dict[tuple, dict] = {}
    n = itertools.count(1)

    def thread_of(event) -> tuple | None:
        m = event.get("api2_chat_message") if isinstance(event, dict) else None
        if not isinstance(m, dict):
            return None
        return str(event.get("__account_id")), (m.get("fromUser") or {}).get("id")

    def flush(key) -> None:
        if key in held:
            asyncio.ensure_future(real(held.pop(key)))

    async def reordering(event):
        key = thread_of(event)
        if key is None:
            return await real(event)
        if key in held:
            first = held.pop(key)
            delivered = await real(event)
            await real(first)
            return delivered
        if next(n) % 5 == 0:
            held[key] = event
            asyncio.get_running_loop().call_later(3.0, flush, key)
            return 1
        return await real(event)

    events.broadcast = reordering


def _access_log_writer_spin_waits() -> None:
    """The API access-log writer thread spin-waits for its next line: after each
    write it hashes a 1 MiB buffer in a loop until a line is queued (or 1 s), as a
    busy C loop would, instead of blocking in Queue.get(). hashlib releases the GIL,
    so the event loop barely notices and nothing is lost or late; the relay just
    burns about one more core. Only the process CPU check can see it. (Spinning on
    the event loop itself instead slows every request, which piles up sessions and
    sets off the SQLite connection storm: measured, latencies go red too.)"""
    import hashlib
    import time

    import server
    real = server._api_log_write
    buf = b"\0" * (1 << 20)

    def spinning(lines):
        real(lines)
        t = time.monotonic()
        while server._api_log_queue.empty() and time.monotonic() - t < 1.0:
            hashlib.sha256(buf)

    server._api_log_write = spinning  # the writer thread looks it up per line


@dataclass(frozen=True)
class Fault:
    apply: Callable[[], None]
    targets: tuple[str, ...]  # check names that must go PASS -> FAIL under this fault


FAULTS: dict[str, Fault] = {
    "transcoder-drops-1-in-10": Fault(_transcoder_drops_1_in_10, (
        "every DM is in its thread (/admin/messages)",
        "unreadMessagesCount == seeded + sent for every burst fan",
    )),
    "sse-fanout-reorders-within-thread": Fault(_sse_fanout_reorders_within_thread, (
        "per-thread order preserved on every /events stream",
    )),
    # Needs a scenario with CPU_BUDGET_PCT = 80 (the check is named after it):
    # slop/run big-model --break --fault=access-log-writer-spin-waits
    "access-log-writer-spin-waits": Fault(_access_log_writer_spin_waits, (
        "relay process CPU mean <= 80% of one core in every stage",
    )),
}


def apply(name: str | None) -> None:
    if not name:
        return
    if name not in FAULTS:
        raise SystemExit(f"slop: unknown fault {name!r}; known: {', '.join(FAULTS)}")
    FAULTS[name].apply()
