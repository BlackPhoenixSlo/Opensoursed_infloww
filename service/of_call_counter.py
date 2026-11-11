"""The OF call counter: every signed OF request the Relay sends, counted by
(Caller kind, "METHOD folded-path", Creator, status class). Stdlib only, a leaf
beside of_pacing; `of_client._Transport._http_call` calls `record` once per
request that reached the send (a refused call never does).

Caller kind: `caller(name)` sets it for everything inside (tasks and
to_thread work too; innermost wins): `walk:<kind>` (of_pacing.walk), `auto:<kind>`
(automation_executor.run_once), `route:<METHOD> <folded path>` (`label_request_calls`, a server
hook), `loop:<task name>` (server's background tasks). Ids in any name fold (`fold_caller`).
No label: `task:<asyncio task name>` on the loop, else `unlabelled`.

Nothing is logged per call. In memory by default; the Relay calls `start(path)`
once (server.py, at import), which folds the file at `path` back in, bumps
`boots`, writes at once and runs one daemon thread that rewrites the file every
`FLUSH_S`, so a quiet Relay still refreshes `flushed_at`; the shutdown handler
flushes. `record` never writes. A process that never
calls `start` (a script, a test importing of_client) never writes a file.

File (`v` 1), the cumulative view since `started_at` across `boots` restarts:
  {"v": 1, "started_at": <epoch s>, "flushed_at": <epoch s>, "boots": n,
   "rows": [[caller kind, "METHOD folded-path", creator id or "-", status class, count], ...],
   "folded": <calls folded into the "other" rows past MAX_ROWS>, "write_error": null | "<Type: msg>",
   "unobserved_s": <s>, "unobserved_since": <epoch s>}
A missing, unreadable or other-version file, or any malformed field or row in it, starts a fresh
window (logged); never fails the boot.
`unobserved_s`: the seconds no Relay process counted (each boot adds boot time - the loaded file's
`flushed_at`), summed since `unobserved_since`. A boot that cannot measure its gap (no or a bad tally or
`flushed_at` in the file, a gap < 0 or non-finite: a clock step) restarts the tally at 0 from its own boot
time, so a reader comparing two snapshots with different `unobserved_since` knows the gap between them is
unknown (never 0). Measured once per boot: no per-call cost.

Knobs (read here only; a non-positive, non-finite or unparsable number -> the default, logged):
  OF_CALL_STATS_PATH      unset: of_call_stats.json in the SQLite DB's directory; empty: memory only
  OF_CALL_STATS_FLUSH_S   30
  OF_CALL_STATS_MAX_ROWS  20000 distinct keys; past it a new key counts as
                          ["other", "other", creator, status class] (bounded by Creators x 8)
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("of-relay.of_call_counter")

SCHEMA = 1
# db/write_telemetry._ID_SEG (a numeric or 16+ hex/dash segment); copied so this module stays a
# stdlib leaf (importing db/ pulls in the engine).
_ID_SEG = re.compile(r"/(?:\d+|[0-9a-fA-F-]{16,})(?=/|$)")
# /users/<x>: a username (of_reads.get_user) unless one of the static endpoints the code calls.
_USERS_SEG = re.compile(r"(/users/)(?!(?:me|list|notifications|performers|settings)(?:/|$))[^/]+")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        v = float(raw or default)
    except ValueError:
        v = math.nan
    if math.isfinite(v) and v > 0:
        return v
    log.warning("of_call_stats_bad_knob %s=%r; default %g", name, raw[:40], default)
    return default


FLUSH_S = _env_float("OF_CALL_STATS_FLUSH_S", 30.0)
MAX_ROWS = int(_env_float("OF_CALL_STATS_MAX_ROWS", 20000))


def stats_path() -> Path | None:
    """The Relay's counter file (`OF_CALL_STATS_PATH`), or None for memory only."""
    raw = os.environ.get("OF_CALL_STATS_PATH")
    if raw is not None:
        raw = raw.strip()
        return Path(raw) if raw else None
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite") and ":///" in url:
        db = url.split(":///", 1)[1].split("?", 1)[0]
        if db and Path(db).parent.is_dir():
            return Path(db).parent / "of_call_stats.json"
    return None


_lock = threading.Lock()          # the counts
_write_lock = threading.Lock()    # one file write at a time
_counts: dict[tuple[str, str, str, str], int] = {}   # cumulative: the file's rows plus this process
_folded = 0                       # this process's, plus the file's (added at start)
_started_at = time.time()
_boots = 1
_flushed_at: float | None = None
_write_error: str | None = None
_path: Path | None = None
_unobserved_s = 0.0               # the tally (see the module doc): Relay downtime since _unobserved_since
_unobserved_since = _started_at


def status_class(status) -> str:
    """OF's answer as a status class (2xx 3xx 401 403 429 4xx 5xx error); None (no answer came back) is `error`."""
    if not isinstance(status, int):
        return "error"
    if status in (401, 403, 429):
        return str(status)
    if 200 <= status < 600:
        return f"{status // 100}xx"
    return "error"


def path_key(method, url) -> str:
    """"METHOD /path" with ids and usernames folded to {} and the query dropped."""
    p = urlsplit(str(url or "")).path or "/"
    p = _USERS_SEG.sub(r"\1{}", _ID_SEG.sub("/{}", p))
    return f"{str(method or '?').upper()} {p}"


# ── Caller kinds ─────────────────────────────────────────────────────
# A ContextVar, so a label follows its work into tasks and `asyncio.to_thread` started inside
# (context copy); a bare `threading.Thread` starts empty. Innermost scope wins.
_caller: contextvars.ContextVar[str | None] = contextvars.ContextVar("of_call_counter_caller", default=None)
# A dash segment that is a run / Creator / chat id (digits, or 8+ hex) in a name.
_DASH_ID = re.compile(r"-(?:\d+|[0-9a-fA-F]{8,})(?=-|$)")


def fold_caller(name) -> str:
    """Ids in a Caller kind folded to {}, so one code site is one kind:
    `mass-recipients-1545` -> `mass-recipients-{}`, `route:GET /api/x/123` -> `route:GET /api/x/{}`."""
    return _DASH_ID.sub("-{}", _ID_SEG.sub("/{}", str(name)))


@contextlib.contextmanager
def caller(name: str):
    """The Caller kind of every OF call inside (and in tasks / to_thread work started inside)."""
    token = _caller.set(fold_caller(name))
    try:
        yield
    finally:
        _caller.reset(token)


async def label_request_calls(request, call_next):
    """http_hooks hook: the request's OF calls are `route:<METHOD> <folded path>`."""
    with caller("route:" + path_key(request.method, request.url.path)):
        return await call_next(request)


def caller_kind() -> str:
    """Who asked: the innermost `caller(...)` label, else `task:<asyncio task name>` on the
    event loop's thread, else `unlabelled`."""
    label = _caller.get()
    if label is not None:
        return label
    try:
        task = asyncio.current_task()
    except RuntimeError:   # no running loop in this thread
        task = None
    return "task:" + fold_caller(task.get_name()) if task is not None else "unlabelled"


def record(account_id, method, url, status) -> None:
    """One OF request sent for `account_id`; `status` its answer's code, or None when none
    came back. Never raises."""
    global _folded
    try:
        key = (caller_kind(), path_key(method, url), str(account_id) if account_id else "-",
               status_class(status))
        with _lock:
            if key not in _counts and len(_counts) >= MAX_ROWS:
                key = ("other", "other", key[2], key[3])
                _folded += 1
            _counts[key] = _counts.get(key, 0) + 1
    except Exception:  # noqa: BLE001 — counting must never break an OF call
        pass


def snapshot() -> dict:
    """The cumulative view (the file's rows plus this process), in the file's shape."""
    with _lock:
        counts = dict(_counts)
        folded = _folded
    return {"v": SCHEMA, "started_at": _started_at, "flushed_at": _flushed_at, "boots": _boots,
            "rows": [[*k, n] for k, n in sorted(counts.items())], "folded": folded,
            "write_error": _write_error, "unobserved_s": _unobserved_s, "unobserved_since": _unobserved_since}


def flush() -> None:
    """Write the cumulative counts to the file (tmp + os.replace). Nothing without `start`.
    Never raises; keeps the last write error."""
    global _flushed_at, _write_error
    p = _path
    if p is None:
        return
    with _write_lock:
        try:
            at = time.time()
            snap = snapshot()
            snap["flushed_at"] = at
            tmp = p.parent / (p.name + ".tmp")
            tmp.write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, p)
            _flushed_at, _write_error = at, None
        except Exception as exc:  # noqa: BLE001
            _write_error = f"{type(exc).__name__}: {exc}"[:200]


def _count(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 2 ** 63


def _time(x) -> bool:
    """An epoch-s / seconds number: finite (an int too large for a float is not, never an OverflowError)."""
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:
        return False


def _load(p: Path) -> None:
    """Fold the file back in; anything but a wholly valid v1 file leaves a fresh window (logged), never
    a part of one under its old started_at. Every check runs before any state changes, inside the try."""
    global _started_at, _boots, _folded, _unobserved_s, _unobserved_since
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("v") != SCHEMA:
            log.warning("of_call_stats_schema_mismatch path=%s; fresh window", p)
            return
        rows, started = raw.get("rows"), raw.get("started_at")
        bad = next((why for why, ok in (
            ("rows", isinstance(rows, list) and all(
                isinstance(r, list) and len(r) == 5 and all(isinstance(x, str) for x in r[:4]) and _count(r[4]) and r[4] > 0
                for r in rows)),
            ("started_at", _time(started) and started > 0),
            ("boots", _count(raw.get("boots"))), ("folded", _count(raw.get("folded")))) if not ok), None)
        if bad:
            log.warning("of_call_stats_bad_field path=%s field=%s; fresh window", p, bad)
            return
        now, fl = time.time(), raw.get("flushed_at")
        us, since = raw.get("unobserved_s"), raw.get("unobserved_since")
        gap = now - fl if _time(fl) else None
        tally = (us + gap, float(since)) if (_time(us) and us >= 0 and _time(since) and gap is not None
                                             and math.isfinite(gap) and gap >= 0) else None
        started = float(started)
    except FileNotFoundError:
        return
    except Exception as exc:  # noqa: BLE001 — a bad file never fails the boot
        log.warning("of_call_stats_unreadable path=%s %s: %s; fresh window", p, type(exc).__name__, str(exc)[:120])
        return
    if tally is None:
        log.warning("of_call_stats_unobserved_unknown path=%s; downtime tally restarts at this boot", p)
        tally = (0.0, now)
    with _lock:
        for r in rows:
            k = tuple(r[:4])
            _counts[k] = _counts.get(k, 0) + r[4]
        _folded += raw["folded"]
    _started_at, _boots = started, raw["boots"] + 1
    _unobserved_s, _unobserved_since = tally


def _flusher() -> None:
    while True:
        time.sleep(FLUSH_S)
        flush()


def start(path: Path | str | None) -> None:
    """The Relay's persistence, once per process: load `path`, write at once, then a daemon
    flush every FLUSH_S. None: memory only, no thread."""
    global _path
    if path is None or _path is not None:
        return
    _path = Path(path)
    _load(_path)
    flush()
    threading.Thread(target=_flusher, name="of-call-stats-flush", daemon=True).start()
