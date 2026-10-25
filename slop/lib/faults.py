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


def _db_pool_unbounded_overflow() -> None:
    """The relay's DB pool as it was before 03-write-storm: 5 kept connections and
    unbounded overflow, so a checkout that finds none free opens a new SQLite
    connection (a thread, a schema parse) instead of waiting for one. Every write
    still lands; under a pile-up (the scenario's 2 s stall) the relay opens 200+
    connections and burns 4-11 cores for seconds. Only the stall check can see it
    reliably (the natural storm comes and goes)."""
    import sys

    from sqlalchemy.pool import AsyncAdaptedQueuePool

    import db.engine  # noqa: F401 — the package re-exports `engine` over the module name
    pool = sys.modules["db.engine"].engine.sync_engine.pool
    if "_queue" in pool._pool.__dict__ or pool.checkedout() or pool.checkedin():
        raise SystemExit("slop: db-pool-unbounded-overflow must be applied before the first DB session")
    pool.__class__ = AsyncAdaptedQueuePool  # QueuePool._do_get: max_overflow=-1 never waits
    pool._pool.maxsize, pool._overflow = 5, -5
    pool._pool.__dict__.pop("_queue", None)  # memoized at maxsize 8 by checkedout() above


def _write_telemetry_misses_1_in_50_dms() -> None:
    """The write-path telemetry line under-reports: every 50th inbound DM frame
    is not counted (an ingest counter on the wrong branch). The DM itself is
    persisted, transcoded and fanned out as ever, so only the check that sums
    the telemetry lines against what was injected can see it."""
    from db import write_telemetry
    real = write_telemetry.frame
    n = itertools.count(1)

    def undercount(account_id, event_type, event):
        if event_type == "api2_chat_message" and next(n) % 50 == 0:
            return None
        return real(account_id, event_type, event)

    write_telemetry.frame = undercount  # events.handle_event looks it up per frame


def _of_writer_per_op_txns() -> None:
    """The OF-cache writer never starts (db/of_writer.py as if batching were off):
    every DM's event_inbox row, its transcode and every mark-read is written through
    in a transaction of its own, as before the writer. Nothing is lost and every
    row is right, so only the write-transaction checks can see it."""
    from db import of_writer
    of_writer.start = lambda: None


def _of_writer_holds_batches_3s() -> None:
    """The OF-cache writer waits 3 s before committing each batch (bug class: a
    timer / fill-the-batch writer instead of flushing as soon as work exists).
    Every row still lands, so only a crash shows it: the loss window grows from
    the in-flight batch to seconds of DMs."""
    import asyncio

    from db import of_writer
    real = of_writer._flush

    async def held(batch):
        await asyncio.sleep(3)
        return await real(batch)

    of_writer._flush = held


def _otp_code_never_consumed() -> None:
    """The served Browserbase login never reads its pending 2FA code: POST
    /admin/login/remote/{id}/otp still answers 200 and fills the job's slot,
    but the job's thread never types it into OnlyFans (bug class: a request
    thread and a worker thread that never meet)."""
    import remote_login

    remote_login.RemoteLoginJob.take_otp = lambda self: None


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
    # slop/run big-model --break --fault=db-pool-unbounded-overflow (medium: the stall
    # runs only with stages >= 60 s).
    "db-pool-unbounded-overflow": Fault(_db_pool_unbounded_overflow, (
        "relay absorbs a 2s stall: CPU <= 300% every second and p95 <= 750ms for requests sent in the "
        "30s after (no SQLite connection storm)",
    )),
    # slop/run big-model --break --fault=write-telemetry-misses-1-in-50-dms
    "write-telemetry-misses-1-in-50-dms": Fault(_write_telemetry_misses_1_in_50_dms, (
        "write_telemetry lines: frames and DMs per account == injected",
    )),
    # slop/run big-model-dm-flood --break --fault=of-writer-per-op-txns
    "of-writer-per-op-txns": Fault(_of_writer_per_op_txns, (
        "OF-cache writer: every op committed, and no DM / event_inbox write transaction outside its batches",
        "mark-read: <= 1.05 write transaction per call (its audit row)",
    )),
    # slop/run relay-crash --break (the scenario's FAULT)
    "of-writer-holds-batches-3s": Fault(_of_writer_holds_batches_3s, (
        "crash loses only DMs the relay took < 1000ms before the kill",
    )),
    # slop/run browserbase-otp --break (the scenario's FAULT)
    "otp-code-never-consumed": Fault(_otp_code_never_consumed, (
        "API: a wrong 2FA code comes back as rejected and the job stays on the 2FA prompt",
        "API: the right 2FA code signs in; the session is saved and linked to the owner",
        "OnlyFans' 2FA field received exactly the codes submitted, in order",
        "card: a wrong code shows the rejection and the field takes another code",
        "card: the right code links the account (job done, user_accounts row)",
    )),
}


def apply(name: str | None) -> None:
    if not name:
        return
    if name not in FAULTS:
        raise SystemExit(f"slop: unknown fault {name!r}; known: {', '.join(FAULTS)}")
    FAULTS[name].apply()
