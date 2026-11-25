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
_SAMPLES_MAX = 4000
_WRITERS_MAX = 40
_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLAC")
_BEGIN_IMMEDIATE = "BEGIN IMMEDIATE"
_TXN_END = {"COMMIT": False, "END": False, "ROLLBACK": True}
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
_enq: "list[float]" = []
_enq_head = 0
_pool = None
_spills_seen = 0
_task: asyncio.Task | None = None



def frame(account_id, event_type, event) -> None:
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
        return
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
    if not ENABLED:
        return
    _enq.append(time.monotonic())
    if depth > _cur.q_max:
        _cur.q_max = depth


def dequeued(n: int = 1) -> None:
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
    if ENABLED and depth > _cur.ow_q:
        _cur.ow_q = depth


def writer_batch(ops: int, entries: int, flush_ms: float, ages_ms: list[float]) -> None:
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



@contextlib.contextmanager
def writer(name: str):
    token = _writer.set(name)
    try:
        yield
    finally:
        _writer.reset(token)


def labelled(name: str):
    def wrap(fn):
        @functools.wraps(fn)
        async def run(*a, **kw):
            with writer(name):
                return await fn(*a, **kw)
        return run
    return wrap


_ID_SEG = re.compile(r"/(?:\d+|[0-9a-fA-F-]{16,})(?=/|$)")


async def label_request_writes(request, call_next):
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



# Wraps dialect execute/commit/rollback, not Connection events: those enable per-statement dispatch for every hook, and commit fires before the DBAPI commit.
def instrument(async_engine) -> None:
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
        if st[1] is None:
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
            ov = _pool.overflow()
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



def snapshot(reason: str) -> dict:
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
        if nxt < time.monotonic():
            nxt = time.monotonic() + INTERVAL_S


def start() -> None:
    global _task, _cur
    if not ENABLED or (_task is not None and not _task.done()):
        return
    _cur = _Interval()
    _task = asyncio.create_task(_loop(), name="write-telemetry")
    log.info("write_telemetry every %gs (CHATTERLY_WRITE_TELEMETRY_S)", INTERVAL_S)


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
    emit("shutdown")
