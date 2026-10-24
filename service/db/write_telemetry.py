"""Write-path telemetry: one JSON log line per interval (default 60 s) and one
on shutdown, so production shows what the SQLite write path carries before
anyone resizes it. Observation only: nothing here waits, caps or drops.

    INFO of-relay.write_telemetry write_telemetry {...}

`docker logs <relay container> 2>&1 | grep ' write_telemetry {'` collects them (the
JSON starts at the first `{`). Historical DM peaks, from a DB copy instead:
scripts/dm_peak_rates.py. Fields:

  reason   interval | shutdown | flush (an explicit emit())
  s        seconds the line covers
  in       frames / dms handed to events.handle_event (dms: inbound
           api2_chat_message), f1/f10 and d1/d10: the most in one 1 s / 10 s
           wall-clock-aligned bucket; acct: {account: {f, d, d1, d10}}
  q        persist queue: depth max (after a put), age_ms max (enqueue ->
           taken by the worker), head_age_ms (oldest still queued at emit),
           batches, batch mean / max
  w        per writer: SQLite write transactions (those that ran at least one
           INSERT/UPDATE/DELETE/REPLACE) — n, wait [p50, p95, max] ms = the
           first write statement's wall time (SQLite takes the write lock
           there, so this holds the busy_timeout wait), hold [p50, p95, max]
           ms = first write done -> COMMIT/ROLLBACK returned (the lock is held
           all of it, event-loop delays included), hold_sum_ms, locked
           ('database is locked' / busy errors), rb (rolled back)
  lock     sum of hold + wait over all writers / interval: how much of the
           interval the single write lock was taken or being fought for
  pool     out_max (checked out at once), open_max (connections open at once),
           overflow_max (beyond pool_size: spill connections), opened / closed
           this interval, spills (checkouts that waited SPILL_AFTER_S)
  drops    per reason, this interval: queue_full (drop-oldest), persist_error
           (an event_inbox row discarded after its row-by-row retry),
           transcode_exception (transcode swallowed it: canonical rows not
           written), shutdown_queued / shutdown_inflight (cancelled by
           stop_persist_worker); drops_cum: the same since process start
  ow       the OF-cache writer (db/of_writer.py): batches (= its write
           transactions), ops, merged (ops coalesced into another op of the
           same key), batch_mean / batch_max (ops per transaction), flush_ms
           [p50, p95, max] (BEGIN IMMEDIATE -> COMMIT returned), age_ms [p50,
           p95, max] (op queued -> committed: what a caller waited), q_max (ops
           queued at once), failed (ops that failed alone and raised to their
           caller); its lock wait / hold are under w.of_writer. Drop reason
           writer_shutdown = ops still queued when stop() gave up
  sse      api2_chat_message frames: fan-out -> written to an /events
           socket, n and lag [p50, p95, max] ms

Writers: a ContextVar set where the write path starts (`writer(...)`: persist,
transcode, webhook_dispatch, automation_enqueue), else `http:<METHOD> <path>`
(ids folded to {}) from the request hook, else the asyncio task's coroutine.
CHATTERLY_WRITE_TELEMETRY_S=0 turns all of it off (no engine listeners).
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone

log = logging.getLogger("of-relay.write_telemetry")

INTERVAL_S = float(os.environ.get("CHATTERLY_WRITE_TELEMETRY_S", "60") or 0)
ENABLED = INTERVAL_S > 0
_SAMPLES_MAX = 4000   # per histogram per interval; reservoir beyond that
_WRITERS_MAX = 40     # distinct writer labels per interval; the rest are "other"
_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLAC")
# An explicit transaction on an AUTOCOMMIT connection (db/of_writer.immediate,
# the ledger ingest): BEGIN IMMEDIATE takes the write lock, so it starts the
# timing, and a COMMIT / ROLLBACK statement (not the DBAPI's commit()) ends it.
_BEGIN_IMMEDIATE = "BEGIN IMMEDIATE"
_TXN_END = {"COMMIT": False, "END": False, "ROLLBACK": True}
# Every path that loses an event, always on the line (0 included), so a missing
# key never reads as "no drops".
DROP_REASONS = ("queue_full", "persist_error", "transcode_exception", "shutdown_queued", "shutdown_inflight",
                "writer_shutdown")

_writer: contextvars.ContextVar[str | None] = contextvars.ContextVar("write_telemetry_writer", default=None)
_rng = random.Random(0)


class _Hist:
    __slots__ = ("n", "xs", "mx", "sum")

    def __init__(self) -> None:
        self.n, self.xs, self.mx, self.sum = 0, [], 0.0, 0.0

    def add(self, x: float) -> None:
        self.n += 1
        self.sum += x
        if x > self.mx:
            self.mx = x
        if len(self.xs) < _SAMPLES_MAX:
            self.xs.append(x)
        else:
            j = _rng.randrange(self.n)
            if j < _SAMPLES_MAX:
                self.xs[j] = x

    def triple(self) -> list[float] | None:
        if not self.n:
            return None
        xs = sorted(self.xs)
        q = lambda p: xs[min(len(xs) - 1, int(len(xs) * p))]  # noqa: E731
        return [round(q(0.5), 1), round(q(0.95), 1), round(self.mx, 1)]


class _Writer:
    __slots__ = ("wait", "hold", "locked", "rb")

    def __init__(self) -> None:
        self.wait, self.hold, self.locked, self.rb = _Hist(), _Hist(), 0, 0


class _Acct:
    __slots__ = ("f", "d", "sec", "sec_n", "d1", "ten", "ten_n", "d10")

    def __init__(self) -> None:
        self.f = self.d = self.sec_n = self.d1 = self.ten_n = self.d10 = 0
        self.sec = self.ten = -1


class _Interval:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.frames = self.dms = 0
        self.fsec = self.ften = -1
        self.fsec_n = self.ften_n = self.f1 = self.f10 = 0
        self.acct: dict[str, _Acct] = {}
        self.q_max = self.batches = self.batch_sum = self.batch_max = 0
        self.q_age = 0.0
        self.writers: dict[str, _Writer] = {}
        self.out_max = self.open_max = 0
        self.overflow_max: int | None = None
        self.opened = self.closed = 0
        self.drops: dict[str, int] = {}
        self.sse = _Hist()
        self.ow_batches = self.ow_ops = self.ow_entries = self.ow_max = self.ow_q = self.ow_failed = 0
        self.ow_flush, self.ow_age = _Hist(), _Hist()


_cur = _Interval()
_drops_cum: dict[str, int] = {}
_enq: "list[float]" = []          # enqueue monotonic times, FIFO with the persist queue
_enq_head = 0                     # index of the oldest still queued in _enq
_pool = None                      # the instrumented engine's pool
_spills_seen = 0
_task: asyncio.Task | None = None


# ── ingest ───────────────────────────────────────────────────────────

def frame(account_id, event_type, event) -> None:
    """One frame handed to events.handle_event."""
    if not ENABLED:
        return
    c = _cur
    now = time.time()
    sec, ten = int(now), int(now // 10)
    c.frames += 1
    if sec != c.fsec:
        c.fsec, c.fsec_n = sec, 0
    c.fsec_n += 1
    if c.fsec_n > c.f1:
        c.f1 = c.fsec_n
    if ten != c.ften:
        c.ften, c.ften_n = ten, 0
    c.ften_n += 1
    if c.ften_n > c.f10:
        c.f10 = c.ften_n
    key = str(account_id) if account_id is not None else "-"
    a = c.acct.get(key)
    if a is None:
        a = c.acct[key] = _Acct()
    a.f += 1
    if event_type != "api2_chat_message":
        return
    m = event.get(event_type)
    if not isinstance(m, dict) or str((m.get("fromUser") or {}).get("id")) == key:
        return  # an outbound echo
    c.dms += 1
    a.d += 1
    if sec != a.sec:
        a.sec, a.sec_n = sec, 0
    a.sec_n += 1
    if a.sec_n > a.d1:
        a.d1 = a.sec_n
    if ten != a.ten:
        a.ten, a.ten_n = ten, 0
    a.ten_n += 1
    if a.ten_n > a.d10:
        a.d10 = a.ten_n


def enqueued(depth: int) -> None:
    """An item went into the persist queue, which now holds `depth`."""
    if not ENABLED:
        return
    _enq.append(time.monotonic())
    if depth > _cur.q_max:
        _cur.q_max = depth


def dequeued(n: int = 1) -> None:
    """`n` items left the persist queue from its head (taken by the worker, or
    displaced as the oldest)."""
    global _enq_head
    if not ENABLED:
        return
    now = time.monotonic()
    c = _cur
    for _ in range(n):
        if _enq_head >= len(_enq):
            break
        age = (now - _enq[_enq_head]) * 1000
        _enq_head += 1
        if age > c.q_age:
            c.q_age = age
    if _enq_head > 4096 and _enq_head * 2 > len(_enq):
        del _enq[:_enq_head]
        _enq_head = 0


def batch(n: int) -> None:
    if not ENABLED:
        return
    c = _cur
    c.batches += 1
    c.batch_sum += n
    if n > c.batch_max:
        c.batch_max = n


def drop(reason: str, n: int = 1) -> None:
    """`n` events lost on `reason`'s path. Counted even with telemetry off, so
    the shutdown line can still be forced; cheap either way."""
    if n <= 0:
        return
    _cur.drops[reason] = _cur.drops.get(reason, 0) + n
    _drops_cum[reason] = _drops_cum.get(reason, 0) + n


def writer_queued(depth: int) -> None:
    """An op went into the OF-cache writer's queue, which now holds `depth`."""
    if ENABLED and depth > _cur.ow_q:
        _cur.ow_q = depth


def writer_batch(ops: int, entries: int, flush_ms: float, ages_ms: list[float]) -> None:
    """The OF-cache writer committed `ops` ops (`entries` after coalescing)."""
    if not ENABLED:
        return
    c = _cur
    c.ow_batches += 1
    c.ow_ops += ops
    c.ow_entries += entries
    if ops > c.ow_max:
        c.ow_max = ops
    c.ow_flush.add(flush_ms)
    for a in ages_ms:
        c.ow_age.add(a)


def writer_failed(n: int) -> None:
    if ENABLED:
        _cur.ow_failed += n


def sse_sent(lag_ms: float) -> None:
    if ENABLED:
        _cur.sse.add(lag_ms)


# ── writer labels ────────────────────────────────────────────────────

@contextlib.contextmanager
def writer(name: str):
    """Label the SQLite writes made inside (and in tasks started inside)."""
    token = _writer.set(name)
    try:
        yield
    finally:
        _writer.reset(token)


def labelled(name: str):
    """Decorator: `writer(name)` around every call of an async function."""
    def wrap(fn):
        @functools.wraps(fn)
        async def run(*a, **kw):
            with writer(name):
                return await fn(*a, **kw)
        return run
    return wrap


_ID_SEG = re.compile(r"/(?:\d+|[0-9a-fA-F-]{16,})(?=/|$)")


async def label_request_writes(request, call_next):
    """http_hooks hook: label the request's writes `http:<METHOD> <path>`."""
    if ENABLED and _writer.get() is None:
        _writer.set(f"http:{request.method} {_ID_SEG.sub('/{}', request.url.path)}")
    return await call_next(request)


def _label() -> str:
    w = _writer.get()
    if w is not None:
        return w
    try:
        t = asyncio.current_task()
    except RuntimeError:
        t = None
    if t is None:
        return "thread"
    coro = t.get_coro()
    return "task:" + getattr(coro, "__qualname__", type(coro).__name__)


def _w(label: str) -> _Writer:
    ws = _cur.writers
    w = ws.get(label)
    if w is None:
        if len(ws) >= _WRITERS_MAX:
            label = "other"
            w = ws.get(label)
        if w is None:
            w = ws[label] = _Writer()
    return w


# ── the engine hook ──────────────────────────────────────────────────

def instrument(async_engine) -> None:
    """Time and count `async_engine`'s writes. Its dialect's execute / commit /
    rollback methods are wrapped on the instance (not SQLAlchemy Connection
    events: any of those switches on per-statement event dispatch for every
    hook; and its commit event fires before the DBAPI commit, not after). A
    write transaction's state lives in its DBAPI connection's `info` from the
    first write statement until COMMIT / ROLLBACK returns. Pool counts come
    from pool events. Nothing here changes what runs or when."""
    global _pool
    if not ENABLED:
        return
    from sqlalchemy import event

    sync = async_engine.sync_engine
    _pool = sync.pool
    dialect = sync.dialect

    def timed(real):
        def run(cursor, statement, *rest):
            context = rest[-1] if rest else None
            try:
                info = context._dbapi_connection.info
            except AttributeError:
                return real(cursor, statement, *rest)
            st = info.get("_wt")
            head = statement.lstrip()[:15].upper()
            if st is None and (head[:6].startswith(_WRITE_VERBS) or head == _BEGIN_IMMEDIATE):
                st = info["_wt"] = [time.perf_counter(), None, _label()]
            try:
                out = real(cursor, statement, *rest)
            except Exception as e:
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    _w(st[2] if st else _label()).locked += 1
                raise
            if st is not None:
                if st[1] is None:
                    st[1] = time.perf_counter()
                end = _TXN_END.get(statement.strip().upper()) if len(head) <= 8 else None
                if end is not None:
                    finish(context._dbapi_connection, end)
            return out
        return run

    def finish(fairy, rolled_back: bool) -> None:
        try:
            st = fairy.info.pop("_wt", None)
        except Exception:  # noqa: BLE001 — a bare DBAPI connection / invalidated record
            return
        if st is None:
            return
        end = time.perf_counter()
        w = _w(st[2])
        if st[1] is None:  # the first write itself failed
            w.wait.add((end - st[0]) * 1000)
            w.rb += 1
            return
        w.wait.add((st[1] - st[0]) * 1000)
        w.hold.add((end - st[1]) * 1000)
        if rolled_back:
            w.rb += 1

    def ended(real, rolled_back: bool):
        def run(dbapi_connection):
            try:
                real(dbapi_connection)
            except Exception as e:
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    st = getattr(dbapi_connection, "info", {}).get("_wt")
                    _w(st[2] if st else _label()).locked += 1
                raise
            finally:
                finish(dbapi_connection, rolled_back)
        return run

    dialect.do_execute = timed(dialect.do_execute)
    dialect.do_execute_no_params = timed(dialect.do_execute_no_params)
    dialect.do_executemany = timed(dialect.do_executemany)
    dialect.do_commit = ended(dialect.do_commit, False)
    dialect.do_rollback = ended(dialect.do_rollback, True)

    def on_connect(*_a):
        _cur.opened += 1

    def on_close(*_a):
        _cur.closed += 1

    def on_checkout(*_a):
        c = _cur
        try:
            out = _pool.checkedout()
            ov = _pool.overflow()   # QueuePool: open connections - pool_size
            size = _pool.size()
        except Exception:  # noqa: BLE001 — NullPool / StaticPool keep no such counts
            return
        if out > c.out_max:
            c.out_max = out
        if c.overflow_max is None or ov > c.overflow_max:
            c.overflow_max = ov
        if size + ov > c.open_max:
            c.open_max = size + ov

    event.listen(_pool, "connect", on_connect)
    event.listen(_pool, "close", on_close)
    event.listen(_pool, "close_detached", on_close)
    event.listen(_pool, "checkout", on_checkout)


# ── emission ─────────────────────────────────────────────────────────

def snapshot(reason: str) -> dict:
    """The current interval as a dict, and start the next one."""
    global _cur, _spills_seen
    c, _cur = _cur, _Interval()
    now = time.monotonic()
    s = now - c.t0
    head_age = (now - _enq[_enq_head]) * 1000 if _enq_head < len(_enq) else 0.0
    ws, lock_ms = {}, 0.0
    for label, w in sorted(c.writers.items()):
        lock_ms += w.hold.sum + w.wait.sum
        ws[label] = {"n": w.wait.n, "wait": w.wait.triple(), "hold": w.hold.triple(),
                     "hold_sum_ms": round(w.hold.sum, 1), "locked": w.locked, "rb": w.rb}
    spills = getattr(_pool, "spills", None)
    pool = {"out_max": c.out_max, "open_max": c.open_max,
            "overflow_max": max(0, c.overflow_max) if c.overflow_max is not None else None,
            "opened": c.opened, "closed": c.closed}
    if spills is not None:
        pool["spills"], _spills_seen = spills - _spills_seen, spills
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reason": reason, "s": round(s, 1),
        "in": {"frames": c.frames, "dms": c.dms, "f1": c.f1, "f10": c.f10,
               "acct": {k: {"f": a.f, "d": a.d, "d1": a.d1, "d10": a.d10} for k, a in sorted(c.acct.items())}},
        "q": {"max": c.q_max, "age_ms": round(c.q_age, 1), "head_age_ms": round(head_age, 1),
              "batches": c.batches, "batch_mean": round(c.batch_sum / c.batches, 1) if c.batches else 0,
              "batch_max": c.batch_max},
        "w": ws, "lock": round(lock_ms / 1000 / s, 4) if s > 0 else None, "pool": pool,
        "drops": {**dict.fromkeys(DROP_REASONS, 0), **c.drops},
        "drops_cum": {**dict.fromkeys(DROP_REASONS, 0), **_drops_cum},
        "ow": {"batches": c.ow_batches, "ops": c.ow_ops, "merged": c.ow_ops - c.ow_entries,
               "batch_mean": round(c.ow_ops / c.ow_batches, 1) if c.ow_batches else 0,
               "batch_max": c.ow_max, "flush_ms": c.ow_flush.triple(), "age_ms": c.ow_age.triple(),
               "q_max": c.ow_q, "failed": c.ow_failed},
        "sse": {"n": c.sse.n, "lag": c.sse.triple()},
    }


def emit(reason: str = "flush") -> dict | None:
    """Log the current interval as one JSON line and start the next. Never raises."""
    if not ENABLED:
        return None
    try:
        snap = snapshot(reason)
        log.info("write_telemetry %s", json.dumps(snap, separators=(",", ":")))
        return snap
    except Exception:  # noqa: BLE001 — telemetry must never take the relay with it
        log.exception("write_telemetry emit failed")
        return None


async def _loop() -> None:
    nxt = time.monotonic() + INTERVAL_S
    while True:
        await asyncio.sleep(max(0.0, nxt - time.monotonic()))
        emit("interval")
        nxt += INTERVAL_S
        if nxt < time.monotonic():  # the loop was stalled past a whole interval
            nxt = time.monotonic() + INTERVAL_S


def start() -> None:
    """Start the periodic emitter on the running loop. Idempotent."""
    global _task, _cur
    if not ENABLED or (_task is not None and not _task.done()):
        return
    _cur = _Interval()
    _task = asyncio.create_task(_loop(), name="write-telemetry")
    log.info("write_telemetry every %gs (CHATTERLY_WRITE_TELEMETRY_S)", INTERVAL_S)


async def stop() -> None:
    """Stop the emitter and log the last (partial) interval."""
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
    emit("shutdown")
