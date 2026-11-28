from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import contextvars
import importlib.abc
import importlib.machinery
import json
import os
import re
import sqlite3
import sys
import threading
import traceback
from pathlib import Path

COPIED = frozenset({
    "users", "chatters", "chatter_users", "employees", "employee_groups",
    "user_accounts", "chatter_account_access", "chatter_folder_access", "employee_account_access",
    "shift_assignments", "user_settings", "settings_versions", "sensitive_words", "owner_tokens",
    "user_llm_keys", "shifts", "mass_message_funnels", "blacklist",
    "push_subscriptions", "runtime_switches",
})
CONTROL = frozenset({
    "clock_events", "chatters_invites", "ultra_plans", "grok_user_daily_cost",
    "push_sent", "accounts", "proxies", "leak_tracker_tenant", "leak_watch",
    "leak_watch_tombstone",
})
CONTROL_PREFIX = "bio_"
CELL_MODE_ONLY_JOBS = frozenset({"agency-copy-poll", "bell-notices-to-control", "grant-age-watch", "reservation-activation-retry"})
LOCAL_BUT_REQUIRED = frozenset({"actions", "agency_notifications"})
MODES = ("block", "record")
OPS = ("INSERT", "UPDATE", "DELETE")
REQUIRED = {
    "last-seen touch": ("users", "UPDATE", "_touch_last_seen"),
    "chatter last_seen": ("chatters", "UPDATE", "_session_identity"),
    "lazy employee": ("employees", "INSERT", "get_or_create_mirror_employee"),
    "audit row": ("actions", "INSERT", "audit_middleware"),
    "session-dead notice": ("agency_notifications", "INSERT", "notify_creator_owners"),
}
TRIGGER_PREFIX = "cell_probe_"
_DML = ("INSERT", "UPDATE", "DELETE", "REPLACE", "WITH", "UPSERT")
BLOCK_MSG = "cell_probe_blocked:"

_HERE = Path(__file__).resolve().parent
_SERVICE = _HERE.parents[1]
_SERVICE_S = str(_SERVICE) + os.sep
_TESTS_S = str(_SERVICE / "tests") + os.sep
_HERE_S = str(_HERE) + os.sep
_PLUMBING = frozenset({"db/engine.py"})
_BOOT_FUNCS = {("db/engine.py", "init_db"), ("tests/_harness.py", "bootstrap")}
_ID_SEG = re.compile(r"/(?:\d+|[0-9a-fA-F-]{16,})(?=/|$)")

LABEL: contextvars.ContextVar[str | None] = contextvars.ContextVar("cell_probe_label", default=None)

_mode: str | None = None
_out: Path | None = None
_script = ""
_hits: dict[tuple, dict] = {}
_errors: list[str] = []
_lock = threading.Lock()
_real_connect = sqlite3.connect
_real_exit = os._exit


def table_class(name: str) -> str | None:
    if name in COPIED:
        return "copied"
    if name in CONTROL or name.startswith(CONTROL_PREFIX):
        return "control"
    if name in LOCAL_BUT_REQUIRED:
        return "local"
    return None


def mode() -> str | None:
    return _mode


def set_mode(m: str | None) -> None:
    global _mode
    if m not in (None, *MODES):
        raise ValueError(f"CELL_PROBE must be one of {MODES}, got {m!r}")
    _mode = m


def is_required(h: dict, table: str, op: str, func: str) -> bool:
    return h["table"] == table and h["op"] == op and any(f.endswith(":" + func) for f in h["frames"])


def registered_jobs(server) -> set[str]:
    import inspect

    src = inspect.getsource(server._start_event_pumps)
    direct = set(re.findall(r'name="([a-z0-9-]+)"', src)) | set(re.findall(r', "([a-z0-9-]+)"\)', src))
    observed = asyncio.run(_observe_jobs(server))
    missing = direct - observed - CELL_MODE_ONLY_JOBS
    if missing:
        raise AssertionError(f"startup registrations missing at runtime: {sorted(missing)}")
    return observed | direct


async def _observe_jobs(server) -> set[str]:
    from unittest.mock import patch
    import badge_reads
    import leak_tracker
    import push_send
    import runtime_switches
    import shared_refresher
    import vault_collect
    from automations import _common
    from db import of_writer, write_telemetry

    names, unnamed = set(), []
    push_label: list[str] = []
    loop = asyncio.get_running_loop()
    create_task = loop.create_task

    def capture(coro, *, name=None, **kwargs):
        module = coro.cr_frame.f_globals["__name__"]
        if module.startswith(("sqlalchemy.", "asyncio.")):
            return create_task(coro, name=name, **kwargs)
        name = name or (push_label[0] if push_label else None)
        if name is None:
            unnamed.append(coro.__qualname__)
        else:
            names.add(name.removeprefix("event-"))
        coro.close()
        return loop.create_future()

    async def skip_init():
        return None

    async def switches_unloaded():
        raise RuntimeError("probe: runtime switch overrides unavailable")

    with contextlib.ExitStack() as stack:
        overrides = (
            (asyncio, "create_task", capture),
            (loop, "create_task", capture),
            (loop, "run_in_executor", lambda *a: None),
            (server, "_sync_proxy_pool", lambda: None),
            (server, "db_init", skip_init),
            (server.account_registry, "list_accounts", lambda: []),
            (_common, "test_mode", lambda: False),
            (vault_collect, "ENABLED", True),
            (leak_tracker, "jobs_on", lambda: True),
            (badge_reads, "ENABLED", True),
            (badge_reads, "_task", None),
            (shared_refresher, "ENABLED", True),
            (shared_refresher, "_relay_loop", None),
            (of_writer, "start", lambda: None),
            (write_telemetry, "start", lambda: None),
            (push_send, "subject", lambda: ("mailto:probe@example.invalid", "")),
            (push_send, "vapid", lambda: None),
            (runtime_switches, "load", switches_unloaded),
        )
        for obj, attr, value in overrides:
            stack.enter_context(patch.object(obj, attr, value))
        for attr in ("_main_loop", "_supervisor_task", "_tx_ingest_task", "_tx_fast_task", "_automation_exec_task"):
            stack.enter_context(patch.object(server, attr, getattr(server, attr)))
        import events_persist
        stack.enter_context(patch.object(events_persist, "_persist_worker_task", None))
        stack.enter_context(patch.object(events_persist, "_persist_queue", None))
        stack.enter_context(patch.object(shared_refresher, "_task", None))
        await server._start_event_pumps()
        push_label.append("push-send")
        try:
            await push_send.start()
        finally:
            push_label.clear()
            for task in push_send._tasks:
                task.cancel()
            await push_send.stop()
    if unnamed:
        raise AssertionError(f"unnamed startup tasks: {unnamed}")
    return names


def hits() -> list[dict]:
    with _lock:
        return [dict(v) for v in _hits.values()]


@contextlib.contextmanager
def scratch():
    with _lock:
        keep = {k: dict(v) for k, v in _hits.items()}
    try:
        yield
    finally:
        with _lock:
            _hits.clear()
            _hits.update(keep)


def trigger_ddl(tables) -> dict[str, str]:
    out = {}
    for t in tables:
        if table_class(t) is None:
            continue
        for op in OPS:
            name = f"{TRIGGER_PREFIX}{t}_{op.lower()}"
            out[name] = (f'CREATE TEMP TRIGGER IF NOT EXISTS "{name}" BEFORE {op} ON main."{t}" BEGIN '
                         f"SELECT RAISE(ABORT, '{BLOCK_MSG}{t}') WHERE cell_probe('{t}', '{op}'); END")
    return out


def sync_triggers(execute, on: bool) -> int:
    tables = [r[0] for r in execute("SELECT name FROM sqlite_master WHERE type='table'")]
    query = f"WHERE type='trigger' AND name LIKE '{TRIGGER_PREFIX}%'"
    permanent = {r[0] for r in execute(f"SELECT name FROM sqlite_master {query}")}
    have = {r[0] for r in execute(f"SELECT name FROM sqlite_temp_master {query}")}
    want = trigger_ddl(tables) if on else {}
    n = len(permanent) + len(have - want.keys())
    for schema, names in (("main", permanent), ("temp", have - want.keys())):
        for name in sorted(names):
            execute(f'DROP TRIGGER IF EXISTS {schema}."{name}"')
    for name in sorted(want.keys() - have):
        execute(want[name])
        n += 1
    return n


class _State:
    __slots__ = ("label", "explicit", "frame")

    def __init__(self) -> None:
        self.label = None
        self.explicit = False
        self.frame = None


class _ProbeConnection(sqlite3.Connection):
    pass


def _label_now() -> tuple[str, bool]:
    lab = LABEL.get()
    if lab:
        return lab, True
    wt = sys.modules.get("db.write_telemetry")
    w = wt._writer.get() if wt is not None else None
    if w:
        return w, True
    try:
        t = asyncio.current_task()
    except RuntimeError:
        t = None
    if t is None:
        return "thread", False
    coro = t.get_coro()
    return "task:" + getattr(coro, "__qualname__", type(coro).__name__), False


def _frames_of(frame) -> list:
    out = []
    while frame is not None:
        out.append(frame)
        frame = frame.f_back
    out.reverse()
    return out


def _repo_rel(path: str) -> str | None:
    if not path.startswith(_SERVICE_S) or path.startswith(_HERE_S) or "site-packages" in path:
        return None
    return path[len(_SERVICE_S):]


def _summarise(frames: list) -> tuple[list[str], str, bool, bool]:
    repo, inner_rel, site, boot = [], None, None, False
    for f in frames:
        rel = _repo_rel(f.f_code.co_filename)
        if rel is None:
            continue
        func = f.f_code.co_name
        if (rel, func) in _BOOT_FUNCS:
            boot = True
        repo.append(f"{rel}:{f.f_lineno}:{func}")
        if rel not in _PLUMBING:
            inner_rel, site = rel, repo[-1]
    fixture = inner_rel is not None and (_SERVICE_S + inner_rel).startswith(_TESTS_S)
    return repo, site or (repo[-1] if repo else "?"), fixture, boot


def _in_aiosqlite_thread() -> bool:
    return type(threading.current_thread()).__module__.startswith("aiosqlite")


def _hit(st: _State, table: str, op: str) -> int:
    try:
        cls = table_class(table)
        if _mode is None or cls is None:
            return 0
        if _in_aiosqlite_thread():
            label, explicit = st.label or "thread", st.explicit
            frames = st.frame or []
        else:
            label, explicit = _label_now()
            frames = _frames_of(sys._getframe(1))
        repo, site, fixture, boot = _summarise(frames)
        if fixture and not explicit and not boot:
            return 0
        if boot and not explicit:
            label = "boot"
        blocked = _mode == "block" and cls != "local" and label != "boot"
        key = (table, op, label, site)
        with _lock:
            h = _hits.get(key)
            if h is None:
                h = _hits[key] = {"table": table, "op": op, "label": label, "test": _script, "mode": _mode,
                                  "class": cls, "site": site, "frames": repo[-40:], "n": 0, "blocked": blocked}
                if label == "thread":
                    h["stack"] = traceback.format_list(traceback.extract_stack(frames[-1]) if frames else [])[-30:]
            h["n"] += 1
        return 1 if blocked else 0
    except Exception as e:  # noqa: BLE001
        _errors.append(f"hit {table} {op}: {e!r}")
        return 1 if _mode == "block" and table_class(table) in ("copied", "control") else 0


def _attach(conn) -> None:
    st = _State()
    try:
        conn._cell_probe = st
    except AttributeError:
        pass
    conn.create_function("cell_probe", 2, lambda t, op: _hit(st, t, op))
    try:
        sync_triggers(lambda sql: conn.execute(sql).fetchall(), on=_mode is not None)
    except sqlite3.Error as e:
        _errors.append(f"install on connect: {e!r}")


def _connect(*a, **kw):
    if "factory" not in kw and len(a) < 6:
        kw["factory"] = _ProbeConnection
    conn = _real_connect(*a, **kw)
    _attach(conn)
    return conn


def _raw(dbapi_conn):
    c = dbapi_conn
    for _ in range(4):
        if isinstance(c, sqlite3.Connection):
            return c
        c = getattr(c, "_connection", None) or getattr(c, "driver_connection", None) or getattr(c, "_conn", None)
    return None


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if not statement.lstrip()[:7].upper().startswith(_DML):
        return
    raw = _raw(conn.connection.dbapi_connection)
    st = getattr(raw, "_cell_probe", None)
    if st is None:
        return
    st.label, st.explicit = _label_now()
    import greenlet
    parent = greenlet.getcurrent().parent
    st.frame = _frames_of(parent.gr_frame if parent is not None else None) + _frames_of(sys._getframe(1))


def _rows(result) -> list:
    return result.fetchall() if result.returns_rows else []


def _after_create(target, connection, **kw):
    try:
        sync_triggers(lambda sql: _rows(connection.exec_driver_sql(sql)), on=_mode is not None)
    except Exception as e:  # noqa: BLE001
        _errors.append(f"install after create_all: {e!r}")



def _checkout(dbapi_conn, record, proxy):
    if not isinstance(_raw(dbapi_conn), _ProbeConnection):
        return
    cursor = dbapi_conn.cursor()
    try:
        def execute(sql):
            cursor.execute(sql)
            return cursor.fetchall() if cursor.description else []
        sync_triggers(execute, on=_mode is not None)
    except sqlite3.Error as e:
        _errors.append(f"install on checkout: {e!r}")
    finally:
        cursor.close()


def _route_label(app, scope) -> str:
    from starlette.routing import Match
    method = scope.get("method", "?")
    for route in getattr(getattr(app, "router", None), "routes", ()):
        try:
            m, _ = route.matches(scope)
        except Exception:  # noqa: BLE001
            continue
        if m == Match.FULL:
            return f"http:{method} {getattr(route, 'path', scope.get('path', ''))}"
    return f"http:{method} {_ID_SEG.sub('/{}', scope.get('path', ''))}"


def _patch_starlette() -> None:
    from starlette.applications import Starlette
    real = Starlette.__call__

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or LABEL.get() is not None:
            return await real(self, scope, receive, send)
        tok = LABEL.set(_route_label(self, scope))
        try:
            return await real(self, scope, receive, send)
        finally:
            LABEL.reset(tok)

    Starlette.__call__ = __call__


def _patch_sqlalchemy() -> None:
    from sqlalchemy import MetaData, event
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import Pool
    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(Pool, "checkout", _checkout)
    event.listen(MetaData, "after_create", _after_create)


class _AfterImport(importlib.abc.MetaPathFinder):
    def __init__(self) -> None:
        self.hooks: dict = {}

    def find_spec(self, name, path, target=None):
        hook = self.hooks.pop(name, None)
        if hook is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None:
            return spec
        real = spec.loader.exec_module

        def exec_module(module):
            real(module)
            hook()
        spec.loader.exec_module = exec_module
        return spec


_finder = _AfterImport()


def _after_import(name: str, hook) -> None:
    # Importing these eagerly binds the real datetime before tests/_clock.py pins it.
    if name in sys.modules:
        hook()
        return
    _finder.hooks[name] = hook
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)


def _patch_executor() -> None:
    real = concurrent.futures.ThreadPoolExecutor.submit

    def submit(self, fn, /, *a, **kw):
        return real(self, contextvars.copy_context().run, fn, *a, **kw)

    concurrent.futures.ThreadPoolExecutor.submit = submit


_CHILD_BOOT = (
    "import sys, runpy; sys.path.insert(0, {here!r}); import cell_probe; cell_probe.activate_from_env()\n"
    "a = sys.argv[1:]\n"
    "if a[:1] == ['-']:\n"
    "    sys.argv = a; exec(compile(sys.stdin.read(), '<stdin>', 'exec'), {{'__name__': '__main__'}})\n"
    "elif a[:1] == ['-m']:\n"
    "    sys.argv = a[1:]; runpy.run_module(a[1], run_name='__main__', alter_sys=True)\n"
    "else:\n"
    "    sys.argv = a; runpy.run_path(a[0], run_name='__main__')\n"
)


def child_args(args: list) -> list:
    py, rest = args[0], list(args[1:])
    flags = []
    while rest and rest[0].startswith("-") and rest[0] not in ("-", "-m", "-c"):
        flags.append(rest.pop(0))
    if "-I" not in flags or (rest and rest[0] == "-c"):
        return list(args)
    return [py, *flags, "-c", _CHILD_BOOT.format(here=str(_HERE)), *rest]


def _is_python(args) -> bool:
    if not isinstance(args, (list, tuple)) or not args:
        return False
    a0 = str(args[0])
    return a0 == sys.executable or Path(a0).name.startswith("python")


def _patch_subprocess() -> None:
    import subprocess
    real = subprocess.Popen.__init__

    def __init__(self, args, *a, **kw):
        env = dict(kw["env"] if kw.get("env") is not None else os.environ)
        if _is_python(args) and env.get("CELL_PROBE"):
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(_HERE), env.get("PYTHONPATH"))))
            kw["env"] = env
            args = child_args(list(args))
        real(self, args, *a, **kw)

    subprocess.Popen.__init__ = __init__


def dump() -> None:
    if _out is None:
        return
    _out.mkdir(parents=True, exist_ok=True)
    root = os.environ.get("CELL_PROBE_ROOT_PID") == str(os.getpid())
    name = f"{_script}.jsonl" if root else f"{_script}.child-{os.getpid()}.jsonl"
    rows = [json.dumps(h, sort_keys=True) for h in hits()]
    rows += [json.dumps({"error": e, "test": _script}) for e in _errors]
    (_out / name).write_text("".join(r + "\n" for r in rows))


def _exit(code):
    try:
        dump()
    finally:
        _real_exit(code)


def activate(m: str, out: Path | None = None) -> None:
    global _out, _script
    set_mode(m)
    if sqlite3.connect is _connect:
        return
    _out = out
    if "CELL_PROBE_ROOT" not in os.environ:
        os.environ["CELL_PROBE_ROOT"] = Path(sys.argv[0] or "python").stem
        os.environ["CELL_PROBE_ROOT_PID"] = str(os.getpid())
    _script = os.environ["CELL_PROBE_ROOT"]
    sqlite3.connect = _connect
    sqlite3.dbapi2.connect = _connect
    _after_import("sqlalchemy", _patch_sqlalchemy)
    _after_import("starlette.applications", _patch_starlette)
    _patch_executor()
    _patch_subprocess()
    if out is not None:
        atexit.register(dump)
        os._exit = _exit


def activate_from_env() -> None:
    m = os.environ.get("CELL_PROBE", "").strip()
    if not m:
        return
    out = os.environ.get("CELL_PROBE_OUT", "").strip()
    if not out:
        raise SystemExit("CELL_PROBE set without CELL_PROBE_OUT")
    activate(m, Path(out))
