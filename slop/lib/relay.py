"""The slop relay: scripts/demo-shots/relay_guarded.py (temp DB, network guards,
redirected secrets and sessions, CHATTERLY_TEST_MODE) plus loopback-only hooks.

  POST /__slop/of-ws-frame  {account_id, frame}  -> server._broadcast_event(frame)
       The exact call the OF WebSocket pump makes per frame (server.py), so
       everything downstream is the real product path: event_inbox persist,
       transcoder (messages / fans / chats.unread_count), SSE fan-out.
  GET  /__slop/stats        frames received; processed (transcode() returned, for
       quiescence); transcoded (a canonical writer returned without raising: the
       successes only); persist drops; queue depth.
  GET  /__slop/loop-cpu     time.thread_time() of the event-loop thread (lib/procmon.py
       polls it each second: the loop's own CPU, the one-core ceiling).
  POST /__slop/telemetry-flush  emit service/db/write_telemetry's JSON line now
       (reason "flush"; its shutdown line, early), so the counts are in relay.log.

The other half of that same wire: a chatter's reply goes OUT to OnlyFans through
`OFClient.send_message`. The seeded Creators' stub sessions cannot build an
OFClient (and must not: curl_cffi would bypass the socket guard), so
`server._load_client` is wrapped: where the real build fails, it returns
`_OfflineOF`, whose `send_message` answers what OF answers (the new message: id,
text, createdAt) and whose every other attribute re-raises the build's own error.
Everything around the send (attribution row, unread clear, `chat_responded`,
cache busts) is the product's own code.

One OF read is faked, and only when a scenario writes OF's side of the record:
`get_messages` (GET /api2/v2/chats/{fan}/messages, the chat scrape's read) pages
`$DEMO_SHOTS_TMP/of-truth.jsonl` (one line per message OnlyFans holds:
{account_id, fan_id, message}), newest first, as OF does. The executor's
client seam (`automation_executor._make_client`, used by the scrape and the
chat's rescrape-now route) falls back to `_OfflineOF` the same way. Without the
file, `get_messages` re-raises the build error like any other read.

The hooks are not product requests: no `actions` audit row is written for them
(the real pump hands a frame to _broadcast_event with no HTTP request around it).

With SLOP_PROFILE=1 (`slop/run --profile`) a stack sampler thread runs in this
process (`_Sampler`): ~200 times a second it reads every thread's Python stack
(sys._current_frames) and adds the wall time since its last look to the leaf
("self") and every on-stack ("cumulative") frame, per stage. `POST /__slop/profile
{stage}` sets the stage, `GET /__slop/profile` returns the totals. Bypass,
declared: this is not py-spy (macOS needs root for that). It shares the GIL, so
it costs the relay some CPU (a few % of a core), sees a running thread only at a
GIL switch, and cannot tell a thread on CPU from one blocked in C: a sample whose
leaf is a known blocking wait (select, Condition.wait, queue get, idle executor
worker; IDLE_LEAVES / IDLE_LINE) counts as idle and is left out of the shares.
"""

import contextvars
import inspect
import linecache
import os
import re
import runpy
import sys
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ["DEMO_SHOTS_ROOT"])
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

_real_run = uvicorn.run
_stats = {"received": 0, "processed": 0, "transcoded": 0, "of_sends": 0}
OF_SEND_ID_BASE = 9_700_000_000_000


class _OfflineOF:
    """A Creator whose OFClient cannot be built in a slop run: OnlyFans' answer to
    POST /api2/v2/chats/{chat_id}/messages, and the build error for anything else."""

    def __init__(self, account_id: str, err: Exception):
        self.account_id, self._err = account_id, err
        self.user_id = str(account_id)

    def send_message(self, chat_id, text, **_kw) -> dict:
        from datetime import datetime, timezone
        _stats["of_sends"] += 1
        return {"id": OF_SEND_ID_BASE + _stats["of_sends"], "text": text, "price": 0, "isFree": True,
                "mediaCount": 0, "media": [], "fromUser": {"id": int(self.account_id)},
                "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}

    def get_messages(self, chat_id, *, limit=10, order="desc", before_id=None, **_kw) -> dict:
        truth = Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-truth.jsonl"
        if not truth.is_file():
            raise self._err
        import json
        rows = []
        for line in truth.read_text().splitlines():
            r = json.loads(line)
            if str(r["account_id"]) == self.account_id and int(r["fan_id"]) == int(chat_id):
                rows.append(r["message"])
        rows.sort(key=lambda m: int(m["id"]), reverse=order == "desc")
        if before_id is not None:
            rows = [m for m in rows if (int(m["id"]) < int(before_id)) == (order == "desc")]
        return {"list": rows[:limit], "hasMore": len(rows) > limit}

    def __getattr__(self, name):
        raise self._err


# The canonical writers event_transcoder.transcode() dispatches to (looked up as
# module globals at call time, so patching the module attribute is enough).
WRITERS = ("_transcode_chat_message", "_transcode_ppv_unlock", "_transcode_toast",
           "_record_queue_frame", "_touch_fan_from_event")
_outcome: contextvars.ContextVar[dict | None] = contextvars.ContextVar("slop_transcode_outcome", default=None)


def _track(mod, name: str) -> None:
    """Mark the current transcode() call: a writer returned / a writer raised."""
    real = getattr(mod, name)

    def mark(key: str) -> None:
        o = _outcome.get()
        if o is not None:
            o[key] = True

    if inspect.iscoroutinefunction(real):
        async def wrapped(*a, **k):
            try:
                out = await real(*a, **k)
            except BaseException:
                mark("raised")
                raise
            mark("wrote")
            return out
    else:
        def wrapped(*a, **k):
            try:
                out = real(*a, **k)
            except BaseException:
                mark("raised")
                raise
            mark("wrote")
            return out
    setattr(mod, name, wrapped)


# (file basename, function) of a leaf frame that is blocked, not running.
IDLE_LEAVES = {("selectors.py", "select"), ("threading.py", "wait"), ("threading.py", "_wait_for_tstate_lock"),
               ("thread.py", "_worker"), ("queue.py", "get"), ("socket.py", "accept"), ("threading.py", "_bootstrap_inner")}
# ... or whose current source line is a blocking call into C (e.g. aiosqlite's
# `tx_item = self._tx.get()` on a SimpleQueue, whose leaf is Connection.run).
IDLE_LINE = re.compile(r"\.get\((block|timeout|\))|\.wait\(|\.acquire\(|\bselect\(|\.control\(|\bsleep\(|\.accept\(|\.recv")


def _part() -> dict:
    return {"busy": 0.0, "self": Counter(), "lines": Counter(), "cum": Counter(), "stacks": Counter(),
            "threads": Counter()}


class _Sampler:
    """Two samplers into one per-stage table, both weighted by the wall ms since
    their last look (so a sample that comes late still covers the time it missed):

    loop: a SIGALRM itimer at HZ. Python runs the handler in the main thread (the
    event loop) at its next bytecode, with the interrupted frame: idle in select,
    or the Python line it is on, or (after a long C call holding the GIL, e.g. the
    json encoder) the line that made the call. A loop waiting for the GIL counts
    as busy where it stopped.
    threads: a daemon thread reads every other thread's stack (sys._current_frames)
    at HZ. It only gets the GIL where they release it, i.e. in C (SQLite, I/O), so
    an aiosqlite worker is labelled with the statement it is running ("sql: ...").
    Wall time, not CPU: a statement waiting on SQLite's lock looks the same."""
    HZ = 200
    LAST_SQL: dict[int, str] = {}

    def __init__(self):
        self.stage: str | None = None
        self.stages: dict[str, dict] = {}
        self._keys: dict = {}
        self._idle: dict = {}
        self._lock = threading.RLock()  # the loop's handler can fire inside dump()
        self._main = threading.main_thread().ident
        self._prefixes = sorted({str(ROOT / "service") + "/", str(ROOT) + "/",
                                 *(p + "/" for p in sys.path if p.endswith("site-packages")),
                                 os.path.dirname(os.__file__) + "/"}, key=len, reverse=True)

    def start(self) -> None:
        """From the main thread, before the loop runs."""
        import signal
        self._last_alarm = time.perf_counter()
        signal.signal(signal.SIGALRM, self._on_alarm)
        signal.siginterrupt(signal.SIGALRM, False)  # SA_RESTART: no extra EINTR in other threads
        signal.setitimer(signal.ITIMER_REAL, 1 / self.HZ, 1 / self.HZ)
        threading.Thread(target=self._threads_loop, name="slop-profiler", daemon=True).start()
        # SQLite runs a SELECT inside fetchall(), whose partial carries no SQL: remember
        # each sqlite3 cursor's last statement (aiosqlite's Cursor.execute, a library).
        import aiosqlite.cursor
        real_execute = aiosqlite.cursor.Cursor.execute
        last = _Sampler.LAST_SQL

        async def execute(cur, sql, parameters=None):
            if len(last) > 5000:
                last.clear()
            last[id(cur._cursor)] = sql
            return await real_execute(cur, sql, parameters)

        aiosqlite.cursor.Cursor.execute = execute

    def _key(self, code) -> str:
        k = self._keys.get(code)
        if k is None:
            f = code.co_filename
            for p in self._prefixes:
                if f.startswith(p):
                    f = f[len(p):]
                    break
            k = self._keys[code] = f"{f}:{code.co_firstlineno}:{code.co_qualname}"
        return k

    def _bucket(self) -> dict:
        name = self.stage or "-"
        b = self.stages.get(name)
        if b is None:
            b = self.stages[name] = {"wall_ms": 0.0, "ticks": 0, "loop": _part(), "threads": _part()}
        return b

    def _is_idle(self, code, line) -> bool:
        idle = self._idle.get((code, line))
        if idle is None:
            idle = self._idle[(code, line)] = (
                (os.path.basename(code.co_filename), code.co_name) in IDLE_LEAVES
                or bool(IDLE_LINE.search(linecache.getline(code.co_filename, line or 0))))
        return idle

    @staticmethod
    def _short(sql: str) -> str:
        """Start of the statement plus its FROM ... (the part that tells two SELECTs apart)."""
        sql = " ".join(sql.split())
        i = sql.find(" FROM ")
        return sql[:140] if i < 0 or i < 60 else f"{sql[:50]} ...{sql[i:i + 170]}"

    @staticmethod
    def _sql_label(fr) -> str | None:
        """What an aiosqlite worker is executing: Connection.run's `function` partial."""
        fn = fr.f_locals.get("function")
        args = getattr(fn, "args", ())
        if args and isinstance(args[0], str):
            return "sql: " + _Sampler._short(args[0])
        f = getattr(fn, "func", None)
        if f is None:
            return None
        sql = _Sampler.LAST_SQL.get(id(getattr(f, "__self__", None)))
        name = getattr(f, "__qualname__", f)
        return f"{name}: " + _Sampler._short(sql) if sql and "fetch" in str(name) else f"call: {name}"

    def _add(self, part: dict, fr, w: float, thread: str) -> None:
        code, line = fr.f_code, fr.f_lineno
        if self._is_idle(code, line):
            return
        part["busy"] += w
        part["threads"][thread] += w
        leaf = None
        if code.co_qualname == "Connection.run" and "aiosqlite" in code.co_filename:
            leaf = self._sql_label(fr)
        stack = []
        while fr is not None and len(stack) < 80:
            stack.append(self._key(fr.f_code))
            fr = fr.f_back
        leaf = leaf or stack[0]
        part["self"][leaf] += w
        part["lines"][f"{stack[0].rsplit(':', 2)[0]}:{line}"] += w
        for k in set(stack):
            part["cum"][k] += w
        part["stacks"][";".join(reversed(stack))] += w

    def _on_alarm(self, _sig, frame) -> None:
        now = time.perf_counter()
        w, self._last_alarm = (now - self._last_alarm) * 1000, now
        if frame is not None:
            with self._lock:
                self._add(self._bucket()["loop"], frame, w, "MainThread")

    def _threads_loop(self) -> None:
        me, period, last = threading.get_ident(), 1 / self.HZ, time.perf_counter()
        while True:
            time.sleep(period)
            with self._lock:
                now = time.perf_counter()
                w, last = (now - last) * 1000, now
                b = self._bucket()
                b["ticks"] += 1
                b["wall_ms"] += w
                names = {t.ident: t.name for t in threading.enumerate()}
                for tid, fr in sys._current_frames().items():
                    if tid not in (me, self._main):
                        self._add(b["threads"], fr, w, names.get(tid, str(tid)).rstrip("0123456789").rstrip("_-"))

    def dump(self) -> dict:
        with self._lock:
            return {"hz": self.HZ, "stages": {
                n: {"wall_ms": b["wall_ms"], "ticks": b["ticks"],
                    **{part: {k: dict(v) if isinstance(v, Counter) else v for k, v in b[part].items()}
                       for part in ("loop", "threads")}}
                for n, b in self.stages.items()}}


def _db_probe():
    """Counters on the product's SQLAlchemy pool, from SQLAlchemy's own pool events
    (read-only listeners, no product code changed): connections opened / closed so
    far, checked out now and the peak since the last poll, and `nested`: checkouts
    by an asyncio task that already held a connection (with a bounded pool, the
    pattern that can wait on itself). Returns a function that snapshots them."""
    import asyncio
    import traceback

    from sqlalchemy import event

    import db.engine  # noqa: F401 — the package re-exports `engine` (the AsyncEngine) over the module name
    dbe = sys.modules["db.engine"]

    c = {"opened": 0, "closed": 0, "out": 0, "out_peak": 0, "checkouts": 0, "nested": 0}
    held: dict[int, object] = {}  # id(pool record) -> the task that checked it out
    per_task: Counter = Counter()
    nested_at: Counter = Counter()  # where nested checkouts come from (top frames in service/)

    def task():
        try:
            return asyncio.current_task()
        except RuntimeError:
            return None

    def stack():
        # The checkout runs in SQLAlchemy's greenlet; the coroutine frames (the
        # service/ code that opened the session) are on its parent greenlet.
        frames = traceback.extract_stack(limit=60)
        parent = getattr(sys.modules.get("greenlet") and sys.modules["greenlet"].getcurrent(), "parent", None)
        if parent is not None and parent.gr_frame is not None:
            frames = traceback.extract_stack(parent.gr_frame, limit=60) + frames
        return frames

    def on_connect(*_a):
        c["opened"] += 1

    def on_close(*_a):
        c["closed"] += 1

    def on_checkout(_dbapi, rec, _proxy):
        t = task()
        c["checkouts"] += 1
        c["out"] += 1
        c["out_peak"] = max(c["out_peak"], c["out"])
        if t is not None:
            if per_task[t]:
                c["nested"] += 1
                if len(nested_at) < 200:
                    frames = [f for f in stack() if "/service/" in f.filename]
                    nested_at[" <- ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}"
                                          for f in reversed(frames[-4:]))] += 1
            per_task[t] += 1
        held[id(rec)] = t

    def on_checkin(_dbapi, rec):
        c["out"] -= 1
        t = held.pop(id(rec), None)
        if t is not None:
            per_task[t] -= 1
            if per_task[t] <= 0:
                del per_task[t]

    sync = dbe.engine.sync_engine
    event.listen(sync, "connect", on_connect)
    event.listen(sync.pool, "close", on_close)
    event.listen(sync.pool, "close_detached", on_close)
    event.listen(sync.pool, "checkout", on_checkout)
    event.listen(sync.pool, "checkin", on_checkin)

    def snap() -> dict:
        out = {**c, "nested_at": dict(nested_at.most_common(5))}
        c["out_peak"] = c["out"]
        return out

    return snap


def _wire(app) -> None:
    from fastapi import HTTPException, Request

    import events
    import event_transcoder
    import faults
    import server

    faults.apply(os.environ.get("SLOP_FAULT") or None)
    # The hooks are not product requests: the real pump hands a frame to
    # _broadcast_event with no HTTP request around it, so no `actions` audit row
    # (one write transaction per injected frame) either.
    import employees
    employees._AUDIT_SKIP_PREFIXES = (*employees._AUDIT_SKIP_PREFIXES, "/__slop/")
    inner = event_transcoder.transcode

    async def counted(event):
        o = {"wrote": False, "raised": False}
        token = _outcome.set(o)
        try:
            return await inner(event)
        finally:
            _outcome.reset(token)
            _stats["processed"] += 1
            _stats["transcoded"] += o["wrote"] and not o["raised"]

    event_transcoder.transcode = counted  # the persist worker imports it at loop start
    # transcode() swallows its writers' exceptions, and a fault may skip them, so
    # "transcoded" counts calls where a writer returned and none raised.
    for name in WRITERS:
        _track(event_transcoder, name)
    real_load = server._load_client

    def load_client(account_id):
        try:
            return real_load(account_id)
        except Exception as e:  # noqa: BLE001 — re-raised on first use, unchanged
            return _OfflineOF(str(account_id), e)

    server._load_client = load_client
    import automation_executor
    real_make = automation_executor._make_client

    def make_client(account_id):
        try:
            return real_make(account_id)
        except Exception as e:  # noqa: BLE001 — re-raised on first use, unchanged
            return _OfflineOF(str(account_id), e)

    automation_executor._make_client = make_client
    app.on_event("startup")(events.start_persist_worker)

    def _loopback(request: Request) -> None:
        if (request.client.host if request.client else "") not in ("127.0.0.1", "::1"):
            raise HTTPException(status_code=403, detail="slop hooks are loopback-only")

    async def of_ws_frame(request: Request) -> dict:
        _loopback(request)
        body = await request.json()
        frame = dict(body["frame"])
        frame["__account_id"] = str(body["account_id"])
        frame["__account_name"] = body.get("account_name") or str(body["account_id"])
        _stats["received"] += 1
        await server._broadcast_event(frame)
        return {"ok": True}

    async def stats(request: Request) -> dict:
        _loopback(request)
        q = events._persist_queue
        return {**_stats, "persist_drops": events._persist_drops,
                "queue_depth": q.qsize() if q is not None else None,
                "fault": os.environ.get("SLOP_FAULT") or None}

    async def telemetry_flush(request: Request) -> dict:
        """Emit the product's write_telemetry line now (reason "flush"), as its
        shutdown does, so a scenario can read every count from relay.log before
        the stack stops. The line itself is the product's own code."""
        _loopback(request)
        from db import write_telemetry
        return {"line": write_telemetry.emit("flush")}

    sampler = None
    if os.environ.get("SLOP_PROFILE") == "1":
        sampler = _Sampler()
        sampler.start()  # _wire runs in the main thread, before uvicorn starts the loop

    async def profile_stage(request: Request) -> dict:
        _loopback(request)
        if sampler is None:
            raise HTTPException(status_code=404, detail="profiler off (slop/run --profile)")
        sampler.stage = (await request.json()).get("stage")
        return {"ok": True}

    async def profile_dump(request: Request) -> dict:
        _loopback(request)
        if sampler is None:
            raise HTTPException(status_code=404, detail="profiler off (slop/run --profile)")
        return sampler.dump()

    db = _db_probe()

    async def loop_cpu(request: Request) -> dict:
        """CPU seconds of the thread this handler runs on: the event loop's, plus the
        DB pool counters (`_db_probe`), polled together once a second by lib/procmon.py."""
        _loopback(request)
        return {"thread_s": time.thread_time(), "mono_s": time.monotonic(), "db": db()}

    app.add_api_route("/__slop/loop-cpu", loop_cpu, methods=["GET"])
    app.add_api_route("/__slop/profile", profile_stage, methods=["POST"])
    app.add_api_route("/__slop/profile", profile_dump, methods=["GET"])
    app.add_api_route("/__slop/of-ws-frame", of_ws_frame, methods=["POST"])
    app.add_api_route("/__slop/stats", stats, methods=["GET"])
    app.add_api_route("/__slop/telemetry-flush", telemetry_flush, methods=["POST"])


def _run(app, *a, **k):
    _wire(app)
    return _real_run(app, *a, **k)


uvicorn.run = _run
runpy.run_path(str(ROOT / "scripts/demo-shots/relay_guarded.py"), run_name="__main__")
